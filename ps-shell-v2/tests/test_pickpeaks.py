# -*- coding: utf-8 -*-
"""func_pickpeaks 复刻测试。锚点由独立脚本复算（2026-10-26），禁改。"""
import numpy as np

from backend.pysauce.pickpeaks import pickpeaks


def _pp(x, w):
    ymax, inx = pickpeaks(np.asarray(x, dtype=float), w)
    return ymax.tolist(), inx.tolist()


def test_two_peaks_basic():
    assert _pp([0, 1, 3, 1, 0, 2, 5, 2, 0], 3) == ([3.0, 5.0], [2, 6])


def test_window_filter_removes_middle_peak():
    # maxima=5(idx1),9(idx4)；4 不是极大值（4<9）。窗口过滤后 5、9 均保留
    assert _pp([0, 5, 1, 4, 9, 1, 0], 3) == ([5.0, 9.0], [1, 4])


def test_competition_later_peak_wins():
    # 5(idx1) 与 4(idx4) 距离 3 ≤ winlen=3 → 竞争，后者胜出，5 被过滤
    assert _pp([2, 5, 2, 1, 4, 2], 3) == ([4.0], [1])


def test_three_peaks_no_kill():
    # 三峰距离均 > winlen=3 → 全保留
    assert _pp([0, 1, 5, 1, 0, 2, 3, 2, 0, 4, 4.5, 4, 0], 3) == (
        [5.0, 3.0, 4.5], [2, 6, 10])


def test_ymin_restored_multi_peak():
    # 与 test_three_peaks_no_kill 同构平移 +3（ymin=3）→ 峰值应加回 ymin
    assert _pp([3, 4, 8, 4, 3, 5, 6, 5, 3, 7, 7.5, 7, 3], 3) == (
        [8.0, 6.0, 7.5], [2, 6, 10])


def test_single_peak_early_return_no_restore():
    # 陷阱①：单峰提前 return，ymax 未加回 ymin（蓝本疏漏，忠实保留）
    # 输入 [1,8,1,1,1]，ymin=1；若"修复"会返回 [8]，蓝本行为返回 [7]
    assert _pp([1, 8, 1, 1, 1], 3) == ([7.0], [1])


def test_end_peak_dropped():
    # 贴信号末端的峰被 inx1(end)=0 丢弃（蓝本 L20）
    # [0,7,0,0,0] 唯一峰在 idx1，其下降沿 diff=+1 位于 inx1 中间 → 应检出
    assert _pp([0, 7, 0, 0, 0], 5) == ([7.0], [1])
    # 峰紧贴末尾：[0,0,7,0] 的 +1 跳变在 inx1 最后一个元素 → 被丢弃
    assert _pp([0, 0, 7, 0], 5) == ([], [])
