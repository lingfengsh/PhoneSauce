# -*- coding: utf-8 -*-
"""展示/导出取数口径回归（2026-10-27 用户实测 bug 的保护网）。

用户实测：VS 页用默认基准（F0=STRAIGHT、共振峰=Snack）跑完批量后点「参数展示」，
界面报「该目录还没有任何测量结果」。根因是 series_export 只认 Praat 的
.Pitch/.Formant 与写死的 out.tsv，认不出：
  - Snack/STRAIGHT 的对象后缀（.sF0/.sFormant/.strF0）
  - pysauce 按基准加前缀的汇总表（<f0>_<fmt>_out.tsv）
  - pysauce 汇总表的时间列叫 time（1.2 叫 t）、强度列叫 Energy（1.2 叫 intensity）

覆盖四种目录形态：
  A. 非 Praat 引擎（本次 bug）
  B. 旧 Praat 目录（不能回归）
  C. 两套对象并存 → 按 _results.json 的基准选
  D. 目录里没有任何结果 → 明确告警
"""
import json
import os

import numpy as np
import pytest

from backend import series_export as se
from backend.pysauce import engine


def _touch_wav(path):
    """内容无关：file_series 只用它做存在性/时长判断。"""
    with open(str(path), "wb") as fh:
        fh.write(b"RIFF")


def _simple_f0(path, vals):
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write("# engine=straight dim=f0\ntime\tf0\n")
        for i, v in enumerate(vals):
            fh.write("%.6f\t%s\n" % (i * 0.005, "--undefined--" if v is None else "%.4f" % v))


def _simple_fmt(path, f1s):
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write("# engine=snack dim=formant\ntime\tF1\tF2\tF3\tF4\tB1\tB2\tB3\tB4\n")
        for i, v in enumerate(f1s):
            fh.write("%.6f\t%s\t1200\t2500\t3500\t60\t80\t100\t120\n"
                     % (i * 0.005, "--undefined--" if v is None else "%.4f" % v))


def _praat_pitch(path, vals):
    engine._write_praat_pitch(str(path), np.array(vals, dtype=float), [])


def _praat_fmt(path, f1s):
    n = len(f1s)
    f = [np.array(f1s, dtype=float), np.full(n, 1200.0), np.full(n, 2500.0), np.full(n, 3500.0)]
    b = [np.full(n, 60.0), np.full(n, 80.0), np.full(n, 100.0), np.full(n, 120.0)]
    engine._write_praat_formant(str(path), f, b, [])


def _tsv(path, time_name, f0_col):
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write("\t".join(["file", time_name, "Energy", "CPP", f0_col]) + "\n")
        for i in range(5):
            fh.write("\t".join(["a.wav", "%.3f" % (i * 0.005), "%.3f" % (3.0 + i),
                                "%.3f" % (20.0 + i), "200.0"]) + "\n")


def _mark_run(dir_path, f0, fmt, out):
    with open(os.path.join(str(dir_path), "_results.json"), "w", encoding="utf-8") as fh:
        json.dump({"runs": [{"f0_algorithm": f0, "fmt_algorithm": fmt, "out": out,
                             "ts": "2026-10-27 21:12:52"}]}, fh)


@pytest.fixture()
def non_praat_dir(tmp_path):
    """A：VS 默认（STRAIGHT F0 + Snack 共振峰）的真实落盘形态。"""
    d = tmp_path / "A"
    (d / "measure").mkdir(parents=True)
    _touch_wav(d / "a.wav")
    _simple_f0(d / "measure" / "a.strF0", [None, 210.0, 220.0, None, 230.0])
    _simple_fmt(d / "measure" / "a.sFormant", [500.0, 510.0, None, 530.0, 540.0])
    _tsv(d / "straight_snack_out.tsv", "time", "strF0")
    _mark_run(d, "straight", "snack", "straight_snack_out.tsv")
    return d


