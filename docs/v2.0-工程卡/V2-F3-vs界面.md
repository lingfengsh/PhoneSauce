# V2-F3：vs 界面改造 → ps-shell-v2/ui/vs.js + vs.html

> 难度：中-高（前端，边界敏感；vs.js 现 1354 行，改动集中在提取掩模与结果展示两处）。前置：V2-F2。
> 参照：`ps-shell-v2/ui/vs.js`（1.2 副本，`VS_PARAMS` L24、`buildValues` L244 附近、`#exStart` L276 附近、导出 L664 附近）、`vs.html`、`vs.css`。
> **本卡是本需求（用户 2026-10-26 提出）的主要落点**：两界面互通 + 基准引擎选择 + 结果来源标注。

## 0. 目标一句话

vs 页发出 `engine:"pysauce"` 请求；**新增「算哪几套引擎」与「下游用哪套」两级选择**；展示 VS 原生列名结果并**明确标注每列来源引擎**。**向导页面（index.html/app.js 等）与 vs 页既有元素一律保留，只增不改删。**

## 0b. 需求背景（必读，来自用户 2026-10-26）

1. **两界面数据互通**：向导页（Praat）产出的 F0/Formant 应能被 vs 页直接复用；反之 vs 页（如 Snack）算出的也应能被向导页用。**1.2 已有基础**（共用 `measure/`，见 F1 §0b）。
2. **算法差异必须标注**：Praat 与 Snack 算的共振峰不同 → **必须在结果中区分**（VS 原生设计本就是分列 `pF1`/`sF1`）。
3. **基准引擎选择**：下游参数（H1/A1/2K/CPP/HNR…）基于 F0/共振峰计算，**须让用户明确选"用哪套引擎的结果作为基准"**（VS 的 `F0algorithm`/`FMTalgorithm`，见 F1 §0c）。

## 1. 文件白名单

修改：
- `ps-shell-v2/ui/vs.html`
- `ps-shell-v2/ui/vs.js`
- `ps-shell-v2/ui/vs.css`（仅新增样式类，禁改既有规则）

## 2. 改造规格

### vs.html（只增）

1. 提取掩模（`mExtract` 区域）内、`#exResample` 行附近，新增**引擎计算选择**（可多选，决定"算哪几套"）：
   ```html
   <div class="row" id="pitchEngineRow">
     <label>F0 引擎</label>
     <select id="pitchEngine" multiple size="4">
       <option value="praat" selected>Praat</option>
       <option value="snack">Snack</option>
       <option value="straight">STRAIGHT（legacy 近似）</option>
       <option value="other">Other（外部文件）</option>
     </select>
   </div>
   <div class="row" id="formantEngineRow">
     <label>共振峰引擎</label>
     <select id="formantEngine" multiple size="3">
       <option value="praat" selected>Praat</option>
       <option value="snack">Snack</option>
       <option value="other">Other（外部文件）</option>
     </select>
   </div>
   ```
   > 若多选 `<select multiple>` 与既有 UI 风格冲突，可改为复选框组（施工者按 vs.html 现有控件风格择一，报告说明）；**但必须支持同时算多套**。

2. 新增**下游基准选择**（单选，决定"用哪套"，F1 §0c）：
   ```html
   <div class="row" id="f0AlgorithmRow">
     <label>下游 F0 基准</label>
     <select id="f0Algorithm">
       <option value="praat">Praat</option>
       <option value="snack">Snack</option>
       <option value="straight">STRAIGHT</option>
       <option value="shr">SHR</option>
       <option value="other">Other</option>
     </select>
     <span class="hint">H1/A1/CPP/HNR 等基于此列计算</span>
   </div>
   <div class="row" id="fmtAlgorithmRow">
     <label>下游共振峰基准</label>
     <select id="fmtAlgorithm">
       <option value="praat">Praat</option>
       <option value="snack">Snack</option>
       <option value="other">Other</option>
     </select>
     <span class="hint">A1/A2/A3、2K/5K 及斜率基于此列计算</span>
   </div>
   ```

3. **数据复用行**（互通，F1 §0b）：
   ```html
   <div class="row" id="reuseRow">
     <label><input type="checkbox" id="exReuse" checked> 复用 measure/ 已有 F0/Formant</label>
     <span class="hint">目录下已有 .Pitch/.Formant（含向导页产出）将直接使用</span>
   </div>
   ```
4. `pitchEngine`/`formantEngine` 含 `other` 时显示外部文件输入行（Browse 复用 openPicker）。
5. **结果列说明**小字：列出各引擎来源列含义（`pF0`=Praat、`sF0`=Snack、`strF0`=STRAIGHT legacy 近似…），并说明"不同引擎数值不可直接混比"。
6. **下拉联动**（js 实现）：`f0Algorithm`/`fmtAlgorithm` 的选项应随 `pitchEngine`/`formantEngine` 勾选变化（只显示已勾选的引擎）；若基准指向未勾选引擎 → 界面给出黄色警示。

