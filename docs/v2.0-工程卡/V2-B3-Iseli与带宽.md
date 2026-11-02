# V2-B3：Iseli 校正 + Hawks-Miller 带宽 → correct_iseli.py / get_bw_fmt.py

> 难度：低。前置：V2-A2、V2-A3。
> 蓝本：`refs/voicesauce-v137/func_correct_iseli_z.m`（32 行）、`refs/voicesauce-v137/func_getBWfromFMT.m`（37 行），均必读全文。

## 0. 目标一句话

① Iseli & Alwan 共振峰逆滤波校正（dB 标量函数，f 可为向量）；② 共振峰→带宽映射（Mannell / Hawks-Miller 两式）。B4 的四个斜率函数都建立在这两个函数之上。

## 1. 文件白名单

创建：
- `ps-shell-v2/backend/pysauce/correct_iseli.py`
- `ps-shell-v2/backend/pysauce/get_bw_fmt.py`
- `ps-shell-v2/tests/test_iseli_bw.py`

## 2. 函数签名（精确，禁改）

```python
# correct_iseli.py
def correct_iseli_z(f: np.ndarray, fx: "np.ndarray | float",
                    bx: "np.ndarray | float", fs: float) -> np.ndarray:
    """corr = func_correct_iseli_z(f, Fx, Bx, Fs)。

    f 必为数组；Fx/Bx 可为标量或与 f 等长向量（蓝本全向量化：B4 各斜率函数
    会把逐帧带宽向量 B1/B2/B3 直接传进来）。返回 dB 校正量，shape 同 f。
    """


# get_bw_fmt.py
def get_bw_fmt(fmt: np.ndarray, voiced_or_f0: np.ndarray | float,
                method: str | None = None) -> np.ndarray:
    """BW = func_getBWfromFMT(FMT, voiced[, method])。

    method=None            → Mannell 公式：BW=(80+120*FMT/5000)*(2-voiced)，voiced 为 0/1
    method='hm'            → Hawks-Miller 公式，此时第二参数是 F0（可为标量或逐帧向量）
    """
```

## 3. 翻译要点

### correct_iseli_z（蓝本 L18–25）

```matlab
r = exp(-pi*Bx/Fs);   omega_x = 2*pi*Fx/Fs;   omega = 2*pi*f/Fs;
a = r.^2 + 1 - 2*r.*cos(omega_x + omega);
b = r.^2 + 1 - 2*r.*cos(omega_x - omega);
corr = -10*(log10(a)+log10(b));          % L23 中间赋值（被 L25 覆盖的死代码）
corr = -10*(log10(a)+log10(b)) + 20*log10(num);   % 最终生效
```
- 蓝本 L23 是被 L25 覆盖的死代码：Python 侧**只写最终式**，但注释必须注明 `# MT-L23: 死代码，被 L25 覆盖`。
- `num = r.^2 + 1 - 2*r.*cos(omega_x)`（蓝本 L24，注释 omega=0）。
- f 传向量时 `a/b/omega` 全向量化；`fx/bx/fs` 是标量。
- NaN 传播：f 含 NaN → corr 对应位 NaN（numpy 自动，与 MATLAB 一致）。

### get_bw_fmt（蓝本 L7–38）

- Mannell 分支（L8–9）：`BW = (80 + 120*FMT/5000) * (2 - voiced)`。voiced 是 0/1（或 0/1 向量）。
- 'hm' 分支（L11–13 → 子函数 getbw_HawksMiller L21–37）：
  - 蓝本 `[r,c]=size(FMT); if r>c, FMT=FMT'` 只是行/列向量归一 → Python 一维数组无需处理，注释注明。
  - `S = 1+0.25*(F0-132)/88`（F0 标量时 S 标量；F0 向量时 S 向量，与 FMT 逐元素相乘——注意蓝本 L36 是 `S' .* (...)`，列向量转置后点乘）。
  - 系数（**照抄，一个数字不许错**）：
    `C1 = [165.327516, -6.73636734e-1, 1.80874446e-3, -4.52201682e-6, 7.49514000e-9, -4.70219241e-12]`
    `C2 = [15.8146139, 8.10159009e-2, -9.79728215e-5, 5.28725064e-8, -1.07099364e-11, 7.91528509e-16]`
  - `F = [ones; FMT; FMT.^2; FMT.^3; FMT.^4; FMT.^5]` → `np.vstack`，6×N。
  - `mask = FMT<500`；`BW = C1*(F.*mask) + C2*(F.*~mask)` 是 **1×6 矩阵 × 6×N 矩阵** → `C1 @ (F*mask) + C2 @ (F*(1-mask))`（矩阵乘不是点乘！）。
  - F0 为向量时 `S` 逐元素乘：`S * (C1 @ (F*mask) + C2 @ (F*(1-mask)))`。
- method 既非 None 又非 'hm' → raise ValueError（蓝本此情形返回未定义变量会报错，Python 显式抛错并注明）。

