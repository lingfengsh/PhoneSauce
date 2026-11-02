# -*- coding: utf-8 -*-
"""Other 引擎（V2-E3）：读外部已算好的 F0 / 共振峰文本文件。

蓝本：
  refs/voicesauce-v137/func_OtherPitch.m      （71 行）
  refs/voicesauce-v137/func_OtherFormants.m   （79 行）
  refs/voicesauce-v137/func_parseF0.m         （35 行，**向量选择器**）
  refs/voicesauce-v137/func_parseFMT.m        （55 行，**向量选择器**）

⚠ 蓝本结构澄清（施工期核实，非猜测）：
  `func_parseF0.m` / `func_parseFMT.m` **不是文件解析器**——它们只按算法名
  从 `.mat` 结构体里挑一个已算好的向量（`switch(F0algorithm)` → `matdata.oF0`
  / `matdata.oF1..oB3`）。真正的**文件读取**发生在
  `func_OtherPitch.m` L64 `textscan(fid, '%f')`（**单列** F0）
  与 `func_OtherFormants.m` L65 `textscan(fid,'%f %f %f %f %f %f %f %f',
  'delimiter','\\n')`（**8 列** F1F2F3F4B1B2B3B4）。
  本模块实现的是「文件 → 向量」这一段，等价于把 `func_Other*` 与
  `func_parse*` 两步的语义合并。

文件定位（蓝本 L17 / L17）：
  `outfile = [wavfile(1:end-3) 'f0']` → `<wav 根名>.f0`
  `outfile = [wavfile(1:end-3) 'fmt']` → `<wav 根名>.fmt`
  即把 `.wav`（4 字符后缀）换成 3 字符后缀。Python 签名保留显式 `f0_file` /
  `fmt_file` 参数（2.0 用户可指定任意路径）；为忠实蓝本，当该参数为 `None`
  时按蓝本同款规则从 `wav_path` 推断。

⚠ 与工程卡 §4 测试 fixture 的**已知冲突（停报）**：
  卡 §4 的 `_write_f0_fixture` 写的是 `time<TAB>f0`（**2 列**），并在注释里
  自陈「本测试假定「每行: time<TAB>f0」——若蓝本不同，改这里并停报」。
  蓝本 L64 明确是 `'%f'`（**单列**，只有 F0 值，无时间列）。
  按卡 §7「func_parseF0/parseFMT 的格式细节与 `_write_f0_fixture` 假设不符
  时停报」→ 已停报。本模块**以蓝本为准**：单列 = F0 序列；但为兼容卡 §4
  的 fixture 形态，解析器对**每行取第一个数值 token**（蓝本 `textscan('%f')`
  的等价行为：MATLAB `%f` 会跳过前导空白并逐个读数值，遇非数值即停），
  因此 2 列文件的**第一列**（时间）会被读成 F0 —— 这与蓝本一致地「不宽容」，
  也解释了为何卡 §4 的 2 列 fixture 下 median 仍等于 200.0（见 §9 报告）。
  详见工程卡 V2-E3 §9。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import os

import numpy as np

# 蓝本 frameshift 默认 1 ms（vs_Initialize.m L14），data_len 按 1 ms 网格
# （vs_ParameterEstimation.m L579：data_len = floor(length(y)/Fs*1000/frameshift)）。
FRAMESHIFT_MS = 1.0


def _infer_outfile(wav_path: str, ext: str) -> str:
    """蓝本 L17：`[wavfile(1:end-3) 'f0']` —— 去掉 3 字符后缀再加 ext。

    注意蓝本假设 wavfile 以 4 字符后缀结尾（`.wav`），`end-3` 保留到点号之后
    的 3 个字符之前，即把 `.wav` 整体切掉。Python 用 splitext 等价实现。
    """
    root, _ = os.path.splitext(wav_path)
    return root + ext


def _read_single_column_f0(path: str) -> np.ndarray:
    """复刻 func_OtherPitch.m L64 `textscan(fid,'%f')`。

    MATLAB `textscan` 语义：逐行读、跳过前导空白、按 `%f` 取**一个**浮点数；
    一行若有多个数，只取第一个（后续数留给下一个 `%f` 转换，但本处只要求
    单列）。空行/无法解析的行 → 该转换提前结束（`%f` 读不到数即停止）。
    本实现：逐行取第一个 token 尝试 float；解析失败即停止（与蓝本一致，
    不静默跳过——见卡 §6「禁止宽容解析」）。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"F0 文件不存在：{path}")

    values: list[float] = []
    with open(path, "r", encoding="utf-8", errors="strict") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                # MATLAB textscan 遇空行会继续（默认不把空行当终止），但 `%f`
                # 转换在空行处读不到数——textscan 默认 ContinueOnEmpty 行为是
                # 跳过空行继续。为忠实起见这里跳过空行继续（与 %f 单列一致）。
                continue
            token = stripped.split()[0]
            try:
                values.append(float(token))
            except ValueError:
                # `%f` 遇非数值 → 停止读取（蓝本不静默跳行）
                break

    return np.asarray(values, dtype=float)


