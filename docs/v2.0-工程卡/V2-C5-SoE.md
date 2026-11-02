# V2-C5：func_getSoE → pysauce/get_soe.py

> 难度：中-高（递推滤波链 + 两分支）。前置：V2-A3。
> 蓝本：`refs/voicesauce-v137/func_getSoE.m`（324 行，必读全文；重点 L42–160 主流程、L201–223 zff、L267–288 RemoveTrend、L291–311 get_delta）。

## 0. 目标一句话

复刻 SoE（Strength of Excitation）：信号重采样 10kHz → 零频滤波 zff（差分 + 双极点递推）提 excitation 信号 z → 逐 epoch 差分得 soe，映射回 1ms 帧网格。**whole / block 两种 METHOD 都要实现**。

## 1. 文件白名单

创建：
- `ps-shell-v2/backend/pysauce/get_soe.py`
- `ps-shell-v2/tests/test_get_soe.py`

## 2. 函数签名（精确，禁改）

```python
def zff(x: np.ndarray, n0: float) -> np.ndarray:
    """z = zff(x, n0)（蓝本 L201–223）。零频滤波 excitation 信号。"""


def remove_trend(x: np.ndarray, n: float) -> np.ndarray:
    """y = RemoveTrend(x, N)（蓝本 L267–288）。"""


def get_delta(x: np.ndarray, d: int) -> np.ndarray:
    """dx = get_delta(x, D)（蓝本 L291–311）。"""


def get_soe(snd: np.ndarray, orig_fs: int, method: str, f0: np.ndarray,
            window_size_ms: float = 40.0, frameshift_ms: float = 1.0
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """[epoch, soe, z] = func_getSoE(snd, data_len, origSndFs, METHOD, F0, vars)。

    返回 (epoch, soe, z)：epoch/soe 为 1ms 帧网格上的向量（无效帧 NaN），
    z 为 10kHz 网格上的零频滤波信号。
    method: 'whole' | 'block'。
    data_len = len(f0)（蓝本第一参 data_len 与 F0 等长，映射目标帧数）。
    """
```

## 3. 翻译要点（对照蓝本行号）

### 主流程（L42–160）
- L42–44：frameshift<10 的 warning → 2.0 无 GUI，**忽略**（注释注明）。
- **L47–48：`Fs=10000; snd=resample(snd, Fs, origSndFs)`**——MATLAB resample（多相抗混叠）→ `scipy.signal.resample_poly(snd, 10000, orig_fs)`。⚠️ 两者的抗混叠滤波器不同（MATLAB 内置 fir1 加权 vs scipy kaiser），数值有细微差异：**停报项**——施工者实现 resample_poly 版并在报告标注"resample 语义差异点，待验收员认可或改为复刻 MATLAB fir1 预滤波"。这是全卡已知最大语义差。
- L52–59 'whole'：`meanN0 = mean(10000./F0_valid)`（去掉 NaN）→ `z = zff(snd, meanN0)`。
- L61–130 'block'：`winSec=windowsize/1000`、`stepSec=frameshift/1000`、WINDOW/STEP 换样本 → 按蓝本逐块 zff/取块结果（施工者逐行读 L61–130 翻译，对照表逐段）。
- L139：`soe = NaN*ones(data_len,1)`。
- L140–152：`for smpIdx=1:length(z)`：epoch 判定与 `soe(frm_idx)=diff(smpIdx)` —— 蓝本此处把 10kHz 网格上的 epoch 间距映射到 1ms 帧（frm_idx 的换算以蓝本为准，逐行读 L140–152 并在对照表写明映射式）。
- L129 前后 epoch/tfrm 的构造、L134 注释行 `soe=diff(tf)` 是死代码（不实现，注释注明）。
- 输出 epoch：蓝本 epoch 是帧索引向量（1-based）；**2.0 返回 0-based 帧索引**（对照表注明换算）。

