# -*- coding: utf-8 -*-
"""合成信号 fixtures 生成器。运行一次生成 tests/fixtures/ 下的 wav 与锚点。

所有信号 Fs=16000 Hz、16bit PCM 单声道，参数均为解析已知：
  sine100   : 100 Hz 正弦，幅度 0.5，1.0 s（16000 样本=100 个整周期 → RMS 精确）
  harm5     : 基频 200 Hz，5 谐波，幅度 [0.5,0.25,0.125,0.0625,0.03125]，0.5 s
              （幅度整体 ×0.5 相对早期版本，使解析峰值 0.687 < 1.0，避免 16bit 硬截幅；
               见 V2-A2 卡 §11.5 缺陷记录）
  noise10   : 白噪声 sigma=0.1，seed=42（np.random.RandomState(42).normal），1.0 s
  silence   : 全零 0.5 s
  chirpF0   : F0 线性 100→300 Hz 的正弦扫频，幅度 0.4，2.0 s
锚点推导见 docs/v2.0-工程卡/V2-A2-测试床.md §6。禁止改动任何参数。
"""
import json
import math
import os
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
FS = 16000


def _write_wav(name, x):
    x16 = np.clip(np.round(x * 32767.0), -32768, 32767).astype(np.int16)
    with wave.open(os.path.join(FIX, name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(x16.tobytes())


def main():
    os.makedirs(FIX, exist_ok=True)
    os.makedirs(os.path.join(FIX, "expected"), exist_ok=True)
    os.makedirs(os.path.join(FIX, "snapshots"), exist_ok=True)
    rng = np.random.RandomState(42)  # noise10 与后续随机信号统一用此 seed

    t1 = np.arange(FS) / FS
    sine100 = 0.5 * np.sin(2 * np.pi * 100.0 * t1)
    _write_wav("sine100.wav", sine100)

    t2 = np.arange(FS // 2) / FS
    harm5 = np.zeros_like(t2)
    # 幅度整体 ×0.5（相对 v1）：解析峰值 0.687 < 1.0，16bit 不截幅。
    # 原 [1.0,0.5,0.25,0.125,0.0625] 峰值达 1.3745，被 np.clip 压平 27.5% 样本 → 能量锚点不可达。
    for k, amp in enumerate([0.5, 0.25, 0.125, 0.0625, 0.03125], start=1):
        harm5 += amp * np.sin(2 * np.pi * 200.0 * k * t2)
    _write_wav("harm5.wav", harm5)

    noise10 = 0.1 * rng.standard_normal(FS)
    _write_wav("noise10.wav", noise10)

    _write_wav("silence.wav", np.zeros(FS // 2))

    t3 = np.arange(2 * FS) / FS
    f_inst = 100.0 + (300.0 - 100.0) * t3 / 2.0          # 瞬时频率 100→300 Hz 线性
    chirpF0 = 0.4 * np.sin(2 * np.pi * np.cumsum(f_inst) / FS)  # 相位=频率积分
    _write_wav("chirpF0.wav", chirpF0)

    anchor = {
        "fs": FS,
        "sine100": {"rms": 0.5 / math.sqrt(2.0), "f0_hz": 100.0, "dur_s": 1.0},
        "harm5": {
            "f0_hz": 200.0,
            "dur_s": 0.5,
            "harmonics_hz": [200.0, 400.0, 600.0, 800.0, 1000.0],
            "amplitudes": [0.5, 0.25, 0.125, 0.0625, 0.03125],
            "peak": 0.6872753980252196,
            "energy_5periods_400samp": 66.6015625,
        },
        "noise10": {"sigma": 0.1, "seed": 42, "dur_s": 1.0},
        "silence": {"rms": 0.0, "dur_s": 0.5},
        "chirpF0": {"f0_start_hz": 100.0, "f0_end_hz": 300.0, "amp": 0.4, "dur_s": 2.0},
    }
    with open(os.path.join(FIX, "expected", "anchor.json"), "w", encoding="utf-8") as f:
        json.dump(anchor, f, ensure_ascii=False, indent=1)
    print("fixtures OK ->", FIX)


if __name__ == "__main__":
    main()