### vs.js（改 buildValues + 结果表 + 来源标注）

1. `buildValues()` 增加：
   ```js
   v.engine = "pysauce";
   v.pitch_engine = 选中值.join(",");      // 多选 → 逗号串（F2 解析）
   v.formant_engine = 选中值.join(",");
   v.f0_algorithm = $("#f0Algorithm").value;   // 基准（F1 §0c）
   v.fmt_algorithm = $("#fmtAlgorithm").value;
   v.reuse = $("#exReuse").checked ? 1 : 0;    // 互通（F1 §0b）
   v.other_f0_file = state.otherF0 || "";
   v.other_fmt_file = state.otherFmt || "";
   ```
   > ⚠️ `pitch_engine`/`formant_engine` 由单选改多选——**F2 卡需同步支持逗号串解析**（见 F2 §2 第 3 条，施工者核对）。若实现成本过高，可退化为"主引擎单选 + 附加勾选框"，报告说明取舍。
2. 13 个开关的映射**保持现状**（F2 后端会把 our 参数名翻成 do_*；**红线**：禁止改 `v.pitch/v.formant/v.slope/...` 现有键名）。
3. 结果展示：按表头渲染（表头已是 VS 原生列名）；`COL_LABELS` 新增**67 条**（从 `output_cols` 对照，含引擎前缀标注，如 `sF1`→"F1 (Snack)"、`pF1`→"F1 (Praat)"）。
4. **来源标注**（本卡重点）：
   - 表头/图例显示每列所属引擎（如 `sF1` 旁标 Snack）；
   - 完成消息加两行：`引擎计算：F0=Praat+Snack，Formant=Praat`、`下游基准：F0=Praat，Formant=Snack`；
   - 若 `_meta` 与 `_warnings` 提示基准引擎未计算 → 结果区顶部黄条警示。
5. **互通提示**：若本次复用了 measure/ 文件，完成消息注明"F0/Formant 复用了 measure/ 已有结果"。

### vs.css
- 仅追加 `.engine-row`/`.hint`/`.warn-bar` 等新类；**禁改既有选择器**。

## 3. 验收标准

1. 人工端到端：起 v2 → vs 页选 samples 目录 → F0 引擎勾 Snack+Praat 各跑一次 → out.tsv 表头为 VS 原生列名、**pF0 与 sF0 两列同时有值且数值不同**（证明多引擎并存 + 分列）。
2. **基准切换验收**：同一 wav 分别设 `fmtAlgorithm=praat` / `snack` → **A1/H2K 等下游列数值不同**，且界面显示的基准与实际一致。
3. **互通验收**：先用向导页对 samples 跑一个 wav（生成 `measure/*.Pitch`），再在 vs 页勾选复用跑 → 结果 F0 列取自该文件（值一致）。
4. 向导五步回归：跑通且行为与 1.2 一致（截图或描述）。
5. vs 页既有元素无丢失（下拉/按钮/勾选逐个在列——验收员对照 1.2 vs.html 清点）。
6. 交付 diff（三文件）。

## 4. 禁止事项

- 禁止改 `index.html` / `app.js` / `help.js` 等向导文件。
- 禁止删改 vs 页既有元素/ID（`#exStart`、`#paramGrid` 等全部保留）。
- 禁止引入前端框架/构建步骤（纯原生 js，沿用现风格）。
- 禁止把 COL_LABELS 之外的新增列名漏翻译（表头渲染 fallback = 原列名）。
- **禁止把不同引擎的同名参数混为一列**（如把 sF1 与 pF1 合并）——VS 原生设计就是分列，必须保持。
- 禁止省略"来源标注"（本卡重点之一）。

## 5. 停报条件

按总纲第 9 节。特别地：F2 返回结构与本卡假设不符时停报（不得在前端兜底猜字段）；多选 `<select>` 与既有 UI 风格严重冲突且无法优雅解决时停报。

---

## 6. 实施记录（2026-10-27，含架构定案修订）

> 本卡原稿假设「F0/共振峰各可多选、多引擎并存于一张表」。实施中发现与 F1 单引擎架构
> 冲突，经用户 2026-10-27 定案修订如下（**以本节为准**）：

### 6.1 架构定案（用户拍板）

1. **基准引擎单值**：F0 与共振峰的「下游基准」（`f0_algorithm`/`fmt_algorithm`）各只能
   指定**一个**，不可能用多个计算其他参数（会混乱）。VS 原生默认：F0=Straight、FMT=Snack。
2. **一次只算一套**：可以算多套，但**一次运行只算一套**，不同套分次跑、互不覆盖。
3. **双前缀命名**：输出文件 `<f0algo>_<fmtalgo>_<原名>`（如 `straight_snack_out.tsv`）——
   F0 与共振峰可能用不同算法，故两个前缀各表一套基准，一眼看出"哪套基准算的"。
