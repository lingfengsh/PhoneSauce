# -*- coding: utf-8 -*-
"""shrp.m / func_GetSHRP.m → Python 适配层（vendored opensauce-python 表达基底）。

蓝本（行为唯一权威）：`refs/voicesauce-v137/shrp.m`（476 行，Sun 2002 SHR 算法）
                      + `refs/voicesauce-v137/func_GetSHRP.m`（133 行，包装层）。
表达基底（合规定案）：**opensauce-python**（Apache-2.0）`shrp.py` 文件级 vendored
                      → `pysauce/_vendor/osp_shrp.py`（见其文件头 Modified 清单）。

本模块只做两件事：
  1. `shrp(...)`  —— 转发 vendored `shrp`，参数/返回值对齐卡 §2 签名。
  2. `get_shrp(...)` —— 复刻 `func_GetSHRP.m` 的 1ms 网格映射（L106–133）。

v1.37 蓝本仲裁结论（详见工程卡 §8）：
  - `shrp.m` 与 vendored 实现数值行为**一致**（逐段核对 476 行）：
      * L93-94 去 DC + 归一化；L99-104 阈值；L106-110 帧网格（`(n-1)*timestep+len/2`）
        与 vendored `n*timestep+len/2`（n 从 0 起）等价；
      * L118-144 频率/对数刻度、startpos/endpos 边界钳位**逐值一致**（已实测）；
      * L272-278 shshift 奇偶求和：vendored 名称互换且 difference 取反，
        **符号相消 + 末行落在搜索区外** → 数值等价（已实测 minf0=50/75/120 均 0 差异）；
      * L305-325 twomax 峰搜索等价；
      * L367-378 toframes：vendored `start<1`→置 0（0-based），等价于蓝本 `start<1`→置 1（1-based）；
      * L455-477 window 与 vendored `window_funcs` 逐式一致（hamm = .54-.46cos(2πn/(N-1))）。
  - 唯一**语义差异在包装层**（见下）：
      * 蓝本 L130-131 写 `F0(n+1)`/`SHR(n+1)`，n=round(k/frameshift)+1（1-based）
        == 0-based 索引 round(k/frameshift)+1；vendored `shr_pitch` 写 `F0[n]`，
        n=round(k/frameshift)+1（0-based）→ **等价**（已推导）。
      * vendored `shr_pitch` 的 `datalen += 1`（自承 MATLAB 多产 1 点）与蓝本一致保留。
      * vendored `frame_precision=None` 默认会崩（`None*frame_shift`）→ 适配层必须传具体值；
        VS 默认 `frame_precision=1`（vs_Initialize.m L32）。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

from ._vendor import osp_shrp as _osp


def shrp(y: np.ndarray, fs: int, f0min: float = 50.0, f0max: float = 500.0,
         frame_length: int = 40, timestep: int = 10,
         haste: float = 2.0) -> "tuple[np.ndarray, np.ndarray, np.ndarray, int]":
    """shrp.m 顶层。返回 (f0_time, f0_value, shr_value, num_voiced)。

    f0_time: 秒；f0_value/shr_value 与之等长；无效/无声帧 NaN。

    注：卡 §2 签名的 `haste` 参数在蓝本/ vendored 中**无对应**（蓝本无此参数）；
        此处接受以匹配签名，实际忽略（保留位置，供未来可能的时域重采样使用）。
        返回值第 4 项按卡 §2 为 `num_voiced`（有声帧计数），非 vendored 的 f0_candidates。
    """
    y = np.asarray(y, dtype=np.float64)
    # 转发 vendored 实现（F0MinMax 用 (f0min, f0max)）
    f0_time, f0_value, shr_value, _f0_candidates = _osp.shrp(
        y, fs, F0MinMax=(f0min, f0max),
        frame_length=frame_length, timestep=timestep)

    # num_voiced：f0_value > 0 的帧数（vendored 无声帧 f0=0）
    num_voiced = int(np.count_nonzero(f0_value > 0))

    # 无效/无声帧置 NaN（vendored 用 0 表示无声；卡 §2 要求 NaN）
    f0_value = np.asarray(f0_value, dtype=np.float64)
    shr_value = np.asarray(shr_value, dtype=np.float64)
    silent = f0_value <= 0
    f0_out = f0_value.copy()
    shr_out = shr_value.copy()
    f0_out[silent] = np.nan
    shr_out[silent] = np.nan

    # f0_time 单位：蓝本/vendored 均为毫秒 → 卡 §2 要求秒
    f0_time_sec = np.asarray(f0_time, dtype=np.float64) / 1000.0

    return f0_time_sec, f0_out, shr_out, num_voiced


def get_shrp(y: np.ndarray, fs: int, f0: np.ndarray | None,
             frameshift_ms: float = 1.0) -> "tuple[np.ndarray, np.ndarray]":
    """[SHR, shrF0] = func_GetSHRP(y, Fs, vars, data_len) 包装。

    对齐蓝本 func_GetSHRP：
      - L28-43 取 vars：SHRmin/SHRmax/SHRThreshold/windowsize/frameshift/frame_precision
        → 2.0 默认取 vs_Initialize.m 出厂值（SHRmin=40, SHRmax=500, SHRThreshold=0.4,
          windowsize=25, frame_precision=1），frameshift 由入参给。
      - L95-102 调用 shrp（≤10s 单块；>10s 分块，2.0 简化：整段调用，见 §8 差异记录）。
      - L106-133 后处理：`t=round(f0_time)`（**round-half-away-from-zero**）→
        对 `k=0,frameshift,2*frameshift,...` 找最近 `t`，若 |t-k| > frame_precision*frameshift
        则跳过；写 `F0[n]`，n=round(k/frameshift)+1（0-based）。
      - datalen = len(f0)（帧网格长度）；蓝本额外 +1 由适配层显式体现（见下）。

    返回 (shr, shrf0)，均与 f0 等长（datalen）；无对应值处 NaN。
    """
    y = np.asarray(y, dtype=np.float64)
    if f0 is None:
        raise ValueError("get_shrp 需要 f0 帧网格（2.0 不支持 None）")
    f0 = np.asarray(f0, dtype=np.float64)
    datalen = len(f0)

    # VS 出厂设置（vs_Initialize.m L32/63/64/65；windowsize/frameshift 亦为 VS 默认）
    shr_min = 40.0
    shr_max = 500.0
    shr_threshold = 0.4
    windowsize = 25.0          # ms
    frame_precision = 1        # 帧
    ceiling = 1250.0
    frame_shift = float(frameshift_ms)

    # L102: 调用 shrp（整段；蓝本 >10s 分块逻辑 2.0 未实现，见 §8）
    f0_time, f0_value, shr_value, _ = _osp.shrp(
        y, fs, F0MinMax=(shr_min, shr_max),
        frame_length=windowsize, timestep=frame_shift,
        SHR_Threshold=shr_threshold, ceiling=ceiling)

    # L109-110: F0 = zeros(datalen,1)*NaN; SHR = zeros(datalen,1)*NaN
    #   注：vendored shr_pitch 用 datalen+1（自承 MATLAB 多 1 点）；蓝本 F0 长度为 datalen。
    #   此处按蓝本 = datalen 严格实现。
    out_shr = np.full(datalen, np.nan, dtype=np.float64)
    out_f0 = np.full(datalen, np.nan, dtype=np.float64)

    if len(f0_time) == 0:
        return out_shr, out_f0

    # L112: t = round(f0_time)  ← round-half-away-from-zero（MATLAB round）
    t = _round_half_away_from_zero(f0_time)

    # L114-133: 网格映射
    #   finish = t(end); increment = frameshift
    finish = t[-1]
    increment = frame_shift
    # 蓝本 `for k=start:increment:finish`（start=0）→ 含 finish
    # 用 while 精确复刻（避免 arange 排除终点）
    k = 0.0
    while k <= finish + 1e-9:
        # L120: [val,inx] = min(abs(t - k))
        dabs = np.abs(t - k)
        inx = int(np.argmin(dabs))
        # L121: if (abs(t(inx)-k) > frame_precision*frameshift) continue
        if dabs[inx] > frame_precision * frame_shift:
            k += increment
            continue
        # L125: n = round(k/frameshift)+1
        n = int(_round_half_away_from_zero(k / frame_shift)) + 1
        # L126: if (n<1 || n>datalen) continue   ← 1-based
        #   蓝本写 F0(n+1) → 1-based 索引 n+1 → 0-based 索引 n
        idx = n
        if idx < 0 or idx >= datalen:
            k += increment
            continue
        # L130-131: F0(n+1)=f0_value(inx); SHR(n+1)=SHR_value(inx)
        out_f0[idx] = f0_value[inx]
        out_shr[idx] = shr_value[inx]
        k += increment

    # 无声帧（vendored f0=0）→ NaN
    silent = out_f0 <= 0
    out_f0[silent] = np.nan

    return out_shr, out_f0


def _round_half_away_from_zero(x: np.ndarray) -> np.ndarray:
    """MATLAB round（远离零）逐元素；复刻 vendored helpers.round_half_away_from_zero。"""
    return np.sign(x) * np.floor(np.abs(x) + 0.5)