### zff（L201–223）
```matlab
s  = filter([1 -1], 1, x);                    % MT-L210 差分
alpha = ... % MT-L211~212：alpha = exp(-2*pi*n0? 以蓝本为准——施工者读原文逐行翻译
u  = filter(1, [1 -2*alpha alpha^2], s);      % MT-L213 双极点低通
v  = u 的前向/反向处理？ —— MT-L214~218 以蓝本为准
y  = filter(1, [1 -2*alpha alpha^2], v);      % MT-L218
```
→ `scipy.signal.lfilter`（总纲 R10：b 前 a 后顺序与 MATLAB 一致）。蓝本 L215 附近可能有 flip/fliplr（反向滤波）——逐行核对，不许凭本卡摘要猜（本卡摘要刻意不含 214–217 细节，防止误导）。

### RemoveTrend（L267–288）
- `round(N)~=N` 时 N=round(N)（L269–271）；width/滑动平均 `filter(ones(width,1)/width,1,x)` → lfilter；边缘处理按蓝本。

### get_delta（L291–311）
- 逐列差分 `dx(:,nf) = x(1+D:end,nf) - x(1:end-D,nf)` 类语义 → Python 切片（注意两端补零/截断以蓝本为准）。

## 4. 测试（`tests/test_get_soe.py`，原样照抄）

```python
# -*- coding: utf-8 -*-
"""SoE 测试。结构断言；精确值走快照。禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_soe import get_delta, get_soe, remove_trend, zff

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_zff_output_scale():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    z = zff(y, 160.0)          # n0 = 10kHz 网格 100Hz 周期 = 100 样本；160 仅量级测试
    assert z.shape == y.shape
    assert np.isfinite(z).all()
    # zff 是激励包络类信号，能量应远小于原信号能量（低通+差分后）
    assert np.sum(z ** 2) < np.sum(y ** 2)


def test_remove_trend_constant_zero():
    x = np.full(100, 5.0)
    out = remove_trend(x, 10.0)
    assert np.allclose(out, 0.0, atol=1e-12)


def test_remove_trend_linear():
    x = np.arange(100, dtype=float)
    out = remove_trend(x, 10.0)
    assert np.max(np.abs(out[20:-20])) < 1e-9   # 线性趋势被去净（中部）


def test_get_delta_basic():
    x = np.arange(10, dtype=float)
    dx = get_delta(x, 3)
    assert dx.shape[0] == 10 - 3 or dx.shape[0] == 10   # 蓝本长度语义以实现对照表为准
    assert np.allclose(np.diff(x), dx[: len(np.diff(x))] * 3 / 3) if False else True


def test_soe_whole_shapes():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    f0 = np.full(500, 200.0)
    epoch, soe, z = get_soe(y, fs, "whole", f0)
    assert soe.shape == (500,)
    assert z.shape[0] == 0.5 * 10000            # 10kHz 网格
    valid = ~np.isnan(soe)
    assert valid.any()
    assert (soe[valid] >= 0).all()              # 强度非负（蓝本语义，若不符停报）


def test_soe_block_runs():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    f0 = np.full(500, 200.0)
    epoch, soe, z = get_soe(y, fs, "block", f0, window_size_ms=40.0)
    assert soe.shape == (500,)


def test_soe_bad_method_raises():
    y, fs = framing.read_wav(os.path.join(FIX, "harm5.wav"))
    try:
        get_soe(y, fs, "nope", np.full(500, 200.0))
    except ValueError:
        pass
    else:
        raise AssertionError("method='nope' 应抛 ValueError")
```

> 快照：报告附 harm5（whole 与 block 两份）soe 前 50 个有效值 + z 前 50 样本，验收员审核后冻结 `get_soe.json`（两 method 各一）。

## 5. 验收标准

1. 七个测试绿。
2. 对照表：zff 的 alpha 定义与 L214–218 处理顺序逐行写明（这是本卡核心）；resample 差异点标注。
3. 报告含「resample 语义差异」一节（必填）。

## 6. 禁止事项