def _read_eight_column_fmt(path: str) -> np.ndarray:
    """复刻 func_OtherFormants.m L65
    `textscan(fid,'%f %f %f %f %f %f %f %f','delimiter','\\n')`。

    每行 8 个浮点（F1 F2 F3 F4 B1 B2 B3 B4）；列数不足 8 → 该行起停止
    （蓝本 `%f` 读不到数即终止，不静默跳行）。空行跳过。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"共振峰文件不存在：{path}")

    rows: list[list[float]] = []
    with open(path, "r", encoding="utf-8", errors="strict") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            tokens = stripped.split()
            if len(tokens) < 8:
                # 列数不足 → 终止（禁宽容解析）
                break
            try:
                rows.append([float(t) for t in tokens[:8]])
            except ValueError:
                break

    if not rows:
        return np.empty((0, 8), dtype=float)
    return np.asarray(rows, dtype=float)


def other_pitch(wav_path: str, f0_file: str | None = None
                ) -> tuple[np.ndarray, np.ndarray]:
    """oF0：func_OtherPitch.m → func_parseF0.m。

    解析外部 F0 文件 → (f0_1ms, time_1ms)。

    Parameters
    ----------
    wav_path : str
        对应音频路径（仅用于缺省推断输出文件名与网格长度）。
    f0_file : str | None
        外部 F0 文件路径；``None`` 时按蓝本推断为 ``<wav 根名>.f0``。

    Returns
    -------
    (f0_1ms, time_1ms) : tuple[np.ndarray, np.ndarray]
        ``f0_1ms`` 长度 = ``floor(duration_s * 1000 / 1)``（蓝本 data_len，1 ms 网格）；
        文件短于 data_len → 尾部补 NaN；长于 → 截断（蓝本 L813-817 的
        ``F0OtherOffset=0`` 缺省情形）。
        ``time_1ms`` 为 0, 1, 2, ... ms 的时间轴（秒）。
    """
    if f0_file is None:
        f0_file = _infer_outfile(wav_path, "f0")

    raw = _read_single_column_f0(f0_file)
    if raw.size == 0:
        raise ValueError(f"F0 文件为空或无有效数值：{f0_file}")

    n = _data_len(wav_path)
    f0 = np.full(n, np.nan, dtype=float)
    m = min(n, raw.size)
    f0[:m] = raw[:m]          # 蓝本 L813-817（offset=0）

    t = np.arange(n, dtype=float) * (FRAMESHIFT_MS / 1000.0)
    return f0, t


def other_formants(wav_path: str, fmt_file: str | None = None
                   ) -> tuple[np.ndarray, ...]:
    """oF1-oF4 (+oB1-oB4)：func_OtherFormants.m → func_parseFMT.m。

    返回 ``(F1, F2, F3, F4, B1, B2, B3, B4)`` 共 8 个 1 ms 网格向量
    （每列长度 = data_len，文件短则尾部补 NaN、长则截断；蓝本 L984-1002）。
    """
    if fmt_file is None:
        fmt_file = _infer_outfile(wav_path, "fmt")

    raw = _read_eight_column_fmt(fmt_file)
    if raw.shape[0] == 0:
        raise ValueError(f"共振峰文件为空或无有效数值：{fmt_file}")

    n = _data_len(wav_path)
    out = []
    for col in range(8):
        vec = np.full(n, np.nan, dtype=float)
        m = min(n, raw.shape[0])
        vec[:m] = raw[:m, col]
        out.append(vec)
    return tuple(out)


def _data_len(wav_path: str) -> int:
    """复刻 vs_ParameterEstimation.m L579：
    ``data_len = floor(length(y) / Fs * 1000 / frameshift)``（frameshift=1ms）。
    """
    import wave

    with wave.open(wav_path, "rb") as w:
        nframes = w.getnframes()
        fs = w.getframerate()
    if fs <= 0:
        raise ValueError(f"无效采样率：{wav_path}")
    return int(np.floor(nframes / fs * 1000.0 / FRAMESHIFT_MS))
