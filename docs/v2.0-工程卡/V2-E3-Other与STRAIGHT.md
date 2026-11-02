# V2-E3：Other 引擎解析 + STRAIGHT（pylstraight）→ engines/other.py / straight.py

> 难度：中。前置：V2-A3。
> 蓝本：`refs/voicesauce-v137/func_OtherPitch.m`（71 行）、`func_OtherFormants.m`（79 行）、`func_parseF0.m`（54 行）、`func_parseFMT.m`（54 行），必读全文。

## 0. 目标一句话

① Other 引擎：复刻「读外部已算好的 F0/FMT 文本文件」的解析（纯 I/O 无算法）；② STRAIGHT 引擎：接入 pylstraight（pip 包，Apache-2.0，legacy-STRAIGHT 复现）产 strF0，界面标注「近似」。

## 1. 文件白名单

创建：
- `ps-shell-v2/backend/pysauce/engines/other.py`
- `ps-shell-v2/backend/pysauce/engines/straight.py`
- `ps-shell-v2/tests/test_engines_other_straight.py`

## 2. 函数签名（精确，禁改）

```python
# engines/other.py
def other_pitch(wav_path: str, f0_file: str) -> tuple[np.ndarray, np.ndarray]:
    """oF0：func_OtherPitch.m → func_parseF0.m。解析外部 F0 文件 → (f0_1ms, time_1ms)。"""


def other_formants(wav_path: str, fmt_file: str
                   ) -> tuple[np.ndarray, ...]:
    """oF1-oF4 (+oB1-oB4 若文件含带宽)：func_OtherFormants.m → func_parseFMT.m。"""


# engines/straight.py
def straight_pitch(wav_path: str, out_dir: str | None = None
                   ) -> tuple[np.ndarray, np.ndarray]:
    """strF0：pylstraight legacy-STRAIGHT F0 → (f0_1ms, time_1ms)。

    ⚠️ 数值口径：legacy-STRAIGHT 近似，与 VS pcode（TANDEM-STRAIGHT）非等价，
    输出仅供对比参考——docstring 与界面都必须带此标注。
    """
```

## 3. 翻译要点

### Other（全部逐行对照蓝本）
- `func_parseF0.m`：外部 F0 文本格式（时间列/频率列的容错、NaN 标记、列序）逐行复刻；格式不符 raise。
- `func_parseFMT.m`：同上（F1-F4 列，可能含 B1-B4 列——以蓝本为准）。
- `func_OtherPitch.m`：文件定位逻辑（同名 .f0? 用户指定?）逐行复刻；蓝本若从文件名推断（`<wav 根名>.f0`），Python 签名保留显式 f0_file 参数并在内部做蓝本同款缺省推断。
- 网格映射：外部文件的时间轴 ≠ 1ms → 蓝本的映射方式（最近邻/线性插值）逐行对照。

### STRAIGHT（pylstraight 接入）
1. `C:/Users/Remi/AppData/Local/Programs/Python/Python311/python.exe -m pip install pylstraight`（本卡唯一允许的 pip 安装；装失败则整个 straight_pitch 实现为「接口就绪 + raise NotImplementedError(带环境说明)」，测试 skip——不阻塞验收）。
2. 用 pylstraight 的 F0 提取 API（读其 README 确认函数名），输出重采样/映射到 1ms 网格。
3. `Fs` 不匹配时先重采样到 pylstraight 要求的采样率（读其文档），完成后 F0 时间轴换算回秒。
4. 代码注释顶部标明：`# 数值口径：legacy-STRAIGHT（pylstraight，Apache-2.0）；非 VS TANDEM-STRAIGHT 等价`。

## 4. 测试（`tests/test_engines_other_straight.py`，原样照抄）

