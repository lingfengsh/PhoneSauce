# -*- coding: utf-8 -*-
"""基准引擎选择（V2-F1 §0c）—— ``parse_f0`` / ``parse_fmt``。

**语义严格照蓝本** `refs/voicesauce-v137/func_parseF0.m`（35 行）与
`func_parseFMT.m`（55 行）：

  • `func_parseF0.m`：``switch(F0algorithm)`` 从已算好的 matdata 里**挑一个向量**：
      - ``'F0 (Straight)'`` → ``strF0``
      - ``'F0 (Snack)'``    → ``sF0``
      - ``'F0 (Praat)'``    → ``pF0``
      - ``'F0 (SHR)'``      → ``shrF0``
      - ``'F0 (Other)'``    → ``oF0``
      - otherwise / 字段不存在 → ``F0 = []``（**空**）
  • `func_parseFMT.m`：同款，``'Formants (Snack)'``→``sF1..sB3``、
    ``'Formants (Praat)'``→``pF1..pB3``、``'Formants (Other)'``→``oF1..oB3``；
    否则全空。

⚠️ **关键：不自动回退**。蓝本在指定引擎列不存在时返回空数组，下游算法随之产出
   NaN——本模块照做，**绝不** fallback 到别的引擎（否则「基准引擎」设置形同虚设，
   且用户无法察觉自己选错了）。

2.0 的 ``f0_algorithm`` / ``fmt_algorithm`` 用**短名语义**取值
（``"praat"|"snack"|"straight"|"shr"|"other"``），与 VS 的显示名一一对应：

  | 2.0 取值 | VS 显示名（func_parseF0 的 case） | 列 |
  |---|---|---|
  | ``straight`` | ``F0 (Straight)`` | strF0 |
  | ``snack``    | ``F0 (Snack)``    | sF0   |
  | ``praat``    | ``F0 (Praat)``    | pF0   |
  | ``shr``      | ``F0 (SHR)``      | shrF0 |
  | ``other``    | ``F0 (Other)``    | oF0   |

  | 2.0 取值 | VS 显示名（func_parseFMT 的 case） | 列 |
  |---|---|---|
  | ``snack`` | ``Formants (Snack)`` | sF1..sB3 |
  | ``praat`` | ``Formants (Praat)`` | pF1..pB3 |
  | ``other`` | ``Formants (Other)`` | oF1..oB3 |

  （``straight`` 不出现在 FMT 侧——STRAIGHT 不产共振峰。）
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

# 2.0 短名 → F0 列名（等价 func_parseF0.m 的 case → matdata 字段）
_F0_FIELD = {
    "straight": "strF0",
    "snack": "sF0",
    "praat": "pF0",
    "shr": "shrF0",
    "other": "oF0",
}

# 2.0 短名 → Formant 列名（等价 func_parseFMT.m 的 case → matdata 字段）
_FMT_FIELDS = {
    "snack": ("sF1", "sF2", "sF3", "sB1", "sB2", "sB3"),
    "praat": ("pF1", "pF2", "pF3", "pB1", "pB2", "pB3"),
    "other": ("oF1", "oF2", "oF3", "oB1", "oB2", "oB3"),
}


def parse_f0(matdata: dict, f0_algorithm: str):
    """[F0] = func_parseF0(matdata, F0algorithm)。

    Parameters
    ----------
    matdata : dict
        已算好的引擎列字典（键 = 短列名，值 = 向量或 None）。
    f0_algorithm : str
        ``"praat" | "snack" | "straight" | "shr" | "other"``（其它值 → 空）。

    Returns
    -------
    np.ndarray | None
        指定引擎的 F0 向量；**引擎列不存在（或值为 None）→ None**（蓝本 ``F0 = []``）。
        不做任何回退。
    """
    field = _F0_FIELD.get(f0_algorithm)
    if field is None:
        return None                      # 蓝本 otherwise → F0 = []
    vec = matdata.get(field)
    if vec is None:
        return None                      # 蓝本 isfield 失败 → F0 = []
    arr = np.asarray(vec, dtype=float)
    return arr if arr.size else None


def parse_fmt(matdata: dict, fmt_algorithm: str):
    """[F1, F2, F3, B1, B2, B3] = func_parseFMT(matdata, FMTalgorithm)。

    返回 6 元组；**指定的引擎列不存在 → 全部 None**（蓝本 ``F1 = []`` 等）。
    不做回退。``straight`` 不在 FMT 合法取值内（STRAIGHT 不产共振峰）→ 全 None。
    """
    fields = _FMT_FIELDS.get(fmt_algorithm)
    if fields is None:
        return (None,) * 6               # 蓝本 otherwise → 全 []
    out = []
    for name in fields:
        vec = matdata.get(name)
        if vec is None:
            out.append(None)             # 蓝本 isfield 失败 → 该列 []
            continue
        arr = np.asarray(vec, dtype=float)
        out.append(arr if arr.size else None)
    return tuple(out)


def parse_f0_all_missing(matdata: dict, f0_algorithm: str) -> bool:
    """便捷判定：指定 F0 引擎列是否缺失（下游据此把该组列整体置 None）。"""
    return parse_f0(matdata, f0_algorithm) is None


def parse_fmt_all_missing(matdata: dict, fmt_algorithm: str) -> bool:
    """便捷判定：指定 FMT 引擎的 F1 是否缺失（蓝本只查 F1/F2/F3 三字段）。"""
    f1, _f2, _f3, _b1, _b2, _b3 = parse_fmt(matdata, fmt_algorithm)
    return f1 is None
