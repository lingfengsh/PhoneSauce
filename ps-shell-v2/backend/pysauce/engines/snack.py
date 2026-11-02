# -*- coding: utf-8 -*-
"""Snack 引擎包装（V2-E2）。

蓝本（行为语义来源）：refs/voicesauce-v137/func_SnackPitch.m（97 行）、
      refs/voicesauce-v137/func_SnackFormants.m（99 行）。**不含其源码**。
2.0 默认以纯 Python 算法复刻（`snack_sim.py`：RAPT 基频 + LPC 共振峰），
**不依赖任何外部 Snack 二进制**；`strategy="exe"` 仅供自备 Tcl+Snack 环境对拍。

蓝本的两条调用路径：
  • **Windows 分支**（L27-29 / L29-34）：`system('Windows\\snack.exe pitch <wav> …')`
    即直接把子命令当 argv 传给 exe。
  • **Mac 分支**（L31-59 / L36-64）：**先生成一个 Tcl 脚本**，脚本内
    `package require snack` → `snack::sound s` → `s read <wav>` →
    `s pitch/formant …` → 写 `<root>.f0/.frm` → `exit`，
    再用 `wish8.4 <脚本.tcl>` 执行。

⚠ **关键发现（2026-10-26，停报）**：VS 的 `Windows/snack.exe` 经 PE 解析确认
   为 **Tcl/Tk 8.4 `wish`**（manifest: `name="Tcl.Tk.wish"`，
   `<description>Tcl/Tk windowing shell (wish)</description>`，version 8.4.0.4，
   X86，UPX 打包）。`wish` 把**第一个非选项参数当作要执行的脚本文件**，因此
   蓝本 Windows 分支的 `snack.exe pitch <wav> …` 会被解释成「运行名为 `pitch`
   的脚本」——本机实测 rc=1 立即退出、不产 `.f0`。**蓝本 PC 分支在本环境不可用。**
   结构上唯一正确的方式是 **Mac 分支范式**（生成 Tcl 脚本再交给 snack.exe 执行）。

因此本模块提供两种调用模式（`invoke_mode`）：
  - `"argv"`（默认，忠实蓝本 PC 分支）：`snack.exe pitch <wav> …`（逐字复刻）。
  - `"tcl"`（蓝本 Mac 分支范式）：生成 Tcl 脚本 → `snack.exe <脚本.tcl>`。
两模式共用同一套 `.f0`/`.frm` 解析与网格对齐。运行期验证见工程卡 V2-E2 §9。

输出解析：
    .f0  4 列：F0 / voicing-probability / RMS / xcorr（蓝本 L84 textread '%f %f %f %f'）
    .frm 8 列：F1 F2 F3 F4 B1 B2 B3 B4（蓝本 L88 textread '%f %f %f %f %f %f %f %f'）

网格映射（在调用侧 vs_ParameterEstimation.m 内，非 func_Snack*）：
    sF0/sF* 先在头部补 floor(windowsize/frameshift/2) 帧 NaN，
    再补尾部 NaN 到 data_len（pitch L687-688；formant L863-871，若更长则截断到 data_len）。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np

# 2.0 自带 vendor 目录（本文件位于 backend/pysauce/engines/）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PS_SHELL_V2 = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
_VENDOR_DIR = os.path.join(_PS_SHELL_V2, "vendor")
_DEFAULT_SNACK = os.path.join(_VENDOR_DIR, "snack.exe")

_VALID_MODES = ("argv", "tcl")

# ── Snack 引擎调用策略（2026-10-26 定案）───────────────────────────────
# 实测确认 VS 自带的 Windows/snack.exe 是 32 位 Tcl/Tk `wish`（md5 dea2b615…），
# 不认识 pitch/formant 子命令；无 Tcl 8.4 环境时连脚本都不执行（实测挂起）。
# → 该 exe 在裸机上**确定不可用**，绝不作为默认路径（会白等 subprocess 超时）。
#
# 调用策略 `strategy`：
#   "sim"（默认）→ 纯算法复刻（snack_sim：RAPT + LPC），不碰任何外部程序；
#   "exe"        → 强制走真 exe（仅当用户自备 Tcl+Snack 环境、要做严格对拍时）。
_VALID_STRATEGIES = ("sim", "exe")


def _resolve_snack_exe(snack_exe):
    exe = snack_exe if snack_exe else _DEFAULT_SNACK
    if not os.path.isfile(exe):
        raise RuntimeError(f"snack.exe 不存在：{exe}")
    return os.path.abspath(exe)


def _wav_duration(wav_path):
    import wave
    with wave.open(wav_path, "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def _pad_to_grid(seq, datalen, windowsize, frameshift):
    """复刻调用侧网格对齐：头部补 floor(windowsize/frameshift/2) 帧 NaN，再补尾到 datalen。

    蓝本：sF0 = [zeros(floor(windowsize/frameshift/2),1)*NaN; sF0];
          sF0 = [sF0; ones(data_len-length(sF0),1)*NaN];
    （zeros(N,1)*NaN == ones(N,1)*NaN == N 个 NaN，MATLAB 中 0*NaN=NaN。）
    """
    seq = np.asarray(seq, dtype=float)
    head = int(np.floor(windowsize / frameshift / 2.0))
    pad = np.full(head, np.nan, dtype=float)
    out = np.concatenate([pad, seq])
    if out.size < datalen:
        out = np.concatenate([out, np.full(datalen - out.size, np.nan, dtype=float)])
    return out


def _tcl_escape_path(path):
    """蓝本 L22-28：`[`→`\\[`、`]`→`\\]`，加双引号；PC 上 `\\`→`\\\\`（Tcl 路径转义）。"""
    p = path.replace("[", "\\[").replace("]", "\\]")
    p = '"' + p + '"'
    if os.name == "nt":
        p = p.replace("\\", "\\\\")
    return p


def _write_tcl_script(script_path, body):
    with open(script_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)


def _run_snack(exe, argv_cmd, tcl_body, invoke_mode):
    """按模式执行 snack.exe。

    invoke_mode="argv" → 直接跑 argv_cmd（蓝本 PC 分支）。
    invoke_mode="tcl"  → 把 tcl_body 写成临时脚本，跑 snack.exe <脚本>（蓝本 Mac 分支范式）。
    """
    if invoke_mode not in _VALID_MODES:
        raise ValueError(f"invoke_mode 必须是 {_VALID_MODES} 之一，得到 {invoke_mode!r}")

    if invoke_mode == "argv":
        proc = subprocess.run(argv_cmd, cwd=_VENDOR_DIR,
                              capture_output=True, timeout=120)
        return proc

    # tcl 模式：写临时脚本（放 vendor 目录，保证 snack 能找到相对资源）
    fd, script_path = tempfile.mkstemp(suffix=".tcl", dir=_VENDOR_DIR)
    os.close(fd)
    try:
        _write_tcl_script(script_path, tcl_body)
        proc = subprocess.run([exe, script_path], cwd=_VENDOR_DIR,
                              capture_output=True, timeout=120)
        return proc
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass


def snack_pitch(wav_path: str, snack_exe: str | None = None,
                frameshift: float = 0.001, windowsize: float = 0.025,
                max_f0: int = 500, min_f0: int = 40,
                invoke_mode: str = "argv", strategy: str = "sim"
                ) -> tuple[np.ndarray, np.ndarray]:
    """sF0：调 snack.exe pitch -method esps → 解析 .f0 → (f0_1ms, time_1ms)。

    snack_exe 默认 <ps-shell-v2>/vendor/snack.exe。

    默认值来源 vs_Initialize.m：windowsize=25ms→0.025、frameshift=1ms→0.001、
    maxF0=500、minF0=40（L15-21）。
    （卡片 §2 写 windowsize=0.0075 / max_f0=400 / min_f0=50，与蓝本不符——
      以蓝本为准，见对照表。）

    invoke_mode：
      - "argv"（默认）：蓝本 PC 分支，`snack.exe pitch <wav> …`。
      - "tcl"：蓝本 Mac 分支范式，生成 Tcl 脚本后 `snack.exe <脚本.tcl>`
               （对 wish 类 exe 是结构上唯一可行的方式）。

    strategy：
      - "sim"（默认）：算法复刻（`snack_sim.rapt_pitch`，RAPT），不依赖外部程序。
      - "exe"：强制真 exe（需自备 Tcl+Snack 环境；裸机上会挂起/超时）。
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(f"strategy 必须是 {_VALID_STRATEGIES} 之一，得到 {strategy!r}")
    if strategy == "sim":
        return _pitch_sim(wav_path, frameshift, windowsize, max_f0, min_f0)
    return _pitch_exe(wav_path, snack_exe, frameshift, windowsize,
                      max_f0, min_f0, invoke_mode)


