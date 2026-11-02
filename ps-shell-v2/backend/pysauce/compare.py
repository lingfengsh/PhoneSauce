# -*- coding: utf-8 -*-
"""双跑对比（V2-F4）—— 1.2 Praat 脚本链产出 vs 2.0 pysauce 产出的并排差异表。

⚠️ **定位澄清（必读，防误用）**
  本工具**不是**"2.0 正确性验证器"。1.2 走 Praat 脚本、2.0 走 VoiceSauce 算法，
  两者**真正等价仅约 3 项**（前期调研结论）。因此：
    · 差异表是**预期差异的呈现**，不是 bug 清单；
    · 用户真正用途 = **横向比较不同引擎/算法口径**（Praat vs Snack vs VS 算法），
      据此选择研究口径；
    · 验收**不得**以"差异小"为通过标准，应检查"差异是否符合已知算法特性"。

数据来源：两份 out.tsv（1.2 引擎产出 / pysauce 产出），列名可能不同（见 `COLUMN_MAP`）。
对齐口径：按 `file` + 时间轴最近邻帧配对（容差 2 ms）。

**禁改**：本模块只读 tsv 做纯函数计算，不碰任何引擎执行路径。

合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import csv
import os

import numpy as np

# ── 1.2 列名 → 2.0 列名映射 ───────────────────────────────────────────────
#
# 来源：1.2 列名 = `scripts/initiateTable.praat` 的 firstLine$ 拼接；
#       2.0 列名 = `backend/pysauce/output_cols.py` OUTPUT_COLS（VS 原生短名）。
#
# 分三类：
#   · 同名（语义一致，直接对比）：H1c/H2c/…/soe 等大多数
#   · 异名（语义一致，需映射）：f0→pF0、F1..3→pF1..3、B1..3→pB1..3、
#       intensity→Energy、H4-2Ku→H42Ku、t→time
#   · 无对应（语义不同或对方独有）→ 进 notes，不参与数值对比：
#       CPPS（1.2 平滑倒谱；2.0 归入 CPP 家族，无独立列）
#       HNR38（1.2 独有 3800Hz 截止；2.0 只有 HNR05/15/25/35）
COLUMN_MAP_12_TO_20 = {
    # 异名
    "f0": "pF0",
    "F1": "pF1", "F2": "pF2", "F3": "pF3",
    "B1": "pB1", "B2": "pB2", "B3": "pB3",
    "intensity": "Energy",
    "H4-2Ku": "H42Ku",
    "t": "time",
    # 同名（列出以便自检映射完整性；值=自身）
    "H1c": "H1c", "H2c": "H2c", "H4c": "H4c",
    "A1c": "A1c", "A2c": "A2c", "A3c": "A3c",
    "H2Ku": "H2Ku", "H5Ku": "H5Ku",
    "H1u": "H1u", "H2u": "H2u", "H4u": "H4u",
    "A1u": "A1u", "A2u": "A2u", "A3u": "A3u",
    "H1H2c": "H1H2c", "H2H4c": "H2H4c", "H1A1c": "H1A1c",
    "H1A2c": "H1A2c", "H1A3c": "H1A3c", "H2KH5Ku": "H2KH5Ku",
    "H1H2u": "H1H2u", "H2H4u": "H2H4u", "H1A1u": "H1A1u",
    "H1A2u": "H1A2u", "H1A3u": "H1A3u",
    "CPP": "CPP",
    "HNR05": "HNR05", "HNR15": "HNR15", "HNR25": "HNR25", "HNR35": "HNR35",
    "soe": "soe",
}

# 1.2 独有 / 语义不同 → 不对比，进 notes
_12_ONLY = {"CPPS": "1.2 平滑倒谱（M&W 2015）；2.0 无独立列（并入 CPP 家族）",
            "HNR38": "1.2 独有 3800Hz 截止；2.0 只有 HNR05/15/25/35"}


def _read_tsv(path):
    """读 out.tsv → (columns, rows)；rows = [ {col: float|None|str}, … ]。

    · 首列常为 `file`（1.2）/ 无（2.0）；`label`/`intervaldID` 为字符串列 → 原样保留字符串；
    · 数值列：`--undefined--`/空 → None；无法转 float 的也留字符串（避免丢 key）。
    """
    with open(path, "r", encoding="utf-8", newline="") as f:
        rd = csv.reader(f, delimiter="\t")
        header = next(rd, None)
        if not header:
            return [], []
        cols = [c.strip().lstrip("\ufeff") for c in header]
        str_cols = {"file", "label", "intervaldID", "intervalID", "name"}
        rows = []
        for parts in rd:
            if not parts or all(p.strip() == "" for p in parts):
                continue
            rec = {}
            for i, c in enumerate(cols):
                if i >= len(parts):
                    rec[c] = None
                    continue
                v = parts[i].strip()
                if v in ("", "--undefined--"):
                    rec[c] = None
                elif c in str_cols:
                    rec[c] = v
                else:
                    try:
                        rec[c] = float(v)
                    except ValueError:
                        rec[c] = v        # 非数值（含文件名落到数值列）→ 保留字符串
            rows.append(rec)
    return cols, rows


def _pick_keys(cols):
    """从列名里挑出「文件列」与「时间列」名（两版命名不同：file/t、time）。"""
    fcol = "file" if "file" in cols else None
    tcol = "time" if "time" in cols else ("t" if "t" in cols else None)
    return fcol, tcol


def _align_rows(rows_a, cols_a, rows_b, cols_b, tol=0.002):
    """按 (file, time) 最近邻配对（容差 tol 秒）。

    返回 [(key, rec_a, rec_b), …]，key=(file, time_b)。未配上的不进结果。
    """
    fa, ta = _pick_keys(cols_a)
    fb, tb = _pick_keys(cols_b)
    if ta is None or tb is None:
        return []
    # 建 B 的 (file → [(t, rec)]) 索引
    b_idx = {}
    for r in rows_b:
        key = (r.get(fb) if fb else "") or ""
        b_idx.setdefault(key, []).append((r.get(tb), r))
    for k in b_idx:
        b_idx[k].sort(key=lambda x: (x[0] is None, x[0]))
    pairs = []
    for ra in rows_a:
        key = (ra.get(fa) if fa else "") or ""
        ta_v = ra.get(ta)
        cand = b_idx.get(key)
        if not cand or ta_v is None:
            continue
        # 最近邻时间帧
        best = None
        best_d = None
        for tv, rb in cand:
            if tv is None:
                continue
            d = abs(tv - ta_v)
            if best_d is None or d < best_d:
                best_d, best = d, rb
        if best is not None and best_d is not None and best_d <= tol:
            pairs.append(((key, ta_v), ra, best))
    return pairs


def compare_files(praat_tsv, pysauce_tsv, tol=1e-6):
    """读两份 out.tsv（1.2 / pysauce），按 file+时间轴对齐，逐列出差异统计。

    返回 ``{"per_column": [{col, col12, n_overlap, mean_diff, max_abs_diff, corr}, …],
             "files": [...], "notes": [...], "pair_ratio": float}``。

    · ``col`` = 2.0 列名；``col12`` = 对应 1.2 列名（便于回查）；
    · ``mean_diff`` = mean(2.0 - 1.2)；``max_abs_diff`` = max|2.0-1.2|；
    · ``corr`` = 皮尔逊相关系数（样本 <2 或零方差 → None）；
    · 对不上的列（1.2 独有 / 语义不同）→ ``notes``；
    · 配对率 = 实际配对数 / 1.2 侧帧数；< 0.5 记 notes。
    """
    cols_a, rows_a = _read_tsv(praat_tsv)
    cols_b, rows_b = _read_tsv(pysauce_tsv)
    notes = []
    fa, ta = _pick_keys(cols_a)
    fb, tb = _pick_keys(cols_b)
    if ta is None or tb is None:
        notes.append("时间列缺失：1.2=%r / pysauce=%r，无法按帧对齐" % (ta, tb))

    pairs = _align_rows(rows_a, cols_a, rows_b, cols_b, tol=0.002) if ta and tb else []
    pair_ratio = (len(pairs) / len(rows_a)) if rows_a else 0.0
    if rows_a and pair_ratio < 0.5:
        notes.append("配对率偏低（%.0f%%）：两版帧网格差异较大，差异统计仅供参考"
                     % (pair_ratio * 100.0))

    # ── 逐列配对 ──────────────────────────────────────────────────────────
    # 两轮：
    #   ① 同名直配（两版列名相同的列，如 CPP/HNR05/H1c…；也覆盖"两文件同构"的测试场景）；
    #   ② 异名映射（f0→pF0、F1→pF1、intensity→Energy…）补配剩余列。
    per_column = []
    a_cols_set = set(cols_a)
    b_cols_set = set(cols_b)
    _skip = {"t", "time", "file", "label", "intervaldID"}

    def _stat(c20, c12):
        va, vb = [], []
        for _key, ra, rb in pairs:
            x, y = ra.get(c12), rb.get(c20)
            if x is not None and y is not None:
                va.append(x)
                vb.append(y)
        n = len(va)
        if n == 0:
            return {"col": c20, "col12": c12, "n_overlap": 0,
                    "mean_diff": None, "max_abs_diff": None, "corr": None}
        A = np.asarray(va, dtype=float)
        B = np.asarray(vb, dtype=float)
        diff = B - A                       # 2.0(第二参数) - 1.2(第一参数)
        corr = None
        if n >= 2 and A.std() > 0 and B.std() > 0:
            c = float(np.corrcoef(A, B)[0, 1])
            corr = c if not np.isnan(c) else None
        return {"col": c20, "col12": c12, "n_overlap": n,
                "mean_diff": float(np.mean(diff)),
                "max_abs_diff": float(np.max(np.abs(diff))), "corr": corr}

    # ① 同名直配
    done_pairs = set()
    for c in cols_a:
        if c in _skip or c not in b_cols_set:
            continue
        per_column.append(_stat(c, c))
        done_pairs.add(c)
    # ② 异名映射补配
    for c12, c20 in COLUMN_MAP_12_TO_20.items():
        if c12 in _skip or c12 in done_pairs:
            continue
        if c12 not in a_cols_set:
            continue                      # 1.2 本次没算这列
        if c20 not in b_cols_set:
            notes.append("1.2 有列 %s（→2.0 %s）但 pysauce 输出无此列" % (c12, c20))
            continue
        per_column.append(_stat(c20, c12))
        done_pairs.add(c12)

    # 1.2 侧有但两边都对不上的列 → note（如测试场景里 a 有 Energy、b 只有 CPP）
    for c12 in cols_a:
        if c12 in _skip or c12 in done_pairs:
            continue
        notes.append("1.2 有列 %s 但 pysauce 输出无对应列（无法对比）" % c12)
        done_pairs.add(c12)

    # 2.0 侧有但 1.2 侧无对应（如 sF0/strF0/oF0 等非 Praat 引擎列）
    for c20 in cols_b:
        if c20 in _skip or c20 in a_cols_set:
            continue
        if c20 in COLUMN_MAP_12_TO_20:
            continue                      # 已是 1.2 列名（b 侧复用 1.2 命名时）
        notes.append("pysauce 独有列 %s（1.2 无对应，仅并列展示）" % c20)

    # 1.2 独有（显式语义不同）
    for c12, why in _12_ONLY.items():
        if c12 in a_cols_set:
            notes.append("1.2 独有列 %s：%s" % (c12, why))

    files = sorted({k[0] for k, _a, _b in pairs})
    return {"per_column": per_column, "files": files,
            "notes": notes, "pair_ratio": pair_ratio}


def write_compare_csv(path, compare, praat_tsv, pysauce_tsv):
    """把对比结果写成 CSV（每列一行 + 顶部两份 tsv 的路径信息）。

    列：2.0列名, 1.2列名, 重叠帧数, 平均差(1.2-2.0), 最大绝对差, 相关系数
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 1.2 结果", praat_tsv])
        w.writerow(["# 2.0 结果", pysauce_tsv])
        w.writerow(["# 配对率", "%.3f" % compare.get("pair_ratio", 0.0)])
        for n in compare.get("notes", []):
            w.writerow(["# 注", n])
        w.writerow([])
        w.writerow(["2.0列名", "1.2列名", "重叠帧数", "平均差(2.0-1.2)", "最大绝对差", "相关系数"])
        for c in compare.get("per_column", []):
            w.writerow([
                c.get("col"), c.get("col12"), c.get("n_overlap"),
                "" if c.get("mean_diff") is None else "%.6f" % c["mean_diff"],
                "" if c.get("max_abs_diff") is None else "%.6f" % c["max_abs_diff"],
                "" if c.get("corr") is None else "%.6f" % c["corr"],
            ])
    return path
