# V2-D1：func_GetHNR → pysauce/get_hnr.py

> 难度：中-高（de Krom 1993 倒谱链）。前置：V2-A3。
> 蓝本：`refs/voicesauce-v137/func_GetHNR.m`（127 行，必读全文；主循环 L24–62、子函数 getHNR L67–127）。

## 0. 目标一句话

复刻 HNR05/15/25/35：5 周期窗（**强制奇数长**）→ hamming → 倒谱 → 在 4 个等价截止频率（500/1500/2500/3500 Hz）下分离谐波谱与噪声谱，各出 dB 比值。

## 1. 文件白名单

创建：
- `ps-shell-v2/backend/pysauce/get_hnr.py`
- `ps-shell-v2/tests/test_get_hnr.py`

## 2. 函数签名（精确，禁改）

```python
def get_hnr_for_frame(yseg: np.ndarray, f0: float, fs: float,
                      nfreqs: "tuple[float, ...]" = (500.0, 1500.0, 2500.0, 3500.0)
                      ) -> np.ndarray:
    """n = getHNR(yseg, F0, Fs, Nfreqs)（蓝本 L67–127）。返回 len(nfreqs)=4 向量。"""


def get_hnr(y: np.ndarray, fs: int, f0: np.ndarray,
            n_periods_ec: int = 5, frameshift_ms: float = 1.0
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """[HNR05, HNR15, HNR25, HNR35] = func_GetHNR(y, Fs, F0, variables)（整段分支）。"""
```

## 3. 翻译要点（对照蓝本行号）

### 主循环（L24–62）
- 骨架同 B1（N_periods_EC=5）。
- **L47–49 特有**：窗长偶数时 `yend = yend - 1`（强制奇数——倒谱需要奇长度，对照表注明）。
- L51–56 边界 continue 同前。

### getHNR 子函数（L67–127）——施工者逐行读，以下为结构导航（细节以蓝本为准）
1. L73：`y = y .* hamming(length(y))`。
2. L75–80 附近：倒谱/谱计算与峰位搜索（`peakinx` 循环 L80）——谐波谱 `Nap` 的构造（L106 附近 `Ha = aY - Nap` 谐波谱减近似）。
3. L117–126：4 个截止频率逐一平均：
   - `Ef = round(Nfreqs(k)/Fs * length(y))`（等价截止 quefrency 索引）
   - 谐波部分能量 / 全谱能量 → dB（具体公式以蓝本 L120–126 为准，逐行翻译并在对照表写明每步的域：倒谱域 or 功率谱域）。
4. **2.0 裁剪**：TextGrid 分支不实现；`handles` 不实现。

## 4. 测试（`tests/test_get_hnr.py`，原样照抄）

```python
# -*- coding: utf-8 -*-
"""HNR 测试。区间+相对关系断言；精确值走快照。禁改。"""
import os

import numpy as np

from backend.pysauce import framing
from backend.pysauce.get_hnr import get_hnr

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_hnr_sine_higher_than_noise():
    y1, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    y2, _ = framing.read_wav(os.path.join(FIX, "noise10.wav"))
    f0 = np.full(1000, 100.0)
    hnr05_sine, _, _, _ = get_hnr(y1, fs, f0)
    hnr05_noise, _, _, _ = get_hnr(y2, fs, np.full(1000, 100.0))
    assert np.median(hnr05_sine[200:800]) > np.median(hnr05_noise[200:800])


def test_hnr_sine_positive_finite():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    hnr05, hnr15, hnr25, hnr35 = get_hnr(y, fs, np.full(1000, 100.0))
    for h in (hnr05, hnr15, hnr25, hnr35):
        mid = h[200:800]
        assert not np.isnan(mid).any()
        assert (mid > -10).all() and (mid < 60).all()


def test_hnr_cutoff_ordering_sine():
    # 纯周期信号：截止频率越高（保留越少），HNR 越低（趋势性检查，允许个别帧反转）
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    h05, h15, h25, h35 = get_hnr(y, fs, f0)
    assert np.median(h05[200:800]) >= np.median(h35[200:800]) - 3.0


def test_hnr_nan_f0_and_edges():
    y, fs = framing.read_wav(os.path.join(FIX, "sine100.wav"))
    f0 = np.full(1000, 100.0)
    f0[500] = np.nan
    h05, _, _, _ = get_hnr(y, fs, f0)
    assert np.isnan(h05[500])
    assert np.isnan(h05[:15]).all()
```

> 快照：报告附 sine100/noise10/harm5 的 4 列中段前 20 值，验收员审核（sine HNR05 应在 20–60dB 区间、noise 接近 0 或负）后冻结 `get_hnr.json`。

## 5. 验收标准

1. 四个测试绿。
2. 对照表：getHNR L75–126 逐段（谱计算、峰搜索、Nap 构造、Ef 截断、dB 公式），每步标注数据域。
3. 报告注明快照待验收员生成。

## 6. 禁止事项

