# -*- coding: utf-8 -*-
"""A1A2A3 测试。禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_a1a2a3 import ana_get_magnitude_max, get_a1a2a3

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_magnitude_max_exact_bin():
    # 16000Hz 采样、fftlen=8192 → fstep=1.953125Hz。1600Hz 恰在 bin 819.2？
    # 取可整除情形：Fs=16384, fstep=2.0 → 1000Hz 恰在 bin 500
    t = np.arange(8192) / 16384.0
    x = np.sin(2 * np.pi * 1000.0 * t)
    m, fmax = ana_get_magnitude_max(x, np.array([1000.0]), 16384.0, 8192)
    assert abs(fmax[0] - 1000.0) < 4.0           # 峰 bin 命中 ±2 bin
    # 单频正弦峰 bin 幅度 = N/2 = 4096 → 20log10(4096) ≈ 72.25 dB
    assert abs(m[0] - 20 * np.log10(4096.0)) < 1.0


def test_magnitude_max_window_clamp():
    # Fx 很低 → lowf<0 钳 0；Fx 很高 → highf 钳 Fs/2-fstep
    t = np.arange(8192) / 16384.0
    x = np.sin(2 * np.pi * 1000.0 * t)
    m, fmax = ana_get_magnitude_max(x, np.array([50.0]), 16384.0, 8192)
    assert not np.isnan(m[0])                    # 钳位后正常取 max


def test_magnitude_max_nan_fx():
    m, fmax = ana_get_magnitude_max(np.ones(100), np.array([np.nan]), 16000.0, 8192)
    assert np.isnan(m[0]) and np.isnan(fmax[0])


def test_a1a2a3_harm5_with_true_formants():
    # harm5 有 200..1000Hz 五根谱线；设 F1=200,F2=400,F3=600 → A1>A2>A3（幅度递减谱）
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    f0 = np.full(500, 200.0)
    f1 = np.full(500, 200.0); f2 = np.full(500, 400.0); f3 = np.full(500, 600.0)
    a1, a2, a3 = get_a1a2a3(y, fs, f0, f1, f2, f3)
    mid = slice(150, 350)
    assert not np.isnan(a1[mid]).any()
    assert np.median(a1[mid]) > np.median(a2[mid]) > np.median(a3[mid])


def test_a1a2a3_nan_formant_keeps_nan():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    f0 = np.full(500, 200.0)
    f1 = np.full(500, 200.0); f2 = np.full(500, np.nan); f3 = np.full(500, 600.0)
    a1, a2, a3 = get_a1a2a3(y, fs, f0, f1, f2, f3)
    assert np.isnan(a1[300]) and np.isnan(a2[300]) and np.isnan(a3[300])


def test_a1a2a3_edges_nan():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    a1, _, _ = get_a1a2a3(y, fs, f0, np.full(1000, 500.0), np.full(1000, 1500.0),
                          np.full(1000, 2500.0))
    assert np.isnan(a1[:15]).all()
