# -*- coding: utf-8 -*-
"""数据入口：读 wav + 时间/样本换算。

pysauce 的约定：算法函数收 np.ndarray(float64, 1-D, ±1.0 标度) 与 fs(int)；
本模块负责把磁盘文件变成这个形态。VS 全局默认（vs_Initialize.m）：
  frameshift = 1 ms；Nperiods = 3（谐波类窗）；Nperiods_EC = 5（Energy/CPP/HNR 窗）
换算 helper 供各算法用；具体窗长由各算法按蓝本计算，本模块不预设。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import wave

import numpy as np

from . import matlang as M

VS_FRAMESHIFT_S = 0.001  # vs_Initialize.m L14: vars.frameshift = 1 (ms)
VS_NPERIODS = 3          # vs_Initialize.m L59
VS_NPERIODS_EC = 5       # vs_Initialize.m L60


def read_wav(path: str) -> tuple[np.ndarray, int]:
    """读 16/32bit PCM 或 32bit float wav → (x, fs)。x 为 float64 1-D，±1.0 标度。

    仅支持单声道（VS 同款约束；多声道时读第一声道并在调用方决定是否告警）。
    """
    with wave.open(path, "rb") as w:
        fs = int(w.getframerate())
        nch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    elif sw == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        x = (
            (b[:, 0].astype(np.int32))
            | (b[:, 1].astype(np.int32) << 8)
            | (b[:, 2].astype(np.int32) << 16)
        )
        x = np.where(x >= 1 << 23, x - (1 << 24), x).astype(np.float64) / float(1 << 23)
    else:
        raise ValueError(f"read_wav: 不支持的采样宽度 {sw} 字节（{path}）")
    if nch > 1:
        x = x[::nch]  # 取第一声道（MATLAB 同款：只处理第一列）
    return np.ascontiguousarray(x, dtype=np.float64), fs


def t2s(t_s: float, fs: int) -> int:
    """时间(秒) → 样本索引（0-based）。MATLAB `round(t*Fs)` 语义（0-based 换算由调用方完成）。

    用 mround 保证 round(-2.5)=-3 的 MATLAB 行为。
    """
    return int(M.mround(t_s * fs))


def s2t(n_samples: int, fs: int) -> float:
    """样本数 → 时长(秒)。"""
    return n_samples / float(fs)


def frame_times(dur_s: float, frameshift_s: float = VS_FRAMESHIFT_S) -> np.ndarray:
    """VS 输出帧时间基：从 0 起每 frameshift 一个时间戳，覆盖 [0, dur_s]。

    对应 MATLAB nframe = floor(dur/frameshift)+1 类逻辑（各算法蓝本一致）。
    """
    return M.mcolon(0.0, dur_s, frameshift_s)
