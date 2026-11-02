# -*- coding: utf-8 -*-
"""第四步 · 导出时间序列。

把批量运行产生的数据整理成可交付的逐点数据。**两个数据源**：

  1. 汇总表（第三步 out.tsv，逐帧长表）：f0、F1–F3、B1–B3、谐波幅度/斜率
     （校正与未校正）、HNR05–35、CPP、CPPS、SHR、intensity、soe
  2. 逐帧对象文件（wav 同目录 <主名>.Pitch / .Formant）：F0、F1–F5、B1–B5

为什么是两源：F4/F5/B4/B5 只存在于 .Formant 对象（上游 initiateTable 只写
F1–F3/B1–B3），而谐波/噪声类只有汇总表有。用户勾的每一列在下面 COLUMNS 里
声明自己的来源（pitch / formant / tsv），后端按源取数、按用户勾选顺序拼列。
（2026-09-26 用户拍板：导出页按「基频/共振峰 | 谐波差 | 噪音水平 | 能量与激励 |
谐波振幅 | 共振峰带宽 | 谐波振幅(未校) | 谐波差(未校)」八组列全部参数。）

三种重采样方式（与「文件布局」正交，用户各选一种）：
  - raw     ：逐帧原始数据（Praat 的帧网格，dx≈0.005s），不重采样
  - smooth  ：先对每条轨道做一个小窗平滑（只在浊音段内，不跨越静音缝），
             再等间隔降采样到「每文件 N 点」
  - interval：按固定时间间隔（如 10ms）等间隔线性插值取点

四种文件布局（2026-09-26 拍板：①保留 + ②③⑤新增；④每音频×每参数不做，
对象文件本身就是这个形态且可从①②随时切出）：
  - single   ：单文件长表 CSV——所有音频顺序堆叠（file, time_s, 参数…），机器最好读
  - per_audio：每音频一个文件——每个音频一张宽表（time_s × 参数），
              写到 <输出目录>/逐音频序列/
  - per_param：每参数一个文件——每个参数一个跨音频长表（file, time_s, 值），
              写到 <输出目录>/分参数序列/
  - xlsx     ：Excel 工作簿——每个参数一页（file × time 长表）+「说明」页。
              openpyxl 懒加载：没装则明确报错并给安装提示，绝不静默失败。

所有 CSV 均为 UTF-8 带 BOM（Excel 双击可开）。数值统一保留 2 位小数、
整数值不带 .0 尾巴；对象里没有的参数（如 3 阶 Formant 的 F4/F5）写空而不是 0。
"""
import os
import re
import bisect
import csv
import json
import datetime
from math import isfinite

from . import praat_objects, review_export, results
from . import working_dir


# ------------------------------------------------------------------ 列注册表
# 每一列 = {"source": ..., "label": ..., "tsv": 汇总表列名（source="tsv"）}
# source="tsv" 的列在跑批量时写进了汇总表（第三步结果文件），可能不在同一个输出目录，
# 所以导出时按「输出目录 / 声音目录 / 设置里上次用过的输出目录」依次找。
SOURCE_PITCH = "pitch"       # <主名>.Pitch 的 candidates[1]
SOURCE_FORMANT = "formant"   # <主名>.Formant 的 F1–F5 / B1–B5
SOURCE_TSV = "tsv"           # 汇总表 out.tsv 的列

_COL = {
    "F0":  (SOURCE_PITCH,  "F0（基频）"),
    "F1":  (SOURCE_FORMANT, "F1（第一共振峰）"),
    "F2":  (SOURCE_FORMANT, "F2（第二共振峰）"),
    "F3":  (SOURCE_FORMANT, "F3（第三共振峰）"),
    "F4":  (SOURCE_FORMANT, "F4（第四共振峰）"),
    "F5":  (SOURCE_FORMANT, "F5（第五共振峰）"),
    "B1":  (SOURCE_FORMANT, "B1（第一共振峰带宽）"),
    "B2":  (SOURCE_FORMANT, "B2（第二共振峰带宽）"),
    "B3":  (SOURCE_FORMANT, "B3（第三共振峰带宽）"),
    "B4":  (SOURCE_FORMANT, "B4（第四共振峰带宽）"),
    "B5":  (SOURCE_FORMANT, "B5（第五共振峰带宽）"),
    # 谐波差（已校正）
    "H1H2c":  (SOURCE_TSV, "H1–H2（已校正）"),
    "H2H4c":  (SOURCE_TSV, "H2–H4（已校正）"),
    "H1A1c":  (SOURCE_TSV, "H1–A1（已校正）"),
    "H1A2c":  (SOURCE_TSV, "H1–A2（已校正）"),
    "H1A3c":  (SOURCE_TSV, "H1–A3（已校正）"),
    "H2KH5Ku": (SOURCE_TSV, "H2K–H5K（未校正，K 谐波无校正版）"),
    "H4-2Ku":  (SOURCE_TSV, "H4–2K（未校正，H4 与最接近 2 kHz 的谐波之差）"),
    # 噪音水平
    "HNR05":  (SOURCE_TSV, "HNR 0.5 kHz"),
    "HNR15":  (SOURCE_TSV, "HNR 1.5 kHz"),
    "HNR25":  (SOURCE_TSV, "HNR 2.5 kHz"),
    "HNR35":  (SOURCE_TSV, "HNR 3.5 kHz"),
    "HNR38":  (SOURCE_TSV, "HNR 3.8 kHz"),
    "CPP":    (SOURCE_TSV, "CPP（倒谱峰值突显）"),
    "CPPS":   (SOURCE_TSV, "CPPS（平滑倒谱峰值突显）"),
    "SHR":    (SOURCE_TSV, "SHR（次谐波谐波比）"),
    # 能量与激励
    "intensity": (SOURCE_TSV, "强度（RMS）"),
    "soe":       (SOURCE_TSV, "SoE（激励强度）"),
    # 谐波振幅（已校正）
    "H1c": (SOURCE_TSV, "H1（已校正）"),
    "H2c": (SOURCE_TSV, "H2（已校正）"),
    "H4c": (SOURCE_TSV, "H4（已校正）"),
    "A1c": (SOURCE_TSV, "A1＝最接近 F1 的谐波（已校正）"),
    "A2c": (SOURCE_TSV, "A2＝最接近 F2 的谐波（已校正）"),
    "A3c": (SOURCE_TSV, "A3＝最接近 F3 的谐波（已校正）"),
    "H2Ku": (SOURCE_TSV, "H2K＝最接近 2 kHz 的谐波（无校正版）"),
    "H5Ku": (SOURCE_TSV, "H5K＝最接近 5 kHz 的谐波（无校正版）"),
    # 谐波振幅（未校正）
    "H1u": (SOURCE_TSV, "H1（未校正）"),
    "H2u": (SOURCE_TSV, "H2（未校正）"),
    "H4u": (SOURCE_TSV, "H4（未校正）"),
    "A1u": (SOURCE_TSV, "A1（未校正）"),
    "A2u": (SOURCE_TSV, "A2（未校正）"),
    "A3u": (SOURCE_TSV, "A3（未校正）"),
    # 谐波差（未校正）
    "H1H2u": (SOURCE_TSV, "H1–H2（未校正）"),
    "H2H4u": (SOURCE_TSV, "H2–H4（未校正）"),
    "H1A1u": (SOURCE_TSV, "H1–A1（未校正）"),
    "H1A2u": (SOURCE_TSV, "H1–A2（未校正）"),
    "H1A3u": (SOURCE_TSV, "H1–A3（未校正）"),
}