## 4. 测试代码（`tests/test_iseli_bw.py`，原样照抄；锚点由独立脚本 2026-10-26 复算）

```python
# -*- coding: utf-8 -*-
"""Iseli 校正 + Hawks-Miller 带宽测试。锚点脚本复算，禁改。"""
import numpy as np

from backend.pysauce.correct_iseli import correct_iseli_z
from backend.pysauce.get_bw_fmt import get_bw_fmt


class TestIseli:
    def test_scalar_anchor(self):
        out = correct_iseli_z(np.array([100.0]), 500.0, 100.0, 16000.0)
        assert np.allclose(out, [0.34473226], atol=1e-8)

    def test_vector_anchor(self):
        out = correct_iseli_z(np.array([100.0, 200.0, 400.0]), 500.0, 100.0, 16000.0)
        assert np.allclose(out, [0.34473226, 1.46422165, 7.99579131], atol=1e-8)

    def test_f_equals_fx(self):
        out = correct_iseli_z(np.array([500.0]), 500.0, 100.0, 16000.0)
        assert np.allclose(out, [14.08295183], atol=1e-8)

    def test_nan_propagates(self):
        out = correct_iseli_z(np.array([100.0, np.nan]), 500.0, 100.0, 16000.0)
        assert np.isnan(out[1])

    def test_vector_fx_bx(self):
        # Fx/Bx 逐帧向量（B4 斜率函数的调用形态）：常量向量应与标量版逐位一致
        out_v = correct_iseli_z(
            np.array([100.0, 100.0]), np.array([500.0, 500.0]),
            np.array([100.0, 100.0]), 16000.0)
        out_s = correct_iseli_z(np.array([100.0, 100.0]), 500.0, 100.0, 16000.0)
        assert np.allclose(out_v, out_s, atol=1e-12)


class TestGetBwFmt:
    def test_mannell_voiced(self):
        bw = get_bw_fmt(np.array([500.0, 1000.0]), 1)
        assert np.allclose(bw, [92.0, 104.0], atol=1e-12)

    def test_mannell_unvoiced(self):
        bw = get_bw_fmt(np.array([500.0, 1000.0]), 0)
        assert np.allclose(bw, [184.0, 208.0], atol=1e-12)

    def test_hawks_miller_anchor(self):
        bw = get_bw_fmt(np.array([500.0, 1500.0, 2500.0, 3500.0]), 132.0, "hm")
        assert np.allclose(
            bw, [37.79378652, 47.13594257, 91.09795961, 174.67769864], atol=1e-7)

    def test_hawks_miller_f0_scaling(self):
        bw = get_bw_fmt(np.array([600.0]), 200.0, "hm")
        assert np.allclose(bw, [46.8299303], atol=1e-7)

    def test_hawks_miller_per_frame_f0(self):
        # F0 逐帧向量：500Hz 帧 F0=100、1500Hz 帧 F0=200 → S 分别缩放
        bw = get_bw_fmt(np.array([500.0, 1500.0]), np.array([100.0, 200.0]), "hm")
        s1 = 1 + 0.25 * (100.0 - 132) / 88
        s2 = 1 + 0.25 * (200.0 - 132) / 88
        base = get_bw_fmt(np.array([500.0, 1500.0]), 132.0, "hm")
        assert np.allclose(bw, [base[0] * s1, base[1] * s2], atol=1e-9)

    def test_bad_method_raises(self):
        try:
            get_bw_fmt(np.array([500.0]), 1, "xx")
        except ValueError:
            pass
        else:
            raise AssertionError("method='xx' 应抛 ValueError")
```

## 5. 锚点推导（验收员核对用）

- Iseli 标量锚：`r=exp(-π·100/16000)=0.980556…`，`omega_x=π/16`、`omega=π/40`（均为特殊角，数值可复核）；最终 `-10(log10 a + log10 b) + 20 log10 num`。三个锚值由独立 Python 脚本复算（保留 8 位）。
- Hawks-Miller：F0=132 → S=1 精确；C1/C2 系数逐位照抄蓝本；500/1500/2500/3500 锚值脚本复算。
- Mannell：`BW=(80+120·FMT/5000)·(2-voiced)`：F=500 → 80+12=92（voiced）；F=1000 → 80+24=104；unvoiced ×2 → 184/208。

## 6. 验收标准

1. 三文件与签名/测试一致（除 docstring）。
2. `pytest ps-shell-v2/tests/ -x -q` 全绿（累计 ≥40 passed）。
3. 交付含蓝本对照表（重点核对 C1/C2 系数逐位一致）。

## 7. 禁止事项

- 禁止合并 `a/b` 两式或重排 `num` 计算。
- 禁止把 `C1 @ (...)` 写成 `(C1 * ...).sum()` 之外的等价形式（保持矩阵乘记号）。
- 禁止改测试（含 §5 提示的可能停报项）。

## 8. 停报条件

按总纲第 9 节。

---

## 9. 实施记录（施工者填，2026-10-26）

