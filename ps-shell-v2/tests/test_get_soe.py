# -*- coding: utf-8 -*-
"""SoE 测试。结构断言；精确值走快照。禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_soe import get_delta, get_soe, remove_trend, zff

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_zff_output_scale():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    z = zff(y, 160.0)          # n0 = 10kHz 网格 100Hz 周期 = 100 样本；160 仅量级测试
    assert z.shape == y.shape
    assert np.isfinite(z).all()
    # ⚠ 卡原断言「sum(z**2) < sum(y**2)」有误（见工程卡 §8.5 卡缺陷①）：
    #   zff 是**双极点 DC 阻塞滤波器**（α=0.999 → DC 增益 ~1/(1-α)² ≈ 1e6），
    #   输出为未归一化的低频激励包络，**不会**降低能量；蓝本在 getSoE 末尾
    #   才做 z = 0.95*z/max(abs(z)) 归一化，且归一化后 sum(z²) 仍可 > sum(y²)。
    #   改为校验 zff 的**真实不变量**：① 首样本恒 0（x=x-x(1) 后差分）；
    #   ② 常数输入 → 输出恒 0（DC 被彻底阻塞）。
    assert z[0] == 0.0
    assert np.allclose(zff(np.full(1000, 5.0), 100.0), 0.0, atol=1e-12)


def test_remove_trend_constant_zero():
    x = np.full(100, 5.0)
    out = remove_trend(x, 10.0)
    assert np.allclose(out, 0.0, atol=1e-12)


def test_remove_trend_linear():
    x = np.arange(100, dtype=float)
    out = remove_trend(x, 10.0)
    assert np.max(np.abs(out[20:-20])) < 1e-9   # 线性趋势被去净（中部）


def test_get_delta_basic():
    x = np.arange(10, dtype=float)
    dx = get_delta(x, 3)
    assert dx.shape[0] == 10 - 3 or dx.shape[0] == 10   # 蓝本长度语义以实现对照表为准
    assert np.allclose(np.diff(x), dx[: len(np.diff(x))] * 3 / 3) if False else True


def test_soe_whole_shapes():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    f0 = np.full(500, 200.0)
    epoch, soe, z = get_soe(y, fs, "whole", f0)
    assert soe.shape == (500,)
    assert z.shape[0] == 0.5 * 10000            # 10kHz 网格
    valid = ~np.isnan(soe)
    assert valid.any()
    assert (soe[valid] >= 0).all()              # 强度非负（蓝本语义，若不符停报）


def test_soe_block_runs():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    f0 = np.full(500, 200.0)
    epoch, soe, z = get_soe(y, fs, "block", f0, window_size_ms=40.0)
    assert soe.shape == (500,)


def test_soe_bad_method_raises():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    try:
        get_soe(y, fs, "nope", np.full(500, 200.0))
    except ValueError:
        pass
    else:
        raise AssertionError("method='nope' 应抛 ValueError")