# 八组展示顺序（前端按这个顺序铺列；后端只用它排出与前端一致的列说明顺序）
GROUPS = [
    ("pitch_formant", "基频/共振峰", ["F0", "F1", "F2", "F3", "F4", "F5"]),
    ("slope",         "谐波差（已校正）", ["H1H2c", "H2H4c", "H1A1c", "H1A2c", "H1A3c", "H2KH5Ku", "H4-2Ku"]),
    ("noise",         "噪音水平", ["HNR05", "HNR15", "HNR25", "HNR35", "HNR38", "CPP", "CPPS", "SHR"]),
    ("energy",        "能量与激励", ["intensity", "soe"]),
    ("harmonic",      "谐波振幅（已校正）", ["H1c", "H2c", "H4c", "A1c", "A2c", "A3c", "H2Ku", "H5Ku"]),
    ("bandwidth",     "共振峰带宽", ["B1", "B2", "B3", "B4", "B5"]),
    ("harmonic_u",    "谐波振幅（未校正）", ["H1u", "H2u", "H4u", "A1u", "A2u", "A3u"]),
    ("slope_u",       "谐波差（未校正）", ["H1H2u", "H2H4u", "H1A1u", "H1A2u", "H1A3u"]),
]

# 全部可导出的列（按展示顺序铺平）。bootstrap 下发这个列表，前端不硬编码。
COLUMNS = [c for _k, _lb, cols in GROUPS for c in cols]
# 兼容旧调用方：PARAMS 仍是对象通道那 11 列（旧名保留，勿再扩展）
PARAMS = ["F0", "F1", "F2", "F3", "F4", "F5", "B1", "B2", "B3", "B4", "B5"]

_PITCH_COLS = {"F0"}
_FORMANT_COLS = {"F1", "F2", "F3", "F4", "F5", "B1", "B2", "B3", "B4", "B5"}
# 汇总表列名 → 导出列名（同名的不必写；f0 是小写）
_TSV_NAME = {"F0": "f0"}
# 同一参数在不同版本汇总表里的别名（按顺序取第一个存在的列）：
#   intensity —— 1.2 表列名 intensity，pysauce 沿用 VS 原名 Energy
#   H4-2Ku    —— pysauce 短名 H42Ku（VS 显示名 H4*-2K* 无连字符）
_TSV_ALIASES = {
    "intensity": ("Energy",),
    "H4-2Ku": ("H42Ku",),
}


def _tsv_col_index(idx, col):
    """导出列 → 汇总表列下标（容忍两版列名差异）；没有该列返回 None。"""
    for nm in (_TSV_NAME.get(col, col),) + tuple(_TSV_ALIASES.get(col, ())):
        i = idx.get(nm)
        if i is not None:
            return i
    return None

LAYOUTS = ("single", "per_audio", "per_param", "xlsx")
# 「每音频一个文件」「每参数一个文件」的默认子目录名（前端也按这个名字拼路径）
PER_AUDIO_DIR = "逐音频序列"
PER_PARAM_DIR = "分参数序列"

# TextGrid 过滤默认参数（2026-09-27 用户拍板：默认开启，空白/匹配跳过正则的段不导出）
TG_FILTER_DEFAULT = True
TG_SKIP_LABELS_DEFAULT = "sil"
# 标注段边界容差（秒）：帧网格与 TG 边界通常差不到半帧（dx≈0.005s），
# 容差取小半帧，避免边界帧因浮点误差被误剔。
TG_EDGE_TOL = 0.002


def _tg_keep_intervals(tg_path, skip_re=None):
    """读 TextGrid → 保留段 [(t0, t1), …]。保留规则：标签非空白，且
    不匹配跳过正则（skip_re=None 或匹配失败时只剔空白段）。
    找不到/读不了 TG 返回 None（调用方回退为不过滤）。"""
    if not tg_path or not os.path.isfile(tg_path):
        return None
    from .review_grid import _read_tg_intervals
    report = {"loaded": 0, "missing": [], "error": []}
    ivs = _read_tg_intervals(tg_path, os.path.basename(tg_path), report)
    if report["error"]:
        return None
    spans = []
    for iv in ivs:
        lab = (iv.get("label") or "").strip()
        if not lab:
            continue
        if skip_re is not None and skip_re.search(lab):
            continue
        spans.append((iv["t0"], iv["t1"]))
    return spans or None


def _in_spans(t, spans):
    """t 是否落在任一保留段内（带边界容差）。"""
    for t0, t1 in spans:
        if t >= t0 - TG_EDGE_TOL and t <= t1 + TG_EDGE_TOL:
            return True
    return False


try:  # Excel 布局的可选依赖：懒加载，没装不影响其它布局
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def _fmt(v):
    """统一数值格式：None→""（空单元格），整数不带 .0（2500.0→2500），其余保留 2 位。"""
    if v is None:
        return ""
    v = round(v, 2)
    return int(v) if v == int(v) else v


def col_source(col):
    return _COL.get(col, (SOURCE_TSV, ""))[0]


# ── 运行产物定位（2026-10-27 用户实测 bug：VS 用默认 STRAIGHT/Snack 跑完批量，
#    「参数展示」却报「该目录还没有任何测量结果」）──────────────────────────────
#    两个来源都必须按「本次实际算的是哪套引擎」去找，不能写死 Praat：
#      1. 逐帧对象：Praat → .Pitch/.Formant；Snack → .sF0/.sFormant；
#         STRAIGHT → .strF0。旧实现只认 .Pitch/.Formant，非 Praat 引擎全部漏掉。
#      2. 汇总表：pysauce 按基准加前缀 <f0>_<fmt>_out.tsv（2026-10-27 定案），
#         旧实现只找写死的 out.tsv，认不出带前缀的文件。
#    基准从哪来：调用方显式值 → <输出目录>/_results.json 最新一条（server 写）→
#    文件名前缀 → 空（= 1.2 老结果，按 Praat 处理）。
_RESULT_MARK_NAME = "_results.json"   # 与 server._results_json_path 同名（不反向依赖 server）
_RUN_KEYS = {"f0": ("f0_algorithm", "f0BaseEngine"),
             "fmt": ("fmt_algorithm", "formantBaseEngine")}
_ENGINE_TRY_ORDER = ("praat", "snack", "straight")


def _candidate_dirs(dir_path, values=None):
    """汇总表可能所在的目录（去重、只要存在的）。输出目录 → 声音目录 → 各自 output/。"""
    out = []
    if values:
        for k in ("lastOutputDir", "outputDir", "inputDir"):
            d = (values.get(k) or "").strip()
            if d:
                out.append(d)
                if k == "inputDir":
                    out.append(os.path.join(d, "output"))
    if dir_path:
        out.append(dir_path)
        out.append(os.path.join(dir_path, "output"))
    seen, dirs = set(), []
    for d in out:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d)
            dirs.append(d)
    return dirs


