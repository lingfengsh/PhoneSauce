# -*- coding: utf-8 -*-
"""pysauce 编排入口（V2-F1）—— 单 wav → 67 列参数字典。

**唯一对外入口**（F2 的 server 只调本模块）。

调度顺序严格照蓝本 `vs_ParameterEstimation.m`（L560-1267）：
  read → [resample?] → data_len → F0 引擎 → Formant 引擎 → SHR → 测量项 → 拼装

列派生照蓝本 `func_buildMData.m`（279 行，**权威**）：
  • ``H1u`` = 原始 ``H1``；``H1c`` = H1u − iseli(F0,F1,B1) − iseli(F0,F2,B2)
  • ``A1c`` = A1u − iseli(F1,F1,B1) − iseli(F1,F2,B2)
  • ``H2Kc`` = H2Ku − iseli(F2K,F1,B1) − iseli(F2K,F2,B2) − iseli(F2K,F3,B3)
  • ``H5Ku`` = 原始 H5K（**无校正版**——蓝本无 H5Kc）
  • ``H1H2u`` = H1 − H2（**原始** H1/H2，非 H1u）
  • ``H2KH5Ku`` = H2Ku − H5Ku（用**未校正** H2Ku）
  • ``H1H2c`` 等 = `func_GetH1H2_H2H4` 家族（slopes.py），与 buildMData 的
    H1c/H2c 各自独立；两套都出自蓝本，此处按蓝本各自的产生点分别计算。

⚠️ 已核实蓝本**不自动重采样**：16 kHz 重采样是用户勾选项
（`checkbox_process16khz`，L562-576）。2.0 无此勾选 → **不重采样**，原样跑
（卡 §4.1 要求「以蓝本为准并写明」，此即结论）。

⚠️ 关键差异：蓝本 `func_buildMData` 的 H1c/H2c/H4c/A*c **不做** `slopes.py`
的三项累加（H1 只减 F1/F2 两项，A1 只减两项，A3 减三项）——两者是蓝本里
**两处独立的校正实现**（`vs_ParameterEstimation` 存 H1c 与
`func_GetH1H2_H2H4` 内部各算一次）。本模块同时保留两者：
  • ``H1c/H2c/H4c/A1c/A2c/A3c/H2Kc``  ← `func_buildMData` 口径
  • ``H1H2c/H2H4c/H1A1c/H1A2c/H1A3c/H42Kc/H2KH5Kc`` ← `slopes.py` 口径
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import os

import numpy as np

from . import correct_iseli as _ci
from . import framing
from . import get_2k_5k as _g25
from . import get_a1a2a3 as _ga
from . import get_bw_fmt as _bw
from . import get_cpp as _gcpp
from . import get_energy as _gen
from . import get_h1_h2_h4 as _gh
from . import get_hnr as _ghnr
from . import get_soe as _gsoe
from . import parse_engine as _pe
from . import shrp as _shrp
from . import slopes as _sl
from .output_cols import OUTPUT_COLS, empty_result

# ── 默认值（vs_Initialize.m）───────────────────────────────────────────────
FRAMESHIFT_MS = 1.0
_DEF_PRAAT_F0 = dict(min_pitch=40.0, max_pitch=500.0, silence_th=0.03,
                     voicing_th=0.45, octave_cost=0.01, octave_jump_cost=0.35,
                     vuv_cost=0.14)
_DEF_PRAAT_FMT = dict(frame_shift=0.001, window_length=0.025,
                      num_formants=4.0, max_formant=6000.0)
_DEF_SNACK_F0 = dict(frameshift=0.001, windowsize=0.025, max_f0=500.0, min_f0=40.0)
_DEF_SNACK_FMT = dict(window_length=0.025, framelength=0.001, preemphasis=0.96,
                      lpc_order=12)
_SHR_MIN, _SHR_MAX = 40.0, 500.0


def _data_len(dur_s: float) -> int:
    """蓝本 L579：data_len = floor(length(y)/Fs*1000/frameshift)。"""
    return int(np.floor(dur_s * 1000.0 / FRAMESHIFT_MS))


def _fit(vec, n: int):
    """把引擎输出对齐到 n 帧（1 ms 网格）：短补 NaN、长截断。"""
    if vec is None:
        return None
    a = np.asarray(vec, dtype=float)
    if a.size == n:
        return a
    out = np.full(n, np.nan, dtype=float)
    m = min(n, a.size)
    out[:m] = a[:m]
    return out


def _vec_or_none(v):
    """np 向量 → list（含 NaN）；None 保持 None。"""
    if v is None:
        return None
    return [float(x) for x in np.asarray(v, dtype=float)]


def _nan_list(n: int) -> list:
    """全 NaN 的 n 长列表。

    卡 §4.5：「指定的引擎列缺失 → 空 → **该项全 NaN**（VS 行为，不自动回退）」。
    即测量项在基准 F0/FMT 缺失时，**不是 None，而是等长的全 NaN 列表**——
    这样出表时是 500 个 ``--undefined--``，与 VS 的「列存在但无值」一致。
    """
    return [float("nan")] * n


def run_file(req: dict) -> dict:
    """单文件全流程。返回 {列名: 值列表(1 ms 网格)}，67 列全量（未勾选/失败 = None）。

    特殊键：``_meta``（``{"f0_algorithm":…, "fmt_algorithm":…}``）、
    ``_warnings``（字符串列表）。**永不 raise**（单算法失败 → 该组列 None + warning）。
    """
    res = empty_result()
    warn: list[str] = res["_warnings"]
    res["_meta"] = {
        "f0_algorithm": req.get("f0_algorithm") or "praat",
        "fmt_algorithm": req.get("fmt_algorithm") or "praat",
    }

    wav = req.get("wav_path") or ""
    try:
        y, fs = framing.read_wav(wav)
    except Exception as exc:  # noqa: BLE001
        warn.append(f"读取音频失败：{wav}（{exc}）")
        return res

    n = _data_len(y.size / fs)
    if n <= 0:
        warn.append(f"音频过短，data_len=0：{wav}")
        return res

    pitch_engine = req.get("pitch_engine") or "praat"
    formant_engine = req.get("formant_engine") or "praat"
    reuse = bool(req.get("reuse"))
    mdir = req.get("measure_dir")
    base = os.path.splitext(os.path.basename(wav))[0]

    # ── 1. F0 引擎（复用优先）────────────────────────────────────────────
    matdata: dict = {}
    f0_col = {"praat": "pF0", "snack": "sF0", "straight": "strF0",
              "other": "oF0"}.get(pitch_engine)
    f0_vec = None
    if f0_col is None:
        warn.append(f"未知 pitch_engine：{pitch_engine}，F0 列留空")
    else:
        reuse_path = _reuse_path(req, mdir, base, "f0", pitch_engine)
        if reuse and reuse_path and os.path.isfile(reuse_path):
            got = (_read_praat_pitch(reuse_path, n, warn) if pitch_engine == "praat"
                   else _read_simple_object(reuse_path, "f0", n, warn))
            if got is not None:
                f0_vec = got
                warn.append(f"F0 复用 measure/（{pitch_engine}）：{os.path.basename(reuse_path)}")
        if f0_vec is None:
            f0_vec = _compute_f0(req, pitch_engine, wav, fs, n, warn)
            if f0_vec is not None and mdir:
                _save_engine_object(mdir, base, "f0", pitch_engine, f0_vec, fs, warn)
        if f0_vec is not None:
            matdata[f0_col] = f0_vec

    # ── 2. Formant 引擎（复用优先）───────────────────────────────────────
    fmt_cols = {"praat": ("pF1", "pF2", "pF3", "pF4"),
                "snack": ("sF1", "sF2", "sF3", "sF4"),
                "other": ("oF1", "oF2", "oF3", "oF4")}.get(formant_engine)
    f_vecs = None
    b_vecs = None
    if fmt_cols is None:
        warn.append(f"未知 formant_engine：{formant_engine}，共振峰列留空")
    else:
        reuse_path = _reuse_path(req, mdir, base, "formant", formant_engine)
        if reuse and reuse_path and os.path.isfile(reuse_path):
            got = (_read_praat_formant(reuse_path, n, warn) if formant_engine == "praat"
                   else _read_simple_object(reuse_path, "formant", n, warn))
            if got is not None:
                f_vecs, b_vecs = got
                warn.append(f"共振峰复用 measure/（{formant_engine}）：{os.path.basename(reuse_path)}")
        if f_vecs is None:
            got = _compute_fmt(req, formant_engine, wav, fs, n, warn)
            if got is not None:
                f_vecs, b_vecs = got
                if mdir:
                    _save_engine_object(mdir, base, "formant", formant_engine,
                                        f_vecs, fs, warn, b_vecs=b_vecs)
        if f_vecs is not None:
            for col, v in zip(fmt_cols, f_vecs):
                matdata[col] = v
        if b_vecs is not None:
            bcols = {"praat": ("pB1", "pB2", "pB3", "pB4"),
                     "snack": ("sB1", "sB2", "sB3", "sB4"),
                     "other": ("oB1", "oB2", "oB3", "oB4")}[formant_engine]
            for col, v in zip(bcols, b_vecs):
                matdata[col] = v

    # ── 3. 基准引擎取用（§0c）────────────────────────────────────────────
    F0 = _pe.parse_f0(matdata, res["_meta"]["f0_algorithm"])
    F1, F2, F3, B1p, B2p, B3p = _pe.parse_fmt(matdata, res["_meta"]["fmt_algorithm"])
    if F0 is None:
        warn.append(f"基准 F0 引擎列缺失（f0_algorithm="
                    f"{res['_meta']['f0_algorithm']}）→ 依赖 F0 的测量列全部为空")

    # 带宽（Hawks-Miller，供 iseli 校正；蓝本 buildMData L63-65 同款）
    def _bw_of(fx):
        if fx is None or F0 is None:
            return None
        return _bw.get_bw_fmt(fx, F0, "hm")

    hmB1 = B1p if B1p is not None else _bw_of(F1)
    hmB2 = B2p if B2p is not None else _bw_of(F2)
    hmB3 = B3p if B3p is not None else _bw_of(F3)

    # ── 4. SHR（蓝本 L764 最前，保持此序）────────────────────────────────
    if req.get("do_shr"):
        try:
            if F0 is not None:
                shr, shrf0 = _shrp.get_shrp(y, fs, F0, frameshift_ms=FRAMESHIFT_MS)
                res["SHR"] = _vec_or_none(shr)
                if "shrF0" not in matdata:
                    matdata["shrF0"] = shrf0
                    res["shrF0"] = _vec_or_none(shrf0)
            else:
                warn.append("SHR 跳过：基准 F0 缺失")
                res["SHR"] = _nan_list(n)
        except Exception as exc:  # noqa: BLE001
            warn.append(f"SHR 失败：{exc}")

    # ── 5. 测量项（每项仅当开关 True）─────────────────────────────────────
    raw: dict = {}          # 中间量（H1/H2/H4/A1..A3/H2K/F2K/H5K）

    if req.get("do_h1h2h4"):
        if F0 is not None:
            try:
                h1, h2, h4 = _gh.get_h1_h2_h4(y, fs, F0)
                raw.update(H1=h1, H2=h2, H4=h4)
                # func_buildMData L67-68/78-79/89-90：H1u=H1（原始谐波）
                res["H1u"] = _vec_or_none(h1)
                res["H2u"] = _vec_or_none(h2)
                res["H4u"] = _vec_or_none(h4)
            except Exception as exc:  # noqa: BLE001
                warn.append(f"H1/H2/H4 失败：{exc}")
        else:
            warn.append("H1/H2/H4 跳过：基准 F0 缺失")
            for _c in ("H1u", "H2u", "H4u"):
                res[_c] = _nan_list(n)

    if req.get("do_a1a2a3"):
        if F0 is not None and F1 is not None and F2 is not None and F3 is not None:
            try:
                a1, a2, a3 = _ga.get_a1a2a3(y, fs, F0, F1, F2, F3)
                raw.update(A1=a1, A2=a2, A3=a3)
                # func_buildMData L96-97/105-106/114-115：A1u=A1（原始幅度）
                res["A1u"] = _vec_or_none(a1)
                res["A2u"] = _vec_or_none(a2)
                res["A3u"] = _vec_or_none(a3)
            except Exception as exc:  # noqa: BLE001
                warn.append(f"A1/A2/A3 失败：{exc}")
        else:
            warn.append("A1/A2/A3 跳过：基准 F0 或 F1-F3 缺失")
            for _c in ("A1u", "A2u", "A3u"):
                res[_c] = _nan_list(n)

    if req.get("do_2k5k"):
        if F0 is not None:
            try:
                h2k, f2k = _g25.get_2k(y, fs, F0)
                h5k, _f5k = _g25.get_5k(y, fs, F0)
                raw.update(H2K=h2k, F2K=f2k, H5K=h5k)
                # func_buildMData L131/143：H2Ku=H2K、H5Ku=H5K（H5K 无校正版）
                res["H2Ku"] = _vec_or_none(h2k)
                res["H5Ku"] = _vec_or_none(h5k)
            except Exception as exc:  # noqa: BLE001
                warn.append(f"2K/5K 失败：{exc}")
        else:
            warn.append("2K/5K 跳过：基准 F0 缺失")
            for _c in ("H2Ku", "H5Ku"):
                res[_c] = _nan_list(n)

    if req.get("do_slopes"):
        _do_slopes(res, raw, fs, F0, F1, F2, F3, hmB1, hmB2, hmB3, warn)

    if req.get("do_energy"):
        if F0 is not None:
            try:
                res["Energy"] = _vec_or_none(_gen.get_energy(y, F0, fs))
            except Exception as exc:  # noqa: BLE001
                warn.append(f"Energy 失败：{exc}")
        else:
            warn.append("Energy 跳过：基准 F0 缺失")
            res["Energy"] = _nan_list(n)

    if req.get("do_cpp"):
        if F0 is not None:
            try:
                res["CPP"] = _vec_or_none(_gcpp.get_cpp(y, fs, F0))
            except Exception as exc:  # noqa: BLE001
                warn.append(f"CPP 失败：{exc}")
        else:
            warn.append("CPP 跳过：基准 F0 缺失")
            res["CPP"] = _nan_list(n)

    if req.get("do_hnr"):
        if F0 is not None:
            try:
                h05, h15, h25, h35 = _ghnr.get_hnr(y, fs, F0)
                res["HNR05"] = _vec_or_none(h05)
                res["HNR15"] = _vec_or_none(h15)
                res["HNR25"] = _vec_or_none(h25)
                res["HNR35"] = _vec_or_none(h35)
            except Exception as exc:  # noqa: BLE001
                warn.append(f"HNR 失败：{exc}")
        else:
            warn.append("HNR 跳过：基准 F0 缺失")
            for _c in ("HNR05", "HNR15", "HNR25", "HNR35"):
                res[_c] = _nan_list(n)

    if req.get("do_soe"):
        if F0 is not None:
            method = req.get("do_soe_method") or "whole"
            try:
                epoch, soe, _z = _gsoe.get_soe(y, fs, method, F0)
                res["epoch"] = _vec_or_none(epoch)
                res["soe"] = _vec_or_none(soe)
            except Exception as exc:  # noqa: BLE001
                warn.append(f"SoE 失败：{exc}")
        else:
            warn.append("SoE 跳过：基准 F0 缺失")
            for _c in ("epoch", "soe"):
                res[_c] = _nan_list(n)

    # ── 6. 引擎列写入结果 ────────────────────────────────────────────────
    for col in OUTPUT_COLS:
        if col in matdata and res.get(col) is None:
            res[col] = _vec_or_none(_fit(matdata[col], n))

    return res


def _do_slopes(res, raw, fs, F0, F1, F2, F3, B1, B2, B3, warn):
    """未校正差值 + Iseli 校正版（照 func_buildMData.m 与 slopes.py）。"""
    H1 = raw.get("H1"); H2 = raw.get("H2"); H4 = raw.get("H4")
    A1 = raw.get("A1"); A2 = raw.get("A2"); A3 = raw.get("A3")
    H2K = raw.get("H2K"); F2K = raw.get("F2K"); H5K = raw.get("H5K")

    # ── 未校正差值（func_buildMData L155-196，用**原始** Hx/Ax）──────────
    def _sub(a, b):
        return None if (a is None or b is None) else np.asarray(a, float) - np.asarray(b, float)

    pairs = {
        "H1H2u": (H1, H2), "H2H4u": (H2, H4),
        "H1A1u": (H1, A1), "H1A2u": (H1, A2), "H1A3u": (H1, A3),
        "H42Ku": (H4, H2K), "H2KH5Ku": (H2K, H5K),
    }
    for col, (a, b) in pairs.items():
        v = _sub(a, b)
        if v is not None:
            res[col] = _vec_or_none(v)

    # ── 校正版：buildMData 口径（H1c/H2c/H4c/A1c/A2c/A3c/H2Kc）─────────
    if F0 is not None:
        def _corr(f, fx, bx):
            if fx is None or bx is None:
                return None
            return _ci.correct_iseli_z(f, fx, bx, fs)

        def _apply(col, base, terms):
            v = base
            for fx, bx in terms:
                c = _corr(base_f, fx, bx)
                if c is None:
                    return None
                v = v - c
            return v

        # H1c = H1u - iseli(F0,F1,B1) - iseli(F0,F2,B2)
        if H1 is not None:
            base_f = F0
            v = _apply("H1c", H1, [(F1, B1), (F2, B2)])
            if v is not None:
                res["H1c"] = _vec_or_none(v)
        if H2 is not None:
            base_f = 2 * F0
            v = _apply("H2c", H2, [(F1, B1), (F2, B2)])
            if v is not None:
                res["H2c"] = _vec_or_none(v)
        if H4 is not None:
            base_f = 4 * F0
            v = _apply("H4c", H4, [(F1, B1), (F2, B2)])
            if v is not None:
                res["H4c"] = _vec_or_none(v)
        # A1c = A1u - iseli(F1,F1,B1) - iseli(F1,F2,B2)
        if A1 is not None:
            base_f = F1
            v = _apply("A1c", A1, [(F1, B1), (F2, B2)])
            if v is not None:
                res["A1c"] = _vec_or_none(v)
        if A2 is not None:
            base_f = F2
            v = _apply("A2c", A2, [(F1, B1), (F2, B2)])
            if v is not None:
                res["A2c"] = _vec_or_none(v)
        if A3 is not None:
            base_f = F3
            v = _apply("A3c", A3, [(F1, B1), (F2, B2), (F3, B3)])
            if v is not None:
                res["A3c"] = _vec_or_none(v)
        # H2Kc = H2Ku - iseli(F2K,F1,B1) - iseli(F2K,F2,B2) - iseli(F2K,F3,B3)
        if H2K is not None and F2K is not None:
            base_f = F2K
            v = _apply("H2Kc", H2K, [(F1, B1), (F2, B2), (F3, B3)])
            if v is not None:
                res["H2Kc"] = _vec_or_none(v)

    # ── 校正版：slopes.py 口径（H1H2c/H2H4c/H1A1c/H1A2c/H1A3c/H42Kc/H2KH5Kc）
    try:
        if H1 is not None and H2 is not None and H4 is not None:
            h1h2c, h2h4c = _sl.get_h1h2_h2h4(H1, H2, H4, fs, F0, F1, F2, B1, B2)
            res["H1H2c"] = _vec_or_none(h1h2c)
            res["H2H4c"] = _vec_or_none(h2h4c)
    except Exception as exc:  # noqa: BLE001
        warn.append(f"H1H2c/H2H4c 失败：{exc}")
    try:
        if H1 is not None and A1 is not None and A2 is not None and A3 is not None:
            h1a1c, h1a2c, h1a3c = _sl.get_h1a1_h1a2_h1a3(
                H1, A1, A2, A3, fs, F0, F1, F2, F3, B1, B2, B3)
            res["H1A1c"] = _vec_or_none(h1a1c)
            res["H1A2c"] = _vec_or_none(h1a2c)
            res["H1A3c"] = _vec_or_none(h1a3c)
    except Exception as exc:  # noqa: BLE001
        warn.append(f"H1A1c/H1A2c/H1A3c 失败：{exc}")
    try:
        if H4 is not None and H2K is not None and F2K is not None:
            h42kc = _sl.get_h42k(H4, H2K, F2K, fs, F0, F1, F2, F3, B1, B2, B3)
            res["H42Kc"] = _vec_or_none(h42kc)
    except Exception as exc:  # noqa: BLE001
        warn.append(f"H42Kc 失败：{exc}")
    try:
        if H2K is not None and F2K is not None and H5K is not None:
            h2kh5kc = _sl.get_2k5k(H2K, F2K, H5K, fs, F0, F1, F2, F3, B1, B2, B3)
            res["H2KH5Kc"] = _vec_or_none(h2kh5kc)
    except Exception as exc:  # noqa: BLE001
        warn.append(f"H2KH5Kc 失败：{exc}")


# ── 引擎计算 ──────────────────────────────────────────────────────────────
def _compute_f0(req, engine, wav, fs, n, warn):
    try:
        if engine == "praat":
            exe = req.get("praat_exe") or ""
            if not exe or not os.path.isfile(exe):
                warn.append("F0(Praat) 跳过：praat_exe 缺失")
                return None
            from .engines import praat_f0
            f0, _t = praat_f0.praat_pitch(wav, exe, time_step=0.005, **_DEF_PRAAT_F0)
            return _fit(f0, n)
        if engine == "snack":
            exe = req.get("snack_exe")
            from .engines import snack
            f0, _t = snack.snack_pitch(wav, snack_exe=exe, **_DEF_SNACK_F0)
            return _fit(f0, n)
        if engine == "straight":
            from .engines import straight
            f0, _t = straight.straight_pitch(wav)
            return _fit(f0, n)
        if engine == "other":
            p = req.get("other_f0_file")
            if not p:
                warn.append("F0(Other) 跳过：other_f0_file 未给")
                return None
            from .engines import other
            f0, _t = other.other_pitch(wav, p)
            return _fit(f0, n)
        warn.append(f"F0 引擎未知：{engine}")
    except Exception as exc:  # noqa: BLE001
        warn.append(f"F0({engine}) 失败：{exc}")
    return None


def _compute_fmt(req, engine, wav, fs, n, warn):
    try:
        if engine == "praat":
            exe = req.get("praat_exe") or ""
            if not exe or not os.path.isfile(exe):
                warn.append("Formant(Praat) 跳过：praat_exe 缺失")
                return None
            from .engines import praat_fmt
            f1, f2, f3, f4 = praat_fmt.praat_formants(wav, exe, **_DEF_PRAAT_FMT)
            return ([_fit(v, n) for v in (f1, f2, f3, f4)], None)
        if engine == "snack":
            exe = req.get("snack_exe")
            from .engines import snack
            out = snack.snack_formants(wav, snack_exe=exe, **_DEF_SNACK_FMT)
            f1, f2, f3, f4, b1, b2, b3, b4 = out
            return ([_fit(v, n) for v in (f1, f2, f3, f4)],
                    [_fit(v, n) for v in (b1, b2, b3, b4)])
        if engine == "other":
            p = req.get("other_fmt_file")
            if not p:
                warn.append("Formant(Other) 跳过：other_fmt_file 未给")
                return None
            from .engines import other
            vecs = other.other_formants(wav, p)
            return ([_fit(v, n) for v in vecs[:4]], [_fit(v, n) for v in vecs[4:8]])
        warn.append(f"Formant 引擎未知：{engine}")
    except Exception as exc:  # noqa: BLE001
        warn.append(f"Formant({engine}) 失败：{exc}")
    return None


# ── measure/ 复用读写 ─────────────────────────────────────────────────────
def _reuse_path(req, mdir, base, dim, engine):
    """measure/ 复用文件路径——**按引擎取后缀**（read_dir 留空 = measure_dir）。

    ⚠️ 2026-10-27 审查修复：原实现签名带 engine 却恒用 `.Pitch`/`.Formant`，导致
    基准为 snack/straight 时把 Praat 对象读进来冒充 sF0/strF0（静默错误数据）。
    现按 `review_export.ENGINE_OBJECT_EXT` 取该引擎自己的后缀；无后缀（该引擎
    不产该维度，如 straight 无共振峰）→ 返回 None（不复用、交由重算）。
    """
    rd = req.get("pitch_read_dir") if dim == "f0" else req.get("formant_read_dir")
    d = rd or mdir
    if not d:
        return None
    from backend import review_export as _re
    ext = (_re.ENGINE_OBJECT_EXT.get(dim) or {}).get(engine)
    if not ext:
        return None
    return os.path.join(d, base + ext)


def _read_praat_pitch(path, n, warn):
    try:
        from backend import praat_objects
        rows = praat_objects.read_pitch_text(path)
        if not rows:
            warn.append(f".Pitch 读回为空：{os.path.basename(path)}")
            return None
        vals = np.full(n, np.nan, dtype=float)
        for i, r in enumerate(rows[:n]):
            v = r.get("f0")
            if v is not None:
                vals[i] = float(v)
        return vals
    except Exception as exc:  # noqa: BLE001
        warn.append(f".Pitch 读取失败：{exc}")
        return None


def _read_praat_formant(path, n, warn):
    try:
        from backend import praat_objects
        rows = praat_objects.read_formant_text(path)
        if not rows:
            warn.append(f".Formant 读回为空：{os.path.basename(path)}")
            return None
        fs_ = {k: np.full(n, np.nan, dtype=float) for k in ("F1", "F2", "F3", "F4")}
        bs_ = {k: np.full(n, np.nan, dtype=float) for k in ("B1", "B2", "B3", "B4")}
        for i, r in enumerate(rows[:n]):
            for k in fs_:
                v = r.get(k)
                if v is not None:
                    fs_[k][i] = float(v)
            for k in bs_:
                v = r.get(k)
                if v is not None:
                    bs_[k][i] = float(v)
        return ([fs_["F1"], fs_["F2"], fs_["F3"], fs_["F4"]],
                [bs_["B1"], bs_["B2"], bs_["B3"], bs_["B4"]])
    except Exception as exc:  # noqa: BLE001
        warn.append(f".Formant 读取失败：{exc}")
        return None


def _read_simple_object(path, dim, n, warn):
    """读回非 Praat 引擎的自有格式对象（`_write_simple_object` 的逆操作）。

    格式：``# engine=… dim=…`` 注释行 + 表头 ``time\\tf0`` 或
    ``time\\tF1\\tF2\\tF3\\tF4[\\tB1..B4]``；缺值写作 ``--undefined--``。
    F0 维度返回 1-D 数组（长度 n，短补 NaN）；formant 返回
    ``(f_vecs, b_vecs|None)``，与 ``_read_praat_formant`` 的返回同构。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except Exception as exc:  # noqa: BLE001
        warn.append(f"对象读取失败（{os.path.basename(path)}）：{exc}")
        return None
    rows = [ln for ln in lines if not ln.startswith("#")]
    if len(rows) < 2:
        warn.append(f"对象为空：{os.path.basename(path)}")
        return None
    hdr = rows[0].split("\t")
    data = rows[1:]

    def _num(s):
        return None if s in ("", "--undefined--") else float(s)

    if dim == "f0":
        vals = np.full(n, np.nan, dtype=float)
        for i, ln in enumerate(data[:n]):
            parts = ln.split("\t")
            if len(parts) >= 2:
                v = _num(parts[1])
                if v is not None:
                    vals[i] = v
        return vals

    # formant：time + F1..F4 + 可选 B1..B4
    nf = min(4, max(0, len(hdr) - 1))
    if nf <= 0:
        warn.append(f"对象表头异常（{os.path.basename(path)}）：{rows[0]}")
        return None
    fs_ = [np.full(n, np.nan, dtype=float) for _ in range(nf)]
    nb = max(0, len(hdr) - 1 - nf)
    bs_ = [np.full(n, np.nan, dtype=float) for _ in range(nb)]
    for i, ln in enumerate(data[:n]):
        parts = ln.split("\t")
        for k in range(nf):
            if 1 + k < len(parts):
                v = _num(parts[1 + k])
                if v is not None:
                    fs_[k][i] = v
        for k in range(nb):
            if 1 + nf + k < len(parts):
                v = _num(parts[1 + nf + k])
                if v is not None:
                    bs_[k][i] = v
    return (fs_, bs_ if nb else None)


