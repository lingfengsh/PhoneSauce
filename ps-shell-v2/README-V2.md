# PhoneSauce 嗓音分析助手 2.0（ps-shell-v2）

> **源于 praatSauce / VoiceSauce 的中文嗓音（发声态）声学分析工具。**
>
> 本目录是 **PhoneSauce 2.0**（原工作名 "PraatSauce 助手 2.0"），与 1.2（`../ps-shell/`）
> **完全独立、可同时运行**。

## 与 1.2 的关系

| | 1.2（`../ps-shell/`，旧名 PraatSauce 助手） | 2.0（本目录，PhoneSauce） |
|---|---|---|
| 向导界面算法 | Praat 脚本（`scripts/`） | 仍用 Praat 脚本（**不变**） |
| VoiceSauce 界面算法 | 复用 Praat 结果 + 少量 Python 补算 | **pysauce 原生实现 VS v1.37 算法**（Python，按论文独立实现） |
| 引擎 | 仅 Praat | Praat / pysauce / Snack（RAPT·LPC 复刻）/ STRAIGHT（legacy 近似）/ 外部文件 |
| 目的 | 稳定可用 | 方便**比较不同引擎/算法的计算结果** |

两版共用同一套 `measure/` 目录与 `.Pitch`/`.Formant` 格式，数据可互通。

## 目录说明

- `backend/pysauce/` —— VoiceSauce v1.37 算法的 Python 实现（2.0 的核心；按论文独立实现，不含其 MATLAB 源码）
- `backend/` —— 外壳服务（server.py 等），复制自 1.2 后按 2.0 需求改造
- `ui/` —— 界面（`index.html` 向导 / `vs.html` VoiceSauce 风格 / `launch.html` 选择界面）
- `scripts/` —— Praat 脚本（向导界面用，复制自仓库根 `scripts/`）+ `scripts/vs_praat/`（VoiceSauce 版 F0/共振峰脚本）
- `samples/` —— 示例音频（复制自仓库根 `samples/`）
- `vendor/` —— 外部引擎二进制（snack.exe 等，不进 git）

## 工程卡

2.0 的全部改造以工程卡为施工依据，见 `../docs/v2.0-工程卡/`（00-总纲 + A1..G1）。
规划全文见 `../docs/v2.0-VoiceSauce算法迁移规划.md`。

## 打包

- 构建配置：`../packaging/PraatSauce2.spec`（入口 `app.py`）
- 组装脚本：`../packaging/stage2.py`
- 产物：`_build/dist2/`（2.0 独立于 1.2 的 `_build/dist/`）
