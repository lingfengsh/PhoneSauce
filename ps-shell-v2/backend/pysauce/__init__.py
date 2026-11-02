# -*- coding: utf-8 -*-
"""pysauce —— VoiceSauce v1.37 声学参数的 Python 独立实现。

本包按公开论文与 VoiceSauce v1.37 的**行为语义**（参数约定、系数、分支、输出列名）
独立实现，供 PhoneSauce 2.0 的 VoiceSauce 页面使用：

  · SHR/SHRP、F0 引擎包装、谐波幅度校正与带宽映射：改编自 OpenSauce
    （opensauce-python，Apache-2.0，doi:10.5281/zenodo.2638411），文件级 vendored
    于 `_vendor/osp_*.py`，改动逐条记于其文件头；
  · 其余测量项（CPP/HNR/Energy/SoE/2K/5K/斜率组合等）：按公开论文独立实现。

**不含任何 VoiceSauce（© UCLA SPAPL）MATLAB 源码**——`refs/voicesauce-v137/` 仅为
只读行为蓝本，永不进仓库、永不进分发包。出处详见 `THIRD-PARTY-NOTICES.md` §5–§9。

约定：纯算法无 I/O 副作用；NaN 表示未定义；见 docs/v2.0-工程卡/00-总纲.md 第 5 节。

合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本包按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""
__version__ = "2.0.0-dev"
