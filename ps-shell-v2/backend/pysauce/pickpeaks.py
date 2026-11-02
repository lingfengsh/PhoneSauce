# -*- coding: utf-8 -*-
"""func_pickpeaks.m → Python 复刻。

蓝本：refs/voicesauce-v137/func_pickpeaks.m（49 行，Yen-Liang Shue & Markus Iseli, UCLA SPAPL 2009）。
用途：被 func_GetCPP / func_GetHNR 调用，在倒谱/自相关曲线上找峰。

两段式：① 一阶差分找全部局部极大；② 用 winlen 窗逐峰过滤（窗口内只留最大者）。

忠实保留的两处 MATLAB 陷阱（禁止"修复"）：
  ① nofmax==1 时提前 return，返回的 ymax **未加回 ymin**（蓝本 L28-30 疏漏）。
  ② 过滤循环里 `ymax(arr2)` 是「逻辑索引短于数组 → 取前缀」语义（蓝本 L37-39）。

位置索引：蓝本 1-based → 本函数返回 **0-based**（内部换算，调用方按 0-based 用）。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np


def pickpeaks(y: np.ndarray, winlen: int) -> tuple[np.ndarray, np.ndarray]:
    """[ymax, inx] = func_pickpeaks(y, winlen)。

    返回 (峰值数组, 峰位置数组)，位置为 **0-based** 索引（蓝本是 1-based，
    位置值统一减 1 —— 由本函数内部换算，调用方按 0-based 使用）。
    """
    y = np.asarray(y, dtype=np.float64)

    # MT-L13-14: ymin = min(y); y = y - ymin
    ymin = float(np.min(y))
    y = y - ymin

    # MT-L15: dy = [y(1); transpose(diff(y))]   首样本补回，保持等长
    dy = np.concatenate([[y[0]], np.diff(y)])

    # MT-L16: inx1 = diff(dy < 0)   +1=极大，-1=极小
    inx1 = np.diff((dy < 0).astype(np.int64))

    # MT-L17-18: inx1(1)=0; inx1(end)=0   丢弃贴边峰
    inx1[0] = 0
    inx1[-1] = 0

    # MT-L19-21: inx = inx1>0; ymax = y(inx); inx = find(inx)
    # ⚠ 陷阱②同源语义：y 长 N，mask(inx1) 长 N-1 → MATLAB 逻辑索引短于数组 = 取 y 前缀。
    #   直接 y[mask] 会 IndexError（shape 不匹配）。此处必须显式取前缀。
    mask = inx1 > 0
    ymax = y[:mask.size][mask].copy()      # copy：后面要原地改
    inx = np.nonzero(mask)[0]              # 0-based（蓝本 find 为 1-based）

    # MT-L27-30: nofmax=length(ymax); if nofmax==1 return
    # ⚠ 陷阱①：此处返回的 ymax 未加回 ymin（蓝本疏漏，忠实保留，禁止"修复"）
    nofmax = int(ymax.size)
    if nofmax == 1:
        return ymax, inx

    # MT-L32-41: for cnt = 1:nofmax  用 winlen 窗过滤极大值
    for cnt in range(1, nofmax + 1):
        # MT-L33: arr = inx(1:cnt)   前 cnt 个峰位置
        arr = inx[:cnt]
        # MT-L34: cmp = inx(cnt) - winlen
        cmp_ = inx[cnt - 1] - winlen
        # MT-L35: arr2 = arr > cmp    逻辑掩码，长度 cnt
        arr2 = arr > cmp_
        # MT-L37: [m, mi] = max(ymax(arr2))
        # ⚠ MATLAB 允许逻辑索引短于数组 → 取 ymax 前 cnt 个元素再筛（陷阱②核心）。
        #   直接 ymax[arr2] 会 IndexError。
        pref = ymax[:cnt]
        loc = pref[arr2]
        mi = int(np.argmax(loc))
        m = float(loc[mi])
        # MT-L38: ymax(arr2) = -60000
        pref[arr2] = -60000
        # MT-L39: ymax(mi + length(arr2) - sum(arr2)) = m   全局线性索引写回
        ymax[mi + len(arr2) - int(arr2.sum())] = m

    # MT-L42-44: temp = find(ymax>0); inx = inx(temp); ymax = ymax(temp)
    temp = np.nonzero(ymax > 0)[0]
    inx = inx[temp]
    ymax = ymax[temp]

    # MT-L49: ymax = ymax + ymin   仅在未提前 return 时执行
    ymax = ymax + ymin

    return ymax, inx
