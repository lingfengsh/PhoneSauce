# -*- coding: utf-8 -*-
"""v2 测试公共配置：把 ps-shell-v2 插到 sys.path 最前，保证 `backend` 解析到 v2。"""
import os
import sys

V2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if V2_ROOT not in sys.path:
    sys.path.insert(0, V2_ROOT)

FIX = os.path.join(V2_ROOT, "tests", "fixtures")
