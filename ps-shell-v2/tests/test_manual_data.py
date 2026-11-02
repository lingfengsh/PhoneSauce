# -*- coding: utf-8 -*-
"""Manual Data（数据调整）导入列的回归测试。

口径依据 VoiceSauce ``vs_ManualData.m`` + ``func_getmanualdataparameterlist.m``：
参数按引擎分列、无效占位符记 NaN、offset/重采样铺帧、只覆盖所选那一列。
2.0 的载体是 ``measure/`` 下的引擎对象（见 ``backend/manual_data.py`` 头注释）。
"""
import hashlib
import os
import shutil

import pytest

from backend import manual_data as md

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "..", "samples", "1")


def _fixture_dir(tmp_path):
    """造一份「straight/snack 已算过」的目录（拷真实样本，避免依赖合成 wav）。"""
    src_wav = os.path.join(SAMPLES, "11.wav")
    if not os.path.isfile(src_wav):
        pytest.skip("缺少样本 %s" % src_wav)
    wav = str(tmp_path / "11.wav")
    shutil.copy(src_wav, wav)
    mdir = tmp_path / "measure"
    mdir.mkdir()
    for nm in ("11.strF0", "11.sFormant"):
        src = os.path.join(SAMPLES, "measure", nm)
        if os.path.isfile(src):
            shutil.copy(src, str(mdir / nm))
    return wav


def test_parse_values_invalid_tokens():
    assert md.parse_values("120\nNaN\n--undefined--\n130.5\n\n-") == \
        [120.0, None, None, 130.5, None]
    assert md.parse_values("") == []
    assert md.parse_values("1\nabc\n2") == [1.0, None, 2.0]


def test_fit_values_resample_and_offset():
    fit = md.fit_values([100.0, 200.0], 4)
    assert [round(x, 6) for x in fit] == [100.0, 133.333333, 166.666667, 200.0]
    assert md.fit_values([1.0, 2.0], 5, offset=2, resample=False) == \
        [None, None, 1.0, 2.0, None]
    # 蓝本 newdata(OF+1:L)：OF 越过末尾时取到空区间 → 一帧都不写
    assert md.fit_values([1.0], 3, offset=99, resample=False) == [None, None, None]


def test_resolve_engine_follows_existing_object(tmp_path):
    wav = _fixture_dir(tmp_path)
    # 只有 .strF0 + .sFormant（无 .Pitch）→ F0 认 straight
    assert md.resolve_engine(wav, "f0") == "straight"
    assert md.read_rows(wav, "f0")["engine"] == "straight"


def test_save_f0_writes_only_that_engine(tmp_path):
    wav = _fixture_dir(tmp_path)
    r0 = md.read_rows(wav, "f0", "straight")
    n = r0["n"]
    assert n > 0 and len(r0["rows"]) == n
    sf = os.path.join(os.path.dirname(r0["path"]), "11.sFormant")
    h0 = hashlib.md5(open(sf, "rb").read()).hexdigest()

    vec = [150.0 + i * 0.5 for i in range(n)]
    res = md.save_values(wav, "f0", "straight", vec, resample=True)
    assert res["ok"], res

    back = md.read_rows(wav, "f0", "straight")["rows"]
    assert len(back) == n
    assert abs(back[0]["f0"] - 150.0) < 1e-6
    assert abs(back[-1]["f0"] - (150.0 + (n - 1) * 0.5)) < 1e-6
    # 同引擎另一维度 / Praat 对象都不该被碰
    assert hashlib.md5(open(sf, "rb").read()).hexdigest() == h0
    assert not os.path.isfile(os.path.join(os.path.dirname(r0["path"]), "11.Pitch"))


def test_save_formant_replaces_one_column_only(tmp_path):
    wav = _fixture_dir(tmp_path)
    before = md.read_rows(wav, "formant", "snack")["rows"]
    probe = next(i for i, r in enumerate(before) if r.get("F1") is not None)
    n = len(before)

    res = md.save_values(wav, "formant", "snack",
                         [500.0 + i for i in range(n)], column="F2")
    assert res["ok"], res
    after = md.read_rows(wav, "formant", "snack")["rows"]
    assert abs(after[0]["F2"] - 500.0) < 1e-6
    assert abs(after[-1]["F2"] - (500.0 + n - 1)) < 1e-6
    # 其余列原样
    assert after[probe]["F1"] == before[probe]["F1"]
    assert after[probe]["F3"] == before[probe]["F3"]
    assert after[probe]["B1"] == before[probe]["B1"]


def test_rejects_unsupported_engine_and_empty_data(tmp_path):
    wav = _fixture_dir(tmp_path)
    r = md.save_values(wav, "formant", "straight", [1.0])
    assert not r["ok"] and "不产出" in r["error"]
    r2 = md.save_values(wav, "f0", "straight", [None, None])
    assert not r2["ok"] and "为空" in r2["error"]
