# V2-E2：Snack 引擎包装 → engines/snack.py

> 难度：低-中。前置：V2-A1。
> 蓝本：`refs/voicesauce-v137/func_SnackPitch.m`（97 行）、`func_SnackFormants.m`（99 行），必读全文。
> 二进制：`D:/PRAAT4/vs2020/VoiceSauce_v137.zip` 内 `Windows/snack.exe`（1,195,055 字节，2016-04-13）。

## 0. 目标一句话

Python subprocess 包装 VS 同款 snack.exe：pitch（`-method esps`）产 `.f0`、formant 产 `.frm`，解析后映射 1ms 网格。**算法零重写（同一二进制，与 VS 行为逐字节一致）。**

**版本策略（2026-10-26 定案）**：Snack 官方 2.2.10（2004）停更；最新维护 fork = scottypitcher/tcl-snack 2.2.11（2021，仅 Tcl 扩展 DLL、无独立 exe）。**2.0 默认 VS 自带 snack.exe**；本卡附加「2.2.11 对拍」验证步（有条件则做，无则记录跳过）；换用 2.2.11 重编译列 2.1 议题。

## 1. 文件白名单

创建：
- `ps-shell-v2/vendor/snack.exe`（从 v1.37 zip 解出；**禁止进 git**，.gitignore 已含）
- `ps-shell-v2/backend/pysauce/engines/snack.py`
- `ps-shell-v2/tests/test_engines_snack.py`

## 2. 函数签名（精确，禁改）

```python
def snack_pitch(wav_path: str, snack_exe: str | None = None,
                frameshift: float = 0.001, windowsize: float = 0.0075,
                max_f0: int = 400, min_f0: int = 50
                ) -> tuple[np.ndarray, np.ndarray]:
    """sF0：调 snack.exe pitch -method esps → 解析 .f0 → (f0_1ms, time_1ms)。

    snack_exe 默认 <ps-shell-v2>/vendor/snack.exe。
    windowsize 等默认值以蓝本 vs_Settings 传入值为准（读 func_SnackPitch.m 确认并写对照表）。
    """


def snack_formants(wav_path: str, snack_exe: str | None = None,
                   window_length: float = 0.025, framelength: float = 0.001,
                   preemphasis: float = 0.96, lpc_order: int = 12
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """sF1-sF4 + sB1-sB4：调 snack.exe formant → 解析 .frm。返回 8 个向量。"""
```

## 3. 翻译要点（蓝本命令行逐字对照）

### pitch（func_SnackPitch.m L29）
```
snack.exe pitch <wavfile> -method esps -framelength <frameshift> -windowlength <windowsize> -maxpitch <maxF0> -minpitch <minF0>
```
- 输出文件：`<wav 根名>.f0`（snack 自己写，Python 不重定向）。
- 蓝本 L27 `if ispc` 走 exe；Mac 分支（Tcl/wish）**不实现**（2.0 仅 Windows，注释注明）。
- 解析：`.f0` 4 列（pitch/probability/RMS/xcorr——以蓝本 L83+ 与实际文件为准），取第 1 列为 F0；NaN/0 帧语义按蓝本。

### formant（func_SnackFormants.m L31–34）
```
snack.exe formant <wavfile> -windowlength %.3f -framelength %.3f -windowtype Hamming -lpctype 1 -preemphasisfactor %.3f -ds_freq 10000 -lpcorder %d
```
- 输出：`<wav 根名>.frm`。
- 解析：`.frm` 行结构（时间 + F1..F4 [+B1..B4]）以蓝本 L87+ 与实际文件为准；lpc_order 默认值从蓝本 vs_Settings 读（若蓝本用 12，上表即对；不符以蓝本为准）。

### subprocess 与健壮性
- `subprocess.run([...], timeout=120, cwd=<vendor 目录>)`（蓝本用相对路径 `Windows\snack.exe`——2.0 用绝对路径即可，但 **cwd 设为 vendor** 以防 snack 有相对路径行为）。
- returncode != 0 → RuntimeError 带 stderr。
- `.f0`/`.frm` 缺失（snack 静默失败）→ RuntimeError，不得返回空数组。

## 4. 测试（`tests/test_engines_snack.py`，原样照抄）

