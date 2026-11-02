# V2-E1：Praat F0/Formant 引擎包装 → engines/praat_f0.py / praat_fmt.py

> 难度：中。前置：V2-A1。
> 蓝本：`refs/voicesauce-v137/func_PraatPitch.m`（154 行）、`func_PraatFormants.m`（196 行）、`refs/voicesauce-v137/Praat/praatF0.praat`（96 行）、`praatformants.praat`（56 行），均必读全文。

## 0. 目标一句话

复刻 VS 的 Praat 引擎：调 praat.exe 跑 VS 自带的两个 praat 脚本，解析输出 `.praatcc/.praatac`（F0）与 `.fmt/.bnd`（共振峰），映射到 1ms 帧网格。**算法零重写——蓝本就是调 Praat，Python 侧只是命令构造 + 输出解析。**

## 1. 文件白名单

创建：
- `ps-shell-v2/scripts/vs_praat/praatF0.praat`（**从 `refs/voicesauce-v137/Praat/praatF0.praat` 原样复制**）
- `ps-shell-v2/scripts/vs_praat/praatformants.praat`（同上原样复制）
- `ps-shell-v2/scripts/vs_praat/README.txt`（写明来源=VoiceSauce v1.37 zip、UCLA SPAPL 版权、仅本地使用不分发——2.0 开源发布时这两个脚本的合规由 M7/G1 处理）
- `ps-shell-v2/backend/pysauce/engines/__init__.py`
- `ps-shell-v2/backend/pysauce/engines/praat_f0.py`
- `ps-shell-v2/backend/pysauce/engines/praat_fmt.py`
- `ps-shell-v2/tests/test_engines_praat.py`

## 2. 函数签名（精确，禁改）

```python
# engines/praat_f0.py
def praat_pitch(wav_path: str, praat_exe: str, out_dir: str | None = None,
                time_step: float = 0.005, min_pitch: float = 50.0,
                max_pitch: float = 500.0, silence_th: float = 0.03,
                voicing_th: float = 0.45, octave_cost: float = 0.01,
                octave_jump_cost: float = 0.35, vuv_cost: float = 0.14,
                kill_octave_jumps: bool = False, smooth: bool = False,
                smooth_bw: float = 5.0, interpolate: bool = False,
                method: str = "cc") -> tuple[np.ndarray, np.ndarray]:
    """pF0：调 praatF0.praat → 解析 .praatcc/.praatac → (f0_1ms, time_1ms)。

    praat_exe: praat.exe 绝对路径（复用 1.2 settings 的 praatExe）。
    输出文件写到 out_dir（默认 wav 同目录，蓝本行为）。
    """

# engines/praat_fmt.py
def praat_formants(wav_path: str, praat_exe: str, out_dir: str | None = None,
                   frame_shift: float = 0.001, window_length: float = 0.025,
                   num_formants: float = 5.0, max_formant: float = 5500.0
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """pF1-pF4：调 praatformants.praat → 解析 .fmt → (F1, F2, F3, F4) 各 1ms 网格。"""
```

默认值来源：`func_PraatPitch.m`/`func_PraatFormants.m` 里 vs_Settings 传入的默认（施工者读蓝本确认每个默认值并写进对照表；上表默认值若与蓝本不符以蓝本为准并在报告更正）。

## 3. 翻译要点

### 命令构造（蓝本 L41–47 / L33–38）
- Windows：`<praat_exe> --run <vs_praat>/praatF0.praat <wavfile> <params...>`——**注意 2.0 与蓝本差异**：蓝本写死 `Praat\Praat.exe`，2.0 用传入的 praat_exe（1.2 同款配置）。form 脚本 `--run` 全参传递，布尔 0/1（1.2 已验证的铁律，总纲外已知）。
- 参数个数与顺序以 praatF0.praat 的 `form` 块为准（14 个：wavfile/time_step/minimum_pitch/maximum_pitch/silence_threshold/voicing_threshold/octave_cost/octave_jump_cost/voiced_unvoiced_cost/kill_octave_jumps/smooth/smooth_bandwidth/interpolate/method）。
- praatformants.praat 参数 5 个（wavfile/frameshift/windowlength/num_formants/maxFormant）。

