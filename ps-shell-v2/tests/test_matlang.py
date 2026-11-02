# -*- coding: utf-8 -*-
"""matlang/framing 语义单测。断言值均为 MATLAB 语义的权威值，禁改。"""
import os

import numpy as np
import pytest

from backend.pysauce import framing, matlang as M

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class TestMRound:
    def test_half_away_from_zero(self):
        assert M.mround(2.5) == 3.0
        assert M.mround(-2.5) == -3.0
        assert M.mround(0.5) == 1.0
        assert M.mround(-0.5) == -1.0
        assert M.mround(2.4) == 2.0
        assert M.mround(-2.4) == -2.0

    def test_array_and_nan(self):
        out = M.mround(np.array([-1.5, 1.5, 2.5, np.nan]))
        # MATLAB round 保留 NaN（round(NaN)=NaN，官方文档）；故第 4 元素为 NaN。
        # 原卡断言写成 == [-2.0, 2.0, 3.0]（3 元素）与其下一行 np.isnan(out[3]) 自相矛盾；
        # 按 MATLAB 语义（实现正确）修正为含 NaN 的 4 元素断言。
        assert out[:3].tolist() == [-2.0, 2.0, 3.0]
        assert np.isnan(out[3])


class TestMRem:
    def test_sign_follows_dividend(self):
        assert M.mrem(-3, 2) == -1.0          # Python % 会给 1
        assert M.mrem(3, -2) == 1.0
        assert M.mrem(5, 3) == 2.0
        assert np.isnan(M.mrem(1, 0))          # MATLAB rem(x,0)=NaN


class TestMColon:
    def test_basic(self):
        assert M.mcolon(1, 5).tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
        assert M.mcolon(0, 1, 0.25).tolist() == [0.0, 0.25, 0.5, 0.75, 1.0]

    def test_empty_and_reverse(self):
        assert M.mcolon(5, 1).size == 0
        assert M.mcolon(3, 1, -1).tolist() == [3.0, 2.0, 1.0]

    def test_float_endpoint_tolerance(self):
        # 0:0.1:0.3 的 MATLAB 结果以 0.3 结尾（补端点）
        out = M.mcolon(0.0, 0.3, 0.1)
        assert abs(out[-1] - 0.3) < 1e-12


class TestMFind:
    def test_basic_0based(self):
        x = np.array([0.0, 1.0, 0.0, 2.0])
        assert M.mfind(x > 0).tolist() == [1, 3]

    def test_empty(self):
        assert M.mfind(np.array([0, 0]) > 1).size == 0


class TestFrameify:
    def test_shape_and_content(self):
        x = np.arange(10, dtype=float)
        fr = M.frameify(x, win_len=4, shift=2)
        assert fr.shape == (4, 4)
        assert fr[0].tolist() == [0, 1, 2, 3]
        assert fr[3].tolist() == [6, 7, 8, 9]

    def test_too_short(self):
        assert M.frameify(np.arange(3, dtype=float), 4, 1).shape == (0, 4)


class TestInterp1:
    def test_linear_and_nan_outside(self):
        out = M.interp1([1.0, 3.0], [10.0, 30.0], np.array([1.0, 2.0, 3.0, 4.0]))
        assert out[0] == 10.0
        assert out[1] == 20.0
        assert out[2] == 30.0
        assert np.isnan(out[3])

    def test_descending_query(self):
        out = M.interp1([3.0, 1.0], [30.0, 10.0], np.array([2.0]))
        assert out[0] == 20.0


class TestFraming:
    def test_read_wav_sine100(self):
        x, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
        assert fs == 16000
        assert len(x) == 16000
        rms = float(np.sqrt(np.mean(x ** 2)))
        assert abs(rms - 0.5 / np.sqrt(2.0)) < 1e-3

    def test_frame_times(self):
        t = framing.frame_times(0.005)
        assert t[0] == 0.0
        assert len(t) == 6  # 0,1,2,3,4,5 ms
        assert abs(t[-1] - 0.005) < 1e-12

    def test_t2s_mround(self):
        assert framing.t2s(0.0015, 1000) == 2      # round(1.5)=2 远离零
        assert framing.t2s(0.0025, 1000) == 3      # round(2.5)=3
        assert framing.t2s(-0.0025, 1000) == -3