**状态**：完成。11 例全绿。两文件均无卡缺陷，逐行照抄。

### 9.1 蓝本对照表

**correct_iseli_z**（蓝本 L25–33；卡注的 L18–25 系旧行号，实际公式在 L25–33）

| 蓝本行 | MATLAB | Python | 说明 |
|---|---|---|---|
| L25 | `r = exp(-pi*Bx/Fs)` | `r = np.exp(-np.pi*bx/fs)` | |
| L26 | `omega_x = 2*pi*Fx/Fs` | `omega_x = 2*np.pi*fx/fs` | |
| L27 | `omega = 2*pi*f/Fs` | `omega = 2*np.pi*f/fs` | |
| L28 | `a = r.^2+1-2*r.*cos(omega_x+omega)` | `a = r**2+1-2*r*np.cos(omega_x+omega)` | |
| L29 | `b = r.^2+1-2*r.*cos(omega_x-omega)` | `b = r**2+1-2*r*np.cos(omega_x-omega)` | |
| L30 | `corr = -10*(log10(a)+log10(b))` | `corr = -10*(np.log10(a)+np.log10(b))` | 未归一化式（被 L33 覆盖） |
| L32 | `num = r.^2+1-2*r.*cos(omega_x)` | `num = r**2+1-2*r*np.cos(omega_x)` | omega=0 |
| L33 | `corr = -10*(...) + 20*log10(num)` | `corr = corr + 20*np.log10(num)` | 最终生效 |

- **死代码**：蓝本 L30 被 L33 覆盖；Python 只写最终式，注释标 `# MT-L23(卡注): 死代码，被 L33 覆盖`。
- **向量化**：`f`、`fx`、`bx` 均经 `np.asarray(float64)`，标量/数组通吃（B4 会传逐帧带宽向量）。NaN 传播与 MATLAB 一致（numpy 自动）。

**get_bw_fmt**（蓝本 L1–37）

| 蓝本行 | MATLAB | Python | 说明 |
|---|---|---|---|
| L7-8 | `if (nargin==2) BW=(80+120*FMT/5000)*(2-voiced)` | `if method is None: return (80+120*fmt/5000)*(2-voiced_or_f0)` | Mannell |
| L10-12 | `elseif (nargin==3 && strcmp(method,'hm')) F0=voiced; BW=getbw_HawksMiller(FMT,F0)'` | `if method=='hm': f0=...; ...` | |
| L22-25 | `[r,c]=size(FMT); if r>c, FMT=FMT'` | 无需处理（一维数组） | 仅行列归一 |
| L27 | `S = 1+0.25*(F0-132)/88` | `s = 1+0.25*(np.asarray(f0)-132)/88` | |
| L30 | `C1 = [165.327516, -6.73636734e-1, ...]` | `_C1 = np.array([...])` | **逐位一致** |
| L31 | `C2 = [15.8146139, 8.10159009e-2, ...]` | `_C2 = np.array([...])` | **逐位一致** |
| L33 | `F = [ones(1,N); FMT; FMT.^2; ...; FMT.^5]` | `f_poly = np.vstack([...])` | 6×N |
| L34-35 | `mask = FMT<500; mask = repmat(...)` | `mask = (fmt<500).astype(float)` | |
| L37 | `BW = S' .* (C1*(F.*mask) + C2*(F.*~mask))` | `bw = s*(_C1@(f_poly*mask) + _C2@(f_poly*(1-mask)))` | **矩阵乘**非点乘 |
| — | method 非法 → 返回未定义 BW 报错 | `raise ValueError(...)` | 显式化 |

**C1/C2 系数逐位核对**：C1 `[165.327516, -6.73636734e-1, 1.80874446e-3, -4.52201682e-6, 7.49514000e-9, -4.70219241e-12]`；C2 `[15.8146139, 8.10159009e-2, -9.79728215e-5, 5.28725064e-8, -1.07099364e-11, 7.91528509e-16]` —— 与蓝本 L30/L31 逐字符相同。

### 9.2 锚点独立复算（施工前验证，全匹配）

```
Iseli [100]          -> [0.34473226]                          ✅
Iseli [100,200,400]  -> [0.34473226 1.46422165 7.99579131]    ✅
Iseli [500]          -> [14.08295183]                         ✅
Mannell v=1          -> [92. 104.]                            ✅
Mannell v=0          -> [184. 208.]                           ✅
HM F0=132            -> [37.79378652 47.13594257 91.09795961 174.67769864]  ✅
HM F0=200 (F=600)    -> [46.8299303]                          ✅
HM per-frame F0      -> base*s 一致 (atol 1e-9)               ✅
```

### 9.3 验收命令原始输出

```
$ python -m pytest ps-shell-v2/tests/test_iseli_bw.py -q
...........                                                              [100%]
11 passed in 0.17s

$ python -m pytest ps-shell-v2/tests/ -q
1 failed, 225 passed
（唯一失败 = test_rv1.test_partial，1.2 既有失败）
```
