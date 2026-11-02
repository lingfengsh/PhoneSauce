# -*- coding: utf-8 -*-
"""engine 编排（**蓝本口径**）回归测试 —— V2-F1 停报的补充件。

背景（卡 §5 脚注 / §8 停报）：
  卡 §5 的 `test_measure_reuse_roundtrip` 调 ``praat_objects.write_pitch_text``，
  该函数在 1.2 与 v2 中**都不存在**（`.Pitch` 由 Praat 自己写出）。
  按卡 §5 脚注「若签名与本测试不符，以 praat_objects.py 现状为准改测试的调用方式，
  但断言语义（复用值一致）不得改」→ 本文件用**符合蓝本**的写入方式
  （Praat ``Pitch 2`` 文本，即 engine 内部 `_write_praat_pitch` 同款格式）
  验证同一断言语义。

另含卡 §0b 要求的 `test_engine_object_suffix`（各引擎各落各文件、互不覆盖）。
"""
import os

import numpy as np

from backend.pysauce import engine
from backend.pysauce.output_cols import OUTPUT_COLS

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _req(**kw):
    req = dict(
        pitch_engine="praat", formant_engine="praat",
        do_h1h2h4=False, do_a1a2a3=False, do_2k5k=False, do_slopes=False,
        do_energy=False, do_cpp=False, do_hnr=False, do_shr=False, do_soe=False,
        wav_path=os.path.join(FIX, "harm5.wav"),
        praat_exe="", snack_exe=None,
        other_f0_file=None, other_fmt_file=None, out_dir=None,
    )
    req.update(kw)
    return req


# ── 卡 §0b 第 5 条：互通 roundtrip（蓝本写法）────────────────────────────
def test_measure_reuse_roundtrip_blueprint(tmp_path):
    """measure/ 已有 .Pitch（Praat 文本格式）→ reuse=True 直接复用，值来自该文件。"""
    mdir = str(tmp_path / "measure")
    os.makedirs(mdir, exist_ok=True)
    # 用 engine 内部同款 Praat Pitch 文本写法造文件（模拟 Praat 的 Save as text）
    engine._write_praat_pitch(os.path.join(mdir, "harm5.Pitch"),
                              [123.0, 123.0, 123.0], warn=[])
    res = engine.run_file(_req(reuse=True, measure_dir=mdir))
    vals = [x for x in (res.get("pF0") or []) if x is not None]
    assert vals, "reuse 后 pF0 应有值"
    assert abs(vals[0] - 123.0) < 1e-6
    assert any("复用" in w or "reuse" in w.lower() for w in res["_warnings"])


def test_measure_reuse_off_ignores_file(tmp_path):
    """reuse=False 时不读 measure/（praat_exe 空 → pF0 仍 None）。"""
    mdir = str(tmp_path / "measure")
    os.makedirs(mdir, exist_ok=True)
    engine._write_praat_pitch(os.path.join(mdir, "harm5.Pitch"),
                              [123.0, 123.0, 123.0], warn=[])
    res = engine.run_file(_req(reuse=False, measure_dir=mdir))
    assert res["pF0"] is None


# ── 卡 §0b 第 5 条：对象后缀各落各文件 ────────────────────────────────────
def test_engine_object_suffix(tmp_path):
    """非 Praat 引擎各落各文件、互不覆盖；且不写成 Praat 对象格式。"""
    from backend import review_export as re
    mdir = str(tmp_path / "measure")
    os.makedirs(mdir, exist_ok=True)
    base = "harm5"
    dx = 0.001

    # Snack F0 → .sF0
    engine._save_engine_object(mdir, base, "f0", "snack",
                               np.full(10, 200.0), 16000, [])
    # STRAIGHT F0 → .strF0
    engine._save_engine_object(mdir, base, "f0", "straight",
                               np.full(10, 210.0), 16000, [])
    # Snack Formant → .sFormant
    engine._save_engine_object(mdir, base, "formant", "snack",
                               [np.full(10, 500.0)] * 4, 16000, [])

    s_f0 = os.path.join(mdir, base + ".sF0")
    str_f0 = os.path.join(mdir, base + ".strF0")
    s_fmt = os.path.join(mdir, base + ".sFormant")
    assert os.path.isfile(s_f0)
    assert os.path.isfile(str_f0)
    assert os.path.isfile(s_fmt)
    # 后缀口径与 review_export.ENGINE_OBJECT_EXT 一致
    assert re.ENGINE_OBJECT_EXT["f0"]["snack"] == ".sF0"
    assert re.ENGINE_OBJECT_EXT["f0"]["straight"] == ".strF0"
    assert re.ENGINE_OBJECT_EXT["formant"]["snack"] == ".sFormant"
    # 三者互不覆盖：内容各含自己的引擎标记
    assert "engine=snack" in open(s_f0, encoding="utf-8").read()
    assert "engine=straight" in open(str_f0, encoding="utf-8").read()
    assert "engine=snack" in open(s_fmt, encoding="utf-8").read()
    # 绝不写 Praat 对象头
    for p in (s_f0, str_f0, s_fmt):
        assert '"Pitch 2"' not in open(p, encoding="utf-8").read()
        assert '"Formant 2"' not in open(p, encoding="utf-8").read()


# ── §0c：基准引擎切换 → 下游列不同 + _meta 记录 ──────────────────────────
def test_meta_records_algorithms():
    res = engine.run_file(_req(f0_algorithm="snack", fmt_algorithm="other"))
    assert res["_meta"]["f0_algorithm"] == "snack"
    assert res["_meta"]["fmt_algorithm"] == "other"


def test_missing_base_engine_gives_all_nan():
    """基准引擎列缺失 → 依赖它的测量列**全 NaN**（卡 §4.5，不自动回退）。"""
    res = engine.run_file(_req(praat_exe="", f0_algorithm="snack",
                               do_energy=True))
    assert isinstance(res["Energy"], list)
    assert len(res["Energy"]) == 500
    assert all(x != x for x in res["Energy"])       # 全 NaN
    assert any("基准 F0" in w for w in res["_warnings"])


# ── 结构：67 列 + 特殊键 ─────────────────────────────────────────────────
def test_result_has_all_cols():
    res = engine.run_file(_req())
    for c in OUTPUT_COLS:
        assert c in res
    assert "_meta" in res and "_warnings" in res


def test_batch_progress_cb():
    calls = []
    reqs = [_req(), _req()]
    out = engine.run_batch(reqs, progress_cb=lambda d, t: calls.append((d, t)))
    assert len(out) == 2
    assert calls == [(1, 2), (2, 2)]
