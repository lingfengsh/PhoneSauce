# -*- coding: utf-8 -*-
"""输出列清单（V2-F1 §3）—— VoiceSauce 原生 67 列。

**唯一事实源**：`refs/voicesauce-v137/func_getoutputparameterlist.m`。
该函数返回一个 cell 数组，每项形如 ``'H1* (H1c)'``（显示名 + 括号内短名）。
机器列名 = **括号内短名**。

── 实测核对结论（2026-10-26，脚本从蓝本正则抽取，非手写）────────────────────
  显示名条数 = **67**
  短名条数   = **67**
  短名唯一数 = **67**（无重复）

⚠ 工程卡 §3 写「66 短名」，并提示「必须找出差在哪」。**已查明：卡的算术笔误**——
  卡把「未校正量」写成 14 项，但其列表 ``H1u, H2u, H4u, A1u, A2u, A3u, H2Ku, H5Ku,
  H1H2u, H2H4u, H1A1u, H1A2u, H1A3u, H42Ku, H2KH5Ku`` 实际是 **15** 项。
  卡又提示「蓝本有 '2K (H2Ku)' 与 '5K (H5Ku)' 两条但短名 H2Ku/H5Ku 已计入」——
  这句是对的，但结论应是**计入后 15 项**，而非从 14 里再减。
  正确计数：**14 + 7 + 15 + 5 + 12 + 12 + 2 = 67**。
  → 蓝本 67 显示名 = 67 短名，**不存在差 1**。本模块按蓝本原序写 67 项。

短名分组（与蓝本顺序完全一致）：
  校正量 14：H1c H2c H4c A1c A2c A3c H2Kc | H1H2c H2H4c H1A1c H1A2c H1A3c H42Kc H2KH5Kc
  标量   7：CPP Energy HNR05 HNR15 HNR25 HNR35 SHR
  未校正 15：H1u H2u H4u A1u A2u A3u H2Ku H5Ku | H1H2u H2H4u H1A1u H1A2u H1A3u H42Ku H2KH5Ku
  F0 五引擎 5：strF0 sF0 pF0 shrF0 oF0
  共振峰 12：sF1..sF4 pF1..pF4 oF1..oF4
  带宽   12：sB1..sB4 pB1..pB4 oB1..oB4
  激励   2：epoch soe

另加一列非蓝本列 ``time``（1 ms 时间轴，秒），**不入 OUTPUT_COLS**，由 F2 放最前。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

# ── 蓝本原序 67 短名（禁改顺序：F2/F3 按此序出表）─────────────────────────
OUTPUT_COLS: list[str] = [
    # 校正量（14）—— func_getoutputparameterlist.m L15-28
    "H1c", "H2c", "H4c", "A1c", "A2c", "A3c", "H2Kc",
    "H1H2c", "H2H4c", "H1A1c", "H1A2c", "H1A3c", "H42Kc", "H2KH5Kc",
    # 标量测量（7）—— L29-35
    "CPP", "Energy", "HNR05", "HNR15", "HNR25", "HNR35", "SHR",
    # 未校正量（15）—— L36-50
    "H1u", "H2u", "H4u", "A1u", "A2u", "A3u", "H2Ku", "H5Ku",
    "H1H2u", "H2H4u", "H1A1u", "H1A2u", "H1A3u", "H42Ku", "H2KH5Ku",
    # F0 五引擎（5）—— L51-55
    "strF0", "sF0", "pF0", "shrF0", "oF0",
    # 共振峰四引擎（12）—— L56-67
    "sF1", "sF2", "sF3", "sF4",
    "pF1", "pF2", "pF3", "pF4",
    "oF1", "oF2", "oF3", "oF4",
    # 带宽四引擎（12）—— L68-79
    "sB1", "sB2", "sB3", "sB4",
    "pB1", "pB2", "pB3", "pB4",
    "oB1", "oB2", "oB3", "oB4",
    # 激励（2）—— L80-81
    "epoch", "soe",
]

# 非蓝本列（时间轴），单独常量，避免误入 OUTPUT_COLS 计数
TIME_COL = "time"

# 蓝本显示名（供 F3 表头显示；顺序与 OUTPUT_COLS 一一对应）
DISPLAY_NAMES: list[str] = [
    "H1*", "H2*", "H4*", "A1*", "A2*", "A3*", "2K*",
    "H1*-H2*", "H2*-H4*", "H1*-A1*", "H1*-A2*", "H1*-A3*", "H4*-2K*", "2K*-5K",
    "CPP", "Energy", "HNR05", "HNR15", "HNR25", "HNR35", "SHR",
    "H1", "H2", "H4", "A1", "A2", "A3", "2K", "5K",
    "H1-H2", "H2-H4", "H1-A1", "H1-A2", "H1-A3", "H4-2K", "2K-5K",
    "F0 - Straight", "F0 - Snack", "F0 - Praat", "F0 - SHR", "F0 - Other",
    "F1 - Snack", "F2 - Snack", "F3 - Snack", "F4 - Snack",
    "F1 - Praat", "F2 - Praat", "F3 - Praat", "F4 - Praat",
    "F1 - Other", "F2 - Other", "F3 - Other", "F4 - Other",
    "B1 - Snack", "B2 - Snack", "B3 - Snack", "B4 - Snack",
    "B1 - Praat", "B2 - Praat", "B3 - Praat", "B4 - Praat",
    "B1 - Other", "B2 - Other", "B3 - Other", "B4 - Other",
    "epoch", "SoE",
]


def empty_result() -> dict:
    """全部列 → None（F2 落表时写空 / --undefined--）。

    ``_meta`` 与 ``_warnings`` 为特殊键，不属 67 列。
    """
    res: dict = {c: None for c in OUTPUT_COLS}
    res["_meta"] = {}
    res["_warnings"] = []
    return res


def is_output_col(name: str) -> bool:
    return name in OUTPUT_COLS