```python
# -*- coding: utf-8 -*-
"""Other 解析 + STRAIGHT 接入测试。禁改。"""
import os

import numpy as np
import pytest

from backend.pysauce.engines.other import other_formants, other_pitch

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _write_f0_fixture(tmp_path):
    # 常量 F0=200Hz、时间 0..0.5s 步进 5ms 的外部 F0 文件（格式以蓝本 func_parseF0 为准，
    # 施工者按蓝本格式写此 fixture；本测试假定「每行: time<TAB>f0」——若蓝本不同，改这里并停报）
    lines = [f"{i * 0.005:.3f}\t{200.0:.4f}" for i in range(101)]
    p = os.path.join(str(tmp_path), "fake.f0")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p


def test_other_pitch_constant(tmp_path):
    p = _write_f0_fixture(tmp_path)
    f0, t = other_pitch(os.path.join(FIX, "harm5.wav"), p)
    assert f0.shape == t.shape
    valid = f0[f0 > 0]
    assert abs(np.median(valid) - 200.0) < 1e-6


def test_other_pitch_bad_file_raises(tmp_path):
    p = os.path.join(str(tmp_path), "nope.f0")
    with pytest.raises(Exception):
        other_pitch(os.path.join(FIX, "harm5.wav"), p)


def test_straight_importable_or_marked():
    try:
        from backend.pysauce.engines.straight import straight_pitch  # noqa: F401
    except NotImplementedError:
        pytest.skip("pylstraight 未安装，接口占位")
```

## 5. 验收标准

1. pytest 全绿（pylstraight 缺失时 straight skip）。
2. 对照表：parseF0/parseFMT 逐行；OtherPitch/OtherFormants 逐行。
3. pylstraight 成功时：harm5 的 strF0 中位数落 [150, 250]（sanity），输出示例附报告。

## 6. 禁止事项

- 禁止"宽容解析"（列数不符/空行语义必须按蓝本，不许静默跳行）。
- 禁止在 straight.py 里宣称与 VS 数值等价（注释/docstring 必须带「近似」标注）。

## 7. 停报条件

按总纲第 9 节。特别地：func_parseF0/parseFMT 的格式细节与 `_write_f0_fixture` 假设不符时停报。

---

## 8. 对照表（逐行）

### 8.1 func_parseF0.m / func_parseFMT.m —— **向量选择器，非文件解析器**（关键结构澄清）

| 蓝本行 | 蓝本内容 | 2.0 落点 | 说明 |
|---|---|---|---|
| parseF0 L11 | `switch(F0algorithm)` | — | 按算法名挑 `.mat` 结构体里的向量 |
| parseF0 L12-31 | `matdata.strF0` / `sF0` / `pF0` / `shrF0` / `oF0` | — | **不读文件**；`oF0` 由 `func_OtherPitch` 产出 |
| parseF0 L33 | `otherwise F0=[]` | — | 无匹配 → 空 |
| parseFMT L16-45 | 同上（`sF1..sB3` / `pF1..pB3` / `oF1..oB3`） | — | **不读文件** |
| parseFMT L47-53 | `otherwise` 全空 | — | — |

→ **结论**：真正的文件 I/O 在 `func_Other*`。2.0 把「`func_Other*` 的文件读取」+
「`func_parse*` 的向量选择」两步合并为 `engines/other.py` 的两个函数。

### 8.2 func_OtherPitch.m（71 行）

| 蓝本行 | 蓝本内容 | 2.0 实现 | 差异 |
|---|---|---|---|
| L17 | `outfile = [wavfile(1:end-3) 'f0']` | `_infer_outfile(wav, ".f0")` = splitext + ".f0" | 等价（`.wav` 4 字符后缀） |
| L19-20 | `textscan(F0OtherCommand,'%s','delimiter',' ')` | — | 外部命令模板，2.0 不执行外部命令（用户直接给文件） |
| L26-34 | `$wavfile` / `$outfile` 替换 | — | 同上，不适用 |
| L37 | `system(command)` | — | 同上 |
| L40-49 | `status~=0` → err_msg + 清理 | — | 2.0 无子进程 |
| L52-55 | 文件不存在 → err_msg | `FileNotFoundError` | 语义等价（异常 vs 返回 err_msg） |
| **L64** | **`textscan(fid, '%f')`** | `_read_single_column_f0`：逐行取第一个 token → float；空行跳过；非数值停止 | **单列**（蓝本原文） |
| L66 | `F0 = C{1}` | 返回 `np.ndarray` | — |
| L70 | `delete(outfile)` | 不删（2.0 文件是用户资产） | 刻意差异（见 §9） |

