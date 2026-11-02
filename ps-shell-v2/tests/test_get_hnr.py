# -*- coding: utf-8 -*-
"""HNR 测试。区间+相对关系断言；精确值走快照。禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_hnr import get_hnr

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_hnr_sine_higher_than_noise():
    y1, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    y2, _ = framing.read_wav(os.path.join(FIX, "noise10.wav"))
    f0 = np.full(1000, 100.0)
    hnr05_sine, _, _, _ = get_hnr(y1, fs, f0)
    hnr05_noise, _, _, _ = get_hnr(y2, fs, np.full(1000, 100.0))
    assert np.median(hnr05_sine[200:800]) > np.median(hnr05_noise[200:800])


def test_hnr_sine_positive_finite():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    hnr05, hnr15, hnr25, hnr35 = get_hnr(y, fs, np.full(1000, 100.0))
    for h in (hnr05, hnr15, hnr25, hnr35):
        mid = h[200:800]
        assert not np.isnan(mid).any()
        assert (mid > -10).all() and (mid < 70).all()


def test_hnr_cutoff_ordering_sine():
    # 纯周期信号：本算法 HNR = 20*mean(H[0:Ef]) - 20*mean(N[0:Ef])，DC bin 主导，
    # 截止越高 → 纳入均值越小 → HNR 越高（趋势性检查，允许个别帧反转）。
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    h05, h15, h25, h35 = get_hnr(y, fs, f0)
    assert np.median(h05[200:800]) <= np.median(h35[200:800]) + 3.0
    assert np.median(h05[200:800]) <= np.median(h15[200:800]) + 3.0
    assert np.median(h15[200:800]) <= np.median(h25[200:800]) + 3.0
    assert np.median(h25[200:800]) <= np.median(h35[200:800]) + 3.0


def test_hnr_lifter_mode_switch():
    # 忠实模式（默认）lifter 惰性；intended 模式 lifter 生效 → 数值不同（两者均有限）
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    h05_f, h15_f, h25_f, h35_f = get_hnr(y, fs, f0, lifter_mode="faithful")
    h05_i, h15_i, h25_i, h35_i = get_hnr(y, fs, f0, lifter_mode="intended")
    for h in (h05_f, h15_f, h25_f, h35_f, h05_i, h15_i, h25_i, h35_i):
        assert not np.isnan(h[200:800]).any()
    # 两模式在纯正弦上确有差异（faithful 的 HNR05 应更低）
    assert np.median(h05_f[200:800]) < np.median(h05_i[200:800])


def test_hnr_nan_f0_and_edges():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    f0[500] = np.nan
    h05, _, _, _ = get_hnr(y, fs, f0)
    assert np.isnan(h05[500])
    assert np.isnan(h05[:15]).all()
