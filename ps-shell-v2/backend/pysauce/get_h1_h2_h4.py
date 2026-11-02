# -*- coding: utf-8 -*-
"""func_GetH1_H2_H4.m → Python 复刻（整段分支）。

蓝本：refs/voicesauce-v137/func_GetH1_H2_H4.m（224 行，Yen-Liang Shue, UCLA SPAPL 2009）。
功能：H1/H2/H4 谐波幅度（dB）。每帧在 3 个基频周期的窗内，对 f_est±10% 频率窗
用有界优化器（fminsearchbnd）搜索**单点 DFT 幅度峰值**。

本卡只实现 `nargin==5` 的整段分支（蓝本 L26-69）：
  - TextGrid 分段分支（L71-162）不在本卡实现 —— 由 F1 编排层负责分段（v2 架构决定）。
  - handles / isComplete / stop-button 逻辑（L57-60）不实现（无 GUI）。

引用：Iseli & Alwan 的谐波幅度估计（配合 correct_iseli 的共振峰校正使用）。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

from . import matlang as M
from .fminsearchbnd import fminsearchbnd


def get_harmonics(data: np.ndarray, f_est: float, fs: float) -> tuple[float, float]:
    """[h, fh] = func_GetHarmonics(data, f_est, Fs)。"""
    data = np.asarray(data, dtype=np.float64)

    # MT-L176-177: df = 0.1; df_range = round(f_est*df)
    df = 0.1
    df_range = M.mround(f_est * df)

    # MT-L179-180: f_min = f_est - df_range; f_max = f_est + df_range
    f_min = f_est - df_range
    f_max = f_est + df_range

    # MT-L182: f = @(x) func_EstMaxVal(x, data, Fs)
    def est_max_val(x):
        # MT-L195-197: n = 0:length(data)-1; v = exp(-1i*2*pi*x*n/Fs)
        #              val = -1 * 20*log10(abs(data * v'))
        n = np.arange(len(data), dtype=np.float64)
        v = np.exp(-1j * 2 * np.pi * x * n / fs)
        return -1.0 * 20 * np.log10(abs(np.dot(data, np.conj(v))))

    # MT-L186: [x, val, exitflag, output] = fminsearchbnd(f, f_est, f_min, f_max, options)
    x, val = fminsearchbnd(est_max_val, float(f_est), float(f_min), float(f_max))

    # MT-L188-189: h = -1*val; fh = x
    h = -1.0 * val
    fh = x
    return h, fh


def get_h1_h2_h4(y: np.ndarray, fs: int, f0: np.ndarray,
                 n_periods: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """[H1, H2, H4] = func_GetH1_H2_H4(y, Fs, F0, ...)（整段分支）。"""
    y = np.asarray(y, dtype=np.float64)
    f0 = np.asarray(f0, dtype=np.float64)

    # MT-L17-18: N_periods = variables.Nperiods; sampleshift = Fs/1000*frameshift
    sampleshift = fs / 1000.0 * 1.0   # frameshift 默认 1 ms

    # MT-L20-22: H1/H2/H4 = zeros(length(F0),1)*NaN
    h1 = np.full(len(f0), np.nan, dtype=np.float64)
    h2 = np.full(len(f0), np.nan, dtype=np.float64)
    h4 = np.full(len(f0), np.nan, dtype=np.float64)

    # MT-L28: for k=1:length(F0)
    for k0 in range(1, len(f0) + 1):
        # MT-L30: ks = round(k*sampleshift)
        ks = int(M.mround(k0 * sampleshift))

        # MT-L32-34: if (ks<=0 || ks>length(y)) continue
        if ks <= 0 or ks > len(y):
            continue

        # MT-L36: F0_curr = F0(k)
        f0_curr = f0[k0 - 1]

        # MT-L38-40: if (isnan(F0_curr) || F0_curr == 0) continue
        if np.isnan(f0_curr) or f0_curr == 0:
            continue

        # MT-L42: N0_curr = 1/F0_curr*Fs
        n0_curr = 1.0 / f0_curr * fs

        # MT-L44-45: ystart = round(ks - N_periods/2*N0_curr); yend = round(ks + ...) - 1
        ystart = int(M.mround(ks - n_periods / 2.0 * n0_curr))
        yend = int(M.mround(ks + n_periods / 2.0 * n0_curr)) - 1

        # MT-L47-53: if (ystart<=0) continue; if (yend>length(y)) continue
        if ystart <= 0:
            continue
        if yend > len(y):
            continue

        # MT-L55: yseg = y(ystart:yend)'   （转置为行向量；一维数组无需）
        yseg = y[ystart - 1:yend]

        # MT-L57-60: stop-button 检查（无 GUI，不实现）

        # MT-L62-64: [h1,f0]=GetHarmonics(yseg,F0,Fs); [h2,~]=...(2*F0); [h4,~]=...(4*F0)
        hh1, _ = get_harmonics(yseg, float(f0_curr), fs)
        hh2, _ = get_harmonics(yseg, float(2 * f0_curr), fs)
        hh4, _ = get_harmonics(yseg, float(4 * f0_curr), fs)

        # MT-L66-68: H1(k)=h1; H2(k)=h2; H4(k)=h4
        h1[k0 - 1] = hh1
        h2[k0 - 1] = hh2
        h4[k0 - 1] = hh4

    return h1, h2, h4
