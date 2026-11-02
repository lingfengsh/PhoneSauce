# -*- coding: utf-8 -*-
"""func_getSoE.m → Python 复刻（whole / block 两分支）。

蓝本：refs/voicesauce-v137/func_getSoE.m（324 行），Soo Jin Park, UCLA SPAPL 2015。
参考文献：Murty & Yegnanarayana 2008（epoch extraction）；Yegnanarayana & Murty 2009。
语义：SoE（Strength of Excitation）——信号重采样 10 kHz → 零频滤波 zff 得 excitation 信号 z
      → 过零（正→负）点即 epoch → 逐 epoch 取 z 的负二阶差分得 soe → 映射回 1 ms 帧网格。

本卡两处必停报项（见模块末与工程卡 §8）：
  ① zff 的 alpha 与"反向滤波"细节 —— 已读原文确认：**无 flip/fliplr**，纯两次前向 lfilter
     + 两次 RemoveTrend；卡 §3 关于 L214-218 反向处理的猜测**不成立**。
  ② resample 等价策略 —— 采用 scipy.signal.resample_poly（见 §8.3 差异说明）。

翻译约定（00-总纲 R1–R10）：
- MATLAB 1-based → 0-based；闭区间 y(a:b) → y[a-1:b]；
- filter(b, a, x) → scipy.signal.lfilter(b, a, x)（b 前 a 后，与 MATLAB 一致）；
- round → matlang.mround；所有 continue 分支逐条保留。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter, resample_poly

from . import matlang as M


def zff(x: np.ndarray, n0: float) -> np.ndarray:
    """z = zff(x, n0)（蓝本 L201–223）。零频滤波 excitation 信号。

    流程（**无反向滤波**）：
      alpha = .999
      x = x - x(1)                              去直流（减首样本）
      s = filter([1 -1], 1, x)                  一阶差分
      u = filter(1, [1 -2α α²], s)              第 1 次零频滤波（双极点低通）
      v = RemoveTrend(u, round(n0/1.5))         去趋势
      y = filter(1, [1 -2α α²], v)              第 2 次零频滤波
      z = RemoveTrend(y, round(n0/1.5))         去趋势
    """
    x = np.asarray(x, dtype=np.float64)

    # MT-L205: alpha = .999
    alpha = 0.999

    # MT-L209: x = x - x(1)
    x = x - x[0]

    # MT-L210: s = filter([1 -1], 1, x)
    s = lfilter([1.0, -1.0], [1.0], x)

    # MT-L213: u = filter(1, [1 -2*alpha alpha^2], s)
    den = [1.0, -2.0 * alpha, alpha ** 2]
    u = lfilter([1.0], den, s)

    # MT-L215: v = RemoveTrend(u, round(n0/1.5))
    v = remove_trend(u, M.mround(n0 / 1.5))

    # MT-L218: y = filter(1, [1 -2*alpha alpha^2], v)
    y = lfilter([1.0], den, v)

    # MT-L220: z = RemoveTrend(y, round(n0/1.5))
    z = remove_trend(y, M.mround(n0 / 1.5))

    return z


def remove_trend(x: np.ndarray, n: float) -> np.ndarray:
    """y = RemoveTrend(x, N)（蓝本 L267–288）。滑动均值去趋势，边缘用累积均值补齐。"""
    x = np.asarray(x, dtype=np.float64)

    # MT-L269-272: if round(N)~=N → N = round(N)
    if M.mround(n) != n:
        n = M.mround(n)
    n = int(n)

    # MT-L274-275: width = 2*N+1; L = length(x)
    width = 2 * n + 1
    length = len(x)

    # MT-L278: c = filter(ones(width,1)/width, 1, x)   滑动均值
    c = lfilter(np.ones(width) / width, [1.0], x)

    # MT-L279-281: 边缘修正
    #   cbegin = cumsum(x(1:width-2)); cbegin = cbegin(1:2:end)./(1:2:(width-2))'
    #   → 0-based: x[:width-2]（width-2 个）；[0::2]；除数 1,3,…,width-2
    cbegin = np.cumsum(x[: width - 2])
    cbegin = cbegin[0::2] / np.arange(1, width - 1, 2)
    #   cend = cumsum(x(L:-1:L-width+3)); cend = cend(end:-2:1)./(width-2:-2:1)'
    #   MATLAB x(L:-1:L-width+3) = 1-based L,L-1,…,L-width+3（共 width-2 个）
    #   → 0-based 起点 L-1，终点 (L-width+3)-1 = L-width+2，切片 [L-1 : L-width+1 : -1]
    cend = np.cumsum(x[length - 1: length - width + 1: -1])
    cend = cend[::-1][0::2] / np.arange(width - 2, 0, -2)

    # MT-L282: c = [cbegin; c(width:end); cend]
    #   MATLAB c(width:end) 含端点 → 0-based c[width-1:]
    c = np.concatenate([cbegin, c[width - 1:], cend])

    # MT-L285: y = x - c
    y = x - c

    return y


def get_delta(x: np.ndarray, d: int) -> np.ndarray:
    """dx = get_delta(x, D)（蓝本 L291–311）。HTK 式 delta 系数。

    x: [FEATURE_DIMENSION, FRM] 矩阵（蓝本语义）。为便于 1-D 信号调用，
    本实现接受 1-D 输入并按**帧向量**处理（输出与输入等长、同维数）——
    这与蓝本 `dx = NaN*ones(size(x))` 的"输出同尺寸"语义一致
    （蓝本内部调用 `get_delta(z.',2)`，z.' 为行向量）。
    D: delta 窗（2D+1 帧参与）。
    边界（nf<=D 或 nf>=size(x,2)-D）退化为简单一阶差分；更远处保持 NaN。
    """
    x = np.asarray(x, dtype=np.float64)
    was_1d = x.ndim == 1
    if was_1d:
        x = x.reshape(1, -1)

    # MT-L302: dx = NaN*ones(size(x))
    dx = np.full(x.shape, np.nan, dtype=np.float64)

    n_frames = x.shape[1]
    for nf in range(1, n_frames + 1):
        # MT-L306-312: try 内求 numer/denom（MATLAB 用 try/catch 处理越界）
        ok = True
        numer = np.zeros(x.shape[0], dtype=np.float64)
        denom = 0.0
        for theta in range(1, d + 1):
            lo = nf - theta          # MATLAB 1-based nf-theta → 0-based nf-1-theta
            hi = nf + theta
            if lo < 1 or hi > n_frames:
                ok = False
                break
            # MT-L311: numer = numer + theta*(x(:,nf+theta)-x(:,nf-theta))
            numer = numer + theta * (x[:, hi - 1] - x[:, lo - 1])
            # MT-L312: denom = denom + 2*theta^2
            denom = denom + 2 * theta ** 2

        if ok:
            # MT-L314: dx(:,nf) = numer/denom
            dx[:, nf - 1] = numer / denom
        else:
            # MT-L316-321: 边界退化
            if nf <= d:
                # dx(:,nf) = x(:,nf+1)-x(:,nf)
                dx[:, nf - 1] = x[:, nf] - x[:, nf - 1]
            elif nf >= n_frames - d:
                # dx(:,nf) = x(:,nf)-x(:,nf-1)
                dx[:, nf - 1] = x[:, nf - 1] - x[:, nf - 2]
            # 其余保持 NaN（蓝本 catch 未赋值）

    return dx.ravel() if was_1d else dx


def get_soe(snd: np.ndarray, orig_fs: int, method: str, f0: np.ndarray,
            window_size_ms: float = 40.0, frameshift_ms: float = 1.0
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """[epoch, soe, z] = func_getSoE(snd, data_len, origSndFs, METHOD, F0, vars)。

    返回 (epoch, soe, z)：epoch/soe 为 1ms 帧网格上的向量（无效帧 NaN/0），
    z 为 10kHz 网格上的零频滤波信号。method: 'whole' | 'block'。
    data_len = len(f0)（蓝本第一参 data_len 与 F0 等长，映射目标帧数）。
    """
    snd = np.asarray(snd, dtype=np.float64)
    f0 = np.asarray(f0, dtype=np.float64)
    data_len = len(f0)

    # MT-L42-44: if vars.frameshift<10 warning → 2.0 无 GUI，忽略（仅注释保留）

    # MT-L47-48: Fs = 10000; snd = resample(snd, Fs, origSndFs)
    fs = 10000
    snd = resample_poly(snd, fs, int(orig_fs))

    # ⚠ 复刻修正：STRAIGHT 等引擎在未发声段产出 F0=0（蓝本假设 F0 无 0/Inf）。
    #   Fs/F0=Inf 会传入 zff → RemoveTrend(round(Inf)) 在 Python 抛
    #   "cannot convert float infinity to integer"。故统计前先过滤非有限/非正 F0；
    #   无有效帧时报错（被 engine.run_file 捕获为 warning，不崩批量）。
    f0_valid = f0[np.isfinite(f0) & (f0 > 0)]

    if method == "whole":
        # MT-L52-57: whole 分支
        #   F0_nonans = F0(~isnan(F0)); meanN0 = mean(Fs./F0_nonans)
        if not f0_valid.size:
            raise ValueError("SoE 跳过：F0 无有效帧（全为 NaN/0/Inf）")
        mean_n0 = float(np.mean(fs / f0_valid))
        #   z = zff(snd, meanN0)
        z = zff(snd, mean_n0)

    elif method == "block":
        # MT-L61-130: block 分支
        win_sec = window_size_ms / 1000.0
        step_sec = frameshift_ms / 1000.0
        window = int(win_sec * fs)
        step = int(step_sec * fs)

        # MT-L73: Nfrm = floor((length(snd)+WINDOW)/Fs/stepSec)
        n_frm = int(np.floor((len(snd) + window) / fs / step_sec))

        # MT-L76: z = zeros(size(snd))
        z = np.zeros(len(snd), dtype=np.float64)

        for nf in range(1, n_frm + 1):
            # MT-L78: ks = round((nf-1)*STEP)
            ks = int(M.mround((nf - 1) * step))

            # MT-L79-81: if (ks<=0 || ks>length(snd)) continue
            if ks <= 0 or ks > len(snd):
                continue

            # MT-L83-89: currF0 = F0(nf); if isnan → mean(F0_nonans)
            if nf <= len(f0):
                curr_f0 = f0[nf - 1]
            else:
                curr_f0 = np.nan
            # ⚠ 复刻修正：NaN/Inf/0 一律回退到有效帧均值（蓝本仅 NaN 分支；
            #   0 帧会让 currN0=Inf 在 zff 内崩溃）。无有效帧则跳过该窗。
            if not np.isfinite(curr_f0) or curr_f0 <= 0:
                if not f0_valid.size:
                    continue
                curr_f0 = float(np.mean(f0_valid))

            # MT-L91: currN0 = Fs/currF0
            curr_n0 = fs / curr_f0

            # MT-L94-99: winStart = round(ks - WINDOW/2)
            #            if winStart<=0 || winStart+WINDOW-1>length(snd) continue
            win_start = int(M.mround(ks - window / 2.0))
            if win_start <= 0 or win_start + window - 1 > len(snd):
                continue
            # winSnd = snd(winStart:winStart+WINDOW-1)
            win_snd = snd[win_start - 1: win_start - 1 + window]

            # MT-L106: x = winSnd .* hamming(length(winSnd), 'periodic')
            #   ⚠ MATLAB hamming(L,'periodic') = 0.54-0.46cos(2πn/L), n=0..L-1
            #     ≠ numpy 对称式 np.hamming(L)（= 0.54-0.46cos(2πn/(L-1))）。
            #     periodic 式等价于 np.hamming(L+1)[:L]（实测逐点一致，见卡 §8）。
            x = win_snd * np.hamming(len(win_snd) + 1)[: len(win_snd)]

            # MT-L109: currZ = zff(x, currN0)
            curr_z = zff(x, curr_n0)

            # MT-L110: z(winStart:winStart+WINDOW-1) += currZ
            z[win_start - 1: win_start - 1 + window] += curr_z

    else:
        # MT-L132-133: else error('invalid method')
        raise ValueError("invalid method")

    # MT-L136: z = 0.95*z/max(abs(z))
    z = 0.95 * z / np.max(np.abs(z))

    # ----- epoch detection (MT-L139-144) -----
    # MT-L140: z1 = [NaN; z(1:end-1)]   1 样本延迟
    z1 = np.concatenate([[np.nan], z[:-1]])
    # MT-L141: tf = z1>0 & z<=0         正→负过零点
    #   ⚠ NaN>0 为 False（numpy 与 MATLAB 一致）→ 首样本必为 False
    tf = (z1 > 0) & (z <= 0)

    # MT-L143: diff = -get_delta(z.',2)  负二阶差分
    #   get_delta 期望 [DIM, FRM]；z 为 1-D → 视作 [1, N]
    diff_ = -get_delta(z, 2).ravel()

    # ------ fit into frames (MT-L151-167) ------
    # MT-L151: epoch = zeros(data_len,1)
    epoch = np.zeros(data_len, dtype=np.float64)
    # MT-L152: soe = NaN*ones(data_len,1)
    soe = np.full(data_len, np.nan, dtype=np.float64)

    for smp_idx in range(1, len(z) + 1):
        if tf[smp_idx - 1]:
            # MT-L156: frm_idx = round(smpIdx/Fs/(vars.frameshift/1000))
            frm_idx = int(M.mround(smp_idx / fs / (frameshift_ms / 1000.0)))
            # MT-L158-160: if frm_idx<1 || frm_idx>data_len continue
            if frm_idx < 1 or frm_idx > data_len:
                continue
            # MT-L162-163: epoch(frm_idx)=1; soe(frm_idx)=diff(smpIdx)
            epoch[frm_idx - 1] = 1
            soe[frm_idx - 1] = diff_[smp_idx - 1]

    # MT-L168: epoch = logical(epoch)
    epoch = epoch.astype(bool)

    return epoch, soe, z
