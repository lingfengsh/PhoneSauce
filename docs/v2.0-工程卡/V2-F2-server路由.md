# V2-F2：server.py 引擎路由 → ps-shell-v2/backend/server.py

> 难度：中（改 1.2 复制品，边界敏感）。前置：V2-F1。
> 参照：`ps-shell-v2/backend/server.py`（= 1.2 副本；`/api/run` 在 do_POST 内，`/api/validate` 同）。

## 0. 目标一句话

`/api/run` 加 `engine` 字段：缺省（无该字段或 `"praat"`）走 1.2 原 Praat 脚本链（**向导零变化**）；`"pysauce"` 走 `pysauce.engine.run_batch`。`/api/validate` 同理双轨。

## 1. 文件白名单

修改（唯一）：
- `ps-shell-v2/backend/server.py`

## 2. 改造规格（精确到行为，禁扩大）

### /api/run（do_POST 内，1.2 定位：`p == "/api/run"` 分支）
1. 请求体 `{"values": {...}, "files": [...], "engine": "pysauce"|"praat"}`（`engine` 缺省 = `"praat"`）。
2. `engine == "praat"`：**原代码路径一行不动**（1.2 的 startRun/praatSauce 链）。
3. `engine == "pysauce"`：新函数 `run_pysauce_job(values, files, job)`：
   - 把 1.2 `values` 的 13 个参数开关（pitch/formant/harmonicAmplitude/...，见 vs.js buildValues）映射为 F1 `EngineRequest` 字段（映射表写进代码注释与报告）；
   - `values.pitch_engine`/`values.formant_engine`（F3 新增，缺省 `"praat"`）透传——**决定"算哪几套"**；
   - **`values.f0_algorithm`/`values.fmt_algorithm`（F3 新增，决定"下游用哪套"，见 F1 §0c）透传**；缺省取 `vs_Initialize.m` L71/72 的 VS 默认值（`"straight"`/`"snack"`），但**若对应引擎未勾选计算，须回退为已勾选引擎并在 warnings 注明**（VS 行为是直接产出 NaN，此处按 F1 §0c 第 2 条：不回退，交给用户设置）；
   - **数据互通参数**（F1 §0b）：`values.pitchRead`/`pitchReadDir`/`formantRead`/`formantReadDir` → `EngineRequest.reuse`/`measure_dir`/`pitch_read_dir`/`formant_read_dir`；**`measure_dir` 缺省 = 输入目录下 `measure/`**（照 1.2 `server.py` L218–279 的既有推导逻辑，禁止另立规则）；
   - `values.praatExe` 来自 settings（1.2 的 settings 模块读取方式照抄 server.py 内既有用法）；
   - 逐文件 `run_batch(reqs, progress_cb)`：`progress_cb(done,total)` 写 job 进度（1.2 的 watch 机制字段名照抄现有 job 结构——读 server.py 内 job 创建/更新代码后对接）；
   - 输出 out.tsv：表头 = `time` + `OUTPUT_COLS`（F1 顺序）；值 `None` → `--undefined--`（沿用 1.2 导出约定）；浮点保留 6 位小数；路径 = `values.outputDir/values.outputFile`。
   - **`_meta`（`f0_algorithm`/`fmt_algorithm`）写入 job summary**，供 F3 界面显示"本批基准引擎"。
   - 结果 job 的 `resultPath`/`summary.rowCount` 字段结构与 1.2 一致（前端 pollJob 不改）。
4. **异常**：pysauce 分支的顶层 try/except → job 置 error + message（照 1.2 job 错误格式），禁止裸 raise 打崩线程池。

### /api/validate
- `engine == "pysauce"`：新校验（输入目录存在、≥1 个选中扩展名文件、输出目录可写、praat_exe 存在（当任一引擎选 praat）、snack.exe 存在（当选 snack）、other 文件路径存在（当选 other））。**新增校验**：`f0_algorithm`/`fmt_algorithm` 指定的引擎若未在 `pitch_engine`/`formant_engine` 中勾选 → 返回 **warning**（不阻断，提示"下游基准引擎未计算，相关列将为 undefined"）。返回 `{"ok":bool,"errors":[...],"warnings":[...]}` 结构与 1.2 一致。
- 缺省路径原样不动。

### 禁改清单（本卡红线）
- 向导用到的全部端点（/api/scan、/api/review/*、/api/export、/api/preprocess 等）**一行不动**；
- `do_GET` 全部不动；
- Token/guard 机制不动；
- settings 模块不动。

## 3. 验收标准

1. `pytest ps-shell-v2/tests/ -x -q` 全绿 + 新增两个测试（写进 `tests/test_server_engine.py`——**允许创建**，白名单补充此文件）：
   ```python
   # -*- coding: utf-8 -*-
   """server engine 路由测试。禁改。"""
   import json
   import urllib.request

   import pytest


   def _post(base, path, payload):
       req = urllib.request.Request(
           base + path, data=json.dumps(payload).encode(),
           headers={"Content-Type": "application/json"}, method="POST")
       # Token 由 bootstrap cookie 提供——测试内先 GET /api/bootstrap 拿 token
       import http.cookiejar
       cj = http.cookiejar.CookieJar()
       opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
       opener.open(base + "/api/bootstrap").read()
       return json.loads(opener.open(req).read())


   def test_validate_pysauce_missing_dir(tmp_path):
       # 起服务 → validate 输入目录不存在 → ok=false
       ...  # 由施工者按 server.py 现有测试基建（若有）写完整版；
            # 若 server 无测试基建，改为直接调用处理函数（import server 模块级函数）
   ```
   ⚠️ 上面测试是**半成品骨架**：施工者读 `ps-shell-v2/tests/` 现状后补完（若 1.2 无 server 测试基建，可改为对 `run_pysauce_job` 的直接单元测试——mapper 函数把 values→EngineRequest 的映射单测必须覆盖全部 13 个开关）。
2. 人工：起 v2 服务，向导五步跑一遍 samples（引擎路由缺省 = 1.2 行为不变）；vs 页手发 `engine:"pysauce"` 请求（可用浏览器 devtools）出表。
3. 交付 diff（server.py）+ 映射表 + 上述测试。

## 4. 禁止事项

- 禁止重构 server.py 任何既有函数（包括"顺手"改名/抽函数）。
- 禁止动 1.2 的 `ps-shell/backend/server.py`。
- 禁止在 handler 线程里直接跑 run_batch（必须走 1.2 现有 job/线程机制）。

## 5. 停报条件

按总纲第 9 节。特别地：若发现 1.2 job 机制无法承载 pysauce 的进度回调，停报（不得自创第二套 job）。
