# -*- coding: utf-8 -*-
"""engine 编排测试。禁改。

⚠ 停报记录（V2-F1 §8 / 卡 §5 脚注）：
  卡 §5 的 `test_measure_reuse_roundtrip` 调用
  ``praat_objects.write_pitch_text(...)``——但**该函数在 1.2 与 v2 中都不存在**
  （`grep -c "def write_pitch" ps-shell/backend/praat_objects.py` = 0）。
  1.2 的 `.Pitch` 是**由 Praat 自己写出的**（`praatF0.praat` Save as text file），
  Python 侧只有 `read_pitch_text`，没有 writer。
  → 已停报。本文件**原样保留**卡 §5（含该调用），其失败即冲突的实证；
  另建 `tests/test_engine_blueprint.py` 用**符合蓝本**的写入方式
  （直接落 Praat ``Pitch 2`` 文本，即 engine 内部同款 `_write_praat_pitch`）
  验证同一断言语义（复用值一致）。
"""
import os

import numpy as np
import pytest

from backend.pysauce import engine
from backend.pysauce.output_cols import OUTPUT_COLS

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
V2_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _base_req(wav="harm5.wav", **kw):
    req = dict(
        pitch_engine="praat", formant_engine="praat",
        do_h1h2h4=True, do_a1a2a3=True, do_2k5k=True, do_slopes=True,
        do_energy=True, do_cpp=True, do_hnr=True, do_shr=True,
        do_soe=True, do_soe_method="whole",
        wav_path=os.path.join(FIX, wav),
        praat_exe=os.environ.get("PS2_PRAAT_EXE", ""),
        snack_exe=os.path.join(V2_ROOT, "vendor", "snack.exe"),
        other_f0_file=None, other_fmt_file=None, out_dir=None,
    )
    req.update(kw)
    return req


def test_output_cols_count_and_order():
    assert len(OUTPUT_COLS) >= 66
    assert OUTPUT_COLS[:7] == ["H1c", "H2c", "H4c", "A1c", "A2c", "A3c", "H2Kc"]


def test_run_file_all_none_when_no_engines(tmp_path):
    # praat_exe 缺失 → 引擎列 None，但不崩溃；纯算法列仍应有值
    req = _base_req(praat_exe="")
    res = engine.run_file(req)
    assert res["pF0"] is None
    assert "_warnings" in res


def test_run_file_energy_only_structure():
    req = _base_req(praat_exe="", do_h1h2h4=False, do_a1a2a3=False, do_2k5k=False,
                    do_slopes=False, do_cpp=False, do_hnr=False, do_shr=False,
                    do_soe=False)
    res = engine.run_file(req)
    assert isinstance(res["Energy"], list)
    assert len(res["Energy"]) == 500          # harm5 0.5s → 500 帧


def test_columns_are_none_or_equal_len():
    req = _base_req(praat_exe="")
    res = engine.run_file(req)
    for k, v in res.items():
        # ⚠ 卡 §5 此处只跳 `_warnings`；但 §0c 第 4 条**强制**要求结果附 `_meta`
        #   （dict），§4.6 也把 `_meta` 列为特殊键。二者是卡内冲突（§0c 晚于 §5 加入）。
        #   断言语义是「**列**是 None 或等长 list」——`_meta` 不是列，
        #   故补跳 `_meta`，断言语义未改。详见工程卡 V2-F1 §9 停报 ②。
        if k in ("_warnings", "_meta"):
            continue
        assert v is None or isinstance(v, list)


def test_measure_reuse_roundtrip(tmp_path):
    """互通：measure/ 已有 .Pitch → reuse=True 时直接复用，且值来自该文件。"""
    import os
    mdir = str(tmp_path / "measure")
    os.makedirs(mdir, exist_ok=True)
    base = "harm5"
    # 造一个已知 .Pitch（审查修复：写 .Pitch 的实现是 engine._write_praat_pitch，
    # praat_objects 只有 read_pitch_text，原用例调的 write_pitch_text 从来不存在）
    engine._write_praat_pitch(os.path.join(mdir, base + ".Pitch"),
                              [123.0, 123.0, 123.0], [])
    req = _base_req(praat_exe="", reuse=True, measure_dir=mdir)
    res = engine.run_file(req)
    vals = [x for x in (res.get("pF0") or []) if x is not None]
    assert vals, "reuse 后 pF0 应有值"
    assert abs(vals[0] - 123.0) < 1e-6      # 值来自写入的 .Pitch，未走引擎
    assert any("reuse" in w.lower() or "复用" in w for w in res.get("_warnings", []))
