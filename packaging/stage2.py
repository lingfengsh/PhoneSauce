# -*- coding: utf-8 -*-
"""组装分发包 PhoneSauce（2.0）：把 exe 之外的全部资源复制进 PyInstaller 的 dist2 目录。

这是 packaging/stage.py（1.2 现役）的 2.0 对应版，两者并列存在、互不干扰：
  1.2 → 源 ps-shell/        → 组装 _build/dist/PraatSauceShell
  2.0 → 源 ps-shell-v2/     → 组装 _build/dist2/PhoneSauce

与 1.2 stage.py 的差异点（逐条）：
  1. OUT 改 _build/dist2（与 PraatSauce2.spec 的 --distpath 对齐）。
  2. UI_SRC / VOWEL_REF_SRC / 新鲜度检查源目录 改指向 ps-shell-v2/。
  3. scripts/ 除根 scripts/*.praat（25 个）外，额外复制 scripts/vs_praat/*.praat
     （VoiceSauce 版 F0/共振峰脚本，2 个）到分发根 scripts/vs_praat/。
  4. 许可证复制追加 2.0 新增的 LICENSES/Apache-2.0.txt、GPL-2.0.txt、BSD-2-Clause.txt。
  5. 构建版本指纹改取 ps-shell-v2 的文件，并追加 vs.js / vs.html / pysauce 关键模块。

「一个 exe + 按需复制资源」：exe 只装 Python 运行时与后端代码，
scripts/、samples/、ui/、vowel_ref.json、praat.exe、帮助文档一律外部复制。

流程：
  1. 先跑（workpath/distpath 必须与下面的 OUT 一致）：
       pyinstaller packaging/PraatSauce2.spec --clean --noconfirm \
           --workpath _build/build2 --distpath _build/dist2
     —— 产出 _build/dist2/PhoneSauce（exe + _internal）
  2. 再跑本脚本 —— 往同一个目录里补 scripts/、samples/、ui/、vowel_ref.json、
     praat.exe、入手简介.txt（不删除 exe/_internal，只刷新资源子目录）
"""
import os
import shutil
import time

# 路径一律由本脚本位置推导（本脚本位于 <仓库根>/packaging/），不写死任何机器绝对路径。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 必须与 PyInstaller 的 --distpath 一致。两边一旦错开，就会把陈旧 exe 当成新构建
# 同步进分发 —— 这是过去"改了却没生效"的根因，故此处强绑定同一目录。
OUT = os.path.join(ROOT, "_build", "dist2", "PhoneSauce")

# 2.0 源码根
V2 = os.path.join(ROOT, "ps-shell-v2")

# 运行时 Praat 脚本的唯一副本（根级统一后不再散落 praatsauce-master/src 与 ps-shell/praat）
SCRIPT_SOURCES = [
    os.path.join(ROOT, "scripts"),
]
# 2.0 新增：VoiceSauce 版 Praat 脚本（F0/共振峰蓝本脚本复制），复制到 scripts/vs_praat/
VS_PRAAT_SRC = os.path.join(V2, "scripts", "vs_praat")

UI_SRC = os.path.join(V2, "ui")           # 界面：外部资源，不进 exe
VOWEL_REF_SRC = os.path.join(V2, "backend", "vowel_ref.json")

SAMPLES_SRC = os.path.join(V2, "samples")
README_SRC = os.path.join(ROOT, "packaging", "入手简介2.txt")
# 完整使用手册：由 build_usage_doc.py 生成到 docs/，随包分发给使用者
MANUAL_SRC = os.path.join(ROOT, "docs", "PraatSauce使用说明.docx")
# 2.0 增补说明（md）：登记 2.0 相对 1.2 的使用者可见变化，随包提供
MANUAL2_SRC = os.path.join(ROOT, "docs", "v2.0-使用说明增补.md")
PRAAT_SRC = os.path.join(ROOT, "praat.exe")  # 仓库根自带 Praat 引擎，打包进分发根目录


