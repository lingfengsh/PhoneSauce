# -*- coding: utf-8 -*-
"""本地 HTTP 后端：界面通过它读目录、生成参数、调用 Praat、取回结果。

做成 HTTP 而不是直接嵌进窗口，是为了让同一套界面
既能跑在原生窗口里，也能跑在普通浏览器里。
"""

import os
import csv
import json
import re
import time
import uuid
import string
import secrets
import threading
import traceback
import tempfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from . import settings, params_schema as schema, params_io, praat, audio, results, measures_extra
from . import params_validate, safety, errors_i18n
from . import (health, transcode, tgmatch, profiles, probe, review_build,
               review_profiles, review_choice)
from . import review_grid, syllables, preprocess, review_export, series_export
from . import working_dir
from . import selfcheck

if settings.IS_FROZEN:
    # 冻结态：UI 静态文件由 PyInstaller 随包，落在 exe 同目录的 _internal/ui/ 下
    UI_DIR = settings._resource("ui")
else:
    UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".json": "application/json; charset=utf-8",
}


# ------------------------------------------------------------------ 任务

class Job:
    def __init__(self, kind, values, total=0):
        self.id = uuid.uuid4().hex[:8]
        self.kind = kind  # preview | batch
        self.status = "queued"
        self.values = values
        self.log = []
        self._lock = threading.Lock()
        self.progress = {"done": 0, "total": total, "current": ""}
        self.stop_event = threading.Event()
        self.result_path = None
        self.error = None
        self.error_file = None
        self.summary = None
        self.started = time.time()
        self.elapsed = None

    def add_log(self, text, tag="out"):
        text = (text or "").rstrip()
        if not text:
            return
        with self._lock:
            self.log.append({
                "tag": tag,
                "text": text,
                "ts": round(time.time() - self.started, 2),
            })
            if len(self.log) > 4000:
                self.log = self.log[-2500:]

    def to_dict(self, log_offset=0):
        with self._lock:
            total_lines = len(self.log)
            tail = self.log[log_offset:]
        if self.status == "error" and not self.error_file:
            _dump_error_file(self)
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": dict(self.progress),
            "log": tail,
            "logOffset": total_lines,
            "resultPath": self.result_path,
            "error": self.error,
            "errorFile": self.error_file,
            "summary": self.summary,
            "elapsed": self.elapsed if self.elapsed else round(time.time() - self.started, 1),
        }


def _dump_error_file(job):
    """把完整报错（人类可读信息 + 全部日志，不截断）写成 txt，方便用户整段复制后反馈。"""
    try:
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        # 报错快照写到 <程序根>/logs（用户一眼可见、出问题把整个目录回传即可）；
        # 程序根不可写时 settings.log_dir() 自动回退到 %APPDATA%\PhoneSauce\logs。
        d = os.path.join(settings.log_dir(), "praatsauce_error_%s_%s.txt" % (job.id, ts))
        parts = [
            "PhoneSauce 运行报错",
            "时间: " + ts,
            "任务ID: " + job.id,
            "状态: " + str(job.status),
            "=" * 60,
            "错误信息:",
            job.error or "(无)",
            "=" * 60,
            "完整日志 (%d 行):" % len(job.log),
        ]
        for e in job.log:
            parts.append("[%s] %s" % (e.get("tag", "?"), e.get("text", "")))
        with open(d, "w", encoding="utf-8") as f:
            f.write("\n".join(parts) + "\n")
        job.error_file = d
    except Exception:
        pass


JOBS = {}
JOBS_LOCK = threading.Lock()

# 界面加载后会打一次 ping，用来判断原生窗口里的页面是否真的跑起来了
LAST_PING = {"t": 0.0}

# 每次启动生成一次性 Token：所有 /api/* 请求必须携带（Cookie 自动带上，前端零改动）。
# 防两类攻击：①恶意网页对 127.0.0.1 发跨站 POST（Cookie 是 SameSite=Strict，
# 跨站 fetch 不会带上）；②拿到端口的恶意进程直接打接口（没有 Token 就 403）。
TOKEN = secrets.token_urlsafe(32)


def _get_job(jid):
    with JOBS_LOCK:
        return JOBS.get(jid)


# ------------------------------------------------------------------ 执行

def _ensure_measure_dirs_and_clean(values):
    """批量启动前预处理（2026-09-30 配套 get_pitch/get_formants 路径对齐 + 读回自愈）：

    ① 为每个待处理 wav 建好 ``<wav 所在目录>/measure/``——Praat 自身不能建目录，
       而新路径口径把对象落在 wav 旁边（与审计/第四步一致），父目录必须提前存在，
       否则 Save as text file 会因父目录不存在而失败。
    ② 递归清掉 inputDir 下已有的 0 字节 ``.Pitch``/``.Formant``——这些是「批量跑一半手动停止」
       留下的中断坏文件。读回分支虽已用 nocheck 自愈（损坏即重算覆盖），但提前清掉能让
       第四步在批量前就恢复正常，并顺手清理旧版批量在 ``<inputDir>/measure/<子目录>/``
       留下的孤儿坏文件。有效对象（>0 字节）一律不动，绝不误删。
    """
    _in = (values.get("inputDir") or "").strip()
    if not _in or not os.path.isdir(_in):
        return
    from . import review_export  # 延迟导入，避免模块顶层循环依赖
    # 收集 wav 清单：优先用 filelist，否则递归扫描 inputDir
    wavs = []
    fl = values.get("filelist")
    if fl and os.path.isfile(fl):
        try:
            with open(fl, "r", encoding="utf-8") as _fh:
                for _line in _fh:
                    _line = _line.strip()
                    if not _line:
                        continue
                    _p = _line if os.path.isabs(_line) else os.path.join(_in, _line)
                    if _p.lower().endswith(".wav"):
                        wavs.append(_p)
        except OSError:
            wavs = []
    if not wavs:
        for _root, _dirs, _files in os.walk(_in):
            for _fn in _files:
                if _fn.lower().endswith(".wav"):
                    wavs.append(os.path.join(_root, _fn))
    # ① 建 measure 目录
    for _wav in wavs:
        try:
            os.makedirs(review_export.measure_dir(_wav), exist_ok=True)
        except OSError:
            pass
    # ② 递归清 0 字节对象文件（覆盖新旧两种落盘位置）
    for _root, _dirs, _files in os.walk(_in):
        for _fn in _files:
            if _fn.lower().endswith((".pitch", ".formant")):
                _op = os.path.join(_root, _fn)
                try:
                    if os.path.getsize(_op) == 0:
                        os.remove(_op)
                except OSError:
                    pass


