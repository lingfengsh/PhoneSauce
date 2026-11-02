# -*- coding: utf-8 -*-
"""STRAIGHT 引擎（V2-E3）：pylstraight 接入。

# 数值口径：legacy-STRAIGHT（pylstraight，Apache-2.0）；非 VS TANDEM-STRAIGHT 等价
# ⚠️ 输出仅供对比参考，不得宣称与 VS（TANDEM-STRAIGHT / pcode）数值等价。

蓝本：
  refs/voicesauce-v137/func_StraightPitch.m（VS 调用的是 **TANDEM-STRAIGHT 编译产物**
  `straight_pcode`，非开源；v1.37 未随包分发该二进制）。

2.0 用 pip 包 **pylstraight 0.1.3**（Apache-2.0，legacy-STRAIGHT 的 Python 复现）
作为**近似**替代——这是工程卡 V2-E3 §3 明示的路径。

── 实测行为（2026-10-26，Python311 + pylstraight 0.1.3）────────────────────
`pylstraight.extract_f0(x, fs, frame_shift=1.0, f0_range=(40,500))` 在
**1 ms 帧移**下对平稳谐波信号（tests/fixtures/harm5.wav，200 Hz 五谐波）
返回**全 0**（即全部判为清音）；`frame_shift=5.0` 时正常返回 ≈200 Hz。
已定位到具体机制（非本包装的问题，属 pylstraight 上游在极小帧移下的行为）：

  `core/f0.py::zvuvdecision4` 用**平滑后**的功率谱峰位 `pv`（`zpeakdipdetect`
  内做 `wsml = round(81/shiftm)` 点 Hanning 平滑，1 ms → wsml=81，
  5 ms → wsml=16），但**门限比较用的是未平滑的 `pwsdb[pv]`**：

      if (1.2 * maxpwsdb + noiselevel) / 2.2 < pwsdb[pv[ii]] and lastp < pv[ii]:

  harm5 是平稳信号，1 ms 下 wsml=81 把峰值平滑掉 0.24 dB
  （smoothed max −8.085 vs raw max −7.842），于是
  `pwsdb[pv[ii]] ≈ −8.105 < 门限 −7.922` 对**全部 68 个峰**都不成立
  → `for ii in range(len(pv))` 循环体一次都不进入 → `vuv` 全 0
  → `extract_f0` 返回 `f0 * vuv = 0`。
  5 ms 下 wsml=16 几乎不压低峰值（差 0.000 dB），17 个峰全部过门限 → 正常。

因此本模块**默认 `frame_shift=5.0`**（pylstraight 自身默认值，也是实测可用值），
并把结果重采样到 VS 的 1 ms 网格。调用方若显式传 `frame_shift=1.0`，
本模块会照传（忠实接口），但**在检测到全 0 输出时抛出 RuntimeError 并附诊断**，
避免把「全清音」静默当成合法结果。

⚠ 与 VS 的差异（必须随输出一并披露）：
  • 算法不同：legacy-STRAIGHT ≠ TANDEM-STRAIGHT（VS pcode）。
  • 帧移不同：VS 的 straight 输出按 1 ms 网格（vs_Initialize.m frameshift=1）；
    pylstraight 在此环境下 1 ms 不可用（见上），故默认 5 ms 再线性插值到 1 ms。
  • F0 搜索范围：VS 的 straight 用 maxF0/minF0（500/40，vs_Initialize.m L20/L21）；
    本模块同值传入。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import os

import numpy as np

FRAMESHIFT_MS = 1.0          # VS 目标网格（vs_Initialize.m L14）
_DEFAULT_SHIFT_MS = 5.0      # pylstraight 实测可用帧移（其自身默认值）
_DEFAULT_F0_RANGE = (40.0, 500.0)   # vs_Initialize.m L20/L21


def _read_wav_mono(path: str) -> tuple[np.ndarray, int]:
    """读 wav → (float64 单声道波形 ∈ [-1,1], Fs)。

    与其它引擎保持一致：16-bit PCM → /32768；多声道取平均。
    """
    import wave

    with wave.open(path, "rb") as w:
        fs = w.getframerate()
        nch = w.getnchannels()
        sw = w.getsampwidth()
        n = w.getnframes()
        raw = w.readframes(n)

    if sw != 2:
        raise ValueError(f"仅支持 16-bit PCM（当前 sampwidth={sw}）：{path}")

    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1)
    return x, fs


def straight_pitch(wav_path: str, out_dir: str | None = None,
                   frame_shift: float = _DEFAULT_SHIFT_MS,
                   f0_range: tuple[float, float] = _DEFAULT_F0_RANGE,
                   ) -> tuple[np.ndarray, np.ndarray]:
    """strF0：pylstraight legacy-STRAIGHT F0 → (f0_1ms, time_1ms)。

    ⚠️ 数值口径：legacy-STRAIGHT 近似，与 VS pcode（TANDEM-STRAIGHT）非等价，
    输出仅供对比参考。

    Parameters
    ----------
    wav_path : str
        输入音频。
    out_dir : str | None
        预留（其它引擎用它落中间对象）。pylstraight 全内存计算，不使用此参数；
        保留以对齐三引擎统一签名。
    frame_shift : float
        pylstraight 的帧移（ms）。默认 5.0（见模块 docstring：1.0 在平稳谐波上
        会因 pylstraight 内部 V/UV 门限的平滑不一致而返回全 0）。
    f0_range : (float, float)
        F0 搜索上下界（Hz）。默认 (40, 500)，同 vs_Initialize.m L20/L21。

    Returns
    -------
    (f0_1ms, time_1ms) : tuple[np.ndarray, np.ndarray]
        长度 = ``floor(duration_s * 1000 / 1)``（VS 的 1 ms 网格，data_len）；
        pylstraight 的 ``frame_shift`` 网格结果线性插值到该网格。
        清音帧为 0.0（与 pylstraight 一致，不用 NaN）。

    Raises
    ------
    RuntimeError
        当 pylstraight 返回全 0（全清音）时——这在本环境意味着帧移选择触发了
        上游 V/UV 门限问题，必须显式报错而不是把「全清音」当结果。
    NotImplementedError
        pylstraight 未安装时（接口就绪、环境缺失）。
    """
    try:
        import pylstraight as pyls
    except ImportError as exc:  # pragma: no cover - 环境相关
        raise NotImplementedError(
            "pylstraight 未安装；请执行："
            "'C:/Users/Remi/AppData/Local/Programs/Python/Python311/python.exe' "
            "-m pip install pylstraight（Apache-2.0，legacy-STRAIGHT 近似）。"
            f"原始错误：{exc}"
        ) from exc

    x, fs = _read_wav_mono(wav_path)
    if x.size == 0:
        raise ValueError(f"空音频：{wav_path}")

    f0_ps = np.asarray(
        pyls.extract_f0(
            x, fs,
            frame_shift=float(frame_shift),
            f0_range=(float(f0_range[0]), float(f0_range[1])),
            f0_format="linear",
        ),
        dtype=float,
    )

    if f0_ps.size == 0 or not np.any(f0_ps > 0):
        raise RuntimeError(
            "pylstraight 返回全 0（全部判为清音）。本环境下 1 ms 帧移对平稳谐波"
            "信号会触发上游 V/UV 门限问题（详见模块 docstring 与工程卡 V2-E3 §9）；"
            f"当前 frame_shift={frame_shift}。建议使用默认 5.0。"
        )

    n = int(np.floor(x.size / fs * 1000.0 / FRAMESHIFT_MS))   # VS data_len
    t_ps = np.arange(f0_ps.size, dtype=float) * (float(frame_shift) / 1000.0)
    t_1ms = np.arange(n, dtype=float) * (FRAMESHIFT_MS / 1000.0)

    if f0_ps.size == 1:
        f0_1ms = np.full(n, f0_ps[0], dtype=float)
    else:
        f0_1ms = np.interp(t_1ms, t_ps, f0_ps, left=f0_ps[0], right=f0_ps[-1])

    return f0_1ms, t_1ms
