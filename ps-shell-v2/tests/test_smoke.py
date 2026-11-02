# -*- coding: utf-8 -*-
import importlib


def test_pysauce_importable():
    import backend.pysauce as ps
    assert ps.__version__ == "2.0.0-dev"


def test_server_module_intact():
    # server.py 复制后应可导入（依赖 numpy/scipy 尚未引入，此卡只查 import 不炸）
    importlib.import_module("backend.server")
