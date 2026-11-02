# -*- coding: utf-8 -*-
"""func_GetHNR.m → Python 复刻（整段分支）。

蓝本：refs/voicesauce-v137/func_GetHNR.m（127 行），Yen-Liang Shue, UCLA SPAPL 2009。
算法：de Krom 1993《A cepstrum-based technique for determining a harmonic-to-noise
      ratio in speech signals》(JSHR)。5 周期窗（**强制奇数长**）→ hamming → FFT →
      log10|·| → IFFT（实倒谱）→ 逐 rahmonic 峰做 lifter 置零 → 对称化 → FFT 回对数谱
      → 基线校正 → 在 4 个等价截止频率（500/1500/2500/3500 Hz）上算
      `HNR = 20*mean(H[0:Ef]) - 20*mean(N[0:Ef])`（dB）。

本卡只实现整段分支（蓝本 L24-63）；TextGrid 分支与 handles 不实现。

关键忠实点（详见工程卡 §8）：
  ① L41-43 窗长偶数 → `yend = yend - 1`（**强制奇数**，倒谱需要）。
  ② L79 `peakinx = zeros(floor(length(y)/2/N0), 1)` → 循环次数 = floor(NB/2/N0)。
  ③ L89-90 `sign(inx)` 中 inx 是**段内 1-based 峰位置（≥1）** → `sign(inx) ≡ +1` 恒成立
     （蓝本疑似笔误，但行为确定：等价于与 +1 比较）。忠实按 `sign(inx)=+1` 实现。
  ④ L89-90 `find(...,1)` 返回空 → MATLAB `ay([])=0` 是 **no-op**（不置零该峰）。
  ⑤ L101-102 后半 = 前半镜像（实倒谱对称化）；`midL = round(len/2)+1` 用 **mround**（远离零）。

⚠️ lifter 双模式（2026-10-26 用户拍板「代码加开关，默认 A」）：
  蓝本 `ay = ifft(aY)`，`aY = log10(abs(Y))` 为实向量 → MATLAB `ifft` 返回**复数**
  （虚部浮点残差 ~1e-14）。故 `s_ayseg = sign(diff(ayseg))` 是**复数**，MATLAB 的 `~=`/`==`
  对复数**同时比较实虚部**：
    - `(1+1e-14i) ~= 1` 恒真 → `find(...,1)` 恒返 1 → `l_inx = inx`；
    - `(1+1e-14i) == 1` 恒假 → `find` 返空 → `r_inx = []`；
    - `ay(inx:[])` = 空索引赋值 = **no-op**。
  ⇒ **忠实翻译（mode="faithful"）下 L80-98 的 lifter 完全失效（惰性）**——这是已发布
  VoiceSauce 代码的潜在缺陷，但为「与 VS 输出可比」，本项目**默认采忠实模式**。
  另一模式 `"intended"`（算法本意，见 de Krom 1993 / phonlab 独立再实现）把 `sign` 作用于
  **实倒谱**（`ay.real`），使 lifter 真正围绕每个 rahmonic 置零，供对照实验用。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

from . import matlang as M


def get_hnr_for_frame(yseg: np.ndarray, f0: float, fs: float,
                      nfreqs: "tuple[float, ...]" = (500.0, 1500.0, 2500.0, 3500.0),
                      lifter_mode: str = "faithful"
                      ) -> np.ndarray:
    """n = getHNR(yseg, F0, Fs, Nfreqs)（蓝本 L67–127）。返回 len(nfreqs) 向量。

    lifter_mode:
      "faithful"（默认）—— 忠实蓝本：`sign` 作用在**复数**倒谱上 → 复数比较恒真/恒假
                           → `r_inx` 恒空 → 置零赋值 no-op（lifter 惰性）。
      "intended"        —— 算法本意：`sign` 作用在**实**倒谱（`ay.real`）上 → lifter 真正
                           围绕每个 rahmonic 置零（对照 de Krom 1993 / phonlab 实现）。
    """
    y = np.asarray(yseg, dtype=np.float64)
    if lifter_mode not in ("faithful", "intended"):
        raise ValueError(f"lifter_mode 必须是 'faithful' 或 'intended'，得到 {lifter_mode!r}")

    # MT-L69-71: NBins = length(y); N0 = round(Fs/F0); N0_delta = round(N0*0.1)
    n_bins = len(y)
    n0 = int(M.mround(fs / f0))
    n0_delta = int(M.mround(n0 * 0.1))

    # MT-L73-76: y = y.*hamming(length(y)); Y = fft(y,NBins); aY = log10(abs(Y)); ay = ifft(aY)
    y = y * np.hamming(len(y))
    big_y = np.fft.fft(y, n_bins)
    a_y = np.log10(np.abs(big_y))
    ay = np.fft.ifft(a_y)

    # MT-L79: peakinx = zeros(floor(length(y)/2/N0), 1)
    n_peaks = int(np.floor(len(y) / 2 / n0))
    peakinx = np.zeros(n_peaks, dtype=np.float64)

    for k in range(1, n_peaks + 1):
        # MT-L81: ayseg = ay(k*N0 - N0_delta : k*N0 + N0_delta)   1-based 闭区间
        #   → 0-based 起点 k*N0-N0_delta-1，终点 k*N0+N0_delta-1（含）
        lo = k * n0 - n0_delta - 1
        hi = k * n0 + n0_delta - 1          # 含端点
        # 防御：蓝本未判边界（MATLAB 越界会报错），此处若越界则跳过（不产生伪结果）
        if lo < 0 or hi >= len(ay):
            continue
        ayseg = ay[lo: hi + 1]

        # MT-L82: [val, inx] = max(abs(ayseg))   inx 为段内 1-based
        inx = int(np.argmax(np.abs(ayseg))) + 1

        # MT-L83: peakinx(k) = inx + k*N0 - N0_delta - 1   （1-based 全局；本实现仅记录）
        peakinx[k - 1] = inx + k * n0 - n0_delta - 1

        # MT-L86: s_ayseg = sign(diff(ayseg))
        #   mode="faithful"：ayseg 复数 → diff/sign 复数（z/|z|，虚部 ~1e-14）
        #   mode="intended"：先取实部 → 纯实数符号（±1/0）
        diff_ayseg = np.diff(ayseg)
        s_ayseg = np.sign(diff_ayseg if lifter_mode == "faithful" else diff_ayseg.real)

        # MT-L89: l_inx = inx - find((s_ayseg(inx-1:-1:1) ~= sign(inx)), 1) + 1
        #   sign(inx)=+1（inx>=1）；s_ayseg(inx-1:-1:1) 为 1-based 倒序切片
        #   0-based: s_ayseg[inx-2::-1]（取段内第 inx-1 到第 1 个）
        #   find 空 → MATLAB no-op（不置零）→ 用 sentinel None 表示
        left = s_ayseg[inx - 2:: -1] if inx >= 2 else np.array([])
        l_idx = np.nonzero(left != 1.0)[0]
        l_inx = inx - (int(l_idx[0]) + 1) + 1 if l_idx.size else None

        # MT-L90: r_inx = inx + find((s_ayseg(inx+1:end) == sign(inx)), 1)
        #   0-based: s_ayseg[inx:]（段内第 inx+1 到末尾）
        right = s_ayseg[inx:]
        r_idx = np.nonzero(right == 1.0)[0]
        r_inx = inx + (int(r_idx[0]) + 1) if r_idx.size else None

        # MT-L92-93: l_inx/r_inx 加回全局偏移（1-based: +k*N0-N0_delta-1）
        #   本实现统一换算到 0-based 全局：段内 1-based p → 全局 0-based = lo + (p-1)
        # MT-L96: ay(l_inx:r_inx) = 0     ← 仅在 l_inx、r_inx **均非空**时生效
        if l_inx is not None and r_inx is not None:
            gl = lo + (l_inx - 1)
            gr = lo + (r_inx - 1)
            ay[gl: gr + 1] = 0

    # MT-L101-102: midL = round(length(y)/2)+1; 后半 = 前半镜像（实倒谱对称化）
    #   MATLAB round 远离零 → mround
    #   ay(midL:end) = ay(midL-1:-1:midL-1-(length(ay)-midL))
    #   右侧 1-based midL..NB → 0-based [midL-1 : NB]，共 NB-midL+1 个
    #   左侧 1-based (midL-1):-1:(midL-1-(NB-midL)) → 0-based 倒序，共 NB-midL+1 个
    #     → 0-based 切片 ay[midL-2 :: -1][:NB-midL+1]（已验证奇偶长度均一致）
    mid_l = int(M.mround(len(y) / 2)) + 1
    nb = len(ay)
    cnt = nb - mid_l + 1
    ay[mid_l - 1:] = ay[mid_l - 2:: -1][:cnt]

    # MT-L104-106: Nap = real(fft(ay)); N = Nap; Ha = aY - Nap
    nap = np.real(np.fft.fft(ay))
    n = nap.copy()
    ha = a_y - nap

    # MT-L109-115: 基线校正
    #   Hdelta = F0/Fs*length(y)
    #   for f=Hdelta+0.0001 : Hdelta : round(length(y)/2)
    #       fstart = ceil(f - Hdelta)
    #       Bdf = abs(min(Ha(fstart:round(f))))
    #       N(fstart:round(f)) = N(fstart:round(f)) - Bdf
    h_delta = f0 / fs * len(y)
    f_vals = np.arange(h_delta + 0.0001, M.mround(len(y) / 2) + h_delta * 1e-9, h_delta)
    for f in f_vals:
        fstart = int(np.ceil(f - h_delta))          # 1-based
        fend = int(M.mround(f))                      # 1-based
        if fstart < 1 or fend > len(ha) or fstart > fend:
            continue
        # 0-based: [fstart-1 : fend]
        seg_ha = ha[fstart - 1: fend]
        bdf = abs(np.min(seg_ha))
        n[fstart - 1: fend] = n[fstart - 1: fend] - bdf

    # MT-L118-123: H = aY - N; 逐 Nfreqs 求 20*mean(H[1:Ef]) - 20*mean(N[1:Ef])
    h = a_y - n
    out = np.zeros(len(nfreqs), dtype=np.float64)
    for k, nfreq in enumerate(nfreqs):
        # MT-L121: Ef = round(Nfreqs(k)/Fs*length(y))   1-based 截止
        ef = int(M.mround(nfreq / fs * len(y)))
        # MT-L122: n(k) = 20*mean(H(1:Ef)) - 20*mean(N(1:Ef))
        #   0-based: H[0:ef]（1:Ef 含端点 → 0-based 0..Ef-1 → 切片 [:ef]）
        out[k] = 20 * np.mean(h[:ef]) - 20 * np.mean(n[:ef])

    return out


def get_hnr(y: np.ndarray, fs: int, f0: np.ndarray,
            n_periods_ec: int = 5, frameshift_ms: float = 1.0,
            lifter_mode: str = "faithful"
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """[HNR05, HNR15, HNR25, HNR35] = func_GetHNR(y, Fs, F0, variables)（整段分支）。

    lifter_mode 见 `get_hnr_for_frame`（"faithful" 默认 / "intended"）。
    """
    y = np.asarray(y, dtype=np.float64)
    f0 = np.asarray(f0, dtype=np.float64)

    # MT-L16: sampleshift = Fs/1000*frameshift
    sampleshift = fs / 1000.0 * frameshift_ms

    # MT-L18-21: 四列 NaN
    hnr05 = np.full(len(f0), np.nan, dtype=np.float64)
    hnr15 = np.full(len(f0), np.nan, dtype=np.float64)
    hnr25 = np.full(len(f0), np.nan, dtype=np.float64)
    hnr35 = np.full(len(f0), np.nan, dtype=np.float64)

    for k0 in range(1, len(f0) + 1):
        # MT-L25: ks = round(k*sampleshift)
        ks = int(M.mround(k0 * sampleshift))

        # MT-L27-29: if (ks<=0 || ks>length(y)) continue
        if ks <= 0 or ks > len(y):
            continue

        # MT-L31-36: F0_curr=F0(k); N0_curr=1/F0_curr*Fs; if isnan(F0_curr) continue
        # ⚠ 复刻修正：原版先在 f0_curr 可能为 0 时就算 N0_curr=Inf，再判 isnan 跳过——
        #   Python 下 f0_curr==0 让 1/0=Inf，随后 int(mround(...*Inf)) 抛
        #   "cannot convert float infinity to integer"。这里先拦截非有限/非正 F0，
        #   与 MATLAB（ystart=-Inf≤0 跳过）有效行为一致。
        f0_curr = f0[k0 - 1]
        if not np.isfinite(f0_curr) or f0_curr <= 0:
            continue
        n0_curr = 1.0 / f0_curr * fs

        # MT-L38-39: ystart = round(ks - N_periods/2*N0_curr); yend = round(ks + ...) - 1
        ystart = int(M.mround(ks - n_periods_ec / 2.0 * n0_curr))
        yend = int(M.mround(ks + n_periods_ec / 2.0 * n0_curr)) - 1

        # MT-L41-43: if (mod(yend-ystart+1, 2) == 0) yend = yend - 1   ← 强制奇数长
        if (yend - ystart + 1) % 2 == 0:
            yend = yend - 1

        # MT-L45-51: if (ystart<=0) continue; if (yend>length(y)) continue
        if ystart <= 0:
            continue
        if yend > len(y):
            continue

        # MT-L53: yseg = y(ystart:yend)
        yseg = y[ystart - 1: yend]

        # MT-L56: hnr = getHNR(yseg, F0_curr, Fs, [500 1500 2500 3500])
        hnr = get_hnr_for_frame(yseg, float(f0_curr), float(fs), lifter_mode=lifter_mode)

        # MT-L58-61: HNR05(k)=hnr(1) … HNR35(k)=hnr(4)
        hnr05[k0 - 1] = hnr[0]
        hnr15[k0 - 1] = hnr[1]
        hnr25[k0 - 1] = hnr[2]
        hnr35[k0 - 1] = hnr[3]

    return hnr05, hnr15, hnr25, hnr35