def _prepare(values, preview_file=None, job=None):
    """写出 params.csv，返回 (csv_path, exe, script_dir, workdir)。"""
    cfg = settings.load()
    exe = settings.resolve_praat_exe(cfg)
    sdir = settings.resolve_script_dir(cfg)
    # 试跑也用独立子目录：两个并发试跑不再互相覆盖 filelist/params/进度文件
    workdir = os.path.join(settings.WORK_DIR, job.id if job else uuid.uuid4().hex)
    os.makedirs(workdir, exist_ok=True)

    v = dict(values)
    v.pop("skipCols", None)  # 仅外壳层用的「按列剔除」标记，不写进 praat 的 params.csv
    # 重采样后工作目录自动切到 Resample/（见 working_dir）。批量（非试跑）统一用工作副本，
    # 否则会把原始目录(samples/1)与 Resample/ 两套同名文件都扫进来 → 互相覆盖 / 空白。
    # 试跑是用户单文件显式选择，保留其原目录不动。
    _in_raw = (v.get("inputDir") or "").strip()
    if _in_raw and not preview_file:
        v["inputDir"] = working_dir.resolve_working_dir(_in_raw)
        # 中间对象目录同样要跟到工作副本（2026-10-18 事故）：前端/旧档把
        # pitchReadDir 设成「用户选的原始目录」时，批量会去原始目录的 measure/
        # 找对象 —— 那份往往是旧参数留下的，读回来网格对不上就重算并覆盖
        # Resample/measure/ 里审核好的对象。这里统一解析，读写落在同一个副本。
        for _k in ("pitchSaveDir", "pitchReadDir",
                   "formantSaveDir", "formantReadDir"):
            _d = (v.get(_k) or "").strip()
            if _d:
                v[_k] = working_dir.resolve_working_dir(_d)
    # 旧档把布尔 0 存进了 includeTheseLabels（该参数现在是正则）："0" 作正则只匹配
    # 字面标签 "0"，会把所有区间滤光 → 整批 0 行且日志毫无线索。归一到 schema 默认
    # 的「非空标签」正则。
    if (v.get("includeTheseLabels") or "").strip() == "0":
        v["includeTheseLabels"] = r"^(?!\s*$).+"
    # 测量间隔二选一：intervalMode 是外壳层概念，不写进 params.csv；按它把
    # 不生效的那个值归零（Praat 端语义不变：equidistant<>0 用等分，否则用 fixed）。
    try:
        _imode = int(float(v.get("intervalMode", 0) or 0))
    except (TypeError, ValueError):
        _imode = 0
    v.pop("intervalMode", None)
    if _imode == 1:
        v["intervalFixed"] = 0
    else:
        v["intervalEquidistant"] = 0
    # 旧档用 formant/bw 总开关；先摊成 F1–F5 / B1–B3 独立选择，再聚合成脚本要的总开关与数量
    v = schema.normalize_legacy_formants(v)
    v = schema.derive_formant_flags(v)
    if preview_file:
        flist = os.path.join(workdir, "filelist.txt")
        with open(flist, "w", encoding="utf-8") as f:
            f.write(preview_file + "\n")
        v["filelist"] = flist
        v["outputDir"] = workdir
        v["outputFile"] = "preview.tsv"
    else:
        # W4：若前端传来了有效的 filelist（staging 里的完整路径清单）则保留，
        # 让 praatSauce 只处理配对成功的声音；否则按原逻辑弹出。
        fl = v.get("filelist")
        if not (fl and os.path.exists(fl)):
            v.pop("filelist", None)
        # 输出目录留空 → 默认 <音频目录>/output（2026-09-27 方案 A：中间/结果文件
        # 都归子目录，音频目录根只留 wav/TextGrid）。不补写的话 params.csv 里
        # outputDir 为空，Praat 会把结果写到它自己的工作目录（脚本目录），后端却在
        # inputDir 下找——表现为「Praat 没有生成结果文件（退出码 0）」而实际已经算完。
        if not (v.get("outputDir") or "").strip():
            _in = (v.get("inputDir") or "").strip()
            v["outputDir"] = (os.path.join(_in, "output") if _in else workdir)
            if _in:
                os.makedirs(v["outputDir"], exist_ok=True)
        # Pitch/Formant 中间文件统一进 <音频目录>/measure/ 子目录（与九宫格/详情/
        # 审核导出同一口径；用户显式填过的目录尊重不覆盖）。留空的话上游 read_params
        # 会回落到 inputDir，对象文件就散在音频目录根了。
        if v.get("pitchSave") or v.get("pitchRead"):
            _in = (v.get("inputDir") or "").strip()
            _md = _in if _in else ""
            for _k in ("pitchSaveDir", "pitchReadDir"):
                if not (v.get(_k) or "").strip():
                    v[_k] = _md
        if v.get("formantSave") or v.get("formantRead"):
            _in = (v.get("inputDir") or "").strip()
            _md = _in if _in else ""
            for _k in ("formantSaveDir", "formantReadDir"):
                if not (v.get(_k) or "").strip():
                    v[_k] = _md
        ## 批量启动前：确保每个 wav 的 <所在目录>/measure/ 存在（Praat 不能建目录），
        ## 并清掉已有的 0 字节 .Pitch/.Formant（中断存盘遗留的坏文件，否则读回会被永久信任成空白）。
        _ensure_measure_dirs_and_clean(v)

    csv_path = os.path.join(workdir, "params.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write(params_io.build_csv(v, sdir))
    return csv_path, exe, sdir, workdir, v


def _write_filelist(filenames):
    """把选中的文件清单写成临时 txt，供 praatSauce 的 filelist 参数只处理这些文件。"""
    os.makedirs(settings.WORK_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="filelist_", suffix=".txt", dir=settings.WORK_DIR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(str(n) for n in filenames) + "\n")
    return path


def _count_files(values):
    # 若指定了 filelist（前端只选了部分文件），进度总数应以清单为准
    fl = values.get("filelist")
    if fl and os.path.isfile(fl):
        try:
            with open(fl, encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            pass
    ext = (values.get("soundExt") or "wav").strip().lstrip(".")
    d = values.get("inputDir") or ""
    if not os.path.isdir(d):
        return 0
    try:
        return len([n for n in os.listdir(d) if n.lower().endswith("." + ext.lower())])
    except Exception:
        return 0


def _truthy(v):
    """判断参数值是否为「开启」。与 params_schema._truthy 同义，本地副本避免跨模块耦合。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip() not in ("", "0", "false", "False")
    return bool(v)


def _textgrid_diag(v):
    """0 行时的补充诊断：声音文件数 vs tgDir 里的 TextGrid 数，帮用户快速定位。

    tgDir 的回退口径与 read_params.praat 一致：path/to/tg 或空 → inputDir。
    出错时返回空串（诊断只是锦上添花，不能把真正的报错顶掉）。
    """
    try:
        fl = v.get("filelist")
        if fl and os.path.isfile(fl):
            with open(fl, encoding="utf-8") as f:
                n_wav = sum(1 for ln in f if ln.strip())
        else:
            n_wav = _count_files(v)
        tg_dir = (v.get("tgDir") or "").strip()
        if not tg_dir or tg_dir == "path/to/tg":
            tg_dir = (v.get("inputDir") or "").strip()
        n_tg = 0
        if tg_dir and os.path.isdir(tg_dir):
            n_tg = sum(1 for n in os.listdir(tg_dir) if n.lower().endswith(".textgrid"))
        return ("诊断：本次声音文件 %d 个；TextGrid 目录 [%s] 里找到 %d 个 .TextGrid。"
                % (n_wav, tg_dir or "（空）", n_tg))
    except Exception:
        return ""


def _batch_wavs(v):
    """本批实际要处理的 wav 清单：优先 filelist，否则递归扫 inputDir。"""
    _in = (v.get("inputDir") or "").strip()
    wavs = []
    fl = v.get("filelist")
    if fl and os.path.isfile(fl):
        try:
            with open(fl, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    p = line if os.path.isabs(line) else os.path.join(_in, line)
                    if p.lower().endswith(".wav"):
                        wavs.append(p)
        except OSError:
            wavs = []
    if not wavs and _in and os.path.isdir(_in):
        for root, _dirs, files in os.walk(_in):
            for fn in files:
                if fn.lower().endswith(".wav"):
                    wavs.append(os.path.join(root, fn))
    return wavs


def _reuse_report(v, started):
    """说明本批的 F0 / 共振峰对象是「复用 measure 里已审核的」还是「刚重算的」。

    Praat 端（get_pitch / get_formants）读分支命中就不计算；但日志里原先没有一行
    交代这件事，用户审完第四步再点批量，会怀疑参数被重新算了一遍。判断依据是对象
    文件的修改时间：早于任务开始 = 复用，晚于 = 本次重算/新存。
    """
    from . import review_export  # 延迟导入，避免模块顶层循环依赖
    wavs = _batch_wavs(v)
    if not wavs:
        return "中间对象：本批没有找到音频，无法统计复用情况。"
    stat = {"pitchOld": 0, "pitchNew": 0, "formOld": 0, "formNew": 0,
            "pitchAll": 0, "formAll": 0}
    for w in wavs:
        for ext, key in ((".Pitch", "pitch"), (".Formant", "form")):
            p = os.path.join(review_export.measure_dir(w),
                             os.path.splitext(os.path.basename(w))[0] + ext)
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            stat[key + "All"] += 1
            stat[key + ("Old" if mt < started else "New")] += 1
    parts = []
    if _truthy(v.get("pitchRead")):
        parts.append("F0 复用 %d 个已审核的 .Pitch（未重算），本批新算/重写 %d 个"
                     % (stat["pitchOld"], stat["pitchNew"]))
    elif _truthy(v.get("pitchSave")):
        parts.append("F0 本批强制重算（复用开关关闭），共 %d 个文件" % stat["pitchAll"])
    if _truthy(v.get("formantRead")):
        parts.append("共振峰复用 %d 个已审核的 .Formant（未重算），本批新算/重写 %d 个"
                     % (stat["formOld"], stat["formNew"]))
    elif _truthy(v.get("formantSave")):
        parts.append("共振峰本批强制重算（复用开关关闭），共 %d 个文件" % stat["formAll"])
    if not parts:
        return "中间对象：本批没有开启 .Pitch/.Formant 存盘或复用。"
    return "中间对象：" + "；".join(parts) + "。"


def _execute(job, values, preview_file=None):
    try:
        job.status = "running"
        cfg = settings.load()
        job.add_log("Praat: " + (cfg.get("praatVersion") or cfg.get("praatExe") or ""))
        csv_path, exe, sdir, workdir, v = _prepare(values, preview_file, job)

        if not exe or not os.path.exists(exe):
            job.status = "error"
            job.error = "没有找到 Praat 程序。请到「设置」里指定 Praat.exe 的位置。"
            return

        out_file = v.get("outputFile") or "out.tsv"
        # outputDir 为空时 _prepare 已补成 <音频目录>/output；这里兜底（旧调用直跑 _execute）
        out_dir = v.get("outputDir") or v.get("inputDir") or workdir
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            job.status = "error"
            job.error = f"无法创建输出目录：{e}"
            return
        result_path = os.path.join(out_dir, out_file)

        # W4 结果归档防覆盖：批量且上一版结果已存在时，先归档再让 Praat 覆盖。
        # preview 的结果写在临时工作区，不归档。
        if not preview_file and os.path.exists(result_path):
            try:
                archived = safety.archive_previous_result(result_path)
                if archived:
                    job.add_log(f"已归档上一版结果 → {archived}")
            except Exception as e:
                job.add_log(f"归档上一版结果失败：{e}", "err")

        total = 1 if preview_file else _count_files(values)
        job.progress["total"] = total or 1

        # 实时进度旁路：Praat 的 stdout 在管道下是全缓冲的（实测所有
        # Processing 行到进程退出才一次性到达），进度条只能 0% 干等后跳 100%。
        # praatSauce.praat 已打补丁（form 第二参数 progressloc）：每开始处理
        # 一个文件，就把文件名追加到 ps_progress.txt（文件写入不缓冲）。
        # 进度文件属中间文件，放任务临时目录、不进声音/结果目录；这里起读线程
        # 轮询它，实时更新进度条并往日志里补 Processing 行。
        progress_path = os.path.join(workdir, "ps_progress.txt")
        stop_watch = threading.Event()

        def watch_progress():
            seen = 0
            while not stop_watch.is_set():
                try:
                    with open(progress_path, encoding="utf-8") as f:
                        names = [ln.strip() for ln in f if ln.strip()]
                except OSError:
                    names = []
                if len(names) > seen:
                    for n in names[seen:]:
                        job.add_log("Processing " + n, "out")
                    seen = len(names)
                    job.progress["done"] = min(seen, job.progress["total"])
                    job.progress["current"] = names[-1]
                stop_watch.wait(0.4)

        threading.Thread(target=watch_progress, daemon=True).start()

        def on_line(line, tag):
            # stdout 里的 Processing 行因缓冲要到结束才到达，进度已由
            # watch_progress 实时上报，这里跳过以防日志与进度重复计一次。
            if line.startswith("Processing"):
                return
            job.add_log(line, tag)
            if "All done" in line:
                job.progress["done"] = job.progress["total"]

        job.add_log("$ praat --run praatSauce.praat " + csv_path)
        rc, _ = praat.run_script(
            exe, "praatSauce.praat", [csv_path, progress_path], cwd=sdir,
            on_line=on_line, stop_event=job.stop_event, timeout=6 * 3600,
            full_trust=True,
        )
        stop_watch.set()
        try:
            os.remove(progress_path)
        except OSError:
            pass
        job.elapsed = round(time.time() - job.started, 1)

        if job.stop_event.is_set():
            job.status = "cancelled"
            return

        # 归档是「复制」不是移动：Praat 失败时上一版结果仍在原位，只查
        # 文件是否存在会把旧结果当成本次结果（界面还不报错=静默成功）。
        # 因此要求结果文件是本次运行新写的（修改时间晚于任务开始时间）。
        try:
            fresh = os.path.getmtime(result_path) > job.started
        except OSError:
            fresh = False
        if not fresh:
            job.status = "error"
            human = errors_i18n.translate_log_tail(job.log)
            # 不把「最近日志」拼进报错文案：界面日志框里已有完整日志（且是
            # 实时流式的），报错文件里也会整段附上，重复展示只混淆视线。
            job.error = human or f"Praat 没有生成结果文件（退出码 {rc}）。"
            return

        # 外接补算：SHR（CPPS 已由 Praat 侧 ps_get_CPPS.praat 直出，无需补算）
        if int(v.get("shr", 0) or 0):
            try:
                ok, msg = measures_extra.augment_result(
                    result_path, v,
                    log_fn=lambda text, tag="out": job.add_log(text, tag))
                if ok:
                    job.add_log(msg)
                else:
                    job.add_log(msg, "err")
            except Exception as e:
                job.add_log(f"SHR/CPPS 补算失败：{e}", "err")

        job.result_path = result_path
        # 让「第四步审核过的曲线，批量时到底有没有被重算」这件事可见（2026-10-18）：
        # Praat 端优先读 <wav 目录>/measure/<主名>.Pitch / .Formant，命中就不计算。
        # 这里按对象文件的修改时间给出「复用 / 重算」的准确交代，避免用户怀疑白审了。
        try:
            job.add_log(_reuse_report(v, job.started))
        except Exception as e:
            job.add_log(f"对象复用统计失败：{e}", "err")
        # 逐列剔除：前端「要测哪些 / 结果行」里点掉的列，从结果表（含导出 CSV）真正去掉
        _skip = [s.strip() for s in str(values.get("skipCols", "")).split(",") if s.strip()]
        # 按所选共振峰/带宽列自动剔除未勾选的 F/B 列：Praat 照算全部，这里只留选中的
        for n in ("1", "2", "3", "4", "5"):
            if not _truthy(values.get("formant" + n)):
                _skip.append("F" + n)
        for n in ("1", "2", "3"):
            if not _truthy(values.get("bw" + n)):
                _skip.append("B" + n)
        # 谐波幅度 / 频谱斜率 / HNR：逐列剔除未勾选的 H*/HNR* 列
        for nm in schema.HARMONIC_C + schema.HARMONIC_U + schema.SLOPE_C + schema.SLOPE_U + schema.HNR_PARAMS:
            if not _truthy(values.get(nm)):
                _col = (schema.BY_NAME.get(nm) or {}).get("cols")
                if _col:
                    _skip.append(_col[0])
        _skip = list(dict.fromkeys(_skip))
        if _skip:
            try:
                results.drop_columns(result_path, _skip)
                job.add_log("已按选择剔除 %d 个未选列" % len(_skip))
            except Exception as e:
                job.add_log("剔除列失败：%s" % e, "err")
        # 结果数值统一舍入（2026-09-26 用户定案，默认开启）：时间列不动，
        # HNR* / CPP 两位小数，其余一位小数。前端「结果数值按规则舍入」可关掉。
        if _truthy(values.get("roundValues", 1)):
            try:
                n = results.round_result(result_path)
                if n:
                    job.add_log(f"已按列规则舍入 {n} 个数值（时间列不动；HNR/CPP 两位小数，其余一位）")
            except Exception as e:
                job.add_log(f"数值舍入失败：{e}", "err")
        # 试跑要把全部帧传回前端画曲线；批量只回传摘要
        table = results.read_table(result_path, max_rows=5000 if preview_file else 200)
        diag = results.diagnose(result_path, v)

        # W3.2 空结果拦截（仅批量）：批量结束但没有任何数据行
        if not preview_file and table.get("total", 0) == 0:
            job.status = "error"
            human = errors_i18n.translate_log_tail(job.log)
            job.error = ("批量结束但没有产生任何数据行。常见原因：目录里没有匹配的音频、"
                         "TextGrid 标签筛选过严。请查看上方日志。")
            _tg = _textgrid_diag(v)
            if _tg:
                job.error += "\n" + _tg
            if human:
                job.error = human + "\n\n" + job.error
            return

        # W3.3 全列检出率为 0：f0 与 F1 两列检出率均为 0
        stats = diag.get("stats", {})
        f0s = stats.get("f0")
        f1s = stats.get("F1")
        empty_all = (isinstance(f0s, dict) and isinstance(f1s, dict)
                     and f0s.get("ratio", 1) == 0 and f1s.get("ratio", 1) == 0)

        diags = list(diag.get("diagnostics", []))
        if empty_all:
            diags.insert(0, {
                "level": "error",
                "title": "所有帧的基频与共振峰均为空",
                "detail": "大概率是基频范围设置错误，请先用第 3 步试跑一个文件调整范围",
            })

        job.summary = {
            "columns": table.get("columns", []),
            "rowCount": table.get("total", 0),
            "rows": table.get("rows", []),
            "previewRows": table.get("rows", [])[:50],
            "diagnostics": diags,
            "perFile": diag.get("perFile", []),
            "fileCount": diag.get("files", 0),
            "stats": stats,
            "returnCode": rc,
            "emptyResult": empty_all,
        }
        job.status = "done"
    except Exception as e:
        job.status = "error"
        human = errors_i18n.translate_log_tail(job.log)
        job.error = (human + "\n\n" if human else "") + f"{e}\n\n{traceback.format_exc(limit=6)}"
        job.add_log(str(e), "err")


def start_job(kind, values, preview_file=None):
    job = Job(kind, values, 1 if preview_file else _count_files(values))
    with JOBS_LOCK:
        JOBS[job.id] = job
    t = threading.Thread(target=_execute, args=(job, values, preview_file), daemon=True)
    t.start()
    return job


# ------------------------------------------------------------------ 校验

def validate(values, for_preview=False):
    """校验参数。

    for_preview=True 时用于「第 3 步试跑」：试跑结果写在临时工作区，
    不需要「结果输出目录」，故跳过 outputDir 检查，免得用户为了试跑被迫先填输出目录。
    """
    errors = []
    warns = []

    d = (values.get("inputDir") or "").strip()
    # 重采样后工作目录自动切到 Resample/（见 working_dir）：选的是父目录时，wav 实际在
    # Resample/ 里，这里必须按工作副本计数，否则会误报「该目录下没有 wav 文件」。
    d = working_dir.resolve_working_dir(d) if d else d
    if not d:
        errors.append({"field": "inputDir", "msg": "还没有选择声音文件目录"})
    elif not os.path.isdir(d):
        errors.append({"field": "inputDir", "msg": f"目录不存在：{d}"})
    else:
        ext = (values.get("soundExt") or "wav").strip().lstrip(".")
        try:
            n = len([x for x in os.listdir(d) if x.lower().endswith("." + ext.lower())])
        except Exception:
            n = 0
        if n == 0:
            errors.append({"field": "inputDir",
                           "msg": f"在 {d} 下没有找到任何 .{ext} 文件。请确认选的是音频目录、且扩展名设置为 {ext}"})
        elif n > 300:
            warns.append({"field": "inputDir",
                          "msg": f"目录里有 {n} 个文件，批量处理会花较长时间，建议先用「试跑」确认参数"})

    if not for_preview:
        od = (values.get("outputDir") or "").strip()
        if od:
            if not os.path.isdir(od):
                try:
                    os.makedirs(od, exist_ok=True)
                except Exception as e:
                    errors.append({"field": "outputDir", "msg": f"输出目录无法创建：{e}"})
        elif not (values.get("inputDir") or "").strip():
            # 输出目录留空时默认 <音频目录>/output；只有连声音目录都没选才报错
            errors.append({"field": "outputDir",
                           "msg": "输出目录留空会默认放在音频目录的 output 子目录；请先选择声音目录"})

    # 参数取值范围校验（人话版，与 read_params.praat 对齐并加严）
    # 这些规则原本散在下面，现统一移交 params_validate 作为唯一权威，避免重复报错。
    vp = params_validate.validate_params(values)
    errors.extend(vp["errors"])
    warns.extend(vp["warnings"])
    fixed = vp["fixed"]

    measures = ["pitch", "formant1", "formant2", "formant3", "formant4", "formant5",
                "ha_h1c", "ha_h2c", "ha_h4c", "ha_a1c", "ha_a2c", "ha_a3c",
                "hau_h1u", "hau_h2u", "hau_h4u", "hau_a1u", "hau_a2u", "hau_a3u", "hau_h2ku", "hau_h5ku",
                "sl_h1h2c", "sl_h2h4c", "sl_h1a1c", "sl_h1a2c", "sl_h1a3c", "sl_h42ku",
                "slu_h1h2u", "slu_h2h4u", "slu_h1a1u", "slu_h1a2u", "slu_h1a3u", "slu_h2kh5ku",
                "bw1", "bw2", "bw3", "cpp",
                "hnr_05", "hnr_15", "hnr_25", "hnr_35", "hnr_38",
                "intensity", "soe", "shr", "cpps"]
    if not any(int(values.get(m, 0) or 0) for m in measures):
        errors.append({"field": "measures", "msg": "至少要勾选一个要测量的参数"})

    # ---- 基准引擎校验（2.0）----
    # 用户要求：下游参数若需要基于 F0 / 共振峰计算，而 measure/ 里一套基础数据都没有，
    # 就必须先在本步算出 F0 / 共振峰，否则拦住批量（不允许「跑完得到一堆空列」）。
    #
    # 依赖关系（严格照 VoiceSauce 的下游调用）：
    #   F0  → 谐波幅度、频谱斜率、CPP、CPPS、HNR、SoE、SHR、强度
    #   FMT → 谐波幅度（共振峰校正）、频谱斜率（已校正）、带宽
    if d and os.path.isdir(d):
        need_f0 = any(int(values.get(m, 0) or 0) for m in [
            "ha_h1c", "ha_h2c", "ha_h4c", "ha_a1c", "ha_a2c", "ha_a3c",
            "hau_h1u", "hau_h2u", "hau_h4u", "hau_a1u", "hau_a2u", "hau_a3u",
            "hau_h2ku", "hau_h5ku",
            "sl_h1h2c", "sl_h2h4c", "sl_h1a1c", "sl_h1a2c", "sl_h1a3c", "sl_h42ku",
            "slu_h1h2u", "slu_h2h4u", "slu_h1a1u", "slu_h1a2u", "slu_h1a3u", "slu_h2kh5ku",
            "cpp", "cpps", "hnr_05", "hnr_15", "hnr_25", "hnr_35", "hnr_38",
            "soe", "shr", "intensity",
        ])
        need_fmt = any(int(values.get(m, 0) or 0) for m in [
            "ha_h1c", "ha_h2c", "ha_h4c", "ha_a1c", "ha_a2c", "ha_a3c",
            "sl_h1h2c", "sl_h2h4c", "sl_h1a1c", "sl_h1a2c", "sl_h1a3c", "sl_h42ku",
            "bw1", "bw2", "bw3",
        ])
        try:
            from . import review_export as _re
            avail = _re.engine_availability(d, (values.get("soundExt") or "wav").strip().lstrip("."))
        except Exception:
            avail = None
        if avail:
            # 本批是否会现场算 F0 / 共振峰（勾了 pitch / formant1..5 就一定会算）
            will_compute_f0 = int(values.get("pitch", 0) or 0)
            will_compute_fmt = any(int(values.get(f"formant{i}", 0) or 0) for i in range(1, 6))
            if need_f0 and not will_compute_f0 and not avail.get("f0_any"):
                errors.append({
                    "field": "f0BaseEngine",
                    "msg": "所选参数需要基频（F0）作为基准，但 measure/ 里没有任何 F0 对象，"
                           "本批也没有勾选「基频 F0」。请先勾选 F0 并运行一次，"
                           "或先做全量审查生成 F0。",
                })
            if need_fmt and not will_compute_fmt and not avail.get("formant_any"):
                errors.append({
                    "field": "formantBaseEngine",
                    "msg": "所选参数需要共振峰作为基准，但 measure/ 里没有任何共振峰对象，"
                           "本批也没有勾选 F1–F5。请先勾选共振峰并运行一次，"
                           "或先做全量审查生成共振峰。",
                })
            # 基准引擎指向的那套对象不存在 → 警示（不拦，因为可能本批会算出来）
            f0_base = str(values.get("f0BaseEngine") or "praat").strip().lower()
            fmt_base = str(values.get("formantBaseEngine") or "praat").strip().lower()
            if need_f0 and f0_base in (avail.get("f0") or {}) and not avail["f0"].get(f0_base) \
                    and not will_compute_f0:
                warns.append({"field": "f0BaseEngine",
                              "msg": f"F0 基准选的是 {f0_base}，但 measure/ 里没有该引擎的 F0 对象。"
                                     f"下游 F0 相关列可能全空。"})
            if need_fmt and fmt_base in (avail.get("formant") or {}) and not avail["formant"].get(fmt_base) \
                    and not will_compute_fmt:
                warns.append({"field": "formantBaseEngine",
                              "msg": f"共振峰基准选的是 {fmt_base}，但 measure/ 里没有该引擎的共振峰对象。"
                                     f"下游共振峰相关列可能全空。"})

    if int(values.get("useTextGrid", 0) or 0):
        tg = (values.get("tgDir") or "").strip() or d
        if not os.path.isdir(tg):
            errors.append({"field": "tgDir", "msg": f"TextGrid 目录不存在：{tg}"})
        else:
            ext = (values.get("soundExt") or "wav").strip().lstrip(".")
            try:
                wavs = {os.path.splitext(x)[0] for x in os.listdir(d)
                        if x.lower().endswith("." + ext.lower())}
                tgs = {os.path.splitext(x)[0] for x in os.listdir(tg)
                       if x.lower().endswith(".textgrid")}
            except Exception:
                wavs, tgs = set(), set()
            # ⚠️ TextGrid 不是必需的（2026-10-18 用户定）：有同名标注的文件只测标注段，
            # 没有的测整段——get_times.praat 逐文件回退，praatSauce 结束打 PSA_TG_SUMMARY。
            # 所以数量对不上只能是**提醒**，绝不能拦住批量（旧版这里是 errors，
            # 示例目录 33 个 wav / 0 个 TextGrid 一走就卡死）。
            # fix 字段给前端一个动作线索：点「自动制作 TextGrid」直接进切分九宫格，
            # 而不是又弹一个文件夹选择器（那解决不了"一个标注都没有"）。
            if len(wavs) != len(tgs):
                warns.append({
                    "field": "tgDir", "fix": "tg-make",
                    "msg": f"声音文件 {len(wavs)} 个、TextGrid {len(tgs)} 个，数量对不上。"
                           f"这不是错误：有同名标注的文件只测标注段，没有的测整段。"
                           f"想让所有文件都只测标注段，可以现在自动切分生成。"})
            elif wavs != tgs:
                diff = list((wavs ^ tgs))[:5]
                warns.append({"field": "tgDir", "fix": "tg-match",
                              "msg": "有文件名对不上：" + "、".join(diff) + "（可能只是大小写差异）"})

    cfg = settings.load()
    exe = settings.resolve_praat_exe(cfg)
    if not exe or not os.path.exists(exe):
        errors.append({"field": "praatExe", "msg": "Praat 程序路径无效，请到「设置」里重新指定"})

    sdir = settings.resolve_script_dir(cfg)
    if not os.path.exists(os.path.join(sdir, "praatSauce.praat")):
        errors.append({"field": "scriptDir",
                       "msg": f"在脚本目录里找不到 praatSauce.praat：{sdir}"})

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warns, "fixed": fixed}


# ------------------------------------------------------------------ 文件系统浏览

def list_dir(path, mode="dir", ext=None):
    """给内置选择器用。mode='dir' 只列目录；mode='file' 额外列出文件（可按 ext 过滤）。"""
    if not path:
        drives = []
        for c in string.ascii_uppercase:
            p = f"{c}:\\"
            if os.path.exists(p):
                drives.append({"name": f"{c}:", "path": p, "type": "drive"})
        home = os.path.expanduser("~")
        special = [
            {"name": "桌面", "path": os.path.join(home, "Desktop"), "type": "dir"},
            {"name": "文档", "path": os.path.join(home, "Documents"), "type": "dir"},
            {"name": "下载", "path": os.path.join(home, "Downloads"), "type": "dir"},
            {"name": "用户目录", "path": home, "type": "dir"},
        ]
        return {"ok": True, "path": "", "parent": None,
                "entries": [s for s in special if os.path.isdir(s["path"])] + drives}

    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return {"ok": False, "error": "目录不存在", "path": path}
    entries = []
    try:
        for n in sorted(os.listdir(path)):
            full = os.path.join(path, n)
            is_dir = os.path.isdir(full)
            if not is_dir:
                if mode != "file":
                    continue
                if ext:
                    exts = [e.lower().lstrip(".") for e in ext.split(",")]
                    if not any(n.lower().endswith("." + e) for e in exts):
                        continue
                if n.startswith("."):
                    continue
            if is_dir and (n.startswith(".") or n in ("$RECYCLE.BIN", "System Volume Information")):
                continue
            entries.append({"name": n, "path": full, "type": "dir" if is_dir else "file"})
    except Exception as e:
        return {"ok": False, "error": str(e), "path": path}
    parent = os.path.dirname(path)
    if parent == path:
        parent = ""
    return {"ok": True, "path": path, "parent": parent, "entries": entries}


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 30   # 慢速连接（Slowloris 式）最多占用线程 30 秒

    def log_message(self, fmt, *args):
        pass

    # ---------- 访问守卫：Host / Origin / Token ----------
    def _guard(self):
        """校验请求来自本机界面而非任意来源。返回 False 时调用方回 403。"""
        # Host 校验防 DNS rebinding：解析到 127.0.0.1 的恶意域名会带自己的 Host
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        # 浏览器跨站请求会带 Origin；非本机来源一律拒绝
        origin = self.headers.get("Origin")
        if origin:
            oh = urlparse(origin).hostname or ""
            if oh not in ("127.0.0.1", "localhost"):
                return False
        # Token：优先 X-PS-Token 头，其次本服务种下的 SameSite=Strict Cookie
        tok = self.headers.get("X-PS-Token") or ""
        if not tok:
            m = re.search(r"(?:^|;\s*)PS-Token=([^\s;]+)", self.headers.get("Cookie") or "")
            tok = m.group(1) if m else ""
        return tok == TOKEN

    def handle_one_request(self):
        # 浏览器提前断开很常见，别让 traceback 刷屏吓到用户
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, TimeoutError):
            self.close_connection = True

    # ---------- helpers

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, obj)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        if length > 8 * 1024 * 1024:   # 请求体上限 8MB，防内存耗尽
            self.close_connection = True
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---------- GET

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)

        if p.startswith("/api/") and not self._guard():
            self.close_connection = True
            return self._json({"ok": False, "error": "forbidden"}, 403)

        if p == "/" or p == "/launch.html":
            # 启动先弹界面选择页；已记住选择时由 launch.html 自行跳转
            return self._file(os.path.join(UI_DIR, "launch.html"))
        if p == "/index.html":
            return self._file(os.path.join(UI_DIR, "index.html"))
        if p == "/vs.html":
            return self._file(os.path.join(UI_DIR, "vs.html"))
        if p.startswith("/ui/") or p.endswith((".css", ".js", ".svg", ".png", ".ico")):
            rel = p[4:] if p.startswith("/ui/") else p.lstrip("/")
            # 防路径穿越：规范化后必须仍在 UI_DIR 之内，否则拒绝
            full = os.path.abspath(os.path.normpath(os.path.join(UI_DIR, rel)))
            ui_root = os.path.abspath(UI_DIR)
            if full == ui_root or full.startswith(ui_root + os.sep):
                return self._file(full)
            return self._json({"ok": False, "error": "forbidden"}, 403)

        try:
            if p == "/api/bootstrap":
                return self._json(bootstrap())
            if p == "/api/selfcheck":
                return self._json(selfcheck.run())
            if p == "/api/param-defaults":
                return self._json(get_param_defaults())
            if p == "/api/ping":
                LAST_PING["t"] = time.time()
                return self._json({"ok": True})
            if p.startswith("/api/job/"):
                jid = p.rsplit("/", 1)[-1]
                job = _get_job(jid)
                if not job:
                    return self._json({"ok": False, "error": "任务不存在"}, 404)
                off = int(q.get("offset", ["0"])[0] or 0)
                d = job.to_dict(off)
                d["ok"] = True
                return self._json(d)
            if p == "/api/result":
                path = q.get("path", [""])[0]
                return self._json(result_payload(path))
            if p == "/api/fs":
                return self._json(list_dir(q.get("path", [""])[0],
                                          mode=q.get("mode", ["dir"])[0],
                                          ext=q.get("ext", [""])[0]))
            if p == "/api/review/wav":
                return self._wav_file(q.get("path", [""])[0])
            return self._json({"ok": False, "error": "未知接口"}, 404)
        except Exception as e:
            return self._json({"ok": False, "error": f"{e}\n{traceback.format_exc(limit=5)}"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        if p.startswith("/api/") and not self._guard():
            self.close_connection = True   # 未读请求体就回 403，必须断开 keep-alive
            return self._json({"ok": False, "error": "forbidden"}, 403)
        data = self._body()
        try:
            if p == "/api/scan":
                return self._json(audio.scan_directory(data.get("dir"), data.get("ext", "wav")))
            if p == "/api/textgrid":
                rep = audio.textgrid_report(data.get("wavFiles", []), data.get("tgDir"))
                return self._json(rep)
            if p == "/api/pysauce-results":
                d = (data.get("dir") or "").strip()
                if not d:
                    return self._json({"ok": False, "error": "缺少 dir"})
                return self._json(list_pysauce_results(d))
            if p == "/api/validate":
                _v = data.get("values", {})
                _eng = (data.get("engine") or _v.get("engine") or "praat").strip().lower()
                if _eng == "pysauce":
                    return self._json(validate_pysauce(_v))
                return self._json(validate(_v))
            if p == "/api/preview":
                return self._json(start_preview(data))
            if p == "/api/run":
                return self._json(start_run(data))
            if p == "/api/compare":
                values = dict(data.get("values", {}))
                files = data.get("files")
                chk = validate_compare(values)
                if not chk["ok"]:
                    return self._json({
                        "ok": False,
                        "error": "参数有问题，先修好再跑：\n" + "\n".join(
                            "· " + e["msg"] for e in chk["errors"]),
                        "errors": chk["errors"], "check": chk})
                job = start_compare_job(values, files)
                return self._json({"ok": True, "jobId": job.id,
                                   "warnings": chk["warnings"]})
            if p == "/api/cancel":
                job = _get_job(data.get("jobId"))
                if job:
                    job.stop_event.set()
                    return self._json({"ok": True})
                return self._json({"ok": False, "error": "任务不存在"})
            if p == "/api/settings":
                saved = settings.save(data.get("settings", {}))
                return self._json({"ok": True, "settings": saved})
            if p == "/api/param-defaults":
                if data.get("reset"):
                    settings.clear_param_overrides()
                else:
                    settings.save_param_overrides(data.get("values", {}))
                return self._json(get_param_defaults())
            if p == "/api/reset-paths":
                which = data.get("which") or "both"
                pd = settings.path_defaults()
                patch = {}
                if which in ("praatExe", "both"):
                    patch["praatExe"] = pd["praatExe"]
                if which in ("scriptDir", "both"):
                    patch["scriptDir"] = pd["scriptDir"]
                saved = settings.save(patch)
                exe = saved.get("praatExe") or ""
                sdir = saved.get("scriptDir") or settings.DEFAULT_SCRIPT_DIR
                env = {
                    "praatExe": exe,
                    "praatOk": bool(exe and os.path.exists(exe)),
                    "praatVersion": saved.get("praatVersion") or "",
                    "scriptDir": sdir,
                    "scriptOk": os.path.exists(os.path.join(sdir, "praatSauce.praat")),
                }
                return self._json({"ok": True, "settings": saved, "env": env})
            if p == "/api/test-praat":
                exe = data.get("exe")
                # 只接受名字像 Praat 的可执行文件，避免被当作通用程序启动器
                bn = os.path.basename(exe or "").lower()
                if not (bn.startswith("praat") and bn.endswith(".exe")):
                    return self._json({"ok": False, "error": "请选择 praat.exe（文件名需以 Praat 开头）"})
                ver = praat.probe_praat(exe)
                if ver:
                    settings.save({"praatExe": exe, "praatVersion": ver})
                return self._json({"ok": bool(ver), "version": ver or ""})
            if p == "/api/detect-praat":
                cands = praat.detect_praat(data.get("roots") or [])
                found = []
                for c in cands[:6]:
                    v = praat.probe_praat(c)
                    if v:
                        found.append({"path": c, "version": v})
                    if len(found) >= 3:
                        break
                return self._json({"ok": True, "candidates": found})
            if p == "/api/export":
                pth = data.get("path")
                try:
                    out = export_csv(pth)
                    return self._json({"ok": True, "path": out})
                except Exception as e:
                    return self._json({"ok": False, "error": str(e)})
            if p == "/api/read-object":
                try:
                    from . import praat_objects
                    pth = data.get("path", "")
                    kind = data.get("kind", "")
                    if not pth or not os.path.exists(pth):
                        return self._json({"ok": False, "error": "文件不存在"})
                    if kind == "pitch":
                        rows = praat_objects.read_pitch_text(pth)
                    elif kind == "formant":
                        rows = praat_objects.read_formant_text(pth)
                    else:
                        return self._json({"ok": False, "error": "kind 必须是 pitch 或 formant"})
                    return self._json({"ok": True, "rows": rows, "kind": kind})
                except Exception as e:
                    return self._json({"ok": False, "error": str(e)})
            # ---- 数据调整（Manual Data）：按引擎读/预览/写入测量列 ----
            # 复刻 vs_ManualData.m 的语义（引擎带名的参数列 + offset/重采样 + 只覆盖该列），
            # 载体换成 2.0 的 measure/ 引擎对象。三者都不碰其他引擎的文件。
            if p == "/api/manual-data/read":
                from . import manual_data
                return self._json(manual_data.read_rows(
                    data.get("wavPath", ""), data.get("dim", "f0"),
                    data.get("engine") or None,
                    values={"inputDir": data.get("dir", ""),
                            "outputDir": data.get("outputDir", "") or "",
                            "outputFile": data.get("outputFile", "") or ""}))
            if p in ("/api/manual-data/preview", "/api/manual-data/save"):
                from . import manual_data
                # 数据来源三选一：path（读文件）> text（粘贴）> values（数组）
                if data.get("path"):
                    try:
                        raw = manual_data.load_text(data["path"])
                    except Exception as exc:  # noqa: BLE001
                        return self._json({"ok": False,
                                           "error": "读数据文件失败：%s" % exc})
                elif data.get("text") is not None:
                    raw = data.get("text")
                else:
                    raw = None
                vals = (manual_data.parse_values(raw, data.get("invalid"))
                        if raw is not None else (data.get("values") or []))
                if p == "/api/manual-data/preview":
                    n = int(data.get("n") or 0) or manual_data._n_frames(
                        data.get("wavPath", ""))
                    fitted = manual_data.fit_values(
                        vals, n, offset=data.get("offset", 0),
                        resample=bool(data.get("resample", True)))
                    return self._json({
                        "ok": True, "n": n, "count": len(vals),
                        "filled": sum(1 for v in fitted if v is not None),
                        "points": [{"t": i * 0.001, "v": v}
                                   for i, v in enumerate(fitted)],
                        "error": None})
                return self._json(manual_data.save_values(
                    data.get("wavPath", ""), data.get("dim", "f0"),
                    data.get("engine") or "praat", vals,
                    offset=data.get("offset", 0),
                    resample=bool(data.get("resample", True)),
                    column=data.get("column")))
            if p == "/api/import-params":
                return self._json(import_params(data))
            if p == "/api/healthcheck":
                v = data.get("values") or {}
                input_dir = (data.get("dir") or v.get("inputDir") or "").strip()
                ext = (data.get("ext") or v.get("soundExt") or "wav").strip() or "wav"
                tg_dir = (data.get("tgDir") or v.get("tgDir") or "").strip() or None
                use_tg = bool(int(v.get("useTextGrid", 0) or 0))
                return self._json(health.health_check(input_dir, ext, tg_dir, use_tg))
            if p == "/api/preprocess":
                d = (data.get("dir") or "").strip()
                ext = (data.get("ext") or "wav").strip() or "wav"
                if not d or not os.path.isdir(d):
                    return self._json({"ok": False, "error": "目录不存在或不可访问"})
                return self._json(preprocess.run(d, ext))
            if p == "/api/transcode":
                d = (data.get("dir") or "").strip()
                files = data.get("files") or []
                mono = bool(data.get("mono", True))
                if not d or not os.path.isdir(d):
                    return self._json({"ok": False, "error": "目录不存在或不可访问"})
                if not files:
                    return self._json({"ok": False, "error": "没有要转码的文件"})
                return self._json(transcode.transcode(d, files, mono))
            if p == "/api/tgmatch-proposal":
                d = (data.get("dir") or "").strip()
                ext = (data.get("ext") or "wav").strip() or "wav"
                tg = (data.get("tgDir") or "").strip()
                if not d or not os.path.isdir(d):
                    return self._json({"ok": False, "error": "音频目录不存在"})
                if not tg or not os.path.isdir(tg):
                    return self._json({"ok": False, "error": "TextGrid 目录不存在"})
                return self._json(tgmatch.proposal(d, ext, tg))
            if p == "/api/tgmatch-apply":
                d = (data.get("dir") or "").strip()
                ext = (data.get("ext") or "wav").strip() or "wav"
                tg = (data.get("tgDir") or "").strip()
                pairs = data.get("pairs") or []
                return self._json(tgmatch.apply(d, ext, tg, pairs))
            if p == "/api/profiles/list":
                return self._json(profiles.list_profiles())
            if p == "/api/profiles/save":
                return self._json(profiles.save_profile(data))
            if p == "/api/profiles/delete":
                return self._json(profiles.delete_profile(data))
            if p == "/api/profiles/rename":
                return self._json(profiles.rename_profile(data))
            if p == "/api/probe-f0":
                d = (data.get("dir") or "").strip()
                ext = (data.get("ext") or "wav").strip() or "wav"
                return self._json(probe.probe_f0(d, ext))
            if p == "/api/open":
                path = data.get("path")
                # 目录直接放行（打开资源管理器）；文件限结果类扩展名白名单，
                # 不允许被当通用启动器打开任意 .exe/.lnk/.vbs 等
                _openable = (".tsv", ".csv", ".xlsx", ".wav", ".txt", ".log",
                             ".json", ".textgrid", ".png", ".jpg")
                if path and os.path.isdir(path):
                    os.startfile(path)
                    return self._json({"ok": True})
                if path and os.path.isfile(path) \
                        and os.path.splitext(path)[1].lower() in _openable:
                    os.startfile(path)
                    return self._json({"ok": True})
                return self._json({"ok": False, "error": "路径不存在或文件类型不允许打开"})
            if p == "/api/mkdir":
                path = data.get("path")
                try:
                    os.makedirs(path, exist_ok=True)
                    return self._json({"ok": True, "path": path})
                except Exception as e:
                    return self._json({"ok": False, "error": str(e)})
            # ---- 基频/共振峰审查（独立功能，不影响四步向导主线）----
            if p == "/api/review/build":
                return self._json(review_build.build_review(data.get("wavPath")))
            # F0 滑块实时预览：单文件按给定参数跑一次 pitch 分析（详情页 2026-09-25）
            if p == "/api/review/pitch-preview":
                prm = data.get("params")
                return self._json(review_build.pitch_preview(
                    data.get("wavPath"), prm if isinstance(prm, dict) else None))
            # 共振峰实时预览：单文件按给定数量/上限跑一次 burg（不落盘），供手动界面调参
            if p == "/api/review/formant-preview":
                prm = data.get("params")
                return self._json(review_build.formant_preview(
                    data.get("wavPath"), prm if isinstance(prm, dict) else None))
            if p == "/api/review/demo":
                return self._json(review_build.demo_review())
            if p == "/api/review/save":
                return self._json(review_profiles.save_profile(data))
            if p == "/api/review/profile":
                sp = (data.get("speaker") or "") if isinstance(data, dict) else ""
                return self._json({"ok": True, "profile": review_profiles.get_profile(sp or None)})
            # ---- 全量审查网格：一次 Praat 批量抽取一页目录的 F0 / 共振峰 ----
            if p == "/api/review/grid":
                return self._json(review_grid.build_grid(
                    data.get("dir", ""),
                    page=int(data.get("page", 0) or 0),
                    size=int(data.get("size", 9) or 9),
                    pitch_ceiling=float(data.get("pitchCeiling", 500) or 500),
                    formant_ceiling=float(data.get("formantCeiling", 5500) or 5500),
                    pitch_floor=float(data.get("pitchFloor", 75) or 75),
                    n_formants=float(data.get("nFormants", 5) or 5),
                    ext=data.get("ext", "wav") or "wav",
                # 默认平滑（2026-09-26 用户拍板：九宫格与详情页两处都默认 Track）——
                # 显式传 formantTrack:false 才关得掉。
                formant_track=bool(data.get("formantTrack", True)),
                formant_opt=bool(data.get("formantOpt", False)),
                # 默认优先复用 wav 旁已存盘的中间文件（2026-09-26 用户拍板）；
                # 显式传 reuse:false 才强制全量现算。
                reuse=bool(data.get("reuse", True)),
            ))
            # ---- 全量审查：批量重测（覆盖式单维强抽）----
            # 两步：scan（列出选中文件的手工修正，供前端弹窗让用户逐文件决定覆盖/跳过）
            #       + execute（真正用新参数重抽并覆盖落盘）。参数仅本次用，不回写全局设置。
            if p == "/api/review/rerun":
                if (data.get("action") or "scan") == "scan":
                    # 与同文件其它 review 端点一致：成功统一包 {ok:True, ...}，异常才 {ok:False}
                    return self._json({"ok": True, "corrections": review_grid.scan_corrections(
                        data.get("dir", ""), data.get("names") or [],
                        data.get("mode", "f0"))})
                return self._json(review_grid.rerun_grid(
                    data.get("dir", ""),
                    data.get("names") or [],
                    data.get("mode", "f0"),
                    pitch_ceiling=float(data.get("pitchCeiling", 500) or 500),
                    formant_ceiling=float(data.get("formantCeiling", 5500) or 5500),
                    pitch_floor=float(data.get("pitchFloor", 75) or 75),
                    n_formants=float(data.get("nFormants", 5) or 5),
                    formant_track=bool(data.get("formantTrack", True)),
                    formant_opt=bool(data.get("formantOpt", False))))
            # ---- 全量审查：在 Praat 中打开 / 导入修正数据 ----
            if p == "/api/review/open-praat":
                return self._json(review_grid.open_in_praat(data.get("path")))
            if p == "/api/review/import":
                # wavPath（可选）：共振峰导入时原始文本直接落盘到 wav 旁 .Formant 并记标记
                return self._json(review_grid.import_review_object(
                    data.get("text", ""), data.get("kind", "auto"),
                    wav_path=data.get("wavPath") or data.get("path") or ""))
            # ---- 全量审查：FormantPath 人工精修闭环（Route B）----
            if p == "/api/review/open-formantpath":
                return self._json(review_grid.open_formant_path(
                    data.get("path", ""), name=data.get("name", ""),
                    tg_path=data.get("tgPath") or None,
                    formant_ceiling=float(data.get("formantCeiling", 5500) or 5500)))
            if p == "/api/review/opt-result":
                # 脚本已把 FormantPath 精修结果直接存成 wav 旁 .Formant，
                # 这里按 wav 路径读回解析显示 + 记 formantImported 标记
                return self._json(review_grid.read_opt_result(data.get("path", "")))
            # ---- 全量审查：「在 Praat 中修周期」两段式人工修正闭环 ----
            if p == "/api/review/open-pointprocess":
                return self._json(review_grid.open_pointprocess(
                    data.get("path", ""),
                    pitch_floor=data.get("pitchFloor"),
                    pitch_ceiling=data.get("pitchCeiling"),
                    time_step=data.get("timeStep"),
                    n_formants=data.get("nFormants"),
                    formant_ceiling=data.get("formantCeiling")))
            if p == "/api/review/pp-result":
                return self._json(review_grid.read_pp_result(data.get("path", "")))
            # ---- 全量审查：文件详情里的「平滑（Track）」（单文件跑一遍 Praat）----
            if p == "/api/review/track":
                return self._json(review_grid.track_file(
                    data.get("wavPath", ""), name=data.get("name", ""),
                    tg_path=data.get("tgPath") or None,
                    formant_ceiling=float(data.get("formantCeiling", 5500) or 5500),
                    # 2026-09-26 平滑与候选耦合：跟随界面勾选的那条候选（上限+数量）
                    n_formants=int(data.get("nFormants", 5) or 5),
                    # 顶部条刚填的音标/性别（还没存盘也生效）：有音标 → Track 参考频率
                    # 用该元音期望值；没填 → 回退自动估计
                    vowel_ipa=data.get("vowelIpa") or None,
                    speaker=data.get("speaker") or None))
            if p == "/api/review/track-imported":
                # 对「读入的那条共振峰」（wav 旁 .Formant）做 Track，不重新抽取。
                # 默认只返回点（预览，落盘文件不动）；writeBack=true = 存盘时把
                # Track 结果写回 .Formant（Track 确定性变换，重跑=预览所见）
                return self._json(review_grid.track_imported_formant(
                    data.get("path", ""), tg_path=data.get("tgPath") or None,
                    vowel_ipa=data.get("vowelIpa") or None,
                    speaker=data.get("speaker") or None,
                    write_back=bool(data.get("writeBack"))))
            # ---- 全量审查：单文件「最终采用哪组参数」的记录（wav 同目录 sidecar）----
            if p == "/api/review/choice-get":
                return self._json(review_choice.read_choice(data.get("path", "")))
            if p == "/api/review/choice-save":
                r = review_choice.save_choice(data.get("path", ""), data.get("choice"))
                # 「读入的结果」+ 勾了平滑 = 存盘时把 Track 结果覆盖写回 wav 旁 .Formant
                # （平滑在界面只是预览；Track 确定性，重跑与预览一致，无需暂存）
                ch = data.get("choice") or {}
                if (r.get("ok") and isinstance(ch, dict)
                        and ch.get("formantImported") and ch.get("formantSmoothed")):
                    sm = review_grid.track_imported_formant(
                        data.get("path", ""), tg_path=data.get("tgPath") or None,
                        vowel_ipa=data.get("vowelIpa") or None,
                        speaker=data.get("speaker") or None, write_back=True)
                    if not sm.get("ok"):
                        r["smoothError"] = sm.get("error") or "平滑写回失败"
                return self._json(r)
            # ---- 审查结果导出：把选定的 F0/共振峰存成 praatSauce 能直接读的对象 ----
            # 传 dir = 批量（「审核完成」按钮）；传 path = 单文件（九宫格存盘后自动重导）
            if p == "/api/review/export":
                _opt = data.get("defaults") if isinstance(data.get("defaults"), dict) else None
                if data.get("dir"):
                    return self._json(review_export.export_dir(
                        data.get("dir", ""), defaults=_opt))
                return self._json(review_export.export_one(
                    data.get("path", ""), choice=data.get("choice"), defaults=_opt,
                    dims=data.get("dims")))
            # ---- 审核状态：某目录有多少 wav 已导出过审查对象（决定批量时是否重算）----
            if p == "/api/review/reviewed":
                return self._json(review_export.reviewed_state(
                    data.get("dir", ""), ext=data.get("ext", "wav") or "wav"))
            # ---- 基准引擎可用性（2.0）：扫描 measure/ 里各引擎对象是否存在 ----
            # 供第三步「其他参数的基准引擎」选择：有该引擎的对象才让选，全无则禁用批量。
            if p == "/api/engine-availability":
                return self._json(review_export.engine_availability(
                    data.get("dir", ""), ext=data.get("ext", "wav") or "wav"))
            # ---- 第四步：导出逐点时间序列（对象文件 + 汇总表双数据源，可重采样）----
            if p == "/api/export-series":
                return self._json(series_export.export_series(
                    data.get("dir", ""),
                    params=data.get("params") or [],
                    method=data.get("method", "raw"),
                    n=data.get("n"),
                    interval=data.get("interval"),
                    ext=data.get("ext", "wav") or "wav",
                    out_path=data.get("outPath") or None,
                    layout=data.get("layout", "single"),
                    # 汇总表定位需要输出目录/声音目录（结果文件可能不在声音目录里）
                    values={"inputDir": data.get("dir", ""),
                            "outputDir": data.get("outputDir", "") or ""},
                    tg_filter=bool(data.get("tgFilter", True)),
                    skip_labels=data.get("skipLabels") or series_export.TG_SKIP_LABELS_DEFAULT,
                    log_fn=lambda m, tag="out": job and job.add_log(m, tag)))
            # ---- 第四步辅助：目录里已测算的参数（VS 版「输出到文本」据此点亮/灰掉复选框）----
            # 与 grid_page / export_series 同源口径：对象文件 + 汇总表；两界面数据互通。
            if p == "/api/series-available":
                return self._json(series_export.series_available(
                    data.get("dir", ""),
                    ext=data.get("ext", "wav") or "wav",
                    values={"inputDir": data.get("dir", ""),
                            "outputDir": data.get("outputDir", "") or "",
                            "outputFile": data.get("outputFile", "") or ""},
                ))
            # ---- 第四步（新）· 查看测量结果：按页返回每文件所选参数的逐点曲线 ----
            # 纯读文件（.Pitch/.Formant 对象 + 汇总表），不调 Praat；文件清单与九宫格
            # 同序，前端点格子拿全局序号去 /api/review/grid（size=1）打开文件详情窗。
            if p == "/api/results/grid":
                return self._json(series_export.grid_page(
                    data.get("dir", ""),
                    page=int(data.get("page", 0) or 0),
                    size=int(data.get("size", 16) or 16),
                    params=data.get("params") or [],
                    ext=data.get("ext", "wav") or "wav",
                    values={"inputDir": data.get("dir", ""),
                            "outputDir": data.get("outputDir", "") or "",
                            "outputFile": data.get("outputFile", "") or ""},
                ))
            if p == "/api/results/param-ranges":
                # 参数量程：批内 2%–98% 分位 + 先验兜底（2026-09-27 方案③）。
                # 只读文件统计，不调 Praat；同一量程冻结给全批共用，跨文件/跨时间可比。
                return self._json(series_export.param_ranges(
                    data.get("dir", ""),
                    params=data.get("params") or None,
                    values={"inputDir": data.get("dir", ""),
                            "outputDir": data.get("outputDir", "") or "",
                            "outputFile": data.get("outputFile", "") or ""},
                ))
            # ---- 第四步（新）· 参数显示：单文件逐点序列（点选文件后取它的全部曲线）----
            # 与 grid_page 同源口径：对象文件 + 汇总表。供 VS 版「参数显示」界面叠加绘制。
            if p == "/api/file-series":
                return self._json(series_export.file_series(
                    data.get("dir", ""),
                    data.get("name", ""),
                    params=data.get("params") or None,
                    ext=data.get("ext", "wav") or "wav",
                    values={"inputDir": data.get("dir", ""),
                            "outputDir": data.get("outputDir", "") or "",
                            "outputFile": data.get("outputFile", "") or ""},
                ))
            # ---- 音节自动切分：批量生成 TextGrid + 九宫格检查 ----
            if p == "/api/syllables/grid":
                return self._json(syllables.segment_directory(
                    data.get("dir", ""),
                    page=int(data.get("page", 0) or 0),
                    size=int(data.get("size", 9) or 9),
                    min_silence=float(data.get("minSilence", 0.1) or 0.1),
                    min_syllable=float(data.get("minSyllable", 0.1) or 0.1),
                    threshold_db=float(data.get("thresholdDb", -25.0) or -25.0),
                    ext=data.get("ext", "wav") or "wav",
                    force=bool(data.get("force", False)),
                    readonly=bool(data.get("readonly", False)),
                    # scope="all" → 整目录（含子目录）一起切，不只当前页
                    scope=data.get("scope", "page") or "page",
                ))
            # ---- 批量重切分（覆盖式）：九宫格「重测」对选中的文件用新参数重做 TextGrid ----
            if p == "/api/syllables/resegment":
                return self._json(syllables.resegment_files(
                    data.get("dir", ""),
                    data.get("names") or [],
                    min_silence=float(data.get("minSilence", 0.1) or 0.1),
                    min_syllable=float(data.get("minSyllable", 0.1) or 0.1),
                    threshold_db=float(data.get("thresholdDb", -25.0) or -25.0),
                    ext=data.get("ext", "wav") or "wav",
                ))
            # ---- 浏览器内手工编辑后，把区间写回 TextGrid ----
            if p == "/api/syllables/save":
                return self._json(syllables.save_textgrid(
                    data.get("path"), data.get("intervals")))
            # ---- 在 Praat 里打开 wav + TextGrid 供精修，点「保存并退出」写回 ----
            if p == "/api/syllables/open-praat":
                return self._json(syllables.open_in_praat_with_tg(
                    data.get("path"), exe=None))
            return self._json({"ok": False, "error": "未知接口"}, 404)
        except Exception as e:
            return self._json({"ok": False, "error": f"{e}\n{traceback.format_exc(limit=5)}"}, 500)

    def _file(self, path):
        if not os.path.exists(path):
            return self._json({"ok": False, "error": "not found"}, 404)
        ext = os.path.splitext(path)[1].lower()
        # HTML 页面下发一次性 Token（SameSite=Strict Cookie）：
        # 之后所有同源 fetch 自动带上，/api/* 守卫据此放行本界面、拒绝其他来源
        extra = None
        if ext == ".html":
            extra = [("Set-Cookie", "PS-Token=%s; Path=/; SameSite=Strict" % TOKEN)]
        with open(path, "rb") as f:
            body = f.read()
        self._send(200, body, MIME.get(ext, "application/octet-stream"), extra=extra)

    def _wav_file(self, path):
        """按绝对路径返回 wav 字节，供前端解码算语图（共振峰模式）。"""
        if not path or not os.path.isfile(path):
            return self._json({"ok": False, "error": "文件不存在"}, 404)
        if not path.lower().endswith(".wav"):
            return self._json({"ok": False, "error": "仅支持 wav 文件"}, 403)
        try:
            with open(path, "rb") as f:
                body = f.read()
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)
        self._send(200, body, "audio/wav")


# ------------------------------------------------------------------ API 实现

def _sample_dir():
    """示例目录：<程序根>/samples/1（女声，用户 2026-10-18 指定的默认示例）。

    samples 下按发音人分了 1（女）/ 2（男）两个子目录；扫描与批量都是非递归的，
    所以这里必须直接指到子目录，指 samples 根会扫到 0 个文件。
    老包若还是压平结构（wav 直接在 samples 根），回落到根目录。
    """
    base = settings.DEFAULT_SAMPLE_DIR
    for cand in (os.path.join(base, "1"), base):
        if os.path.isdir(cand):
            return cand
    return None


def get_param_defaults():
    """参数默认值三件套：生效默认（出厂+override 合并）、用户 override、出厂默认。"""
    return {
        "ok": True,
        "defaults": settings.effective_param_defaults(),
        "overrides": settings.load_param_overrides(),
        "factory": schema.default_values(),
    }


def bootstrap():
    cfg = settings.load()
    exe = settings.resolve_praat_exe(cfg)
    version = cfg.get("praatVersion") or ""
    if exe and os.path.exists(exe) and not version:
        version = praat.probe_praat(exe) or ""
        if version:
            settings.save({"praatVersion": version})
    sdir = settings.resolve_script_dir(cfg)
    return {
        "ok": True,
        "groups": schema.GROUPS,
        "tiers": schema.TIERS,
        "params": schema.PARAMS,
        # 第四步「导出时间序列」可勾选的列 + 八组分组定义（与 backend/series_export.py
        # 的 COLUMNS / GROUPS 同源下发，前端按它铺表，后端加列自动跟随）
        "seriesParams": series_export.COLUMNS,
        "seriesGroups": [{"key": k, "label": lb, "cols": cs}
                         for k, lb, cs in series_export.GROUPS],
        "presets": schema.PRESETS,
        "speakers": profiles.merge_speakers(),
        "defaults": settings.effective_param_defaults(),
        "overrides": settings.load_param_overrides(),
        "factory": schema.default_values(),
        "settings": cfg,
        "env": {
            "praatExe": exe,
            "praatOk": bool(exe and os.path.exists(exe)),
            "praatVersion": version,
            "scriptDir": sdir,
            "scriptOk": os.path.exists(os.path.join(sdir, "praatSauce.praat")),
            "sampleDir": _sample_dir(),
            "workDir": settings.WORK_DIR,
            "selfCheck": selfcheck.cached(),
        },
    }


# ------------------------------------------------------------------ pysauce 引擎路由（V2-F2）
#
# 2.0 与 1.2 的分界：请求体多一个 `engine` 字段。
#   · 无该字段 / "praat"  → 走 1.2 原 Praat 脚本链（向导零变化，本文件以下原有函数一行未改）；
#   · "pysauce"           → 走 backend/pysauce（VoiceSauce 算法的 Python 实现）。
# 唯一改动点集中在 `start_run` / `validate` 两个入口的**分派**，以及本节新增的
# `run_pysauce_job` / `_values_to_engine_request`。既有函数体一律不动。

# 1.2 `values` 的 13 个测量开关（vs.js buildValues）→ EngineRequest 的 do_* 字段。
# 映射表（施工卡 V2-F2 §2 要求写进代码注释）：
#   pitch                    → F0 引擎（由 pitch_engine 决定用哪套）
#   formant                  → 共振峰引擎（由 formant_engine 决定）
#   harmonicAmplitude        → do_h1h2h4（已校正 H1*/H2*/H4*）
#   harmonicAmplitudeUncorrected → do_h1h2h4（未校正 H1u/H2u/H4u，同一引擎、同批产出）
#   slope                    → do_slopes（已校正差值列）
#   slopeUncorrected         → do_slopes（未校正差值列）
#   intensity                → do_energy
#   cpp                      → do_cpp
#   hnr                      → do_hnr
#   soe                      → do_soe
#   shr                      → do_shr
#   cpps                     → do_cpp（CPPS 与 CPP 同族，由 do_cpp 一并产出）
#   （第 13 项 resample16kHz 是采样率开关，非测量项，见 §注）
_PYSAUCE_SWITCH_MAP = (
    ("harmonicAmplitude", "do_h1h2h4"),
    ("harmonicAmplitudeUncorrected", "do_h1h2h4"),
    ("slope", "do_slopes"),
    ("slopeUncorrected", "do_slopes"),
    ("intensity", "do_energy"),
    ("cpp", "do_cpp"),
    ("cpps", "do_cpp"),
    ("hnr", "do_hnr"),
    ("soe", "do_soe"),
    ("shr", "do_shr"),
)

# VoiceSauce 默认基准引擎（refs vs_Initialize.m L71/72）
# 仅当前端既未显式给 f0_algorithm、也未给 f0BaseEngine 时才回退到此（绝大多数情况
# 已被前两者覆盖）。默认 praat：向导版以 Praat 为基准，VS 版会显式传 straight/snack。
_VS_DEFAULT_F0_ALGO = "praat"
_VS_DEFAULT_FMT_ALGO = "praat"


def _truthy_int(v, default=0):
    try:
        return int(float(v if v is not None else default) or 0)
    except (TypeError, ValueError):
        return int(default)


def _resolve_measure_dir(values):
    """<音频目录>/measure/ —— 照 1.2 `_prepare` L267-281 的既有推导逻辑，禁止另立规则。

    1.2 的口径：pitchSaveDir/pitchReadDir（formant 同）留空时补 inputDir；而对象文件
    统一落在 `<音频目录>/measure/`（review_export 侧）。这里取「输入目录下 measure/」。
    """
    d = (values.get("inputDir") or "").strip()
    if d:
        d = working_dir.resolve_working_dir(d)
    return os.path.join(d, "measure") if d else ""


def _values_to_engine_request(values, wav_path):
    """1.2 `values` → F1 `EngineRequest`（dict）。映射表见 `_PYSAUCE_SWITCH_MAP`。

    返回 dict，键与 `pysauce.engine.run_file` 读取的 req 键一一对应。
    """
    v = dict(values or {})
    req = {
        "wav_path": wav_path,
        # —— 算哪几套（F3 新增，缺省 praat）——
        "pitch_engine": (v.get("pitch_engine") or "praat").strip().lower(),
        "formant_engine": (v.get("formant_engine") or "praat").strip().lower(),
        # —— 下游用哪套（F3 新增）：前端显式给 f0_algorithm 则用；否则取向导基准引擎
        #    f0BaseEngine；再否则回退到 praat（向导默认以 Praat 为基准）。——
        "f0_algorithm": (v.get("f0_algorithm") or v.get("f0BaseEngine") or _VS_DEFAULT_F0_ALGO).strip().lower(),
        "fmt_algorithm": (v.get("fmt_algorithm") or v.get("formantBaseEngine") or _VS_DEFAULT_FMT_ALGO).strip().lower(),
        # —— 多引擎：VS 勾选了哪些 F0 / 共振峰引擎（可多选；空 = 仅基准）——
        "f0_engines": list(v.get("f0_engines") or []),
        "fmt_engines": list(v.get("fmt_engines") or []),
        # —— 数据互通（F1 §0b）——
        "reuse": bool(_truthy_int(v.get("pitchRead")) or _truthy_int(v.get("formantRead"))),
        "measure_dir": _resolve_measure_dir(v),
        "pitch_read_dir": (v.get("pitchReadDir") or "").strip() or None,
        "formant_read_dir": (v.get("formantReadDir") or "").strip() or None,
        # —— 外部引擎可执行文件 ——
        "praat_exe": (v.get("praatExe") or "").strip() or None,
        "snack_exe": (v.get("snackExe") or "").strip() or None,
        # —— Other 引擎的数据文件 ——
        "other_f0_file": (v.get("otherF0File") or "").strip() or None,
        "other_fmt_file": (v.get("otherFmtFile") or "").strip() or None,
        "do_soe_method": (v.get("soeMethod") or "whole").strip().lower(),
    }
    # 13 个开关 → do_*（同一 do_* 被多个开关命中时取或）
    for src, dst in _PYSAUCE_SWITCH_MAP:
        req[dst] = bool(req.get(dst)) or bool(_truthy_int(v.get(src)))
    for dst in ("do_h1h2h4", "do_slopes", "do_energy", "do_cpp",
                "do_hnr", "do_soe", "do_shr", "do_a1a2a3", "do_2k5k"):
        req.setdefault(dst, False)
    # A1/A2/A3 与 2K/5K 是谐波幅度的子项：1.2 用 harmonicAmplitude 一个总开关承载，
    # 2.0 拆成独立子算法，仍随总开关一起算（与 vs.js 的 ha 组一致）。
    if req["do_h1h2h4"]:
        req["do_a1a2a3"] = True
        req["do_2k5k"] = True
    return req


# 各引擎的「引擎列」集合（F0 + F1..F4 + B1..B4）——供基准引擎补齐时做列合并。
# 只合并引擎列；测量列（H1c/CPP/…）恒取「以基准引擎算」的那一遍，保证下游正确。
_ENGINE_COL_SETS = {
    "praat": ("pF0", ("pF1", "pF2", "pF3", "pF4"), ("pB1", "pB2", "pB3", "pB4")),
    "snack": ("sF0", ("sF1", "sF2", "sF3", "sF4"), ("sB1", "sB2", "sB3", "sB4")),
    "straight": ("strF0", None, None),
    "shr": ("shrF0", None, None),
    "other": ("oF0", ("oF1", "oF2", "oF3", "oF4"), ("oB1", "oB2", "oB3", "oB4")),
}


def _engine_columns(engine):
    """某引擎在结果字典里占用的列名（F0 1 个 + 可选 4 个 F + 可选 4 个 B）。"""
    spec = _ENGINE_COL_SETS.get(engine)
    if not spec:
        return []
    f0, fcols, bcols = spec
    out = [f0] if f0 else []
    if fcols:
        out.extend(fcols)
    if bcols:
        out.extend(bcols)
    return out


def _merge_engine_columns(dst_res, src_res, engine):
    """把 src_res 中 `engine` 的引擎列（非 None 的）并进 dst_res（F3 基准补齐）。

    仅动引擎列——测量列（H1c/CPP/…）保留 dst_res 原值（它以基准引擎算得，语义正确）。
    """
    for col in _engine_columns(engine):
        v = src_res.get(col)
        if v is not None:
            dst_res[col] = v


def _pysauce_wav_list(values, files):
    """批量待处理 wav 绝对路径列表：优先用前端传来的 `files`，否则扫描 inputDir。"""
    d = (values.get("inputDir") or "").strip()
    if d:
        d = working_dir.resolve_working_dir(d)
    ext = (values.get("soundExt") or "wav").strip().lstrip(".").lower()
    out = []
    if isinstance(files, list) and files:
        for f in files:
            p = f if os.path.isabs(str(f)) else os.path.join(d, str(f))
            if os.path.isfile(p):
                out.append(p)
        return out
    if d and os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            if n.lower().endswith("." + ext) and os.path.isfile(p):
                out.append(p)
    return out


def _write_pysauce_tsv(path, results_list, file_names=None):
    """out.tsv：表头 = file + time + OUTPUT_COLS（F1 顺序）；None → `--undefined--`；6 位小数。

    `file_names`（可选）与 results_list 等长：写入首列 `file`（与 1.2 输出同款），
    多文件批量时用于区分各行属于哪个 wav（compare 按 file+time 对齐依赖此列）。
    """
    from .pysauce import output_cols as _oc
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cols = list(_oc.OUTPUT_COLS)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(["file", "time"] + cols) + "\n")
        for k, res in enumerate(results_list):
            fname = ""
            if file_names and k < len(file_names):
                fname = os.path.basename(str(file_names[k]))
            n = 0
            for c in cols:
                vec = res.get(c)
                if vec is not None:
                    n = max(n, len(vec))
            for i in range(n):
                row = [fname, "%g" % ((i + 1) / 1000.0)]
                for c in cols:
                    vec = res.get(c)
                    val = vec[i] if (vec is not None and i < len(vec)) else None
                    if val is None:
                        row.append("--undefined--")
                    else:
                        try:
                            fv = float(val)
                            row.append("--undefined--" if fv != fv else "%.6f" % fv)
                        except (TypeError, ValueError):
                            row.append("--undefined--")
                f.write("\t".join(row) + "\n")


def _results_json_path(out_dir):
    """结果标记文件：<输出目录>/_results.json（单文件记多套 runs）。"""
    return os.path.join(out_dir, "_results.json")


def _record_pysauce_result(out_dir, req, result_path):
    """把本次运行的基准引擎 + 输出文件记进 _results.json（供导出时判断多套）。

    结构（2026-10-27 用户定案）：
      {"runs": [{"f0_algorithm":…, "fmt_algorithm":…, "out":<文件名>, "ts":…}, …]}
    同一 (f0_algorithm, fmt_algorithm) 重复运行 → 覆盖该条（保留最新），不重复堆叠。
    """
    p = _results_json_path(out_dir)
    data = {"runs": []}
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f) or {"runs": []}
    except Exception:
        data = {"runs": []}
    runs = [r for r in (data.get("runs") or [])
            if not (r.get("f0_algorithm") == req["f0_algorithm"]
                    and r.get("fmt_algorithm") == req["fmt_algorithm"])]
    runs.append({
        "f0_algorithm": req["f0_algorithm"],
        "fmt_algorithm": req["fmt_algorithm"],
        "out": os.path.basename(result_path),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    data["runs"] = runs
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def list_pysauce_results(out_dir):
    """查 <输出目录>/_results.json：返回已有多套结果列表（供导出询问）。

    返回 {"ok": bool, "count": n, "runs": [...], "multi": bool}。
    count>1 即"有多套"，前端应询问导出哪套。
    """
    p = _results_json_path(out_dir)
    runs = []
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                runs = (json.load(f) or {}).get("runs") or []
    except Exception:
        runs = []
    # 只保留输出文件仍存在的记录
    runs = [r for r in runs
            if r.get("out") and os.path.exists(os.path.join(out_dir, r["out"]))]
    return {"ok": True, "count": len(runs), "runs": runs, "multi": len(runs) > 1}


def run_pysauce_job(job, values, files):
    """pysauce 批量执行体（在 1.2 既有 job 线程内跑，禁在 handler 线程直跑）。

    进度通过 job.progress 上报（沿用 1.2 watch 机制的字段名：done/total/current）。
    """
    v = dict(values or {})
    cfg = settings.load()
    if not v.get("praatExe"):
        v["praatExe"] = settings.resolve_praat_exe(cfg) or ""
    if not v.get("snackExe"):
        _snack = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "vendor", "snack.exe")
        v["snackExe"] = _snack if os.path.exists(_snack) else ""

    wavs = _pysauce_wav_list(v, files)
    job.progress["total"] = len(wavs) or 1
    if not wavs:
        job.status = "error"
        job.error = "没有找到任何待处理的音频文件。请确认已选择音频目录且扩展名设置正确。"
        return

    reqs = [_values_to_engine_request(v, w) for w in wavs]
    job.add_log("引擎: pysauce（VoiceSauce 算法 Python 实现）")
    # 实际计算集合 = 基准引擎 ∪ 勾选引擎（base 跑恒用基准，其余靠 extras 补算）。
    calc_f0 = sorted(set([reqs[0]["f0_algorithm"]]) | set(reqs[0].get("f0_engines") or []))
    calc_fmt = sorted(set([reqs[0]["fmt_algorithm"]]) | set(reqs[0].get("fmt_engines") or []))
    job.add_log("基准 F0=%s  基准 FMT=%s（下游测量列以基准算）" % (
        reqs[0]["f0_algorithm"], reqs[0]["fmt_algorithm"]))
    job.add_log("本次计算 F0 引擎=%s  共振峰引擎=%s" % (
        "+".join(calc_f0), "+".join(calc_fmt)))

    def _cb(done, total):
        job.progress["done"] = done
        if 0 < done <= len(wavs):
            job.progress["current"] = os.path.basename(wavs[done - 1])
            job.add_log("Processing " + os.path.basename(wavs[done - 1]), "out")

    from .pysauce import engine as _pyengine

    # ── 基准引擎补齐（F3，2026-10-27 用户定案：「换基准但基准值还没计算，则立即现算」）──
    #
    # 语义：测量列（H1c/CPP/…）必须以**基准引擎**为底算，故「主跑」恒用基准引擎作为
    # pitch_engine/formant_engine；若用户另外指定了「要算哪套引擎」且与基准不同，
    # 则再补跑一遍该引擎，只把它的**引擎列**并进主结果（测量列不动）。
    base_reqs = []
    for r in reqs:
        r2 = dict(r)
        r2["pitch_engine"] = r["f0_algorithm"]
        r2["formant_engine"] = r["fmt_algorithm"]
        base_reqs.append(r2)
    results_list = _pyengine.run_batch(base_reqs, progress_cb=_cb)

    # 多引擎补齐（F3 扩展）：VS 可勾选多个 F0 / 共振峰引擎，本批需把它们各自的
    # 引擎列也算出并合并；基准引擎恒为主跑，其余逐个补跑（仅引擎列，测量列不动）。
    base_f0 = reqs[0]["f0_algorithm"]
    base_fmt = reqs[0]["fmt_algorithm"]
    extra_f0 = [e for e in (reqs[0].get("f0_engines") or []) if e != base_f0]
    extra_fmt = [g for g in (reqs[0].get("fmt_engines") or []) if g != base_fmt]

    def _run_extra(pe, fe):
        ex_reqs = []
        for r in reqs:
            r2 = dict(r)
            r2["pitch_engine"] = pe
            r2["formant_engine"] = fe
            # extras 只为取引擎列（_merge_engine_columns 只并 F0/F1-4/B1-4），
            # 测量列会被整体丢弃 → 关掉全部 do_* 开关，避免重复计算
            # H1/A1/2K5K/斜率/Energy/CPP/HNR/SHR/SoE（STRAIGHT 场景下这步很慢）。
            for k in list(r2):
                if k.startswith("do_") and isinstance(r2[k], bool):
                    r2[k] = False
            ex_reqs.append(r2)
        return _pyengine.run_batch(ex_reqs, progress_cb=None)

    for e in extra_f0:
        job.add_log("基准补齐：立即现算 F0 引擎 %s（供下游列使用）" % e, "out")
        ex_results = _run_extra(e, base_fmt)
        for i, ex in enumerate(ex_results):
            if i < len(results_list):
                _merge_engine_columns(results_list[i], ex, e)
    for g in extra_fmt:
        job.add_log("基准补齐：立即现算 共振峰引擎 %s（供下游列使用）" % g, "out")
        ex_results = _run_extra(base_f0, g)
        for i, ex in enumerate(ex_results):
            if i < len(results_list):
                _merge_engine_columns(results_list[i], ex, g)

    job.elapsed = round(time.time() - job.started, 1)

    if job.stop_event.is_set():
        job.status = "cancelled"
        return

    out_dir = (v.get("outputDir") or "").strip() or os.path.join(
        (v.get("inputDir") or "").strip(), "output")
    # 输出文件名加双前缀 <f0algo>_<fmtalgo>_<原名>（2026-10-27 用户定案）：
    # F0 与共振峰可能用不同算法，故两个前缀各表一套基准，一眼看出"哪套基准算的"，
    # 且不同基准互不覆盖。例：praat_praat_out.tsv / straight_snack_out.tsv。
    out_file = (v.get("outputFile") or "out.tsv").strip() or "out.tsv"
    prefix = "%s_%s_" % (reqs[0]["f0_algorithm"], reqs[0]["fmt_algorithm"])
    result_path = os.path.join(out_dir, prefix + out_file)
    _write_pysauce_tsv(result_path, results_list, wavs)
    job.result_path = result_path
    _record_pysauce_result(out_dir, reqs[0], result_path)

    n_rows = 0
    warnings = []
    for res in results_list:
        for c in _OUTPUT_COLS_CACHE():
            vec = res.get(c)
            if vec is not None:
                n_rows = max(n_rows, len(vec))
        warnings.extend(res.get("_warnings") or [])
    for w in warnings:
        job.add_log(str(w), "err" if "失败" in str(w) else "out")

    # _meta（f0_algorithm/fmt_algorithm）写入 job summary，供 F3 界面显示「本批基准引擎」
    job.summary = {
        "columns": ["time"] + list(_OUTPUT_COLS_CACHE()),
        "rowCount": n_rows,
        "rows": [],
        "previewRows": [],
        "diagnostics": [],
        "perFile": [],
        "fileCount": len(wavs),
        "stats": {},
        "returnCode": 0,
        "emptyResult": n_rows == 0,
        "engine": "pysauce",
        "f0_algorithm": reqs[0]["f0_algorithm"],
        "fmt_algorithm": reqs[0]["fmt_algorithm"],
        "pitch_engine": reqs[0]["pitch_engine"],
        "formant_engine": reqs[0]["formant_engine"],
        # 本次实际计算的引擎集合（base ∪ 勾选），供界面如实显示（审查修复 2026-10-27）
        "f0_engines": sorted(set([reqs[0]["f0_algorithm"]]) | set(reqs[0].get("f0_engines") or [])),
        "fmt_engines": sorted(set([reqs[0]["fmt_algorithm"]]) | set(reqs[0].get("fmt_engines") or [])),
    }
    if n_rows == 0:
        job.status = "error"
        job.error = "pysauce 批量结束但没有产生任何数据行。请查看上方日志。"
        return
    job.status = "done"


_OUTPUT_COLS_MEMO = []


def _OUTPUT_COLS_CACHE():
    if not _OUTPUT_COLS_MEMO:
        from .pysauce import output_cols as _oc
        _OUTPUT_COLS_MEMO.extend(_oc.OUTPUT_COLS)
    return _OUTPUT_COLS_MEMO


def _execute_pysauce(job, values, files):
    """pysauce 版 _execute：顶层 try/except → job error（禁止裸 raise 打崩线程池）。"""
    try:
        job.status = "running"
        run_pysauce_job(job, values, files)
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = f"{e}\n\n{traceback.format_exc(limit=6)}"
        job.add_log(str(e), "err")


def start_pysauce_job(values, files):
    """建 job（沿用 1.2 Job 结构）并在独立线程跑 pysauce。"""
    job = Job("batch", values, len(files) if isinstance(files, list) and files else 0)
    with JOBS_LOCK:
        JOBS[job.id] = job
    t = threading.Thread(target=_execute_pysauce, args=(job, values, files), daemon=True)
    t.start()
    return job


def validate_pysauce(values):
    """pysauce 双轨校验。返回结构与 1.2 `validate` 一致：{ok,errors,warnings,fixed}。"""
    errors = []
    warns = []
    d = (values.get("inputDir") or "").strip()
    d = working_dir.resolve_working_dir(d) if d else d
    if not d:
        errors.append({"field": "inputDir", "msg": "还没有选择声音文件目录"})
    elif not os.path.isdir(d):
        errors.append({"field": "inputDir", "msg": f"目录不存在：{d}"})
    else:
        ext = (values.get("soundExt") or "wav").strip().lstrip(".")
        try:
            n = len([x for x in os.listdir(d) if x.lower().endswith("." + ext.lower())])
        except Exception:
            n = 0
        if n == 0:
            errors.append({"field": "inputDir",
                           "msg": f"在 {d} 下没有找到任何 .{ext} 文件"})

    od = (values.get("outputDir") or "").strip()
    if od:
        if not os.path.isdir(od):
            try:
                os.makedirs(od, exist_ok=True)
            except Exception as e:
                errors.append({"field": "outputDir", "msg": f"输出目录无法创建：{e}"})

    pitch_engine = (values.get("pitch_engine") or "praat").strip().lower()
    formant_engine = (values.get("formant_engine") or "praat").strip().lower()
    # 下游基准（F3）：主跑**恒以基准引擎**计算（见 run_pysauce_job 的 base_reqs），
    # 故实际会跑的引擎集合 = {基准} ∪ {勾选}。预检必须按这个全集检查依赖，
    # 否则「基准=snack 但只勾了 praat」这类组合会漏检 snack.exe。
    f0_algo = (values.get("f0_algorithm") or values.get("f0BaseEngine") or _VS_DEFAULT_F0_ALGO).strip().lower()
    fmt_algo = (values.get("fmt_algorithm") or values.get("formantBaseEngine") or _VS_DEFAULT_FMT_ALGO).strip().lower()
    engines_f0 = set([f0_algo, pitch_engine]) | set(values.get("f0_engines") or [])
    engines_fmt = set([fmt_algo, formant_engine]) | set(values.get("fmt_engines") or [])
    if "praat" in engines_f0 or "praat" in engines_fmt:
        cfg = settings.load()
        exe = settings.resolve_praat_exe(cfg)
        if not exe or not os.path.exists(exe):
            errors.append({"field": "praatExe", "msg": "Praat 程序路径无效，请到「设置」里重新指定"})
    if "snack" in engines_f0 or "snack" in engines_fmt:
        _snack = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "vendor", "snack.exe")
        if not os.path.exists(_snack):
            errors.append({"field": "snackExe", "msg": f"找不到 snack.exe：{_snack}"})
    if "other" in engines_f0:
        p = (values.get("otherF0File") or "").strip()
        if not p or not os.path.exists(p):
            errors.append({"field": "otherF0File", "msg": "Other 引擎的 F0 数据文件不存在"})
    if "other" in engines_fmt:
        p = (values.get("otherFmtFile") or "").strip()
        if not p or not os.path.exists(p):
            errors.append({"field": "otherFmtFile", "msg": "Other 引擎的共振峰数据文件不存在"})

    # 下游基准引擎：**恒会被计算**（base 跑即基准引擎，缺对象时也会现算），
    # 故不再告警「基准未计算」。原 `f0_algo != pitch_engine → 相关列 undefined`
    # 是 F3 单引擎时代的判断，多引擎（base=基准 + extras=其余）下已不成立，
    # 保留会误报（例：向导基准 snack、只勾 praat，实际会算 snack）。
    if f0_algo not in engines_f0 or fmt_algo not in engines_fmt:  # 防御：结构异常才报
        warns.append({"field": "f0_algorithm",
                      "msg": f"基准引擎解析异常：F0={f0_algo}，共振峰={fmt_algo}"})
    return {"ok": len(errors) == 0, "errors": errors, "warnings": warns, "fixed": []}


# ------------------------------------------------------------------ 双跑对比（V2-F4）
#
# ⚠️ 本工具**不是**「2.0 正确性验证器」：1.2 走 Praat 脚本、2.0 走 VoiceSauce 算法，
#    两者真正等价仅约 3 项。差异表是**预期差异的呈现**，不是 bug 清单；用途是横向比较
#    不同引擎/算法口径（Praat vs Snack vs VS 算法）。compare 只在外面串联，**不动 1.2 引擎执行路径**。

def run_compare_job(job, values, files):
    """双跑对比：先按 1.2 Praat 链跑一遍（out_12.tsv），再按 pysauce 跑一遍，然后逐列对比。

    结果落 <输出目录>/compare_<时间戳>.csv，并把对比 dict 放 job.summary["compare"]。
    """
    from .pysauce import compare as _cmp

    v = dict(values or {})
    cfg = settings.load()
    if not v.get("praatExe"):
        v["praatExe"] = settings.resolve_praat_exe(cfg) or ""
    if not v.get("snackExe"):
        _snack = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "vendor", "snack.exe")
        v["snackExe"] = _snack if os.path.exists(_snack) else ""

    wavs = _pysauce_wav_list(v, files)
    if not wavs:
        job.status = "error"
        job.error = "没有找到任何待处理的音频文件。"
        return
    job.progress["total"] = len(wavs) * 2 or 1

    out_dir = (v.get("outputDir") or "").strip() or os.path.join(
        (v.get("inputDir") or "").strip(), "output")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    # ── 第一腿：1.2 Praat 链（原样复用 _prepare + praat.run_script，不动其行为）──
    job.add_log("【双跑对比】第一腿：1.2 Praat 脚本链", "out")
    v12 = dict(v)
    v12["outputDir"] = out_dir
    v12["outputFile"] = "out_12.tsv"
    v12["engine"] = "praat"
    csv_path, exe, sdir, workdir, pv = _prepare(v12, preview_file=None, job=job)
    if not exe or not os.path.exists(exe):
        job.status = "error"
        job.error = "没有找到 Praat 程序（1.2 链需要）。请到「设置」里指定。"
        return
    progress_path = os.path.join(workdir, "ps_progress.txt")
    job.add_log("$ praat --run praatSauce.praat " + csv_path)
    rc, _ = praat.run_script(
        exe, "praatSauce.praat", [csv_path, progress_path], cwd=sdir,
        on_line=lambda ln: job.add_log(ln, "out"), stop_event=job.stop_event,
        timeout=6 * 3600, full_trust=True)
    if job.stop_event.is_set():
        job.status = "cancelled"
        return
    praat_tsv = os.path.join(out_dir, "out_12.tsv")
    if not os.path.exists(praat_tsv):
        job.status = "error"
        job.error = f"1.2 Praat 链未生成结果文件（退出码 {rc}）。"
        return
    job.progress["done"] = len(wavs)

    # ── 第二腿：pysauce ──
    job.add_log("【双跑对比】第二腿：2.0 pysauce 引擎", "out")
    reqs = [_values_to_engine_request(v, w) for w in wavs]
    base_reqs = []
    for r in reqs:
        r2 = dict(r)
        r2["pitch_engine"] = r["f0_algorithm"]
        r2["formant_engine"] = r["fmt_algorithm"]
        base_reqs.append(r2)

    def _cb(done, total):
        job.progress["done"] = len(wavs) + done
        if 0 < done <= len(wavs):
            job.progress["current"] = os.path.basename(wavs[done - 1])

    from .pysauce import engine as _pyengine
    results_list = _pyengine.run_batch(base_reqs, progress_cb=_cb)
    extra_f0 = reqs[0]["pitch_engine"] if reqs[0]["pitch_engine"] != reqs[0]["f0_algorithm"] else None
    extra_fmt = reqs[0]["formant_engine"] if reqs[0]["formant_engine"] != reqs[0]["fmt_algorithm"] else None
    if extra_f0 or extra_fmt:
        ex_reqs = []
        for r in reqs:
            r2 = dict(r)
            r2["pitch_engine"] = extra_f0 or r["f0_algorithm"]
            r2["formant_engine"] = extra_fmt or r["fmt_algorithm"]
            ex_reqs.append(r2)
        ex_results = _pyengine.run_batch(ex_reqs, progress_cb=None)
        for i, ex in enumerate(ex_results):
            if i < len(results_list):
                if extra_f0:
                    _merge_engine_columns(results_list[i], ex, extra_f0)
                if extra_fmt:
                    _merge_engine_columns(results_list[i], ex, extra_fmt)

    prefix = "%s_%s_" % (reqs[0]["f0_algorithm"], reqs[0]["fmt_algorithm"])
    pysauce_tsv = os.path.join(out_dir, prefix + "out.tsv")
    _write_pysauce_tsv(pysauce_tsv, results_list, wavs)
    job.result_path = pysauce_tsv

    if job.stop_event.is_set():
        job.status = "cancelled"
        return

    # ── 对比 ──
    job.add_log("【双跑对比】逐列对比中…", "out")
    cmp_res = _cmp.compare_files(praat_tsv, pysauce_tsv)
    cmp_csv = os.path.join(out_dir, "compare_%s.csv" % stamp)
    _cmp.write_compare_csv(cmp_csv, cmp_res, praat_tsv, pysauce_tsv)

    job.summary = {
        "columns": ["time"] + list(_OUTPUT_COLS_CACHE()),
        "rowCount": 0, "rows": [], "previewRows": [], "diagnostics": [],
        "perFile": [], "fileCount": len(wavs), "stats": {}, "returnCode": 0,
        "emptyResult": False, "engine": "compare",
        "praatPath": praat_tsv, "pysaucePath": pysauce_tsv, "compareCsv": cmp_csv,
        "compare": cmp_res,
        "f0_algorithm": reqs[0]["f0_algorithm"],
        "fmt_algorithm": reqs[0]["fmt_algorithm"],
    }
    job.elapsed = round(time.time() - job.started, 1)
    job.add_log("对比完成 → " + cmp_csv, "out")
    job.status = "done"


def _execute_compare(job, values, files):
    try:
        job.status = "running"
        run_compare_job(job, values, files)
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = f"{e}\n\n{traceback.format_exc(limit=6)}"
        job.add_log(str(e), "err")


def start_compare_job(values, files):
    job = Job("compare", values, len(files) if isinstance(files, list) and files else 0)
    with JOBS_LOCK:
        JOBS[job.id] = job
    t = threading.Thread(target=_execute_compare, args=(job, values, files), daemon=True)
    t.start()
    return job


def validate_compare(values):
    """双跑对比校验：pysauce 校验 + 1.2 链所需（Praat 存在）。"""
    chk = validate_pysauce(values)
    cfg = settings.load()
    exe = settings.resolve_praat_exe(cfg)
    if not exe or not os.path.exists(exe):
        chk["errors"].append({"field": "praatExe",
                              "msg": "1.2 Praat 链需要 Praat 程序，请到「设置」里指定"})
        chk["ok"] = False
    return chk


def start_preview(data):
    values = dict(data.get("values", {}))
    fname = data.get("file") or ""
    # 支持在第三步直接挑选的绝对路径测试音频：拆成 inputDir + 文件名，
    # 复用既有试跑链路（praatSauce 的 filelist 只接受相对 inputDir 的路径）。
    if fname and os.path.isabs(fname) and os.path.isfile(fname):
        values["inputDir"] = os.path.dirname(fname)
        fname = os.path.basename(fname)
    if not fname:
        return {"ok": False, "error": "没有指定试跑的文件"}
    # 试跑结果写在临时工作区，不涉及「结果输出目录」，故按试跑模式校验（跳过 outputDir）。
    chk = validate(values, for_preview=True)
    fatal = [e for e in chk["errors"] if e["field"] not in ("praatExe", "scriptDir")]
    if fatal:
        return {"ok": False, "error": "先解决这些问题：\n" + "\n".join("· " + e["msg"] for e in fatal),
                "errors": fatal, "check": chk}
    job = start_job("preview", values, preview_file=fname)
    return {"ok": True, "jobId": job.id}


def start_run(data):
    values = dict(data.get("values", {}))
    files = data.get("files")
    # V2-F2：engine 缺省 = "praat"（1.2 原链，一行不动）；"pysauce" 走 Python 引擎。
    engine = (data.get("engine") or values.get("engine") or "praat").strip().lower()
    if engine == "pysauce":
        chk = validate_pysauce(values)
        if not chk["ok"]:
            return {"ok": False,
                    "error": "参数有问题，先修好再跑：\n" + "\n".join("· " + e["msg"] for e in chk["errors"]),
                    "errors": chk["errors"], "check": chk}
        job = start_pysauce_job(values, files)
        return {"ok": True, "jobId": job.id, "warnings": chk["warnings"]}
    # 前端只勾选了部分文件 → 把清单写成 filelist，praatSauce 只处理这些
    if isinstance(files, list) and files:
        values["filelist"] = _write_filelist(files)
    chk = validate(values)
    if not chk["ok"]:
        return {"ok": False, "error": "参数有问题，先修好再跑：\n" + "\n".join("· " + e["msg"] for e in chk["errors"]),
                "errors": chk["errors"], "check": chk}
    job = start_job("batch", values)
    return {"ok": True, "jobId": job.id, "warnings": chk["warnings"]}


def export_csv(path):
    """Praat 写出来的 tsv 在 Windows 上是 UTF-16，Excel 打开是乱码。
    这里转成带 BOM 的 UTF-8 csv，双击就能看。"""
    text = results._read_text(path)
    out_path = os.path.splitext(path)[0] + ".csv"
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for ln in text.replace("\r\n", "\n").split("\n"):
            if not ln.strip():
                continue
            w.writerow(ln.split("\t"))
    return out_path


def import_params(data):
    """从 params.csv 文件或文本框读回参数。

    支持两条入口（W1 / FT1b）：
      - data["path"]：读文件，编码/分隔符容错走 parse_csv_file_ex；
      - data["text"]：直接解析文本框内容（前端已保证是 UTF-8 字符串）。
    两者共用 diff_against_schema + coerce_from_csv + warnings 整理逻辑（_finalize_import）。
    """
    path = data.get("path")
    text = data.get("text")
    if text is not None and text != "":
        values, notes = params_io.parse_csv_text_ex(text)
        return _finalize_import(values, notes)
    if path and os.path.exists(path):
        values, notes = params_io.parse_csv_file_ex(path)
        return _finalize_import(values, notes)
    return {"ok": False, "error": "没有提供参数文件或文本内容"}


def _finalize_import(values, notes):
    """把解析出的 values + notes 整理成统一的 import_params 响应。"""
    unknown, missing = params_io.diff_against_schema(values)
    warnings = []
    if unknown:
        warnings.append({"field": "", "msg": "以下参数不在参数表中，已忽略：" + "、".join(unknown)})
    if missing:
        warnings.append({"field": "", "msg": "以下参数未提供，将使用默认值：" + "、".join(missing)})
    for n in notes:
        warnings.append({"field": "", "msg": n})
    coerced = params_io.coerce_from_csv(values)
    return {"ok": True, "values": coerced, "notes": notes,
            "unknown": unknown, "missing": missing, "warnings": warnings}


def result_payload(path):
    if not path:
        return {"ok": False, "error": "没有结果文件路径"}
    table = results.read_table(path, max_rows=60)
    diag = results.diagnose(path)
    out = {
        "ok": table["ok"],
        "path": path,
        "columns": table.get("columns", []),
        "rowCount": table.get("total", 0),
        # 结果卡「帧数 / N 个文件」里的 N。没有这个字段时前端会退化成 1，
        # 33 个文件的批也会显示「1 个文件」。diag["files"] 是逐文件统计的条数。
        "fileCount": diag.get("files", 0),
        "rows": table.get("rows", []),
        "diagnostics": diag.get("diagnostics", []),
        "perFile": diag.get("perFile", []),
        "stats": diag.get("stats", {}),
    }
    if not table["ok"]:
        out["error"] = table.get("error")
    return out


# ------------------------------------------------------------------ 启动

def start_server(port=0, host="127.0.0.1"):
    # 启动即自检：核对 Praat 能否执行、脚本是否齐全、界面资源是否到位，
    # 结果写入 logs/ 并交给界面显示。放在这里是为了让"缺东西/被拦截"在启动
    # 阶段就暴露，而不是等跑测量时才冒出一个看不懂的 Praat 报错。
    try:
        selfcheck.run()
    except Exception:
        pass
    srv = ThreadingHTTPServer((host, port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv
