# -*- coding: utf-8 -*-
"""Praat Formant 引擎包装（V2-E1）。

蓝本：refs/voicesauce-v137/func_PraatFormants.m（196 行）。
算法零重写——本模块只做「命令构造 + 输出解析 + 1ms 帧网格映射」，
共振峰估计由 Praat 自带的 scripts/vs_praat/praatformants.praat 完成。

命令构造（蓝本 L38，Windows 分支）：
    Praat\\Praat.exe --run Praat\\praatformants.praat <wav> <frameshift>
        <windowlength> <num_formants> <maxFormant>
    格式化：%s %.3f %.3f %.1f %d
    （2.0 差异：蓝本写死路径，2.0 用传入的 praat_exe 与自带脚本路径；
      2.0 不加双引号（subprocess 无 shell）；2.0 加 `--FULL-TRUST`。）

输出解析（蓝本 L131-190）：
    .pfmt 首行为表头（丢弃），其后按 num_formants 决定列数：
        case 4 → 10 列；case 5 → 12 列；case 6 → 14 列；case 7 → 16 列。
    列含义（1-based）：1=时间(s)、2=num_formants、3=F1、4=B1、5=F2、6=B2、
        7=F3、8=B3、9=F4、10=B4、11=F5、12=B5、13=F6、14=B6、15=F7、16=B7。
    缺失值标记 `--undefined--`。
    映射到 1ms 帧网格：同 func_PraatPitch（start=0, finish=t(end),
    increment=frameshift*1000, 最近点 + 容差 frameprecision*frameshift*1000）。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import os
import subprocess

import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PS_SHELL_V2 = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
_VS_PRAAT_DIR = os.path.join(_PS_SHELL_V2, "scripts", "vs_praat")
_PRAAT_FMT_SCRIPT = os.path.join(_VS_PRAAT_DIR, "praatformants.praat")

_DEFAULT_FRAME_PRECISION = 1

# 蓝本 L137-148：num_formants → 读取的列数（含 time 与 num_formants 两列）
_COLS_BY_NF = {4: 10, 5: 12, 6: 14, 7: 16}
_COLS_DEFAULT = 10  # otherwise 分支


def _parse_praat_formant_file(fmtfile, frameshift, datalen, frameprecision,
                              num_formants):
    """解析 .pfmt → (F1,F2,F3,F4) 各长度 datalen（1ms 网格）。

    严格按蓝本 L131-190 逐列解析：先丢弃首行表头，再按 num_formants 取列。
    """
    ncols = _COLS_BY_NF.get(int(num_formants), _COLS_DEFAULT)

    rows = []
    with open(fmtfile, "r", encoding="utf-8", errors="replace") as fh:
        first = True
        for line in fh:
            line = line.rstrip("\r\n")
            if first:
                first = False  # 蓝本 L134：丢弃首行表头
                continue
            if line == "":
                continue
            parts = line.split()
            if len(parts) < 3:
                # 至少需要 time/numF/F1；不足视为异常行
                continue
            vals = []
            for tok in parts[:ncols]:
                if tok == "--undefined--":
                    vals.append(float("nan"))
                else:
                    try:
                        vals.append(float(tok))
                    except ValueError:
                        vals.append(float("nan"))
            # 若列数不足 ncols，补 NaN 到 ncols（textscan 行为近似）
            while len(vals) < ncols:
                vals.append(float("nan"))
            rows.append(vals)

    if not rows:
        nan = np.full(datalen, np.nan, dtype=float)
        return nan.copy(), nan.copy(), nan.copy(), nan.copy()

    arr = np.asarray(rows, dtype=float)      # shape (nrows, ncols)
    t = np.rint(arr[:, 0] * 1000.0)          # 蓝本 L150 round(C{1}*1000)

    F1 = np.full(datalen, np.nan, dtype=float)
    F2 = np.full(datalen, np.nan, dtype=float)
    F3 = np.full(datalen, np.nan, dtype=float)
    F4 = np.full(datalen, np.nan, dtype=float)

    start = 0
    finish = float(t[-1])
    increment = frameshift * 1000.0

    k = float(start)
    while k <= finish + 1e-9:
        diffs = np.abs(t - k)
        inx = int(np.argmin(diffs))
        if diffs[inx] > frameprecision * frameshift * 1000.0:
            k += increment
            continue

        n1 = int(np.rint(k / (frameshift * 1000.0))) + 1
        if n1 < 1 or n1 > datalen:
            k += increment
            continue

        F1[n1 - 1] = arr[inx, 2]   # C{3}
        F2[n1 - 1] = arr[inx, 4]   # C{5}
        F3[n1 - 1] = arr[inx, 6]   # C{7}
        F4[n1 - 1] = arr[inx, 8]   # C{9}
        k += increment

    return F1, F2, F3, F4


def praat_formants(wav_path: str, praat_exe: str, out_dir: str | None = None,
                   frame_shift: float = 0.001, window_length: float = 0.025,
                   num_formants: float = 4.0, max_formant: float = 6000.0
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """pF1-pF4：调 praatformants.praat → 解析 .fmt → (F1, F2, F3, F4) 各 1ms 网格。

    默认值来源 vs_Initialize.m L49-50 与 vs_Initialize.m L13：
        FormantsPraatNumFormants=4, FormantsPraatMaxFormantFreq=6000,
        windowsize=25 (ms) → window_length=0.025, frameshift=1 (ms) → frame_shift=0.001。
    （卡片 §2 写 num_formants=5.0 / max_formant=5500.0，与蓝本不符——
      以蓝本 4 / 6000 为准，见对照表。）
    """
    if not os.path.isfile(praat_exe):
        raise RuntimeError(f"praat.exe 不存在：{praat_exe}")
    if not os.path.isfile(_PRAAT_FMT_SCRIPT):
        raise RuntimeError(f"praatformants.praat 不存在：{_PRAAT_FMT_SCRIPT}")

    wav_path = os.path.abspath(wav_path)
    if out_dir is None:
        out_dir = os.path.dirname(wav_path)
    os.makedirs(out_dir, exist_ok=True)

    fmtfile = wav_path + ".pfmt"

    # 路径不加双引号 + 必须 --FULL-TRUST（Praat 7 视脚本写文件为危险动作）。
    # 理由同 praat_f0.py（见对照表「命令构造」节）。
    # 参数顺序严格按 praatformants.praat form（5 个）
    # 蓝本 %s %.3f %.3f %.1f %d → frameshift, windowlength, num_formants, maxFormant
    cmd = [
        praat_exe, "--FULL-TRUST", "--run", _PRAAT_FMT_SCRIPT,
        wav_path,
        f"{frame_shift:.3f}",
        f"{window_length:.3f}",
        f"{float(num_formants):.1f}",
        f"{int(round(float(max_formant)))}",
    ]

    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-16-le", errors="replace") if proc.stderr else ""
        stdout = proc.stdout.decode("utf-16-le", errors="replace") if proc.stdout else ""
        raise RuntimeError(
            f"praatformants.praat 退出码 {proc.returncode}\n"
            f"stdout: {stdout.strip()[:500]}\n"
            f"stderr: {stderr.strip()[:500]}"
        )

    if not os.path.isfile(fmtfile):
        raise RuntimeError(f"Praat 未生成输出文件：{fmtfile}")

    import wave
    with wave.open(wav_path, "rb") as wf:
        nframes = wf.getnframes()
        framerate = wf.getframerate()
    duration = nframes / float(framerate)
    datalen = int(round(duration / frame_shift)) + 1

    return _parse_praat_formant_file(
        fmtfile, frame_shift, datalen, _DEFAULT_FRAME_PRECISION,
        int(round(float(num_formants)))
    )