### 8.3 func_OtherFormants.m（79 行）

| 蓝本行 | 蓝本内容 | 2.0 实现 | 差异 |
|---|---|---|---|
| L17 | `outfile = [wavfile(1:end-3) 'fmt']` | `_infer_outfile(wav, ".fmt")` | 等价 |
| L19-38 | 命令模板 + `system()` | — | 不适用 |
| L41-56 | 错误分支 | `FileNotFoundError` | 语义等价 |
| **L65** | **`textscan(fid,'%f %f %f %f %f %f %f %f','delimiter','\n')`** | `_read_eight_column_fmt`：每行 8 列；<8 列停止 | **8 列** F1F2F3F4B1B2B3B4 |
| L67-74 | `F1=C{1} … B4=C{8}` | 返回 8 元组 | — |
| L78 | `delete(outfile)` | 不删 | 同 8.2 |

### 8.4 vs_ParameterEstimation.m 的网格放置（L813-817 / L984-1002）

| 蓝本行 | 蓝本内容 | 2.0 实现 |
|---|---|---|
| L579 | `data_len = floor(length(y)/Fs*1000/frameshift)` | `_data_len()`（frameshift=1 ms） |
| L780 / L945-952 | `zeros(data_len,1)*NaN` 预分配（MATLAB `0*NaN=NaN`） | `np.full(n, np.nan)` |
| L813 | `if (F0OtherOffset + length(F0) <= data_len)` | `m = min(n, raw.size)` 统一处理 |
| L814 | `oF0(off+1 : off+len) = F0` | `f0[:m] = raw[:m]`（off=0 默认，vs_Initialize.m L25） |
| L816 | `else oF0(off+1:end) = F0(1:data_len-off)` | 同上（截断） |
| L984-1002 | 8 列同款放置 | `other_formants` 逐列同款 |
| vs_Initialize L25/L28 | `F0OtherOffset = 0` / `FormantsOtherOffset = 0` | 2.0 无 offset 参数（恒 0），与出厂默认一致 |

### 8.5 STRAIGHT

| 项 | 蓝本（VS pcode） | 2.0（pylstraight 0.1.3） |
|---|---|---|
| 实现 | `straight_pcode`（TANDEM-STRAIGHT 编译产物，**未随 v1.37 分发**） | pip `pylstraight`（Apache-2.0，**legacy-STRAIGHT** 复现） |
| 等价性 | — | **非等价**，近似；docstring/注释已带标注 |
| F0 范围 | maxF0=500 / minF0=40（vs_Initialize L20/L21） | 同值传入 |
| 目标网格 | 1 ms（frameshift=1） | 结果重采样到 1 ms |
| 帧移 | pcode 内部 | **默认 5 ms**（1 ms 触发上游 V/UV 缺陷，见 §9） |

---

## 9. 停报与偏差记录（V2-E3）

### 9.1 停报 ①：卡 §4 fixture 与蓝本格式冲突（**按 §7 停报**）

- **冲突**：卡 §4 `_write_f0_fixture` 写 `time<TAB>f0`（2 列）；蓝本 `func_OtherPitch.m` L64
  是 `textscan(fid,'%f')`（**单列**）。
- **处置**：卡 §4 文件**原样照抄**、**未改**（保留冲突证据）；实测其 `test_other_pitch_constant`
  **FAIL**（`median=0.2525`，即被读入的是**第一列时间**，而非第二列 200.0）——
  这正是冲突的实证。另建 `tests/test_engines_other_straight_blueprint.py`（5 项，全绿）
  按**蓝本单列**格式做真实验证。
