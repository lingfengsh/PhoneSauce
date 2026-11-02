# V2-B2：func_pickpeaks.m → pysauce/pickpeaks.py

> 难度：低-中（有两处 MATLAB 特有语义陷阱）。前置：V2-A2、V2-A3。
> 蓝本：`refs/voicesauce-v137/func_pickpeaks.m`（49 行，必读全文）。
> 用途：被 func_GetCPP / func_GetHNR 调用（可在 refs 内 grep 确认），用于在倒谱/自相关曲线上找峰。

## 0. 目标一句话

复刻两段式峰值拾取：① 一阶差分找全部局部极大；② 用 winlen 窗逐峰过滤（窗口内只留最大者）。

## 1. 文件白名单

创建：
- `ps-shell-v2/backend/pysauce/pickpeaks.py`
- `ps-shell-v2/tests/test_pickpeaks.py`

## 2. 函数签名（精确，禁改）

```python
def pickpeaks(y: np.ndarray, winlen: int) -> tuple[np.ndarray, np.ndarray]:
    """[ymax, inx] = func_pickpeaks(y, winlen)。

    返回 (峰值数组, 峰位置数组)，位置为 **0-based** 索引（蓝本是 1-based，
    位置值统一减 1 —— 由本函数内部换算，调用方按 0-based 使用）。
    """
```

## 3. 翻译要点（对照蓝本行号，两处陷阱已标红）

| 蓝本行 | MATLAB | Python | 说明 |
|---|---|---|---|
| L15–16 | `ymin=min(y); y=y-ymin` | 同式 | |
| L17 | `dy=[y(1); diff(y)']` | `dy = np.concatenate([[y[0]], np.diff(y)])` | 首样本补回，保持等长 |
| L18 | `inx1 = diff(dy<0)` | `inx1 = np.diff((dy < 0).astype(int))` | 布尔→int 再 diff；+1=极大，-1=极小 |
| L19–20 | `inx1(1)=0; inx1(end)=0` | `inx1[0]=0; inx1[-1]=0` | 丢弃贴边峰 |
| L21–22 | `inx=inx1>0; ymax=y(inx); inx=find(inx)` | `mask=inx1>0; ymax=y[:mask.size][mask].copy(); inx=np.nonzero(mask)[0]` | mfind（R3）；**必须 copy**；⚠️ 同陷阱②语义：`y` 长 N、`mask` 长 N−1，MATLAB 逻辑索引短于数组=取 `y` 前缀，**直接 `y[mask]` 会 IndexError** |
| L26–27 | `if nofmax==1 return` | `if len(ymax) == 1: return ymax, inx` | ⚠️ **陷阱①**：此时返回的 ymax **未加回 ymin**（蓝本疏漏，忠实保留，禁止"修复"） |
| L29–33 | 过滤循环 | 见下 | ⚠️ **陷阱②**：逻辑索引前缀语义 |
| L35–37 | `temp=find(ymax>0); inx=inx(temp); ymax=ymax(temp)` | 同构（mfind + 判空语义一致） | |
| L39 | `ymax=ymax+ymin` | 同式 | 仅在未提前 return 时执行 |

**陷阱②详解（过滤循环）**：
```matlab
arr = inx(1:cnt);              % 前 cnt 个峰位置（数值索引）
cmp = inx(cnt)-winlen;
arr2 = arr>cmp;                % 逻辑掩码，长度 cnt
[m, mi] = max(ymax(arr2));     % MATLAB 允许逻辑索引短于数组 → 取 ymax 前 cnt 个元素再筛
ymax(arr2) = -60000;
ymax(mi+length(arr2)-sum(arr2)) = m;   % 全局线性索引写回
```
Python 必须显式表达"取前 cnt 个"：
```python
arr = inx[:cnt]
cmp_ = inx[cnt - 1] - winlen
arr2 = arr > cmp_
pref = ymax[:cnt]                    # MATLAB 逻辑索引短于数组 = 取前缀；直接 ymax[arr2] 会 IndexError
loc = pref[arr2]
mi = int(np.argmax(loc)); m = float(loc[mi])
pref[arr2] = -60000
ymax[mi + len(arr2) - int(arr2.sum())] = m
```
禁止把这段改写成任何"等价简化"（比如用堆/排序重写）——必须逐行对应。