def _save_engine_object(mdir, base, dim, engine, vec, fs, warn, b_vecs=None):
    """落盘到 measure/（§0b 第 2/3 条）。

    Praat → 原生 ``.Pitch``/``.Formant``（格式与 1.2 一致）；
    非 Praat → 自有文本格式 + 引擎后缀（``.sF0``/``.strF0``/``.sFormant``），
    **绝不**写成 Praat 对象格式。
    """
    try:
        os.makedirs(mdir, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        warn.append(f"measure/ 创建失败：{exc}")
        return
    try:
        if engine == "praat":
            if dim == "f0":
                _write_praat_pitch(os.path.join(mdir, base + ".Pitch"), vec, warn)
            else:
                _write_praat_formant(os.path.join(mdir, base + ".Formant"),
                                     vec, b_vecs, warn)
        else:
            from backend import review_export as _re
            ext = (_re.ENGINE_OBJECT_EXT.get(dim) or {}).get(engine)
            if not ext:
                return
            _write_simple_object(os.path.join(mdir, base + ext), dim, engine,
                                 vec, b_vecs)
    except Exception as exc:  # noqa: BLE001
        warn.append(f"引擎对象落盘失败（{dim}/{engine}）：{exc}")


def _write_praat_pitch(path, f0, warn):
    """写 Praat ``Pitch 1`` 文本对象（**逐字对齐真实 Praat 输出**）。

    格式取自 samples 里的真实 ``.Pitch``（``praatF0.praat`` 的 Save as text）：
        File type = "ooTextFile"
        Object class = "Pitch 1"
        <空行>
        xmin / xmax / nx / dx / x1 / ceiling / maxnCandidates
        frames []:
            frames [1]:
                intensity = …
                nCandidates = 1
                candidates []:
                    candidates [1]:
                        frequency = …
                        strength = …

    ⚠️ 必须与 ``praat_objects.read_pitch_text`` 的期望一致（它按 ``frames [N]:``
    分帧、读 ``nCandidates``、取 ``candidates [1]`` 的 ``frequency``）。
    """
    a = np.asarray(f0, dtype=float)
    nx = int(a.size)
    dx = FRAMESHIFT_MS / 1000.0
    xmin = 0.0
    x1 = 0.0                      # 2.0 的 1 ms 网格从 0 起（framing 口径）
    xmax = xmin + (nx - 1) * dx if nx else 0.0

    out = [
        'File type = "ooTextFile"',
        'Object class = "Pitch 1"',
        "",
        f"xmin = {xmin} ",
        f"xmax = {xmax} ",
        f"nx = {nx} ",
        f"dx = {dx} ",
        f"x1 = {x1} ",
        "ceiling = 500 ",
        "maxnCandidates = 15 ",
        "frames []: ",
    ]
    for i in range(1, nx + 1):
        v = a[i - 1]
        freq = 0.0 if (v is None or not np.isfinite(v)) else float(v)
        strength = 0.0 if freq == 0.0 else 1.0
        out += [
            f"    frames [{i}]:",
            f"        intensity = 0 ",
            f"        nCandidates = 1 ",
            f"        candidates []: ",
            f"            candidates [1]:",
            f"                frequency = {freq} ",
            f"                strength = {strength} ",
        ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def _write_praat_formant(path, f_vecs, b_vecs, warn):
    """写 Praat ``Formant 2`` 文本对象（借 1.2 praat_objects.write_formant_text）。"""
    from backend import praat_objects
    n = len(f_vecs[0])
    dx = FRAMESHIFT_MS / 1000.0
    pts = []
    for i in range(n):
        p = {"t": i * dx}
        for k, name in enumerate(("F1", "F2", "F3", "F4")):
            v = f_vecs[k][i]
            p[name] = None if not np.isfinite(v) else float(v)
        if b_vecs is not None:
            for k, name in enumerate(("B1", "B2", "B3", "B4")):
                v = b_vecs[k][i]
                p[name] = None if not np.isfinite(v) else float(v)
        pts.append(p)
    ok = praat_objects.write_formant_text(path, pts, xmin=0.0, maxn=5)
    if not ok:
        warn.append("写 .Formant 失败（write_formant_text 返回 False）")


def _write_simple_object(path, dim, engine, vec, b_vecs):
    """非 Praat 引擎自有格式：``# engine=… dim=…`` 头 + ``time<TAB>value`` 列。"""
    dx = FRAMESHIFT_MS / 1000.0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# engine={engine} dim={dim}\n")
        if dim == "f0":
            fh.write("time\tf0\n")
            for i, v in enumerate(vec):
                val = "--undefined--" if not np.isfinite(v) else f"{v:.6f}"
                fh.write(f"{i * dx:.6f}\t{val}\n")
        else:
            fh.write("time\tF1\tF2\tF3\tF4")
            if b_vecs is not None:
                fh.write("\tB1\tB2\tB3\tB4")
            fh.write("\n")
            n = len(vec[0])
            for i in range(n):
                row = [f"{i * dx:.6f}"]
                for k in range(4):
                    v = vec[k][i]
                    row.append("--undefined--" if not np.isfinite(v) else f"{v:.6f}")
                if b_vecs is not None:
                    for k in range(4):
                        v = b_vecs[k][i]
                        row.append("--undefined--" if not np.isfinite(v) else f"{v:.6f}")
                fh.write("\t".join(row) + "\n")


# ── 批量 ──────────────────────────────────────────────────────────────────
def run_batch(reqs: list, progress_cb=None) -> list:
    """批量。``progress_cb(done, total)`` 每 1 文件回调一次（供 F2 接 watch 机制）。"""
    out = []
    total = len(reqs)
    for i, r in enumerate(reqs, start=1):
        try:
            out.append(run_file(r))
        except Exception as exc:  # noqa: BLE001  —— 防御：run_file 本不该 raise
            res = empty_result()
            res["_warnings"].append(f"run_file 异常：{exc}")
            out.append(res)
        if progress_cb is not None:
            try:
                progress_cb(i, total)
            except Exception:  # noqa: BLE001
                pass
    return out