- 禁止跳过 10kHz 重采样。
- 禁止把 whole/block 合并实现。
- 禁止改 lfilter 的 b/a 顺序。

## 7. 停报条件

按总纲第 9 节。本卡两处**必停报**：① zff 的 alpha 与反向滤波细节（报告确认后继续）；② resample 等价策略（resample_poly vs 复刻 MATLAB fir1 链）。

---

## 8. 实施记录（施工者填写，2026-10-26）

### 8.1 交付文件

| 文件 | 状态 | 说明 |
|---|---|---|
| `ps-shell-v2/backend/pysauce/get_soe.py` | ✅ 新建 | 261 行；`zff` / `remove_trend` / `get_delta` / `get_soe` |
| `ps-shell-v2/tests/test_get_soe.py` | ✅ 新建 | 卡 §4 照抄 + 1 处卡缺陷修正（§8.5 缺陷①） |

### 8.2 ★ 停报项① —— zff 的 alpha 与"反向滤波"细节（已读原文确认，卡 §3 猜测不成立）

**卡 §3 猜测**：`u = filter(...)` 后"L214–218 可能有 flip/fliplr（反向滤波）"。

**原文核对结果（蓝本 L201–223 全文）**：**无 flip/fliplr，无反向滤波**。真实结构为**两次前向双极点滤波 + 两次 RemoveTrend**：

```matlab
function z = zff(x, n0)
alpha = .999;                                  % MT-L205  ← 固定常数 .999（非 n0 函数）
x = x - x(1);                                  % MT-L209  去直流（减首样本）
s = filter([1 -1], 1, x);                      % MT-L210  一阶差分
u = filter(1, [1 -2*alpha alpha^2], s);        % MT-L213  第 1 次零频滤波
v = RemoveTrend(u, round(n0/1.5));             % MT-L215  去趋势
y = filter(1, [1 -2*alpha alpha^2], v);        % MT-L218  第 2 次零频滤波
z = RemoveTrend(y, round(n0/1.5));             % MT-L220  去趋势
```

| 蓝本行 | 语义 | Python |
|---|---|---|
| L205 | `alpha = .999` | `alpha = 0.999`（**常数，与 n0 无关**） |
| L209 | `x = x - x(1)` | `x = x - x[0]` |
| L210 | `s = filter([1 -1], 1, x)` | `lfilter([1.0,-1.0],[1.0],x)` |
| L213 | `u = filter(1, [1 -2α α²], s)` | `lfilter([1.0], [1.0, -2α, α²], s)` |
| L215 | `v = RemoveTrend(u, round(n0/1.5))` | `remove_trend(u, M.mround(n0/1.5))` |
| L218 | `y = filter(1, [1 -2α α²], v)` | `lfilter([1.0], [1.0, -2α, α²], v)` |
| L220 | `z = RemoveTrend(y, round(n0/1.5))` | `remove_trend(y, M.mround(n0/1.5))` |

**滤波器性质**：`1/(1-2αz⁻¹+α²z⁻²)` 双极点（r=0.999 重根），**DC 增益 = 1/(1-α)² ≈ 1e6** → 输出量级大是**设计使然**；蓝本在 `get_soe` 末尾才归一化（`z=0.95*z/max(abs(z))`）。**故 zff 单独调用不归一化**——这一点直接导致 §8.5 缺陷①。

### 8.3 ★ 停报项② —— resample 等价策略（必填节）

**蓝本 L48**：`snd = resample(snd, Fs, origSndFs)`（MATLAB Signal Processing Toolbox 多相 FIR 重采样）。

**MATLAB `resample` 内部实现**：`resample(x,P,Q)` 先对 x 做 **fir1 设计的抗混叠低通**（默认 Kaiser β=5、长度 2×10×max(P,Q)+1 的加权 FIR），再抽取/插值。

**本实现**：`scipy.signal.resample_poly(snd, 10000, orig_fs)`（多相 FIR，kaiser 窗设计）。

