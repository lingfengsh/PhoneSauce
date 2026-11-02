# -*- coding: utf-8 -*-
"""server engine 路由测试（V2-F2）。禁改。

覆盖：
  1) `_values_to_engine_request` 的 values→EngineRequest 映射——13 个开关全覆盖；
  2) `/api/validate` 与 `/api/run` 的 engine 分派（起真实服务 + bootstrap token）。
"""
import json
import os
import sys
import http.cookiejar
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import server  # noqa: E402


# ─────────────────────────────────────────────────────────── 映射单测
def test_map_all_13_switches():
    """13 个开关逐一映射到 EngineRequest 的 do_* 字段（施工卡 §3 硬性要求）。"""
    v = {
        "pitch": 1, "formant": 1,
        "harmonicAmplitude": 1, "harmonicAmplitudeUncorrected": 1,
        "slope": 1, "slopeUncorrected": 1,
        "intensity": 1, "cpp": 1, "hnr": 1, "soe": 1, "shr": 1, "cpps": 1,
        "resample16kHz": 0,
    }
    req = server._values_to_engine_request(v, "/tmp/x.wav")
    assert req["do_h1h2h4"] is True
    assert req["do_slopes"] is True
    assert req["do_energy"] is True
    assert req["do_cpp"] is True
    assert req["do_hnr"] is True
    assert req["do_soe"] is True
    assert req["do_shr"] is True
    # 谐波幅度子项随总开关一起算
    assert req["do_a1a2a3"] is True
    assert req["do_2k5k"] is True


def test_map_off_switches():
    v = {"pitch": 0, "formant": 0, "harmonicAmplitude": 0,
         "harmonicAmplitudeUncorrected": 0, "slope": 0, "slopeUncorrected": 0,
         "intensity": 0, "cpp": 0, "hnr": 0, "soe": 0, "shr": 0, "cpps": 0}
    req = server._values_to_engine_request(v, "/tmp/x.wav")
    for k in ("do_h1h2h4", "do_slopes", "do_energy", "do_cpp",
              "do_hnr", "do_soe", "do_shr", "do_a1a2a3", "do_2k5k"):
        assert req[k] is False


def test_map_engine_and_algorithm_defaults():
    req = server._values_to_engine_request({}, "/tmp/x.wav")
    assert req["pitch_engine"] == "praat"
    assert req["formant_engine"] == "praat"
    # 后端缺省基准 = praat（2026-10-27 用户定案：向导版恒以 Praat 为基准；
    # VS 版由 vs.js 显式传 straight/snack，不走这里的缺省）
    assert req["f0_algorithm"] == "praat"
    assert req["fmt_algorithm"] == "praat"


def test_map_interop_params():
    v = {
        "inputDir": "/data/wav",
        "pitchRead": 1, "pitchReadDir": "/data/wav/measure",
        "formantRead": 1, "formantReadDir": "/data/wav/measure",
        "praatExe": "/p/praat.exe", "snackExe": "/v/snack.exe",
        "otherF0File": "/o/f0.txt", "otherFmtFile": "/o/fmt.txt",
    }
    req = server._values_to_engine_request(v, "/data/wav/a.wav")
    assert req["reuse"] is True
    assert req["measure_dir"] == os.path.join("/data/wav", "measure")
    assert req["pitch_read_dir"] == "/data/wav/measure"
    assert req["formant_read_dir"] == "/data/wav/measure"
    assert req["praat_exe"] == "/p/praat.exe"
    assert req["snack_exe"] == "/v/snack.exe"
    assert req["other_f0_file"] == "/o/f0.txt"
    assert req["other_fmt_file"] == "/o/fmt.txt"


def test_resolve_measure_dir():
    assert server._resolve_measure_dir({"inputDir": "/data/wav"}) == \
        os.path.join("/data/wav", "measure")
    assert server._resolve_measure_dir({}) == ""


# ─────────────────────────────────────────────────────────── HTTP 分派
@pytest.fixture()
def base_url():
    srv = server.start_server(0, "127.0.0.1")
    host, port = srv.server_address
    yield "http://%s:%d" % (host, port)
    srv.shutdown()


