# -*- coding: utf-8 -*-
"""四个斜率校正函数 → 五个带 Iseli 校正的斜率对。

蓝本（均 UCLA SPAPL 2009/2014，Yen-Liang Shue）：
  - refs/voicesauce-v137/func_GetH1H2_H2H4.m        → get_h1h2_h2h4
  - refs/voicesauce-v137/func_GetH1A1_H1A2_H1A3.m   → get_h1a1_h1a2_h1a3
  - refs/voicesauce-v137/func_GetH42K.m             → get_h42k
  - refs/voicesauce-v137/func_Get2K5K.m             → get_2k5k

输出列名带 c 后缀：H1H2c/H2H4c/H1A1c/H1A2c/H1A3c/H42Kc/H2KH5Kc。

约定：参数均为 float64 一维向量（等长）；`b* = None` 对应蓝本 `nargin==N` 分支
→ 内部用 get_bw_fmt(fx, f0, 'hm') 现算（Hawks-Miller）。
校正项条数与顺序严格照蓝本（先 F1 后 F2 后 F3），浮点减法顺序影响末位，禁止重排。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

from .correct_iseli import correct_iseli_z
from .get_bw_fmt import get_bw_fmt


def get_h1h2_h2h4(h1, h2, h4, fs, f0, f1, f2, b1=None, b2=None):
    """[H1H2, H2H4] = func_GetH1H2_H2H4(...)。返回 (H1H2c, H2H4c)。"""
    # MT-L18-21: if (nargin==7) B1=getBWfromFMT(F1,F0,'hm'); B2=getBWfromFMT(F2,F0,'hm')
    if b1 is None:
        b1 = get_bw_fmt(f1, f0, "hm")
    if b2 is None:
        b2 = get_bw_fmt(f2, f0, "hm")

    # MT-L24-25: H1_corr = H1 - iseli(F0,F1,B1) - iseli(F0,F2,B2)
    h1_corr = h1 - correct_iseli_z(f0, f1, b1, fs)
    h1_corr = h1_corr - correct_iseli_z(f0, f2, b2, fs)
    # MT-L26-27: H2_corr = H2 - iseli(2*F0,F1,B1) - iseli(2*F0,F2,B2)
    h2_corr = h2 - correct_iseli_z(2 * f0, f1, b1, fs)
    h2_corr = h2_corr - correct_iseli_z(2 * f0, f2, b2, fs)
    # MT-L28-29: H4_corr = H4 - iseli(4*F0,F1,B1) - iseli(4*F0,F2,B2)
    h4_corr = h4 - correct_iseli_z(4 * f0, f1, b1, fs)
    h4_corr = h4_corr - correct_iseli_z(4 * f0, f2, b2, fs)

    # MT-L31-32: H1H2 = H1_corr - H2_corr; H2H4 = H2_corr - H4_corr
    h1h2 = h1_corr - h2_corr
    h2h4 = h2_corr - h4_corr
    return h1h2, h2h4


def get_h1a1_h1a2_h1a3(h1, a1, a2, a3, fs, f0, f1, f2, f3, b1=None, b2=None, b3=None):
    """[H1A1, H1A2, H1A3] = func_GetH1A1_H1A2_H1A3(...)。返回 (H1A1c, H1A2c, H1A3c)。"""
    # MT-L17-21: if (nargin==9) B1/B2/B3 = getBWfromFMT(Fx, F0, 'hm')
    if b1 is None:
        b1 = get_bw_fmt(f1, f0, "hm")
    if b2 is None:
        b2 = get_bw_fmt(f2, f0, "hm")
    if b3 is None:
        b3 = get_bw_fmt(f3, f0, "hm")

    # MT-L23-24: H1_corr = H1 - iseli(F0,F1,B1) - iseli(F0,F2,B2)
    h1_corr = h1 - correct_iseli_z(f0, f1, b1, fs)
    h1_corr = h1_corr - correct_iseli_z(f0, f2, b2, fs)
    # MT-L25: 蓝本注释行（F3 校正被禁用），不实现 —— 禁止真的减 F3。
    #         %H1_corr = H1_corr - func_correct_iseli_z(F0, F3, B3, Fs);

    # MT-L27-29: A3_corr 减三条（F1/F2/F3）
    a3_corr = a3 - correct_iseli_z(f3, f1, b1, fs)
    a3_corr = a3_corr - correct_iseli_z(f3, f2, b2, fs)
    a3_corr = a3_corr - correct_iseli_z(f3, f3, b3, fs)

    # MT-L31-32: A1_corr 减两条（F1/F2）
    a1_corr = a1 - correct_iseli_z(f1, f1, b1, fs)
    a1_corr = a1_corr - correct_iseli_z(f1, f2, b2, fs)

    # MT-L34-35: A2_corr 减两条（F1/F2）
    a2_corr = a2 - correct_iseli_z(f2, f1, b1, fs)
    a2_corr = a2_corr - correct_iseli_z(f2, f2, b2, fs)

    # MT-L37-39: H1A1 = H1_corr - A1_corr; H1A2 = H1_corr - A2_corr; H1A3 = H1_corr - A3_corr
    h1a1 = h1_corr - a1_corr
    h1a2 = h1_corr - a2_corr
    h1a3 = h1_corr - a3_corr
    return h1a1, h1a2, h1a3


def get_h42k(h4, h2k, f2k, fs, f0, f1, f2, f3, b1=None, b2=None, b3=None):
    """[H42K] = func_GetH42K(...)。返回 H42Kc。"""
    # MT-L18-22: if (nargin==8) B1/B2/B3 = getBWfromFMT(Fx, F0, 'hm')
    if b1 is None:
        b1 = get_bw_fmt(f1, f0, "hm")
    if b2 is None:
        b2 = get_bw_fmt(f2, f0, "hm")
    if b3 is None:
        b3 = get_bw_fmt(f3, f0, "hm")

    # MT-L25-26: H4_corr = H4 - iseli(4*F0,F1,B1) - iseli(4*F0,F2,B2)  （只两条，无 F3）
    h4_corr = h4 - correct_iseli_z(4 * f0, f1, b1, fs)
    h4_corr = h4_corr - correct_iseli_z(4 * f0, f2, b2, fs)
    # MT-L27-29: H2K_corr = H2K - iseli(F2K,F1,B1) - iseli(F2K,F2,B2) - iseli(F2K,F3,B3)  （三条）
    h2k_corr = h2k - correct_iseli_z(f2k, f1, b1, fs)
    h2k_corr = h2k_corr - correct_iseli_z(f2k, f2, b2, fs)
    h2k_corr = h2k_corr - correct_iseli_z(f2k, f3, b3, fs)

    # MT-L31: H42K = H4_corr - H2K_corr
    return h4_corr - h2k_corr


def get_2k5k(h2k, f2k, h5k, fs, f0, f1, f2, f3, b1=None, b2=None, b3=None):
    """[H2KH5K] = func_Get2K5K(...)。返回 H2KH5Kc。"""
    # MT-L18-22: if (nargin==8) B1/B2/B3 = getBWfromFMT(Fx, F0, 'hm')
    if b1 is None:
        b1 = get_bw_fmt(f1, f0, "hm")
    if b2 is None:
        b2 = get_bw_fmt(f2, f0, "hm")
    if b3 is None:
        b3 = get_bw_fmt(f3, f0, "hm")

    # MT-L24-26: H2K_corr = H2K - iseli(F2K,F1,B1) - iseli(F2K,F2,B2) - iseli(F2K,F3,B3)  （三条）
    h2k_corr = h2k - correct_iseli_z(f2k, f1, b1, fs)
    h2k_corr = h2k_corr - correct_iseli_z(f2k, f2, b2, fs)
    h2k_corr = h2k_corr - correct_iseli_z(f2k, f3, b3, fs)

    # MT-L28: H2KH5K = H2K_corr - H5K   （H5K 不校正——5K 无校正值，蓝本如此）
    return h2k_corr - h5k
