# -*- mode: python ; coding: utf-8 -*-
"""PhoneSauce 嗓音分析助手 2.0 —— PyInstaller（onedir）打包配置。

与 1.2 的 PraatSauce.spec 并列存在，互不干扰：
  1.2 → 入口 ps-shell/app.py      产物 _build/dist/PraatSauceShell
  2.0 → 入口 ps-shell-v2/app.py   产物 _build/dist2/PhoneSauce

所有路径相对本 spec 所在目录推导（本文件在 <仓库根>/packaging/，
仓库根 = packaging 的上一级），不写死任何本机绝对路径。

⚠ 用法务必显式指定 workpath/distpath（否则会与 stage 脚本的组装目录错开，
  把陈旧 exe 当成新构建——这正是 1.2 曾经踩过的坑）：
    pyinstaller packaging/PraatSauce2.spec --clean --noconfirm \
        --workpath _build/build2 --distpath _build/dist2

关于 2.0 与 1.2 spec 的关键差异（见 docs/v2.0-工程卡/V2-G1-打包合规.md §2）：
  1. pathex 加 ps-shell-v2/backend（pysauce 包可达）。
  2. hiddenimports 追加 numpy / scipy / pysauce 全部子模块（逐个列出，不用通配）/
     pylstraight。
  3. datas 追加 vendor/snack.exe 与 scripts/vs_praat/*.praat。
     ⚠ ui/ 与 scripts/ 仍是外部资源（由 stage 脚本复制），不进 exe —— 与 1.2 同策略。
  4. excludes 不再排除 numpy（2.0 核心算法依赖它），改排除 pytest / matplotlib。
  5. 产物目录 dist2，与 1.2 的 dist 分开。

关于壳（窗口模式）依赖：
pywebview/pythonnet/clr_loader 等第三方库解包在 _build/_vendor，
由下方 pathex 引入。换一台机器重打包时若 _vendor 不存在，
先跑 `python packaging/fetch_wheels.py` 重新拉取。
"""

import glob
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# SPECPATH 由 PyInstaller 执行 spec 时注入（= 本 spec 所在目录，即 packaging/）
ROOT = os.path.dirname(SPECPATH)

# 2.0 源码根（与 1.2 的 ps-shell 并列）
V2 = os.path.join(ROOT, "ps-shell-v2")

# 壳模式依赖（pywebview → pythonnet → clr_loader → cffi），缓冲在 _build/_vendor
VENDOR = os.path.join(ROOT, "_build", "_vendor")
if os.path.isdir(VENDOR):
    sys.path.insert(0, VENDOR)

# pywebview 的后端是运行时按平台挑的，静态分析看不出来，必须显式列出；
# pythonnet 的 .NET 程序集（Python.Runtime.dll、WebView2 wrapper）是数据文件，
# 走 collect_* 才会随包带上——缺了它们的表现是"exe 双击没反应"。
hiddenimports = [
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr",
    "pythonnet",
    "pythonnet.runtime",
    "clr_loader",
    "clr_loader.netfx",
    "clr_loader.ffi",
    "cffi",
    "_cffi_backend",
    "pycparser",
    "proxy_tools",
    "bottle",
    "importlib_resources",
    "typing_extensions",
    # ---- 2.0 新增：科学计算栈（1.2 曾把 numpy 排除，2.0 核心算法依赖它）----
    "numpy",
    "scipy",
    "scipy.signal",
    "scipy.fft",
    "scipy.linalg",
    "scipy.optimize",
    # ---- 2.0 新增：STRAIGHT 近似（E3 已装则进包；缺失不阻断打包）----
    "pylstraight",
]

# ---- 2.0 新增：pysauce 及其全部子模块（逐个列出，不用通配——PyInstaller 通配不可靠）----
# 用 glob 在打包时枚举真实存在的模块，避免手写清单与代码脱节；
# 生成的是显式模块名列表（非通配），符合 G1 卡 §2.2 要求。
_PYSAUCE_ROOT = os.path.join(V2, "backend", "pysauce")
if os.path.isdir(_PYSAUCE_ROOT):
    for _dp, _dn, _fn in os.walk(_PYSAUCE_ROOT):
        _dn[:] = [d for d in _dn if d != "__pycache__"]
        for _f in sorted(_fn):
            if not _f.endswith(".py"):
                continue
            _rel = os.path.relpath(os.path.join(_dp, _f), _PYSAUCE_ROOT)[:-3]
            _rel = _rel.replace(os.sep, ".")
            _mod = "pysauce" if _rel == "__init__" else "pysauce." + _rel
            if _mod.endswith(".__init__"):
                _mod = _mod[: -len(".__init__")]
            if _mod not in hiddenimports:
                hiddenimports.append(_mod)

datas = (
    collect_data_files("webview")
    + collect_data_files("pythonnet")
    + collect_data_files("clr_loader")
)
binaries = collect_dynamic_libs("pythonnet")

# ---- 2.0 新增：随包数据 ----
# vendor/snack.exe：Snack 引擎（算法复刻路径默认不用它；保留以支持 strategy="exe" 对拍）
_snack = os.path.join(V2, "vendor", "snack.exe")
if os.path.exists(_snack):
    datas.append((_snack, "vendor"))
# scripts/vs_praat/*.praat：VoiceSauce 版 Praat 脚本（F0/共振峰蓝本脚本复制）
for _p in glob.glob(os.path.join(V2, "scripts", "vs_praat", "*.praat")):
    datas.append((_p, os.path.join("scripts", "vs_praat")))

a = Analysis(
    [os.path.join(V2, "app.py")],
    pathex=[os.path.join(V2, "backend"), V2, VENDOR],
    binaries=binaries,
    # 程序自身的资源（ui/、scripts/、samples/、praat.exe、vowel_ref.json）一律不进包，
    # 由 packaging/stage2.py 在打包后复制到 exe 同目录。这样改界面、改脚本、换示例
    # 都不必重新编译 exe —— 只有后端 Python 变了才需要重打包（"一个 exe + 资源"）。
    # 注：上方 collect_* 收的是第三方库自己的数据（.NET 程序集），与本条不冲突。
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 2.0 依赖 numpy/scipy，不能再排除 numpy（与 1.2 的关键差异）
        "PIL", "pillow", "lxml", "pandas",
        # 测试/绘图不进分发
        "pytest", "_pytest", "matplotlib",
        # ---- 瘦身：pylstraight 真实依赖只有 numpy/scipy/soundfile/cffi，
        #      但 PyInstaller 的 hook 会把本机 site-packages 里「已安装但无人 import」
        #      的重型包一并收集（实测 torch 365M + cv2 99M + imageio_ffmpeg 84M +
        #      onnxruntime 29M + torchvision 12M ≈ 590M 全是垃圾）。全部显式排除。----
        "torch", "torchvision", "torchaudio",
        "cv2", "onnxruntime", "imageio", "imageio_ffmpeg", "tifffile",
        "sympy", "networkx", "sklearn", "scikit-image", "skimage",
        "IPython", "jupyter", "notebook", "nbformat", "nbconvert",
        "tkinter",
        # pywebview 的其它 GUI 后端，Windows 上用不到，排除以免拖进无关依赖
        "PyQt5", "PyQt6", "PySide2", "PySide6", "gi", "cefpython3",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PhoneSauce",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PhoneSauce",
)
