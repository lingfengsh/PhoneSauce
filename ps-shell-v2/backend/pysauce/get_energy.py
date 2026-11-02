# -*- coding: utf-8 -*-
"""func_GetEnergy.m → Python 复刻。

蓝本：refs/voicesauce-v137/func_GetEnergy.m（50 行，Yen-Liang Shue, UCLA SPAPL 2009）。
语义：每个 1 ms 帧，以该帧的 F0 取 **5 个基频周期的变长窗**，输出窗内信号平方和
`sum(yseg.^2)`（**不是 RMS、不是 dB**）；窗越界或 F0 为 NaN 的帧输出 NaN。

翻译约定（见 V2-A3 卡 / 00-总纲 R1–R10）：
- MATLAB 1-based 索引 → 显式 k0 in range(1, len(f0)+1)（R2）
- round 用 matlang.mround（远离零，非银行家舍入）（R1）
- MATLAB 闭区间 y(ystart:yend) → Python 左闭右开 y[ystart-1:yend]（R2）
- 所有 continue 分支逐条保留，禁止合并（蓝本 L22/L28/L37/L41 四处）
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

from . import matlang as M


def get_energy(y: np.ndarray, f0: np.ndarray, fs: int,
               frameshift_ms: float = 1.0, n_periods_ec: int = 5) -> np.ndarray:
    """E = func_GetEnergy(y, F0, Fs, variables)。返回 len(f0) 的 float64 数组，无效帧为 NaN。"""
    y = np.asarray(y, dtype=np.float64)
    f0 = np.asarray(f0, dtype=np.float64)

    # MT-L15: sampleshift = (Fs / 1000 * variables.frameshift)
    sampleshift = fs / 1000.0 * frameshift_ms

    # MT-L17: E = zeros(length(F0), 1) * NaN
    e = np.full(len(f0), np.nan, dtype=np.float64)

    # MT-L19: for k=1:length(F0)  （k 是 1-based，R2）
    for k0 in range(1, len(f0) + 1):
        # MT-L20: ks = round(k * sampleshift)  （mround：MATLAB 远离零，R1）
        ks = int(M.mround(k0 * sampleshift))

        # MT-L22-24: if (ks <= 0 || ks > length(y)) continue
        if ks <= 0 or ks > len(y):
            continue

        # MT-L26: F0_curr = F0(k)
        f0_curr = f0[k0 - 1]

        # MT-L28-30: if (isnan(F0_curr)) continue
        # ⚠ 复刻修正：F0_curr==0（STRAIGHT 等引擎在未发声段会产出 0）会在 MT-L32
        #   算 N0_curr=Fs/0=Inf，随后 int(mround(...*Inf)) 在 Python 抛
        #   "cannot convert float infinity to integer"。MATLAB 原版因 ystart=-Inf≤0
        #   走 `if ystart<=0 continue` 静默跳过；这里显式拦截非有限/非正 F0，
        #   与 MATLAB 有效行为一致（未发声帧本就该跳过）。
        if not np.isfinite(f0_curr) or f0_curr <= 0:
            continue

        # MT-L32: N0_curr = Fs/F0_curr
        n0_curr = fs / f0_curr

        # MT-L34-35: ystart = round(ks - N_periods/2 * N0_curr)
        #            yend   = round(ks + N_periods/2 * N0_curr) - 1   （闭区间，含端点）
        ystart = int(M.mround(ks - n_periods_ec / 2.0 * n0_curr))
        yend = int(M.mround(ks + n_periods_ec / 2.0 * n0_curr)) - 1

        # MT-L37-39: if (ystart <= 0) continue
        if ystart <= 0:
            continue

        # MT-L41-43: if (yend > length(y)) continue
        if yend > len(y):
            continue

        # MT-L45: yseg = y(ystart:yend)  → 左闭右开 y[ystart-1:yend]（R2 核心）
        yseg = y[ystart - 1:yend]

        # MT-L47: E(k) = sum(yseg .^ 2)
        e[k0 - 1] = float(np.sum(yseg ** 2))

    return e
