# -*- coding: utf-8 -*-
"""Snack 引擎测试（需要 vendor/snack.exe，缺失自动跳过）。禁改。

注（机械性补全，未改动任何断言）：
1) 卡片 §4 片段未含 `import numpy as np`，但断言用了 `np.nanmedian` → 补 import。
2) 卡片 §4 的 `V2_ROOT` 用 3 次 dirname → 得到的是**仓库根**，而 vendor 在
   `ps-shell-v2/vendor/`；此处改为 2 次 dirname（=ps-shell-v2），与 conftest.py 口径一致。
   否则 SNACK 路径恒不存在、测试被误 skip。
"""
import os

import numpy as np
import pytest

from backend.pysauce.engines.snack import snack_formants, snack_pitch

V2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNACK = os.path.join(V2_ROOT, "vendor", "snack.exe")
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

pytestmark = pytest.mark.skipif(not os.path.isfile(SNACK), reason="需要 vendor/snack.exe")


def test_snack_pitch_harm5(tmp_path):
    wav = os.path.join(FIX, "harm5.wav")
    f0, t = snack_pitch(wav)
    assert f0.shape == t.shape
    assert (f0 > 0).any()
    assert abs(np.nanmedian(f0[f0 > 0]) - 200.0) < 25.0


def test_snack_formants_harm5(tmp_path):
    wav = os.path.join(FIX, "harm5.wav")
    f1, f2, f3, f4, b1, b2, b3, b4 = snack_formants(wav)
    assert f1.shape == f4.shape == b1.shape == b4.shape
    assert (f1 > 0).any()
