# V2-B1：func_GetEnergy.m → pysauce/get_energy.py

> 难度：低。前置：V2-A2、V2-A3。
> 蓝本：`refs/voicesauce-v137/func_GetEnergy.m`（50 行，必读全文）。

## 0. 目标一句话

逐行复刻 VS 的 Energy：**5 个基频周期的变长窗内信号平方和**（`sum(yseg.^2)`，不是 RMS、不是 dB），每 1 ms 帧一个值。

## 1. 文件白名单

创建：
- `ps-shell-v2/backend/pysauce/get_energy.py`
- `ps-shell-v2/tests/test_get_energy.py`

## 2. 函数签名（精确，禁改）

```python
def get_energy(y: np.ndarray, f0: np.ndarray, fs: int,
               frameshift_ms: float = 1.0, n_periods_ec: int = 5) -> np.ndarray:
    """E = func_GetEnergy(y, F0, Fs, variables)。返回 len(f0) 的 float64 数组，无效帧为 NaN。"""
```

参数对应蓝本 `variables`：`n_periods_ec=variables.Nperiods_EC`（vs_Initialize 默认 5）、`frameshift_ms=variables.frameshift`（默认 1）。

## 3. 翻译要点（对照蓝本行号）

| 蓝本行 | MATLAB | Python | 说明 |
|---|---|---|---|
| L18 | `sampleshift = Fs/1000*frameshift` | 同式 | 每帧步进样本数（可为浮点） |
| L20 | `E = zeros(length(F0),1)*NaN` | `np.full(len(f0), np.nan)` | |
| L22 | `for k=1:length(F0)` | `for k0 in range(1, len(f0)+1)` | **k 是 1-based**（R2） |
| L24 | `ks = round(k*sampleshift)` | `ks = int(M.mround(k0*sampleshift))` | mround！内建 round 是银行家舍入（R1） |
| L26–28 | `ks<=0 \|\| ks>length(y)` continue | 同逻辑 | MATLAB 索引 1-based：ks 是"第 ks 个样本"，越界判 `ks > len(y)` |
| L32 | `N0_curr = Fs/F0_curr` | 同式 | |
| L35–36 | `ystart=round(ks-N/2*N0); yend=round(ks+N/2*N0)-1` | 同式（mround） | 闭区间 `[ystart, yend]`，**含端点** |
| L38–43 | `ystart<=0`、`yend>length(y)` continue | 同逻辑 | |
| L45 | `yseg = y(ystart:yend)` | `y[ystart-1 : yend]` | **MATLAB 闭区间 → Python 左闭右开，起点减 1**（R2 核心案例） |
| L47 | `E(k) = sum(yseg.^2)` | `e[k0-1] = float(np.sum(yseg**2))` | 平方和，不改 RMS/dB |

NaN F0 帧 → 保持 NaN（`continue`，蓝本 L29–31）。所有 continue 分支逐条保留，禁止合并。

## 4. 测试代码（`tests/test_get_energy.py`，原样照抄）