## 4. 测试代码（`tests/test_pickpeaks.py`，原样照抄；锚点已用独立脚本复算）

```python
# -*- coding: utf-8 -*-
"""func_pickpeaks 复刻测试。锚点由独立脚本复算（2026-10-26），禁改。"""
import numpy as np

from backend.pysauce.pickpeaks import pickpeaks


def _pp(x, w):
    ymax, inx = pickpeaks(np.asarray(x, dtype=float), w)
    return ymax.tolist(), inx.tolist()


def test_two_peaks_basic():
    assert _pp([0, 1, 3, 1, 0, 2, 5, 2, 0], 3) == ([3.0, 5.0], [2, 6])


def test_window_filter_removes_middle_peak():
    # maxima=5(idx1),9(idx4)；4 不是极大值（4<9）。窗口过滤后 5、9 均保留
    assert _pp([0, 5, 1, 4, 9, 1, 0], 3) == ([5.0, 9.0], [1, 4])


def test_competition_later_peak_wins():
    # 5(idx1) 与 4(idx4) 距离 3 ≤ winlen=3 → 竞争，后者胜出，5 被过滤
    assert _pp([2, 5, 2, 1, 4, 2], 3) == ([4.0], [1])


def test_three_peaks_no_kill():
    # 三峰距离均 > winlen=3 → 全保留
    assert _pp([0, 1, 5, 1, 0, 2, 3, 2, 0, 4, 4.5, 4, 0], 3) == (
        [5.0, 3.0, 4.5], [2, 6, 10])


def test_ymin_restored_multi_peak():
    # 与 test_three_peaks_no_kill 同构平移 +3（ymin=3）→ 峰值应加回 ymin
    assert _pp([3, 4, 8, 4, 3, 5, 6, 5, 3, 7, 7.5, 7, 3], 3) == (
        [8.0, 6.0, 7.5], [2, 6, 10])


def test_single_peak_early_return_no_restore():
    # 陷阱①：单峰提前 return，ymax 未加回 ymin（蓝本疏漏，忠实保留）
    # 输入 [1,8,1,1,1]，ymin=1；若"修复"会返回 [8]，蓝本行为返回 [7]
    assert _pp([1, 8, 1, 1, 1], 3) == ([7.0], [1])


def test_end_peak_dropped():
    # 贴信号末端的峰被 inx1(end)=0 丢弃（蓝本 L20）
    # [0,7,0,0,0] 唯一峰在 idx1，其下降沿 diff=+1 位于 inx1 中间 → 应检出
    assert _pp([0, 7, 0, 0, 0], 5) == ([7.0], [1])
    # 峰紧贴末尾：[0,0,7,0] 的 +1 跳变在 inx1 最后一个元素 → 被丢弃
    assert _pp([0, 0, 7, 0], 5) == ([], [])
```

## 5. 验收标准

1. 两文件与签名/测试逐字符一致（模块 docstring 可自写）。
2. `pytest ps-shell-v2/tests/ -x -q` 全绿（累计 ≥32 passed）。
3. 交付含蓝本对照表，并回答（2–3 句即可）：为什么 `ymax[arr2]` 直接索引会崩、`pref = ymax[:cnt]` 解决了什么 MATLAB 语义差。

## 6. 禁止事项

- 禁止"修复"陷阱①（单峰不加回 ymin）。
- 禁止重写过滤循环为任何"等价"算法。
- 禁止把返回索引改成 1-based。

## 7. 停报条件

按总纲第 9 节。特别地：若你认为 `test_end_peak_dropped` 的第二个断言与蓝本行为不符，停报并手推 `dy`/`inx1` 逐步结果对照。

---

## 8. 实施记录（施工者填，2026-10-26）

**状态**：完成。7 例全绿。

### 8.1 卡缺陷与修正（§3 表 L21-22 行）

