# -*- coding: utf-8 -*-
"""func_GetEnergy 复刻测试。锚点为解析解（推导见工程卡 V2-B1 §5），禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_energy import get_energy

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _sig(name):
    return framing.read_wav(os.path.join(FIX, name))


def test_sine100_constant_f0():
    y, fs = _sig("sine100.wav")
    f0 = np.full(1000, 100.0)          # 1 秒音频、1 ms 帧 → 1000 帧
    e = get_energy(y, f0, fs)
    assert e.shape == (1000,)
    mid = e[200:800]
    # 5 整周期 × 160 样本/周期，sum(sin^2)*0.25 = 0.125*800 = 100.0（解析精确）
    # 16bit 量化使 wav 实测 ≈ 99.9947（偏离 5.3e-3），故 atol 用 1e-2
    assert np.allclose(mid, 100.0, atol=1e-2)
    assert not np.isnan(mid).any()


def test_sine100_nan_pattern():
    y, fs = _sig("sine100.wav")
    f0 = np.full(1000, 100.0)
    e = get_energy(y, f0, fs)
    valid = np.nonzero(~np.isnan(e))[0]
    assert valid[0] == 25 and valid[-1] == 974   # 边缘 ±2.5 周期=±400 样本=±25 帧
    assert int(np.isnan(e).sum()) == 50


def test_sine100_nan_f0_propagates():
    y, fs = _sig("sine100.wav")
    f0 = np.full(1000, 100.0)
    f0[500] = np.nan
    e = get_energy(y, f0, fs)
    assert np.isnan(e[500])
    # 相邻帧仍有效且量级正确
    assert abs(e[499] - 100.0) < 3.0 and abs(e[501] - 100.0) < 3.0


def test_harm5_constant_f0():
    y, fs = _sig("harm5.wav")
    f0 = np.full(500, 200.0)
    e = get_energy(y, f0, fs)
    mid = e[150:350]
    # Parseval：mean(y^2)=Σ amp_k^2/2 = 0.3330078125/2；窗 5×80=400 样本 → 66.6015625
    # （幅度 [0.5,0.25,0.125,0.0625,0.03125]，见 V2-A2 卡 §11.5；量化后实测 66.5974）
    assert np.allclose(mid, 66.6015625, atol=0.5)


def test_silence_energy_zero():
    y, fs = _sig("silence.wav")
    f0 = np.full(500, 100.0)
    e = get_energy(y, f0, fs)
    mid = e[150:350]
    assert np.allclose(mid, 0.0, atol=1e-12)   # 零信号窗存在 → 0（不是 NaN）


def test_short_signal_all_nan():
    y, fs = _sig("sine100.wav")
    e = get_energy(y[:100], np.full(10, 100.0), fs)  # 信号 100 样本 < 窗 800 样本
    assert np.isnan(e).all()