4. **JSON 标记**：`<输出目录>/_results.json` 记录已算各套 `{f0_algorithm, fmt_algorithm, out, ts}`；
   导出时若存在多套 → 询问导出哪一套。
5. **基准切换规则**：
   - **向导页**（F5）：默认 praat；按 measure/ 对象动态启用/置灰，**无结果则该引擎选项置灰**，
     有结果才能换（硬拦）。
   - **vs 页**（本卡）：默认与 VS 一致（straight/snack）；**换基准但基准值还没计算 → 立即现算**。

### 6.2 vs 页实施要点

| 项 | 实施 |
|---|---|
| 引擎计算选择 | `#pitchEngine`（praat/snack/straight/other）、`#formantEngine`（praat/snack/other） |
| 下游基准选择 | `#f0Algorithm`（praat/snack/straight/shr/other）、`#fmtAlgorithm`（praat/snack/other） |
| Other 文件行 | `#otherF0Row`/`#otherF0File`/`#otherFmtRow`/`#otherFmtFile`，选 other 时显形 |
| 复用 measure/ | `#exReuse`（→ `pitchRead`/`formantRead`） |
| 警示条 | `#engineWarn`：基准≠本次计算引擎时提示"将按基准现算该引擎"（**不置灰**） |
| 多套提示 | `#exResultSets`：完成后查 `_results.json`，多套时列出并提示"导出时会询问" |
| 完成消息 | 加 `引擎计算：F0=…，Formant=… | 下游基准：F0=…，Formant=…` |

### 6.3 后端「基准补齐」实现（`server.py`，未动 F1 `engine.py`）

- **语义**：测量列（H1c/CPP/…）必须以**基准引擎**为底算 → 主跑恒以基准引擎作
  `pitch_engine`/`formant_engine`（保证下游正确）；若用户另选了「要算哪套引擎」且与基准不同，
  再补跑该引擎，只把它的**引擎列**（`*F0`、`*F1..*B4`）并进主结果。
- 新增：`_ENGINE_COL_SETS`、`_engine_columns(engine)`、`_merge_engine_columns(dst,src,engine)`。
- `run_pysauce_job`：构造 `base_reqs`（引擎=基准）跑主批；`extra_f0`/`extra_fmt` 非空时补跑并合并。
- `validate_pysauce`：`base_autocompute=1`（vs 页发）→ 不再告警"相关列将 undefined"；
  向导页无该标志 → 保持告警。

### 6.4 验证

- `tests/test_server_engine.py` 14 通过（新增 5 条：引擎列集合、合并只动引擎列、跳过 None、
  告警抑制、端到端合并出 `straight_praat_out.tsv` 且同含 `strF0`+`pF0`）。
- 全量：**324 通过 / 3 既有失败**（`test_measure_reuse_roundtrip` 卡-9.1 冲突、
  `test_other_pitch_constant` E3 停报①、`test_rv1.test_partial` 过期用例——均与本次无关）。
- 前端 `rg_ui_regress.js` **182 通过 / 0 失败**。
- 1.2 `ps-shell/` `git status --short` 空（零改动）。

### 6.5 与本卡原稿的偏离（已获批）

- 原稿「多选引擎、多引擎同表并存」→ 改为「一次一套 + 双前缀 + JSON 标记 + 分次跑」（用户定案）。
- 原稿「来源标注（表头逐列标引擎）」→ 简化为完成消息双行 + 多套提示（列名本身已含引擎前缀
  `sF0`/`pF0`/`strF0`，无需再逐列翻译）。

---

## 7. G1 打包收尾时的补充改动（2026-10-27）

- **版本号升 2.0**（G1 §2.5）：`ui/feedback.js::PRAATSAUCE_VERSION` = `'向导界面 2.0'`；
  `ui/index.html #appVer` 同步；`ui/app.js` 兜底同步；`ui/vs.html` 关于弹窗标题改
  「VoiceSauce 风格界面 2.0」并把引擎描述从"底层主要是 Praat 脚本"改为
  "可由 Praat/Snack(RAPT-LPC 复刻)/STRAIGHT/外部文件计算，F0 与共振峰可分别指定基准引擎"。
- **首页 `ui/launch.html` 文案更新**（用户 2026-10-27 追加要求）：
  - 副标题去掉"计算全部由本机 Praat 完成，这个程序只是个外壳" → 改"测量由本机完成，无需 MATLAB Runtime"。
  - VoiceSauce 卡第 3 条"底层仍是 Praat 引擎，免 MATLAB Runtime" → 改
    "按论文独立实现 VS v1.37 核心算法，F0 / 共振峰基准引擎可分别指定"。
  - ⚠ 1.2 的 `ps-shell/ui/launch.html` **未动**（1.2 冻结铁律）。