- 禁止把 4 个截止频率写成 4 个窗长（HNR05/15/25/35 = 截止频率 500/1500/2500/3500 Hz，蓝本 L68 `[500 1500 2500 3500]`）。
- 禁止去掉奇数长度强制（L47–49）。
- 禁止复用 CPP 的代码改出 HNR（两个算法倒谱后路径不同，必须独立对照蓝本实现）。

## 7. 停报条件

按总纲第 9 节。特别地：蓝本 L75–116 的倒谱→谐波/噪声分离若任何一步有两种解读（尤其 Nap 构造与 peakinx 循环），必停报。

---

## 8. 施工记录（2026-10-26）——⚠️ 停报（条件 #1 / 卡 §7 指定点）

### 8.1 已完成部分

- 创建 `ps-shell-v2/backend/pysauce/get_hnr.py`（194 行）：`get_hnr_for_frame`（蓝本 L67–127）
  + `get_hnr`（整段分支 L24–63）。主循环骨架、奇数窗长强制（L41–43）、`isnan` 判定、
  基线校正循环（L109–115）、dB 公式（L118–123）均已逐行对照翻译。
- 创建 `ps-shell-v2/tests/test_get_hnr.py`（卡 §4 原样照抄，未改）。
- 已修复实现 bug 2 处（自检阶段）：倒谱对称化切片（L101–102）奇偶长度对齐；
  基线校正 0-based 切片边界。修复后 **2 测试通过 / 2 测试失败**（失败见 §8.2、§8.3）。

### 8.2 ⚠️ 停报项 A：`sign(diff(ayseg))` 的复数语义（卡 §7 指定「peakinx 循环」两解）

**蓝本原文（L86–96）**：
```matlab
s_ayseg = sign(diff(ayseg));
l_inx = inx - find((s_ayseg(inx-1:-1:1) ~= sign(inx)), 1) + 1;
r_inx = inx + find((s_ayseg(inx+1:end) == sign(inx)), 1);
l_inx = l_inx + k*N0 - N0_delta - 1;
r_inx = r_inx + k*N0 - N0_delta - 1;
ay(l_inx:r_inx) = 0;
```

**关键事实（已实测）**：`ay = ifft(aY)`，`aY = log10(abs(Y))` 为**实向量**。MATLAB 文档明载
`ifft` 对**非共轭对称**输入返回复数——任意实向量不满足回文共轭对称条件，故 `ay` 是**复数**
（虚部为浮点残差 ~1e-14，非精确 0）。实测：`max|imag(ay)| = 2.2e-14`。

于是 `s_ayseg = sign(diff(ayseg))` 是**复数**（`z/|z|`，虚部 ~1e-14）。
MATLAB 的 `~=`/`==` 对复数**同时比较实部与虚部**：
- `(1+1e-14i) ~= 1` → **真**（虚部≠0）→ `find(...,1)` 恒返回 1 → `l_inx = inx`；
- `(1+1e-14i) == 1` → **假** → `find` 返回**空** → `r_inx = []`；
- `ay(l_inx:r_inx) = ay(inx:[])` → MATLAB 中 `A(5:[])` 为 1×0 空索引 → **赋值是 no-op**。

**即：忠实翻译下，L80–98 的「逐 rahmonic 峰 lifter 置零」在 MATLAB 里完全失效（惰性）。**

**两种合理解读**：
- **解读 A（忠实蓝本）**：按复数比较实现 → lifter 恒 no-op → `Nap` 即未 lifter 的倒谱反变换。
  实测 sine100 帧 500：`HNR = [29.35, 41.31, 46.24, 49.30]`。
- **解读 B（算法本意）**：`ay` 取实部（或把 `sign` 作用在实倒谱上）→ lifter 真正生效，围绕
  每个 rahmonic 置零一段。实测同帧：`HNR = [35.86, 46.96, 50.71, 53.09]`。

**独立仲裁证据**：de Krom(1993) 的独立再实现 phonlab.acoustic.HNR（明示「Shue 的 VoiceSauce
MATLAB 实现提供了 valuable pointers」）显示**本意 lifter 必须生效**，且用**固定带宽**：
```python
half_combwidth = 5
for k in range(1,4):
    C_cl[j, T0*k-(half_combwidth+1) : T0*k+half_combwidth] = 0   # 真置零
```
其倒谱用 `np.real(irfft(S))`（**实倒谱**），佐证「lifter 应作用在实倒谱上」。据此，
VS 版用 `sign(diff())` 自适应测峰宽的写法，**因复数比较而塌缩为 no-op**，属**已发布代码的
潜在缺陷**，而非算法本意。

**我的倾向**：**解读 A（忠实蓝本 no-op）**。理由：本卡（及全项目）第一原则是「忠实复刻
VoiceSauce 行为」，验收靠「与蓝本逐行对照」而非「与论文一致」；蓝本实际行为就是 no-op，
若取解读 B 等于**替上游修 bug**，会与 VS 输出不可比，且超出本卡白名单（须另立修正卡）。
（若验收员要求「算法正确性优先」，则取 B 并单开修正卡记录偏差。）

**此差异影响数值 ~6 dB，非容差级，必须由验收员拍板后方可定稿。**