def _looks_like_result(fn):
    low = fn.lower()
    return low.endswith("out.tsv") or low.endswith("_out.tsv")


def _latest_run(dir_path, values=None):
    """最近一次运行的基准引擎 + 汇总表文件名 → {"f0", "fmt", "out"}（缺项为空串）。"""
    run = {"f0": "", "fmt": "", "out": ""}
    if values:
        for k, keys in _RUN_KEYS.items():
            for kk in keys:
                v = (values.get(kk) or "").strip().lower()
                if v:
                    run[k] = v
                    break
    if run["f0"] and run["fmt"]:
        return run
    dirs = _candidate_dirs(dir_path, values)
    # 1) server 写的结果清单：明确记着基准与输出文件名（最可靠）
    for d in dirs:
        p = os.path.join(d, _RESULT_MARK_NAME)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except Exception:
            continue
        runs = [r for r in (data.get("runs") or []) if isinstance(r, dict)]
        if not runs:
            continue
        best = max(runs, key=lambda r: str(r.get("ts") or ""))
        run["f0"] = run["f0"] or (best.get("f0_algorithm") or "").strip().lower()
        run["fmt"] = run["fmt"] or (best.get("fmt_algorithm") or "").strip().lower()
        run["out"] = (best.get("out") or "").strip()
        break
    if run["f0"] and run["fmt"]:
        return run
    # 2) 文件名前缀兜底：<f0>_<fmt>_out.tsv
    f0_ok = set((review_export.ENGINE_OBJECT_EXT.get("f0") or {}).keys())
    fmt_ok = set((review_export.ENGINE_OBJECT_EXT.get("formant") or {}).keys())
    for d in dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for fn in names:
            if not _looks_like_result(fn):
                continue
            stem = fn[:-4]
            parts = stem.split("_")
            if len(parts) >= 3 and parts[-1].lower() == "out" \
                    and parts[0] in f0_ok and parts[1] in fmt_ok:
                run["f0"] = run["f0"] or parts[0]
                run["fmt"] = run["fmt"] or parts[1]
                run["out"] = run["out"] or fn
                return run
    return run


def _find_engine_object(wav_path, dim, run=None):
    """该 wav 在 dim(f0|formant) 上「实际存在」的引擎对象 → (路径, 引擎)。

    优先本次运行的基准引擎；没有基准信息时按 Praat→Snack→STRAIGHT 兜底
    （Praat 最通用，且 1.2 老目录里只有它）。
    """
    run = run or {}
    pref = (run.get("f0" if dim == "f0" else "fmt") or "").strip().lower()
    order = ([pref] if pref else []) + [e for e in _ENGINE_TRY_ORDER if e != pref]
    for e in order:
        p = review_export.engine_object_path(wav_path, dim, e)
        if p and os.path.isfile(p):
            return p, e
    return None, None


