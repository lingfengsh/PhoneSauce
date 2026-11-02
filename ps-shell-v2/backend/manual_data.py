# -*- coding: utf-8 -*-
"""Manual Data（数据调整）——按引擎导入/覆盖测量列。

## 依据

复刻 VoiceSauce ``vs_ManualData.m``（UCLA SPAPL, 2009-2015）**行为语义**：
``func_getmanualdataparameterlist.m`` 里每个参数名都带引擎（``F0 - Straight
(strF0)`` / ``F0 - Snack (sF0)`` / ``F0 - Praat (pF0)`` / ``F1 - Snack (sF1)`` …），
``vs_ManualData`` 从文本文件读一列数值，无效占位符记 NaN，支持 offset（帧偏移）
与重采样到该音频帧数，最后 ``save(matfile, param, '-append')`` 只覆盖那一个变量。

## 与蓝本的有意差异（2.0 架构决定）

1. 蓝本把结果写进 ``<wav>.mat``；2.0 没有 mat，F0/共振峰的权威载体是
   ``measure/`` 下**按引擎分后缀**的对象文件（Praat ``.Pitch``/``.Formant``、
   Snack ``.sF0``/``.sFormant``、STRAIGHT ``.strF0``）。故这里写对象，
   且**只动所选引擎那一个文件**——不伪造 Praat 对象，也不串到别的引擎。
2. 蓝本是单列覆盖（F1 一列一列改）；对象格式里 F1–F4 同表，故这里读现有对象、
   只替换目标列，其余列原样保留。

## 帧数口径

与 ``pysauce/engine.py`` 一致：1 ms 网格，``n = floor(duration_s * 1000)``。
"""
import os
from math import isfinite

from . import review_export
from .pysauce.engine import FRAMESHIFT_MS

# 蓝本 MD_invalidentry 默认值（逗号分隔）；空串也算无效（空行）
DEFAULT_INVALID = "NaN,nan,--undefined--,-,--,"

F0_COLUMN = "f0"
FORMANT_COLUMNS = ("F1", "F2", "F3", "F4", "B1", "B2", "B3", "B4")


def _n_frames(wav_path):
    """该音频在 1 ms 网格上的帧数；读不到返回 0。"""
    try:
        from .pysauce import framing
        y, fs = framing.read_wav(wav_path)
        return int(y.size / float(fs) * 1000.0 / FRAMESHIFT_MS)
    except Exception:
        return 0


def object_path(wav_path, dim, engine):
    """该引擎在该维度上的对象路径（不保证存在）；不支持的组合返回 None。"""
    return review_export.engine_object_path(wav_path, dim, engine)


def resolve_engine(wav_path, dim, values=None):
    """当前该文件在该维度上「实际有对象」的引擎（按本次运行的基准优先）。

    与参数展示/导出同一口径（series_export._find_engine_object），保证
    数据调整打开时看到的就是链路真正在用的那套，而不是写死的 Praat。
    """
    from . import series_export as _se
    try:
        run = _se._latest_run(os.path.dirname(wav_path), values)
        _p, e = _se._find_engine_object(wav_path, dim, run)
        return e or "praat"
    except Exception:  # noqa: BLE001
        return "praat"


def read_rows(wav_path, dim, engine=None, values=None):
    """读该引擎对象 → 逐帧行（键与 praat_objects.read_* 同构）。

    ``engine`` 省略/为空时按 ``resolve_engine`` 自动认定，响应里回传实际引擎。
    返回 ``{ok, engine, path, exists, rows, n, error}``；对象不存在不算错误
    （exists=False），界面据此显示「该引擎还没算过这套」。
    """
    engine = (engine or "").strip().lower() or resolve_engine(wav_path, dim, values)
    p = object_path(wav_path, dim, engine)
    if not p:
        return {"ok": False, "error": "该引擎不产出这个维度：%s / %s" % (dim, engine),
                "engine": engine, "path": "", "exists": False, "rows": [], "n": 0}
    if not os.path.isfile(p):
        return {"ok": True, "engine": engine, "path": p, "exists": False, "rows": [],
                "n": _n_frames(wav_path), "error": None}
    try:
        from . import praat_objects
        if engine == "praat":
            rows = (praat_objects.read_pitch_text(p) if dim == "f0"
                    else praat_objects.read_formant_text(p))
        else:
            from .series_export import _read_simple_rows
            rows = _read_simple_rows(p)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "对象读取失败：%s" % exc,
                "engine": engine, "path": p, "exists": True, "rows": [], "n": 0}
    return {"ok": True, "engine": engine, "path": p, "exists": True, "rows": rows,
            "n": _n_frames(wav_path), "error": None}


