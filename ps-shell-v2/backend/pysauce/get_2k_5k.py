# -*- coding: utf-8 -*-
"""func_Get2K.m / func_Get5K.m → Python 复刻（整段分支）。

蓝本：refs/voicesauce-v137/func_Get2K.m（218 行）、func_Get5K.m（213 行），
均 Yen-Liang Shue, UCLA SPAPL 2014。
功能：2000 Hz / 5000 Hz 附近的谱峰幅度（dB）与峰频。

与 C1（H1/H2/H4）的三处关键差异：
  ① 目标频率**固定** 2000 / 5000 Hz（非 k·F0）；
  ② 搜索窗 df=**0.5**（非 C1 的 0.1）→ df_range = round(F0_curr*0.5)；
  ③ GetHarmonics 为 **4 参** `(data, f2_est, f0_est, Fs)`：f2_est 是搜索中心，
     f0_est **只用于算搜索半径** df_range（蓝本 L171 `df_range = round(f0_est*df)`），
     目标函数 EstMaxVal 与 C1 完全相同。

本卡只实现整段分支（蓝本 L26-66）；TextGrid 分段分支与 handles/isComplete 不实现。
F2K/F5K 输出 = 优化器返回的实际峰频 fh。

⚠ 蓝本偏差（见卡 §8）：蓝本 `func_Get5K` 签名 `[H5K, isComplete]` **只输出 H5K**，
`f5k` 计算后即丢弃；本实现按卡 §2 签名额外返回 F5K（超集，供输出列使用）。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

from . import matlang as M
from .fminsearchbnd import fminsearchbnd


def _get_harmonics_fixed(data: np.ndarray, f_est: float, f0_est: float,
                         fs: float) -> tuple[float, float]:
    """[h, fh] = func_GetHarmonics(data, f2_est, f0_est, Fs)（4 参变体）。

    f_est   = 目标中心频率（固定 2000 或 5000）
    f0_est  = 当前帧基频，仅用于搜索半径 df_range = round(f0_est * 0.5)
    """
    data = np.asarray(data, dtype=np.float64)

    # MT-L170-171: df = 0.5; df_range = round(f0_est*df)   ← f0_est 用于搜索半径
    df = 0.5
    df_range = M.mround(f0_est * df)

    # MT-L173-174: f_min = f2_est - df_range; f_max = f2_est + df_range
    f_min = f_est - df_range
    f_max = f_est + df_range

    # MT-L176: f = @(x) func_EstMaxVal(x, data, Fs)
    def est_max_val(x):
        # MT-L189-191: n = 0:length(data)-1; v = exp(-1i*2*pi*x*n/Fs)
        #              val = -1 * 20*log10(abs(data * v'))
        n = np.arange(len(data), dtype=np.float64)
        v = np.exp(-1j * 2 * np.pi * x * n / fs)
        return -1.0 * 20 * np.log10(abs(np.dot(data, np.conj(v))))

    # MT-L180: [x, val] = fminsearchbnd(f, f2_est, f_min, f_max, options)
    x, val = fminsearchbnd(est_max_val, float(f_est), float(f_min), float(f_max))

    # MT-L182-183: h = -1*val; fh = x
    return -1.0 * val, x


def _run_fixed(y: np.ndarray, fs: int, f0: np.ndarray, f_target: float,
               n_periods: int) -> tuple[np.ndarray, np.ndarray]:
    """2K/5K 共用帧循环（蓝本 Get2K L28-66 / Get5K L26-63）。"""
    y = np.asarray(y, dtype=np.float64)
    f0 = np.asarray(f0, dtype=np.float64)

    # MT-L19: sampleshift = Fs/1000*frameshift
    sampleshift = fs / 1000.0 * 1.0

    # MT-L21-22: H2K/F2K = zeros(length(F0),1)*NaN
    h = np.full(len(f0), np.nan, dtype=np.float64)
    fr = np.full(len(f0), np.nan, dtype=np.float64)

    for k0 in range(1, len(f0) + 1):
        # MT-L30: ks = round(k*sampleshift)
        ks = int(M.mround(k0 * sampleshift))

        # MT-L32-34: if (ks<=0 || ks>length(y)) continue
        if ks <= 0 or ks > len(y):
            continue

        # MT-L36-40: F0_curr=F0(k); if (isnan || ==0) continue
        f0_curr = f0[k0 - 1]
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

        # MT-L55: yseg = y(ystart:yend)'
        yseg = y[ystart - 1:yend]

        # MT-L62: [h2k, f2k] = func_GetHarmonics(yseg, 2000, F0_curr, Fs)
        hh, ff = _get_harmonics_fixed(yseg, f_target, float(f0_curr), fs)

        # MT-L64-65: H2K(k)=h2k; F2K(k)=f2k
        h[k0 - 1] = hh
        fr[k0 - 1] = ff

    return h, fr


def get_2k(y: np.ndarray, fs: int, f0: np.ndarray,
           n_periods: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """[H2K, F2K] = func_Get2K(y, Fs, F0, ...)（整段分支）。返回 (H2K, F2K) 两个 len(F0) 向量。"""
    return _run_fixed(y, fs, f0, 2000.0, n_periods)


def get_5k(y: np.ndarray, fs: int, f0: np.ndarray,
           n_periods: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """[H5K, F5K] = func_Get5K(y, Fs, F0, ...)（整段分支）。

    注：蓝本只输出 H5K（f5k 计算后丢弃）；F5K 为本实现按卡 §2 签名的扩展返回。
    """
    return _run_fixed(y, fs, f0, 5000.0, n_periods)