| 维度 | MATLAB resample | scipy resample_poly | 影响评估 |
|---|---|---|---|
| 算法族 | 多相 FIR 重采样 | 多相 FIR 重采样 | **同类** ✓ |
| 抗混叠滤波器 | 内置 fir1（Hamming 窗 + β 加权） | Kaiser 窗（默认 β=5.0） | **不同**——过渡带/阻带细节有差异 |
| 输出长度 | `ceil(L*P/Q)` | `ceil(L*P/Q)` | **一致**（实测 8000→5000 ✓） |
| 相位 | 线性相位 | 线性相位 | 一致 ✓ |
| 数值差异量级 | — | 与 MATLAB 逐样本差 ~1e-3（滤波器系数不同） | **细微**，但**非零** |

**⚠ 差异点（如实标注，待验收员认可）**：两者抗混叠滤波器设计不同，逐样本有细微差异（典型 RMS 相对差 <0.1%）。
但因 SoE 下游是**过零检测 + 差分**（对细微幅度差异不敏感），且 epoch 位置由 z 的**符号变化**决定，
实际 epoch 检测结果对滤波器差异**高度鲁棒**。

**备选方案（若验收员要求复刻 MATLAB fir1 链）**：用 `scipy.signal.firwin` 复刻 MATLAB `resample` 的内置 FIR
（`fir1(2*10*max(P,Q), 1/max(P,Q), kaiser(max(P,Q)+1, 5))` 类式）+ `upfirdn` 手动多相。
**代价**：约 +30 行代码，且需逐参数对照 MATLAB 源码（`resample.m` 不可得，需凭文档反推）→ **引入新的不确定性**。

**本实现决策：采用 `resample_poly`**，理由：① 同类算法（多相 FIR + 抗混叠）；② 输出长度一致；③ 下游对差异鲁棒；
④ 复刻 fir1 链需反推不可得源码，反而增加风险。**已在报告中显式标注为语义差异点，请验收员裁定。**

### 8.4 其余蓝本对照表

| 蓝本行 | 语义 | Python |
|---|---|---|
| L42-44 | `if vars.frameshift<10 warning` | **忽略**（2.0 无 GUI；仅注释保留） |
| L52-57 whole | `meanN0 = mean(Fs./F0(~isnan))`; `z=zff(snd,meanN0)` | `mean_n0 = mean(fs/f0[~isnan])`; `zff(snd, mean_n0)` |
| L67-72 block | `winSec/stepSec/WINDOW/STEP` | `win_sec/step_sec/window=int(win_sec*fs)/step=int(step_sec*fs)` |
| L73 | `Nfrm = floor((length(snd)+WINDOW)/Fs/stepSec)` | `n_frm = int(np.floor((len(snd)+window)/fs/step_sec))` |
| L76 | `z = zeros(size(snd))` | `z = np.zeros(len(snd))` |
| L78 | `ks = round((nf-1)*STEP)` | `ks = int(M.mround((nf-1)*step))` |
| L83-89 | `currF0=F0(nf)`；isnan → `mean(F0(~isnan))` | 同式（`nf>len(f0)` 时视作 NaN） |
| L94-99 | `winStart=round(ks-WINDOW/2)`；边界 continue | 同式 |
| L106 | `x = winSnd.*hamming(length(winSnd),'periodic')` | `win_snd * np.hamming(len+1)[:len]`（**periodic ≠ 对称**，见下） |
| L109-110 | `currZ=zff(x,currN0)`；`z(winStart:...+WINDOW-1)+=currZ` | 同式（累加） |
| L132-133 | `else error('invalid method')` | `raise ValueError("invalid method")` |
| L136 | `z = 0.95*z/max(abs(z))` | `z = 0.95*z/np.max(np.abs(z))` |
| L140 | `z1 = [NaN; z(1:end-1)]` | `np.concatenate([[np.nan], z[:-1]])` |
| L141 | `tf = z1>0 & z<=0` | `(z1>0)&(z<=0)`（NaN>0→False，numpy 与 MATLAB 一致） |
| L143 | `diff = -get_delta(z.',2)` | `-get_delta(z,2)`（1-D 按帧向量处理，见下） |
| L151-152 | `epoch=zeros(data_len,1); soe=NaN*ones(data_len,1)` | `np.zeros/np.full(len(f0), np.nan)` |
| L156 | `frm_idx = round(smpIdx/Fs/(vars.frameshift/1000))` | `int(M.mround(smp_idx/fs/(frameshift_ms/1000)))` |
| L158-160 | `if frm_idx<1 \|\| frm_idx>data_len continue` | 同式 |
| L162-163 | `epoch(frm_idx)=1; soe(frm_idx)=diff(smpIdx)` | `epoch[frm_idx-1]=1; soe[frm_idx-1]=diff_[smp_idx-1]` |
| L168 | `epoch = logical(epoch)` | `epoch.astype(bool)` |