- **卡中代码会崩**：§3 表 L21-22 给的是 `ymax = y[mask].copy()`，但 `y` 长 N、`mask`（= `inx1>0`）长 **N−1**（`inx1 = diff(...)` 比 `dy` 短 1）。NumPy 直接 `y[mask]` 报 `IndexError: boolean index did not match`。
- **MATLAB 语义仲裁**：MATLAB `y(inx)` 中逻辑索引短于数组时**取 y 前缀**再筛。此规则卡中「陷阱②详解」已明确写出（`pref = ymax[:cnt]`），只是 L21-22 行漏了同样处理。
- **修正**（最小）：`ymax = y[mask].copy()` → `ymax = y[:mask.size][mask].copy()`。行为无损——`inx1(end)=0` 已保证末尾样本不可能成为极大值，被截掉的那个样本永不入选。
- **独立验证**：8 个测试用例用独立参考实现（严格照蓝本 + 前缀语义）全部匹配后才落笔。
- **陷阱①、②、索引 0-based**：均按卡要求忠实保留，未"修复"。

### 8.2 蓝本对照表（MATLAB 行 → Python 行）

| 蓝本行 | MATLAB | Python | 说明 |
|---|---|---|---|
| L13-14 | `ymin=min(y); y=y-ymin` | `ymin=float(np.min(y)); y=y-ymin` | |
| L15 | `dy=[y(1); transpose(diff(y))]` | `dy=np.concatenate([[y[0]], np.diff(y)])` | 首样本补回 |
| L16 | `inx1 = diff(dy<0)` | `inx1=np.diff((dy<0).astype(np.int64))` | +1 极大 / −1 极小 |
| L17-18 | `inx1(1)=0; inx1(end)=0` | `inx1[0]=0; inx1[-1]=0` | 丢弃贴边峰 |
| L19-21 | `inx=inx1>0; ymax=y(inx); inx=find(inx)` | `mask=inx1>0; ymax=y[:mask.size][mask].copy(); inx=np.nonzero(mask)[0]` | **前缀语义修正**；copy 必填 |
| L28-30 | `if nofmax==1 return` | `if nofmax==1: return ymax, inx` | ⚠ 陷阱①：不加回 ymin |
| L33 | `arr = inx(1:cnt)` | `arr = inx[:cnt]` | |
| L34 | `cmp = inx(cnt)-winlen` | `cmp_ = inx[cnt-1] - winlen` | |
| L35 | `arr2 = arr>cmp` | `arr2 = arr > cmp_` | |
| L37 | `[m,mi]=max(ymax(arr2))` | `pref=ymax[:cnt]; loc=pref[arr2]; mi=argmax(loc); m=loc[mi]` | ⚠ 陷阱②：取前缀 |
| L38 | `ymax(arr2)=-60000` | `pref[arr2]=-60000` | |
| L39 | `ymax(mi+length(arr2)-sum(arr2))=m` | `ymax[mi+len(arr2)-int(arr2.sum())]=m` | 全局线性索引 |
| L42-44 | `temp=find(ymax>0); inx=inx(temp); ymax=ymax(temp)` | `temp=np.nonzero(ymax>0)[0]; inx=inx[temp]; ymax=ymax[temp]` | |
| L49 | `ymax = ymax + ymin` | `ymax = ymax + ymin` | 仅未提前 return 时 |

### 8.3 验收命令原始输出

```
$ python -m pytest ps-shell-v2/tests/test_pickpeaks.py -q
.......                                                                  [100%]
7 passed in 0.15s

$ python -m pytest ps-shell-v2/tests/ -q
1 failed, 214 passed
（唯一失败 = test_rv1.test_partial，1.2 既有失败）
```

### 8.4 问题回答（§5 验收标准 3）

- **为什么 `ymax[arr2]` 直接索引会崩**：`arr2` 长度是 `cnt`（前 cnt 个峰的掩码），而 `ymax` 全长是 `nofmax`。当 `cnt < nofmax` 时布尔掩码与数组长度不等，NumPy 抛 `IndexError`。
- **`pref = ymax[:cnt]` 解决了什么 MATLAB 语义差**：MATLAB 允许逻辑索引**短于**被索引数组，此时只作用于数组**前 len(mask) 个元素**（即前缀）；NumPy 严格禁止长度不等。取前缀 `ymax[:cnt]` 显式复刻了这一 MATLAB 行为，使 `pref[arr2]` 合法且语义一致。