def _read_simple_rows(path):
    """读非 Praat 引擎的自有对象格式 → [{t, …}]（键与 praat_objects.read_* 同构）。

    格式见 pysauce/engine.py::_write_simple_object：`# engine=… dim=…` 注释 +
    制表符表头（`time\\tf0` 或 `time\\tF1…[\\tB1…]`），缺值写 `--undefined--`。
    """
    with open(path, "r", encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    data = [ln for ln in lines if not ln.startswith("#")]
    if len(data) < 2:
        return []
    hdr = data[0].split("\t")
    rows = []
    for ln in data[1:]:
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        try:
            t = float(parts[0])
        except (TypeError, ValueError):
            continue
        rec = {"t": t}
        for i, name in enumerate(hdr[1:], start=1):
            if i >= len(parts):
                break
            v = parts[i].strip()
            rec[name] = None if v in ("", "--undefined--") else results._to_float(v)
        rows.append(rec)
    return rows


def _read_pitch_rows(wav_path, run=None):
    """该 wav 的 F0 逐帧行（按运行基准选引擎；读不到返回 []）。"""
    p, engine = _find_engine_object(wav_path, "f0", run)
    if not p:
        return []
    try:
        return praat_objects.read_pitch_text(p) if engine == "praat" else _read_simple_rows(p)
    except Exception:
        return []


def _read_formant_rows(wav_path, run=None):
    """该 wav 的共振峰逐帧行（同上）。"""
    p, engine = _find_engine_object(wav_path, "formant", run)
    if not p:
        return []
    try:
        return praat_objects.read_formant_text(p) if engine == "praat" else _read_simple_rows(p)
    except Exception:
        return []


def find_result_file(dir_path, values=None):
    """定位汇总表（第三步结果文件）的绝对路径。找不到返回 None。

    顺序：`_latest_run` 认定的文件名/基准前缀 → 设置里上次用过的输出目录 →
    声音目录 → 用户设置的输出目录 → 任意 `*out.tsv`（取最新）。
    （0 字节的 out.tsv 视为不存在：Praat 建表后崩掉会留下空文件。）
    """
    run = _latest_run(dir_path, values)
    names = []
    if values:
        nm = (values.get("outputFile") or "").strip()
        if nm:
            names.append(nm)
    base_nm = names[0] if names else "out.tsv"
    # pysauce 的运行结果带基准前缀 <f0>_<fmt>_，先按它精确找
    if run.get("f0") and run.get("fmt"):
        names.append("%s_%s_%s" % (run["f0"], run["fmt"], base_nm))
    if run.get("out"):
        names.append(run["out"])
    names.append("out.tsv")

    seen_name, ordered_names = set(), []
    for nm in names:
        if nm and nm not in seen_name:
            seen_name.add(nm)
            ordered_names.append(nm)

    dirs = _candidate_dirs(dir_path, values)
    for d in dirs:
        for nm in ordered_names:
            p = os.path.join(d, nm)
            try:
                if os.path.isfile(p) and os.path.getsize(p) > 0:
                    return p
            except OSError:
                continue
    # 兜底：任何 *out.tsv（自定义文件名/历史遗留），取最新修改的那个
    best, best_mtime = None, -1.0
    for d in dirs:
        try:
            for fn in os.listdir(d):
                if not _looks_like_result(fn):
                    continue
                p = os.path.join(d, fn)
                try:
                    if os.path.getsize(p) <= 0:
                        continue
                    mt = os.path.getmtime(p)
                except OSError:
                    continue
                if mt > best_mtime:
                    best, best_mtime = p, mt
        except OSError:
            continue
    return best



def series_available(dir_path, ext="wav", values=None):
    """扫描目录，返回每个可导出行（COLUMNS）在当前目录里是否已有数据。

    与 grid_page / export_series 同一口径：F0 ← measure/ 下**当前基准引擎**的对象
    （Praat .Pitch / Snack .sF0 / STRAIGHT .strF0）；F1–F5/B1–B5 ← 对应的
    .Formant/.sFormant；谐波差/噪音/能量类 ← 汇总表（含 pysauce 的
    <f0>_<fmt>_out.tsv）的对应列（按 _TSV_NAME 换算，F0 对应 "f0"）。
    返回 {ok, dir, available{col:bool}, tsvPath, hasPitch, hasFormant, warnings}。
    前端据此点亮/灰掉导出复选框——只让「目录里确实测过」的参数可被勾选
    （2026-09-27 用户拍板：VS / 向导两界面数据互通，不以当前会话的
    lastResultPath 为准，而以目录里实际落盘的结果为准）。
    """
    if not dir_path or not os.path.isdir(dir_path):
        return {"ok": False, "error": "目录不存在：%s" % dir_path}
    ext = (ext or "wav").strip().lstrip(".")
    from .review_grid import _list_wavs
    wavs = _list_wavs(dir_path, ext)
    run = _latest_run(dir_path, values)
    has_pitch = False
    has_formant = False
    # 只扫前若干文件即可判断「有没有对象文件」（命中即停）
    for wf in wavs[:500]:
        wav = os.path.join(dir_path, wf)
        if not has_pitch and _find_engine_object(wav, "f0", run)[0]:
            has_pitch = True
        if not has_formant and _find_engine_object(wav, "formant", run)[0]:
            has_formant = True
        if has_pitch and has_formant:
            break

    tsv_path = find_result_file(dir_path, values)
    tsv_idx = {}
    if tsv_path:
        res = results.read_table(tsv_path)
        if res.get("ok"):
            tsv_idx = {h: i for i, h in enumerate(res["columns"])}
    available = {}
    for c in COLUMNS:
        src = col_source(c)
        if src == SOURCE_PITCH:
            available[c] = has_pitch
        elif src == SOURCE_FORMANT:
            available[c] = has_formant
        else:  # SOURCE_TSV
            available[c] = bool(tsv_idx) and (_tsv_col_index(tsv_idx, c) is not None)
    warnings = []
    if not (has_pitch or has_formant or tsv_path):
        warnings.append("该目录还没有任何测量结果（measure/ 下没有引擎对象，"
                        "也没找到汇总表 *out.tsv）。先在「参数提取」跑一次批量运行，或用向导版完成测量。")
    return {"ok": True, "dir": dir_path, "available": available,
            "tsvPath": tsv_path or "", "hasPitch": has_pitch, "hasFormant": has_formant,
            # run 供界面如实显示「当前取的是哪套基准」（F0/FMT 基准 + 汇总表文件名）
            "run": run, "warnings": warnings}


def _smooth(times, values, win=5):
    """对 (t, v) 轨道做小窗移动平均平滑，只在有效值（v 非 None）之间做，
    不跨越静音缝。返回与输入等长的 values（无效点保持 None）。"""
    n = len(times)
    out = [None] * n
    half = max(1, win // 2)
    for i in range(n):
        if values[i] is None:
            continue
        lo = max(0, i - half)
        hi = min(n - 1, i + half)
        vals = [values[j] for j in range(lo, hi + 1) if values[j] is not None]
        if vals:
            out[i] = sum(vals) / len(vals)
    return out


def _resample(times, values, target_times):
    """把 (t, v) 轨道线性插值到 target_times。v 为 None 的点不参加插值；
    target 落在有效段之外（静音缝、首尾之外）记 None。"""
    pts = [(t, v) for t, v in zip(times, values) if v is not None]
    if not pts:
        return [None] * len(target_times)
    ts = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    out = []
    for tt in target_times:
        if tt < ts[0] or tt > ts[-1]:
            out.append(None)
            continue
        i = bisect.bisect_right(ts, tt) - 1
        if i < 0:
            i = 0
        if i >= len(ts) - 1:
            out.append(vs[-1])
            continue
        t0, t1 = ts[i], ts[i + 1]
        if t1 == t0:
            out.append(vs[i])
            continue
        a = (tt - t0) / (t1 - t0)
        out.append(vs[i] + a * (vs[i + 1] - vs[i]))
    return out


def _target_times(method, frame_times, n, interval):
    """根据重采样方式生成目标时间网格（秒）。frame_times 为升序帧时间列表。"""
    if not frame_times:
        return []
    t0, t1 = frame_times[0], frame_times[-1]
    if method == "raw":
        return list(frame_times)
    if method == "smooth":
        n = max(2, int(n or 0) or 100)
        if t1 <= t0:
            return [t0]
        step = (t1 - t0) / (n - 1)
        return [t0 + step * i for i in range(n)]
    # interval
    iv = float(interval or 0) or 0.01
    if iv <= 0:
        iv = 0.01
    if t1 <= t0:
        return [t0]
    return [round(t0 + iv * k, 6) for k in range(int((t1 - t0) / iv) + 1)]


def _track_columns(params):
    """返回 (need_pitch, need_formant, need_tsv)：分别要不要读 .Pitch / .Formant / 汇总表。"""
    need_pitch = any(col_source(c) == SOURCE_PITCH for c in params)
    need_formant = any(col_source(c) == SOURCE_FORMANT for c in params)
    need_tsv = any(col_source(c) == SOURCE_TSV for c in params)
    return need_pitch, need_formant, need_tsv


def _tsv_groups(tsv_path, params):
    """读汇总表 → {主名: {"t": [秒…], "cols": {列: [值…]}}}。

    汇总表是逐帧长表，同一 file 的行可能不连续，这里统一按 file 归组并按 t 排序。
    找不到的列留空列表（该文件这一列全空），与"对象里没有这一阶"同样处理。
    """
    res = results.read_table(tsv_path)
    if not res.get("ok"):
        return {}, res.get("error") or "读取汇总表失败"
    header = res["columns"]
    idx = {h: i for i, h in enumerate(header)}
    if "file" not in idx:
        return {}, "汇总表没有 file 列"
    # 时间列名两版不同：1.2（Praat 表）用 t，pysauce 用 time（另有导出用 time_s）。
    ti = next((idx[k] for k in ("time", "t", "time_s") if k in idx), None)
    groups = {}
    for r in res["rows"]:
        fk = (r[idx["file"]] or "").strip()
        if not fk:
            continue
        g = groups.setdefault(fk, {"raw": []})
        g["raw"].append(r)
    want = [c for c in params if col_source(c) == SOURCE_TSV]
    col_idx = {c: _tsv_col_index(idx, c) for c in want}
    out = {}
    for fk, g in groups.items():
        rows = g["raw"]
        if ti is not None:
            rows.sort(key=lambda r: results._to_float(r[ti]) or 0.0)
        times = []
        for r in rows:
            tv = results._to_float(r[ti]) if ti is not None else None
            times.append(tv if tv is not None else 0.0)
        cols = {}
        for col in want:
            i = col_idx[col]
            cols[col] = ([results._to_float(r[i]) if (i is not None and len(r) > i) else None
                          for r in rows])
        out[fk] = {"t": times, "cols": cols}
    return out, None


def _norm_key(name):
    """文件名的匹配键：去掉目录前缀与扩展名、统一小写与斜杠，用于把汇总表的
    file 列（可能写作 "sub/11.wav" 或 "11.wav"）对到 wav 主名上。"""
    s = str(name or "").strip().replace("\\", "/")
    s = s.split("/")[-1]
    return os.path.splitext(s)[0].strip().lower()


def _collect(dir_path, params, method, n, interval, ext, values=None, log_fn=None,
             tg_filter=TG_FILTER_DEFAULT, skip_labels=TG_SKIP_LABELS_DEFAULT):
    """公共采集核心：逐文件读两个数据源 → 重采样到统一时间网格。

    返回 (items, skipped, tsv_path, tg_missing, tg_filtered)。
    item = {"base": 主名, "targets": [t…], "sampled": {参数: [v…]}}
    （v 为原始浮点或 None，格式化交给写出器）。
    skipped = 两个源都没有数据的 wav 名。遍历用 os.listdir（非递归，与批量口径一致）。
    tg_filter：开启后按 TextGrid 标注段过滤——目标时间点只保留落在「非空白且
    不匹配 skip_labels 正则」的标注段内；没有 TG 的文件不过滤（计入 tgMissing）。
    """
    skip_re = None
    if tg_filter:
        pat = (skip_labels or "").strip()
        if pat:
            try:
                skip_re = re.compile(pat)
            except re.error as e:
                if log_fn:
                    log_fn(f"跳过标记正则无效（{e}），按只剔空白段处理。", "err")
    ext = (ext or "wav").strip().lstrip(".")
    wavs = sorted(f for f in os.listdir(dir_path)
                  if f.lower().endswith("." + ext.lower()))
    need_pitch, need_formant, need_tsv = _track_columns(params)

    run = _latest_run(dir_path, values)
    tsv_path = find_result_file(dir_path, values) if need_tsv else None
    tsv_map, tsv_err = ({}, None)
    if need_tsv:
        if tsv_path:
            tsv_map, tsv_err = _tsv_groups(tsv_path, params)
            if tsv_err and log_fn:
                log_fn(f"汇总表读取失败（谐波/噪声/能量列将留空）：{tsv_err}", "err")
        elif log_fn:
            log_fn("没找到汇总表（*out.tsv，如 straight_snack_out.tsv）：谐波差/噪音水平/能量与激励/谐波振幅类列将留空。"
                   "先在第三步跑一次批量运行，或把第一步的输出目录指到结果所在处。", "err")

    items = []
    skipped = []
    tg_missing = []
    tg_filtered = 0
    for wf in wavs:
        base = os.path.splitext(wf)[0]
        # 对象文件在音频所在目录的 measure/ 子目录里（2026-09-27 方案 A）；
        # 后缀随本次运行的基准引擎（Praat .Pitch / Snack .sF0 / STRAIGHT .strF0）
        full = os.path.join(dir_path, wf)
        pitch_rows = _read_pitch_rows(full, run) if need_pitch else []
        formant_rows = _read_formant_rows(full, run) if need_formant else []
        tsv_g = None
        if need_tsv:
            tsv_g = tsv_map.get(_norm_key(base))
            if tsv_g is None:   # 文件名大小写/前缀不一致时再宽松匹配一次
                for k, v in tsv_map.items():
                    if _norm_key(k) == _norm_key(base):
                        tsv_g = v
                        break

        if not pitch_rows and not formant_rows and not tsv_g:
            skipped.append(wf)
            continue

        # 规范时间网格：三条源的帧网格通常在同一 timeStep 下只差一个很小的
        # x1 偏移，取三者帧时间的并集作为基准，避免某一轨的首/尾帧在另一轨时间轴之外
        # 被插值成 None（raw 模式下表现为前几行 F0 有值、共振峰为空）。
        all_t = set()
        if pitch_rows:
            all_t.update(round(p["t"], 6) for p in pitch_rows)
        if formant_rows:
            all_t.update(round(p["t"], 6) for p in formant_rows)
        if tsv_g:
            all_t.update(round(t, 6) for t in tsv_g["t"])
        frame_times = sorted(all_t)
        if not frame_times:
            skipped.append(wf)
            continue

        # 各轨道的 (t, v) 序列
        src = {}
        if pitch_rows:
            src["F0"] = ([p["t"] for p in pitch_rows],
                         [p["f0"] for p in pitch_rows])
        if formant_rows:
            for col in _FORMANT_COLS:
                if col in params:
                    src[col] = ([p["t"] for p in formant_rows],
                                [p.get(col) for p in formant_rows])
        if tsv_g:
            for col, vals in tsv_g["cols"].items():
                src[col] = (tsv_g["t"], vals)

        # smooth 方式：先对每条轨道做小窗平滑（只处理用户勾选的列）
        if method == "smooth":
            for col in list(src.keys()):
                src[col] = (src[col][0], _smooth(src[col][0], src[col][1], win=5))

        targets = _target_times(method, frame_times, n, interval)

        # TextGrid 过滤：只保留落在保留标注段内的目标时间点（2026-09-27 用户拍板）
        tg_spans = None
        if tg_filter:
            from .review_grid import _find_textgrid
            tg_path = _find_textgrid(full, dir_path)
            tg_spans = _tg_keep_intervals(tg_path, skip_re)
            if tg_spans is None:
                tg_missing.append(wf)
            else:
                before = len(targets)
                targets = [t for t in targets if _in_spans(t, tg_spans)]
                if len(targets) < before:
                    tg_filtered += 1
        if tg_filter and tg_spans is not None and not targets:
            skipped.append(wf)
            continue

        # 把每条轨道重采样到目标网格
        sampled = {}
        for col, (ts, vs) in src.items():
            sampled[col] = _resample(ts, vs, targets)

        items.append({"base": base, "targets": targets, "sampled": sampled})
    return items, skipped, tsv_path, tg_missing, tg_filtered


def export_series(dir_path, params, method="raw", n=100, interval=0.01,
                  ext="wav", out_path=None, layout="single", values=None, log_fn=None,
                  tg_filter=TG_FILTER_DEFAULT, skip_labels=TG_SKIP_LABELS_DEFAULT):
    # 重采样后工作目录自动切到 Resample/（见 working_dir），与第四步读取同源口径。
    dir_path = working_dir.resolve_working_dir(dir_path, ext)

    """导出时间序列。

    dir_path : wav 所在目录（对象文件 .Pitch/.Formant 也在该目录）。
    params   : 要导出的列名列表，取值于 COLUMNS。
    method   : "raw" | "smooth" | "interval"。
    n        : smooth 方式下每文件点数（默认 100）。
    interval : interval 方式下固定间隔（秒，默认 0.01）。
    out_path : 输出路径。single/xlsx 是文件路径；per_audio/per_param 是
               **目标子目录**（内部自动创建）。为空则按布局取默认位置。
    layout   : "single" | "per_audio" | "per_param" | "xlsx"。
    values   : 运行参数（用于定位汇总表：输出目录 / 声音目录）。
    log_fn   : 可选日志回调 log_fn(msg, tag)。
    tg_filter: 开启后按 TextGrid 标注段过滤（默认开）：空白段及匹配 skip_labels
               正则的段不导出；没有 TextGrid 的文件不过滤。
    skip_labels: 跳过段标签的正则（默认 "sil"，匹配即整段不导出）。

    返回 {"ok", "path", "kind", "files", "rows", "skipped", "tsv", "error"}，
    kind="file"（path 是文件）或 "dir"（path 是目录，前端打开目录而非文件）。
    """
    params = [p for p in (params or []) if p in COLUMNS]
    # 去重但保留用户勾选顺序（列顺序即用户看到的勾选顺序）
    seen = set()
    params = [p for p in params if not (p in seen or seen.add(p))]
    if not params:
        return {"ok": False, "error": "没有勾选任何要导出的参数"}
    if not dir_path or not os.path.isdir(dir_path):
        return {"ok": False, "error": "声音目录不存在或未设置"}
    method = method or "raw"
    if method not in ("raw", "smooth", "interval"):
        method = "raw"
    layout = layout or "single"
    if layout not in LAYOUTS:
        layout = "single"

    items, skipped, tsv_path, tg_missing, tg_filtered = _collect(
        dir_path, params, method, n, interval, ext,
        values=values, log_fn=log_fn, tg_filter=tg_filter, skip_labels=skip_labels)
    if not items:
        return {"ok": False, "error": "没有可导出的数据：measure/ 下没有引擎对象，"
                                      "也没找到汇总表（*out.tsv；先批量运行或审核完成）"}

    if layout == "per_audio":
        target_dir = out_path or os.path.join(dir_path, PER_AUDIO_DIR)
        r = _write_per_audio(items, params, target_dir, skipped, method)
    elif layout == "per_param":
        target_dir = out_path or os.path.join(dir_path, PER_PARAM_DIR)
        r = _write_per_param(items, params, target_dir, skipped, method)
    elif layout == "xlsx":
        if not out_path:
            out_path = os.path.join(dir_path, "praatsauce_series.xlsx")
        r = _write_xlsx(items, params, out_path, skipped, method, n, interval, dir_path)
    else:
        # single（默认）：单文件长表
        if not out_path:
            out_path = os.path.join(dir_path, "praatsauce_series.csv")
        out_path = os.path.abspath(out_path)
        rows_written = 0
        with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "time_s"] + params)
            for item in items:
                for i, tt in enumerate(item["targets"]):
                    row = [item["base"], round(tt, 6)]
                    for col in params:
                        row.append(_fmt(item["sampled"].get(col, [None] * len(item["targets"]))[i]))
                    w.writerow(row)
                    rows_written += 1
        r = _result(out_path, "file", len(items), rows_written, skipped, method)
    if r.get("ok"):
        r["tsv"] = tsv_path
        r["tgMissing"] = tg_missing
        r["tgFiltered"] = tg_filtered
    return r


