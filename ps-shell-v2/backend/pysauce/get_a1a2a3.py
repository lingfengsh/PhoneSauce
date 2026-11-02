# -*- coding: utf-8 -*-
"""func_GetA1A2A3.m → Python 复刻（整段分支）。

蓝本：refs/voicesauce-v137/func_GetA1A2A3.m（190 行），Yen-Liang Shue, UCLA SPAPL 2009。
功能：F1/F2/F3 处的**未校正**谱幅度（dB）——3 周期窗内 8192 点 FFT（**不加窗**），
     在 Fx ±10% 频窗内取最大谱线。

与 C1/C2（H1/H2/H4、2K/5K）的关键区别：
  - **无优化器**；改用固定 8192 点 FFT 后取频窗内 max。
  - 目标频率 = 输入 F1/F2/F3（**不是** k·F0，也不是固定常数）。

本卡只实现整段分支（蓝本 L20-62）；TextGrid 分段分支（L63+）不实现。

⚠ 蓝本忠实点（详见卡 §3 与 §8）：
  ① L168 `X = fft(hamming(hamlen).*x(1:hamlen), fftlen)` **被注释** → 本实现**不加窗**，
     直接 `np.fft.fft(x, fftlen)`（hamlen 变量仅用于那条注释行，本实现不产生）。
  ② L170 `X(X==0)=1e-9` 作用在**复数谱**上（abs 之前）→ 必须保持同序，用复数判零。
  ③ L171 `X(1:fftlen/2)` → 0-based `[:fftlen//2]`（fftlen=8192 → 4096 个点）。
  ④ L178-180 索引换算见 §8 对照表（本卡 off-by-one 试金石）。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np


def ana_get_magnitude_max(x: np.ndarray, fx: np.ndarray | float, fs: float,
                          fftlen: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    """[M, fmax] = ana_GetMagnitudeMax(x, Fx, Fs, fftlen)。fx 可为标量或向量。返回 (M, fmax)。

    蓝本 L158-190。对每一点 Fx：在 Fx ±10% 频窗内取最大谱线幅度（dB）与其频点。
    """
    x = np.asarray(x, dtype=np.float64)
    fx_arr = np.atleast_1d(np.asarray(fx, dtype=np.float64))

    # MT-L160-162: if (isnan(Fx)) M=NaN; fmax=NaN
    m = np.full(fx_arr.shape, np.nan, dtype=np.float64)
    fmax = np.full(fx_arr.shape, np.nan, dtype=np.float64)

    # MT-L167-168: len = length(x); hamlen = min(fftlen, len);
    #              %X = fft(hamming(hamlen).*x(1:hamlen), fftlen);   ← 被注释 → 不加窗
    # MT-L169: X = fft(x, fftlen)
    x_spec = np.fft.fft(x, int(fftlen))

    # MT-L170: X(X==0) = 1e-9   ← 对**复数谱**判零（abs 之前），保持同序
    x_spec = np.where(x_spec == 0, 1e-9 + 0j, x_spec)

    # MT-L171: X = 20*log10(factor*abs(X(1:fftlen/2, :)))，factor=1
    # MATLAB 1:fftlen/2 含端点 → 0-based [:fftlen//2]（4096 点）
    mag = 20.0 * np.log10(np.abs(x_spec[: int(fftlen) // 2]))

    # MT-L172: fstep = Fs / fftlen
    fstep = fs / float(fftlen)

    for idx in range(fx_arr.size):
        fxc = fx_arr.flat[idx]
        if np.isnan(fxc):
            continue  # MT-L160-162：保持 NaN

        # MT-L173-176: lowf/highf 钳位
        lowf = fxc - 0.1 * fxc
        if lowf < 0:
            lowf = 0.0
        highf = fxc + 0.1 * fxc
        if highf > fs / 2.0 - fstep:
            highf = fs / 2.0 - fstep

        # MT-L178-180: MATLAB X(1+round(lowf/fstep) : 1+round(highf/fstep)) 闭区间
        #   → 0-based 起点 a = round(lowf/fstep)；终点 b = round(highf/fstep)
        #   → Python 切片 [a : b+1]（左闭右开，等价闭区间）
        a = int(round(lowf / fstep))
        b = int(round(highf / fstep))

        seg = mag[a: b + 1]
        pos = int(np.argmax(seg))            # 0-based 段内位置
        m.flat[idx] = float(seg[pos])
        # MT-L180: fmax = (pos-1 + round(lowf/fstep)) * fstep（pos 为 MATLAB 1-based）
        #   → 0-based: fmax = (pos0 + a) * fstep
        fmax.flat[idx] = (pos + a) * fstep

    return m, fmax


def get_a1a2a3(y: np.ndarray, fs: int, f0: np.ndarray, f1: np.ndarray,
               f2: np.ndarray, f3: np.ndarray,
               n_periods: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """[A1, A2, A3] = func_GetA1A2A3(y, Fs, F0, F1, F2, F3, ...)（整段分支）。

    返回 (A1, A2, A3) 三个 len(F0) 向量；F1/F2/F3 任一为 NaN 的帧保持 NaN。
    """
    y = np.asarray(y, dtype=np.float64)
    f0 = np.asarray(f0, dtype=np.float64)
    f1 = np.asarray(f1, dtype=np.float64)
    f2 = np.asarray(f2, dtype=np.float64)
    f3 = np.asarray(f3, dtype=np.float64)

    # MT-L18: sampleshift = Fs/1000*frameshift
    sampleshift = fs / 1000.0 * 1.0

    a1 = np.full(len(f0), np.nan, dtype=np.float64)
    a2 = np.full(len(f0), np.nan, dtype=np.float64)
    a3 = np.full(len(f0), np.nan, dtype=np.float64)

    for k0 in range(1, len(f0) + 1):
        # MT-L26: ks = round(k*sampleshift)
        ks = int(round(k0 * sampleshift))

        # MT-L28-30: if (ks<=0 || ks>length(y)) continue
        if ks <= 0 or ks > len(y):
            continue

        # MT-L32-36: F0_curr=F0(k); if (isnan || ==0) continue
        f0_curr = f0[k0 - 1]
        if np.isnan(f0_curr) or f0_curr == 0:
            continue

        # MT-L38: N0_curr = 1/F0_curr*Fs
        n0_curr = 1.0 / f0_curr * fs

        # MT-L40-41: ystart = round(ks - N_periods/2*N0_curr); yend = round(ks + ...) - 1
        ystart = int(round(ks - n_periods / 2.0 * n0_curr))
        yend = int(round(ks + n_periods / 2.0 * n0_curr)) - 1

        # MT-L43-49: if (ystart<=0) continue; if (yend>length(y)) continue
        if ystart <= 0:
            continue
        if yend > len(y):
            continue

        # MT-L51: yseg = y(ystart:yend)
        yseg = y[ystart - 1: yend]

        # MT-L54-56: if (~isnan(F1(k)) && ~isnan(F2(k)) && ~isnan(F3(k)) && ~isnan(N0_curr))
        f1k = f1[k0 - 1]
        f2k = f2[k0 - 1]
        f3k = f3[k0 - 1]
        if (not np.isnan(f1k) and not np.isnan(f2k) and not np.isnan(f3k)
                and not np.isnan(n0_curr)):
            # MT-L57-59: 三调 ana_GetMagnitudeMax(yseg, F1/F2/F3(k), Fs, 8192)
            a1_, _ = ana_get_magnitude_max(yseg, f1k, fs, 8192)
            a2_, _ = ana_get_magnitude_max(yseg, f2k, fs, 8192)
            a3_, _ = ana_get_magnitude_max(yseg, f3k, fs, 8192)

            # MT-L61-63: A1(k)=A1_; A2(k)=A2_; A3(k)=A3_
            a1[k0 - 1] = float(a1_[0])
            a2[k0 - 1] = float(a2_[0])
            a3[k0 - 1] = float(a3_[0])

    return a1, a2, a3