```python
# -*- coding: utf-8 -*-
"""func_GetEnergy 复刻测试。锚点为解析解（推导见工程卡 V2-B1 §5），禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_energy import get_energy

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _sig(name):
    return framing.read_wav(os.path.join(FIX, name))


def test_sine100_constant_f0():
    y, fs = _sig("sine100.wav")
    f0 = np.full(1000, 100.0)          # 1 秒音频、1 ms 帧 → 1000 帧
    e = get_energy(y, f0, fs)
    assert e.shape == (1000,)
    mid = e[200:800]
    # 5 整周期 × 160 样本/周期，sum(sin^2)*0.25 = 0.125*800 = 100.0（解析精确）
    # 16bit 量化使 wav 实测 ≈ 99.9947（偏离 5.3e-3），故 atol 用 1e-2
    assert np.allclose(mid, 100.0, atol=1e-2)
    assert not np.isnan(mid).any()


def test_sine100_nan_pattern():
    y, fs = _sig("sine100.wav")
    f0 = np.full(1000, 100.0)
    e = get_energy(y, f0, fs)
    valid = np.nonzero(~np.isnan(e))[0]
    assert valid[0] == 25 and valid[-1] == 974   # 边缘 ±2.5 周期=±400 样本=±25 帧
    assert int(np.isnan(e).sum()) == 50


def test_sine100_nan_f0_propagates():
    y, fs = _sig("sine100.wav")
    f0 = np.full(1000, 100.0)
    f0[500] = np.nan
    e = get_energy(y, f0, fs)
    assert np.isnan(e[500])
    # 相邻帧仍有效且量级正确
    assert abs(e[499] - 100.0) < 3.0 and abs(e[501] - 100.0) < 3.0


def test_harm5_constant_f0():
    y, fs = _sig("harm5.wav")
    f0 = np.full(500, 200.0)
    e = get_energy(y, f0, fs)
    mid = e[150:350]
    # Parseval：mean(y^2)=Σ amp_k^2/2 = 0.3330078125/2；窗 5×80=400 样本 → 66.6015625
    # （幅度 [0.5,0.25,0.125,0.0625,0.03125]，见 V2-A2 卡 §11.5；量化后实测 66.5974）
    assert np.allclose(mid, 66.6015625, atol=0.5)


def test_silence_energy_zero():
    y, fs = _sig("silence.wav")
    f0 = np.full(500, 100.0)
    e = get_energy(y, f0, fs)
    mid = e[150:350]
    assert np.allclose(mid, 0.0, atol=1e-12)   # 零信号窗存在 → 0（不是 NaN）


def test_short_signal_all_nan():
    y, fs = _sig("sine100.wav")
    e = get_energy(y[:100], np.full(10, 100.0), fs)  # 信号 100 样本 < 窗 800 样本
    assert np.isnan(e).all()
```

## 5. 锚点推导（验收员核对用）

- sine100：峰 0.5 正弦整周期窗，`sum(sin²)·0.25`，窗 800 样本 → 恰 100.0。有效帧边界：`ystart<=0` 首次失效在 k0=25（ks=400, ystart=round(400-400)=0），k0=26 起有效（0-based idx 25）；尾部对称 → NaN 共 50 帧（实测脚本验证：mean=100.0, std≈1.7e-14, first=25, last=974）。
- harm5：各谐波为 200 Hz 整数倍、窗 400 样本含整周期 → Parseval 精确：`Σ amp²/2 ×400 = 0.3330078125/2×400 = 66.6015625`（幅度 [0.5,0.25,0.125,0.0625,0.03125]，2026-10-26 由原 [1.0,…,0.0625] 整体 ×0.5，见 V2-A2 卡 §11.5；原 266.40625 因 16bit 截幅不可达）。
- sine100 量化后实测 99.9947（偏离 5.3e-3），故测试 atol 由 1e-6 放宽为 1e-2。
- 这些数值均由独立 Python 脚本复算过（2026-10-26），非手算估算。

## 6. 验收标准

1. 两个文件与签名/测试逐字符一致（除模块 docstring 可自写一行）。
2. `pytest ps-shell-v2/tests/ -x -q` 全绿（此前 ≥19 + 本卡 6 = ≥25 passed）。
3. 交付含蓝本对照表（§3 表逐行确认）。
4. 快照：报告末尾注明「get_energy 待验收员生成快照」，并附上对 `samples/` 前 3 个 wav（用常数 F0=已存在 pF0 或跳过——若 samples 无 F0 文件，快照用 fixtures 5 波形 + 各自真值 F0）的全帧输出前 20 个值。

## 7. 禁止事项

- 禁止把循环向量化（蓝本是显式 for + 多 continue 分支，保持逐帧结构）。
- 禁止用内建 `round()`/`np.round()`（银行家舍入陷阱，R1）。
- 禁止改测试。

## 8. 停报条件

按总纲第 9 节。特别地：若你认为 `y[ystart-1:yend]` 与蓝本 `y(ystart:yend)` 不等价，停报并列出两种解读。

---

## 9. 实施记录（施工者填，2026-10-26）

**状态**：完成。`get_energy.py` 逐行复刻蓝本；测试 6 例全绿。

### 9.1 预检

- 依赖 A2/A3 已完成（fixtures 5 wav + anchor、matlang/framing 就位）。
- 蓝本 `func_GetEnergy.m` 50 行已通读；§3 翻译表逐行核对**与蓝本完全一致**。

### 9.2 施工中发现的上游缺陷（已按用户拍板方案 A 修复，见 A2 卡 §11.5）