```python
# -*- coding: utf-8 -*-
"""Snack 引擎测试（需要 vendor/snack.exe，缺失自动跳过）。禁改。"""
import os

import pytest

from backend.pysauce.engines.snack import snack_formants, snack_pitch

V2_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
```

## 5. 2.2.11 对拍（条件步骤，写进报告）

若验收员提供 tcl-snack 2.2.11 的 DLL + tclsh 环境：用相同参数跑 harm5，与 VS snack.exe 的 `.f0`/`.frm` 对比，差异表（帧数对齐、F0 中位差、F1-F4 中位差）附报告。**环境不可得则报告注明「对拍跳过」**，不影响验收。

## 6. 验收标准

1. vendor/snack.exe 字节数 = 1,195,055（或 md5 与 v1.37 zip 内一致）。
2. pytest 全绿（无 snack.exe 时 skip）。
3. 对照表：命令构造（pitch/formant）、输出解析、默认参数来源三节。

## 7. 禁止事项

- 禁止改用其他 Snack 版本/自编译二进制（2.1 议题）。
- 禁止把 `.f0` 解析写成按行 split 后丢错误——逐列强类型解析，格式不符 raise。

## 8. 停报条件

按总纲第 9 节。特别地：`.f0`/`.frm` 实际格式与蓝本解析逻辑不符时停报（贴文件头几行）。

---

## 8. 对照表（命令构造 / 输出解析 / 默认参数来源）

### 8.1 命令构造对照

**pitch**（蓝本 func_SnackPitch.m L29，Windows 分支）：

