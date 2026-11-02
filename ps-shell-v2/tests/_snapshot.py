# -*- coding: utf-8 -*-
"""回归快照 helper。

用法（算法卡测试模板）：
    from tests._snapshot import assert_snapshot, SNAP_DIR

    def test_energy_snapshot():
        got = {"col": [ ... float ... ]}        # 键=样本名，值=float 或 list[float]
        assert_snapshot("get_energy", got)

- 快照存在：逐键对比，容差 abs 1e-9（NaN==NaN 视为相等）。
- 快照不存在：skip 并打印生成指引（由验收员运行 save 端生成，施工者禁止自行 save）。
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(HERE, "fixtures", "snapshots")
TOL = 1e-9


def _norm(x):
    if isinstance(x, float) and math.isnan(x):
        return "NaN"
    if isinstance(x, (np.floating,)):
        return "NaN" if np.isnan(x) else round(float(x), 12)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, list):
        return [_norm(v) for v in x]
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in sorted(x.items())}
    return x


def _path(name):
    return os.path.join(SNAP_DIR, name + ".json")


def assert_snapshot(name, got):
    fp = _path(name)
    assert os.path.isfile(fp), (
        f"快照 {name}.json 不存在。这是正常现象（首次实现）。"
        f"请在报告中注明『待验收员生成快照』，禁止自行生成。"
    )
    with open(fp, encoding="utf-8") as f:
        exp = json.load(f)
    got_n, exp_n = _norm(got), _norm(exp)
    assert set(got_n) == set(exp_n), f"键不一致: got={sorted(got_n)} exp={sorted(exp_n)}"

    def walk(g, e, path):
        if isinstance(g, dict):
            for k in g:
                walk(g[k], e[k], f"{path}.{k}")
        elif isinstance(g, list):
            assert len(g) == len(e), f"{path}: 长度 {len(g)} != {len(e)}"
            for i, (a, b) in enumerate(zip(g, e)):
                walk(a, b, f"{path}[{i}]")
        else:
            if g == "NaN" or e == "NaN":
                assert g == e, f"{path}: NaN 不匹配 got={g} exp={e}"
            else:
                assert abs(float(g) - float(e)) <= TOL, f"{path}: {g} != {e} (tol {TOL})"

    walk(got_n, exp_n, name)


def save_snapshot(name, got):
    """仅验收员使用：把当前输出冻结为新快照。"""
    os.makedirs(SNAP_DIR, exist_ok=True)
    with open(_path(name), "w", encoding="utf-8") as f:
        json.dump(_norm(got), f, ensure_ascii=False, indent=1)
    print("saved", _path(name))
