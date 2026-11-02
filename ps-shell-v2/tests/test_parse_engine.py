# -*- coding: utf-8 -*-
"""parse_f0 / parse_fmt 基准引擎选择测试（V2-F1 §6.2）。

照蓝本 `func_parseF0.m` / `func_parseFMT.m` **逐 case 覆盖**：
  • 五 F0 分支（praat/snack/straight/shr/other）+ 未知值返回空；
  • 三 FMT 分支（praat/snack/other）+ 未知值返回空；
  • **指定引擎不存在 → 空（不自动回退）**（蓝本核心语义）。
"""
import numpy as np

from backend.pysauce import parse_engine as pe


def _md(**kw):
    return dict(kw)


# ── parse_f0：五分支 ────────────────────────────────────────────────────
def test_parse_f0_all_five_branches():
    md = _md(strF0=np.array([1.0]), sF0=np.array([2.0]), pF0=np.array([3.0]),
             shrF0=np.array([4.0]), oF0=np.array([5.0]))
    assert pe.parse_f0(md, "straight")[0] == 1.0
    assert pe.parse_f0(md, "snack")[0] == 2.0
    assert pe.parse_f0(md, "praat")[0] == 3.0
    assert pe.parse_f0(md, "shr")[0] == 4.0
    assert pe.parse_f0(md, "other")[0] == 5.0


def test_parse_f0_unknown_returns_none():
    md = _md(pF0=np.array([3.0]))
    assert pe.parse_f0(md, "magic") is None
    assert pe.parse_f0(md, "") is None


def test_parse_f0_missing_field_returns_none_no_fallback():
    """核心语义：指定引擎列不存在 → 空，**不回退**到已存在的列。"""
    md = _md(pF0=np.array([3.0]))            # 只有 praat 列
    assert pe.parse_f0(md, "snack") is None  # 要 snack → 空，不拿 pF0 顶上
    assert pe.parse_f0(md, "straight") is None


def test_parse_f0_none_value_treated_as_missing():
    md = _md(sF0=None, pF0=np.array([3.0]))
    assert pe.parse_f0(md, "snack") is None


# ── parse_fmt：三分支 ───────────────────────────────────────────────────
def test_parse_fmt_all_three_branches():
    md = _md(sF1=np.array([1.0]), sF2=np.array([2.0]), sF3=np.array([3.0]),
             sB1=np.array([4.0]), sB2=np.array([5.0]), sB3=np.array([6.0]),
             pF1=np.array([11.0]), pF2=np.array([12.0]), pF3=np.array([13.0]),
             pB1=np.array([14.0]), pB2=np.array([15.0]), pB3=np.array([16.0]),
             oF1=np.array([21.0]), oF2=np.array([22.0]), oF3=np.array([23.0]),
             oB1=np.array([24.0]), oB2=np.array([25.0]), oB3=np.array([26.0]))
    for algo, base in (("snack", 1.0), ("praat", 11.0), ("other", 21.0)):
        F1, F2, F3, B1, B2, B3 = pe.parse_fmt(md, algo)
        assert F1[0] == base and F2[0] == base + 1 and F3[0] == base + 2
        assert B1[0] == base + 3 and B2[0] == base + 4 and B3[0] == base + 5


def test_parse_fmt_unknown_and_straight_return_all_none():
    md = _md(pF1=np.array([1.0]), pF2=np.array([2.0]), pF3=np.array([3.0]))
    assert pe.parse_fmt(md, "magic") == (None,) * 6
    assert pe.parse_fmt(md, "straight") == (None,) * 6   # STRAIGHT 不产共振峰


def test_parse_fmt_missing_returns_all_none_no_fallback():
    md = _md(pF1=np.array([1.0]), pF2=np.array([2.0]), pF3=np.array([3.0]))
    assert pe.parse_fmt(md, "snack") == (None,) * 6


def test_all_missing_helpers():
    md = _md(pF0=np.array([3.0]))
    assert pe.parse_f0_all_missing(md, "snack") is True
    assert pe.parse_f0_all_missing(md, "praat") is False
    assert pe.parse_fmt_all_missing(md, "praat") is True