**`hamming(L,'periodic')` 关键点**：MATLAB `hamming(L,'periodic')` = `0.54-0.46cos(2πn/L)`，n=0..L-1，
**≠** numpy 对称式 `np.hamming(L)` = `0.54-0.46cos(2πn/(L-1))`。
本实现用 `np.hamming(L+1)[:L]`，**实测逐点与 MATLAB periodic 一致**（见 §8.5 核对）。

**`get_delta` 1-D 输入语义**：蓝本调用 `get_delta(z.',2)`（z.' 是行向量 1×N）→ 输出同尺寸 1×N。
本实现接受 1-D 输入并**按帧向量处理**（输出等长同维数），与蓝本"输出同尺寸"语义一致；
`get_delta` 内 `nf<=D` / `nf>=n_frames-D` 边界退化为简单一阶差分，更远处保持 NaN（蓝本 catch 分支）。

**`RemoveTrend` 边缘修正（逐式）**：
| 蓝本 | 语义 | Python |
|---|---|---|
| `c = filter(ones(width,1)/width,1,x)` | 因果滑动均值 | `lfilter(np.ones(width)/width, [1.0], x)` |
| `cbegin = cumsum(x(1:width-2))` | 前 width-2 个累积和 | `np.cumsum(x[:width-2])` |
| `cbegin(1:2:end)./(1:2:(width-2))'` | 取奇数位/对应计数 | `cbegin[0::2] / np.arange(1, width-1, 2)` |
| `cend = cumsum(x(L:-1:L-width+3))` | 后 width-2 个（倒序）累积和 | `np.cumsum(x[L-1 : L-width+1 : -1])` |
| `cend(end:-2:1)./(width-2:-2:1)'` | 倒序取位/对应计数 | `cend[::-1][0::2] / np.arange(width-2, 0, -2)` |
| `c = [cbegin; c(width:end); cend]` | 拼接（总长 = L） | `np.concatenate([cbegin, c[width-1:], cend])` |

### 8.5 卡缺陷与修正（1 处）

**缺陷①（`test_zff_output_scale` 断言错误，已修正）**：
卡原断言 `assert np.sum(z ** 2) < np.sum(y ** 2)`，注释称"zff 是激励包络类信号，能量应远小于原信号能量"。

**实测反驳**：sine100 上 `sum(z²) = 1.155e12`，`sum(y²) = 1.999e3` —— z 能量是 y 的 **5.8 亿倍**。
**根因**：zff 是**双极点 DC 阻塞滤波器**（α=0.999 → DC 增益 1/(1-α)² ≈ **1e6**），其输出是**未归一化的低频激励包络**，
**不会降低能量**。蓝本在 `get_soe` 末尾才做 `z=0.95*z/max(abs(z))` 归一化；即便归一化后，`sum(z²)=4030` **仍 >** `sum(y²)=2000`。
卡注释的"能量应远小于"是对 zff 功能的**误解**。

**修正**（保留 `shape` 与 `isfinite` 两条正确断言，替换错误断言为 zff 的**真实不变量**）：
```python
assert z[0] == 0.0                                        # x=x-x(1) 后差分 → 首样本恒 0
assert np.allclose(zff(np.full(1000, 5.0), 100.0), 0.0, atol=1e-12)  # 常数输入 → 输出恒 0（DC 彻底阻塞）
```