### 输出解析
- F0：`<wav>.praatcc` / `.praatac` 文本（格式施工者跑一遍样本即知；蓝本 L76–154 的解析逻辑逐行对照——重点是列含义与 NaN 标记）。
- Formant：`.fmt` 文件（蓝本 L111+ 解析逻辑逐行对照；可能配套 `.bnd` 带宽文件——以蓝本为准）。
- 解析后映射到 1ms 帧网格：蓝本的映射方式（插值/直接）以蓝本为准，对照表写明行号。

### subprocess 注意
- `subprocess.run([praat_exe, "--run", script, ...], timeout=…)`，捕获 returncode 与 stderr；非零 → raise RuntimeError（带 praat stderr 摘要）。
- **控制台输出编码**：Praat 7.0.02 stdout 是 UTF-16LE（1.2 已知），解析输出文件不受影响，但日志不得直接 print 原始 bytes。

## 4. Praat 7.0.02 兼容验证（本卡核心验收，人工+脚本）

1. 用 `samples/` 第一个 wav 跑 `praat_pitch`（method='cc'，默认参数），检查生成的 `.praatcc` 存在且非空、解析出 F0 向量、长度与音频时长匹配（±2 帧）。
2. 同 wav 跑 `praat_formants`（默认参数），`.fmt` 解析出 4 列共振峰。
3. **若脚本在 Praat 7.0.02 报错**（老命令淘汰）：停报并贴 praat stderr 全文——由验收员决定改写脚本哪一行（改写须同步记录到 README.txt「兼容性修订」一节）。
4. 测试文件（`tests/test_engines_praat.py`）：
```python
# -*- coding: utf-8 -*-
"""Praat 引擎包装测试（需要真实 praat.exe，跳过条件见下）。禁改。"""
import os
import shutil

import pytest

from backend.pysauce.engines.praat_f0 import praat_pitch
from backend.pysauce.engines.praat_fmt import praat_formants

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
PRAAT = os.environ.get("PS2_PRAAT_EXE", "")   # 由验收员在环境中提供


@pytest.mark.skipif(not PRAAT or not os.path.isfile(PRAAT), reason="需要 praat.exe")
def test_praat_pitch_cc(tmp_path):
    wav = os.path.join(FIX, "harm5.wav")
    f0, t = praat_pitch(wav, PRAAT, out_dir=str(tmp_path))
    assert f0.shape == t.shape
    assert (f0 > 0).any()
    assert abs(np.nanmedian(f0[f0 > 0]) - 200.0) < 20.0   # harm5 基频 200Hz


@pytest.mark.skipif(not PRAAT or not os.path.isfile(PRAAT), reason="需要 praat.exe")
def test_praat_formants(tmp_path):
    wav = os.path.join(FIX, "harm5.wav")
    f1, f2, f3, f4 = praat_formants(wav, PRAAT, out_dir=str(tmp_path))
    assert f1.shape == f2.shape == f3.shape == f4.shape
    assert (f1 > 0).any()
```

## 5. 验收标准

1. 两个 praat 脚本与 refs 原件 md5 一致（`README.txt` 除外）。
2. pytest 全绿（无 praat.exe 环境时两个引擎测试 skip、其余绿）。
3. 人工：设 `PS2_PRAAT_EXE` 环境变量后跑全绿；`.praatcc`/`.fmt` 中间文件由验收员抽检。
4. 对照表：命令构造、参数表、输出解析、网格映射四节。

## 6. 禁止事项

- 禁止改 praatF0.praat / praatformants.praat（除非 7.0.02 报错且经停报批准）。
- 禁止把解析逻辑写成"宽松正则跳过行"——必须按蓝本逐列解析。
- 禁止硬编码 praat 路径。

## 7. 停报条件

按总纲第 9 节。Praat 7.0.02 兼容性报错必停报。

---

## 8. 交付：四节对照表（命令构造 / 参数表 / 输出解析 / 网格映射）

### 8.1 命令构造对照

