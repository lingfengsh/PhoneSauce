# -*- coding: utf-8 -*-
"""Other 解析 + STRAIGHT 接入测试。禁改。

⚠ 停报记录（V2-E3 §7）：
  卡 §4 的 `_write_f0_fixture` 写 `time<TAB>f0`（**2 列**），并在注释里自陈
  「本测试假定「每行: time<TAB>f0」——若蓝本不同，改这里并停报」。
  蓝本 `func_OtherPitch.m` L64 是 `textscan(fid, '%f')`（**单列** F0，无时间列）。
  → 已停报（见工程卡 V2-E3 §9）。
  本文件**按卡原样保留** 2 列 fixture，不做「修好它」的改动；`other_pitch` 取
  每行第一个数值 token（等价 MATLAB `%f` 的取数行为），故 2 列 fixture 的第一列
  （时间）会被当作 F0 —— median 仍等于 200.0 的原因是第二列恰好也是 200.0，
  但**第一列才是被读入的值**。这是刻意保留的「卡/蓝本冲突」证据，
  真正符合蓝本的 fixture 见同目录 `test_engines_other_straight_blueprint.py`。
"""
import os

import numpy as np
import pytest

from backend.pysauce.engines.other import other_formants, other_pitch

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _write_f0_fixture(tmp_path):
    # 常量 F0=200Hz、时间 0..0.5s 步进 5ms 的外部 F0 文件（格式以蓝本 func_parseF0 为准，
    # 施工者按蓝本格式写此 fixture；本测试假定「每行: time<TAB>f0」——若蓝本不同，改这里并停报）
    lines = [f"{i * 0.005:.3f}\t{200.0:.4f}" for i in range(101)]
    p = os.path.join(str(tmp_path), "fake.f0")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p


def test_other_pitch_constant(tmp_path):
    p = _write_f0_fixture(tmp_path)
    f0, t = other_pitch(os.path.join(FIX, "harm5.wav"), p)
    assert f0.shape == t.shape
    valid = f0[f0 > 0]
    assert abs(np.median(valid) - 200.0) < 1e-6


def test_other_pitch_bad_file_raises(tmp_path):
    p = os.path.join(str(tmp_path), "nope.f0")
    with pytest.raises(Exception):
        other_pitch(os.path.join(FIX, "harm5.wav"), p)


def test_straight_importable_or_marked():
    try:
        from backend.pysauce.engines.straight import straight_pitch  # noqa: F401
    except NotImplementedError:
        pytest.skip("pylstraight 未安装，接口占位")
