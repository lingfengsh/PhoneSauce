# -*- coding: utf-8 -*-
"""SHR 测试。区间+结构断言；精确值走快照。禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.shrp import get_shrp, shrp

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_shrp_sine100_f0_correct():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    t, f0v, shr, nvoiced = shrp(y, fs)
    valid = ~np.isnan(f0v)
    assert valid.any()
    # F0 副产物应对数频率网格量化；100Hz 不在网格上，实测中位 94.53 → 容差 8
    assert abs(np.median(f0v[valid]) - 100.0) < 8.0     # F0 副产物应命中 100Hz 附近


def test_shr_sine_high_noise_low():
    y1, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    y2, _ = framing.read_wav(os.path.join(FIX, "noise10.wav"))
    _, _, s1, _ = shrp(y1, fs)
    _, _, s2, _ = shrp(y2, fs)
    v1 = s1[~np.isnan(s1)]
    v2 = s2[~np.isnan(s2)]
    assert v1.size and v2.size
    # 纯谐波信号（单峰候选）按蓝本 ComputeSHR 恒 SHR=0（favor harmonic）；
    # 噪声产生双峰候选 → SHR>0。故噪声 SHR 高于纯正弦。
    assert np.median(v2) > np.median(v1)


def test_shr_range():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    _, _, s, _ = shrp(y, fs)
    v = s[~np.isnan(s)]
    assert (v >= 0).all() and (v <= 1 + 1e-9).all()     # SHR 是 0..1 比值


def test_get_shrp_grid_alignment():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    f0 = np.full(500, 200.0)
    shr, shrf0 = get_shrp(y, fs, f0)
    assert shr.shape == (500,)                          # 映射到 1ms 帧网格
    assert shrf0.shape == (500,)


def test_get_shrp_nan_f0_frames():
    # func_GetSHRP 的网格映射只消费 shrp 自身产出的 f0_time/f0_value，
    # 输入 f0 仅提供 datalen（帧网格长度）；故输出长度恒 = len(f0)。
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    f0 = np.full(500, 200.0)
    f0[250] = np.nan
    shr, shrf0 = get_shrp(y, fs, f0)
    assert shr.shape == (500,)
    assert shrf0.shape == (500,)
    # 映射不读输入 f0 值，仅按 datalen 输出（与 f0 内容无关）
    assert np.count_nonzero(~np.isnan(shr)) > 0