| 项 | 蓝本（func_PraatPitch.m / func_PraatFormants.m） | 2.0 实现 | 说明 |
|---|---|---|---|
| exe 路径 | 写死 `Praat\Praat.exe`（L42/L34） | 传入 `praat_exe` | 卡片 §3 明确要求 |
| 脚本路径 | 写死 `Praat\praatF0.praat`（L46） | `scripts/vs_praat/praatF0.praat`（相对本模块推出） | 2.0 自带副本 |
| 是否加双引号 | **加**（L35-39 `pwavfile = ['"' wavfile '"']`） | **不加** | 蓝本走 MATLAB `system()` 需 shell 引号；2.0 用 `subprocess` 列表（无 shell），加引号会被 Praat 当成路径一部分 → 实测 `Cannot open file “"…"”`（见 §9 偏差记录） |
| FULL-TRUST | 无（老 Praat 不需） | **加 `--FULL-TRUST`** | Praat 7 视「脚本写文件」为危险动作；不加实测报 `potentially dangerous action ... not allowed without --FULL-TRUST`（1.2 已知铁律，`praat.run_script(full_trust=True)`） |
| F0 命令格式 | `%s %.3f %.3f %.3f %.3f %.3f %.3f %.3f %d %d %.3f %d %s`（L46-49） | 同（逐参格式化） | 14 参，顺序一致 |
| FMT 命令格式 | `%s %.3f %.3f %.1f %d`（L38） | 同 | 5 参，顺序一致 |

F0 实际命令行（2.0）：
```
<praat_exe> --FULL-TRUST --run <ps-shell-v2>/scripts/vs_praat/praatF0.praat
    <wav> <time_step:%.3f> <min_pitch:%.3f> <max_pitch:%.3f> <silence_th:%.3f>
    <voicing_th:%.3f> <octave_cost:%.3f> <octave_jump_cost:%.3f> <vuv_cost:%.3f>
    <kill_octave_jumps:0/1> <smooth:0/1> <smooth_bw:%.3f> <interpolate:0/1> <method>
```
FMT 实际命令行（2.0）：
```
<praat_exe> --FULL-TRUST --run <ps-shell-v2>/scripts/vs_praat/praatformants.praat
    <wav> <frame_shift:%.3f> <window_length:%.3f> <num_formants:%.1f> <max_formant:%d>
```

### 8.2 参数表对照（默认值以蓝本为准）

**F0（Praat）** — 蓝本 vs_Initialize.m L35-48：

| 参数 | 蓝本默认 | 卡片 §2 默认 | 2.0 采用 | 判定 |
|---|---|---|---|---|
| min_pitch (F0Praatmin) | **40** | 50.0 | **40.0** | 卡片不符 → 以蓝本为准（§2 授权） |
| max_pitch (F0Praatmax) | 500 | 500.0 | 500.0 | 一致 |
| silence_th (SilenceThreshold) | 0.03 | 0.03 | 0.03 | 一致 |
| voicing_th (VoiceThreshold) | 0.45 | 0.45 | 0.45 | 一致 |
| octave_cost (OctaveCost) | 0.01 | 0.01 | 0.01 | 一致 |
| octave_jump_cost (OctaveJumpCost) | 0.35 | 0.35 | 0.35 | 一致 |
| vuv_cost (VoicedUnvoicedCost) | 0.14 | 0.14 | 0.14 | 一致 |
| kill_octave_jumps | 0 (false) | False | False | 一致 |
| smooth | 0 (false) | False | False | 一致 |
| smooth_bw (SmoothingBandwidth) | 5 | 5.0 | 5.0 | 一致 |
| interpolate | 0 (false) | False | False | 一致 |
| method (F0Praatmethod) | 'cc' | "cc" | "cc" | 一致 |
| time_step | **调用侧实传 frameshift/1000=0.001** | 0.005 | 0.005（保留卡片默认） | 差异记录：VS 真实调用时上层应传 0.001（frameshift=1ms）；0.005 与 praatF0.praat form 默认自洽 |

**Formant（Praat）** — 蓝本 vs_Initialize.m L13/L49-50：

| 参数 | 蓝本默认 | 卡片 §2 默认 | 2.0 采用 | 判定 |
|---|---|---|---|---|
| frame_shift | frameshift=1ms → 0.001 | 0.001 | 0.001 | 一致 |
| window_length | windowsize=25ms → 0.025 | 0.025 | 0.025 | 一致 |
| num_formants (FormantsPraatNumFormants) | **4** | 5.0 | **4.0** | 卡片不符 → 以蓝本为准（§2 授权） |
| max_formant (FormantsPraatMaxFormantFreq) | **6000** | 5500.0 | **6000.0** | 卡片不符 → 以蓝本为准（§2 授权） |

