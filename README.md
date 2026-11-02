# PhoneSauce 嗓音分析助手

> **源于 praatSauce / VoiceSauce 的中文嗓音（发声态）声学分析工具。**
>
> 多引擎：Praat / pysauce（按论文独立实现 VoiceSauce v1.37 核心算法）/ Snack（RAPT·LPC 复刻）/ STRAIGHT（legacy 近似）/ 外部文件。
> 提供向导界面与 VoiceSauce 风格界面，带试跑、九宫格审核、人工修正与结构化导出。

源码仓库：<https://github.com/lingfengsh/PhoneSauce>
（`praat.exe` 不随仓库分发，配置方法见下文「Praat 从哪里来」。）

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23463195.svg)](https://doi.org/10.5281/zenodo.23463195)

- 已归档版本：**v1.2.0**（[版本 DOI](https://doi.org/10.5281/zenodo.23463196)），代码在 `ps-shell/`。
- 当前版本：**2.0.0**（PhoneSauce），代码在 `ps-shell-v2/`。
- 概念 DOI `10.5281/zenodo.23463195` 始终指向最新版本，论文引用请用它。

<p align="center">
  <img src="docs/screenshots/step1.png" width="820" alt="第一步：选择声音文件">
</p>

一套中文、零编程门槛的语音声学分析工具：批量提取 F0、共振峰、谐波幅度差（H1-H2 / H1-A3 / H2K / H5K）、HNR、CPP、SHR、SoE、能量等
60 余项指标，带试跑体检、九宫格审核、人工修正与结构化导出。面向语言学 / 语音学 /
方言与发声态研究，Windows 平台，离线可用。

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [快速开始](#快速开始)
- [Praat 从哪里来](#praat-从哪里来)
- [两套界面与多引擎](#两套界面与多引擎)
- [工作流](#工作流)
- [目录结构](#目录结构)
- [从源码运行](#从源码运行)
- [构建发布包](#构建发布包)
- [测试](#测试)
- [已知限制](#已知限制)
- [许可证](#许可证)
- [引用](#引用)

---

## 它解决什么问题

[VoiceSauce](https://www.phonetics.ucla.edu/voicesauce/) 是这一领域的经典工具，但它有两个门槛：
要装 MATLAB Runtime（几个 GB），而且只能整目录盲跑 —— 参数设错，全部重来。

[PraatSauce](https://github.com/kirbyj/praatsauce) 用 Praat 脚本实现了大部分同类指标，轻量、
开源、可改；但它是命令行脚本集，参数对非技术用户并不友好。

本项目在两者之间补上操作层，并在 2.0 引入**多引擎**以便比较不同算法的结果：

| 痛点 | 这里的做法 |
|---|---|
| 参数看不懂 | 向导界面两档视图（新手 / 进阶），新手只面对几个决定 |
| 参数错了要全部重跑 | 先试跑 1 个文件，看 F0 / 共振峰曲线和体检结论，确认后再批量 |
| 不知道哪个文件测坏了 | 按文件统计基频检出率，自动点名异常文件（排除静音段干扰） |
| 逐段核对很费眼 | 九宫格批量看图 + 单文件详情，支持删帧 / 补点 / 改 F0 / 平滑共振峰 |
| 只信一套引擎 | 2.0 可分别指定 F0 / 共振峰的基准引擎（Praat / pysauce / Snack / STRAIGHT），横向比较 |
| 结果要自己拼表 | 一键导出 CSV / XLSX / 逐文件 / 逐参数四种版式 |

---

## 快速开始

### 用发布包（推荐给大多数用户）

1. 解压 `PhoneSauce-2.0-*.zip` 到任意目录（**路径避免中文和空格**，例如 `D:\PhoneSauce`）。
2. 双击 `PhoneSauce.exe`。
3. 第一次打开会让你选界面（向导 / VoiceSauce 风格），之后记住选择。

发布包已经自带 `praat.exe`，开箱即用。

### 用源码

见 [从源码运行](#从源码运行)。

---

## Praat 从哪里来

本程序的**源代码仓库不包含 `praat.exe`**（它是 90 多 MB 的二进制，且许可是 GPL，
与本项目的 MIT 不同 —— 见 [许可证](#许可证)）。程序按以下顺序找 Praat：

| 顺序 | 位置 | 说明 |
|---|---|---|
| 1 | 设置页手动指定 | **最推荐**。点「设置 → Praat 程序路径 → 浏览」，选中 `Praat.exe` |
| 2 | 与主程序同目录 | 把 `praat.exe` 复制到 `PhoneSauce.exe` 旁边即可，便于绿色部署 |
| 3 | 常见安装位置 | `C:\Program Files\Praat\Praat.exe`、`%LOCALAPPDATA%\Programs\Praat\Praat.exe` 等 |
| 4 | 都没有 | 设置页会给出下载提示 |

Praat 官方下载：<https://praat.org>

> **版本要求**：建议 Praat **6.4.01 及以上**。上游脚本以 6.4.01 为测试基线，大量使用
> 向量化运算与较新的 `To Pitch (filtered autocorrelation)`，版本太老会直接报错。
> 本项目实际验证版本为 **7.0.02**（2026-08-26 构建）。

> **pysauce / Snack / STRAIGHT 不需要 Praat**：这三类引擎由 Python 原生实现或在程序内
> 复刻，只有 Praat 引擎本身才调用 `praat.exe`。

---

## 两套界面与多引擎

2.0 在 `ps-shell-v2/` 下提供两套界面（启动时有 `launch.html` 选择页）：

- **向导界面**（`index.html`）：五步向导，新手友好。算法上仍用 Praat 脚本做向导的测量。
- **VoiceSauce 风格界面**（`vs.html`）：模仿 VoiceSauce 的矩阵式参数面板，便于**比较不同引擎**。

**引擎**（决定"数怎么算"）：

| 引擎 | 用于 | 实现说明 |
|---|---|---|
| **Praat** | F0 / 共振峰 / 多数声学量 | 调用本机 Praat 脚本（与 1.2 一致） |
| **pysauce** | F0 / 共振峰 / 谐波量 / CPP / HNR / SoE 等 | 按论文**独立实现** VoiceSauce v1.37 核心算法（Python + NumPy/SciPy），不含其 MATLAB 源码 |
| **Snack**（复刻） | F0 / 共振峰 | RAPT 基频 + LPC 自相关共振峰的 Python 复刻（**非**真 Snack 二进制） |
| **STRAIGHT**（近似） | F0 | legacy-STRAIGHT 的 Python 复现（`pylstraight`），仅提供 F0 基准 |
| **外部文件** | 任意列 | 读入你用别的工具算好的数据列，按引擎列覆盖 |

> ⚠️ **诚实声明**：本项目**不是** VoiceSauce 的移植，也**不**包含其源代码或 MATLAB 运行时。
> `pysauce` 是按公开论文**独立实现**的 VS v1.37 核心算法；Snack / STRAIGHT 为算法**复刻 / 近似**，
> 与原始实现存在数值差异。若论文中使用这两类引擎的结果，请按 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
> 的指引注明所用实现，并引用上游（PraatSauce / Snack / STRAIGHT / VoiceSauce 论文）。

---

## 工作流

向导界面是五步，每一步都能回头改：

| 步骤 | 做什么 | 为什么放在这一步 |
|---|---|---|
| **1 选择音频** | 选目录，看文件数 / 时长 / 采样率 | 先确认读到的东西是对的 |
| **2 要测什么** | 选研究目标预设 + 发音人，参数自动配好 | 新手不用面对几十个参数 |
| **3 批量运行** | 运行前检查 → 试跑 → 进度 / 日志 → 结果诊断 | 参数错了在这里拦住，不把锅甩给引擎报错 |
| **4 查看结果** | 九宫格一屏 9 个文件，点进去看单文件详情 | 批量跑完不等于测对了，要能逐段核对 |
| **5 导出数据** | 选列、选版式、导出 CSV / XLSX | 结果要能直接进 R / Python |

**试跑**嵌在第三步：点「开始批量处理」之前可以先只跑 1 个文件，看完基频 / 共振峰曲线
和体检结论，确认没问题再放开整批。

第四步的九宫格可以**改**，不只是看：一屏 9 个文件，看基频点是否落在元音段上、共振峰轨迹
是否连续；点进单个文件可以删掉误判的帧、手工补点、切分 TextGrid、平滑共振峰轨迹。
审核过的结果会写回 `measure/` 目录，下次批量直接复用，不重算。

### 主要能力

- **基频**：Praat `To Pitch (filtered autocorrelation)`；pysauce 自相关 + 重采样；Snack RAPT；STRAIGHT 近似
- **共振峰**：Burg / 多档 LPC 阶数择优，FormantPath 精修，Viterbi 平滑；pysauce / Snack 复刻
- **声质**：H1-H2、H1-A3、HNR（分频带）、CPP / CPPS、SHR、SoE、能量
- **区间**：按 TextGrid 标注段测量，自动配对同名 TextGrid，静音段不计入检出率
- **导出**：TSV / CSV（带 BOM）/ XLSX；单表、逐文件、逐参数四种版式
- **可复现**：参数落盘，中间对象存 `measure/`，随时可重跑比对；两版共用 `measure/` 与 `.Pitch`/`.Formant` 格式

---

## 目录结构

```
PhoneSauce/
├── ps-shell/              v1.2（已冻结归档，旧名 PraatSauce 助手）
│   ├── app.py            入口：本地 HTTP 服务 + 原生窗口
│   ├── backend/          后端（参数、Praat 调用、批量调度、审核、导出）
│   ├── ui/               前端（原生 JS，无框架、无 CDN，完全离线）
│   ├── tests/            unittest + 前端回归脚本
│   └── vowel_data/       IPA 元音参考值
├── ps-shell-v2/          2.0（PhoneSauce，当前版本）
│   ├── app.py            入口
│   ├── backend/          外壳服务；backend/pysauce/ 为 VS v1.37 算法的 Python 实现
│   ├── ui/               界面（index.html 向导 / vs.html VS 风格 / launch.html 选择）
│   ├── scripts/          Praat 脚本 + scripts/vs_praat/（VS 版 F0/共振峰脚本）
│   └── samples/          示例音频（复制自仓库根 samples/）
├── scripts/              实际运行的 Praat 脚本（含上游 PraatSauce + ps_ 扩展）
├── praatsauce-master/    上游 PraatSauce 1.0.8 原样副本（MIT，供对照）
├── packaging/            打包脚本
│   ├── PraatSauce.spec   v1.2 PyInstaller 配置
│   ├── PraatSauce2.spec  2.0 PyInstaller 配置
│   ├── stage.py / stage2.py  组装分发包
│   ├── fetch_wheels.py   下载 pywebview 等依赖到 _build/_vendor
│   └── 入手简介.txt / 入手简介2.txt  随包短说明
├── docs/
│   ├── screenshots/      README 截图
│   ├── v2.0-工程卡/       2.0 改造任务卡（施工依据，历史记录）
│   └── PraatSauce使用说明.docx / 各 v2.0 说明文档
├── LICENSES/             GPL-3.0 / Apache-2.0 / BSD-2-Clause / 上游 MIT 全文
├── LICENSE               本项目 MIT
├── THIRD-PARTY-NOTICES.md 第三方组件与 Praat 许可说明（含合规声明）
├── CITATION.cff          引用信息
└── CHANGELOG.md          版本记录
```

`samples/`、`_build/`、`logs/`、`praat.exe`、`refs/`（VoiceSauce 上游 MATLAB 源码，不分发）都不入库（见 `.gitignore`）。
`samples/` 可用 `python ps-shell/tools/make_samples.py` 重新生成。

---

## 从源码运行

需要 **Python 3.13**（3.10+ 应该也可以，未逐一验证）。

```bash
git clone <本仓库地址> PhoneSauce
cd PhoneSauce

# 可选：装原生窗口依赖。不装也能跑，只是界面开在浏览器里
pip install pywebview

# 启动 2.0（默认 pywebview 独立窗口；可用 --browser 强制开浏览器）
python ps-shell-v2/app.py
```

`app.py` 起一个只监听 `127.0.0.1` 的本地服务，仅本机可访问。关闭窗口后
服务会自行退出；调试时也可以用 `python ps-shell-v2/serve_only.py [端口]` 只起服务、不开窗口。

然后按 [Praat 从哪里来](#praat-从哪里来) 配好 Praat 路径，就可以跑示例数据了。

---

## 构建发布包

只在 **Windows** 上构建（产物是 Windows exe）。需要 Python 3.13 + PyInstaller。

```bash
# 0) 准备依赖（只需第一次；会下载 pywebview/pythonnet 等 wheel 到 _build/_vendor）
python packaging/fetch_wheels.py

# 1) 编译 2.0（产物在 _build/dist2/PhoneSauce）
python -m PyInstaller --noconfirm \
    --workpath _build/build2 --distpath _build/dist2 \
    packaging/PraatSauce2.spec

# 2) 组装外部资源（ui/ scripts/ samples/ praat.exe 等复制到 exe 同目录）
python packaging/stage2.py

# 3) 试运行
_build\dist2\PhoneSauce\PhoneSauce.exe
```

**两个容易踩的坑**：

- `--workpath` / `--distpath` 必须显式写成上面这两个路径。不写的话 PyInstaller 会输出到
  当前工作目录下的 `build/` 和 `dist/`，与 `stage2.py` 的组装目录错开 —— 表现是"改了却没生效"。
- `ui/`、`scripts/`、`samples/` 是**外部资源**，不进 exe。改界面、改脚本不需要重新编译，
  只有后端 `.py` 变了才要重打。`stage2.py` 结尾会做新鲜度检查。

打 zip 前记得把 `praat.exe`、`samples/`、`docs/` 一并放进分发包，并附上
`LICENSE`、`LICENSES/`、`THIRD-PARTY-NOTICES.md`（GPL 合规要求，见下）。

---

## 测试

```bash
# 后端（mock 掉 Praat，不需要真跑）
python -m unittest discover -s ps-shell-v2/tests -t ps-shell-v2 -v

# 前端回归（node vm，不需要浏览器）
node ps-shell-v2/tests/rg_ui_regress.js
node ps-shell-v2/tests/engine_ui_regress.js
```

前端回归覆盖九宫格渲染、选择保存、导出参数、F0 手工点算法、引擎基准选择等纯逻辑分支，
GUI 相关的部分靠手工验收。

---

## 已知限制

- **仅 Windows**。代码本身是跨平台的（Python + 原生 JS），但打包脚本、pywebview 的
  WebView2 后端、以及部分 Praat 控制台解码逻辑是按 Windows 写的。
- **Praat 路径必须正确**（仅 Praat 引擎需要）。找不到 Praat 时不会静默失败，会明确报错并给出下载地址。
- **中文路径**：读取没问题，但个别 Praat 版本写文件时对非 ASCII 路径支持不好，
  建议音频和输出目录都用纯英文、无空格路径。
- **超长录音**：整段测量很慢且占内存。10 分钟以上的录音建议先做 TextGrid 切分。
- **共振峰上限**：`maxFormant` 默认按发音人给（男 5000 / 女 5500 / 儿童 5500 Hz），
  嗓音特殊的发音人需要手动调；太高会引入虚假极点，太低会丢 F3/F4。
- **不做统计**。本程序只负责"把数测出来并保证测得对"，混合模型、归一化、绘图请导出后
  交给 R / Python / Praat。
- **复刻引擎的差异**：pysauce / Snack / STRAIGHT 是独立实现或近似，与原始工具存在数值差异；
  正式发表前请核对所用引擎，并按 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) 注明与引用。
- `praatsauce-master/` 是上游原样副本，只作参考；实际运行的是 `scripts/` 里的版本
  （已打补丁，差异见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)）。

---

## 许可证

本项目代码以 **MIT** 发布，见 [LICENSE](LICENSE)。

但发布包里部分组件**不是 MIT**：

| 组件 | 许可证 | 说明 |
|---|---|---|
| 本程序（ps-shell-v2、ps_*.praat、构建脚本） | MIT | 随便用，保留版权声明即可 |
| `praat.exe` | **GPL-3.0-or-later** | © Paul Boersma & David Weenink |
| `pysauce` 依赖的 OS-P 组件 | **Apache-2.0** | vendored 进 `ps-shell-v2/pysauce/_vendor/`（上游 MIT 标注见其文件头） |
| 部分 Python 依赖（如 `pylstraight` 片段） | **BSD-2-Clause** 等 | 见 `LICENSES/` 与各文件头 |
| `praatsauce-master/` 与 `scripts/` 中的上游脚本 | MIT | © 2024 praatsauce authors |

本程序通过**子进程**调用 Praat（命令行参数 + 文件交换），不链接、不派生，因此自身
不必变成 GPL。但如果你分发**包含 `praat.exe` 的安装包**，需要同时提供：

1. Praat 的许可证全文（[`LICENSES/GPL-3.0.txt`](LICENSES/GPL-3.0.txt)）；
2. Praat 的版本与版权信息（[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)）；
3. 源码获取地址：<https://www.praat.org/download_sources.html>。

细节和合规选项见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

---

## 引用

如果你在论文里用了本工具，请引用本仓库（见 [CITATION.cff](CITATION.cff)），
**并同时引用上游 PraatSauce 与 Praat**；若使用了 pysauce / Snack / STRAIGHT 引擎，
请按 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) 补充对应引用。

```bibtex
@software{phonesauce,
  title  = {PhoneSauce 嗓音分析助手：多引擎中文嗓音（发声态）声学分析工具},
  author = {零 \& AI},
  year   = {2026},
  version= {2.0.0},
  doi    = {10.5281/zenodo.23463195},
  note   = {MIT License},
  url    = {https://github.com/lingfengsh/PhoneSauce}
}

@software{praatsauce,
  title  = {PraatSauce. Praat-based tools for spectral processing},
  author = {Kirby, James and Puggaard-Rode, Rasmus},
  year   = {2025},
  version= {1.0.8},
  url    = {https://github.com/kirbyj/praatsauce}
}

@manual{praat,
  title  = {Praat: doing phonetics by computer},
  author = {Boersma, Paul and Weenink, David},
  year   = {2026},
  note   = {Version 7.0.02},
  url    = {https://praat.org}
}
```

DOI 的获取方式见 [CITATION.cff](CITATION.cff) 顶部注释，或仓库的 Releases 页面。
2.0 的版本 DOI 将在 GitHub Release 发布后由 Zenodo 自动生成（概念 DOI 不变）。