- 复算锚点时发现 `harm5` wav 与解析值差 −60.7：原幅度 `[1.0,…,0.0625]` 解析峰值 1.3745 > 1.0 → 生成器 `np.clip` **压平 27.5% 样本**。
- 用户拍板方案 A：harm5 幅度整体 ×0.5 → `[0.5,0.25,0.125,0.0625,0.03125]`，峰值 0.687，无截幅；anchor 能量 266.40625 → **66.6015625**。
- 附带：sine100 16bit 量化后实测 99.9947（偏离 5.3e-3），测试 `atol` 由 1e-6 放宽为 1e-2。
- 本卡 §4/§5 已同步新值；实现代码不受影响（算法与幅度无关）。

### 9.3 蓝本对照表（MATLAB 行 → Python）

| 蓝本行 | MATLAB | Python 行 | 说明 |
|---|---|---|---|
| L14 | `N_periods = variables.Nperiods_EC;` | 参数 `n_periods_ec` | 默认 5 |
| L15 | `sampleshift = (Fs/1000*variables.frameshift);` | `sampleshift = fs/1000.0*frameshift_ms` | |
| L17 | `E = zeros(length(F0),1)*NaN;` | `e = np.full(len(f0), np.nan)` | |
| L19 | `for k=1:length(F0)` | `for k0 in range(1, len(f0)+1)` | 1-based（R2） |
| L20 | `ks = round(k*sampleshift);` | `ks = int(M.mround(k0*sampleshift))` | mround（R1） |
| L22-24 | `if (ks<=0 \|\| ks>length(y)) continue;` | `if ks<=0 or ks>len(y): continue` | |
| L26 | `F0_curr = F0(k);` | `f0_curr = f0[k0-1]` | |
| L28-30 | `if (isnan(F0_curr)) continue;` | `if np.isnan(f0_curr): continue` | |
| L32 | `N0_curr = Fs/F0_curr;` | `n0_curr = fs/f0_curr` | |
| L34 | `ystart = round(ks - N_periods/2*N0_curr);` | `ystart = int(M.mround(...))` | |
| L35 | `yend = round(ks + N_periods/2*N0_curr) - 1;` | `yend = int(M.mround(...)) - 1` | |
| L37-39 | `if (ystart<=0) continue;` | `if ystart<=0: continue` | |
| L41-43 | `if (yend>length(y)) continue;` | `if yend>len(y): continue` | |
| L45 | `yseg = y(ystart:yend);` | `yseg = y[ystart-1:yend]` | 闭→左闭右开（R2） |
| L47 | `E(k) = sum(yseg.^2);` | `e[k0-1] = float(np.sum(yseg**2))` | 平方和，非 RMS/dB |

四处 `continue` 分支（L22/L28/L37/L41）逐条保留，未合并；循环保持逐帧结构，未向量化。

### 9.4 验收命令原始输出

```
$ python -m pytest ps-shell-v2/tests/test_get_energy.py -q
......                                                                   [100%]
6 passed in 0.20s

$ python -m pytest ps-shell-v2/tests/ -q
1 failed, 207 passed in 4.72s
（唯一失败 = test_rv1.test_partial，1.2 既有失败，非本卡引入）
```

### 9.5 快照与全帧输出（§6 验收标准 4）

**「get_energy 待验收员生成快照」**（施工者禁止自行 save_snapshot）。

fixtures 5 波形各取常数 F0，全帧输出前 20 个值：

| 波形 | F0 | 前 20 帧 |
|---|---|---|
| sine100 | 100 | 全 nan（前 25 帧无效，±2.5 周期边界） |
| harm5 | 200 | 前 12 nan，第 13 帧起 66.5974（→ 5 周期窗能量） |
| noise10 | 120 | 全 nan（窗 5×133=667 样本，前 13 帧越界） |
| silence | 100 | 全 nan（前 25 帧无效；中段为 0） |
| chirpF0 | 200 | 前 12 nan，第 13 帧起 31.7–32.6（扫频幅度 0.4，能量随窗内频率变化） |

> 注：`samples/` 下 wav 无配套 pF0 文件，故按卡 §6 备选口径「快照用 fixtures 5 波形 + 各自真值 F0」执行。
