# -*- coding: utf-8 -*-
"""Iseli 校正 + Hawks-Miller 带宽测试。锚点脚本复算，禁改。"""
import numpy as np

from backend.pysauce.correct_iseli import correct_iseli_z
from backend.pysauce.get_bw_fmt import get_bw_fmt


class TestIseli:
    def test_scalar_anchor(self):
        out = correct_iseli_z(np.array([100.0]), 500.0, 100.0, 16000.0)
        assert np.allclose(out, [0.34473226], atol=1e-8)

    def test_vector_anchor(self):
        out = correct_iseli_z(np.array([100.0, 200.0, 400.0]), 500.0, 100.0, 16000.0)
        assert np.allclose(out, [0.34473226, 1.46422165, 7.99579131], atol=1e-8)

    def test_f_equals_fx(self):
        out = correct_iseli_z(np.array([500.0]), 500.0, 100.0, 16000.0)
        assert np.allclose(out, [14.08295183], atol=1e-8)

    def test_nan_propagates(self):
        out = correct_iseli_z(np.array([100.0, np.nan]), 500.0, 100.0, 16000.0)
        assert np.isnan(out[1])

    def test_vector_fx_bx(self):
        # Fx/Bx 逐帧向量（B4 斜率函数的调用形态）：常量向量应与标量版逐位一致
        out_v = correct_iseli_z(
            np.array([100.0, 100.0]), np.array([500.0, 500.0]),
            np.array([100.0, 100.0]), 16000.0)
        out_s = correct_iseli_z(np.array([100.0, 100.0]), 500.0, 100.0, 16000.0)
        assert np.allclose(out_v, out_s, atol=1e-12)


class TestGetBwFmt:
    def test_mannell_voiced(self):
        bw = get_bw_fmt(np.array([500.0, 1000.0]), 1)
        assert np.allclose(bw, [92.0, 104.0], atol=1e-12)

    def test_mannell_unvoiced(self):
        bw = get_bw_fmt(np.array([500.0, 1000.0]), 0)
        assert np.allclose(bw, [184.0, 208.0], atol=1e-12)

    def test_hawks_miller_anchor(self):
        bw = get_bw_fmt(np.array([500.0, 1500.0, 2500.0, 3500.0]), 132.0, "hm")
        assert np.allclose(
            bw, [37.79378652, 47.13594257, 91.09795961, 174.67769864], atol=1e-7)

    def test_hawks_miller_f0_scaling(self):
        bw = get_bw_fmt(np.array([600.0]), 200.0, "hm")
        assert np.allclose(bw, [46.8299303], atol=1e-7)

    def test_hawks_miller_per_frame_f0(self):
        # F0 逐帧向量：500Hz 帧 F0=100、1500Hz 帧 F0=200 → S 分别缩放
        bw = get_bw_fmt(np.array([500.0, 1500.0]), np.array([100.0, 200.0]), "hm")
        s1 = 1 + 0.25 * (100.0 - 132) / 88
        s2 = 1 + 0.25 * (200.0 - 132) / 88
        base = get_bw_fmt(np.array([500.0, 1500.0]), 132.0, "hm")
        assert np.allclose(bw, [base[0] * s1, base[1] * s2], atol=1e-9)

    def test_bad_method_raises(self):
        try:
            get_bw_fmt(np.array([500.0]), 1, "xx")
        except ValueError:
            pass
        else:
            raise AssertionError("method='xx' 应抛 ValueError")
