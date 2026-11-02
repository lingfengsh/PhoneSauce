import numpy as np
from backend.pysauce.fminsearchbnd import fminsearchbnd


def test_quadratic_inside_bounds():
    # 目标 (x-3.7)^2 在 [0,10] → 最优点 3.7
    x, val = fminsearchbnd(lambda t: (t - 3.7) ** 2, 5.0, 0.0, 10.0)
    assert abs(x - 3.7) < 1e-3
    assert val < 1e-5


def test_optimum_at_bound():
    # 最优点在边界 → sin 变换收敛到边界（值可无限逼近）
    x, val = fminsearchbnd(lambda t: (t - 0.0) ** 2, 5.0, 0.0, 10.0)
    assert abs(x - 0.0) < 1e-2


def test_unimodal_cosine():
    # cos 在 [2,4] 的全局最小在 x=pi≈3.14159（cos(pi)=-1），窗内可达。
    # 原卡注释误把 3π/2（cos 的过零点）当作极小点，断言 abs(x-4)<1e-2 数学上错误；
    # 按数学事实修正为 x≈pi（见卡 §8 缺陷记录）。
    x, val = fminsearchbnd(lambda t: np.cos(t), 3.0, 2.0, 4.0)
    assert abs(x - np.pi) < 1e-2 and abs(val - (-1.0)) < 1e-6
