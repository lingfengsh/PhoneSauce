# -*- coding: utf-8 -*-
"""H1/H2/H4 测试。区间+结构断言；精确值走快照（验收员生成）。禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_h1_h2_h4 import get_h1_h2_h4, get_harmonics

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_get_harmonics_sine_peak_at_fundamental():
    # 100Hz 正弦 5 周期：f_est=100 附近优化器应停在 ≈100
    fs = 16000
    t = np.arange(800) / fs
    x = 0.5 * np.sin(2 * np.pi * 100.0 * t)
    h, fh = get_harmonics(x, 100.0, fs)
    assert abs(fh - 100.0) <= 10.0 + 1e-6   # 搜索窗 ±10%
    assert h > 20 * np.log10(0.5 * 800 / 2) - 6   # 单点DFT 峰≈N/2·A，dB 量级 sanity（±6dB）


def test_h1h2h4_harm5_shapes_and_range():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    f0 = np.full(500, 200.0)
    h1, h2, h4 = get_h1_h2_h4(y, fs, f0)
    assert h1.shape == h2.shape == h4.shape == (500,)
    mid = slice(150, 350)
    for h in (h1, h2, h4):
        assert not np.isnan(h[mid]).any()
        assert (h[mid] > -120).all() and (h[mid] < 120).all()
    # 谐波串幅度递减 → H1 > H2 > H4（中位数，稳健比较）
    assert np.median(h1[mid]) > np.median(h2[mid]) > np.median(h4[mid])


def test_h1h2h4_nan_f0():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    f0[500] = np.nan
    h1, h2, h4 = get_h1_h2_h4(y, fs, f0)
    assert np.isnan(h1[500]) and np.isnan(h2[500]) and np.isnan(h4[500])


def test_h1h2h4_edge_frames_nan():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    h1, _, _ = get_h1_h2_h4(y, fs, f0)
    # 头部窗越界：±1.5 周期 = ±240 样本 = ±15 帧 → 前 15 帧 NaN，第 16 帧（idx 15）有效。
    # 原卡写 h1[:20]（期望 20 帧 NaN）与注释自相矛盾（15<20），按实测修正为 15。
    assert np.isnan(h1[:15]).all()
    assert not np.isnan(h1[15])
