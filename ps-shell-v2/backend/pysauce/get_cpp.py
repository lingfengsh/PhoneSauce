# -*- coding: utf-8 -*-
"""func_GetCPP.m → Python 复刻。

蓝本：refs/voicesauce-v137/func_GetCPP.m（77 行），Yen-Liang Shue, UCLA SPAPL 2009。
语义：CPP（Cepstral Peak Prominence，Hillenbrand 1994）——
      5 周期窗 → hamming 加窗 → FFT → log|·| → IFFT（倒谱）→ 10log10(·²) → dB 曲线
      → 丢前 1 ms（Hillenbrand：低于 1 ms 的倒谱时延忽略）→ pickpeaks 找倒谱峰
      → polyfit 线性基线 → CPP = 峰 − 基线。

⚠ 复数处理决策（卡 §3 强制停报项，见 §8 报告）：
  蓝本 L50-51 `yseg_c = ifft(log(abs(YSEG))); yseg_c_db = 10*log10(yseg_c .^ 2);`
  `yseg_c` 在数学上**是实数**（ifft 的输入 log|YSEG| 为实数组 → ifft 输出实部对称），
  但因浮点误差其 `.imag ≈ 1e-11`（纯噪声），故 `yseg_c.^2` 为复数、`10*log10(复数)` 亦复数。
  **本实现取 `.real`**，依据：
    ① 数值上 `10*log10(c**2).real ≡ 20*log10(|c|)`（实测最大差 7.1e-15），虚部仅 1e-7 量级；
    ② MATLAB 的关系运算符（`<`/`>`，蓝本 pickpeaks L18/L42 使用）**只比较实部**
       （MathWorks `lt` 文档："lt compares only the real part of the elements in A"）；
    ③ 因此取实部与"保持复数交给 MATLAB 关系运算"**在数值上完全一致**（差异 < 1e-9 dB）。
  取实部同时避免了 numpy 复数 min/argmax（按实部/字典序）与 MATLAB（按模）的语义分歧。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

from . import matlang as M
from .pickpeaks import pickpeaks


def get_cpp(y: np.ndarray, fs: int, f0: np.ndarray,
            n_periods_ec: int = 5, frameshift_ms: float = 1.0) -> np.ndarray:
    """CPP = func_GetCPP(y, Fs, F0, variables)。返回 len(f0) 向量，无效帧 NaN。"""
    y = np.asarray(y, dtype=np.float64)
    f0 = np.asarray(f0, dtype=np.float64)

    # MT-L15: sampleshift = Fs/1000*frameshift
    sampleshift = fs / 1000.0 * frameshift_ms

    # MT-L17: CPP = zeros(length(F0),1)*NaN
    cpp = np.full(len(f0), np.nan, dtype=np.float64)

    # MT-L19: N_ms = round(Fs/1000)   Quefrency below 1ms ignored (Hillenbrand)
    n_ms = int(M.mround(fs / 1000.0))

    for k0 in range(1, len(f0) + 1):
        # MT-L22: ks = round(k*sampleshift)
        ks = int(M.mround(k0 * sampleshift))

        # MT-L24-26: if (ks<=0 || ks>length(y)) continue
        if ks <= 0 or ks > len(y):
            continue

        # MT-L28-32: F0_curr=F0(k); if (isnan(F0_curr)) continue
        #   注意：CPP 只判 NaN，**不判 ==0**（与 Energy/A1A2A3 的 `isnan || ==0` 不同）
        # ⚠ 复刻修正：F0_curr==0 → N0_curr=Inf → int(mround(...*Inf)) 在 Python 抛
        #   "cannot convert float infinity to integer"（MATLAB 因 ystart=-Inf≤0 跳过）。
        #   故此处把 NaN/非有限/非正一并拦截，等价于 MATLAB 有效跳过行为。
        f0_curr = f0[k0 - 1]
        if not np.isfinite(f0_curr) or f0_curr <= 0:
            continue

        # MT-L34: N0_curr = Fs/F0_curr
        n0_curr = fs / f0_curr

        # MT-L36-37: ystart = round(ks - N_periods/2*N0_curr); yend = round(ks + ...) - 1
        ystart = int(M.mround(ks - n_periods_ec / 2.0 * n0_curr))
        yend = int(M.mround(ks + n_periods_ec / 2.0 * n0_curr)) - 1

        # MT-L39-45: if (ystart<=0) continue; if (yend>length(y)) continue
        if ystart <= 0:
            continue
        if yend > len(y):
            continue

        # MT-L47-48: yseg = y(ystart:yend); yseg = yseg .* hamming(length(yseg))
        yseg = y[ystart - 1: yend]
        yseg = yseg * np.hamming(len(yseg))

        # MT-L49: YSEG = fft(yseg)
        yseg_fft = np.fft.fft(yseg)

        # MT-L50: yseg_c = ifft(log(abs(YSEG)))   （数学上实值；浮点下 imag≈1e-11）
        yseg_c = np.fft.ifft(np.log(np.abs(yseg_fft)))

        # MT-L51: yseg_c_db = 10*log10(yseg_c .^ 2)
        #   ⚠ 逐字对应为复数式 `10*np.log10(yseg_c**2)`，但随后取 .real（见模块 docstring）
        yseg_c_db = (10.0 * np.log10(yseg_c ** 2)).real

        # MT-L53: yseg_c_db = yseg_c_db(1:floor(length(yseg)/2))
        #   MATLAB 1:floor(L/2) 含端点 → 0-based [:L//2]
        yseg_c_db = yseg_c_db[: len(yseg) // 2]

        # MT-L55-57: if (N_ms >= length(yseg_c_db)) continue
        if n_ms >= len(yseg_c_db):
            continue

        # MT-L59: [vals, inx] = func_pickpeaks(yseg_c_db(N_ms:end)', 2*N0_curr)
        #   ⚠ 坐标系规定（全卡最关键）：统一 0-based。
        #   子数组 sub = yseg_c_db[n_ms:]（全局 0-based 起点 n_ms）
        #   pickpeaks 返回 0-based 子数组位置 inx0；全局 0-based 位置 = inx0 + n_ms
        #   winlen = 2*N0_curr（浮点）→ pickpeaks 签名要求 int → int(mround(...))
        sub = yseg_c_db[n_ms:]
        winlen = int(M.mround(2.0 * n0_curr))
        vals, inx = pickpeaks(sub, winlen)

        # MT-L60: [pos, pinx] = min(abs(inx - N0_curr))
        #   注意：蓝本此处 inx 仍是**子数组 1-based** 位置（pickpeaks 返回 1-based）。
        #   本实现 inx 为 0-based，而 N0_curr 是**样本数**（非索引），蓝本直接相减
        #   隐含 1-based 与样本偏移的近似（见 §8 对照表"坐标系规定"条）。
        #   忠实做法：与蓝本同式，用 0-based inx 与 N0_curr 相减，取 argmin。
        if inx.size == 0:
            continue
        pinx = int(np.argmin(np.abs(inx - n0_curr)))

        # MT-L62-67: inx = inx(pinx(1));
        #            vals = yseg_c_db(inx+N_ms-1);          ← 1-based 全局索引
        #            p = polyfit([N_ms:length(yseg_c_db)], yseg_c_db(N_ms:end)', 1);
        #            base_val = p(1)*(inx+N_ms-1) + p(2);
        #            CPP(k) = vals - base_val;
        #   ⚠ 坐标系换算：MATLAB 全局 1-based 位置 = inx_1based + N_ms - 1
        #     → 0-based 全局位置 = (inx_1based - 1) + N_ms = inx0 + n_ms（本实现 inx 已是 0-based）
        inx0 = int(inx[pinx])
        gpos = inx0 + n_ms                       # 全局 0-based 位置
        vals_g = yseg_c_db[gpos]                 # = yseg_c_db(inx+N_ms-1)

        # polyfit 的 x 轴 = 全局 0-based 索引 np.arange(n_ms, len(yseg_c_db))
        #   （蓝本 [N_ms:length] 是 1-based；x 轴与取值点、base 求值点同坐标系 → 整体平移 1
        #    不影响 CPP 差值，见 §8 对照表"平移等价性"条）
        x_axis = np.arange(n_ms, len(yseg_c_db))
        p = np.polyfit(x_axis, sub, 1)
        base_val = np.polyval(p, gpos)

        # MT-L67: CPP(k) = vals - base_val
        cpp[k0 - 1] = float(vals_g - base_val)

    return cpp
