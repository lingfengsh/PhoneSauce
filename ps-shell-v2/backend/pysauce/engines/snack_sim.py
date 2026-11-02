# -*- coding: utf-8 -*-
"""Snack ESPS pitch 的纯 Python 复刻（RAPT，Talkin 1995）。

## 为什么需要这个模块

蓝本 `func_SnackPitch.m` / `func_SnackFormants.m` 走的是 VS 自带的
`Windows/snack.exe`。实测确认（2026-10-26）：

* `vendor/snack.exe` 与 `refs/voicesauce-v137/Windows/snack.exe` **md5 完全相同**
  （`dea2b615…`），PE manifest = `Tcl.Tk.wish`，32 位，且**只有一个 PE**
  （libsnack.dll 未内嵌）。
* 它是 **Tcl/Tk `wish`**，不认识 `pitch`/`formant` 子命令；传脚本参数也不执行
  （`puts` 无输出、直接挂起）。VS 作者机器上之所以能跑，是因为**环境里另装了
  完整 Tcl+Snack**，而不是靠这个 exe。

→ 该 exe 在裸机（无 Tcl 8.4 环境、64 位 Python）上**不可用**。本模块以**纯算法**
复刻 Snack 的两项测量，避免外部依赖。

## 复刻的算法（均为公开论文算法，独立实现）

* **sF0 / sV / sRMS** = Snack `pitch -method esps` → **RAPT**
  （Talkin, D., "A Robust Algorithm for Pitch Tracking (RAPT)", in
  *Speech Coding and Synthesis*, Elsevier, 1995）。
  第三方独立实现佐证：superassp 的 `trk_pitch_snack`（dp_f0）输出
  f0 / voicing / rms / acpeak 四轨，与蓝本 `.f0` 的 4 列一一对应。
* **sF1–sF4 / sB1–sB4** = Snack `formant -lpctype 1` → **LPC 自相关法**
  （教科书算法：Hamming 窗 → 预加重 → 降采样 → 自相关 → Levinson-Durbin
  → 求根 → 极点频率/带宽）。

## 参数（照蓝本）

* pitch：`-windowlength 0.025 -framelength 0.001 -maxpitch 500 -minpitch 40`
  （`vs_Initialize.m` L15-21：windowsize=25ms、frameshift=1ms、maxF0=500、minF0=40）
* formant：`-windowlength 0.025 -framelength 0.001 -windowtype Hamming
  -lpctype 1 -preemphasisfactor 0.96 -ds_freq 10000 -lpcorder 12`
  （`func_SnackFormants.m` L31-32；preemphasis/lpcOrder 来自 `vs_Initialize.m` L17-18）

## ⚠ 诚实声明

本模块是**算法等价复刻**，不是真 Snack 二进制。数值**不可能与真 Snack 逐位相同**
（DP 代价函数系数、边界帧处理、内部滤波器细节均有实现自由度）。用途是让
"Snack 引擎"在无 Tcl 环境下可用；引用其值时须标注"RAPT/LPC 复刻"。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

# ── 蓝本默认参数 ─────────────────────────────────────────────────────────
FRAMESHIFT_S = 0.001      # 1 ms（vs_Initialize.m L16）
WINDOWSIZE_S = 0.025      # 25 ms（L15）
MAX_F0 = 500              # L20
MIN_F0 = 40               # L21
PREEMPHASIS = 0.96        # L17
LPC_ORDER = 12            # L18
DS_FREQ = 10000           # func_SnackFormants.m L31（共振峰分析降采样目标）

# ── RAPT 内部常数（Talkin 1995）─────────────────────────────────────────
_DECIMATE_TARGET = 1000.0   # 粗搜索的目标采样率（Hz）
_NCCF_CANDIDATES = 20       # 每帧保留的候选峰数（RAPT 默认 20）
_VOICING_THRESH = 0.30      # NCCF 峰值 > 阈值判为浊音候选
_DP_TRANS_COST = 0.10       # 帧间 F0 变化惩罚系数
_DP_OCTAVE_COST = 0.35      # 倍频/半频惩罚系数
_DP_VOICED_UNVOICED = 0.14  # 清浊切换代价
_SUBHARM_PENALTY = 0.30     # 次谐波（k·T）每级扣分（Talkin 1995 §3）


# ══════════════════════════════════════════════════════════════════════════
# 预处理
# ══════════════════════════════════════════════════════════════════════════
def _preprocess(y: np.ndarray) -> np.ndarray:
    """RAPT 预处理：去直流 + 一阶预加重（Talkin 1995 §2）。"""
    y = np.asarray(y, dtype=float)
    if y.size == 0:
        return y
    y = y - np.mean(y)
    if y.size > 1:
        y = np.append(y[0], y[1:] - 0.96 * y[:-1])
    return y


def _decimate_for_coarse(y: np.ndarray, fs: float):
    """降采样到 ~1 kHz 做粗搜索。返回 (y_dec, fs_dec, factor)。"""
    factor = max(1, int(round(fs / _DECIMATE_TARGET)))
    if factor <= 1:
        return y.copy(), float(fs), 1
    n = (y.size // factor) * factor
    y2 = y[:n].reshape(-1, factor).mean(axis=1)   # 简单块平均抗混叠
    return y2, fs / factor, factor


# ══════════════════════════════════════════════════════════════════════════
# NCCF（归一化互相关）
# ══════════════════════════════════════════════════════════════════════════
def _nccf_frame(y: np.ndarray, start: int, win_len: int, lag: int) -> float:
    """单点 NCCF：用前向窗与滞后窗的归一化互相关（Talkin 1995 式 2-3）。

    NCCF(τ) = Σ x[n]·x[n+τ] / sqrt( Σ x[n]² · Σ x[n+τ]² )
    """
    a = y[start:start + win_len]
    b = y[start + lag:start + lag + win_len]
    if a.size < win_len or b.size < win_len:
        return 0.0
    denom = np.sqrt(np.dot(a, a) * np.dot(b, b))
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


def _nccf_over_lags(y, start, win_len, lag_min, lag_max):
    """给定帧，对 lag ∈ [lag_min, lag_max] 逐点算 NCCF，返回 (lags, vals)。"""
    lags = np.arange(lag_min, lag_max + 1)
    vals = np.array([_nccf_frame(y, start, win_len, int(l)) for l in lags], dtype=float)
    return lags, vals


def _parabolic_peak(vals, idx):
    """抛物线插值精化峰位：返回 (峰位置偏移, 峰高度)。"""
    if idx <= 0 or idx >= vals.size - 1:
        return float(idx), float(vals[idx])
    y0, y1, y2 = vals[idx - 1], vals[idx], vals[idx + 1]
    denom = (y0 - 2.0 * y1 + y2)
    if abs(denom) < 1e-12:
        return float(idx), float(y1)
    delta = 0.5 * (y0 - y2) / denom
    delta = float(np.clip(delta, -1.0, 1.0))
    peak = y1 - 0.25 * (y0 - y2) * delta
    return float(idx) + delta, float(peak)


def _find_candidates(vals, lags, max_cand):
    """找 NCCF 的局部极大值，按高度降序取前 max_cand 个。"""
    cands = []
    for i in range(1, vals.size - 1):
        if vals[i] >= vals[i - 1] and vals[i] > vals[i + 1] and vals[i] > 0:
            pos, h = _parabolic_peak(vals, i)
            lag = lags[0] + pos
            cands.append((float(lag), float(h)))
    cands.sort(key=lambda t: t[1], reverse=True)
    return cands[:max_cand]


def _suppress_subharmonics(cands):
    """次谐波抑制（RAPT 核心步骤，Talkin 1995 §3）。

    周期信号在 k·T（k=1,2,3…）处 NCCF 都≈1，无法靠峰高区分。RAPT 的策略是
    **优先最短周期**：若某个 lag 近似为另一个更小 lag 的整数倍（且在容差内），
    则把大 lag 候选的分数按倍频数惩罚——这样除非小 lag 峰本身不合格，
    否则不会锁到次谐波（50 Hz 而真值 200 Hz）。

    返回重排后的候选 [(lag, score)]，score 已含次谐波惩罚。
    """
    if not cands:
        return []
    out = []
    for lag, h in cands:
        penalty = 0.0
        for lag2, h2 in cands:
            if lag2 >= lag * 0.9:
                continue
            ratio = lag / lag2
            nearest = round(ratio)
            if nearest >= 2 and abs(ratio - nearest) < 0.10 and h2 >= 0.6 * h:
                # lag 是 lag2 的整数倍 → 判为次谐波，按倍频数扣分
                penalty += _SUBHARM_PENALTY * (nearest - 1)
        out.append((float(lag), float(h) - penalty))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


# ══════════════════════════════════════════════════════════════════════════
# 主入口：RAPT F0
# ══════════════════════════════════════════════════════════════════════════
def rapt_pitch(y: np.ndarray, fs: float,
               frameshift_s: float = FRAMESHIFT_S,
               windowsize_s: float = WINDOWSIZE_S,
               max_f0: float = MAX_F0, min_f0: float = MIN_F0,
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """RAPT 基频跟踪。返回 (f0, voicing, rms)，长度 = 帧数（含边界帧）。

    f0 单位 Hz（清音帧 = 0），voicing ∈ [0,1]，rms 为线性幅度。
    帧网格：第 k 帧中心时间 = k·frameshift_s（与 Snack ESPS 的 half-window 偏移
    在调用侧统一处理，见 `snack_pitch_sim`）。
    """
    y = _preprocess(y)
    n_samples = y.size
    hop = max(1, int(round(frameshift_s * fs)))
    win = max(2, int(round(windowsize_s * fs)))
    if n_samples < win:
        return np.zeros(0), np.zeros(0), np.zeros(0)

    # 帧数：覆盖到最后一帧完整窗
    n_frames = (n_samples - win) // hop + 1

    # ── 粗搜索（低采样率）─────────────────────────────────────────────
    y_dec, fs_dec, factor = _decimate_for_coarse(y, fs)
    win_dec = max(2, int(round(windowsize_s * fs_dec)))
    hop_dec = max(1, int(round(frameshift_s * fs_dec)))
    lag_min_dec = max(1, int(np.floor(fs_dec / max_f0)))
    lag_max_dec = max(lag_min_dec + 1, int(np.ceil(fs_dec / min_f0)))

    # ── 精搜索（原采样率）────────────────────────────────────────────
    lag_min = max(1, int(np.floor(fs / max_f0)))
    lag_max = max(lag_min + 1, int(np.ceil(fs / min_f0)))

    f0 = np.zeros(n_frames, dtype=float)
    voicing = np.zeros(n_frames, dtype=float)
    rms = np.zeros(n_frames, dtype=float)
    cand_list: list[list[tuple[float, float]]] = []   # 每帧候选 [(f0_hz, nccf)]

    for k in range(n_frames):
        s = k * hop
        seg = y[s:s + win]
        rms[k] = float(np.sqrt(np.mean(seg * seg))) if seg.size else 0.0

        # 粗搜索
        s_dec = int(round(s / factor))
        if s_dec + win_dec + lag_max_dec <= y_dec.size:
            _lags_d, vals_d = _nccf_over_lags(y_dec, s_dec, win_dec,
                                              lag_min_dec, lag_max_dec)
            rough = _find_candidates(vals_d, _lags_d, _NCCF_CANDIDATES)
        else:
            rough = []

        # 精搜索：在每个粗峰邻域精算 NCCF
        cands = []
        for lag_d, _h in rough:
            lag_c = lag_d * factor
            lo = max(lag_min, int(lag_c) - factor)
            hi = min(lag_max, int(lag_c) + factor)
            if hi <= lo:
                continue
            if s + win + hi > n_samples:
                continue
            _lags_f, vals_f = _nccf_over_lags(y, s, win, lo, hi)
            if vals_f.size == 0:
                continue
            i = int(np.argmax(vals_f))
            pos, h = _parabolic_peak(vals_f, i)
            lag_f = _lags_f[0] + pos
            if lag_f <= 0:
                continue
            cands.append((float(fs / lag_f), float(h)))
        # 去重（相近 F0 合并取高者）+ 次谐波抑制
        cands.sort(key=lambda t: -t[1])
        merged = []
        for f, h in cands:
            if all(abs(f - g) / max(f, 1.0) > 0.05 for g, _ in merged):
                merged.append((f, h))
        # 转成 (lag, score) 做次谐波抑制后再转回 (f0, score)
        by_lag = [(fs / f, h) for f, h in merged if f > 0]
        by_lag = _suppress_subharmonics(by_lag)
        merged = [(float(fs / lag), float(score)) for lag, score in by_lag]
        cand_list.append(merged)

    # ── 动态规划回溯 ────────────────────────────────────────────────
    _dp_track(cand_list, f0, voicing)

    # 与粗峰高度挂钩的浊音概率（NCCF 峰值本身即 voicing 的代理）
    for k, cands in enumerate(cand_list):
        if cands:
            voicing[k] = min(1.0, max(0.0, cands[0][1]))
    # 未选定帧（f0=0）的 voicing 归零
    voicing[f0 <= 0] = 0.0

    return f0, voicing, rms


def _dp_track(cand_list, f0, voicing):
    """RAPT 动态规划：在候选网格上求总代价最小的 F0 轨迹。

    代价 = 帧间 |Δlog F0| 惩罚 + 倍频惩罚 + 清浊切换代价。
    """
    n = len(cand_list)
    if n == 0:
        return
    INF = 1e18
    # 状态：每帧的候选索引（外加一个"清音"状态 = -1）
    cost = np.full((n, _NCCF_CANDIDATES + 1), INF)
    back = np.full((n, _NCCF_CANDIDATES + 1), -1, dtype=int)

    def _voiced_cost(h):
        # 候选越好（NCCF 高）代价越低
        return -_VOICING_THRESH * h

    # 第一帧
    for j, (f, h) in enumerate(cand_list[0]):
        cost[0, j] = _voiced_cost(h)
    cost[0, -1] = 0.0  # 清音

    for k in range(1, n):
        cands_prev = cand_list[k - 1]
        cands_cur = cand_list[k]
        # 当前清音
        best_prev = int(np.argmin(cost[k - 1]))
        cost[k, -1] = cost[k - 1, best_prev] + _DP_VOICED_UNVOICED
        back[k, -1] = best_prev
        for j, (f, h) in enumerate(cands_cur):
            base = _voiced_cost(h)
            # 从前一帧每个状态转移
            for i_prev in range(cost.shape[1]):
                c_prev = cost[k - 1, i_prev]
                if c_prev >= INF:
                    continue
                if i_prev == cost.shape[1] - 1:
                    trans = _DP_VOICED_UNVOICED
                else:
                    fp = cands_prev[i_prev][0] if i_prev < len(cands_prev) else f
                    dlog = abs(np.log2(f / fp)) if (f > 0 and fp > 0) else 0.0
                    trans = _DP_TRANS_COST * dlog
                    # 倍频惩罚：整数倍偏差额外加
                    if dlog > 0.7:
                        trans += _DP_OCTAVE_COST
                tot = c_prev + trans
                if tot < cost[k, j]:
                    cost[k, j] = tot
                    back[k, j] = i_prev
            cost[k, j] += base

    # 回溯
    j = int(np.argmin(cost[n - 1]))
    for k in range(n - 1, -1, -1):
        if j == cost.shape[1] - 1 or j >= len(cand_list[k]):
            f0[k] = 0.0
        else:
            f0[k] = cand_list[k][j][0]
            voicing[k] = cand_list[k][j][1]
        j = back[k, j] if k > 0 else j


# ══════════════════════════════════════════════════════════════════════════
# LPC 共振峰（Snack formant -lpctype 1）
# ══════════════════════════════════════════════════════════════════════════
def _levinson(r, order):
    """Levinson-Durbin 递推求 LPC 系数。r 为自相关序列（长度 ≥ order+1）。"""
    a = np.zeros(order + 1)
    a[0] = 1.0
    e = r[0]
    if e <= 0:
        return a, 0.0
    for i in range(1, order + 1):
        acc = r[i] + np.dot(a[1:i], r[i - 1:0:-1])
        k = -acc / e
        a_new = a.copy()
        a_new[1:i] += k * a[i - 1:0:-1]
        a_new[i] = k
        a = a_new
        e *= (1.0 - k * k)
        if e <= 0:
            break
    return a, e


def _lpc_roots_to_formants(a, fs_eff, order):
    """LPC 多项式求根 → 极点频率/带宽。返回按频率排序的 (freqs, bws)。"""
    roots = np.roots(a)
    roots = roots[np.imag(roots) > 0]           # 只取上半平面
    freqs, bws = [], []
    for rt in roots:
        ang = np.angle(rt)
        f = ang * fs_eff / (2.0 * np.pi)
        bw = -np.log(max(abs(rt), 1e-12)) * fs_eff / np.pi
        if f > 0 and f < fs_eff / 2.0:
            freqs.append(float(f))
            bws.append(float(abs(bw)))
    order_idx = np.argsort(freqs)
    return np.array(freqs)[order_idx], np.array(bws)[order_idx]


def _downsample(y, fs, target):
    """线性插值降采样到 target Hz（近似 Snack 的 -ds_freq）。"""
    if fs <= target:
        return y.copy(), float(fs)
    n_out = int(round(y.size * target / fs))
    if n_out < 2:
        return y.copy(), float(fs)
    x_old = np.arange(y.size)
    x_new = np.linspace(0, y.size - 1, n_out)
    return np.interp(x_new, x_old, y), float(target)


def lpc_formants_frame(seg: np.ndarray, fs: float, order: int = LPC_ORDER,
                       preemphasis: float = PREEMPHASIS,
                       ds_freq: float = DS_FREQ):
    """单帧 LPC 共振峰：预加重 → 降采样 → Hamming → 自相关 → Levinson → 求根。"""
    seg = np.asarray(seg, dtype=float)
    if seg.size < order + 2:
        return np.array([]), np.array([])
    seg = seg - np.mean(seg)
    # 预加重
    seg = np.append(seg[0], seg[1:] - preemphasis * seg[:-1])
    y_ds, fs_ds = _downsample(seg, fs, ds_freq)
    if y_ds.size < order + 2:
        return np.array([]), np.array([])
    y_ds = y_ds * np.hamming(y_ds.size)
    r = np.correlate(y_ds, y_ds, mode="full")[y_ds.size - 1:]
    if r[0] <= 0:
        return np.array([]), np.array([])
    r = r[:order + 1]
    a, _e = _levinson(r, order)
    return _lpc_roots_to_formants(a, fs_ds, order)


def lpc_formants(y: np.ndarray, fs: float,
                 frameshift_s: float = FRAMESHIFT_S,
                 windowsize_s: float = WINDOWSIZE_S,
                 order: int = LPC_ORDER,
                 n_formants: int = 4,
                 ) -> tuple[np.ndarray, np.ndarray]:
    """逐帧 LPC 共振峰。返回 (F, B)，形状 (n_frames, n_formants)，缺项 = NaN。"""
    y = np.asarray(y, dtype=float)
    hop = max(1, int(round(frameshift_s * fs)))
    win = max(2, int(round(windowsize_s * fs)))
    if y.size < win:
        return np.zeros((0, n_formants)), np.zeros((0, n_formants))
    n_frames = (y.size - win) // hop + 1
    F = np.full((n_frames, n_formants), np.nan)
    B = np.full((n_frames, n_formants), np.nan)
    for k in range(n_frames):
        seg = y[k * hop:k * hop + win]
        f, b = lpc_formants_frame(seg, fs, order=order)
        # 带宽过滤（项目既有判据）：<30 Hz = 谐波伪极点；>1500 Hz = 污染帧
        keep = (b >= 30.0) & (b <= 1500.0) if b.size else np.zeros(0, dtype=bool)
        f, b = f[keep], b[keep]
        m = min(n_formants, f.size)
        if m:
            F[k, :m] = f[:m]
            B[k, :m] = b[:m]
    return F, B


# ══════════════════════════════════════════════════════════════════════════
# 对外包装：与真 Snack 调用侧同口径（网格对齐 + 头部半窗 NaN）
# ══════════════════════════════════════════════════════════════════════════
def _pad_to_grid(seq, datalen, windowsize, frameshift):
    """复刻调用侧网格对齐（vs_ParameterEstimation.m L687-688 / L863-871）：
    头部补 floor(windowsize/frameshift/2) 帧 NaN，再补尾到 datalen。

    注：MATLAB 中 zeros(N,1)*NaN == ones(N,1)*NaN == N 个 NaN（0*NaN=NaN）。
    """
    seq = np.asarray(seq, dtype=float)
    head = int(np.floor(windowsize / frameshift / 2.0))
    out = np.concatenate([np.full(head, np.nan), seq])
    if out.size < datalen:
        out = np.concatenate([out, np.full(datalen - out.size, np.nan)])
    return out


def snack_pitch_sim(wav_path: str, fs: float = None,
                    frameshift_s: float = FRAMESHIFT_S,
                    windowsize_s: float = WINDOWSIZE_S,
                    max_f0: float = MAX_F0, min_f0: float = MIN_F0,
                    ) -> tuple[np.ndarray, np.ndarray]:
    """sF0 模拟入口：返回 (f0_1ms, time_1ms)，与真 Snack 路径同口径。

    清音帧 f0 = 0（真 Snack 同），随后由调用侧按既有 NaN 口径处理。
    """
    y, fs = _read_wav_mono(wav_path, fs)
    f0, _v, _r = rapt_pitch(y, fs, frameshift_s, windowsize_s, max_f0, min_f0)
    datalen = int(round(y.size / fs / frameshift_s)) + 1
    f0 = _pad_to_grid(f0, datalen, windowsize_s, frameshift_s)
    time_ms = np.arange(datalen, dtype=float) * (frameshift_s * 1000.0)
    return f0, time_ms


def snack_formants_sim(wav_path: str, fs: float = None,
                       frameshift_s: float = FRAMESHIFT_S,
                       windowsize_s: float = WINDOWSIZE_S,
                       order: int = LPC_ORDER,
                       ) -> tuple[np.ndarray, ...]:
    """sF1-sF4 + sB1-sB4 模拟入口：返回 8 个向量（各 1ms 网格）。"""
    y, fs = _read_wav_mono(wav_path, fs)
    F, B = lpc_formants(y, fs, frameshift_s, windowsize_s, order=order)
    datalen = int(round(y.size / fs / frameshift_s)) + 1
    cols = []
    for i in range(4):
        cols.append(_pad_to_grid(F[:, i], datalen, windowsize_s, frameshift_s))
    for i in range(4):
        cols.append(_pad_to_grid(B[:, i], datalen, windowsize_s, frameshift_s))
    return tuple(cols)


def _read_wav_mono(path, fs=None):
    """读单声道 16-bit PCM（与 engines/straight.py 同口径）。"""
    import wave
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError(f"仅支持 16-bit PCM，得到 sampwidth={sw}")
    data = np.frombuffer(raw, dtype=np.int16).astype(float) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, float(rate if fs is None else fs)
