# -*- coding: utf-8 -*-
"""MATLAB → NumPy 语义桥。

只封装两语言语义确有差异的操作；业务计算一律写在各算法模块内。
用法总则见 docs/v2.0-工程卡/00-总纲.md 第 5 节（R1–R10）。
关键差异速查：
  round : MATLAB 四舍五入远离零（round(-2.5)=-3）；np.round 是银行家舍入 → 用 mround
  %     : MATLAB rem(-3,2)=-1；Python (-3)%2=1 → 用 mrem
  colon : 0:0.1:0.3 的端点行为 → 用 mcolon（含端点容差补齐）
  find  : 空集时 MATLAB 后续统计返回 []，Python 直接崩 → 每处 mfind 后必须判空（R3）
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np

__all__ = ["mround", "mrem", "mcolon", "mfind", "frameify", "interp1"]


def mround(x):
    """MATLAB round：四舍五入远离零。支持标量与数组，返回 float（保持 NaN）。

    np.floor(np.abs(x)+0.5)*sign 是标准实现；对 NaN 透传（floor(NaN)=NaN）。
    """
    a = np.asarray(x, dtype=np.float64)
    return np.sign(a) * np.floor(np.abs(a) + 0.5)


def mrem(x, y):
    """MATLAB rem：结果符号与被除数一致。rem(-3,2)=-1，rem(3,-2)=1。y=0 → NaN（MATLAB 语义）。"""
    a = np.asarray(x, dtype=np.float64)
    b = np.asarray(y, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = a - b * np.fix(a / b)  # fix=向零截断，与 MATLAB rem 定义一致
    return r


def mcolon(start, stop, step=1.0):
    """MATLAB a:s:b，返回 float64 数组。

    处理 MATLAB 端点语义：若 stop 与最后元素之差在 step*eps*10 容差内则补端点。
    step 必须非零；start/stop/step 可为 float。
    """
    step = float(step)
    if step == 0:
        raise ValueError("mcolon: step 不能为 0")
    n = int(np.floor((float(stop) - float(start)) / step + 1e-10)) + 1
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    out = float(start) + step * np.arange(n, dtype=np.float64)
    # 端点容差补齐（MATLAB colon 的经典行为）
    if (step > 0 and out[-1] < float(stop) <= float(stop) - out[-1] + step * 1e-9) or (
        step < 0 and out[-1] > float(stop) >= float(stop) - out[-1] + step * 1e-9
    ):
        out = np.append(out, float(stop))
    return out


def mfind(cond):
    """MATLAB find 的 0-based 等价：返回满足条件的索引数组（int64）。

    注意：返回值是 **0-based**（Python 惯例）。翻译 `x(find(c))` 时直接 x[mfind(c)]；
    翻译 `for k = find(c)` 时循环变量是 0-based —— 循环体内的 1-based 字面索引要按 R2 换算。
    空集返回长度 0 的数组（MATLAB 语义），调用方必须判空（R3）。
    """
    return np.nonzero(np.asarray(cond))[0]


def frameify(x, win_len, shift):
    """滑动窗切帧 → (n_frames, win_len) 矩阵。

    MATLAB 惯用法（VS 各算法同款）：
      nframes = floor((len(x)-win_len)/shift)+1
      frames(:,i) = x((i-1)*shift+1 : (i-1)*shift+win_len)
    x 长度 < win_len 时返回 (0, win_len)（与 MATLAB 空矩阵语义一致，调用方判空）。
    """
    x = np.asarray(x, dtype=np.float64)
    win_len = int(win_len)
    shift = int(shift)
    if len(x) < win_len or win_len <= 0 or shift <= 0:
        return np.zeros((0, win_len), dtype=np.float64)
    n = int(np.floor((len(x) - win_len) / shift)) + 1
    idx = np.arange(win_len)[None, :] + shift * np.arange(n)[:, None]
    return x[idx]


def interp1(xq_x, xq_v, x):
    """MATLAB interp1（默认 linear，无外推）：x 超出 [xq_x[0], xq_x[-1]] 的点返回 NaN。

    xq_x 必须单调（升或降均可，MATLAB 允许降序查询点）；xq_v 同长。
    精确命中端点返回端点值；重复值用 np.interp 处理升序，降序先翻转。
    """
    xs = np.asarray(xq_x, dtype=np.float64)
    vs = np.asarray(xq_v, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    if xs.size == 0:
        return np.full(x.shape, np.nan)
    if xs[0] > xs[-1]:  # 降序 → 翻转成升序再插值
        xs = xs[::-1]
        vs = vs[::-1]
    out = np.interp(x, xs, vs, left=np.nan, right=np.nan)
    return out