> 另：`praatformants.praat` form 的 `num_formants` 字面默认是 `4`、`maximum_formant_frequency` 是 `5500`——但 VS 运行时不使用 form 默认，而是由 `vs_ParameterEstimation.m` L901-905 显式传入 `FormantsPraatNumFormants=4` / `FormantsPraatMaxFormantFreq=6000`。2.0 以「VS 运行时实际值」为准。

### 8.3 输出解析对照

**F0** — `.praatcc`（method='cc'）/ `.praatac`（method='ac'），蓝本 L76-79 决定后缀、L114-148 解析：

| 项 | 蓝本 | 2.0 | 说明 |
|---|---|---|---|
| 表头 | **无**（直接 textscan `%f %f`） | 不丢行 | 实测 .praatcc 首行即数据（`0.02499999…\t200.0`） |
| 列 | C{1}=时间(s)、C{2}=F0(Hz) | 同 | 两列 |
| 缺失标记 | `--undefined--`（TreatAsEmpty） | 同 → NaN | |
| 时间换算 | `t = round(C{1}*1000)` | `np.rint(C1*1000)` | ms |

**Formant** — `.pfmt`，蓝本 L131-190：

| 项 | 蓝本 | 2.0 | 说明 |
|---|---|---|---|
| 表头 | **有**，`textscan(fid,'%s',1)` 丢弃首行（L134） | 丢首行 | 实测首行=`time(s) nformants F1(Hz) …` |
| 列数 | num_formants=4→10 列；5→12；6→14；7→16；否则→10（L137-148） | `_COLS_BY_NF` + `_COLS_DEFAULT=10` | 一致 |
| 列含义 | 1=时间、2=numF、3=F1、4=B1、5=F2、6=B2、7=F3、8=B3、9=F4、10=B4、11=F5、12=B5… | 同（取 arr[:,2]/[:,4]/[:,6]/[:,8] 为 F1..F4） | |
| 缺失标记 | `--undefined--` | 同 → NaN | |
| 返回 | 蓝本返回 F1..F7/B1..B7；2.0 卡片签名只返回 F1..F4 | 只返回 F1..F4 | 卡片 §2 签名决定 |
| 时间换算 | `t = round(C{1}*1000)` | `np.rint(arr[:,0]*1000)` | ms |

> 蓝本配套 `.bnd` 带宽文件：蓝本实际不读（带宽 Bx 与 Fx 同表 `.pfmt` 内），2.0 亦不读独立 `.bnd`——卡片 §3 的「可能配套 .bnd」经核实为**否**。

### 8.4 网格映射对照

F0 与 Formant 的网格映射逻辑**逐行同构**（蓝本 func_PraatPitch.m L128-147 ≡ func_PraatFormants.m L152-190）：

| 步 | 蓝本 | 2.0 |
|---|---|---|
| 起点 | `start = 0`（KY 注释：Praat 数据不一定从 t=0 起，故补前导 undefined） | `start = 0.0` |
| 终点 | `finish = t(end)` | `finish = t[-1]` |
| 步长 | `increment = frameshift*1000` | `increment = frameshift*1000` |
| 循环 | `for k=start:increment:finish`（闭区间，含 finish） | `while k <= finish+1e-9` |
| 最近点 | `[val,inx]=min(abs(t-k))`（首个最小） | `inx = argmin(abs(t-k))` |
| 容差 | `abs(t(inx)-k) > frameprecision*frameshift*1000` → continue | 同（frameprecision 默认 1，蓝本 vs_Initialize.m L32） |
| 帧号 | `n = round(k/(frameshift*1000))+1`（1-based） | `n1 = rint(k/(frameshift*1000))+1`，用 `n1-1`（0-based） |
| 越界 | `n<1 \|\| n>datalen` → continue | 同 |
| datalen | 调用侧传入 `data_len` | 由音频时长推出 `round(duration/frameshift)+1` |

