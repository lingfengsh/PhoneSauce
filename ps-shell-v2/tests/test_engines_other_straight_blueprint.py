# -*- coding: utf-8 -*-
"""Other 解析（**蓝本格式**）回归测试 —— V2-E3 停报的补充件。

背景（工程卡 V2-E3 §7 停报）：
  卡 §4 的 `_write_f0_fixture` 假定外部 F0 文件是 `time<TAB>f0`（2 列），
  但蓝本 `func_OtherPitch.m` L64 明确是 `textscan(fid, '%f')`（**单列** F0）。
  按卡 §7「格式细节与 `_write_f0_fixture` 假设不符时停报」→ 已停报。

本文件**不改卡 §4 的文件**，另建一份**符合蓝本**的 fixture 做真实验证：
  • `.f0`  → 单列 F0（func_OtherPitch.m L64 `'%f'`）
  • `.fmt` → 8 列 F1 F2 F3 F4 B1 B2 B3 B4（func_OtherFormants.m L65）
网格按蓝本 vs_ParameterEstimation.m L579 data_len = floor(len/Fs*1000/1)。
"""
import os

import numpy as np

from backend.pysauce.engines.other import other_formants, other_pitch

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _write_blueprint_f0(tmp_path, n=101, value=200.0):
    """蓝本格式：**单列** F0 值（每行一个数）。"""
    p = os.path.join(str(tmp_path), "bp.f0")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(f"{value:.4f}" for _ in range(n)) + "\n")
    return p


def test_blueprint_single_column_f0(tmp_path):
    """单列 F0 → 值原样落在 1 ms 网格头部，其余补 NaN。"""
    p = _write_blueprint_f0(tmp_path)
    f0, t = other_pitch(os.path.join(FIX, "harm5.wav"), p)
    # harm5 = 0.5 s @16k → data_len = floor(8000/16000*1000/1) = 500
    assert f0.shape == (500,)
    assert t.shape == (500,)
    assert t[0] == 0.0
    assert abs(t[1] - 0.001) < 1e-12
    # 前 101 帧 = 200.0，其余 NaN（蓝本 offset=0 + 尾部保持分配时的 NaN）
    assert np.allclose(f0[:101], 200.0)
    assert np.all(np.isnan(f0[101:]))


def test_blueprint_offset_zero_trim_long_file(tmp_path):
    """文件长于 data_len → 截断（蓝本 L816 else 分支）。"""
    p = _write_blueprint_f0(tmp_path, n=900, value=123.0)
    f0, t = other_pitch(os.path.join(FIX, "harm5.wav"), p)
    assert f0.shape == (500,)
    assert np.allclose(f0, 123.0)     # 全部被填满（900 > 500，取前 500）


def test_blueprint_eight_column_formants(tmp_path):
    """8 列共振峰 → F1..B4 八个向量。"""
    p = os.path.join(str(tmp_path), "bp.fmt")
    rows = []
    for i in range(101):
        rows.append(" ".join(f"{v:.2f}" for v in
                             (500.0 + i, 1500.0 + i, 2500.0 + i, 3500.0 + i,
                              50.0 + i, 60.0 + i, 70.0 + i, 80.0 + i)))
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")

    F1, F2, F3, F4, B1, B2, B3, B4 = other_formants(
        os.path.join(FIX, "harm5.wav"), p)
    for vec in (F1, F2, F3, F4, B1, B2, B3, B4):
        assert vec.shape == (500,)
    assert abs(F1[0] - 500.0) < 1e-9
    assert abs(F2[100] - 1600.0) < 1e-9
    assert abs(B4[100] - 180.0) < 1e-9
    assert np.all(np.isnan(F1[101:]))


def test_blueprint_f0_file_missing_raises(tmp_path):
    with np.testing.assert_raises(Exception):
        other_pitch(os.path.join(FIX, "harm5.wav"),
                    os.path.join(str(tmp_path), "absent.f0"))


def test_blueprint_fmt_column_short_raises(tmp_path):
    """列数 < 8 → 不宽容（卡 §6），解析为空 → raise。"""
    p = os.path.join(str(tmp_path), "short.fmt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("500.0 1500.0 2500.0\n")
    with np.testing.assert_raises(Exception):
        other_formants(os.path.join(FIX, "harm5.wav"), p)