def _pitch_sim(wav_path, frameshift, windowsize, max_f0, min_f0):
    from . import snack_sim
    return snack_sim.snack_pitch_sim(
        wav_path, frameshift_s=frameshift, windowsize_s=windowsize,
        max_f0=float(max_f0), min_f0=float(min_f0))


def _pitch_exe(wav_path, snack_exe, frameshift, windowsize,
               max_f0, min_f0, invoke_mode):
    """真 exe 路径（原实现，未改行为）。"""
    exe = _resolve_snack_exe(snack_exe)
    wav_path = os.path.abspath(wav_path)
    wav_tcl = _tcl_escape_path(wav_path)

    # 蓝本 L29（Windows 分支）
    argv_cmd = [
        exe, "pitch", wav_tcl,
        "-method", "esps",
        "-framelength", f"{frameshift}",
        "-windowlength", f"{windowsize}",
        "-maxpitch", f"{max_f0}",
        "-minpitch", f"{min_f0}",
    ]

    # 蓝本 L36-48（Mac 分支范式）：生成 Tcl 脚本
    root_tcl = _tcl_escape_path(
        wav_path[:-4] if wav_path.lower().endswith(".wav") else wav_path)
    tcl_body = (
        "package require snack\n"
        "snack::sound s\n"
        f"s read {wav_tcl}\n"
        f"set fd [open [file rootname {root_tcl}].f0 w]\n"
        "puts $fd [join [s pitch -method esps "
        f"-framelength {frameshift} -windowlength {windowsize} "
        f"-maxpitch {max_f0} -minpitch {min_f0}] \\n]\n"
        "close $fd\n"
        "exit\n"
    )

    proc = _run_snack(exe, argv_cmd, tcl_body, invoke_mode)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        raise RuntimeError(f"snack.exe pitch 退出码 {proc.returncode}: {err.strip()[:300]}")

    # 蓝本 L64：pitchfile = [wavfile(2:end-4) 'f0'] → <root>.f0
    root = wav_path[:-4] if wav_path.lower().endswith(".wav") else wav_path
    f0file = root + ".f0"
    if not os.path.isfile(f0file):
        raise RuntimeError(f"snack 未生成输出文件：{f0file}")

    # 蓝本 L84：textread '%f %f %f %f' → 4 列；取第 1 列 F0
    f0_raw = []
    with open(f0file, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 1:
                continue
            try:
                f0_raw.append(float(parts[0]))
            except ValueError:
                raise RuntimeError(f".f0 第 1 列非数值：{line!r}")
    f0_raw = np.asarray(f0_raw, dtype=float)

    datalen = int(round(_wav_duration(wav_path) / frameshift)) + 1
    f0 = _pad_to_grid(f0_raw, datalen, windowsize, frameshift)
    time_ms = np.arange(datalen, dtype=float) * (frameshift * 1000.0)
    return f0, time_ms


def snack_formants(wav_path: str, snack_exe: str | None = None,
                   window_length: float = 0.025, framelength: float = 0.001,
                   preemphasis: float = 0.96, lpc_order: int = 12,
                   invoke_mode: str = "argv", strategy: str = "sim"
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """sF1-sF4 + sB1-sB4：调 snack.exe formant → 解析 .frm。返回 8 个向量（各 1ms 网格）。

    默认值来源 vs_Initialize.m：windowsize=25ms、frameshift=1ms、
    preemphasis=0.96（L17）、lpcOrder=12（L18）。

    strategy 语义同 `snack_pitch`（sim 默认 / exe 强制真程序）。
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(f"strategy 必须是 {_VALID_STRATEGIES} 之一，得到 {strategy!r}")
    if strategy == "sim":
        return _formants_sim(wav_path, window_length, framelength, lpc_order)
    return _formants_exe(wav_path, snack_exe, window_length, framelength,
                         preemphasis, lpc_order, invoke_mode)


def _formants_sim(wav_path, window_length, framelength, lpc_order):
    from . import snack_sim
    return snack_sim.snack_formants_sim(
        wav_path, frameshift_s=framelength, windowsize_s=window_length,
        order=int(lpc_order))


def _formants_exe(wav_path, snack_exe, window_length, framelength,
                  preemphasis, lpc_order, invoke_mode):
    """真 exe 路径（原实现，未改行为）。"""
    exe = _resolve_snack_exe(snack_exe)
    wav_path = os.path.abspath(wav_path)
    wav_tcl = _tcl_escape_path(wav_path)

    # 蓝本 L31-34（Windows 分支）
    argv_cmd = [
        exe, "formant", wav_tcl,
        "-windowlength", f"{window_length:.3f}",
        "-framelength", f"{framelength:.3f}",
        "-windowtype", "Hamming",
        "-lpctype", "1",
        "-preemphasisfactor", f"{preemphasis:.3f}",
        "-ds_freq", "10000",
        "-lpcorder", f"{lpc_order}",
    ]

    # 蓝本 L41-52（Mac 分支范式）
    root_tcl = _tcl_escape_path(
        wav_path[:-4] if wav_path.lower().endswith(".wav") else wav_path)
    tcl_body = (
        "package require snack\n"
        "snack::sound s\n"
        f"s read {wav_tcl}\n"
        f"set fd [open [file rootname {root_tcl}].frm w]\n"
        "puts $fd [join [s formant "
        f"-windowlength {window_length:.3f} -framelength {framelength:.3f} "
        f"-windowtype 1 -lpctype 1 -preemphasisfactor {preemphasis:.3f} "
        f"-ds_freq 10000 -lpcorder {lpc_order}] \\n]\n"
        "close $fd\n"
        "exit\n"
    )

    proc = _run_snack(exe, argv_cmd, tcl_body, invoke_mode)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        raise RuntimeError(f"snack.exe formant 退出码 {proc.returncode}: {err.strip()[:300]}")

    # 蓝本 L23：formantfile = [wavfile(1:end-3) 'frm'] → <root>.frm
    root = wav_path[:-4] if wav_path.lower().endswith(".wav") else wav_path
    frmfile = root + ".frm"
    if not os.path.isfile(frmfile):
        raise RuntimeError(f"snack 未生成输出文件：{frmfile}")

    # 蓝本 L88：textread '%f %f %f %f %f %f %f %f' → 8 列 F1..F4,B1..B4
    rows = []
    with open(frmfile, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 8:
                raise RuntimeError(f".frm 列数不足 8：{line!r}")
            try:
                rows.append([float(x) for x in parts[:8]])
            except ValueError:
                raise RuntimeError(f".frm 含非数值：{line!r}")
    arr = np.asarray(rows, dtype=float) if rows else np.zeros((0, 8))

    datalen = int(round(_wav_duration(wav_path) / framelength)) + 1

    def _col(i):
        return _pad_to_grid(arr[:, i], datalen, window_length, framelength) if arr.size else \
            np.full(datalen, np.nan)

    F1, F2, F3, F4 = _col(0), _col(1), _col(2), _col(3)
    B1, B2, B3, B4 = _col(4), _col(5), _col(6), _col(7)
    return F1, F2, F3, F4, B1, B2, B3, B4