def _opener(base):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(base + "/launch.html").read()  # 触发 PS-Token cookie
    return op


def _post(op, base, path, payload):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(op.open(req).read())


def test_validate_pysauce_missing_dir(base_url):
    op = _opener(base_url)
    r = _post(op, base_url, "/api/validate",
              {"engine": "pysauce", "values": {"inputDir": "/no/such/dir/xyz"}})
    assert r["ok"] is False
    assert any(e["field"] == "inputDir" for e in r["errors"])


def test_validate_pysauce_base_engine_no_false_warning(base_url, tmp_path):
    """基准引擎与「本次算哪套」不同 **不再告警**（2026-10-27 审查修复）。

    批量现在恒以基准引擎为主跑（server.run_pysauce_job：base_reqs 用
    pitch_engine=f0_algorithm），故「基准未计算 → 相关列 undefined」永不成立，
    旧告警纯属多引擎时代的假警报。
    """
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    op = _opener(base_url)
    r = _post(op, base_url, "/api/validate", {
        "engine": "pysauce",
        "values": {
            "inputDir": str(tmp_path), "outputDir": str(tmp_path),
            "pitch_engine": "praat", "formant_engine": "praat",
            "f0_algorithm": "straight", "fmt_algorithm": "snack",
        },
    })
    assert r["ok"] is True
    fields = {w["field"] for w in r["warnings"]}
    assert "f0_algorithm" not in fields
    assert "fmt_algorithm" not in fields


def test_run_engine_default_is_praat(base_url):
    """engine 缺省 → 1.2 原链：目录不存在时 validate 报错（不走 pysauce）。"""
    op = _opener(base_url)
    r = _post(op, base_url, "/api/run",
              {"values": {"inputDir": "/no/such/dir/xyz"}})
    assert r["ok"] is False
    assert "errors" in r


# ── 输出命名 + 结果 JSON（2026-10-27 定案）──────────────────────────────
def test_output_prefix_and_results_json(tmp_path):
    """输出文件名 = <f0algo>_<fmtalgo>_out.tsv；_results.json 记多套。"""
    import numpy as np

    # 造一个可跑的 wav（harm5 复制）
    import shutil
    fix = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "harm5.wav")
    shutil.copy(fix, str(tmp_path / "a.wav"))

    job = server.Job("batch", {}, 1)
    server.run_pysauce_job(job, {
        "inputDir": str(tmp_path), "outputDir": str(tmp_path),
        "outputFile": "out.tsv",
        "pitch_engine": "praat", "formant_engine": "praat",
        "f0_algorithm": "praat", "fmt_algorithm": "praat",
        "harmonicAmplitude": 1,
    }, [str(tmp_path / "a.wav")])
    assert os.path.exists(str(tmp_path / "praat_praat_out.tsv"))
    res = server.list_pysauce_results(str(tmp_path))
    assert res["count"] == 1 and res["multi"] is False
    assert res["runs"][0]["f0_algorithm"] == "praat"

    # 第二套（不同基准）→ multi=True
    job2 = server.Job("batch", {}, 1)
    server.run_pysauce_job(job2, {
        "inputDir": str(tmp_path), "outputDir": str(tmp_path),
        "outputFile": "out.tsv",
        "pitch_engine": "praat", "formant_engine": "praat",
        "f0_algorithm": "straight", "fmt_algorithm": "praat",
        "harmonicAmplitude": 1,
    }, [str(tmp_path / "a.wav")])
    res2 = server.list_pysauce_results(str(tmp_path))
    assert res2["count"] == 2 and res2["multi"] is True
    assert os.path.exists(str(tmp_path / "straight_praat_out.tsv"))