def _result(path, kind, files, rows, skipped, method):
    return {"ok": True, "path": path, "kind": kind, "files": files,
            "rows": rows, "method": method, "skipped": skipped, "error": None}


def _write_per_audio(items, params, target_dir, skipped, method):
    """每音频一个文件：宽表 time_s × 参数。文件名 = <主名>.csv。"""
    target_dir = os.path.abspath(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    rows_written = 0
    for item in items:
        path = os.path.join(target_dir, item["base"] + ".csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time_s"] + params)
            for i, tt in enumerate(item["targets"]):
                row = [round(tt, 6)]
                for col in params:
                    row.append(_fmt(item["sampled"].get(col, [None] * len(item["targets"]))[i]))
                w.writerow(row)
                rows_written += 1
    return _result(target_dir, "dir", len(items), rows_written, skipped, method)


def _write_per_param(items, params, target_dir, skipped, method):
    """每参数一个文件：跨音频长表 file, time_s, <参数>。文件名 = <参数>.csv。"""
    target_dir = os.path.abspath(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    rows_written = 0
    for col in params:
        path = os.path.join(target_dir, col + ".csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "time_s", col])
            for item in items:
                vals = item["sampled"].get(col, [None] * len(item["targets"]))
                for i, tt in enumerate(item["targets"]):
                    w.writerow([item["base"], round(tt, 6), _fmt(vals[i])])
                    rows_written += 1
    return _result(target_dir, "dir", len(params), rows_written, skipped, method)


def _write_xlsx(items, params, out_path, skipped, method, n, interval, dir_path):
    """Excel 工作簿：「说明」页 + 每参数一页（file × time 长表）。

    openpyxl 懒加载——没装时明确报错并提示安装，不静默失败。
    """
    if not HAS_OPENPYXL:
        return {"ok": False, "error": (
            "导出 Excel 需要先安装 openpyxl：命令行运行  pip install openpyxl  （装完重启本程序）。"
            "也可以先用「每音频一个文件 / 每参数一个文件」布局导出 CSV。")}
    out_path = os.path.abspath(out_path)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "说明"
    method_desc = {"raw": "原始数据（逐帧）",
                   "smooth": "平滑后每文件取 %s 点" % (n or 100),
                   "interval": "固定间隔 %s 秒" % (interval or 0.01)}[method]
    for row in (
        ("PhoneSauce 逐点时间序列导出",),
        ("导出时间", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("声音目录", dir_path),
        ("导出方式", method_desc),
        ("列数", len(params)),
        ("音频数", len(items)),
        ("跳过（无数据）", ", ".join(skipped) if skipped else "无"),
        ("",),
        ("每个参数一页：列为 file, time_s, <参数>；空单元格 = 该点无值（静音段或对象里没有该阶）",),
        ("列来源：F0/F1–F5/B1–B5 取自对象文件；谐波、噪声、能量类取自汇总表（out.tsv）",),
    ):
        ws.append(row)
    for row in (("列", "说明", "数据来源"),):
        ws.append(row)
    for col in params:
        _s, label = _COL.get(col, (SOURCE_TSV, col))
        src_name = {SOURCE_PITCH: "对象文件 .Pitch", SOURCE_FORMANT: "对象文件 .Formant",
                    SOURCE_TSV: "汇总表 out.tsv"}[_s]
        ws.append((col, label, src_name))
    rows_written = 0
    for col in params:
        sh = wb.create_sheet(col)
        sh.append(["file", "time_s", col])
        for item in items:
            vals = item["sampled"].get(col, [None] * len(item["targets"]))
            for i, tt in enumerate(item["targets"]):
                v = vals[i]
                sh.append([item["base"], round(tt, 6), None if v is None else _fmt(v)])
                rows_written += 1
    try:
        wb.save(out_path)
    except PermissionError:
        return {"ok": False, "error": "写不进去：%s（文件多半正被 Excel 打开着，关掉再导）" % out_path}
    return _result(out_path, "file", len(items), rows_written, skipped, method)


# ------------------------------------------------------------------ 第四步（新）· 查看测量结果
# 2026-09-26 用户拍板：第三步批量跑完先「看一眼」，再进导出（原第四步顺延为第五步）。
# 前端用 4×4 格子（复用九宫格格局、内嵌在页面里，不开独立窗口），顶部参数组仿导出页
# 的八组下拉菜单；点格子打开文件详情窗（review_grid 那套）。本函数按页返回每文件
# 所选参数的逐点曲线，**纯读文件、绝不调 Praat**：
#   - F0        ← wav 旁 <主名>.Pitch（与导出/批量同一位置；没有则该列空）
#   - F1–F5/B1–B5 ← wav 旁 <主名>.Formant
#   - 其余列    ← 第三步汇总表 out.tsv（find_result_file 定位；没找到则告警、列为空）
# 曲线里的 None = 该帧无值（静音段/丢帧），前端据此断线——绝不把静音缝连成直线。

GRID_MAX_POINTS = 260   # 每条曲线最多保留的点数（16 格 × 8 参数 × 260 点也不至于撑爆 JSON）


def grid_page(dir_path, page=0, size=16, params=None, ext="wav", values=None,
              max_points=GRID_MAX_POINTS):
    """按页返回每文件所选参数的逐点曲线（第四步「查看测量结果」的数据源）。

    文件清单与九宫格同一口径：递归列出目录下全部 wav、按相对路径排序
    （review_grid._list_wavs），并给每个文件带上全局序号 index——前端点格子时
    用 index 去 /api/review/grid 按 size=1 精确取该文件，复用现有文件详情窗，
    不新增详情链路。汇总表按主名宽松匹配（与 _collect 同一规则）；同名文件在
    多个子目录（双副本）会匹配到同一组汇总数据，与导出侧口径一致。

    返回 {ok, dir, page, size, total, pages, files, params, tsvPath, warnings}，
    files[i] = {name, path, index, duration, intervals, tgPath,
                series: {参数: [[t, v|null], …]}}。
    """
    if not dir_path or not os.path.isdir(dir_path):
        return {"ok": False, "error": "目录不存在：%s" % dir_path}
    # 重采样后工作目录自动切到 Resample/（见 working_dir）：第四步只应读工作副本，
    # 否则会同时拉到原始目录(samples/1)与 Resample/ 两套同名文件 → 互相覆盖 / 空白。
    dir_path = working_dir.resolve_working_dir(dir_path, "wav")
    want = [p for p in (params or []) if p in _COL]
    # 去重、保留用户选择顺序（前端下拉菜单的先后即叠加顺序）
    seen = set()
    want = [p for p in want if not (p in seen or seen.add(p))]

    from .review_grid import _list_wavs, _downsample, _find_textgrid, _read_tg_intervals
    from . import audio
    all_wavs = _list_wavs(dir_path, ext)
    total = len(all_wavs)
    size = max(1, int(size or 16))
    pages = (total + size - 1) // size
    page = max(0, min(int(page or 0), max(0, pages - 1)))
    start = page * size
    page_names = all_wavs[start:start + size]

    want_pitch = [c for c in want if c in _PITCH_COLS]
    want_formant = [c for c in want if c in _FORMANT_COLS]
    want_tsv = [c for c in want if col_source(c) == SOURCE_TSV]

    run = _latest_run(dir_path, values)
    tsv_path = find_result_file(dir_path, values) if want_tsv else None
    tsv_map, tsv_err = ({}, None)
    if want_tsv:
        if tsv_path:
            tsv_map, tsv_err = _tsv_groups(tsv_path, want_tsv)
        # 找不到汇总表不算失败：对象文件那几列照常出图，tsv 列为空 + 告警说明

    files = []
    skipped = 0
    for gi, name in enumerate(page_names, start=start):
        wav = os.path.join(dir_path, name)
        base = os.path.splitext(os.path.basename(name))[0]
        series = {}
        if want_pitch:
            rows = _read_pitch_rows(wav, run)
            if rows:
                series["F0"] = [[p["t"], (p["f0"] if p.get("f0") and p["f0"] > 0 else None)]
                                for p in rows]
        if want_formant:
            rows = _read_formant_rows(wav, run)
            if rows:
                for c in want_formant:
                    series[c] = [[p["t"], p.get(c)] for p in rows]
        if want_tsv:
            g = tsv_map.get(_norm_key(base))
            if g is None:   # 大小写/前缀不一致时宽松匹配一次（与 _collect 同）
                for k, v in tsv_map.items():
                    if _norm_key(k) == _norm_key(base):
                        g = v
                        break
            for c in want_tsv:
                if g is None:
                    series[c] = []
                    continue
                vals = g["cols"].get(c) or []
                # 列不在汇总表（或整列全空）= 这批根本没测这个参数 → 空数组，
                # 前端据此灰掉。此前 [None]*len 兜底产出非空数组，前端误判「测过」
                # （2026-09-27 用户实测抓到：没测参数不灰、勾上只画全 null 断线）
                if not vals or all(v is None for v in vals):
                    series[c] = []
                else:
                    series[c] = [[t, v] for t, v in zip(g["t"], vals)]
        # 缺声明：用户选了但完全没数据源的列，给空列表（前端显示「无数据」）
        for c in want:
            series.setdefault(c, [])
        # 降采样（按条降，None 保留 → 静音缝的断线信息不丢）
        for c in list(series):
            series[c] = _downsample(series[c], max_points)
        if not any(series.get(c) for c in want):
            skipped += 1
        # TextGrid 音节段（九宫格同款：浅蓝底 + 边界线，帮助对照测量段）；缺/坏不影响曲线
        tg_report = {"loaded": 0, "missing": [], "error": []}
        tg_path = _find_textgrid(wav, dir_path)
        intervals = _read_tg_intervals(tg_path, name, tg_report)
        dur = 0.0
        try:
            dur = audio._wav_info(wav)[0] or 0.0
        except Exception:
            dur = 0.0   # wav 读不动不拦整页：曲线照常出（时长按数据自适应）
        files.append({
            "name": name,
            "path": wav,
            "index": gi,          # 全局序号：点格子时 /api/review/grid {page: index, size: 1}
            "duration": round(dur, 3) if dur else 0.0,
            "intervals": intervals,
            "tgPath": tg_path or "",
            "series": series,
        })

    warnings = []
    if want_tsv:
        if not tsv_path:
            warnings.append("没找到汇总表（*out.tsv）：谐波差 / 噪音水平 / 能量与激励 / 谐波振幅"
                            "类曲线将是空的。先在第三步跑一次批量运行，或把第一步的输出目录指到结果所在处。")
        elif tsv_err:
            warnings.append("汇总表读取失败（相关列将为空）：" + tsv_err)
    return {
        "ok": True,
        "dir": dir_path,
        "page": page,
        "size": size,
        "total": total,
        "pages": pages,
        "files": files,
        "params": want,
        "tsvPath": tsv_path or "",
        "skipped": skipped,
        "warnings": warnings,
    }


def file_series(dir_path, name, params=None, ext="wav", values=None,
                max_points=GRID_MAX_POINTS):
    """单文件逐点序列（VS 版「参数显示」数据源）。

    与 grid_page 同一口径：F0 ← measure/<主名>.Pitch；F1–B5/B1–B5 ← .Formant；
    谐波差/噪音/能量/谐波振幅 ← 汇总表 out.tsv 的对应列。只取 name 这一个文件
    （name 是 /api/scan 返回的相对名，顶层拼接，不递归），供「参数显示」界面
    点选单个文件后取它的全部曲线并叠加绘制。

    返回 {ok, dir, name, tsvPath, duration, intervals,
          series: {参数: [[t, v|null], …]}, warnings}。
    """
    if not dir_path or not os.path.isdir(dir_path):
        return {"ok": False, "error": "目录不存在：%s" % dir_path}
    wav = os.path.join(dir_path, name)
    if not os.path.isfile(wav):
        return {"ok": False, "error": "文件不存在：%s" % name}
    want = [c for c in (params or COLUMNS) if c in _COL]
    seen = set()
    want = [p for p in want if not (p in seen or seen.add(p))]

    from .review_grid import _downsample, _find_textgrid, _read_tg_intervals
    from . import audio
    base = os.path.splitext(os.path.basename(name))[0]
    series = {}
    run = _latest_run(dir_path, values)
    # 基频对象（按本次运行基准选引擎：.Pitch / .sF0 / .strF0）
    rows = _read_pitch_rows(wav, run)
    if rows:
        series["F0"] = [[p["t"], (p["f0"] if p.get("f0") and p["f0"] > 0 else None)]
                        for p in rows]
    # 共振峰对象（.Formant / .sFormant）
    rows = _read_formant_rows(wav, run)
    if rows:
        for c in want:
            if c in _FORMANT_COLS:
                series[c] = [[p["t"], p.get(c)] for p in rows]
    # 汇总表列
    want_tsv = [c for c in want if col_source(c) == SOURCE_TSV]
    tsv_path = find_result_file(dir_path, values) if want_tsv else None
    tsv_map, tsv_err = ({}, None)
    if want_tsv:
        if tsv_path:
            tsv_map, tsv_err = _tsv_groups(tsv_path, want_tsv)
        if tsv_path and tsv_map:
            g = tsv_map.get(_norm_key(base))
            if g is None:
                for k, v in tsv_map.items():
                    if _norm_key(k) == _norm_key(base):
                        g = v
                        break
            for c in want_tsv:
                if g is None:
                    series[c] = []
                else:
                    vals = g["cols"].get(c) or []
                    if not vals or all(v is None for v in vals):
                        series[c] = []
                    else:
                        series[c] = [[t, v] for t, v in zip(g["t"], vals)]
    for c in want:
        series.setdefault(c, [])
    for c in list(series):
        series[c] = _downsample(series[c], max_points)
    tg_report = {"loaded": 0, "missing": [], "error": []}
    tg_path = _find_textgrid(wav, dir_path)
    intervals = _read_tg_intervals(tg_path, name, tg_report)
    dur = 0.0
    try:
        dur = audio._wav_info(wav)[0] or 0.0
    except Exception:
        dur = 0.0
    warnings = []
    if want_tsv and not tsv_path:
        warnings.append("没找到汇总表（*out.tsv）：谐波差 / 噪音水平 / 能量与激励 / 谐波振幅"
                        "类曲线将为空。先在「参数提取」跑一次批量运行。")
    elif want_tsv and tsv_err:
        warnings.append("汇总表读取失败（相关列将为空）：" + tsv_err)
    return {"ok": True, "dir": dir_path, "name": name, "tsvPath": tsv_path or "",
            "duration": round(dur, 3) if dur else 0.0, "intervals": intervals,
            "series": series, "warnings": warnings}


# ---- 参数量程（2026-09-27 方案③：批内 2%–98% 分位 + 语音学先验兜底） ----------------
# 用户定案：纵轴量程不能由单条曲线自身的 min–max 决定——平线微起伏会被放大成波浪，
# 不同文件间 F0 斜率/高度的差异也会被抹掉。量程必须来自「这个参数在全批的分布」。

_PARAM_PRIOR = {
    # 语音学生理先验（兜底用：批内该参数数据不足 < 30 点时才启用）
    "F0": (50, 500), "F1": (200, 1000), "F2": (600, 2500), "F3": (2200, 3400),
    "F4": (3000, 4300), "F5": (3800, 5000),
    "B1": (20, 400), "B2": (20, 400), "B3": (20, 400), "B4": (20, 400), "B5": (20, 400),
    "HNR05": (0, 30), "HNR15": (0, 30), "HNR25": (0, 30), "HNR35": (0, 30), "HNR38": (0, 30),
    "CPP": (0, 30), "CPPS": (0, 30), "SHR": (0, 1),
    "intensity": (0, 90), "soe": (0, 90),
}


def _percentile(sorted_vals, q):
    """线性插值分位（q∈[0,1]）。sorted_vals 非空。"""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def param_ranges(dir_path, params=None, values=None):
    """整个调查点每个参数的固定量程 {参数: [lo, hi]}（冻结后跨文件、跨时间可比）。

    数据源与 grid_page 同一口径：F0 ← 各文件 .Pitch，F1–B5 ← .Formant，
    其余 ← 汇总表 out.tsv 的全部行。取 2%–98% 分位（截掉离群尖刺）加 10% 余量；
    批内数据 < 30 点的参数退到 _PARAM_PRIOR，先验也没有的退到批内 min–max。
    """
    if not dir_path or not os.path.isdir(dir_path):
        return {"ok": False, "error": "目录不存在：%s" % dir_path}
    want = [c for c in (params or COLUMNS) if c in _COL]
    seen = set()
    want = [c for c in want if not (c in seen or seen.add(c))]

    want_pitch = [c for c in want if c in _PITCH_COLS]
    want_formant = [c for c in want if c in _FORMANT_COLS]
    want_tsv = [c for c in want if col_source(c) == SOURCE_TSV]

    from .review_grid import _list_wavs
    all_wavs = _list_wavs(dir_path, "wav")

    run = _latest_run(dir_path, values)
    tsv_path = find_result_file(dir_path, values) if want_tsv else None
    tsv_map, _ = ({}, None)
    if want_tsv and tsv_path:
        tsv_map, _ = _tsv_groups(tsv_path, want_tsv)

    buckets = {c: [] for c in want}          # 参数 → 全批值
    for name in all_wavs:
        wav = os.path.join(dir_path, name)
        base = os.path.splitext(os.path.basename(name))[0]
        if want_pitch:
            for p in _read_pitch_rows(wav, run):
                if p.get("f0") and p["f0"] > 0:
                    buckets["F0"].append(p["f0"])
        if want_formant:
            for p in _read_formant_rows(wav, run):
                for c in want_formant:
                    v = p.get(c)
                    if v is not None and isfinite(v):
                        buckets[c].append(v)
        if want_tsv:
            g = tsv_map.get(_norm_key(base))
            if g is None:
                for k, v in tsv_map.items():
                    if _norm_key(k) == _norm_key(base):
                        g = v
                        break
            if g:
                for c in want_tsv:
                    for v in (g["cols"].get(c) or []):
                        if v is not None and isfinite(v):
                            buckets[c].append(v)

    ranges, sources = {}, {}
    for c in want:
        vals = sorted(buckets[c])
        if len(vals) >= 30:
            lo, hi = _percentile(vals, 0.02), _percentile(vals, 0.98)
            if hi > lo:
                pad = (hi - lo) * 0.10
                ranges[c] = [lo - pad, hi + pad]
                sources[c] = "batch"
                continue
        if c in _PARAM_PRIOR:
            ranges[c] = list(_PARAM_PRIOR[c])
            sources[c] = "prior"
        elif vals:
            ranges[c] = [vals[0], vals[-1]]
            sources[c] = "minmax"
        else:
            ranges[c] = [0, 1]
            sources[c] = "none"
    return {"ok": True, "dir": dir_path, "n": len(all_wavs),
            "ranges": ranges, "sources": sources}
