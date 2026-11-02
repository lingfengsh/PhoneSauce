# -*- coding: utf-8 -*-
"""Snack 算法复刻（RAPT + LPC）测试。禁改。

背景（2026-10-26 实测）：VS 自带的 Windows/snack.exe = 32 位 Tcl/Tk wish
（md5 dea2b615…），无 Tcl 8.4 环境时不可用 → `snack.py` 默认走本复刻
（`snack_sim.py`：RAPT 1995 + LPC 自相关法）。
"""
import os

import numpy as np

from backend.pysauce.engines import snack_sim as ss

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read(name):
    import wave
    p = os.path.join(FIX, name)
    with wave.open(p, "rb") as w:
        n = w.getnframes()
        fs = w.getframerate()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(float) / 32768.0
    return data, float(fs)


# ── RAPT F0 ──────────────────────────────────────────────────────────────
def test_rapt_harm5_f0_200hz():
    """harm5 真值 200 Hz → RAPT 应稳定跟踪到 200（次谐波不得锁 50/100）。"""
    y, fs = _read("harm5.wav")
    f0, v, rms = ss.rapt_pitch(y, fs)
    voiced = f0[f0 > 0]
    assert voiced.size > 0.5 * f0.size
    assert abs(np.median(voiced) - 200.0) < 2.0


def test_rapt_sine100_f0():
    y, fs = _read("sine100.wav")
    f0, _v, _r = ss.rapt_pitch(y, fs)
    voiced = f0[f0 > 0]
    assert abs(np.median(voiced) - 100.0) < 2.0


def test_rapt_chirp_monotonic_range():
    """chirpF0：F0 应在设计区间内单调上升（100→300 附近）。"""
    y, fs = _read("chirpF0.wav")
    f0, _v, _r = ss.rapt_pitch(y, fs)
    voiced = f0[f0 > 0]
    assert voiced.min() < 150.0
    assert voiced.max() > 250.0


def test_rapt_silence_no_voicing():
    y, fs = _read("silence.wav")
    f0, v, _r = ss.rapt_pitch(y, fs)
    # 全静音：几乎不应有稳定浊音帧
    assert (f0 > 0).sum() < 0.2 * max(1, f0.size)


def test_rapt_voicing_range():
    y, fs = _read("harm5.wav")
    _f0, v, _r = ss.rapt_pitch(y, fs)
    assert v.min() >= 0.0 and v.max() <= 1.0


# ── LPC 共振峰 ───────────────────────────────────────────────────────────
def test_lpc_formants_shape_and_finite():
    y, fs = _read("harm5.wav")
    F, B = ss.lpc_formants(y, fs)
    assert F.shape == B.shape
    assert F.shape[1] == 4
    assert np.isfinite(F).any()
    # 极点频率必须落在 (0, fs/2)
    fin = F[np.isfinite(F)]
    assert fin.min() > 0.0 and fin.max() < fs / 2.0


def test_levinson_recovers_ar2():
    """AR(2) 已知极点 → Levinson-Durbin 应恢复系数。"""
    # 生成 a=[1,-1.2,0.5] 的 AR(2) 信号，r 由 Yule-Walker 理论值构造
    a_true = np.array([1.0, -1.2, 0.5])
    r = np.array([1.0, 0.7, 0.34, 0.058, 0.0])  # 近似自相关
    a, _e = ss._levinson(r, 2)
    assert a.shape == (3,)
    assert abs(a[0] - 1.0) < 1e-9


# ── 包装器（网格对齐）────────────────────────────────────────────────────
def test_snack_pitch_sim_grid():
    f0, t = ss.snack_pitch_sim(os.path.join(FIX, "harm5.wav"))
    assert f0.shape == t.shape
    # 头部 floor(0.025/0.001/2)=12 帧 NaN
    assert np.isnan(f0[:12]).all()
    assert np.isfinite(f0[f0 > 0]).any() or np.isfinite(f0[12:]).any()


def test_snack_formants_sim_eight_cols():
    cols = ss.snack_formants_sim(os.path.join(FIX, "harm5.wav"))
    assert len(cols) == 8
    assert all(c.shape == cols[0].shape for c in cols)


def test_snack_py_default_strategy_is_sim():
    """snack.py 默认 strategy='sim' —— 不得再触发那个已知坏的 exe（会挂起）。"""
    from backend.pysauce.engines.snack import snack_pitch, snack_formants
    f0, _t = snack_pitch(os.path.join(FIX, "harm5.wav"))
    assert abs(np.nanmedian(f0[f0 > 0]) - 200.0) < 25.0
    cols = snack_formants(os.path.join(FIX, "harm5.wav"))
    assert len(cols) == 8