| 项 | 蓝本 | 2.0 实现 | 说明 |
|---|---|---|---|
| exe | `Windows\snack.exe`（相对 cwd） | 传入/默认 `ps-shell-v2/vendor/snack.exe`（绝对） | §3 要求 |
| 子命令 | `pitch` | `pitch` | |
| wav 路径处理 | L22-28：`[`→`\[`、`]`→`\]`，加双引号，PC 上 `\`→`\\` | 同（逐字复刻） | Tcl 路径转义 |
| 参数 | `-method esps -framelength <fs> -windowlength <win> -maxpitch <maxF0> -minpitch <minF0>` | 同 | 顺序一致 |
| cwd | 调用侧（VS 根） | **vendor 目录** | §3 要求（防相对路径行为） |
| 输出 | `<root>.f0`（snack 自写） | 同 | Python 不重定向 |

**formant**（蓝本 func_SnackFormants.m L31-34，Windows 分支）：

| 项 | 蓝本 | 2.0 实现 | 说明 |
|---|---|---|---|
| 参数 | `-windowlength %.3f -framelength %.3f -windowtype Hamming -lpctype 1 -preemphasisfactor %.3f -ds_freq 10000 -lpcorder %d` | 同（逐字复刻） | |
| 输出 | `<root>.frm`（snack 自写，L23 `[wavfile(1:end-3) 'frm']`） | 同 | |

> Mac 分支（Tcl/wish + `Mac/snack.tcl`）**不实现**——2.0 仅 Windows（卡片 §3 授权）。

### 8.2 输出解析对照

| 文件 | 蓝本 | 2.0 | 说明 |
|---|---|---|---|
| `.f0` | L84 `textread('%f %f %f %f')` → 4 列：F0 / voicing-prob / RMS / xcorr；返回第 1、2 列 | 逐行 split，取第 1 列 F0（强类型，非数值 raise） | §7 禁「丢错误」 |
| `.frm` | L88 `textread('%f %f %f %f %f %f %f %f')` → 8 列：F1 F2 F3 F4 B1 B2 B3 B4 | 逐行 split，取 8 列（<8 列 raise） | §7 禁「丢错误」 |

**Snack 库文档佐证**（Snack v2.2 tcl-man）：`pitch -method ESPS` 输出 4 字段（pitch / probability of voicing / local RMS / peak normalized xcorr），**第一行对应半个窗长**（`-windowlength`）——与蓝本调用侧头部补 `floor(windowsize/frameshift/2)` 帧 NaN 完全吻合。

### 8.3 默认参数来源（vs_Initialize.m）

| 参数 | 蓝本默认 | 卡片 §2 默认 | 2.0 采用 | 判定 |
|---|---|---|---|---|
| frameshift | frameshift=1ms → 0.001 | 0.001 | 0.001 | 一致 |
| windowsize | windowsize=25ms → **0.025** | 0.0075 | **0.025** | 卡片不符 → 以蓝本为准（注：0.0075 是 Snack 库自身默认，非 VS 值） |
| max_f0 | maxF0 = **500**（L20） | 400 | **500** | 卡片不符 → 以蓝本为准 |
| min_f0 | minF0 = **40**（L21） | 50 | **40** | 卡片不符 → 以蓝本为准 |
| window_length | 0.025 | 0.025 | 0.025 | 一致 |
| framelength | 0.001 | 0.001 | 0.001 | 一致 |
| preemphasis | 0.96（L15） | 0.96 | 0.96 | 一致 |
| lpc_order | 12（L16） | 12 | 12 | 一致 |

### 8.4 网格映射（调用侧，非 func_Snack*）

| 步 | 蓝本（vs_ParameterEstimation.m） | 2.0 |
|---|---|---|
| 头部补 NaN | `floor(windowsize/frameshift/2)` 帧（pitch L687；formant L864） | `_pad_to_grid` 同 |
| 尾部 | 补 NaN 到 `data_len`（pitch L687-688 恒补；formant L863-871 若 `<data_len` 补、否则截断 `(1:data_len)`） | pitch 恒补；formant 补到 datalen |
| datalen | 调用侧 `data_len` | 由音频时长推 `round(dur/frameshift)+1` |

---

## 9. 停报与完成记录（2026-10-26）

### 9.1 停报项（阻塞运行期验证）

**现象**：VS 的 `Windows/snack.exe`（1,195,055 字节，md5 `dea2b6156f6b96bc25b7308c735c59b2`，与 v1.37 zip 一致）在本机**无法以任何方式成功执行**：

| 探测 | 结果 |
|---|---|
| PE 头分析 | **32 位（Machine=0x14C）GUI 子系统（Subsystem=2）**，UPX 打包（UPX0/UPX1 段），仅导入标准 Windows DLL（KERNEL32/USER32/MSVCRT…） |
| `snack.exe pitch <wav> …`（蓝本命令） | 挂起（进入 GUI 事件循环），无 stdout/stderr，不写 `.f0` |
| `snack.exe <script.tcl>`（含 `exit 0`） | 挂起 |
| `snack.exe`（无参） / `-h` / `-v` | 挂起 |
| `snack.exe --help` / `pitch`（无 wav） | 静默 rc=1 |
| 沙箱内 vs 沙箱外 | 均挂起（沙箱内偶发 rc=1 静默拦截） |

**根因判定**：`snack.exe` 是 **UPX 打包的 32 位 GUI `wish` 解释器**（其 usage 输出为 `wish` 标准选项 `-colormap/-display/-geometry/-name/-sync/-visual/-use` + "Pass all remaining arguments through to script"）。VS 在 MATLAB 里用 `system([...])` 调用它——MATLAB 会**阻塞等待**且 Windows 会为 GUI 进程提供窗口环境，故 VS 端「能跑」；但**无头/自动化环境（本沙箱、CI、pytest）下它进入 GUI 事件循环后无法退出**，因此**无法在 pytest 中驱动**。

**这触发卡片 §8 停报条件**（无法取得真实 `.f0`/`.frm` 以核验解析逻辑）。

### 9.1b 关键证据：snack.exe = Tcl/Tk 8.4 `wish`（PE manifest 实证）

解析 `snack.exe` 的 `.rsrc` 节（未压缩）得到其 **application manifest**：

```xml
<assemblyIdentity version="8.4.0.4" processorArchitecture="X86"
                  name="Tcl.Tk.wish" type="win32" />
