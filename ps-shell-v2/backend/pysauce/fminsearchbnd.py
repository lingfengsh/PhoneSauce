# -*- coding: utf-8 -*-
"""fminsearchbnd 复刻（John D'Errico 公开实现，BSD 风格许可）。

蓝本：refs/voicesauce-v137/fminsearchbnd.m（304 行，Release 4, 7/23/06）。
本模块只实现**本项目需要的单变量、双有限界**分支（BoundClass==3）：
  - 无界参数 xu → 实域 xreal = (sin(xu)+1)/2 * (UB-LB) + LB，再 clamp 到 [LB,UB]
  - 初值反变换 x0 → 2*pi + asin(clamp(2*(x0-LB)/(UB-LB)-1, -1, 1))
    （蓝本 L166-168：+2*pi 是为了避免 x=0 处初始单纯形过小）

未实现（本项目不需要，两界均有限）：
  - case 0（无界）、case 1（仅下界）、case 2（仅上界）、case 4（固定变量）
  - 蓝本对 LB=-Inf / UB=Inf 的分支 —— 本实现要求两界有限，否则 raise。

优化器：MATLAB fminsearch（无界 Nelder-Mead）→ scipy.optimize.minimize(method="Nelder-Mead")，
默认参数对齐 MATLAB TolX/TolFun=1e-4、MaxIter/MaxFunEvals=200*n。
合规声明（见 THIRD-PARTY-NOTICES.md §5–§9）：本文件按公开论文与 VoiceSauce v1.37
的行为语义**独立实现**，未包含或逐字翻译 VoiceSauce（© UCLA SPAPL）MATLAB 源码。
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize


def fminsearchbnd(fun, x0: float, fmin: float, fmax: float) -> tuple[float, float]:
    """[x, val] = fminsearchbnd(fun, x0, LB, UB, options)（单变量版）。返回 (x_real, fval)。"""
    # 本项目仅用双有限界分支；蓝本的 -Inf/Inf 分支不实现。
    if not (np.isfinite(fmin) and np.isfinite(fmax)):
        raise ValueError("fminsearchbnd: 本项目要求两界均有限（不支持 ±Inf）")
    if fmin >= fmax:
        raise ValueError("fminsearchbnd: 要求 fmin < fmax")

    # MT-L156-169 (case 3): 初值反变换到无界域
    if x0 <= fmin:
        x0u = -np.pi / 2                 # 蓝本 L160: 不可行初值
    elif x0 >= fmax:
        x0u = np.pi / 2                  # 蓝本 L163: 不可行初值
    else:
        u = 2 * (x0 - fmin) / (fmax - fmin) - 1
        x0u = 2 * np.pi + np.arcsin(max(-1.0, min(1.0, u)))  # 蓝本 L165-168

    # MT-L261-297 (xtransform, case 3): 无界域 → 实域
    def xtrans(xu):
        t = (np.sin(xu) + 1) / 2                    # 蓝本 L282
        t = t * (fmax - fmin) + fmin                # 蓝本 L283
        return max(fmin, min(fmax, t))              # 蓝本 L285: 浮点保护

    # MT-L249-257 (intrafun): 先变换再调目标
    def intrafun(xu):
        return float(np.asarray(fun(xtrans(float(np.ravel(xu)[0])))).item())

    # MT-L226: fminsearch(@intrafun, x0u, options)
    res = minimize(intrafun, x0u, method="Nelder-Mead",
                   options=dict(xatol=1e-4, fatol=1e-4, maxiter=200, maxfev=200))

    # MT-L229-232: x = xtransform(xu)
    return xtrans(res.x[0]), float(res.fun)
