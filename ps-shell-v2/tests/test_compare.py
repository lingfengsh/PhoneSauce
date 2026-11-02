# -*- coding: utf-8 -*-
"""compare 纯函数测试（不起服务、不跑引擎）。禁改。"""
import os

import numpy as np

from backend.pysauce.compare import compare_files


def _write_tsv(path, cols, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(["file", "time"] + cols) + "\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")


def test_compare_aligns_and_stats(tmp_path):
    a = os.path.join(str(tmp_path), "a.tsv")
    b = os.path.join(str(tmp_path), "b.tsv")
    _write_tsv(a, ["Energy"], [["x.wav", 0.0, 10.0], ["x.wav", 0.001, 12.0]])
    _write_tsv(b, ["Energy"], [["x.wav", 0.0, 11.0], ["x.wav", 0.001, 10.0]])
    out = compare_files(a, b)
    col = out["per_column"][0]
    assert col["n_overlap"] == 2
    assert abs(col["mean_diff"] - (-0.5)) < 1e-9      # a-b 平均
    assert abs(col["max_abs_diff"] - 2.0) < 1e-9


def test_compare_missing_column_noted(tmp_path):
    a = os.path.join(str(tmp_path), "a.tsv")
    b = os.path.join(str(tmp_path), "b.tsv")
    _write_tsv(a, ["Energy"], [["x.wav", 0.0, 10.0]])
    _write_tsv(b, ["CPP"], [["x.wav", 0.0, 5.0]])
    out = compare_files(a, b)
    assert out["notes"]                                # 无交集列 → notes


# ── /api/compare 端点接线（不起真实 Praat，仅查分派与校验）──────────────
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import server  # noqa: E402


def test_validate_compare_requires_praat():
    """双跑对比需要 1.2 Praat 链 → Praat 缺失时 ok=False 且报 praatExe。"""
    chk = server.validate_compare({"inputDir": "", "pitch_engine": "praat"})
    # 无论 Praat 是否安装，validate_compare 结构必须是 4 键
    assert set(chk.keys()) == {"ok", "errors", "warnings", "fixed"}
    # 若本机无 Praat，应报 praatExe
    import backend.settings as _s
    exe = _s.resolve_praat_exe(_s.load())
    if not exe or not os.path.exists(exe):
        assert any(e["field"] == "praatExe" for e in chk["errors"])
        assert chk["ok"] is False


def test_compare_endpoint_registered():
    """server 模块暴露 start_compare_job / validate_compare / run_compare_job。"""
    assert hasattr(server, "start_compare_job")
    assert hasattr(server, "validate_compare")
    assert hasattr(server, "run_compare_job")