def _reset_dir(dst):
    """清空并重建 dst（不存在则直接建）。

    不在打包链路上硬依赖 shutil.rmtree：在受管/沙箱环境里 rmtree 会被替换成
    走回收站的实现，遇到深层目录会抛 OSError（SHFileOperationW 0x2），
    表现是「脚本跑到一半中断、目录被删了个半空」。删不掉就改名移出到
    _build/_trash（同盘、不进分发包）后重建，保证打包永远能继续。
    """
    if os.path.isdir(dst):
        try:
            shutil.rmtree(dst)
        except OSError as exc:
            # 受管环境的 rmtree 往往是「内容已删净、收尾 rmdir 时目录已不存在」
            # 才报 0x2。所以必须先复查：真没了就算删成功；还在才改名移出。
            if os.path.isdir(dst):
                trash = os.path.join(ROOT, "_build", "_trash")
                os.makedirs(trash, exist_ok=True)
                target = os.path.join(
                    trash, "%s_%d" % (os.path.basename(dst), int(time.time())))
                try:
                    os.rename(dst, target)
                    print("⚠ rmtree 失败（%s），已改名移出：%s" % (exc, target))
                except OSError as exc2:
                    print("⚠ 无法清空 %s（%s），改为覆盖复制" % (dst, exc2))
    os.makedirs(dst, exist_ok=True)


def stage_praat():
    """把仓库根的 praat.exe 复制到分发根目录，与主程序 PhoneSauce.exe 同级。

    冻结态 settings.py 默认 praatExe = <exe 目录>/praat.exe，因此必须随包提供，
    否则首次启动默认路径指向一个不存在的文件。
    """
    if os.path.exists(PRAAT_SRC):
        dst = os.path.join(OUT, "praat.exe")
        shutil.copy2(PRAAT_SRC, dst)
        print("praat.exe 已复制到根目录（%d 字节）" % os.path.getsize(dst))
    else:
        print("⚠ 找不到仓库根 praat.exe，请确认：", PRAAT_SRC)


def stage_scripts():
    dst = os.path.join(OUT, "scripts")
    _reset_dir(dst)
    collisions = {}
    for src in SCRIPT_SOURCES:
        if os.path.isfile(src):
            files = [os.path.basename(src)]
            base_dir = os.path.dirname(src)
        else:
            files = [f for f in os.listdir(src) if f.lower().endswith(".praat")]
            base_dir = src
        for f in files:
            sp = os.path.join(base_dir, f)
            dp = os.path.join(dst, f)
            if os.path.exists(dp):
                collisions.setdefault(f, []).append(sp)
            shutil.copy2(sp, dp)
    print("scripts/ 复制完成，共 %d 个 .praat 文件" % len(os.listdir(dst)))
    if collisions:
        print("⚠ 文件名冲突（已用后者覆盖）：")
        for f, lst in collisions.items():
            print("   ", f, "<=", lst)
    else:
        print("（无文件名冲突）")


def stage_vs_praat():
    """2.0 新增：复制 scripts/vs_praat/*.praat 到分发根 scripts/vs_praat/。

    这些是 VoiceSauce 版（vs 界面）的 Praat 蓝本脚本副本，运行时由
    praat_f0 / praat_fmt 引擎按相对路径 scripts/vs_praat/ 调用。
    """
    if not os.path.isdir(VS_PRAAT_SRC):
        print("⚠ 找不到 vs_praat 脚本源目录：", VS_PRAAT_SRC)
        return
    dst = os.path.join(OUT, "scripts", "vs_praat")
    _reset_dir(dst)
    n = 0
    for f in sorted(os.listdir(VS_PRAAT_SRC)):
        if f.lower().endswith(".praat"):
            shutil.copy2(os.path.join(VS_PRAAT_SRC, f), os.path.join(dst, f))
            n += 1
    print("scripts/vs_praat/ 复制完成，共 %d 个 .praat 文件" % n)


# 这些目录是 Praat 的工作/中间产物（重采样、对象缓存、结果备份、历史结果），
# 不是原始示例音频，必须整目录排除，否则会把派生 .wav 当示例带进来。
WORKING_DIR_BLACKLIST = {'Resample', 'measure', 'output', '历史结果'}