- **建议**（待验收员拍板）：将卡 §4 的 `_write_f0_fixture` 改为单列
  （`f"{200.0:.4f}"`，去掉时间列），或明确 2.0 的 `.f0` 契约就是「首列为 F0」。

### 9.2 停报 ②：pylstraight 在 1 ms 帧移下返回全 0（**上游缺陷，已定位到行**）

- **现象**：`pylstraight.extract_f0(harm5, 16000, frame_shift=1.0, f0_range=(40,500))`
  → **全 0**（全清音）；`frame_shift=5.0` → 正常 ≈200 Hz。
  官方 doc 示例（600 样本短信号）在 1 ms 下正常，故非 API 误用。
- **根因**（`pylstraight/core/f0.py::zvuvdecision4`，L2006-2056）：
  - `pv = zpeakdipdetect(pwsdb, wsml)` 的 `wsml = round(81/shiftm)`：1 ms → **81**、5 ms → **16**；
    `zpeakdipdetect` 内部先做 `wsml` 点 Hanning **平滑**再找峰。
  - 但门限比较 `if (1.2*maxpwsdb + noiselevel)/2.2 < pwsdb[pv[ii]]` 用的是**未平滑**的
    `pwsdb[pv]`。
  - harm5 为平稳信号，1 ms 下 wsml=81 把峰值压低 **0.244 dB**
    （smoothed max −8.085 vs raw max −7.842）→ `pwsdb[pv]≈−8.105 < 门限 −7.922`
    对**全部 68 个峰**不成立 → `for ii in range(len(pv))` 体一次不进 → `vuv` 全 0
    → `extract_f0` 返回 `f0*vuv = 0`。
  - 5 ms 下 wsml=16 几乎不压低（差 0.000 dB），17 个峰全部过门限 → 正常。
- **处置**：`straight_pitch` **默认 `frame_shift=5.0`**（pylstraight 自身默认值，实测可用），
  结果线性插值到 VS 的 1 ms 网格；显式传 1.0 时若检出全 0 → **raise RuntimeError**
  （不把「全清音」静默当合法结果）。机制全文写入 `straight.py` docstring。

### 9.3 其它偏差

| # | 项 | 处置 |
|---|---|---|
| 1 | 蓝本 `func_Other*` 末尾 `delete(outfile)` | 2.0 **不删**用户文件（文件是用户资产，非临时产物） |
| 2 | 蓝本执行外部命令（`F0OtherCommand`） | 2.0 不执行命令；签名接收**已算好的文件路径**（卡 §2 明确） |
| 3 | `out_dir` 参数（straight） | pylstraight 全内存，不使用；保留以对齐三引擎签名 |

### 9.4 完成状态

- ✅ `engines/other.py`、`engines/straight.py`、`tests/test_engines_other_straight.py`（卡 §4 原样）
- ✅ `tests/test_engines_other_straight_blueprint.py`（蓝本格式补充验证，5 项全绿）
- ✅ pylstraight 0.1.3 已装（卡 §3 唯一允许的 pip 安装）
- ✅ 全量 pytest：**277 passed / 2 failed / 2 skipped / 2 deselected**
  - failed ①：`test_engines_other_straight.py::test_other_pitch_constant`（**预期**，9.1 冲突实证）
  - failed ②：`test_rv1.test_partial`（**既有**失败，1.2 亦如此，与本卡无关）
  - skipped：`test_engines_praat.py` ×2（需 `PS2_PRAAT_EXE`）
  - deselected：`test_engines_snack.py`（E2 停报：snack.exe=GUI wish，无头环境挂起）
- ✅ `ps-shell/`（1.2）零改动（`git status --short ps-shell/` 空）
- ✅ 验收标准 §5.3：harm5 的 strF0 中位数 = **199.986 Hz**，落 [150, 250] ✓