# ── 基准引擎补齐（F3：vs 页"基准未算则立即现算"）────────────────────────
def test_engine_columns_sets():
    """各引擎的引擎列集合（F0 + F1..4 + B1..4）。"""
    assert server._engine_columns("praat") == [
        "pF0", "pF1", "pF2", "pF3", "pF4", "pB1", "pB2", "pB3", "pB4"]
    assert server._engine_columns("snack") == [
        "sF0", "sF1", "sF2", "sF3", "sF4", "sB1", "sB2", "sB3", "sB4"]
    assert server._engine_columns("straight") == ["strF0"]
    assert server._engine_columns("shr") == ["shrF0"]
    assert server._engine_columns("other") == [
        "oF0", "oF1", "oF2", "oF3", "oF4", "oB1", "oB2", "oB3", "oB4"]
    assert server._engine_columns("bogus") == []


def test_merge_engine_columns_only_engine_cols():
    """合并只动引擎列，不碰测量列（H1c/CPP/…）。"""
    dst = {"H1c": [1.0], "CPP": [2.0], "pF0": [100.0], "sF0": None}
    src = {"H1c": [9.0], "CPP": [8.0], "pF0": [999.0], "sF0": [200.0]}
    server._merge_engine_columns(dst, src, "snack")
    # 引擎列被并入
    assert dst["sF0"] == [200.0]
    # 测量列保持原值（不取 src）
    assert dst["H1c"] == [1.0] and dst["CPP"] == [2.0]
    # 同引擎列不覆盖（snack 合并只写 sF0/sF1..，不写 pF0）
    assert dst["pF0"] == [100.0]


def test_merge_engine_columns_skips_none():
    dst = {"sF0": None}
    src = {"sF0": None}
    server._merge_engine_columns(dst, src, "snack")
    assert dst["sF0"] is None


def test_multi_engine_validate_accepts_engine_lists():
    """多引擎勾选（f0_engines/fmt_engines）不再产生「基准未计算」告警。

    2026-10-27 审查修复：基准恒为主跑，勾选引擎由 extras 补跑；旧告警删除后，
    base_autocompute 与多引擎两套传参口径应当一致（都无该字段告警）。
    """
    base = {"inputDir": "", "pitch_engine": "praat", "formant_engine": "praat",
            "f0_algorithm": "straight", "fmt_algorithm": "snack"}
    chk = server.validate_pysauce(dict(base))
    assert not any(w["field"] == "f0_algorithm" for w in chk["warnings"])
    assert not any(w["field"] == "fmt_algorithm" for w in chk["warnings"])
    chk2 = server.validate_pysauce(dict(base, base_autocompute=1,
                                        f0_engines=["praat", "snack", "straight"],
                                        fmt_engines=["praat", "snack"]))
    assert not any(w["field"] == "f0_algorithm" for w in chk2["warnings"])
    assert not any(w["field"] == "fmt_algorithm" for w in chk2["warnings"])


def test_base_autocompute_run_merges_engine_cols(tmp_path):
    """vs 页：算 praat 但基准 straight → 主跑用 straight 算下游，另补 praat 引擎列。"""
    import shutil
    praat = os.environ.get("PS2_PRAAT_EXE") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "praat.exe")
    if not os.path.isfile(praat):
        pytest.skip("未提供 praat.exe（设 PS2_PRAAT_EXE 或置于仓库根）")
    fix = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "harm5.wav")
    shutil.copy(fix, str(tmp_path / "a.wav"))
    job = server.Job("batch", {}, 1)
    server.run_pysauce_job(job, {
        "inputDir": str(tmp_path), "outputDir": str(tmp_path),
        "outputFile": "out.tsv",
        "praatExe": praat,
        "pitch_engine": "praat", "formant_engine": "praat",
        "f0_algorithm": "straight", "fmt_algorithm": "praat",
        "base_autocompute": 1,
        "harmonicAmplitude": 1,
    }, [str(tmp_path / "a.wav")])
    assert job.status == "done", job.error
    assert os.path.exists(str(tmp_path / "straight_praat_out.tsv"))
    # 读回 tsv：应同时含 strF0（基准，主跑产出）与 pF0（补齐产出）
    with open(str(tmp_path / "straight_praat_out.tsv"), encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("\t")
    assert "strF0" in head and "pF0" in head