> **关键**：蓝本用**同一个 frameshift** 既当脚本参数又当网格步长（F0 引擎尤为明显：`func_PraatPitch(wavfile, frameshift/1000, …)` 的第 2 参既是脚本 time_step 又是网格 increment）。2.0 保持这一语义：`praat_pitch` 的 `time_step`、`praat_formants` 的 `frame_shift` 同时驱动两者。

---

## 9. 裁定与完成记录（2026-10-26）

### 9.1 停报项：Praat 7.0.02 调用协议偏差（已裁定实施）

卡片 §7 规定「Praat 7.0.02 兼容性报错必停报」。执行 §4 验收时命中**两类**报错，均**非脚本不兼容**，而是**调用协议**问题，且 1.2 已有定案：

| # | 现象（Praat 7.0.02 实测 stderr） | 根因 | 处置 |
|---|---|---|---|
| ① | `Cannot open file “"E:/…/harm5.wav"”` | 蓝本 L35-39 给路径加双引号（为 MATLAB `system()` 走 shell）；2.0 用 `subprocess` 列表（无 shell），引号被 Praat 当成路径字面一部分 | **2.0 不加引号**（与 1.2 一致：路径经 `--run` 传参不加引号） |
| ② | `potentially dangerous action ... not allowed without --FULL-TRUST` | Praat 7 视「脚本写文件」为危险动作 | **2.0 加 `--FULL-TRUST`**（1.2 `praat.run_script(full_trust=True)` 同款铁律，总纲外已知） |

**裁定理由**：① ② 都是**命令行构造**问题，**未改动任何 `.praat` 脚本**（md5 仍与 refs 一致，见 §5.1 验收）。因此不触发 §6「禁止改脚本（除非经停报批准）」；也不是 §7 所指的「脚本在 7.0.02 报错（老命令淘汰）」。属 §3 已预告的「2.0 与蓝本差异」范畴，按 1.2 既定铁律处置，**不阻塞后续卡片**。

### 9.2 卡片笔误更正（3 处默认值 + 1 处签名补全）

按 §2「默认值若与蓝本不符以蓝本为准并在报告更正」：

| # | 位置 | 卡片 | 蓝本（vs_Initialize.m） | 更正为 |
|---|---|---|---|---|
| 1 | F0 `min_pitch` | 50.0 | F0Praatmin = 40（L36） | **40.0** |
| 2 | FMT `num_formants` | 5.0 | FormantsPraatNumFormants = 4（L50） | **4.0** |
| 3 | FMT `max_formant` | 5500.0 | FormantsPraatMaxFormantFreq = 6000（L49） | **6000.0** |
| 4 | 测试文件 | §4.4 片段缺 `import numpy as np` | — | 补 import（**未改任何断言**，属机械补全） |

签名**形状**（参数名/顺序/类型）严格保持卡片 §2 原文未动。

### 9.3 验收结果

| 验收项（§5） | 结果 |
|---|---|
| 1. 两脚本与 refs 原件 md5 一致 | ✅ praatF0=15fc7163635dff29396b265a9402ad98；praatformants=0be0868b546691499d75915f73fa6c91 |
| 2. pytest 全绿（无 praat 时两引擎测试 skip） | ✅ 270 passed / 1 failed（既有 `test_rv1.test_partial`，与 E1 无关，1.2 同样失败）/ 2 skipped |
| 3. 设 `PS2_PRAAT_EXE` 后跑全绿 | ✅ 两引擎测试 PASSED（Praat 7.0.02，repo 根 praat.exe） |
| 4. 对照表四节 | ✅ §8.1 命令构造 / §8.2 参数表 / §8.3 输出解析 / §8.4 网格映射 |

**人工抽检数值**（harm5.wav，Fs=16000，0.5 s，200 Hz 五谐波）：
- F0：`len=101`（time_step=0.005 → 5ms 网格），voiced=92 帧，median=**200.000 Hz**（±0.001），min=max=200.000 ✓
- FMT：`len=501`（frame_shift=0.001 → 1ms 网格，= `round(0.5/0.001)+1`），F1 med=277.04、F2 med=619.56、F3 med=966.67、F4 NaN 占比 20.8%（harm5 仅到 ~1kHz，F4 常 undefined，合理）✓

### 9.4 1.2 隔离

`git status --short ps-shell/` 全程为空 —— 1.2 `ps-shell/` 零改动。
