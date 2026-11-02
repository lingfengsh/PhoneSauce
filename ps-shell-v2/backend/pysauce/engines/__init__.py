# -*- coding: utf-8 -*-
"""VoiceSauce 2.0 引擎包装层。

各引擎（Praat / Snack / STRAIGHT / Other）在此目录下以独立模块实现，
统一向上层（编排/输出层）暴露「帧网格对齐后的测量向量」。

引擎与对象后缀的唯一定义见 review_export.ENGINE_OBJECT_EXT（两界面互通约定）。

合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""
