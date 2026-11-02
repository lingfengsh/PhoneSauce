# -*- coding: utf-8 -*-
"""2K/5K 测试。结构+区间断言；精确值走快照。禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_2k_5k import get_2k, get_5k

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _tone(freq, dur, amp=0.4, fs=16000):
    t = np.arange(int(dur * fs)) / fs
    return amp * np.sin(2 * np.pi * freq * t)


def test_2k_finds_tone_at_2000():
    fs = 16000
    y = _tone(2000.0, 0.5)
    f0 = np.full(500, 200.0)
    h2k, f2k = get_2k(y, fs, f0)
    mid = slice(150, 350)
    assert not np.isnan(h2k[mid]).any()
    assert (np.abs(f2k[mid] - 2000.0) <= 1000.0 + 1e-6).all()  # ±50% 窗
    assert (h2k[mid] > -120).all() and (h2k[mid] < 120).all()


def test_2k_quiet_at_wrong_freq():
    # 300Hz 正弦在 2000±50% 窗内无真实峰 → 幅度显著低于 2000Hz tone 情形
    fs = 16000
    y = _tone(300.0, 0.5)
    f0 = np.full(500, 200.0)
    h2k, _ = get_2k(y, fs, f0)
    y_ref = _tone(2000.0, 0.5)
    h2k_ref, _ = get_2k(y_ref, fs, np.full(500, 200.0))
    assert np.median(h2k[150:350]) < np.median(h2k_ref[150:350]) - 10.0


def test_5k_shapes_and_window():
    fs = 16000
    y = _tone(5000.0, 0.5)
    f0 = np.full(500, 200.0)
    h5k, f5k = get_5k(y, fs, f0)
    mid = slice(150, 350)
    assert h5k.shape == f5k.shape == (500,)
    assert not np.isnan(h5k[mid]).any()
    assert (np.abs(f5k[mid] - 5000.0) <= 2500.0 + 1e-6).all()


def test_nan_f0_and_edges():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    f0[500] = np.nan
    h2k, f2k = get_2k(y, fs, f0)
    assert np.isnan(h2k[500]) and np.isnan(f2k[500])
    assert np.isnan(h2k[:15]).all()