def stage_samples():
    """示例音频：只保留 samples/1、samples/2 两个发音人目录里的 .wav（用户 2026-10-19 定）。

    - 1 = 女声，2 = 男声；默认「示例文件走一遍」只分析 samples/1。
    - 批量扫描是非递归的，所以默认示例目录必须指到子目录，不能指 samples 根。
    - **只复制 .wav**：TextGrid（标注）以及 measure/、output/、Resample/、历史结果
      等派生物一律不带。
    """
    dst_root = os.path.join(OUT, "samples")
    _reset_dir(dst_root)
    count = 0
    for dirpath, dirnames, filenames in os.walk(SAMPLES_SRC):
        # 不进入工作/中间目录（Resample / measure / output / 历史结果 / _bak*）
        dirnames[:] = [d for d in dirnames
                       if d not in WORKING_DIR_BLACKLIST and not d.startswith("_bak")]
        for fn in filenames:
            if not fn.lower().endswith(".wav"):
                continue
            sp = os.path.join(dirpath, fn)
            rel = os.path.relpath(sp, SAMPLES_SRC)
            dp = os.path.join(dst_root, rel)
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            shutil.copy2(sp, dp)
            count += 1
    print("samples/ 复制完成，共 %d 个 .wav（1=女声 2=男声，不含 TextGrid/measure）" % count)


def stage_ui():
    """界面资源：外部复制，不进 exe —— 改界面无须重新编译。"""
    if not os.path.isdir(UI_SRC):
        print("⚠ 找不到界面源目录：", UI_SRC)
        return
    dst = os.path.join(OUT, "ui")
    _reset_dir(dst)
    shutil.copytree(UI_SRC, dst, dirs_exist_ok=True)
    # 防「exe 读到旧界面」：exe 的资源定位 _resource() 优先找 <exe>/_internal/ui，
    # 而那里可能是历史打包/同步残留的旧界面。发现即清除，强制 exe 回退读取本函数
    # 复制的顶层 ui/（与源码一致的唯一真相）。
    for stale in (os.path.join(OUT, "_internal", "ui"),
                  os.path.join(OUT, "_internal", "vowel_ref.json")):
        try:
            if os.path.isdir(stale):
                shutil.rmtree(stale)
                print("⚠ 已清除残留：%s" % stale)
            elif os.path.exists(stale):
                os.remove(stale)
                print("⚠ 已清除残留：%s" % stale)
        except OSError as exc:
            print("⚠ 未能清除残留（请手动删除）：%s —— %s" % (stale, exc))
    print("ui/ 复制完成，共 %d 个文件" % len(os.listdir(dst)))


def stage_vowel_ref():
    """元音参考数据：外部复制，不进 exe。"""
    if os.path.exists(VOWEL_REF_SRC):
        shutil.copy2(VOWEL_REF_SRC, os.path.join(OUT, "vowel_ref.json"))
        print("vowel_ref.json 已复制")
    else:
        print("⚠ 找不到：", VOWEL_REF_SRC)


def _check_freshness():
    """拦截「把陈旧 exe 当新构建」：exe 比源码旧就报警。"""
    exe = os.path.join(OUT, "PhoneSauce.exe")
    if not os.path.exists(exe):
        print("⚠ 缺少主程序：", exe)
        return
    newest_src = 0
    # 只比「进 exe 的东西」：后端 Python。ui/ 与 scripts/ 是外部资源。
    for base in (os.path.join(V2, "backend"),
                 os.path.join(V2, "app.py")):
        targets = [base] if os.path.isfile(base) else [
            os.path.join(dp, f) for dp, _dn, fn in os.walk(base) for f in fn]
        for p in targets:
            if p.endswith((".py", ".js", ".html", ".css")):
                try:
                    newest_src = max(newest_src, os.path.getmtime(p))
                except OSError:
                    pass
    if newest_src and os.path.getmtime(exe) < newest_src:
        print("⚠ 陈旧构建：exe(%s) 早于后端源码(%s)，请先重新运行 pyinstaller"
              % (time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(exe))),
                 time.strftime("%H:%M:%S", time.localtime(newest_src))))
    else:
        print("新鲜度检查：exe 不早于后端源码 ✓（界面/脚本为外部资源，不需重编译）")


def stage_readme():
    if os.path.exists(README_SRC):
        shutil.copy2(README_SRC, os.path.join(OUT, "入手简介.txt"))
        print("入手简介.txt 已复制")
    else:
        print("⚠ 找不到使用说明源文件：", README_SRC)