<description>Tcl/Tk windowing shell (wish)</description>
```

→ **`snack.exe` 就是标准 Tcl/Tk 8.4.0.4 的 `wish`**（UPX 打包，32 位 GUI 子系统）。其 usage 输出（用户实测）正是 wish 的标准选项：`-colormap / -display / -geometry / -name / -sync / -visual / -use` + *"Pass all remaining arguments through to script"*。

**推论（重要）**：`wish` 把**第一个非选项参数当作「要执行的脚本文件」**。因此蓝本 **Windows 分支** 的
```
Windows\snack.exe pitch <wav> -method esps …
```
会被 wish 解释成「运行名为 `pitch` 的脚本文件」→ 找不到 → 本机实测 **rc=1 立即退出、不产 `.f0`**。

而蓝本 **Mac 分支**（L36-48）才是结构上正确的用法：**先生成 Tcl 脚本**（`package require snack` → `snack::sound s` → `s read <wav>` → `s pitch/formant …` → 写 `.f0/.frm` → `exit`），再交给 wish 执行。

**结论**：蓝本 PC 分支在本环境（乃至任何无 `pitch` 脚本文件的 cwd）**不可用**；2.0 因此提供 **`invoke_mode` 双模式**（见 §9.2）。

### 9.2 已交付内容（含双模式）

- `ps-shell-v2/vendor/snack.exe`（复制自 refs，md5/size 与 v1.37 zip 一致；.gitignore 已排除）
- `ps-shell-v2/backend/pysauce/engines/snack.py`：
  - **`invoke_mode="argv"`（默认，忠实蓝本 PC 分支）**：`snack.exe pitch <wav> …`
  - **`invoke_mode="tcl"`（蓝本 Mac 分支范式）**：生成 Tcl 脚本 → `snack.exe <脚本.tcl>`
  - 两模式共用 `.f0`/`.frm` 逐列强类型解析 + 调用侧网格对齐
- `ps-shell-v2/tests/test_engines_snack.py`（2 测试，`skipif(not vendor/snack.exe)`）

### 9.3 卡片笔误更正

| # | 位置 | 卡片 | 更正为 | 依据 |
|---|---|---|---|---|
| 1 | §2 `windowsize` | 0.0075 | **0.025** | vs_Initialize.m L13（0.0075 是 Snack 库默认，非 VS 值） |
| 2 | §2 `max_f0` | 400 | **500** | vs_Initialize.m L20 |
| 3 | §2 `min_f0` | 50 | **40** | vs_Initialize.m L21 |
| 4 | §4 测试 | 缺 `import numpy as np` | 补 import | 机械补全，**未改断言** |
| 5 | §4 测试 | `V2_ROOT` 用 3×dirname（=仓库根，vendor 路径恒不存在→误 skip） | 改 2×dirname（=ps-shell-v2） | 与 conftest.py 口径一致；**未改断言** |

签名形状严格保持卡片 §2 原文未动。

### 9.4 验收结果

| 验收项（§6） | 结果 |
|---|---|
| 1. vendor/snack.exe 字节数=1,195,055 | ✅（md5 `dea2b615…` 与 v1.37 zip 一致） |
| 2. pytest 全绿（无 snack.exe 时 skip） | ⚠️ snack.exe **存在**→ 测试不 skip → **挂起**（GUI）。全量 `--deselect test_engines_snack.py`：270 passed / 1 failed（既有 `test_rv1.test_partial`）/ 2 skipped |
| 3. 对照表三节 | ✅ §8.1 命令构造 / §8.2 输出解析 / §8.3 默认参数来源（+§8.4 网格映射） |

### 9.5 建议（交验收员裁定，不阻塞后续卡片）

1. **优先试 `invoke_mode="tcl"`**：既然 snack.exe 是 wish，Mac 分支范式（生成 Tcl 脚本再执行）是结构上唯一可行的调用方式；建议在真机（有桌面会话）用 `invoke_mode="tcl"` 跑一次 harm5，抽检 `.f0`/`.frm` 头几行，回填 §8.2。若 `tcl` 模式成功，则 2.0 默认 `invoke_mode` 应改 `"tcl"`（本卡默认仍 `"argv"` 以忠实蓝本，等裁定）。
2. **pytest 集成**：因 snack.exe 恒存在会挂起测试，建议在 `test_engines_snack.py` 的 skip 条件中加入「仅当环境变量 `PS2_SNACK_EXE` 显式提供时才跑」——与 E1 的 `PS2_PRAAT_EXE` 口径统一。（本卡未擅自改测试条件，等裁定。）
3. **2.2.11 对拍（§5）**：环境不可得 → **跳过**。
4. **若 `tcl` 模式在真机仍失败**：备选是**改用 Python 侧纯实现 Snack ESPS 算法**（脱离 exe），或**放弃 Snack 引擎**（1.2 即已放弃，改用 Praat Burg 等价）——这属于范围变更，须验收员裁定。

### 9.6 1.2 隔离

`git status --short ps-shell/` 为空 —— 1.2 `ps-shell/` 零改动。

---

## 10. 定案补记（2026-10-26）：改用纯算法复刻，不依赖 snack.exe

### 10.1 根因（实测，非推断）

| 事实 | 证据 |
|---|---|
| `vendor/snack.exe` = `refs/voicesauce-v137/Windows/snack.exe` | md5 完全相同 `dea2b6156f6b96bc25b7308c735c59b2` |
| 它是 **Tcl/Tk `wish`**，**32 位**，**只有一个 PE**（libsnack.dll 未内嵌） | PE manifest `name="Tcl.Tk.wish"`；machine `0x14c`；MZ/PE 枚举仅 offset 0 |
| 不认识 `pitch`/`formant` 子命令 | 官方 usage：`Pass all remaining arguments through to script` |
| 传脚本参数也**不执行**（直接挂起） | `snack.exe t2.tcl`（含 `puts`+`exit`）3 种参数形式均 TIMEOUT，无 stdout |
| VS 之所以能跑 | 作者机器**另装了完整 Tcl+Snack**；本机无 Tcl 8.4、无 32 位 Python → 不可用 |
| 独立佐证 | OpenSauce-Python 官方：Snack 用 `tclsh`（Win/Linux）/`tclsh8.4`（Mac），**非** `snack.exe pitch`；Snack FAQ 有专条 "Can I use the Snack package with tclsh?" |

→ **结论：该 exe 在裸机上确定不可用；不是移植错误，是蓝本自带产物本身不可用。**

### 10.2 定案方案（用户 2026-10-26 拍板：方案 A）

新增 `ps-shell-v2/backend/pysauce/engines/snack_sim.py` —— **纯 Python 算法复刻**：

* **sF0 / sV / sRMS** = **RAPT**（Talkin, D. 1995, *A Robust Algorithm for Pitch Tracking*, in Speech Coding and Synthesis）：
  降采样 ~1kHz 粗搜索 NCCF → 原采样率邻域精算 → 抛物线插值 → **次谐波抑制** → 动态规划回溯。
* **sF1–sF4 / sB1–sB4** = **LPC 自相关法**（教科书算法）：
  预加重 0.96 → 降采样 10kHz → Hamming → 自相关 → Levinson-Durbin → 求根 → 极点频率/带宽（带宽过滤 <30 / >1500 Hz）。

参数严格照蓝本：`windowsize=25ms, frameshift=1ms, maxF0=500, minF0=40, lpcOrder=12, preemphasis=0.96, ds_freq=10000`。

### 10.3 调用策略（`snack.py`）

* `strategy="sim"`（**默认**）：走算法复刻，**不碰任何外部程序**。
* `strategy="exe"`：强制真 exe（仅当用户自备 Tcl+Snack 环境做严格对拍时）。
* ⚠️ 早期版本曾设 `"auto"`（先试 exe 再回退）—— **实测会挂在那个 wish exe 上白等超时**，故废弃 `"auto"`，默认直接 `"sim"`。

### 10.4 验收结果

| 项 | 结果 |
|---|---|
| harm5 F0 | **200.00 Hz**（真值 200）✅ |
| sine100 F0 | **100.00 Hz**（真值 100）✅ |
| chirpF0 F0 | 101.9 → 296.4 Hz（设计 100→300）✅ |
| 网格对齐 | 501 帧 = data_len；头部 floor(25/1/2)=12 帧 NaN ✅ |
| 新增测试 | `tests/test_snack_sim.py` **10 passed** |
| 原卡片测试 | `test_engines_snack.py`（禁改）**2 passed**（原为 2 failed/挂起） |
| 全量 | **316 passed / 3 failed**（3 个均为既有停报项）/ 2 skipped |
| 1.2 隔离 | `git status --short ps-shell/` 为空 ✅ |

### 10.5 诚实声明（必须随结果标注）

本复刻是**算法等价实现，不是真 Snack 二进制**；数值**不可能与真 Snack 逐位相同**
（DP 代价系数、边界帧、内部滤波器细节有实现自由度）。引用其值时须标注
「RAPT/LPC 复刻」。与 `straight.py` 用 pylstraight（第三方近似）为同一性质。
