# -*- coding: utf-8 -*-
"""fixtures 自检：生成器跑完后这些测试必须全绿。"""
import json
import os
import wave

import numpy as np

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read(name):
    with wave.open(os.path.join(FIX, name), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32767.0
    return x


def test_anchor_exists():
    with open(os.path.join(FIX, "expected", "anchor.json"), encoding="utf-8") as f:
        a = json.load(f)
    assert a["fs"] == 16000


def test_sine100_rms_exact():
    x = _read("sine100.wav")
    # 16bit 量化引入 ~1e-5 误差，锚点容差放宽到 1e-3
    assert abs(np.sqrt(np.mean(x ** 2)) - 0.5 / np.sqrt(2.0)) < 1e-3
    assert len(x) == 16000


def test_harm5_peak_at_200hz():
    x = _read("harm5.wav")
    spec = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 16000.0)
    for f in [200, 400, 600, 800, 1000]:
        assert spec[np.argmin(np.abs(freqs - f))] > 0  # 各谐波峰存在
    i200 = np.argmin(np.abs(freqs - 200.0))
    assert np.argmax(spec) == i200  # 全谱最大峰在 200 Hz（基频幅度最大）


def test_silence_is_zero():
    x = _read("silence.wav")
    assert float(np.max(np.abs(x))) == 0.0


def test_chirp_f0_range():
    x = _read("chirpF0.wav")
    # 粗检：过零率推平均 F0 应在 150~250 Hz 之间
    zc = np.nonzero(np.diff(np.signbit(x)))[0]
    mean_f0 = len(zc) / 2.0 / (len(x) / 16000.0)
    assert 150.0 < mean_f0 < 250.0
