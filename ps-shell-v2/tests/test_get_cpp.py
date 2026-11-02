# -*- coding: utf-8 -*-
"""CPP 测试。区间+结构断言；精确值走快照。禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_cpp import get_cpp

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_cpp_sine100_positive_and_finite():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    cpp = get_cpp(y, fs, f0)
    mid = cpp[200:800]
    assert not np.isnan(mid).any()
    assert (mid > 0).all()          # 周期信号倒谱峰显著高于基线
    assert (mid < 60).all()         # 上限 sanity


def test_cpp_noise_lower_than_sine():
    y1, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    y2, _ = framing.read_wav(os.path.join(FIX, "noise10.wav"))
    cpp_sine = get_cpp(y1, fs, np.full(1000, 100.0))
    cpp_noise = get_cpp(y2, fs, np.full(1000, 120.0))
    assert np.median(cpp_sine[200:800]) > np.median(cpp_noise[200:800])


def test_cpp_silence_all_nan_or_nonegative():
    y, fs = framing.read_wav(os.path.join(FIX, "silence.wav"))
    cpp = get_cpp(y, fs, np.full(500, 100.0))
    # 全零信号 log(0) → 蓝本在 abs(Y)=0 处 log 产生 -Inf；不应崩溃
    assert np.isnan(cpp).all() or (cpp[~np.isnan(cpp)] <= 0).all()


def test_cpp_nan_f0():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    f0[500] = np.nan
    cpp = get_cpp(y, fs, f0)
    assert np.isnan(cpp[500])
