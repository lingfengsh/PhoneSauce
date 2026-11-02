# -*- coding: utf-8 -*-
"""斜率校正四函数测试。锚点脚本复算，禁改。"""
import numpy as np

from backend.pysauce.slopes import (
    get_2k5k,
    get_h1a1_h1a2_h1a3,
    get_h1h2_h2h4,
    get_h42k,
)

FS = 16000.0
N = 3
F0 = np.full(N, 100.0)
F1 = np.full(N, 500.0);  B1 = np.full(N, 100.0)
F2 = np.full(N, 1500.0); B2 = np.full(N, 120.0)
F3 = np.full(N, 2500.0); B3 = np.full(N, 140.0)
F2K = np.full(N, 2000.0)
H1 = np.full(N, -10.0); H2 = np.full(N, -15.0); H4 = np.full(N, -20.0)
A1 = np.full(N, -12.0); A2 = np.full(N, -18.0); A3 = np.full(N, -22.0)
H2K = np.full(N, -16.0); H5K = np.full(N, -25.0)


def test_h1h2_h2h4_explicit_bw():
    h1h2, h2h4 = get_h1h2_h2h4(H1, H2, H4, FS, F0, F1, F2, B1, B2)
    assert np.allclose(h1h2, [6.23943656] * N, atol=1e-7)
    assert np.allclose(h2h4, [12.0275403] * N, atol=1e-7)


def test_h1h2_h2h4_auto_bw():
    # b* 缺省 → Hawks-Miller 现算（F0=100：B1=34.35798774, B2=42.85085688）
    h1h2, _ = get_h1h2_h2h4(H1, H2, H4, FS, F0, F1, F2)
    assert np.allclose(h1h2, [6.27837285] * N, atol=1e-7)


def test_h1a1a2a3_explicit_bw():
    a, b, c = get_h1a1_h1a2_h1a3(H1, A1, A2, A3, FS, F0, F1, F2, F3, B1, B2, B3)
    assert np.allclose(a, [16.74440872] * N, atol=1e-7)
    assert np.allclose(b, [12.08577079] * N, atol=1e-7)
    assert np.allclose(c, [6.29635895] * N, atol=1e-7)


def test_h1a3_no_f3_correction_on_h1():
    # H1_corr 不减 F3 项（蓝本 L25 注释行）；构造 A3=F1 场景验证 A3_corr 含三条、H1_corr 含两条
    a3v = np.full(N, 500.0)  # A3 描写 F1 位置
    _, _, c = get_h1a1_h1a2_h1a3(H1, A1, A2, a3v, FS, F0, F1, F2, F3, B1, B2, B3)
    # 数值不手推，只验证 H1A3c == H1_corr - A3_corr 的可重构性（用 B3 函数重组）
    from backend.pysauce.correct_iseli import correct_iseli_z
    h1c = H1 - correct_iseli_z(F0, F1, B1, FS) - correct_iseli_z(F0, F2, B2, FS)
    a3c = a3v - (correct_iseli_z(F3, F1, B1, FS) + correct_iseli_z(F3, F2, B2, FS)
                 + correct_iseli_z(F3, F3, B3, FS))
    assert np.allclose(c, h1c - a3c, atol=1e-12)


def test_h42k_explicit_bw():
    out = get_h42k(H4, H2K, F2K, FS, F0, F1, F2, F3, B1, B2, B3)
    assert np.allclose(out, [-23.78621479] * N, atol=1e-7)


def test_2k5k_explicit_bw_and_h5k_uncorrected():
    out = get_2k5k(H2K, F2K, H5K, FS, F0, F1, F2, F3, B1, B2, B3)
    assert np.allclose(out, [20.134866] * N, atol=1e-7)


def test_nan_propagation():
    f0n = F0.copy(); f0n[1] = np.nan
    h1h2, _ = get_h1h2_h2h4(H1, H2, H4, FS, f0n, F1, F2, B1, B2)
    assert np.isnan(h1h2[1])
    assert np.allclose(h1h2[[0, 2]], [6.23943656] * 2, atol=1e-7)