def stage_manual():
    """完整使用手册（docx）+ 2.0 增补说明（md）复制进分发根目录。

    docx 仍是 1.2 版《PraatSauce使用说明》（2.0 正式正文更新由用户另行安排，
    见 docs/v2.0-使用说明增补.md 头部说明）；增补 md 登记 2.0 相对 1.2 的
    使用者可见变化（引擎切换、双跑对比、输出列等），随包提供以免使用者困惑。
    """
    if os.path.exists(MANUAL_SRC):
        dst = os.path.join(OUT, os.path.basename(MANUAL_SRC))
        shutil.copy2(MANUAL_SRC, dst)
        print("使用说明 docx 已复制（%.1f KB）" % (os.path.getsize(dst) / 1024.0))
    else:
        print("⚠ 找不到使用手册：", MANUAL_SRC)
    if os.path.exists(MANUAL2_SRC):
        dst = os.path.join(OUT, os.path.basename(MANUAL2_SRC))
        shutil.copy2(MANUAL2_SRC, dst)
        print("2.0 使用说明增补 已复制（%.1f KB）" % (os.path.getsize(dst) / 1024.0))
    else:
        print("⚠ 找不到 2.0 使用说明增补：", MANUAL2_SRC)


def stage_licenses():
    """把许可证与第三方声明复制进分发根目录。

    这是 GPL 合规的硬要求：分发包里带了 praat.exe（GPL-3.0-or-later），
    就必须同时提供 GPL 全文、Praat 的版权/版本说明与源码获取地址。
    2.0 追加 Apache-2.0（OpenSauce / pylstraight）、GPL-2.0（Snack）、
    BSD-2-Clause（fminsearchbnd）全文 —— 见 THIRD-PARTY-NOTICES.md §5–§9。
    """
    pairs = [
        # 2.0 起本项目自身的 LICENSE / NOTICES 用 ps-shell-v2 版（产品名 PhoneSauce、
        # 含 §2b opensauce-python 的 SHR attribution）；仓库根两份是 1.2 的，不再进 2.0 包
        (os.path.join(V2, "LICENSE"), "LICENSE"),
        (os.path.join(V2, "THIRD-PARTY-NOTICES.md"), "THIRD-PARTY-NOTICES.md"),
        (os.path.join(ROOT, "LICENSES", "GPL-3.0.txt"), os.path.join("LICENSES", "GPL-3.0.txt")),
        (os.path.join(ROOT, "LICENSES", "PraatSauce-MIT.txt"), os.path.join("LICENSES", "PraatSauce-MIT.txt")),
        # ---- 2.0 新增三个许可全文 ----
        (os.path.join(ROOT, "LICENSES", "Apache-2.0.txt"), os.path.join("LICENSES", "Apache-2.0.txt")),
        (os.path.join(ROOT, "LICENSES", "GPL-2.0.txt"), os.path.join("LICENSES", "GPL-2.0.txt")),
        (os.path.join(ROOT, "LICENSES", "BSD-2-Clause.txt"), os.path.join("LICENSES", "BSD-2-Clause.txt")),
    ]
    ok = 0
    for src, rel in pairs:
        dst = os.path.join(OUT, rel)
        if not os.path.exists(src):
            print("⚠ 缺少许可证文件：", src)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        ok += 1
    print("许可证文件已复制 %d/%d（Praat 为 GPL-3.0-or-later，必须随包附全文）" % (ok, len(pairs)))


def stage_version():
    """构建版本标识：让「新包 vs 旧包」一眼可辨。含构建时间与关键文件指纹。"""
    import hashlib
    lines = ["PhoneSauce 嗓音分析助手 2.0 构建版本", "构建时间: " + time.strftime("%Y-%m-%d %H:%M:%S")]
    for f in ("ps-shell-v2/backend/settings.py", "ps-shell-v2/backend/server.py",
              "ps-shell-v2/ui/app.js", "ps-shell-v2/ui/vs.js",
              "ps-shell-v2/ui/vs.html",
              "ps-shell-v2/backend/pysauce/engine.py"):
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            h = hashlib.md5(open(p, "rb").read()).hexdigest()[:8]
            lines.append("%s  %s" % (h, os.path.basename(f)))
    with open(os.path.join(OUT, "构建版本.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("构建版本.txt 已生成")


if __name__ == "__main__":
    if not os.path.isdir(os.path.join(OUT, "_internal")):
        print("⚠ 未检测到 %s\\_internal，请先运行 pyinstaller 生成 exe。" % OUT)
    os.makedirs(OUT, exist_ok=True)
    _check_freshness()
    stage_praat()
    stage_scripts()
    stage_vs_praat()
    stage_samples()
    stage_ui()
    stage_vowel_ref()
    stage_readme()
    stage_manual()
    stage_licenses()
    stage_version()
    print("\n分发包目录：", OUT)
