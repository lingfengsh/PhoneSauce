# -*- coding: utf-8 -*-
"""func_getBWfromFMT.m → Python 复刻。

蓝本：refs/voicesauce-v137/func_getBWfromFMT.m（Yen-Liang Shue & Markus Iseli, UCLA SPAPL 2009）。
共振峰频率 → 带宽映射。两个公式：
  - Mannell 公式（默认）：BW = (80 + 120*FMT/5000) * (2 - voiced)，voiced 为 0/1
  - Hawks & Miller 公式（method='hm'）：多项式拟合 + F0 缩放

引用：Hawks, J. & Miller, J. "A formant bandwidth estimation procedure for vowel
synthesis," JASA, vol 97, no. 2, 1995.
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

# Hawks-Miller 系数（逐位照抄蓝本 L30-31，一个数字不许错）
_C1 = np.array([165.327516, -6.73636734e-1, 1.80874446e-3,
                -4.52201682e-6, 7.49514000e-9, -4.70219241e-12])
_C2 = np.array([15.8146139, 8.10159009e-2, -9.79728215e-5,
                5.28725064e-8, -1.07099364e-11, 7.91528509e-16])


def get_bw_fmt(fmt: np.ndarray, voiced_or_f0: "np.ndarray | float",
               method: str | None = None) -> np.ndarray:
    """BW = func_getBWfromFMT(FMT, voiced[, method])。

    method=None            → Mannell 公式：BW=(80+120*FMT/5000)*(2-voiced)，voiced 为 0/1
    method='hm'            → Hawks-Miller 公式，此时第二参数是 F0（可为标量或逐帧向量）
    """
    fmt = np.asarray(fmt, dtype=np.float64)

    # MT-L7-8: if (nargin==2) BW = (80 + 120*FMT/5000) * (2 - voiced)
    if method is None:
        return (80 + 120 * fmt / 5000.0) * (2 - voiced_or_f0)

    # MT-L10-12: elseif (nargin==3 && strcmp(method,'hm'))  F0=voiced; BW=getbw_HawksMiller(FMT,F0)'
    if method == "hm":
        f0 = voiced_or_f0
        # MT-L22-25: [r,c]=size(FMT); if r>c, FMT=FMT'  —— 仅行列向量归一，一维数组无需处理
        # MT-L27: S = 1+0.25*(F0-132)/88
        s = 1 + 0.25 * (np.asarray(f0, dtype=np.float64) - 132) / 88.0

        # MT-L33: F = [ones(1,length(FMT)); FMT; FMT.^2; FMT.^3; FMT.^4; FMT.^5]  → 6×N
        f_poly = np.vstack([np.ones_like(fmt), fmt, fmt ** 2,
                            fmt ** 3, fmt ** 4, fmt ** 5])
        # MT-L34-35: mask = FMT<500; mask = repmat(mask, length(C1), 1)
        mask = (fmt < 500).astype(np.float64)

        # MT-L37: BW = S' .* (C1*(F.*mask) + C2*(F.*~mask))
        #   注意是 **矩阵乘**（1×6 × 6×N），不是点乘；S 为向量时逐元素缩放。
        bw = s * (_C1 @ (f_poly * mask) + _C2 @ (f_poly * (1 - mask)))
        return bw

    # 蓝本此情形返回未定义变量 BW 会报错；Python 显式抛 ValueError。
    raise ValueError(f"get_bw_fmt: 未知 method={method!r}（应为 None 或 'hm'）")
