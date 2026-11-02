# -*- coding: utf-8 -*-
"""基准引擎（2.0）测试：对象后缀口径 + 可用性探测 + 参数校验。

对应工程卡：V2-F1 §0b/§0c（两界面互通 + 基准引擎）、第三步「其他参数的基准引擎」。
纯离线测试，不碰真实 Praat、不写真实用户目录。
"""
import os
import tempfile
import unittest

from backend import review_export as re
from backend import params_validate as pv


def _mk_wav(d, name):
    p = os.path.join(d, name + ".wav")
    with open(p, "w") as f:
        f.write("")
    return p


def _mk_obj(d, name, ext, size=10):
    md = os.path.join(d, "measure")
    os.makedirs(md, exist_ok=True)
    p = os.path.join(md, name + ext)
    with open(p, "w") as f:
        f.write("x" * size)
    return p


class EngineObjectExtTest(unittest.TestCase):
    """对象后缀口径：Praat 用原生格式，非 Praat 用自有后缀（绝不伪造 Praat 格式）。"""

    def test_ext_mapping(self):
        self.assertEqual(re.ENGINE_OBJECT_EXT["f0"]["praat"], ".Pitch")
        self.assertEqual(re.ENGINE_OBJECT_EXT["f0"]["snack"], ".sF0")
        self.assertEqual(re.ENGINE_OBJECT_EXT["f0"]["straight"], ".strF0")
        self.assertEqual(re.ENGINE_OBJECT_EXT["formant"]["praat"], ".Formant")
        self.assertEqual(re.ENGINE_OBJECT_EXT["formant"]["snack"], ".sFormant")

    def test_engine_object_path(self):
        d = tempfile.mkdtemp()
        w = _mk_wav(d, "a")
        p = re.engine_object_path(w, "f0", "snack")
        self.assertTrue(p.endswith(os.path.join("measure", "a.sF0")))
        # 未知组合返回 None
        self.assertIsNone(re.engine_object_path(w, "formant", "straight"))
        self.assertIsNone(re.engine_object_path(w, "f0", "nope"))

    def test_praat_ext_unchanged(self):
        """1.2 兼容：praat 路径仍是 .Pitch / .Formant。"""
        d = tempfile.mkdtemp()
        w = _mk_wav(d, "a")
        self.assertEqual(re.engine_object_path(w, "f0", "praat"), re.pitch_path(w))
        self.assertEqual(re.engine_object_path(w, "formant", "praat"), re.formant_path(w))


class EngineAvailabilityTest(unittest.TestCase):

    def test_empty_dir(self):
        d = tempfile.mkdtemp()
        _mk_wav(d, "a")
        av = re.engine_availability(d)
        self.assertEqual(av["total"], 1)
        self.assertFalse(av["f0_any"])
        self.assertFalse(av["formant_any"])

    def test_praat_only(self):
        d = tempfile.mkdtemp()
        _mk_wav(d, "a")
        _mk_obj(d, "a", ".Pitch")
        _mk_obj(d, "a", ".Formant")
        av = re.engine_availability(d)
        self.assertEqual(av["f0"]["praat"], 1)
        self.assertEqual(av["f0"]["snack"], 0)
        self.assertTrue(av["f0_any"])
        self.assertTrue(av["formant_any"])

    def test_multi_engine(self):
        d = tempfile.mkdtemp()
        _mk_wav(d, "a")
        _mk_wav(d, "b")
        _mk_obj(d, "a", ".Pitch")
        _mk_obj(d, "b", ".sF0")
        _mk_obj(d, "b", ".strF0")
        av = re.engine_availability(d)
        self.assertEqual(av["f0"]["praat"], 1)
        self.assertEqual(av["f0"]["snack"], 1)
        self.assertEqual(av["f0"]["straight"], 1)
        self.assertTrue(av["f0_any"])
        # 共振峰一个都没有
        self.assertFalse(av["formant_any"])

    def test_zero_byte_ignored(self):
        """0 字节对象是中断残留，不算可用（与 1.2 的坏缓存自愈口径一致）。"""
        d = tempfile.mkdtemp()
        _mk_wav(d, "a")
        _mk_obj(d, "a", ".Pitch", size=0)
        av = re.engine_availability(d)
        self.assertEqual(av["f0"]["praat"], 0)
        self.assertFalse(av["f0_any"])


class BaseEngineValidateTest(unittest.TestCase):

    def test_default_ok(self):
        r = pv.validate_params({"f0BaseEngine": "praat", "formantBaseEngine": "praat"})
        self.assertFalse([e for e in r["errors"] if e["field"] in
                          ("f0BaseEngine", "formantBaseEngine")])

    def test_bad_value_falls_back(self):
        r = pv.validate_params({"f0BaseEngine": "magic", "formantBaseEngine": "stork"})
        fields = {e["field"] for e in r["errors"]}
        self.assertIn("f0BaseEngine", fields)
        self.assertIn("formantBaseEngine", fields)
        self.assertEqual(r["fixed"]["f0BaseEngine"], "praat")
        self.assertEqual(r["fixed"]["formantBaseEngine"], "praat")

    def test_unknown_engine_rejected(self):
        # formant 不允许 straight（STRAIGHT 不产共振峰）
        r = pv.validate_params({"formantBaseEngine": "straight"})
        self.assertIn("formantBaseEngine", {e["field"] for e in r["errors"]})


if __name__ == "__main__":
    unittest.main()