### 8.3 停报项 B：`test_hnr_cutoff_ordering_sine` 与实测反向（卡 §4 测试疑有笔误）

**卡内断言（§4）**：
```python
def test_hnr_cutoff_ordering_sine():
    # 纯周期信号：截止频率越高（保留越少），HNR 越低（趋势性检查，允许个别帧反转）
    ...
    assert np.median(h05[200:800]) >= np.median(h35[200:800]) - 3.0
```

**实测（sine100，两种解读一致）**：截止频率**越高，HNR 越高**（单调递增）：
`median: HNR05=29.35 < HNR15=42.67 < HNR25=47.98 < HNR35=51.22`。
与卡内「截止越高 HNR 越低」的假设**方向相反**。物理解释：本算法的 `HNR = 20*mean(H[0:Ef])
- 20*mean(N[0:Ef])`，`H[0]`（DC bin）远高于高频区，**Ef 越大 → 纳入的平均值越小 → 反而越大**
（且 DC bin 主导，见 §8.4）。故该断言对纯正弦 fixture 不成立。

**结论**：此测试断言**疑似卡内笔误**（同 C5 卡 `test_zff_output_scale` 先例），建议改为：
`assert np.median(h05[200:800]) <= np.median(h35[200:800]) + 3.0`（或断言「单调不降」）。
**因总纲禁改测试断言，此处停报等验收员裁定。**

### 8.4 附：`test_hnr_sine_positive_finite` 的 `<60` 上界

实测部分帧 HNR 达 **60.02 dB**（略超卡内 `<60` 上界）；根因同 §8.3——`mean(H[0:Ef])` 含
DC bin（`aY[0]=-2.79`）导致数值偏高。若采解读 A 则 max=60.02、若采解读 B 则更高。
建议上界放宽至 `<70`。同样**停报等验收员裁定**。

### 8.5 当前状态

- 文件已就位，语法正确，`test_hnr_sine_higher_than_noise` 与 `test_hnr_nan_f0_and_edges` **通过**；
- 其余 2 测试待 §8.2（A/B 定稿）与 §8.3/§8.4（断言修正）裁定后复跑；
- 快照 `get_hnr.json` 待验收员生成（按卡 §5.3）。

---

## 9. 停报裁定与实施（2026-10-26 用户拍板）——✅ 完成

### 9.1 裁定结果

| 停报项 | 选项 | 用户裁定 |
|---|---|---|
| A：`sign(diff(ayseg))` 复数语义 | A=忠实 no-op / B=算法本意 lifter 生效 | **两个都要，代码加开关，默认 A** |
| B：卡 §4 两个测试断言 | 按实测修正 / 保持原样 | **按实测修正** |

### 9.2 实施

**① 双模式开关**（`get_hnr_for_frame` / `get_hnr` 新增 `lifter_mode` 参数）：
- `lifter_mode="faithful"`（**默认**）：`sign` 作用在**复数**倒谱 → 复数比较恒真/恒假 →
  `r_inx` 恒空 → 置零赋值 no-op（**忠实蓝本**，与 VS 输出可比）。
- `lifter_mode="intended"`：`sign` 作用在**实**倒谱（`diff_ayseg.real`）→ lifter 真正围绕
  每个 rahmonic 置零（**算法本意**，对照 de Krom 1993 / phonlab 独立再实现）。
- 非法值抛 `ValueError`。

**② 测试修正**（用户授权，卡 §4 原断言为笔误）：
- `test_hnr_cutoff_ordering_sine`：`h05 >= h35 - 3` → **`h05 <= h35 + 3`**，并加
  05≤15≤25≤35 单调不降校验（实测 `median 29.35<42.67<47.98<51.22`）。
- `test_hnr_sine_positive_finite`：上界 `<60` → **`<70`**（实测 max 60.02，DC bin 根因）。
- 新增 `test_hnr_lifter_mode_switch`：验证两模式均可运行且数值有差异（faithful HNR05 更低）。

### 9.3 验证

- `tests/test_get_hnr.py`：**5 passed**（原 4 + 新增 1）。
- 全套：**265 passed / 1 既有失败**（`test_rv1.test_partial`，1.2 同样失败，与本卡无关）。
- 1.2 `ps-shell/` 零改动（`git status --short ps-shell/` 空）。

### 9.4 数值对照（sine100，帧 500，5 周期窗）

| 模式 | HNR05 | HNR15 | HNR25 | HNR35 |
|---|---|---|---|---|
| faithful（默认） | 29.35 | 41.31 | 46.24 | 49.30 |
| intended | 35.86 | 46.96 | 50.71 | 53.09 |

（截断频率 = 500/1500/2500/3500 Hz，`Nfreqs` 固定，非窗长。）

### 9.5 待办

- 快照 `tests/fixtures/snapshots/get_hnr.json` 待验收员生成（默认 faithful 模式，卡 §5.3）。
- 若将来 UI「设置」需暴露 `lifter_mode`，在 V2-F3（vs 界面）/ F1（编排）卡接入。
