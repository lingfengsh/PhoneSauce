# -*- coding: utf-8 -*-
"""Praat F0 引擎包装（V2-E1）。

蓝本：refs/voicesauce-v137/func_PraatPitch.m（154 行）。
算法零重写——本模块只做「命令构造 + 输出解析 + 1ms 帧网格映射」，
真正的基频估计由 Praat 自带的 scripts/vs_praat/praatF0.praat 完成。

命令构造（蓝本 L41-47，Windows 分支）：
    Praat\\Praat.exe --run Praat\\praatF0.praat <wav> <frameshift> <minF0> <maxF0>
        <silthres> <voicethres> <octavecost> <octavejumpcost> <voiunvoicost>
        <killoctavejumps> <smooth> <smoothbw> <interpolate> <method>
    格式化：%s %.3f %.3f %.3f %.3f %.3f %.3f %.3f %d %d %.3f %d %s
    （2.0 差异：蓝本写死 `Praat\\Praat.exe` / `Praat\\praatF0.praat`，
      2.0 改为传入的 praat_exe 与 2.0 自带的脚本路径。
      2.0 不加双引号（subprocess 无 shell，引号会被当成路径的一部分）；
      2.0 加 `--FULL-TRUST`（Praat 7 视脚本写文件为危险动作）。）

输出解析（蓝本 L114-148）：
    .praatcc（method='cc'）/ .praatac（method='ac'）为无表头两列文本，
    列1=时间(秒)、列2=F0(Hz)，缺失值标记 `--undefined--`。
    映射到 1ms 帧网格：start=0, finish=t(end), increment=frameshift*1000，
    对每个网格点 k 取最近的时间点（容差 frameprecision*frameshift*1000）。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import os
import subprocess

import numpy as np

# 2.0 自带的 VS praat 脚本目录（本文件位于 backend/pysauce/engines/）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# engines -> pysauce -> backend -> ps-shell-v2
_PS_SHELL_V2 = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
_VS_PRAAT_DIR = os.path.join(_PS_SHELL_V2, "scripts", "vs_praat")
_PRAAT_F0_SCRIPT = os.path.join(_VS_PRAAT_DIR, "praatF0.praat")

# 蓝本 vs_Initialize.m L32：frame_precision 默认 1（可容忍偏离的帧数）
_DEFAULT_FRAME_PRECISION = 1


def _parse_praat_pitch_file(f0file, frameshift, datalen, frameprecision):
    """解析 .praatcc/.praatac → (f0, time) 均长度 datalen。

    严格按蓝本 L117-147 逐列解析：两列 %f %f，缺失标记 --undefined--。
    """
    times = []   # 秒
    values = []  # F0 Hz（缺失为 NaN）
    with open(f0file, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if line == "":
                continue
            parts = line.split()
            if len(parts) < 2:
                # 蓝本 textscan '%f %f' 遇列数不足的行会停止/补空；
                # 正常输出每行恰两列，此处跳过空行之外的异常行。
                continue

            def _to_float(tok):
                # textscan 的 TreatAsEmpty '--undefined--' → NaN
                if tok == "--undefined--":
                    return float("nan")
                return float(tok)

            times.append(_to_float(parts[0]))
            values.append(_to_float(parts[1]))

    t = np.rint(np.asarray(times, dtype=float) * 1000.0)  # 蓝本 L123 round(C{1}*1000)
    v = np.asarray(values, dtype=float)

    f0 = np.full(datalen, np.nan, dtype=float)
    time_ms = np.arange(datalen, dtype=float) * (frameshift * 1000.0)

    if t.size == 0:
        return f0, time_ms

    start = 0
    finish = float(t[-1])
    increment = frameshift * 1000.0

    k = float(start)
    # 蓝本 for k=start:increment:finish （闭区间）
    while k <= finish + 1e-9:
        # [val, inx] = min(abs(t - k)) —— 最近时间点（MATLAB min 取首个最小值）
        diffs = np.abs(t - k)
        inx = int(np.argmin(diffs))
        if diffs[inx] > frameprecision * frameshift * 1000.0:
            k += increment
            continue  # 蓝本 continue：无有效值

        # n = round(k/(frameshift*1000)) + 1（1-based）→ 0-based
        n1 = int(np.rint(k / (frameshift * 1000.0))) + 1
        if n1 < 1 or n1 > datalen:
            k += increment
            continue

        f0[n1 - 1] = v[inx]
        k += increment

    return f0, time_ms


def praat_pitch(wav_path: str, praat_exe: str, out_dir: str | None = None,
                time_step: float = 0.005, min_pitch: float = 40.0,
                max_pitch: float = 500.0, silence_th: float = 0.03,
                voicing_th: float = 0.45, octave_cost: float = 0.01,
                octave_jump_cost: float = 0.35, vuv_cost: float = 0.14,
                kill_octave_jumps: bool = False, smooth: bool = False,
                smooth_bw: float = 5.0, interpolate: bool = False,
                method: str = "cc") -> tuple[np.ndarray, np.ndarray]:
    """pF0：调 praatF0.praat → 解析 .praatcc/.praatac → (f0_1ms, time_1ms)。

    praat_exe: praat.exe 绝对路径（复用 1.2 settings 的 praatExe）。
    输出文件写到 out_dir（默认 wav 同目录，蓝本行为）。

    默认值来源 vs_Initialize.m L35-48：
        F0Praatmin=40, F0Praatmax=500, SilenceThreshold=0.03,
        VoiceThreshold=0.45, OctaveCost=0.01, OctaveJumpCost=0.35,
        VoicedUnvoicedCost=0.14, KillOctaveJumps=0, Smooth=0,
        SmoothingBandwidth=5, Interpolate=0, method='cc'。
    （卡片 §2 写 min_pitch=50.0，与蓝本不符——以蓝本 40 为准，见对照表。）

    time_step 语义与蓝本一致：它既是传给 praatF0.praat form 的 time_step，
    也是输出 1ms 网格的步长（蓝本 func_PraatPitch 用同一个 frameshift 实参
    同时承担这两个角色；VS 调用侧实传 frameshift/1000，默认 frameshift=1ms
    → 0.001）。本函数默认值沿用卡片签名 0.005，与蓝本调用侧 0.001 的差异
    已在对照表记录（§2 授权：签名形状禁改，默认值以蓝本为准；此处保留卡片
    默认 0.005 以便与 praatF0.praat form 默认自洽，VS 真实调用时由上层传
    frameshift/1000）。
    """
    if not os.path.isfile(praat_exe):
        raise RuntimeError(f"praat.exe 不存在：{praat_exe}")
    if not os.path.isfile(_PRAAT_F0_SCRIPT):
        raise RuntimeError(f"praatF0.praat 不存在：{_PRAAT_F0_SCRIPT}")

    wav_path = os.path.abspath(wav_path)
    if out_dir is None:
        out_dir = os.path.dirname(wav_path)
    os.makedirs(out_dir, exist_ok=True)

    method = str(method)
    ext = ".praatcc" if method == "cc" else ".praatac"
    f0file = wav_path + ext

    # 路径不加双引号：蓝本 L25-29 的加引号是为 MATLAB system() 走 shell 需要，
    # 2.0 用 subprocess 列表形式（无 shell），嵌入引号会被 Praat 当成路径的一部分
    # → 报 "Cannot open file"（Praat 7.0.02 实测）。见对照表「命令构造」节。
    # 另：Praat 7 视「脚本写文件」为危险动作，必须加 --FULL-TRUST（1.2 已知铁律）。
    # 参数顺序严格按 praatF0.praat form（14 个）
    cmd = [
        praat_exe, "--FULL-TRUST", "--run", _PRAAT_F0_SCRIPT,
        wav_path,
        f"{time_step:.3f}",
        f"{min_pitch:.3f}",
        f"{max_pitch:.3f}",
        f"{silence_th:.3f}",
        f"{voicing_th:.3f}",
        f"{octave_cost:.3f}",
        f"{octave_jump_cost:.3f}",
        f"{vuv_cost:.3f}",
        "1" if kill_octave_jumps else "0",   # 蓝本 %d，布尔 0/1
        "1" if smooth else "0",
        f"{smooth_bw:.3f}",
        "1" if interpolate else "0",
        method,                               # 蓝本 %s
    ]

    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0:
        # Praat 控制台输出为 UTF-16LE（1.2 已知）；此处只做摘要，不 print 原始 bytes。
        stderr = proc.stderr.decode("utf-16-le", errors="replace") if proc.stderr else ""
        stdout = proc.stdout.decode("utf-16-le", errors="replace") if proc.stdout else ""
        raise RuntimeError(
            f"praatF0.praat 退出码 {proc.returncode}\n"
            f"stdout: {stdout.strip()[:500]}\n"
            f"stderr: {stderr.strip()[:500]}"
        )

    if not os.path.isfile(f0file):
        raise RuntimeError(f"Praat 未生成输出文件：{f0file}")

    # datalen：网格点数（蓝本由调用侧传入 data_len；此处由音频时长推出）
    # 网格步长 = time_step（蓝本用同一个 frameshift 同时驱动脚本参数与网格）。
    import wave
    with wave.open(wav_path, "rb") as wf:
        nframes = wf.getnframes()
        framerate = wf.getframerate()
    duration = nframes / float(framerate)
    frameshift = time_step
    datalen = int(round(duration / frameshift)) + 1

    f0, time_ms = _parse_praat_pitch_file(
        f0file, frameshift, datalen, _DEFAULT_FRAME_PRECISION
    )

    return f0, time_ms