def load_text(path):
    """读数据文件（UTF-8 优先，失败退 GBK；再失败按 UTF-8 替换坏字节）。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def parse_values(text, invalid=None):
    """文本 → 数值列表（无效占位符记 None）。一行一个值，忽略空行以外的空白。"""
    bad = _invalid_set(invalid)
    out = []
    for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = ln.strip()
        if s == "":
            continue
        if s in bad:
            out.append(None)
            continue
        try:
            v = float(s)
        except ValueError:
            out.append(None)
            continue
        out.append(v if isfinite(v) else None)
    return out


def _invalid_set(invalid):
    raw = DEFAULT_INVALID if invalid is None else str(invalid)
    # 空串本身是合法占位符（表示「空行即无效」），但不能靠 split 拿到，故显式补
    return set(x.strip() for x in raw.split(","))


def fit_values(values, n, offset=0, resample=True):
    """把导入值铺到 n 帧网格上（复刻蓝本 OF/newdata 的摆放规则）。

    ``offset`` 单位是**帧**（可负）；``resample=True`` 时先把值线性重采样到 n 点。
    """
    vals = [None if v is None or not isfinite(v) else float(v) for v in (values or [])]
    if n <= 0 or not vals:
        return [None] * max(0, n)
    if resample and len(vals) != n:
        vals = _resample(vals, n)
    of = int(offset or 0)
    out = [None] * n
    if len(vals) + of >= n:
        # 蓝本：newdata(OF+1:L) = data(1:L-OF)
        if of >= 0:
            seg = vals[: max(0, n - of)]
            for i, v in enumerate(seg):
                out[of + i] = v
        else:
            # OF<0 时上式会越界（蓝本靠 MATLAB 索引报错兜住），这里取到末尾
            seg = vals[-of:]
            for i, v in enumerate(seg[:n]):
                out[i] = v
    elif of >= 0:
        for i, v in enumerate(vals):
            if of + i < n:
                out[of + i] = v
    else:
        seg = vals[-of:]
        for i, v in enumerate(seg[: n + of]):
            out[i] = v
    return out


def _resample(vals, n):
    """线性重采样到 n 点（None 视为间断：最近的无效点会传染，避免凭空造值）。"""
    m = len(vals)
    if m == 0:
        return [None] * n
    if m == n:
        return list(vals)
    out = []
    for i in range(n):
        pos = i * (m - 1) / float(n - 1) if n > 1 else 0.0
        i0 = int(pos)
        i1 = min(m - 1, i0 + 1)
        f = pos - i0
        a, b = vals[i0], vals[i1]
        if a is None or b is None:
            out.append(a if f < 0.5 else b)
        else:
            out.append(a + (b - a) * f)
    return out


def save_values(wav_path, dim, engine, values, offset=0, resample=True, column=None):
    """把一列导入值写进该引擎对象（其余列 / 其他引擎原样不动）。

    返回 ``{ok, path, n, filled, error}``；``filled`` = 非缺值帧数。
    """
    if not wav_path or not os.path.isfile(wav_path):
        return {"ok": False, "error": "音频文件不存在：%s" % wav_path}
    p = object_path(wav_path, dim, engine)
    if not p:
        return {"ok": False, "error": "该引擎不产出这个维度：%s / %s" % (dim, engine)}
    n = _n_frames(wav_path)
    if n <= 0:
        return {"ok": False, "error": "读不出音频帧数：%s" % wav_path}
    fitted = fit_values(values, n, offset=offset, resample=resample)
    filled = sum(1 for v in fitted if v is not None)
    if filled == 0:
        return {"ok": False, "error": "导入数据为空（或全被判为无效值），未写入"}
    warn = []
    try:
        if dim == "f0":
            _write_f0(p, engine, fitted, warn)
        else:
            _write_formant_column(p, wav_path, engine, column or "F1", fitted, warn)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "写入失败：%s" % exc}
    if warn:
        return {"ok": False, "error": "；".join(warn), "path": p}
    return {"ok": True, "path": p, "n": n, "filled": filled, "error": None}


def _write_f0(path, engine, fitted, warn):
    import numpy as np
    from .pysauce import engine as _eng
    arr = np.array([np.nan if v is None else v for v in fitted], dtype=float)
    if engine == "praat":
        _eng._write_praat_pitch(path, arr, warn)
    else:
        _eng._write_simple_object(path, "f0", engine, arr, None)


def _write_formant_column(path, wav_path, engine, column, fitted, warn):
    """只替换 column 这一列，其余列（F/B）从现有对象读回后原样写回。"""
    import numpy as np
    from .pysauce import engine as _eng
    col = (column or "F1").strip().upper()
    if col not in FORMANT_COLUMNS:
        raise ValueError("未知共振峰列：%s（可选 %s）" % (column, "/".join(FORMANT_COLUMNS)))
    n = len(fitted)
    # 现有对象 → 各列数组（不存在则全 NaN，长度对齐 n 帧）
    f_vecs = [np.full(n, np.nan) for _ in range(4)]
    b_vecs = [np.full(n, np.nan) for _ in range(4)]
    existing = read_rows(wav_path, "formant", engine)
    if existing.get("rows"):
        for i, r in enumerate(existing["rows"][:n]):
            for k in range(4):
                v = r.get("F%d" % (k + 1))
                if v is not None and isfinite(v):
                    f_vecs[k][i] = v
                v = r.get("B%d" % (k + 1))
                if v is not None and isfinite(v):
                    b_vecs[k][i] = v
    target = (f_vecs if col.startswith("F") else b_vecs)[int(col[1]) - 1]
    for i in range(n):
        target[i] = np.nan if fitted[i] is None else fitted[i]
    if engine == "praat":
        _eng._write_praat_formant(path, f_vecs, b_vecs, warn)
    else:
        _eng._write_simple_object(path, "formant", engine, f_vecs, b_vecs)
