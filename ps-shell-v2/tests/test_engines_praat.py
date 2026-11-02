# -*- coding: utf-8 -*-
"""Praat 引擎包装测试（需要真实 praat.exe，跳过条件见下）。禁改。

注：卡片 §4.4 给出的测试片段未含 `import numpy as np`，但断言中使用了
`np.nanmedian`。为使测试在提供 PS2_PRAAT_EXE 时真正可运行，此处补上该
import（属机械性补全，未改动任何断言）。
"""
import os
import shutil

import numpy as np
import pytest

from backend.pysauce.engines.praat_f0 import praat_pitch
from backend.pysauce.engines.praat_fmt import praat_formants

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
PRAAT = os.environ.get("PS2_PRAAT_EXE", "")   # 由验收员在环境中提供


@pytest.mark.skipif(not PRAAT or not os.path.isfile(PRAAT), reason="需要 praat.exe")
def test_praat_pitch_cc(tmp_path):
    wav = os.path.join(FIX, "harm5.wav")
    f0, t = praat_pitch(wav, PRAAT, out_dir=str(tmp_path))
    assert f0.shape == t.shape
    assert (f0 > 0).any()
    assert abs(np.nanmedian(f0[f0 > 0]) - 200.0) < 20.0   # harm5 基频 200Hz


@pytest.mark.skipif(not PRAAT or not os.path.isfile(PRAAT), reason="需要 praat.exe")
def test_praat_formants(tmp_path):
    wav = os.path.join(FIX, "harm5.wav")
    f1, f2, f3, f4 = praat_formants(wav, PRAAT, out_dir=str(tmp_path))
    assert f1.shape == f2.shape == f3.shape == f4.shape
    assert (f1 > 0).any()