def test_non_praat_objects_and_prefix_tsv_are_found(non_praat_dir):
    """旧实现的两个漏点：.strF0/.sFormant 被忽略、带前缀的汇总表找不到。"""
    d = str(non_praat_dir)
    av = se.series_available(d, values={"dir": d})
    assert av["ok"] and not av["warnings"]
    assert av["available"]["F0"] is True
    assert av["available"]["F1"] is True
    assert av["available"]["CPP"] is True
    # pysauce 强度列叫 Energy，导出列叫 intensity → 必须靠别名命中
    assert av["available"]["intensity"] is True
    assert av["run"] == {"f0": "straight", "fmt": "snack", "out": "straight_snack_out.tsv"}
    assert os.path.basename(av["tsvPath"]) == "straight_snack_out.tsv"


def test_non_praat_series_values(non_praat_dir):
    d = str(non_praat_dir)
    fs = se.file_series(d, "a.wav", params=["F0", "F1", "CPP", "intensity"], values={"dir": d})
    assert fs["ok"] and not fs["warnings"]
    assert [v for _t, v in fs["series"]["F0"] if v is not None] == [210.0, 220.0, 230.0]
    assert [v for _t, v in fs["series"]["F1"] if v is not None] == [500.0, 510.0, 530.0, 540.0]
    cpp = fs["series"]["CPP"]
    assert [v for _t, v in cpp if v is not None] == [20.0, 21.0, 22.0, 23.0, 24.0]
    # 时间轴必须来自 pysauce 的 time 列（旧实现找 t 列，全部落到 0.0）
    assert cpp[1][0] == pytest.approx(0.005)


def test_praat_dir_still_works(tmp_path):
    """B：1.2 老目录（.Pitch/.Formant + out.tsv，时间列叫 t）不能回归。"""
    d = tmp_path / "B"
    (d / "measure").mkdir(parents=True)
    _touch_wav(d / "a.wav")
    _praat_pitch(d / "measure" / "a.Pitch", [None, 110.0, 120.0, 130.0, 140.0])
    _praat_fmt(d / "measure" / "a.Formant", [700.0, 710.0, 720.0, 730.0, 740.0])
    _tsv(d / "out.tsv", "t", "f0")
    ds = str(d)
    av = se.series_available(ds, values={"dir": ds})
    assert av["available"]["F0"] is True and av["available"]["F1"] is True
    assert os.path.basename(av["tsvPath"]) == "out.tsv"
    fs = se.file_series(ds, "a.wav", params=["F0", "F1", "CPP"], values={"dir": ds})
    assert [v for _t, v in fs["series"]["F0"] if v is not None] == [110.0, 120.0, 130.0, 140.0]
    assert [v for _t, v in fs["series"]["F1"] if v is not None] == [700.0, 710.0, 720.0, 730.0, 740.0]
    assert fs["series"]["CPP"][1][0] == pytest.approx(0.005)


def test_engine_choice_follows_run_meta(tmp_path):
    """C：.Pitch 与 .strF0 并存 → 按 _results.json 的基准选，不被旧 Praat 残留带偏。"""
    d = tmp_path / "C"
    (d / "measure").mkdir(parents=True)
    _touch_wav(d / "a.wav")
    _praat_pitch(d / "measure" / "a.Pitch", [300.0] * 5)
    _simple_f0(d / "measure" / "a.strF0", [100.0] * 5)
    _tsv(d / "straight_snack_out.tsv", "time", "strF0")
    _mark_run(d, "straight", "snack", "straight_snack_out.tsv")
    ds = str(d)
    fs = se.file_series(ds, "a.wav", params=["F0"], values={"dir": ds})
    assert [v for _t, v in fs["series"]["F0"] if v is not None] == [100.0] * 5
    # 显式指定 praat 时改取 .Pitch（导出页/向导按自己基准取数）
    fs = se.file_series(ds, "a.wav", params=["F0"],
                        values={"dir": ds, "f0_algorithm": "praat"})
    assert [v for _t, v in fs["series"]["F0"] if v is not None] == [300.0] * 5


def test_empty_dir_warns(tmp_path):
    """D：确实没有结果时才告警（措辞不再写死 .Pitch/.Formant）。"""
    d = tmp_path / "D"
    d.mkdir()
    _touch_wav(d / "a.wav")
    ds = str(d)
    av = se.series_available(ds, values={"dir": ds})
    assert av["ok"] is True
    assert av["warnings"] and "out.tsv" in av["warnings"][0]
    assert not any(av["available"].values())