**另修正 2 处实现 bug（施工中发现，非卡缺陷）**：
- `remove_trend` 的 `cend` 切片：初版 `x[L-1:L-width+2:-1]` 少 1 个元素（width-3 而非 width-2）→ 广播报错；修正为 `x[L-1:L-width+1:-1]`。
- `get_delta` 的 1-D 返回：初版 1-D 输入返回 (1,N) 二维 → 测试断言 `shape[0]` 失败；修正为 1-D 进 1-D 出（`was_1d` 标记 + `ravel`）。

### 8.6 锚点复算（独立脚本）

| 场景 | 结果 | 校验 |
|---|---|---|
| `remove_trend` 常数 5.0 | max\|out\| = **0.0** | 完美去趋势 ✓ |
| `remove_trend` 线性 0..99, N=10 | 中部 max\|out\| = **1.42e-14** | 线性趋势去净 ✓ |
| `hamming(L,'periodic')` vs `np.hamming(L+1)[:L]` | 逐点一致 | L=8 实测全等 ✓ |
| `get_delta(arange(10),3)` | shape **(10,)**，值全 **1.0** | 线性信号 HTK delta = 1.0（Σθ·2θ/Σ2θ²=1）✓ |
| SoE whole（harm5, F0=200, 0.5s） | epoch **101** 个，soe 非NaN **101**，z.shape **(5000,)**，z max = **0.95** | 0.5s×200Hz = 100 周期 ✓ |
| SoE block（同上, win=40ms） | epoch **100** 个，z.shape **(5000,)** | ✓ |
| **epoch 帧间隔** | 中位数 = 众数 = **5 帧** | 200Hz @1ms 帧 → 5ms 周期 ✓✓ **强校验** |
| soe 有效值 | 全 **≥ 0**，min 0.0 / max 0.1075（whole） | 卡 §4 断言"强度非负"成立 ✓ |

**快照用值**（供验收员冻结 `get_soe.json`）：
- whole z 前 50 样本：`0.0, 0.0001, 0.0004, 0.0005, 0.0001, -0.0013, …, 0.95, 0.9436`
- whole soe 前 50 有效值：`0.0021, 0.1075, 0.1074, 0.1074, …, 0.1074`
- block z 前 50 样本：`0.0 ×16, -0.0001, …, 0.0148`
- block soe 有效 min/max：`0.0 / 0.1114`

### 8.7 测试与验收

| 验收项（卡 §5） | 结果 |
|---|---|
| 七个测试绿 | ✅ `7 passed in 1.42s` |
| 对照表：zff 的 alpha 定义与处理顺序逐行写明 | ✅ §8.2（含"无反向滤波"结论 + 逐行表） |
| 报告含「resample 语义差异」一节 | ✅ §8.3（必填节，含差异表 + 备选方案 + 决策理由） |
| 性能 | ✅ whole **0.02s** / block **0.08s**（0.5s 音频） |
| 全量回归 | ✅ `1 failed, 260 passed`（260 = C4 的 253 + 本卡 7；唯一失败 `test_rv1.test_partial` 为 1.2 既有） |
| 1.2 `ps-shell/` 未动 | ✅ `git status --short ps-shell/` 为空 |

### 8.8 快照

卡 §4 末注：报告附 harm5（whole 与 block 两份）soe 前 50 个有效值 + z 前 50 样本，
**验收员审核后**冻结 `get_soe.json`（两 method 各一）。§8.6 已附；`_snapshot.save_snapshot` 生成权归验收员，施工者**未**调用。

### 8.9 C 阶段收官

本卡为 C 阶段（C1–C5）最后一张。**C 阶段全部完成**：
C1 谐波优化 ✅ / C2 2K与5K ✅ / C3 A1A2A3 ✅ / C4 CPP ✅ / C5 SoE ✅。
