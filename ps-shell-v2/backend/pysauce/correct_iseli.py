# -*- coding: utf-8 -*-
"""func_correct_iseli_z.m → Python 复刻。

蓝本：refs/voicesauce-v137/func_correct_iseli_z.m（Markus Iseli, UCLA SPAPL 2003）。
Iseli & Alwan 共振峰逆滤波校正（dB 标量函数）。用于把谐波幅度扣除共振峰影响。

引用：Iseli, M. & Alwan, A. "An improved correction formula for the estimation of
harmonic magnitudes and its application to open quotient estimation," ICASSP 2004.

f 为待校正频率（数组）；Fx/Bx 为第 x 共振峰频率/带宽（标量或与 f 等长向量）。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np


def correct_iseli_z(f: np.ndarray, fx: "np.ndarray | float",
                    bx: "np.ndarray | float", fs: float) -> np.ndarray:
    """corr = func_correct_iseli_z(f, Fx, Bx, Fs)。

    f 必为数组；Fx/Bx 可为标量或与 f 等长向量（蓝本全向量化：B4 各斜率函数
    会把逐帧带宽向量 B1/B2/B3 直接传进来）。返回 dB 校正量，shape 同 f。
    """
    f = np.asarray(f, dtype=np.float64)
    fx = np.asarray(fx, dtype=np.float64)
    bx = np.asarray(bx, dtype=np.float64)

    # MT-L25: r = exp(-pi*Bx/Fs)
    r = np.exp(-np.pi * bx / fs)
    # MT-L26: omega_x = 2*pi*Fx/Fs
    omega_x = 2 * np.pi * fx / fs
    # MT-L27: omega = 2*pi*f/Fs
    omega = 2 * np.pi * f / fs

    # MT-L28: a = r.^2 + 1 - 2*r.*cos(omega_x + omega)
    a = r ** 2 + 1 - 2 * r * np.cos(omega_x + omega)
    # MT-L29: b = r.^2 + 1 - 2*r.*cos(omega_x - omega)
    b = r ** 2 + 1 - 2 * r * np.cos(omega_x - omega)

    # MT-L30: corr = -10*(log10(a)+log10(b));   % not normalized
    # MT-L23(卡注): 死代码，被 L33 覆盖 —— 不写入 Python（只保留最终式）。
    corr = -10 * (np.log10(a) + np.log10(b))

    # MT-L32: num = r.^2 + 1 - 2*r.*cos(omega_x);   % sqrt of numerator, omega=0
    num = r ** 2 + 1 - 2 * r * np.cos(omega_x)

    # MT-L33: corr = -10*(log10(a)+log10(b)) + 20*log10(num);   % normalized: H(z=0)=1
    corr = corr + 20 * np.log10(num)

    return corr
