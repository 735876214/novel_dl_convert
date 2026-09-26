import asyncio
import base64
import contextlib
import csv
import hashlib
import io
import hmac
import json
import logging
import mimetypes
import pathlib
import re
import shutil
import threading
import time
import uuid
import zipfile
from urllib.parse import quote, unquote

import yaml

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Body, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .core import pipeline, activity_log, library, fileops, publish, scrape
from .core import watcher as watcher_mod
from .core import (db, stats, auth as auth_mod, ebook_convert, achievements, activity, recommend,
                   fonts, comics, audio, opds, komga, koreader, integrations, sync,
                   metasources, metafetch, metastore, komga_api, bookdock, metascore,
                   authors as authors_mod, narrators as narrators_mod, migrate, library_rules, features, series_meta,
                   lib_settings, browse_counts, customfields, embed, epub_cfi, txtcache)
from . import config
from .sources import REGISTRY, DownloadManager
from .sources import store
from .sources import rules as source_rules

# 启动即确保输入 / 导出 / 配置 / cookie / 缓存 / 用户书源 / 日志目录存在
# （用户书源在 novelforge.sources 包导入时已自动加载）
config.ensure_dirs()

# 全局监听器实例（生命周期内唯一）
WATCHER: "watcher_mod.FolderWatcher | None" = None


def _init_logging(cfg: dict):
    """按配置指定日志目录（留空则用 LOG_DIR 默认值）。"""
    d = (cfg.get("logging") or {}).get("dir")
    if d:
        activity_log.set_dir(d)


def _start_watcher(cfg: dict) -> "watcher_mod.FolderWatcher":
    global WATCHER
    if WATCHER is None:
        WATCHER = watcher_mod.FolderWatcher(cfg=cfg)
    WATCHER.on_scan = bookdock.note_scan      # 收书目录状态机回调（幂等绑定）
    if WATCHER.is_running():
        return WATCHER
    WATCHER.cfg = cfg
    WATCHER.start()
    return WATCHER


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = config.load_config()
    _init_logging(cfg)
    # 初始化 SQLite 持久层（进度 / 批注 / 账号），表与默认账号在此落地
    db.init()
    # 多书库：**这里不再播种任何书库** —— 全新部署的书库表就是空的，等用户手动新建。
    # ⚠️ 由此推出两条必须守住的不变量（第 37 期）：
    #   ① 书目为空**不等于**记录都成了孤儿 ⇒ `db.orphans()` 必须把「库已不存在」的书
    #      排除在孤儿之外，否则「清空全部书库 → 点清理孤儿」会把进度 / 批注真删；
    #   ② 没有可接收的库时摄入链路**拒收**（`library_rules.resolve_target` 返回 root=None），
    #      不再往 OUTPUT_DIR 塞「未归类」的书。
    # 第 17 期：book_id 库维度化的一次性迁移（跨库同名不再串 id）。幂等，跑过即跳过。
    try:
        res = db.upgrade_book_ids()
        if not res.get("skipped"):
            logging.getLogger("novelforge").info(
                "book_id 库维度迁移完成：索引 %s 个文件、迁移 %s 条关联",
                res.get("indexed"), res.get("moved"),
            )
    except Exception as e:  # 迁移失败不应阻断启动
        logging.getLogger("novelforge").exception("book_id 迁移失败：%s", e)
    # 第 35 期：旧配置项 metadata_fetch.custom_fields → 自定义字段定义（幂等，跑过即跳过）。
    # 迁移同时把 settings.json 里那枚旧键删掉（配置项下线）。
    try:
        created_fields = customfields.migrate_from_config(cfg)
        if created_fields:
            logging.getLogger("novelforge").info(
                "自定义字段迁移完成：%s 个字段（%s）",
                len(created_fields), "、".join(created_fields),
            )
    except Exception as e:  # noqa: BLE001 —— 迁移失败不该阻断启动
        logging.getLogger("novelforge").exception("自定义字段迁移失败：%s", e)
    if (cfg.get("watcher") or {}).get("enabled", True):
        w = _start_watcher(cfg)
        # 启动信息只进标准日志（docker logs），不污染「转换 / 添加」活动日志
        logging.getLogger("novelforge").info(
            "目录监听已启动：%s → %s（间隔 %ss）", w.input_dir, w.output_dir, w.interval
        )
    # 第 18 期：刮削出版 worker。**只在有未完成待办时启动** —— 队列是持久化的
    # （status='pending' 的行），重启要接着跑；没待办就不必白起一个后台线程。
    try:
        if (cfg.get("scrape") or {}).get("enabled", True) and db.scrape_pending(limit=1):
            scrape.start()
            logging.getLogger("novelforge").info("刮削 worker 已启动（续跑上次未完成的待办）")
    except Exception as e:  # noqa: BLE001 —— 旁路功能，绝不阻断启动
        logging.getLogger("novelforge").exception("刮削 worker 启动失败：%s", e)
    yield
    if WATCHER is not None:
        WATCHER.stop()
    scrape.stop()


# 应用版本（**唯一真值源**：FastAPI 与 /health 同读它；前端 About / 更新日志从后端取，
# 不再手写版本号）。第 30 期收敛为单一常量，结束「后端 0.5.0 / 前端 v0.6」两套真值源。
APP_VERSION = "0.6.0"

app = FastAPI(title="NovelForge", version=APP_VERSION, lifespan=lifespan)

STATIC_DIR = pathlib.Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

INPUT_DIR = config.INPUT_DIR
# ⚠️ 多书库（第 10 期）后这**不是**「唯一的根」，第 37 期起也不再是「默认库的根」
# （默认库这个概念已下线）。按书取路径一律用 `library.root_of(b) / b["name"]` ——
# 它对「库已被移除登记」的书会回退到 OUTPUT_DIR，正是这里。
OUTPUT_DIR = config.OUTPUT_DIR


# ---------------- 鉴权中间件（单用户轻登录）----------------
# 除 /health 与登录接口外，所有 /api 必须带有效 Bearer Token，否则 401。
# 静态资源（SPA 外壳）不拦，由前端登录门禁决定能否进入。

def _bearer(request: Request) -> str:
    hdr = request.headers.get("Authorization", "")
    return hdr[7:] if hdr.lower().startswith("bearer ") else ""


# `<img src>` 这类浏览器原生请求**无法携带 Authorization 头**，而 /api 前缀一律要求 Bearer。
# 因此下面这些**只读的图片代理接口**额外允许用 `?token=` 传令牌。
#
# 注意：这**没有放宽鉴权强度** —— 令牌仍然必须有效，只是多了一种携带方式；
# 并且严格限定在「GET + 这几个路径」，其余接口依旧只认请求头，不会出现
# 「任何接口都能用 query 传令牌」这种整体性放宽。
_MEDIA_TOKEN_PATHS = (
    re.compile(r"^/api/books/[^/]+/cover$"),
    re.compile(r"^/api/books/[^/]+/asset$"),
    # 字体文件：@font-face 的 src 同样是浏览器原生请求，带不了 Authorization 头
    re.compile(r"^/api/fonts/[^/]+/file$"),
    # 漫画单页：<img src> 同样是原生请求（PRD 的 PDF 用 fetch 带 httpHeaders，漫画用 img 更省内存）
    re.compile(r"^/api/books/[^/]+/comic/\d+$"),
    # 作者头像：同样是 <img src> 原生请求（第 8 期）
    re.compile(r"^/api/authors/[^/]+/photo$"),
    # 账号头像：同样是 <img src> 原生请求（第 25 期）；单用户，无需 {id}
    re.compile(r"^/api/account/avatar$"),
    # 有声书单轨：<audio src> 同样是原生请求，带不了 Authorization（第 9 期）
    re.compile(r"^/api/books/[^/]+/audio/\d+$"),
)


def _request_token(request: Request) -> str:
    tok = _bearer(request)
    if tok:
        return tok
    if request.method == "GET" and any(p.match(request.url.path) for p in _MEDIA_TOKEN_PATHS):
        return (request.query_params.get("token") or "").strip()
    return ""


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    path = request.url.path
    # `/api/logout` 是 Komga 的登出端点（不在 /api/v1 下），也要放行给 komga_api 那边处理
    if path in ("/health", "/api/auth/login", "/api/logout"):
        return await call_next(request)
    # Komga v1 兼容面（`/api/v1/*`）：第三方客户端发的是 **Basic / X-API-Key / 会话 cookie**，
    # 不是 Bearer。这里必须放行，由各路由自己走 `komga_api.verify()` 校验 —— 否则前缀判断
    # 会把客户端全部拦成 401。第 4 期的 OPDS 是为绕开它才另起了 `/opds` 前缀，
    # 但 Komga 客户端的 `/api/v1` 路径是**写死的**，绕不开。
    if path.startswith("/api/v1/"):
        return await call_next(request)
    if path.startswith("/api/"):
        token = _request_token(request)
        user = auth_mod.verify_token(token) if token else None
        if not user:
            return JSONResponse({"detail": "未授权，请先登录"}, status_code=401)
        request.state.user = user
        # 放进活动日志的「当前操作者」上下文：深层调用（core/fileops 等）没有
        # request 参数，靠它自动带上操作者，无需逐个函数透传。
        activity_log.set_actor(user)
    else:
        # 旧接口（/convert、/convert-path、/content、/download 等）不在 /api 前缀下，
        # 历史上就不强制鉴权（为油猴脚本等保留），因此这里只做**可选鉴权**：
        # 带了有效 token 就记录操作者，没带也不拦。
        # 否则审计日志在这条路径上永远拿不到「谁做的」。
        token = _bearer(request)
        if token:
            user = auth_mod.verify_token(token)
            if user:
                request.state.user = user
                activity_log.set_actor(user)
    return await call_next(request)

# 后台任务已落 SQLite（见 core/db.py 的 tasks 表）：重启后仍可查历史任务，
# 前端也不再需要伪造进度条。原先这里是进程内字典 `TASKS: dict = {}`（重启即清空）。


def _manager():
    return DownloadManager(config.load_config())


def _parse_rules_text(text: str) -> list:
    """解析书源文本：支持 JSON 对象、JSON 数组、或每行一个 JSON 的 JSONL。"""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = __import__("json").loads(text)
        return data if isinstance(data, list) else [data]
    except Exception:
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                out.append(__import__("json").loads(line))
            except Exception:
                continue
        return out


def _add_rules_list(rules: list) -> dict:
    added, errors = [], []
    for r in rules:
        if not isinstance(r, dict):
            errors.append({"name": "?", "error": "不是 JSON 对象"})
            continue
        try:
            store.add_rule(r)
            added.append(r.get("name"))
        except ValueError as e:
            errors.append({"name": r.get("name", "?"), "error": str(e)})
    return {"added": added, "errors": errors}


# ---------------- 页面与静态资源 ----------------

@app.get("/")
def index():
    # 前端是 Vue 构建产物，落在 static/v2/（见 frontend/ 与 Dockerfile 的 frontend 阶段）。
    # 产物不入库（.gitignore），由 `npm run deploy` 或镜像构建生成。
    page = STATIC_DIR / "v2" / "index.html"
    if not page.is_file():
        raise HTTPException(
            503,
            "前端尚未构建：请在 frontend/ 下执行 npm install && npm run build && npm run deploy",
        )
    return FileResponse(str(page))


@app.get("/health")
def health():
    return {
        "status": "ok",
        "input": str(INPUT_DIR),
        "output": str(OUTPUT_DIR),
        "watcher": bool(WATCHER and WATCHER.is_running()),
        # 应用版本（**只读**、免鉴权端点，不含任何敏感信息）；前端 About / 更新日志据此渲染
        "version": APP_VERSION,
        "logs": str(activity_log.log_dir()),
    }


# ---------------- 书源管理 ----------------

@app.get("/api/sources")
def api_list_sources():
    return {"sources": store.list_sources()}


@app.get("/api/sources/status")
def api_sources_status():
    """书源运行状态：Cookie 是否已持久化、当前配置下是否可用。"""
    return {"items": store.sources_status()}


@app.post("/api/sources")
async def api_add_sources(request: Request):
    text = (await request.body()).decode("utf-8", errors="ignore")
    rules = _parse_rules_text(text)
    if not rules:
        raise HTTPException(400, "无法解析书源：请粘贴 JSON 对象 / 数组 / JSONL")
    return _add_rules_list(rules)


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    """按上限分块读取上传内容；超限抛 413。

    ⚠️ 刻意**不用** `await file.read()` —— 那是一次性把整个请求体读进内存，
    此前两个上传接口都是这么写的且**没有任何上限**，上传一个大文件即可打满容器内存。
    分块累计的好处：一旦超过上限立刻中断，不会「先读完再判断」。
    """
    chunks: list = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)      # 每次 1 MiB
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"文件超过上限（{_human_size(limit)}）")
        chunks.append(chunk)
    return b"".join(chunks)


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(n)} B"


def _upload_limit(key: str) -> int:
    """读取上传上限；值非法或 <= 0 时回退内置默认。

    回退而非放行，是为了避免「配置写坏 = 变回无限制」这种静默降级。
    """
    default = (config.DEFAULTS.get("upload") or {}).get(key)
    raw = (config.load_config().get("upload") or {}).get(key, default)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = int(default)
    return val if val > 0 else int(default)


@app.post("/api/sources/upload")
async def api_upload_sources(file: UploadFile = File(...)):
    raw = await _read_capped(file, _upload_limit("max_source_rules_bytes"))
    text = raw.decode("utf-8", errors="ignore")
    rules = _parse_rules_text(text)
    if not rules:
        raise HTTPException(400, "文件内容无法解析为书源 JSON")
    return _add_rules_list(rules)


@app.delete("/api/sources/{name}")
def api_delete_source(name: str):
    if not store.remove_rule(name):
        raise HTTPException(404, "书源不存在或为内置源（不可删）")
    return {"ok": True}


@app.post("/api/sources/test")
async def api_sources_test(payload: dict = Body(...)):
    """书源试搜（**不落盘**）：保存前先确认「这条规则真的能搜到东西」。

    body 两种形态：
    - ``{"rule": {...}, "query": "关键词"}``：表单模式 —— 规则先过 `validate_rule` 逐条校验，
      通过后用 `make_rule_class` 建**临时类**跑一次搜索；
    - ``{"name": "已注册源", "query": ...}``：测已有源（含用户源与内置源）。

    ⚠️ 测试用的规则**只存在于本次请求**，绝不写进 `SOURCES_DIR` —— 写盘的唯一入口仍是
    `store.add_rule`（`/api/sources`）。失败原因如实回给前端（校验错误 / 网络错误 / 解析不到结果），
    而不是像批量搜索那样静默跳过。
    """
    p = payload or {}
    query = str(p.get("query") or "").strip() or "三体"
    name = str(p.get("name") or "").strip()
    if name and not p.get("rule"):
        cls = REGISTRY.get(name)
        if cls is None:
            raise HTTPException(404, f"书源不存在：{name}")
    else:
        errors = source_rules.validate_rule(p.get("rule"))
        if errors:
            return {"ok": False, "errors": errors, "count": 0, "items": [], "error": ""}
        try:
            cls = source_rules.make_rule_class(p["rule"])
        except ValueError as e:
            return {"ok": False, "errors": [str(e)], "count": 0, "items": [], "error": ""}
    try:
        items = await _manager().test_source(cls, query)
    except Exception as e:                              # noqa: BLE001 —— 试搜失败要把原因给人看
        return {"ok": False, "errors": [], "count": 0, "items": [], "error": f"{e}"}
    out = [{"title": str(it.get("title") or ""), "author": str(it.get("author") or ""),
            "url": str(it.get("url") or "")} for it in items[:5]]
    return {"ok": True, "errors": [], "count": len(items), "items": out, "error": ""}


# ---------------- 搜索 / 预览 / 下载 ----------------

@app.post("/api/search")
async def api_search(payload: dict = Body(...)):
    title = (payload or {}).get("title", "").strip()
    if not title:
        raise HTTPException(400, "书名不能为空")
    mgr = _manager()
    try:
        results = await mgr.search(title)
    except Exception as e:
        raise HTTPException(502, f"搜索失败: {e}")
    return {"count": len(results), "results": results}


@app.get("/api/preview")
async def api_preview(source: str = Query(...), url: str = Query(...)):
    mgr = _manager()
    try:
        data = await mgr.preview({"_source": source, "url": url})
    except Exception as e:
        raise HTTPException(502, f"预览失败: {e}")
    return data


def _task_out(row: dict | None) -> dict:
    """把任务行整理成前端要的形状。

    保留 `name` 这个字段名（DB 里叫 `fname`），避免前端为改名而改两处。
    """
    if not row:
        return {}
    row = dict(row)
    row["name"] = row.get("fname") or ""
    return row


@app.post("/api/download")
async def api_download(request: Request, item: dict = Body(...)):
    tid = uuid.uuid4().hex
    # 下载在后台任务里跑，届时可能已离开请求上下文 —— 因此在这里把操作者取出来显式带过去，
    # 保证审计日志里「谁发起的下载」是准确的。
    actor = getattr(request.state, "user", "") or "系统"
    title = item.get("title") or item.get("url") or "(未命名)"
    detail = " · ".join(str(x) for x in (item.get("source"), item.get("format")) if x)
    db.task_create(tid, "download", title, detail=detail, actor=actor)
    db.task_prune()          # 只留最近 200 条，避免表无限增长
    asyncio.create_task(_run_download(tid, item, actor))
    return {"task_id": tid}


async def _run_download(tid: str, item: dict, actor: str = "系统"):
    # progress 只记**真实里程碑**：0 = 已入队、50 = 已开始、100 = 已结束。
    # 下载器不报细分进度，因此不伪造中间百分比。
    db.task_update(tid, status="running", progress=50.0)
    try:
        mgr = _manager()
        # 多书库：书源下载走产出 EPUB，按「来源子目录名 → 格式 → 关键词」归库。
        # 没有可接收的库（一个库都没有，或规则不命中）⇒ 拒收，如实报错，不猜落点。
        _dl_name = f"{item.get('title') or 'book'}.epub"
        tgt = library_rules.resolve_target(
            name=_dl_name,
            meta={"title": item.get("title"), "author": item.get("author")},
        )
        if tgt["root"] is None:
            raise RuntimeError(library_rules.no_library_reason(name=_dl_name))
        # 第 13 期：产物格式 / 落盘布局按**目标库**取（库没覆写时等于全局值）
        opts = {"force": True, "merge": True,
                "cfg": lib_settings.config_for(tgt["library_id"] or None)}
        res = await mgr.download_to(item, tgt["root"], INPUT_DIR, opts)
        notice = opts.get("_notice", "")
        name = pathlib.Path(res).name
        db.task_update(tid, status="done", progress=100.0,
                       result=f"/download/{name}", fname=name, notice=notice)
        activity_log.log_convert_ok(
            item.get("title") or name, name, source="download",
            size=(pathlib.Path(res).stat().st_size if pathlib.Path(res).exists() else None),
            detail=notice, actor=actor,
        )
        # 下载已顺带生成 EPUB，把刚落盘的 txt 登记为已处理，避免监听线程重复转换
        if WATCHER is not None:
            await asyncio.to_thread(WATCHER.mark_recent, seconds=30, suffix=".txt")
    except Exception as e:
        db.task_update(tid, status="failed", progress=100.0, error=str(e))
        activity_log.log_convert_fail(
            item.get("title") or item.get("url") or "(未命名)",
            f"{type(e).__name__}: {e}", source="download", actor=actor,
        )


@app.get("/api/tasks")
def api_tasks(limit: int = 100, status: str = ""):
    """任务列表（新 → 旧），可选按状态过滤。

    这是**真实任务表**：前端据此渲染状态与失败原因，不再有演示种子与假推进。
    """
    items = [_task_out(r) for r in db.task_list(limit)]
    if status:
        items = [i for i in items if i.get("status") == status]
    return {"items": items, "count": len(items)}


@app.get("/api/tasks/{tid}")
def api_task(tid: str):
    t = db.task_get(tid)
    if not t:
        raise HTTPException(404, "任务不存在")
    return _task_out(t)


# ---------------- 文件列表 / 下载成品 ----------------

@app.get("/api/files")
def list_files():
    def _stat(d):
        out = []
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            try:
                st = f.stat()
                out.append({"name": f.name, "size": st.st_size, "mtime": st.st_mtime})
            except OSError:
                out.append({"name": f.name, "size": None, "mtime": None})
        return out
    return {"input": _stat(INPUT_DIR), "output": _stat(OUTPUT_DIR)}


@app.get("/download/{name}")
def download_file(name: str):
    target = OUTPUT_DIR / name
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target, filename=name)


# ---------------- OPDS 目录订阅源 ----------------
# ⚠️ 刻意**不用 /api/ 前缀**：鉴权中间件对 /api/ 一律要求 Bearer Token，
#    而 OPDS 客户端只会发 HTTP Basic（且多数不支持自定义请求头）。
#    因此这里自带 Basic 校验，账号就是应用账号（复用 auth.verify_pin，不另建凭据）。
#
# 关闭时返回 **404 而不是 401/403**：客户端遇到 401 会反复弹密码框、
# 遇到 403 常报「无权限」，404 才会老实显示「找不到目录」——这更接近用户的真实意图
# （没打算用 OPDS）。

_OPDS_401 = {"WWW-Authenticate": 'Basic realm="NovelForge OPDS", charset="UTF-8"'}


def _opds_guard(request: Request) -> None:
    if not (config.load_config().get("opds") or {}).get("enabled"):
        raise HTTPException(404, "OPDS 未启用")
    header = request.headers.get("Authorization") or ""
    if not header.lower().startswith("basic "):
        raise HTTPException(401, "需要 Basic 认证", headers=_OPDS_401)
    try:
        raw = base64.b64decode(header[6:].strip()).decode("utf-8", "replace")
        user, _, pin = raw.partition(":")
    except Exception:
        raise HTTPException(401, "凭据格式错误", headers=_OPDS_401)
    if not user or not auth_mod.verify_pin(user, pin):
        raise HTTPException(401, "账号或 PIN 不正确", headers=_OPDS_401)


def _opds_base(request: Request) -> str:
    """客户端看到的根地址。优先 X-Forwarded-*，兼容反代/子路径部署（NAS 常见）。"""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    prefix = (request.headers.get("x-forwarded-prefix") or "").rstrip("/")
    return f"{proto}://{host}{prefix}"


def _opds_xml(body: str, kind: str = "acquisition") -> Response:
    """OPDS 的 content-type 必须带 profile，否则部分客户端不认（当成普通 Atom）。"""
    return Response(
        content=body,
        media_type=f"application/atom+xml;profile=opds-catalog;kind={kind}",
    )


def _opds_groups(bs: list) -> tuple:
    """(作者, 系列, 标签) 三组「名称 + 数量」，按数量倒序、名称次序为稳定副序。"""
    from collections import Counter

    authors = Counter((b.get("author") or "").strip() for b in bs)
    series = Counter((b.get("series") or "").strip() for b in bs)
    tags = Counter(str(x).strip() for b in bs for x in (b.get("tags") or []))
    for c in (authors, series, tags):
        c.pop("", None)
    key = lambda kv: (-kv[1], kv[0].lower())  # noqa: E731
    return (
        sorted(authors.items(), key=key),
        sorted(series.items(), key=key),
        sorted(tags.items(), key=key),
    )


def _opds_updated(bs: list) -> float:
    return max([b.get("mtime") or 0 for b in bs] or [0])


@app.get("/opds")
def opds_root(request: Request):
    """根导航 feed（客户端订阅这个地址）。"""
    _opds_guard(request)
    bs = library.books()
    a, s, t = _opds_groups(bs)
    counts = {"all": len(bs), "authors": len(a), "series": len(s), "tags": len(t),
              "updated": _opds_updated(bs)}
    # 书库入口只在「可见库多于一个」时出现（单库部署输出与加它之前逐字节一致）
    libs = [(str(l.get("id") or ""), str(l.get("name") or ""),
             len(library.books(library_id=str(l.get("id") or ""))))
            for l in _opds_visible_libraries()]
    return _opds_xml(opds.navigation_feed(_opds_base(request), counts, libraries=libs),
                     "navigation")


@app.get("/opds/all")
def opds_all(request: Request, page: int = Query(1, ge=1),
             sort: str = Query("recent"), order: str = Query("desc")):
    _opds_guard(request)
    bs = opds.sort_books(library.books(), sort, order)
    return _opds_xml(opds.acquisition_feed(_opds_base(request), "全部书籍", "all", bs,
                                           page=page, sort=sort, order=order))


@app.get("/opds/recent")
def opds_recent(request: Request, page: int = Query(1, ge=1)):
    _opds_guard(request)
    bs = opds.sort_books(library.books(), "recent", "desc")
    return _opds_xml(opds.acquisition_feed(_opds_base(request), "最近添加", "recent", bs, page=page))


@app.get("/opds/authors")
def opds_authors(request: Request):
    _opds_guard(request)
    bs = library.books()
    a, _, _ = _opds_groups(bs)
    return _opds_xml(opds.group_navigation(_opds_base(request), "按作者", "author", a,
                                           _opds_updated(bs)), "navigation")


@app.get("/opds/series")
def opds_series(request: Request):
    _opds_guard(request)
    bs = library.books()
    _, s, _ = _opds_groups(bs)
    # 系列简介一并下发，订阅端在系列列表就能看到（作者 / 标签页不传 → 输出与之前一致）
    rows = db.all_series_meta()
    descs = {name: series_meta.effective_light(name, rows.get(name) or {})["description"]
             for name, _count in s}
    return _opds_xml(opds.group_navigation(_opds_base(request), "按系列", "series", s,
                                           _opds_updated(bs), descriptions=descs), "navigation")


@app.get("/opds/tags")
def opds_tags(request: Request):
    _opds_guard(request)
    bs = library.books()
    _, _, t = _opds_groups(bs)
    return _opds_xml(opds.group_navigation(_opds_base(request), "按标签", "tag", t,
                                           _opds_updated(bs)), "navigation")


@app.get("/opds/author/{name}")
def opds_by_author(request: Request, name: str, page: int = Query(1, ge=1)):
    _opds_guard(request)
    target = unquote(name).strip()
    bs = [b for b in library.books() if (b.get("author") or "").strip() == target]
    if not bs:
        raise HTTPException(404, "没有该作者的书")
    bs = opds.sort_books(bs, "title", "asc")
    return _opds_xml(opds.acquisition_feed(_opds_base(request), f"作者：{target}", "author",
                                           bs, page=page))


@app.get("/opds/series/{name}")
def opds_by_series(request: Request, name: str, page: int = Query(1, ge=1)):
    _opds_guard(request)
    target = unquote(name).strip()
    bs = [b for b in library.books() if (b.get("series") or "").strip() == target]
    if not bs:
        raise HTTPException(404, "没有该系列的书")
    # 系列内按「系列序号」自然序（sort=series 用的是同系列键，正好）
    bs = opds.sort_books(bs, "series", "asc")
    desc = series_meta.effective_light(target)["description"]
    return _opds_xml(opds.acquisition_feed(_opds_base(request), f"系列：{target}", "series",
                                           bs, page=page, subtitle=desc))


@app.get("/opds/tag/{name}")
def opds_by_tag(request: Request, name: str, page: int = Query(1, ge=1)):
    _opds_guard(request)
    target = unquote(name).strip()
    bs = [b for b in library.books()
          if target in [str(x).strip() for x in (b.get("tags") or [])]]
    if not bs:
        raise HTTPException(404, "没有该标签的书")
    bs = opds.sort_books(bs, "title", "asc")
    return _opds_xml(opds.acquisition_feed(_opds_base(request), f"标签：{target}", "tag",
                                           bs, page=page))


@app.get("/opds/search")
def opds_search(request: Request, q: str = Query(""), page: int = Query(1, ge=1)):
    """搜索。客户端在搜索框提交时带上 q（OpenSearch 惯例）。"""
    _opds_guard(request)
    term = (q or "").strip().lower()
    bs = library.books()
    if term:
        bs = [b for b in bs
              if term in (b.get("title") or "").lower()
              or term in (b.get("author") or "").lower()
              or term in (b.get("series") or "").lower()]
    else:
        bs = []
    bs = opds.sort_books(bs, "title", "asc")
    title = f"搜索：{q}" if term else "搜索（请带 ?q= 参数）"
    return _opds_xml(opds.acquisition_feed(_opds_base(request), title, "search", bs, page=page))


@app.get("/opds/book/{bid}")
def opds_book(request: Request, bid: str):
    _opds_guard(request)
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    return _opds_xml(opds.book_feed(_opds_base(request), b))


@app.get("/opds/cover/{bid}")
def opds_cover(request: Request, bid: str):
    """封面：直接复用应用内的封面实现（EPUB 内嵌图 / CBZ 第一页），避免两份解析逻辑走样。"""
    _opds_guard(request)
    return api_book_cover(bid)


@app.get("/opds/download/{bid}")
def opds_download(request: Request, bid: str):
    _opds_guard(request)
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    path = library.root_of(b) / b["name"]
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, media_type=opds.mime_of(b.get("format")), filename=b["name"])


# ---------------- OPDS 按库暴露（第 14 期）----------------
# 书库在第 10 期之后已经是**数据实体**，但对外目录仍只有一个「全库」视图：客户端订阅
# `/opds` 看到的是所有库混在一起。这里补上库维度 —— 既能订阅全部，也能单独订阅某个库。
#
# 三条口径（改这里之前先看一眼）：
# 1. **库只能落在路径上**。OPDS 客户端只会发 URL（多数连自定义头都不支持），且订阅的是
#    固定地址，所以不加 `?library=` 查询参数，而是给单库整套独立前缀。
# 2. **默认零变化**。`/opds`、`/opds/all` 等既有地址一行没动，输出字节也不变 —— 已经订阅
#    出去的地址不能因为升级而失效。
# 3. **「不可见」与「不存在」对客户端一律 404**。不给任何「这里有个库只是不让你看」的暗示。


def _opds_visible_libraries() -> list:
    """对 OPDS 可见的书库：库类型具备该能力，且开关开着。

    开关取 **每库覆写 ?? 全局**（与 `lib_settings` 的其它覆盖项同口径）：全局默认
    `opds.expose = True`，即**全部书库都暴露**，与加这个开关之前的行为完全一致。
    """
    cfg = config.load_config()
    default = bool((cfg.get("opds") or {}).get("expose", True))
    out = []
    for lib in library.libraries():
        lid = str(lib.get("id") or "")
        if not features.allows_setting(str(lib.get("type") or "mixed"), "opds.expose"):
            continue                        # 库类型没这能力 → 覆写即便残留也不生效
        ov = lib_settings.overrides(lid).get("opds.expose")
        if not (default if ov is None else bool(ov)):
            continue
        out.append(lib)
    return out


def _opds_lib(lid: str) -> dict:
    """取一个**对 OPDS 可见**的书库；不存在 / 不可见都 404。"""
    target = unquote(str(lid or "")).strip()
    for lib in _opds_visible_libraries():
        if str(lib.get("id") or "") == target:
            return lib
    raise HTTPException(404, "书库不存在或未对 OPDS 暴露")


def _opds_prefix(lib_id: str) -> str:
    return f"/opds/lib/{quote(str(lib_id), safe='')}"


def _opds_fid(lib_id: str, section: str) -> str:
    """单库 feed 的 urn。带上库 id，免得与全局同名 section 撞 id（客户端按 id 去重）。"""
    return f"urn:novelforge:opds:lib:{lib_id}:{section}"


def _opds_book_in(lib_id: str, bid: str) -> "dict | None":
    """在该库书目内按 id 取书 —— **不用** `library.by_id`（跨库同名会抛 `BookIdConflict`）。

    单库模式下的详情 / 封面 / 下载都经过这里，于是「这本书在不在该库」只有这一处判定。
    """
    for b in library.books(library_id=lib_id):
        if b.get("id") == bid:
            return b
    return None


@app.get("/opds/libraries")
def opds_libraries(request: Request):
    """书库导航：列出对 OPDS 可见的书库，每个带册数。"""
    _opds_guard(request)
    libs = _opds_visible_libraries()
    rows = [(str(l.get("id") or ""), str(l.get("name") or ""),
             len(library.books(library_id=str(l.get("id") or "")))) for l in libs]
    return _opds_xml(opds.library_navigation(_opds_base(request), rows,
                                             _opds_updated(library.books())), "navigation")


@app.get("/opds/lib/{lid}")
def opds_lib_root(request: Request, lid: str):
    """单库根导航（客户端可以只订阅这一个库）。"""
    _opds_guard(request)
    lib = _opds_lib(lid)
    lib_id = str(lib["id"])
    bs = library.books(library_id=lib_id)
    a, s, t = _opds_groups(bs)
    counts = {"all": len(bs), "authors": len(a), "series": len(s), "tags": len(t),
              "updated": _opds_updated(bs)}
    return _opds_xml(opds.navigation_feed(
        _opds_base(request), counts, prefix=_opds_prefix(lib_id),
        title=str(lib.get("name") or "书库"), feed_id=_opds_fid(lib_id, "root")),
        "navigation")


@app.get("/opds/lib/{lid}/all")
def opds_lib_all(request: Request, lid: str, page: int = Query(1, ge=1),
                 sort: str = Query("recent"), order: str = Query("desc")):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    bs = opds.sort_books(library.books(library_id=lib_id), sort, order)
    return _opds_xml(opds.acquisition_feed(
        _opds_base(request), "全部书籍", "all", bs, page=page, sort=sort, order=order,
        prefix=_opds_prefix(lib_id), feed_id=_opds_fid(lib_id, "all")), "acquisition")


@app.get("/opds/lib/{lid}/recent")
def opds_lib_recent(request: Request, lid: str, page: int = Query(1, ge=1)):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    bs = opds.sort_books(library.books(library_id=lib_id), "recent", "desc")
    return _opds_xml(opds.acquisition_feed(
        _opds_base(request), "最近添加", "recent", bs, page=page,
        prefix=_opds_prefix(lib_id), feed_id=_opds_fid(lib_id, "recent")), "acquisition")


@app.get("/opds/lib/{lid}/authors")
def opds_lib_authors(request: Request, lid: str):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    bs = library.books(library_id=lib_id)
    a, _, _ = _opds_groups(bs)
    return _opds_xml(opds.group_navigation(
        _opds_base(request), "按作者", "author", a, _opds_updated(bs),
        prefix=_opds_prefix(lib_id), feed_id=_opds_fid(lib_id, "author")), "navigation")


@app.get("/opds/lib/{lid}/series")
def opds_lib_series(request: Request, lid: str):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    bs = library.books(library_id=lib_id)
    _, s, _ = _opds_groups(bs)
    rows = db.all_series_meta()
    descs = {name: series_meta.effective_light(name, rows.get(name) or {})["description"]
             for name, _count in s}
    return _opds_xml(opds.group_navigation(
        _opds_base(request), "按系列", "series", s, _opds_updated(bs), descriptions=descs,
        prefix=_opds_prefix(lib_id), feed_id=_opds_fid(lib_id, "series")), "navigation")


@app.get("/opds/lib/{lid}/tags")
def opds_lib_tags(request: Request, lid: str):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    bs = library.books(library_id=lib_id)
    _, _, t = _opds_groups(bs)
    return _opds_xml(opds.group_navigation(
        _opds_base(request), "按标签", "tag", t, _opds_updated(bs),
        prefix=_opds_prefix(lib_id), feed_id=_opds_fid(lib_id, "tag")), "navigation")


@app.get("/opds/lib/{lid}/author/{name}")
def opds_lib_by_author(request: Request, lid: str, name: str, page: int = Query(1, ge=1)):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    target = unquote(name).strip()
    bs = [b for b in library.books(library_id=lib_id)
          if (b.get("author") or "").strip() == target]
    if not bs:
        raise HTTPException(404, "该书库没有这位作者的书")
    bs = opds.sort_books(bs, "title", "asc")
    return _opds_xml(opds.acquisition_feed(
        _opds_base(request), f"作者：{target}", "author", bs, page=page,
        prefix=_opds_prefix(lib_id), feed_id=_opds_fid(lib_id, "author")), "acquisition")


@app.get("/opds/lib/{lid}/series/{name}")
def opds_lib_by_series(request: Request, lid: str, name: str, page: int = Query(1, ge=1)):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    target = unquote(name).strip()
    bs = [b for b in library.books(library_id=lib_id)
          if (b.get("series") or "").strip() == target]
    if not bs:
        raise HTTPException(404, "该书库没有这个系列的书")
    bs = opds.sort_books(bs, "series", "asc")
    desc = series_meta.effective_light(target)["description"]
    return _opds_xml(opds.acquisition_feed(
        _opds_base(request), f"系列：{target}", "series", bs, page=page, subtitle=desc,
        prefix=_opds_prefix(lib_id), feed_id=_opds_fid(lib_id, "series")), "acquisition")


@app.get("/opds/lib/{lid}/tag/{name}")
def opds_lib_by_tag(request: Request, lid: str, name: str, page: int = Query(1, ge=1)):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    target = unquote(name).strip()
    bs = [b for b in library.books(library_id=lib_id)
          if target in [str(x).strip() for x in (b.get("tags") or [])]]
    if not bs:
        raise HTTPException(404, "该书库没有这个标签的书")
    bs = opds.sort_books(bs, "title", "asc")
    return _opds_xml(opds.acquisition_feed(
        _opds_base(request), f"标签：{target}", "tag", bs, page=page,
        prefix=_opds_prefix(lib_id), feed_id=_opds_fid(lib_id, "tag")), "acquisition")


@app.get("/opds/search/description")
def opds_search_description(request: Request):
    """OpenSearch Description：客户端据此拿到搜索地址模板（否则搜索框多半不出现）。"""
    _opds_guard(request)
    return Response(content=opds.search_description(_opds_base(request)),
                    media_type="application/opensearchdescription+xml")


@app.get("/opds/lib/{lid}/search/description")
def opds_lib_search_description(request: Request, lid: str):
    """单库版 OSDD：模板落在该库内（订阅单个库时搜索也只搜这个库）。"""
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    return Response(
        content=opds.search_description(_opds_base(request), prefix=_opds_prefix(lib_id)),
        media_type="application/opensearchdescription+xml")


@app.get("/opds/lib/{lid}/search")
def opds_lib_search(request: Request, lid: str, q: str = Query(""),
                    page: int = Query(1, ge=1)):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    term = (q or "").strip().lower()
    bs = library.books(library_id=lib_id)
    if term:
        bs = [b for b in bs
              if term in (b.get("title") or "").lower()
              or term in (b.get("author") or "").lower()
              or term in (b.get("series") or "").lower()]
    else:
        bs = []
    bs = opds.sort_books(bs, "title", "asc")
    title = f"搜索：{q}" if term else "搜索（请带 ?q= 参数）"
    return _opds_xml(opds.acquisition_feed(
        _opds_base(request), title, "search", bs, page=page,
        prefix=_opds_prefix(lib_id), feed_id=_opds_fid(lib_id, "search")), "acquisition")


@app.get("/opds/lib/{lid}/book/{bid}")
def opds_lib_book(request: Request, lid: str, bid: str):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    b = _opds_book_in(lib_id, bid)
    if not b:
        raise HTTPException(404, "书籍不在该书库内")
    return _opds_xml(opds.book_feed(_opds_base(request), b, prefix=_opds_prefix(lib_id)))


@app.get("/opds/lib/{lid}/cover/{bid}")
def opds_lib_cover(request: Request, lid: str, bid: str):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    if not _opds_book_in(lib_id, bid):
        raise HTTPException(404, "书籍不在该书库内")
    return api_book_cover(bid)


@app.get("/opds/lib/{lid}/download/{bid}")
def opds_lib_download(request: Request, lid: str, bid: str):
    _opds_guard(request)
    lib_id = str(_opds_lib(lid)["id"])
    b = _opds_book_in(lib_id, bid)
    if not b:
        raise HTTPException(404, "书籍不在该书库内")
    path = library.root_of(b) / b["name"]
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, media_type=opds.mime_of(b.get("format")), filename=b["name"])


# ---------------- 书库（图书馆浏览 / 书籍详情）----------------
# 数据源同样是扫描 OUTPUT_DIR（见 core/library.py）。列表走缓存，详情按需抽取
# EPUB 章节树；任何写操作后 library.invalidate() 保证一致性。

@app.get("/api/books")
def api_books():
    """书目列表：附带阅读进度 / 批注数 / 评分 / 阅读状态（来自 SQLite）。"""
    prog = db.all_progress()
    annos = db.annotation_counts()
    ratings = db.all_ratings()
    statuses = db.all_statuses()
    colls = db.collection_map()
    items = []
    for b in library.books():
        p = prog.get(b["id"])
        st = statuses.get(b["id"])
        items.append({
            **b,
            "percent": float(p["percent"]) if p else 0.0,
            "updated_at": p["updated_at"] if p else 0.0,
            "annotation_count": annos.get(b["id"], 0),
            # 评分：0 = 未评分（见 core/db.py 的说明，未评分不用 0 星表示）
            "stars": ratings.get(b["id"], 0),
            # 阅读状态：**真实状态优先**。没有状态行的书给 None，
            # 由前端用进度兜底推导 —— 不能在这里编一个 'unread'，
            # 否则「有进度但没标状态」的老书会被误判成未读。
            "status": st["status"] if st else None,
            "started_at": (st or {}).get("started_at") or 0,
            "finished_at": (st or {}).get("finished_at") or 0,
            # 所属收藏夹 id（第 34 期）：实体浏览页按「收藏」维度分组要用；
            # 一次批量取（**不逐本查**），不在任何夹里就是空数组。
            "collection_ids": colls.get(b["id"], []),
        })
    return {"items": items, "total": len(items)}


# ⚠️ 导出端点必须注册在 /api/books/{bid} **之前**：
#    FastAPI 按注册顺序匹配，参数化路由在前会把 "export" 当成书 id 吞掉。
@app.get("/api/books/export")
def api_export_books():
    """导出全部书目为 CSV（含阅读进度 / 状态 / 评分），供 Excel / Calibre 查看。

    CSV 前面加 UTF-8 BOM：不加的话 Excel（Windows）按本地编码解析，中文全乱码。
    """
    import csv
    import io

    from fastapi import Response

    prog = db.all_progress()
    statuses = db.all_statuses()
    ratings = db.all_ratings()
    annos = db.annotation_counts()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["书名", "文件名", "作者", "系列", "序号", "格式", "大小(字节)",
                "出版年", "出版社", "语言", "ISBN", "题材", "入库日期",
                "阅读进度%", "阅读状态", "评分", "批注数"])
    for b in library.export_rows():
        bid = b["id"]
        st = statuses.get(bid)
        w.writerow([
            b["title"], b["name"], b["author"], b["series"], b["series_index"],
            b["format"], b["size"], b["year"], b["publisher"], b["language"],
            b["isbn"], b["tags"], b["added"],
            round(float(prog[bid]["percent"]), 1) if prog.get(bid) else 0,
            (st or {}).get("status") or "",
            ratings.get(bid, 0),
            annos.get(bid, 0),
        ])
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="library-export.csv"'},
    )


@app.put("/api/books/{bid}/rating")
def api_set_rating(bid: str, request: Request, payload: dict = Body(...)):
    """给书评分（1–5 星）。对应上游成就体系里 4 条依赖评分的条目。"""
    if not library.by_id(bid):
        raise HTTPException(404, "书籍不存在")
    try:
        r = db.set_rating(bid, (payload or {}).get("stars"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _sync_auto_push(bid, request)
    return r


@app.delete("/api/books/{bid}/rating")
def api_clear_rating(bid: str, request: Request):
    """取消评分。"""
    n = db.clear_rating(bid)
    _sync_auto_push(bid, request)
    return {"ok": True, "cleared": n}


# ⚠️ 批量端点必须注册在 /api/books/{bid} **之前**：
#    FastAPI 按注册顺序匹配，参数化路由在前会把 "batch" 当成书 id 吞掉
#    （与 /api/books/export 同一个坑）。
@app.post("/api/books/batch")
def api_batch(payload: dict = Body(...)):
    """批量动作：镜像单本能力，但一次作用于多本书。

    动作（与现有单本接口一一对应，不引入新数据模型）：
      · set_status         params: {status, started_at?, finished_at?} → db.set_status
      · set_rating         params: {stars}（0 = 清除评分）→ set_rating / clear_rating
      · add_to_collection  params: {collection_id} → db.add_book_to_collection

    逐本执行，单本失败不影响其余；返回成功/失败清单，前端据此提示。
    """
    if not isinstance(payload, dict):
        raise HTTPException(400, "请求体必须是 JSON 对象")
    action = str(payload.get("action") or "")
    ids = payload.get("ids") or []
    params = payload.get("params") or {}
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "ids 必须为非空数组")
    if action not in ("set_status", "set_rating", "add_to_collection"):
        raise HTTPException(400, f"不支持的批量动作：{action}")

    succeeded: list = []
    failed: list = []
    for bid in ids:
        bid = str(bid)
        if not library.by_id(bid):
            failed.append({"id": bid, "error": "书籍不存在"})
            continue
        try:
            if action == "set_status":
                db.set_status(
                    bid,
                    str(params.get("status") or ""),
                    started_at=params.get("started_at"),
                    finished_at=params.get("finished_at"),
                )
            elif action == "set_rating":
                stars = int(params.get("stars", 0))
                if stars == 0:
                    db.clear_rating(bid)
                else:
                    db.set_rating(bid, stars)
            elif action == "add_to_collection":
                db.add_book_to_collection(int(params.get("collection_id")), bid)
        except (ValueError, TypeError) as e:
            failed.append({"id": bid, "error": str(e)})
            continue
        succeeded.append(bid)
    return {"ok": True, "total": len(ids), "succeeded": succeeded, "failed": failed}


@app.get("/api/books/{bid}")
def api_book_detail(bid: str):
    for b in library.books():
        if b["id"] == bid:
            detail = library.book_detail(b["name"])
            if detail:
                return detail
    raise HTTPException(404, "书籍不存在")


# ---------------- 账户（单用户轻登录）----------------

@app.post("/api/auth/login")
def api_login(payload: dict = Body(...)):
    user = str(payload.get("user", "") or "")
    pin = str(payload.get("pin", "") or "")
    if not auth_mod.verify_pin(user, pin):
        raise HTTPException(401, "账号或密码错误")
    return {"token": auth_mod.issue_token(user), "user": user}


@app.get("/api/auth/me")
def api_me(request: Request):
    return {"user": getattr(request.state, "user", None) or ""}


@app.post("/api/auth/pin")
def api_change_pin(request: Request, payload: dict = Body(...)):
    """修改当前账号密码（需校验原密码）。"""
    user = getattr(request.state, "user", "") or ""
    old = str(payload.get("old_pin") or "")
    new = str(payload.get("new_pin") or "")
    if not user or not auth_mod.verify_pin(user, old):
        raise HTTPException(400, "原密码不正确")
    if len(new) < 4:
        raise HTTPException(400, "新密码至少 4 位")
    db.set_pin(user, new)
    return {"ok": True}


# ---------------- 阅读器：章节内容 / 资源 / 进度 / 批注 ----------------
# 阅读进度与批注落在 SQLite（见 core/db.py），多端共享同一持久卷即可一致。

@app.get("/api/books/{bid}/asset")
def api_book_asset(bid: str, p: str = Query(..., description="zip 内资源相对路径")):
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    path = library.root_of(b) / b["name"]
    with zipfile.ZipFile(path) as z:
        if p not in z.namelist():
            raise HTTPException(404, "资源不存在")
        data = z.read(p)
        ct = mimetypes.guess_type(p)[0] or "application/octet-stream"
        return Response(
            content=data, media_type=ct,
            headers={"Cache-Control": "public, max-age=86400"},
        )


# 接口用的字段名 → library 书目字典里的键名。
# 不一致的只有两处（date 在 OPF 里是 dc:date、在书目里叫 year；tags 同名但需要按列表比较）。
# 不显式映射的话，「比较前后是否变化」会永远判定为变化（拿 date 去比一个不存在的键）。
_FIELD_TO_BOOK_KEY = {"date": "year", "tags": "tags"}


def _meta_value(book: dict, field: str):
    key = _FIELD_TO_BOOK_KEY.get(field, field)
    if field == "tags":
        return list(book.get(key) or [])
    return book.get(key) or ""


@app.get("/api/books/{bid}/metadata")
def api_book_metadata(bid: str):
    """单书当前的生效元数据（详情页「编辑元数据」标签用）。

    返回的 ``fields`` 是分层后的生效值（override > online > opf）；
    ``meta`` 是逐字段明细（在线建议值 / 是否已被用户本地覆盖 / 是否被锁定），供编辑器渲染
    「已本地修改」「已锁定」徽标与「恢复为在线值」按钮。

    ``locked``（第 35 期）是同一份锁的**扁平清单**：``meta`` 只覆盖 10 个可编辑字段，
    而锁还能落在**封面**（独立键 ``cover``）上 —— 编辑器要用一条清单同时驱动
    「逐字段开关」与「封面开关」，不必为封面另开一次往返。

    ``custom``（第 35 期）是**该书适用**的自定义字段（含定义、类型与当前值），
    顺序即定义的 position 顺序 —— 详情页照着渲染即可，不需要再拉一次定义列表。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    return {
        "id": b["id"],
        "name": b["name"],
        "format": (b.get("format") or "").upper(),
        # 第 22 期起**所有格式都可编辑**（原先限 EPUB 的理由是「字段兜底原值来自 OPF」；
        # 改动只落服务端 DB 后这条前提不再成立：非 EPUB 没有 OPF 层，
        # 「恢复原值」就是撤销覆盖后回落在线的抓取值、没有在线值即为空 —— 是清晰语义）。
        "editable": True,
        # 生效值：用户覆盖 > 在线抓取 > OPF 原值
        "fields": metastore.effective(b),
        # 逐字段明细（含在线建议 / 是否已本地覆盖 / 是否已锁定）
        "meta": metastore.state(b),
        # 锁的扁平清单（含封面用的 `cover`），按字段表顺序
        "locked": metastore.locked_fields(b),
        # 自定义字段：只给**该书适用且未归档**的定义 + 这本书的当前值（按定义顺序）
        "custom": customfields.state(b),
    }


@app.post("/api/books/{bid}/metadata")
def api_set_book_metadata(bid: str, payload: dict = Body(...)):
    """编辑单本书的元数据：**只记服务端覆盖，不改写任何文件**（第 18 期口径）。

    三种取值语义（第 22 期起对所有格式一致）：
      · **非空字符串** → 记为用户覆盖，最高优先、再抓取也不冲掉；
      · **``null``** → **显式清空**（写 ``db.META_CLEAR`` 哨兵）：该字段变成「没有值」，
        能盖住在线的抓取值，之后的抓取也不会把它填回来（哨兵同样在保护名单里）；
      · **空串** → 撤销覆盖，回到「跟随在线 / OPF 原值」（对非 EPUB 即回落到在线值，没有则为空）。

    边界：
      · 只接受 ``fileops.METADATA_FIELDS`` 里的字段，其余**不写**（并在响应里回报）；
      · 只接受 ``db.clearable`` 的字段用 ``null`` 清空（当前 = 全部可编辑字段）；
      · 改完必须 ``library.invalidate()``，否则扫描缓存会让界面继续显示旧值；
      · **不动文件名**：改名只剩「按命名规则重出版副本」一条路，源文件名
        没有任何入口可改（第 28 期起）；
      · ``orig`` 记的是**编辑前的生效值**（供撤销覆盖后无在线值时回退）。

    ``custom``（第 35 期）是**另一套值**：``{字段键: 值}``，写进 ``book_custom_values``
    而不是 ``meta_override``。也只接受**该书适用**的定义（不适用 / 不存在的键如实回报在
    ``custom_ignored`` 里）。两套可以同一次请求一起提交 —— 详情页保存的就是一整张表单。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")

    raw = (payload or {}).get("fields") or {}
    cust_raw = (payload or {}).get("custom") or {}
    if not isinstance(raw, dict):
        raise HTTPException(400, "fields 必须是对象")
    if not isinstance(cust_raw, dict):
        raise HTTPException(400, "custom 必须是对象")
    unknown = sorted(k for k in raw if k not in fileops.METADATA_FIELDS)
    accepted = {k: v for k, v in raw.items() if k in fileops.METADATA_FIELDS}
    if not accepted and not cust_raw:
        raise HTTPException(
            400, "没有可改写的字段" + (f"（不支持：{', '.join(unknown)}）" if unknown else "")
        )

    before = {f: _meta_value(b, f) for f in accepted}
    # 第 17 期 T3：元数据写回**只存服务端**（meta_override），不再改写任何文件。
    # 与编辑前生效值（``before``）不同的才记为用户覆盖，并把 before 记成 orig
    # 供「撤销覆盖后既无在线值也无 OPF」时回退；与 before 一致则撤销覆盖。
    for f in accepted:
        if accepted[f] is None and db.clearable(f):
            # 前端「清空」= **显式无值**：写哨兵，盖住在线的抓取值（且抓取从此不再填它）
            new_val = db.META_CLEAR
        else:
            new_val = str(accepted[f] or "").strip()
        if new_val != str(before[f] or "").strip():
            db.set_override(bid, f, new_val, orig=before[f])
        else:
            db.set_override(bid, f, "")

    library.invalidate()
    # 自定义字段（第 35 期）：按定义的类型校验后写进 book_custom_values。
    # 值与 OPF 字段同批提交、却存两张表 —— 这里做完再统一回写状态，前端一次刷新。
    try:
        cust_res = customfields.write(b, cust_raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None

    fresh = library.by_id(bid) or {}
    changed = sorted(f for f in accepted if before.get(f) != _meta_value(fresh, f))
    detail = "编辑元数据：" + ("、".join(changed) if changed else "无实际变化")
    if cust_res["saved"]:
        detail += "；自定义字段：" + "、".join(cust_res["saved"])
    activity_log.log(activity_log.ACTION_RENAME, b["name"], activity_log.STATUS_OK,
                     detail=detail, source="api")
    return {
        "ok": True,
        # 不再写文件：written 恒为空（保留字段以兼容前端），实际生效见 changed
        "written": [],
        "changed": changed,
        "unknown": unknown,
        # 回写生效值 + 逐字段明细，前端直接据此刷新表单
        "fields": metastore.effective(fresh),
        "meta": metastore.state(fresh),
        # 自定义字段：写完后的全量状态（前端直接替换）+ 本次实际写入与忽略的键
        "custom": cust_res["custom"],
        "custom_saved": cust_res["saved"],
        "custom_ignored": cust_res["ignored"],
    }


@app.get("/api/books/{bid}/metadata/online")
def api_book_metadata_online(bid: str):
    """实时在线候选（编辑器「在线建议 / 重新获取」用）。**不写库**。"""
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    cand = metafetch.online_candidate(b, cfg=config.load_config())
    if not cand:
        return {"ok": False, "values": {}, "source": "", "score": 0.0,
                "message": "未找到在线候选或抓取未启用"}
    return {"ok": True, **cand}


@app.post("/api/books/{bid}/metadata/revert")
def api_revert_book_metadata(bid: str, payload: dict = Body(None)):
    """把指定字段恢复为**跟随在线值**：撤销用户覆盖（``meta_override``）与「显式清空」。

    第 17 期 T3：**不改写任何文件**。撤销覆盖后展示自动回落到在线值（``meta_online``，
    若曾抓取）或文件原值；非 EPUB 没有 OPF 那一层，没有在线值即为空。
    因此**无需外呼**、无需写盘。第 22 期起对**所有格式**可用（原先「仅 EPUB」的闸门已解除）。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    fields = (payload or {}).get("fields") or []
    if not isinstance(fields, list) or not fields:
        raise HTTPException(400, "fields 必须是非空数组")
    fields = [f for f in fields if f in fileops.METADATA_FIELDS]
    if not fields:
        raise HTTPException(400, "没有可恢复的字段")

    # 第 17 期 T3：只撤销覆盖（meta_override）。撤销后展示自动回落到在线值或文件原值。
    recovered = []
    for f in fields:
        if db.get_override_row(bid, f) is not None:
            recovered.append(f)
        db.set_override(bid, f, "")
    library.invalidate()
    fresh = library.by_id(bid) or {}
    return {
        "ok": True,
        "fields": metastore.effective(fresh),
        "meta": metastore.state(fresh),
        "recovered": sorted(recovered),
    }


@app.post("/api/books/{bid}/metadata/lock")
def api_lock_book_metadata(bid: str, payload: dict = Body(...)):
    """给单本书的**一个字段**上锁 / 解锁（第 35 期）。

    锁只挡**抓取**：上锁后在线抓取永不改写该字段（即使该字段策略写着「总是覆盖」），
    手动编辑照旧可改（用户当下的直接意志走在最顶层 override，不该被更早的标记拦住）。

    ``field`` 取 ``fileops.METADATA_FIELDS`` 的 10 个之一，或独立键 ``cover``（封面）。
    一次只处理一个字段：界面上就是一个开关，批量语义（全锁 / 全解）留给前端循环，
    服务端不发明「部分成功」的响应。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    field = str((payload or {}).get("field") or "").strip()
    if field != db.LOCK_COVER and field not in fileops.METADATA_FIELDS:
        raise HTTPException(400, f"不支持锁定的字段：{field or '（空）'}")
    locked = bool((payload or {}).get("locked", True))
    db.set_lock(bid, field, locked)
    # 刻意**不** library.invalidate()：锁只影响抓取的写入决策，不参与任何展示值
    # （生效值仍是 override > online > opf），无需让扫描缓存失效。
    return {
        "ok": True,
        "field": field,
        "locked": locked,
        "locked_fields": metastore.locked_fields(b),
    }


# ---------------- 自定义字段定义（第 35 期）----------------
# 定义是**全局**的（不属于某本书），值才是按书的 —— 值走 metadata 那两个端点。
# 六项操作与上游 custom-metadata 对齐：建字段 / 排序 / 改标签 / 切适用书库 / 归档 / 软删恢复。
# ⚠️ 路由注册顺序：`/reorder` 是字面量路径，必须排在 `/{cid}` 之前（否则被当成 cid 吃掉）。


def _custom_types() -> list:
    return [{"key": k, "label": v} for k, v in customfields.TYPES]


def _valid_library_ids(raw) -> list:
    """校验适用书库：只留**真实存在**的库 id。

    不存在的 id 一律丢掉而不是报错：库可能先删、定义后改，硬报错会让一条历史配置
    把整个定义锁死不能编辑。丢掉后语义退化成「对所有库生效」这件事不会发生 ——
    空列表就是「全部书库」，所以这里宁可返回空也要如实（调用方会把它当默认）。
    """
    if not isinstance(raw, list):
        return []
    known = {str(x["id"]) for x in db.list_libraries()}
    return [str(x) for x in raw if str(x) in known]


@app.get("/api/custom-fields")
def api_list_custom_fields(include_trashed: int = 0):
    """自定义字段定义列表（含归档项；`include_trashed=1` 时额外给 `trashed`）。"""
    out = {"items": db.list_custom_fields(), "types": _custom_types()}
    if include_trashed:
        out["trashed"] = db.trashed_custom_fields()
    return out


@app.post("/api/custom-fields/reorder")
def api_reorder_custom_fields(payload: dict = Body(...)):
    """按给定 id 次序重排（这就是上游的「排序」）。"""
    ids = (payload or {}).get("ids")
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "ids 必须是非空数组")
    return {"ok": True, "moved": db.reorder_custom_fields(ids),
            "items": db.list_custom_fields()}


@app.post("/api/custom-fields")
def api_create_custom_field(payload: dict = Body(...)):
    """新建字段定义。``key`` 缺省由显示名派生（稳定 slug，见 customfields.slug）。"""
    p = payload or {}
    label = str(p.get("label") or "").strip()
    if not label:
        raise HTTPException(400, "label 不能为空")
    type_ = str(p.get("type") or "text")
    if type_ not in customfields.TYPE_KEYS:
        raise HTTPException(400, f"不支持的类型：{type_}（可选 {', '.join(customfields.TYPE_KEYS)}）")
    try:
        default_value = customfields.normalize(type_, p.get("default_value"))
    except ValueError as e:
        raise HTTPException(400, f"默认值{e}") from None
    key = str(p.get("key") or "").strip() or customfields.slug(label)
    try:
        item = db.create_custom_field(
            key=key, label=label, type=type_,
            library_ids=_valid_library_ids(p.get("library_ids")),
            default_value=default_value,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True, "item": item, "items": db.list_custom_fields()}


@app.patch("/api/custom-fields/{cid}")
def api_update_custom_field(cid: int, payload: dict = Body(...)):
    """改定义：label / 类型 / 适用书库 / 默认值 / 归档 / 位置。

    **不改 key**（值表按 key 引用，改 key 等于换一个字段）—— 见 customfields 的模块说明。
    """
    row = db.get_custom_field(cid)
    if not row or row["deleted_at"]:
        raise HTTPException(404, "字段不存在或已在垃圾桶中")
    p = payload or {}
    patch: dict = {}
    if "label" in p:
        label = str(p.get("label") or "").strip()
        if not label:
            raise HTTPException(400, "label 不能为空")
        patch["label"] = label
    if "type" in p:
        t = str(p.get("type") or "text")
        if t not in customfields.TYPE_KEYS:
            raise HTTPException(400, f"不支持的类型：{t}")
        patch["type"] = t
    if "library_ids" in p:
        patch["library_ids"] = _valid_library_ids(p.get("library_ids"))
    if "archived" in p:
        patch["archived"] = bool(p.get("archived"))
    if "position" in p:
        try:
            patch["position"] = int(p.get("position"))
        except (TypeError, ValueError):
            raise HTTPException(400, "position 必须是整数") from None
    if "default_value" in p:
        # 按**改后的**类型校验（同一次请求里既改类型又改默认值时要按新类型判）
        try:
            patch["default_value"] = customfields.normalize(
                patch.get("type", row["type"]), p.get("default_value"))
        except ValueError as e:
            raise HTTPException(400, f"默认值{e}") from None
    return {"ok": True, "item": db.update_custom_field(cid, **patch),
            "items": db.list_custom_fields()}


@app.delete("/api/custom-fields/{cid}")
def api_delete_custom_field(cid: int):
    """**移入垃圾桶**（软删除）。值保留 —— 恢复之后值还在。彻底删除走 `/purge`。"""
    n = db.delete_custom_field(cid)
    return {"ok": True, "trashed": n > 0, "items": db.list_custom_fields(),
            "trashed_items": db.trashed_custom_fields()}


@app.post("/api/custom-fields/{cid}/restore")
def api_restore_custom_field(cid: int):
    n = db.restore_custom_field(cid)
    if not n:
        raise HTTPException(404, "字段不存在或不在垃圾桶中")
    return {"ok": True, "items": db.list_custom_fields()}


@app.delete("/api/custom-fields/{cid}/purge")
def api_purge_custom_field(cid: int):
    """彻底删除（不可恢复），**并连带清掉所有书上的值**（定义没了，值就再没有归属）。

    只允许删垃圾桶里的条目 —— 与批注 / 书签同一条纪律。
    """
    n = db.purge_custom_field(cid)
    if not n:
        raise HTTPException(400, "只能彻底删除垃圾桶中的字段（该条目不存在或仍为活跃状态）")
    return {"ok": True, "items": db.list_custom_fields(),
            "trashed_items": db.trashed_custom_fields()}


@app.get("/api/books/{bid}/cover")
def api_book_cover(bid: str):
    """书籍封面。

    分支（按格式）：
      · **EPUB**：OPF 指定的内嵌图（`library.cover_path`）；
      · **漫画（CBZ / CBR）**：归档第一页 —— 走 `comics.cover_bytes`，zip/rar 双后端统一，
        避免这里再自己解一次 zip（那样 CBR 会「列得出封面名却读不出来」）；
      · **有声书**：目录内的 `cover.jpg` / `folder.jpg` 之类；单文件音频无封面；
      · 其余非 EPUB（mobi/pdf/txt）不解析封面，直接 404 —— 与 has_cover 的口径一致。

    为什么单独开接口：前端只需要一个不含内部路径的稳定 URL，拿不到就 404、回退渐变占位。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    fmt = (b.get("format") or "").upper()
    path = library.root_of(b) / b["name"]

    if fmt in ("CBZ", "CBR"):
        data, media = comics.cover_bytes(path)
        if data is None:
            raise HTTPException(404, "该漫画没有图片")
        return Response(content=data, media_type=media,
                        headers={"Cache-Control": "public, max-age=86400"})

    if fmt == "AUDIO":
        name = audio.cover_in_dir(path) if path.is_dir() else ""
        if not name:
            raise HTTPException(404, "该有声书没有封面")
        return FileResponse(path / name,
                            media_type=mimetypes.guess_type(name)[0] or "image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})

    if fmt != "EPUB":
        raise HTTPException(404, "该格式没有内嵌封面")
    # 第 17 期 T3：优先取服务端缓存封面（在线抓取写入 meta_cover），
    # 无则回退 EPUB 内嵌图（兼容原文件本来就带封面、从未抓过在线封面的情况）。
    server_cover = db.get_cover(bid)
    if server_cover:
        data, sct = server_cover
        return Response(content=data, media_type=sct or "image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    cover = library.cover_path(path)
    if not cover:
        raise HTTPException(404, "该书没有封面")
    try:
        with zipfile.ZipFile(path) as z:
            if cover not in z.namelist():
                raise HTTPException(404, "封面资源不存在")
            data = z.read(cover)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"读取封面失败：{e}")
    ct = mimetypes.guess_type(cover)[0] or "image/jpeg"
    return Response(
        content=data, media_type=ct,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/books/{bid}/file")
def api_book_file(bid: str):
    """原始书籍文件流（PDF 等在线阅读用）。

    · `FileResponse` 自带 Range 支持 → 阅读器可以分块加载（206），大 PDF 不必整份传输；
    · 走 `/api/` 前缀 = 需要 Bearer；前端 pdf.js 用 `httpHeaders` 携带令牌，
      因此**不必**像封面那样开 `?token=` 口子（鉴权面不扩大）。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    path = library.root_of(b) / b["name"]
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=3600"})


# ---------------- 漫画（CBZ / CBR）----------------
# 两种容器走同一套 comics 抽象（zipfile / rarfile 由魔数嗅探选择），上层零分支。

@app.get("/api/books/{bid}/comic")
def api_comic_pages(bid: str):
    """漫画页清单（CBZ / CBR）。前端按 index 逐页取图，不一次拉全部。"""
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    path = library.root_of(b) / b["name"]
    if not comics.is_comic(path):
        raise HTTPException(400, "仅漫画归档（CBZ / CBR）支持漫画阅读")
    if comics.is_cbr(path) and not comics.rar_available():
        raise HTTPException(503, "服务器缺少 RAR 解压能力（需 bsdtar 或 unrar）")
    return comics.pages(path)


@app.get("/api/books/{bid}/comic/{index}")
def api_comic_page(bid: str, index: int):
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    path = library.root_of(b) / b["name"]
    if not comics.is_comic(path):
        raise HTTPException(400, "仅漫画归档（CBZ / CBR）支持漫画阅读")
    if comics.is_cbr(path) and not comics.rar_available():
        raise HTTPException(503, "服务器缺少 RAR 解压能力（需 bsdtar 或 unrar）")
    data, media = comics.page_bytes(path, index)
    if data is None:
        raise HTTPException(404, "页不存在")
    return Response(content=data, media_type=media,
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------------- 有声书（单文件 / 多轨目录）----------------
# 一本书 = 一个音频文件 或 一个含音频的目录（见 core/audio.py）。

_AUDIO_MIME = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".aac": "audio/aac",
    ".flac": "audio/flac", ".opus": "audio/opus", ".ogg": "audio/ogg", ".wav": "audio/wav",
}


@app.get("/api/books/{bid}/audio")
def api_audio_tracks(bid: str):
    """有声书轨清单（单文件 1 轨 / 目录 n 轨，自然序）。"""
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    if (b.get("format") or "").upper() != "AUDIO":
        raise HTTPException(400, "该书不是有声书")
    return audio.tracks(library.root_of(b) / b["name"])


@app.get("/api/books/{bid}/audio/{index}")
def api_audio_track(bid: str, index: int):
    """单轨音频流。

    · 用 `FileResponse` → 自带 **Range（206）**，播放器拖拽跳转必需，且不必整份进内存；
    · 与 PDF 不同：`<audio src>` 是浏览器原生请求、带不了 Bearer，
      所以该路径已在 `_MEDIA_TOKEN_PATHS` 里允许 `?token=`。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    if (b.get("format") or "").upper() != "AUDIO":
        raise HTTPException(400, "该书不是有声书")
    track = audio.track_path(library.root_of(b) / b["name"], index)
    if not track or not track.is_file():
        raise HTTPException(404, "轨道不存在")
    media = _AUDIO_MIME.get(track.suffix.lower()) \
        or mimetypes.guess_type(track.name)[0] or "application/octet-stream"
    return FileResponse(track, media_type=media,
                        headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/books/{bid}/chapter/{index}")
def api_book_chapter(bid: str, index: int):
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    path = library.root_of(b) / b["name"]
    suffix = path.suffix.lower()
    if suffix == ".txt":
        # 第 55 期：TXT 优先读**派生 EPUB**（与详情页下发的目录同一形态，索引空间一致）；
        # 转不动（超大 / 编码坏 / 构建失败）回落原生分章 —— 两条路线 index 语义各自内聚，
        # 由缓存里的源指纹锁定形态，绝不中途混用。
        ep = txtcache.derived_epub(b, path=path)
        if ep is not None:
            try:
                return library.chapter_html(ep, index, bid)
            except IndexError:
                raise HTTPException(404, "章节不存在")
        try:
            return txtcache.native_chapter_html(b, index, path=path)
        except IndexError:
            raise HTTPException(404, "章节不存在")
    if suffix != ".epub":
        raise HTTPException(400, "仅 EPUB / TXT 支持在线阅读")
    try:
        return library.chapter_html(path, index, bid)
    except IndexError:
        raise HTTPException(404, "章节不存在")


@app.get("/api/books/{bid}/progress")
def api_get_progress(bid: str):
    p = db.get_progress(bid)
    if not p:
        return {"locator": 0, "percent": 0, "cfi": ""}
    out = {"locator": p["locator"], "percent": p["percent"], "cfi": p.get("cfi") or "",
           # 第 56 期：多设备进度提示的**新旧比较基准**（前端把它当作「本机已知的最新
           # 写入时间」，只有比它更新的写入才可能是别的设备）。
           "updated_at": p["updated_at"]}
    if out["cfi"]:
        # 附带把 CFI 反解成章内字符偏移（与保存侧同一坐标系）：前端拿到 offset
        # 直接换滚动位置，不需要在 JS 里再实现一遍 CFI 解析。
        b = library.by_id(bid)
        if b and (b.get("format") or "").upper() == "EPUB":
            pos = epub_cfi.position_from_cfi(library.root_of(b) / b["name"], out["cfi"])
            if pos:
                out["offset"] = int(pos[1])
    return out


@app.put("/api/books/{bid}/progress")
def api_set_progress(bid: str, payload: dict = Body(...)):
    try:
        locator = int(payload.get("locator", 0))
        percent = float(payload.get("percent", 0.0))
    except (TypeError, ValueError):
        raise HTTPException(400, "locator/percent 必须为数字")
    # 第 54 期：EPUB 可带「章内字符偏移」（前端 textContent 坐标）⇒ 服务端生成 CFI
    # 落库 —— CFI 格式真值源在 core/epub_cfi.py，前端不自己拼。生成不了（坏书 /
    # 非 EPUB / spine 越界）就存空串：恢复侧回落「章 + 全书百分比」，
    # 保存进度本身绝不能因 CFI 失败。
    cfi = ""
    offset = payload.get("offset")
    if offset is not None and locator >= 0:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise HTTPException(400, "offset 必须为整数")
        if offset < 0:
            raise HTTPException(400, "offset 必须 ≥ 0")
        b = library.by_id(bid)
        if b and (b.get("format") or "").upper() == "EPUB":
            cfi = epub_cfi.cfi_for_position(library.root_of(b) / b["name"], locator, offset)
    at = db.set_progress(bid, locator, percent, cfi)
    # 回带写入时间戳（第 56 期）：前端据此更新「本机上次写入」，避免把自己的保存
    # 当成本机之外的更新而弹提示。
    return {"ok": True, "updated_at": at}


# ---------------- 阅读状态 / 书评 / 相似书 ----------------

@app.get("/api/books/{bid}/status")
def api_get_status(bid: str):
    return db.get_status(bid)


@app.put("/api/books/{bid}/status")
def api_set_status(bid: str, request: Request, payload: dict = Body(...)):
    """设置阅读状态。可选 `started_at` / `finished_at`（epoch 秒，0 = 清除后按规则重记）。"""
    try:
        r = db.set_status(
            bid,
            str(payload.get("status") or ""),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
        )
        _sync_auto_push(bid, request)
        return r
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/books/{bid}/reset-reading-state")
def api_reset_reading_state(bid: str):
    """**从头开始**：清掉这本书的阅读会话 / 进度 / 状态（第 34 期）。

    只清「读出来的痕迹」，批注 / 书签 / 评分 / 收藏 / 元数据一律不动 ——
    它们是关于这本书的内容，不是「读过」的记录（见 ``db.reset_reading_state``）。
    ⚠️ 只删 DB 行，**不碰磁盘上的任何文件**；不可撤销，故写一条审计日志留痕。
    """
    book = library.by_id(bid)
    if not book:
        raise HTTPException(404, "找不到这本书")
    removed = db.reset_reading_state(bid)
    total = sum(removed.values())
    activity_log.log(
        activity_log.ACTION_RESET, book.get("name") or bid, activity_log.STATUS_OK,
        detail=f"重置阅读状态：会话 {removed['sessions']} 条 / 进度 {removed['progress']} 条 / "
               f"状态 {removed['status']} 条 / 尝试 {removed['attempts']} 条"
               f"（共 {total} 行，仅服务端记录，未动文件）",
        source="api",
    )
    return {"ok": True, "removed": removed, "total": total}


# ---- 阅读尝试 / 重读（第 43 期）----
# 一轮 = 「开始读 → 读完」；轮次由 db.set_status 自动维护，也可由用户显式重开或从历史补录。

@app.get("/api/books/{bid}/reading-attempts")
def api_list_reading_attempts(bid: str):
    """这本书的阅读尝试（轮次）清单 + 当前进行中的那一轮。"""
    items = db.list_attempts(bid)
    current = next((a for a in items if not a.get("finished_at")), None)
    return {"items": items, "total": len(items), "current": current}


@app.post("/api/books/{bid}/reading-attempts")
def api_start_reading_attempt(bid: str, payload: dict = Body(default=None)):
    """开新一轮阅读（「再来一遍」）。**幂等**：已有进行中的那一轮就原样返回，不重复开。"""
    if not library.by_id(bid):
        raise HTTPException(404, "找不到这本书")
    started_at = (payload or {}).get("started_at")
    return {"ok": True, "attempt": db.start_attempt(bid, started_at=started_at)}


@app.post("/api/books/{bid}/reading-attempts/finish")
def api_finish_reading_attempt(bid: str, payload: dict = Body(default=None)):
    """收尾进行中的那一轮。没有进行中的轮次返回 404（**不凭空造行**）。"""
    if not library.by_id(bid):
        raise HTTPException(404, "找不到这本书")
    finished_at = (payload or {}).get("finished_at")
    row = db.finish_attempt(bid, finished_at=finished_at)
    if row is None:
        raise HTTPException(404, "没有进行中的阅读尝试")
    return {"ok": True, "attempt": row}


@app.post("/api/reading-attempts/backfill")
def api_backfill_reading_attempts():
    """一次性历史补录：给既有 ``reading_status`` 但**一轮都没有**的书各补一轮（第 43 期）。"""
    return {"ok": True, **db.backfill_attempts()}


@app.get("/api/books/{bid}/review")
def api_get_review(bid: str):
    return db.get_review(bid)


@app.put("/api/books/{bid}/review")
def api_set_review(bid: str, request: Request, payload: dict = Body(...)):
    """评分与书评一起保存。stars 传 0 = 清除评分；review 传空串 = 清除书评。"""
    try:
        stars = int(payload.get("stars", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "stars 必须是 0–5 的整数")
    if not 0 <= stars <= 5:
        raise HTTPException(400, "stars 必须是 0–5 的整数")
    if stars > 0:
        db.set_rating(bid, stars)
    else:
        db.clear_rating(bid)
    db.set_review(bid, payload.get("review") or "")
    _sync_auto_push(bid, request)
    return {"ok": True, **db.get_review(bid)}


# ---------------- 语义向量（第 54 期）----------------
# book_embeddings 的生命周期：写只发生在 recompute（手动端点 / 后台自愈），
# 读只发生在 /similar（embed.load_vectors 按 tag 过滤 + 解码）。
_EMBED_REFRESHING = threading.Event()
_EMBED_LAST_RUN = 0.0
#: 自愈触发的最小间隔（秒）。向量是缓存，缺几本不影响可用性（逐对回落词袋），
#: 不值得为它频繁做 SVD；手动 recompute 端点不受此限。
_EMBED_MIN_INTERVAL = 600.0


def _schedule_embed_refresh() -> None:
    """后台线程跑一次全量重算（fire-and-forget）：新书入库 / 换模型后的自愈路径。

    在跑或距上次自愈不足间隔 ⇒ 跳过 —— 调用方（/similar）是热路径，
    这里绝不允许排队多个 SVD 或阻塞请求。
    """
    global _EMBED_LAST_RUN
    if _EMBED_REFRESHING.is_set():
        return
    if time.time() - _EMBED_LAST_RUN < _EMBED_MIN_INTERVAL:
        return
    _EMBED_REFRESHING.set()
    _EMBED_LAST_RUN = time.time()

    def _run():
        try:
            embed.refresh()
        except Exception:  # noqa: BLE001 —— 自愈是旁路，失败只留日志
            logging.getLogger("novelforge").exception("语义向量后台重算失败")
        finally:
            _EMBED_REFRESHING.clear()

    threading.Thread(target=_run, name="embed-refresh", daemon=True).start()


def wait_embed_refresh(timeout: float = 5.0) -> bool:
    """等后台语义向量重算结束：结束 / 没在跑 ⇒ True，超时 ⇒ False。

    供 ``tests/conftest.py::_quiesce_background`` 用 —— 与 watcher / scrape 同一条
    「测试不养旁路线程」的纪律：夹具必须在 ``db.close()`` 之前等它退出，
    否则线程会攥着旧连接去查下一个用例的库。
    """
    return not _EMBED_REFRESHING.is_set() or _EMBED_REFRESHING.wait(timeout)


@app.post("/api/embeddings/recompute")
async def api_embeddings_recompute():
    """全量重算语义向量并落 ``book_embeddings`` 表。

    手动触发口（新书 / 元数据大改 / 换模型后）；``/similar`` 也有自愈式补算
    （节流见 :func:`_schedule_embed_refresh`）。重算期间旧向量继续可用 ——
    ``set_embeddings`` 一次事务覆写，不存在「删了旧的、没写新的」空档。
    """
    return {"ok": True, **(await asyncio.to_thread(embed.refresh))}


@app.get("/api/books/{bid}/similar")
def api_similar(bid: str, limit: int = Query(6, ge=1, le=25)):
    """相似书：五路加权打分（第 35 期），纯派生、不落库。

    打分与「该不该出现」的门槛都在 ``core/recommend.py``：至少要有一条实质重合
    （同作者 / 共同题材 / 同系列），否则不返回 —— 毫无关系的推荐只会消耗界面的信任。
    第 54 期起余弦一路优先取语义向量（``book_embeddings``，当前模型 tag），
    缺向量的一对回落词袋，接口出参结构不变 —— 前端零改动。

    ``limit`` 默认 6、**上限 25**（第 35 期对齐上游）：详情页先显示 6 条，
    点「查看全部」再按 25 要一次。
    """
    books = library.books()
    vectors = embed.load_vectors()
    items = recommend.similar_books(bid, books, limit, vectors=vectors)
    # 自愈：有书没向量（新书 / 语料首次达 MIN_BOOKS / 换了模型）⇒ 后台补一轮
    if len(vectors) < len(books):
        _schedule_embed_refresh()
    return {"items": items}


# ---------------- Reading Log（阅读记录）----------------
# 数据早就在（reading_sessions 表，阅读器每次退出都会写一行），
# 缺的只是按天 / 按书的展示聚合。单用户 NAS 场景会话量很小，
# Python 侧分组即可，不需要 SQL 窗口函数。

@app.get("/api/reading-log")
def api_reading_log(days: int = Query(60, ge=7, le=365)):
    """阅读记录：按天明细（含每天读了哪些书）+ 按书聚合 + 最近会话。"""
    import time as _time

    bs = {b["id"]: b for b in library.books()}
    now = _time.time()

    daily: dict = {}
    for s in db.recent_sessions(limit=20000):          # 上限只防极端情况
        if now - s["ended_at"] > days * 86400:
            continue
        d = _time.strftime("%Y-%m-%d", _time.localtime(s["ended_at"]))
        row = daily.setdefault(d, {"date": d, "seconds": 0.0, "sessions": 0, "books": {}})
        row["seconds"] += float(s["seconds"])
        row["sessions"] += 1
        b = bs.get(s["book_id"])
        entry = row["books"].setdefault(s["book_id"], {
            "id": s["book_id"],
            "title": (b or {}).get("title") or s["book_id"],
            "seconds": 0.0,
        })
        entry["seconds"] += float(s["seconds"])

    items = sorted(daily.values(), key=lambda r: r["date"], reverse=True)
    for r in items:
        r["books"] = sorted(r["books"].values(), key=lambda x: -x["seconds"])

    by_book = []
    for bid, v in db.session_by_book().items():
        b = bs.get(bid)
        # 页数（非 EPUB 恒 0）与来源标签一并带上，供前端算「阅读速度」并标注口径；
        # 无可靠页数（pages_source 为空）时前端不显示该项，不造假。
        by_book.append({
            "id": bid,
            "title": (b or {}).get("title") or bid,
            "author": (b or {}).get("author") or "",
            "pages": (b or {}).get("pages") or 0,
            "pages_source": (b or {}).get("pages_source") or "",
            **v,
        })
    by_book.sort(key=lambda x: -x["seconds"])

    recent = []
    for s in db.recent_sessions(limit=50):
        b = bs.get(s["book_id"])
        recent.append({
            **s,
            "title": (b or {}).get("title") or s["book_id"],
            "date": _time.strftime("%Y-%m-%d %H:%M", _time.localtime(s["ended_at"])),
        })

    return {"days": days, "items": items, "by_book": by_book, "recent": recent}


@app.post("/api/reading-log")
def api_add_session(payload: dict = Body(...)):
    """手工补录一次阅读会话（对应上游 ``Add a session by hand``）。

    场景：读了纸质书、或在没开阅读器的地方看了一会儿 —— 这些不会产生
    reading_sessions 行，需要一个显式入口补上，否则统计与 Reading Log 都少算。
    复用 db.add_session，但**校验在接口层做**：db 层信任阅读器的上报，不设防。
    """
    import time as _time

    bid = str(payload.get("book_id") or "")
    if not any(b["id"] == bid for b in library.books()):
        raise HTTPException(404, "书不存在或已被移除")

    try:
        minutes = int(payload.get("minutes", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "时长必须是整数分钟")
    if not 1 <= minutes <= 1440:
        raise HTTPException(400, "时长须在 1–1440 分钟之间")

    date_s = str(payload.get("date") or "").strip()
    try:
        day = _time.strptime(date_s, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "日期格式须为 YYYY-MM-DD")
    start_s = str(payload.get("start") or "00:00").strip()
    try:
        hm = _time.strptime(start_s, "%H:%M")
    except ValueError:
        raise HTTPException(400, "开始时间格式须为 HH:MM")

    import datetime as _dt
    # naive datetime 的 .timestamp() 按**本地时区**解释 —— 正是「那天 08:30」想要的语义
    started = _dt.datetime.strptime(
        f"{date_s} {start_s}", "%Y-%m-%d %H:%M"
    ).timestamp()
    seconds = minutes * 60
    ended = started + seconds
    now = _time.time()
    if ended > now + 60:                      # 1 分钟宽限：时钟轻微偏差不算错
        raise HTTPException(400, "不能补录未来的会话")

    db.add_session(bid, seconds, started_at=started, ended_at=ended)
    return {
        "ok": True,
        "session": {
            "book_id": bid,
            "seconds": seconds,
            "started_at": started,
            "ended_at": ended,
            "date": _time.strftime("%Y-%m-%d %H:%M", _time.localtime(ended)),
        },
    }


@app.get("/api/books/{bid}/annotations")
def api_list_annotations(bid: str):
    return {"items": db.list_annotations(bid)}


@app.post("/api/books/{bid}/annotations")
def api_add_annotation(bid: str, request: Request, payload: dict = Body(...)):
    quote = str(payload.get("quote", "") or "").strip()
    if not quote:
        raise HTTPException(400, "quote 不能为空")
    # origin 固定来源枚举（web / koreader / kobo）。当前只有 Web 阅读器会写入，
    # 允许显式传入是为将来批注导入留出契约，但**不校验也不编造**：不传就是 web。
    origin = str(payload.get("origin", "web") or "web").strip() or "web"
    # 第 44 期：样式类型（高亮/下划线/删除线/纯笔记），未知/空回落 'highlight'。
    style = str(payload.get("style", "highlight") or "highlight").strip() or "highlight"
    rid = db.add_annotation(
        bid,
        int(payload.get("chapter", 0) or 0),
        quote,
        str(payload.get("color", "yellow") or "yellow"),
        str(payload.get("note", "") or ""),
        origin,
        style,
    )
    _sync_auto_push(bid, request)
    return {"id": rid, "ok": True}


@app.delete("/api/books/{bid}/annotations/{aid}")
def api_delete_annotation(bid: str, aid: int):
    """**移入垃圾桶**（软删除），不是真删；彻底删除走 `/purge`。"""
    n = db.delete_annotation(bid, aid)
    return {"ok": True, "trashed": n > 0}


@app.post("/api/books/{bid}/annotations/{aid}/restore")
def api_restore_annotation(bid: str, aid: int):
    n = db.restore_annotation(bid, aid)
    if not n:
        raise HTTPException(404, "批注不存在或不在垃圾桶中")
    return {"ok": True}


@app.delete("/api/books/{bid}/annotations/{aid}/purge")
def api_purge_annotation(bid: str, aid: int):
    """彻底删除（不可恢复）。**只允许删垃圾桶里的条目** —— 活跃条目须先删除再 purge，
    避免误点一次就永久丢失。"""
    n = db.purge_annotation(bid, aid)
    if not n:
        raise HTTPException(400, "只能彻底删除垃圾桶中的批注（该条目不存在或仍为活跃状态）")
    return {"ok": True}


# ---------------- 书签（第 34 期）----------------
# 三条与批注不同的口径，都在 db 层实现，这里只做参数搬运与错误码：
#   · **位置去重 + 墓碑复活**：同位置反复加书签恒为同一条；删过再加是「复活那一行」
#     （`revived=True`，created_at 得以保留）；
#   · **并发合并**：客户端回传 `updated_at`（它看到的那一版）⇒ 库里更新则服务端胜，
#     `applied=False` 并把服务端现值回给客户端；
#   · 删除仍是**软删除**（移入垃圾桶），真删走 `/purge`。

@app.get("/api/books/{bid}/bookmarks")
def api_list_bookmarks(bid: str, include_trashed: int = 0):
    """某本书的书签。默认只给活跃条目；``include_trashed=1`` 时额外给 ``trashed``。"""
    active = db.list_bookmarks(bid)
    out = {"items": active, "total": len(active)}
    if include_trashed:
        out["trashed"] = db.trashed_bookmarks(bid)
    return out


@app.post("/api/books/{bid}/bookmarks")
def api_add_bookmark(bid: str, payload: dict = Body(...)):
    """加书签（或复活同位置的墓碑 / 合并并发冲突）。

    ``anchor`` 是**位置锚**（前端按「章序号 + 章内归一化位置」生成），它是去重键：
    传同一个 anchor 绝不会产生第二条书签。
    """
    try:
        percent = float(payload.get("percent", 0.0) or 0.0)
        chapter = int(payload.get("chapter", 0) or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "chapter/percent 必须为数字")
    try:
        return db.save_bookmark(
            bid,
            str(payload.get("anchor", "") or ""),
            percent=percent,
            chapter=chapter,
            label=str(payload.get("label", "") or ""),
            base_updated_at=float(payload.get("updated_at", 0.0) or 0.0),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/books/{bid}/bookmarks/{bmid}")
def api_update_bookmark(bid: str, bmid: int, payload: dict = Body(...)):
    """改备注 / 位置（只对活跃书签）。并发口径同 POST。"""
    try:
        res = db.update_bookmark(
            bid, bmid,
            label=payload.get("label"),
            percent=payload.get("percent"),
            chapter=payload.get("chapter"),
            base_updated_at=float(payload.get("updated_at", 0.0) or 0.0),
        )
    except (TypeError, ValueError):
        raise HTTPException(400, "chapter/percent 必须为数字")
    if not res.get("found"):
        raise HTTPException(404, "书签不存在或已在垃圾桶中")
    return res


@app.delete("/api/books/{bid}/bookmarks/{bmid}")
def api_delete_bookmark(bid: str, bmid: int):
    """**移入垃圾桶**（软删除），不是真删；彻底删除走 `/purge`。"""
    n = db.delete_bookmark(bid, bmid)
    return {"ok": True, "trashed": n > 0}


@app.post("/api/books/{bid}/bookmarks/{bmid}/restore")
def api_restore_bookmark(bid: str, bmid: int):
    n = db.restore_bookmark(bid, bmid)
    if not n:
        raise HTTPException(404, "书签不存在或不在垃圾桶中")
    return {"ok": True}


@app.delete("/api/books/{bid}/bookmarks/{bmid}/purge")
def api_purge_bookmark(bid: str, bmid: int):
    """彻底删除（不可恢复）。**只允许删垃圾桶里的条目** —— 与批注同一条纪律。"""
    n = db.purge_bookmark(bid, bmid)
    if not n:
        raise HTTPException(400, "只能彻底删除垃圾桶中的书签（该条目不存在或仍为活跃状态）")
    return {"ok": True}


# ---------------- 系列（浏览 / 系列详情）----------------
# 系列名来自 EPUB 元数据（见 library.series_list），**没有独立实体表**；
# 系列级元数据（简介 / 出版社 / 首发年 / 题材）另存 `series_meta` 表（第 12 期 C3）。

@app.get("/api/series")
def api_series():
    items = library.series_list()
    # 一次取全所有系列的元数据行：逐系列查库 = N 次查询，列表页不能这么干
    rows = db.all_series_meta()
    out = []
    for s in items:
        eff = series_meta.effective_light(s["name"], rows.get(s["name"]) or {})
        out.append({
            "name": s["name"],
            "count": s["count"],
            "authors": sorted({b["author"] for b in s["books"] if b.get("author")})[:3],
            "covers": [
                {"id": b["id"], "title": b["title"], "c1": b["c1"], "c2": b["c2"],
                 "has_cover": b.get("has_cover", False)}
                for b in s["books"][:4]
            ],
            # 系列简介（无值则空串，前端**有值才渲染**，不占位）
            "description": eff["description"],
            "source": eff["source"],
            "score": eff["score"],
        })
    return {"items": out, "total": len(out)}


@app.get("/api/series/{name}")
def api_series_detail(name: str):
    """系列详情。**按媒体分组**（第 10 期 C2）。

    同一系列常常横跨多种媒体（先有小说 EPUB，后来又收了漫画版 / 有声版），
    混在一个网格里会让「第 1 册」失去意义 —— 序号是**每种媒体各自**的阅读顺序。

    组内顺序仍是扫描顺序：序号排序在前端做（``SeriesDetailView``，
    因为倒序切换是纯展示逻辑，不必来回请求）。

    第 12 期补 ``meta`` / ``meta_state``：系列级元数据的生效值与逐字段明细，
    供系列页展示简介与编辑器渲染「已本地修改 / 恢复在线」。
    """
    bs = library.series_books(name)
    if not bs:
        raise HTTPException(404, "系列不存在")
    buckets: dict = {}
    order: list = []
    for b in bs:
        t = migrate.target_type_of(b) or "other"
        if t not in buckets:
            buckets[t] = []
            order.append(t)
        buckets[t].append(b)
    return {
        "name": name, "count": len(bs), "books": bs,
        "groups": [
            {"media": t, "label": migrate.TYPE_LABELS.get(t, "其它"),
             "count": len(buckets[t]), "books": buckets[t]}
            for t in order
        ],
        # 单系列查询：这里做**完整**分层（含成员书聚合），成本可接受
        "meta": series_meta.effective(name),
        "meta_state": series_meta.state(name),
        # 第 43 期：缺册（按 series_index 数字集合求 [1..max] 的补集；无序号/非数字另计）
        "gaps": library.series_gaps(name),
    }


# ---- 系列级元数据（第 12 期 C3 SYNOPSIS）----
# ⚠️ 只存本项目的 SQLite，**绝不写回 EPUB**：OPF 没有「系列简介」这个字段
#    （唯一近似 dc:description 属于**单册**，写进去就是覆盖某册自己的简介）。
#    生效点是三处注入：本组接口 + komga_api.series_dto + OPDS 系列入口。

@app.get("/api/series/{name}/meta")
def api_series_meta(name: str):
    """系列元数据：生效值 + 逐字段明细（编辑器渲染「已本地修改 / 恢复在线」用）。"""
    if not library.series_books(name):
        raise HTTPException(404, "系列不存在")
    return {
        "ok": True,
        "meta": series_meta.effective(name),
        "state": series_meta.state(name),
        "fields": list(series_meta.FIELDS),
        "labels": series_meta.LABELS,
    }


@app.post("/api/series/{name}/meta")
def api_set_series_meta(name: str, payload: dict = Body(...)):
    """设置 / 清除系列的本地覆盖（**空串 = 撤销该字段的覆盖**）。只写本项目 DB。

    与作者侧同一语义：用户改过的不会被再次抓取冲掉。
    """
    if not library.series_books(name):
        raise HTTPException(404, "系列不存在")
    p = payload or {}
    unknown = [k for k in p if k not in series_meta.FIELDS]
    if unknown:
        raise HTTPException(400, f"不支持的字段：{'、'.join(sorted(unknown))}")
    if not p:
        raise HTTPException(400, "没有可更新的字段")
    try:
        meta = series_meta.set_local(name, **p)
    except ValueError as e:
        raise HTTPException(400, str(e))
    activity_log.log(activity_log.ACTION_METADATA, name, activity_log.STATUS_OK,
                     detail="编辑系列元数据：" + "、".join(sorted(p)), source="api")
    return {"ok": True, "meta": meta, "state": series_meta.state(name)}


@app.post("/api/series/{name}/fetch")
def api_fetch_series_meta(name: str):
    """抓取单个系列的在线元数据。**失败不抛** —— 抓不到就如实回「未找到」。"""
    if not library.series_books(name):
        raise HTTPException(404, "系列不存在")
    res = series_meta.fetch_one(name)
    return {"ok": bool(res.get("ok")), "result": res, **series_meta.effective(name)}


@app.post("/api/series/fetch-all")
def api_fetch_all_series_meta(payload: dict = Body(None)):
    """批量抓取系列元数据：一次只处理一批，回 ``remaining`` 让前端循环显示进度。

    全库一次跑完必然超时（见 ``/api/metadata/plan`` 的既有教训），故分批；
    单个系列失败不中断其余，统计在 ``ok`` / ``failed`` 里。
    """
    p = payload or {}
    names = p.get("names")
    if names is not None and not isinstance(names, list):
        raise HTTPException(400, "names 必须是数组")
    limit = p.get("limit")
    try:
        cap = int(limit) if limit else series_meta.FETCH_BATCH
    except (TypeError, ValueError):
        raise HTTPException(400, "limit 必须是整数")
    return series_meta.fetch_all(names=names, limit=cap)


@app.get("/api/series/{name}/renumber/preview")
def api_series_renumber_preview(name: str):
    """重排册号**预览**（只算不改）。序号的落点是**服务端**，不动文件名、不改文件内容。"""
    try:
        return series_meta.renumber_plan(name)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/series/{name}/renumber/apply")
def api_series_renumber_apply(name: str, payload: dict = Body(...)):
    """执行重排：写**服务端覆盖**（``meta_override.series_index``）。只认前端回传的具体条目。

    先预览、再应用（工具页既有纪律）；不动文件名 → ``book_id`` 不变 →
    阅读进度 / 批注 / 评分 / 收藏不断链；**不改写 EPUB 文件**（第 18 期口径）。
    ``new_index`` 给空串 = 撤销覆盖（该册回到文件原值，不等价于「文件里没有序号」）。
    """
    items = (payload or {}).get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "items 必须是非空数组")
    try:
        return series_meta.renumber_apply(name, items)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------- 作者（浏览 / 作者详情）----------------

@app.get("/api/authors")
def api_authors():
    items = library.authors_list()
    rows = db.all_authors()
    out = []
    for a in items:
        row = rows.get(a["name"]) or {}
        has_photo = bool(str(row.get("photo_local_path") or "").strip()
                         or str(row.get("photo_path") or "").strip())
        stamps = [b.get("mtime") or 0 for b in a["books"]]
        out.append({
            "name": a["name"],
            "count": a["count"],
            "series": sorted({b["series"] for b in a["books"] if b.get("series")})[:3],
            "covers": [
                {"id": b["id"], "title": b["title"], "c1": b["c1"], "c2": b["c2"],
                 "has_cover": b.get("has_cover", False)}
                for b in a["books"][:4]
            ],
            # 排序名（本地覆盖 > 在线；空串 = 没设，前端排序时回退到 name）。
            # 复用 authors.sort_name_of 而不是在这儿再写一遍回退 —— 与详情页同一个口径
            "sort_name": authors_mod.sort_name_of(row),
            # 本地缓存的作者头像有无（有则前端去 /api/authors/{name}/photo 取；无则渐变占位）
            "has_photo": has_photo,
            # 名下最早一本书的入库时间（秒），用于「本周新增」筛选
            "added_ts": min(stamps) if stamps else 0,
        })
    return {"items": out, "total": len(items)}


@app.get("/api/authors/{name}")
def api_author_detail(name: str):
    bs = library.author_books(name)
    if not bs:
        raise HTTPException(404, "作者不存在")
    info = authors_mod.effective(name)
    stamps = [b.get("mtime") or 0 for b in bs]
    return {
        "name": name,
        "count": len(bs),
        "books": bs,
        # 传记（本地覆盖 > 在线），无则空串
        "bio": info["bio"],
        "bio_overridden": info["bio_overridden"],
        # 排序名（本地覆盖 > 在线），无则空串 = 按显示名排序
        "sort_name": info["sort_name"],
        "sort_name_overridden": info["sort_name_overridden"],
        # 头像（本地缓存的在线照片 或 用户上传），经专属端点分发
        "has_photo": info["has_photo"],
        "photo_overridden": info["photo_overridden"],
        "photo_source": info["photo_source"],
        "fetched_at": info["fetched_at"],
        # 名下最早一本书的入库时间（秒）
        "added_ts": min(stamps) if stamps else 0,
    }


# ---------------- 作者元数据（抓取 / 编辑 / 头像分发，第 8 期 D1/D2/D5）----------------

_AUTHOR_PHOTO_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                       ".webp": "image/webp", ".gif": "image/gif"}
_AUTHOR_PHOTO_MAX = 8 * 1024 * 1024


@app.get("/api/authors/{name}/photo")
def api_author_photo(name: str):
    """分发作者头像（本地缓存文件，零外链）。无头像返回 404，前端回退渐变占位。"""
    p = authors_mod.photo_path_for(name)
    if not p:
        raise HTTPException(404, "无头像")
    media = _AUTHOR_PHOTO_TYPES.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(p, media_type=media, headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/authors/{name}/bio")
def api_set_author_bio(name: str, payload: dict = Body(...)):
    """设置作者传记的本地覆盖（空串 = 撤销覆盖，回退到在线传记）。"""
    if not library.author_books(name):
        raise HTTPException(404, "作者不存在")
    bio = (payload or {}).get("bio")
    if bio is None:
        raise HTTPException(400, "缺少 bio 字段")
    return {"ok": True, **authors_mod.set_bio(name, str(bio))}


@app.post("/api/authors/sort-name/backfill")
def api_backfill_author_sort_names():
    """为还没有**派生排序键**的作者补 ``sort_name``（第 43 期）。

    上游 ``book-author-sort-key-backfill.service.ts`` 的等价物。⚠️ 只写派生态列
    ``sort_name``，**绝不动** ``sort_name_local``（用户覆盖）—— 写后者等于冒充用户改过、
    界面会误显示「已覆盖」。返回 ``{ok, total, filled, skipped, details}``。
    """
    return {"ok": True, **authors_mod.backfill_sort_names()}


@app.post("/api/authors/{name}/sort-name")
def api_set_author_sort_name(name: str, payload: dict = Body(...)):
    """设置作者排序名的本地覆盖（空串 = 撤销覆盖，排序回退到在线排序名 / 显示名）。"""
    if not library.author_books(name):
        raise HTTPException(404, "作者不存在")
    value = (payload or {}).get("sort_name")
    if value is None:
        raise HTTPException(400, "缺少 sort_name 字段")
    return {"ok": True, **authors_mod.set_sort_name(name, str(value))}


@app.post("/api/authors/{name}/photo")
async def api_upload_author_photo(name: str, file: UploadFile = File(...)):
    """上传作者头像作为本地覆盖（保存到 CACHE_DIR/authors/，覆盖在线照片）。"""
    if not library.author_books(name):
        raise HTTPException(404, "作者不存在")
    fn = (file.filename or "").lower()
    ext = ("." + fn.rsplit(".", 1)[-1]) if "." in fn else ".jpg"
    if ext not in _AUTHOR_PHOTO_TYPES:
        raise HTTPException(400, "仅支持 jpg / png / webp / gif 图片")
    data = await _read_capped(file, _AUTHOR_PHOTO_MAX)
    if not data:
        raise HTTPException(400, "文件为空")
    return {"ok": True, **authors_mod.set_photo(name, data, ext)}


@app.delete("/api/authors/{name}/photo")
def api_clear_author_photo(name: str):
    """撤销本地头像覆盖，回退到在线照片。"""
    if not library.author_books(name):
        raise HTTPException(404, "作者不存在")
    return {"ok": True, **authors_mod.clear_photo_override(name)}


# ---------------- 演播者（浏览 / 详情 / 排序名，第 53 期，镜像 authors）----------------
# 能力矩阵 hasPhoto=— 且本项目作者侧未实现真·软删，故无头像 / 软删端点；
# 也不新增前端独立浏览维度（第 34 期已明确不做），仅保留排序名管理能力。

@app.get("/api/narrators")
def api_narrators():
    items = library.narrators_list()
    rows = db.all_narrators()
    out = []
    for n in items:
        row = rows.get(n["name"]) or {}
        stamps = [b.get("mtime") or 0 for b in n["books"]]
        out.append({
            "name": n["name"],
            "count": n["count"],
            "covers": [
                {"id": b["id"], "title": b["title"], "c1": b["c1"], "c2": b["c2"],
                 "has_cover": b.get("has_cover", False)}
                for b in n["books"][:4]
            ],
            # 排序名（本地覆盖 > 在线；空串 = 没设，前端排序时回退到 name）。
            # 复用 narrators.sort_name_of 与详情页同一个口径。
            "sort_name": narrators_mod.sort_name_of(row),
            "added_ts": min(stamps) if stamps else 0,
        })
    return {"items": out, "total": len(items)}


@app.get("/api/narrators/{name}")
def api_narrator_detail(name: str):
    bs = library.narrator_books(name)
    if not bs:
        raise HTTPException(404, "演播者不存在")
    info = narrators_mod.effective(name)
    stamps = [b.get("mtime") or 0 for b in bs]
    return {
        "name": name,
        "count": len(bs),
        "books": bs,
        "sort_name": info["sort_name"],
        "sort_name_overridden": info["sort_name_overridden"],
        "added_ts": min(stamps) if stamps else 0,
    }


@app.post("/api/narrators/sort-name/backfill")
def api_backfill_narrator_sort_names():
    """为还没有派生排序键的演播者补 ``sort_name``（第 53 期，镜像作者）。

    ⚠️ 只写派生态列 ``sort_name``，**绝不动** ``sort_name_local``（用户覆盖）—— 写后者等于
    冒充用户改过、界面会误显示「已覆盖」。返回 ``{ok, total, filled, skipped, details}``。
    """
    return {"ok": True, **narrators_mod.backfill_sort_names()}


@app.post("/api/narrators/{name}/sort-name")
def api_set_narrator_sort_name(name: str, payload: dict = Body(...)):
    """设置演播者排序名的本地覆盖（空串 = 撤销覆盖，排序回退到在线排序名 / 显示名）。"""
    if not library.narrator_books(name):
        raise HTTPException(404, "演播者不存在")
    value = (payload or {}).get("sort_name")
    if value is None:
        raise HTTPException(400, "缺少 sort_name 字段")
    return {"ok": True, **narrators_mod.set_sort_name(name, str(value))}


# ---------------- 账号资料（第 25 期）----------------
# 单用户：profile 只有一行，头像以覆盖式文件落在 CACHE_DIR/user/avatar.<ext>。

_USER_AVATAR_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                      ".webp": "image/webp"}
_USER_AVATAR_MAX = 5 * 1024 * 1024


def _account_avatar_url() -> "str | None":
    p = db.get_user_profile().get("avatar_path") or ""
    return f"/api/account/avatar?t={int(time.time())}" if p else None


@app.get("/api/account/profile")
def api_account_profile():
    """当前账号资料（头像以可分发 URL 形式返回）。"""
    prof = db.get_user_profile()
    prof["avatar_url"] = _account_avatar_url()
    return prof


@app.put("/api/account/profile")
def api_update_account_profile(payload: dict = Body(...)):
    """更新展示名 / 时区（缺字段则沿用当前值）。"""
    cur = db.get_user_profile()
    new_name = payload.get("display_name", cur["display_name"])
    new_tz = payload.get("timezone", cur["timezone"])
    prof = db.update_user_profile(str(new_name), str(new_tz))
    prof["avatar_url"] = _account_avatar_url()
    return prof


@app.post("/api/account/avatar")
async def api_upload_account_avatar(file: UploadFile = File(...)):
    """上传账号头像（JPG/PNG/WEBP，≤5MB），覆盖式写入。"""
    fn = (file.filename or "").lower()
    ext = ("." + fn.rsplit(".", 1)[-1]) if "." in fn else ""
    if ext not in _USER_AVATAR_TYPES:
        raise HTTPException(400, "仅支持 JPG / PNG / WEBP 图片")
    data = await _read_capped(file, _USER_AVATAR_MAX)
    if not data:
        raise HTTPException(400, "文件为空")
    d = pathlib.Path(config.CACHE_DIR) / "user"
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"avatar{ext}"
    target.write_bytes(data)
    db.set_user_avatar(f"avatar{ext}")
    return {"ok": True, "avatar_url": _account_avatar_url()}


@app.delete("/api/account/avatar")
def api_clear_account_avatar():
    """移除账号头像，回退占位。"""
    p = db.get_user_profile().get("avatar_path") or ""
    if p:
        f = pathlib.Path(config.CACHE_DIR) / "user" / p
        if f.is_file():
            f.unlink()
    db.clear_user_avatar()
    return {"ok": True}


@app.get("/api/account/avatar")
def api_account_avatar():
    """分发账号头像（单用户；走 _MEDIA_TOKEN_PATHS 允许 ?token=）。"""
    p = db.get_user_profile().get("avatar_path") or ""
    if not p:
        raise HTTPException(404, "无头像")
    f = pathlib.Path(config.CACHE_DIR) / "user" / p
    if not f.is_file():
        raise HTTPException(404, "无头像")
    media = _USER_AVATAR_TYPES.get(pathlib.Path(p).suffix.lower(), "application/octet-stream")
    return FileResponse(f, media_type=media, headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/authors/{name}/fetch")
def api_fetch_author(name: str):
    """抓取单个作者的在线传记 / 头像。"""
    if not library.author_books(name):
        raise HTTPException(404, "作者不存在")
    res = authors_mod.fetch_author(name)
    return {"ok": bool(res.get("ok")), "result": res, **authors_mod.effective(name)}


@app.post("/api/authors/fetch-all")
def api_fetch_all_authors():
    """抓取全部作者的在线元数据（逐个抓取、失败不中断）。"""
    return authors_mod.fetch_all()


# ---------------- 批注总览（跨书）----------------

@app.get("/api/annotations")
def api_all_annotations(include_trashed: int = 0):
    """跨书批注总览。

    ``include_trashed=1`` 时把垃圾桶里的条目一并返回（每条带 ``deleted_at``，
    由前端区分活跃/垃圾桶）。**默认 0，即与本次改动前行为一致** ——
    图书详情「批注」tab、每日划线 widget 等无参调用方不该看到已丢弃的条目。
    """
    out = []
    for a in db.all_annotations(include_trashed=bool(include_trashed)):
        b = library.by_id(a["book_id"])
        out.append({
            **a,
            "book_title": b["title"] if b else a["book_id"],
            "book_author": b["author"] if b else "",
        })
    return {"items": out, "total": len(out)}


@app.get("/api/annotations/export")
def api_annotation_export(format: str = "markdown", library_id: str = "", book_id: str = ""):
    """导出批注（第 43 期）：``format`` ∈ markdown / json / csv，可按书库或单书收窄。

    只导**活跃**批注（``deleted_at=0``）—— 垃圾桶里的是已丢弃的内容，不该出现在导出的
    书摘里。需补书名 / 作者供阅读，故与 ``/api/annotations`` 同一套 ``library.by_id`` 口径。
    """
    fmt = str(format or "markdown").lower()
    if fmt not in ("markdown", "json", "csv"):
        raise HTTPException(400, "format 只支持 markdown / json / csv")
    rows = []
    for a in db.all_annotations(include_trashed=False):
        b = library.by_id(a["book_id"])
        if book_id and str(a["book_id"]) != str(book_id):
            continue
        if library_id and str((b or {}).get("library_id") or "") != str(library_id):
            continue
        rows.append({
            **a,
            "book_title": (b or {}).get("title") or a["book_id"],
            "book_author": (b or {}).get("author") or "",
        })
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if fmt == "json":
        body = json.dumps({"items": rows, "total": len(rows)}, ensure_ascii=False, indent=2)
        return Response(
            content=body, media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="annotations-{stamp}.json"'})
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["book_title", "book_author", "chapter", "quote", "note", "color", "style", "created_at"])
        for r in rows:
            w.writerow([r.get("book_title", ""), r.get("book_author", ""), r.get("chapter", ""),
                        r.get("quote", ""), r.get("note", ""), r.get("color", ""),
                        r.get("style", ""), r.get("created_at", "")])
        return Response(
            content=buf.getvalue(), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="annotations-{stamp}.csv"'})
    lines = ["# 批注导出", "", f"共 {len(rows)} 条", ""]
    cur_book = None
    for r in rows:
        bt = r.get("book_title") or ""
        if bt != cur_book:
            cur_book = bt
            suffix = f"（{r.get('book_author')}）" if r.get("book_author") else ""
            lines += ["", f"## {bt}{suffix}", ""]
        quote = str(r.get("quote") or "").strip()
        note = str(r.get("note") or "").strip()
        style = str(r.get("style") or "highlight").strip() or "highlight"
        line = f"- {quote}" + (f"  \n  > {note}" if note else "")
        if style != "highlight":
            line += f"  （样式：{style}）"
        lines.append(line)
    body = "\n".join(lines) + "\n"
    return Response(
        content=body, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="annotations-{stamp}.md"'})


# ⚠️ 字面量路径 `/api/annotations/overview` 与参数化路径不冲突（该前缀下没有
#    `{param}` 兄弟路由），但仓库已有「字面量注册在 {param} 之后、只因 method 不同
#    才没出事」的先例（`/api/authors/{name}` 先于 `/api/authors/fetch-all`）——
#    契约测试因此同时断言 method + path，而不是只看 path。
@app.get("/api/annotations/overview")
def api_annotations_overview():
    """批注总览统计：活跃 / 垃圾桶计数 + 周节拍（有批注的周数、最长连续无批注周数）。

    ⚠️ 上游同名字段还含 `needsReview` 与 `devices`，本项目**刻意不返回**：
    它们依赖「设备回传批注 + 人工对账」这套上游能力，而本项目 kosync 只同步**进度**
    （无批注端点）、也没有 KOReader/Kobo 批注导入 —— 没有数据源就返回恒 0/恒 1 是假数据。
    等批注导入落地后再一并补上。
    """
    return db.annotation_overview()


# ---------------- 书库（第 10 期 D8）----------------
# 三个概念各有归属，别再混用：
#   /api/libraries          → **库实体**（id / 名称 / 类型 / 归属模式 / 根目录 / 书数）
#   /api/library-facets     → **格式分面**（原 /api/libraries 的语义：fmt: / issues: / nocover:）
#   /api/library-migrations → 现有书「按格式迁移」的预览 / 计划 / 执行 / 回滚

_LIB_TYPE_LABELS = migrate.TYPE_LABELS


def _library_root_allowed(raw) -> pathlib.Path:
    """库根必须落在白名单父目录内。

    放任任意路径 = 放任「扫描 / 改名 / 回收」作用到系统目录：``safe_path`` 的边界是
    **库根**，库根一放开边界就等于没有。所以这里与 ``safe_path`` 同一条思路 ——
    只认已知根的子路径。
    """
    p = pathlib.Path(str(raw or "").strip()).expanduser()
    if not p.is_absolute():
        raise HTTPException(400, "库根必须是绝对路径")
    rp = p.resolve()
    bases = [r["path"] for r in config.LIBRARY_SOURCE_ROOTS] + [config.OUTPUT_DIR, config.DATA_DIR]
    for base in bases:
        try:
            br = pathlib.Path(base).resolve()
        except Exception:
            continue
        if rp == br or br in rp.parents:
            return rp
    raise HTTPException(400, "库根必须位于「书库来源目录 / 导出目录 / 数据目录」之内"
                             "（否则可能误扫、甚至误移系统文件）")


def _roots_from_json(raw) -> "list[pathlib.Path]":
    """把库行的 source_dirs（JSON 数组文本）解析为已 resolve 的绝对路径列表。"""
    try:
        arr = json.loads(raw) if raw else []
    except Exception:
        arr = []
    out = []
    for x in arr:
        try:
            out.append(pathlib.Path(str(x)).resolve())
        except Exception:
            pass
    return out


def _roots_of(lib: dict) -> "list[pathlib.Path]":
    """库实体的所有文件夹绝对路径（已 resolve）。空库返回空列表。"""
    return _roots_from_json(lib.get("source_dirs") or "")


def _own_roots(roots) -> list:
    """「本书库自己」的库根 → 成品目录校验的守卫项。roots = 绝对路径可迭代。"""
    out = []
    for p in (roots or []):
        try:
            out.append(("本书库的库根", pathlib.Path(str(p)).resolve()))
        except Exception:
            pass
    return out


def _publish_path_allowed(raw, extra_roots=()) -> "pathlib.Path | None":
    """刮削出版的**成品目录**校验（第 18 期）。

    比库根更严一档：除了必须在白名单根内（复用 :func:`_library_root_allowed`），
    还**不得与任何扫描根 / 库根相交** —— 相等、位于其内、或是它的祖先都不行。

    理由：成品目录里放的是**硬链接副本**，一旦它落在扫描范围里，watcher 与库扫描
    会把副本当成新书扫进来（书列表出现重复），改名 / 回收 / 迁移也会作用到副本上，
    进而破坏「原书不被改动」这条底线。空值表示该库不产出副本，直接放行。

    ``extra_roots``：**正在建 / 正在改的那一个书库自己**的库根与扫描源目录。
    库表里已有的书库能从 :func:`library.libraries` 查到，但「还没落库的自己」查不到，
    必须显式传进来 —— 否则「把成品目录放进自己库根」这条最典型的错法会漏过校验。
    """
    text = str(raw or "").strip()
    if not text:
        return None
    rp = _library_root_allowed(text)
    guards = list(extra_roots)
    try:
        guards.append(("投递目录", pathlib.Path(config.INPUT_DIR).resolve()))
    except Exception:                                   # noqa: BLE001
        pass
    try:
        for lib in library.libraries():
            for lr in _roots_of(lib):
                guards.append((f"书库「{lib.get('name') or lib.get('id')}」的库根", lr))
    except Exception:                                   # noqa: BLE001
        pass
    for label, g in guards:
        if rp == g or g in rp.parents or rp in g.parents:
            raise HTTPException(
                400,
                f"成品目录不能与{label}重叠（{g}）：副本会被扫描回来变成重复书，"
                "请选一个独立目录（可与库根、扫描源目录平级）")
    return rp


def _writable_dir(p: pathlib.Path) -> bool:
    """真实试写一次 —— 只看权限位会漏掉只读挂载等情形。"""
    try:
        probe = p / ".nf-write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _library_dto(lib: dict, counts: dict = None) -> dict:
    roots = _roots_of(lib)
    t = str(lib.get("type") or "mixed")
    # 刮削出版成品目录（第 18 期）：空串 = 该库不产出硬链接副本。
    # ⚠️ 不能用 pathlib.Path("") 兜底 —— 那会解析成 "." 并被 is_dir() 判真。
    pub_raw = str(lib.get("publish_path") or "").strip()
    pub = pathlib.Path(pub_raw) if pub_raw else None
    return {
        "id": lib.get("id"), "name": lib.get("name") or "", "type": t,
        "type_label": _LIB_TYPE_LABELS.get(t, "混合库"),
        # 第 41 期：该库所有文件夹的绝对路径（就地引用语义，跨根合法）。
        "source_dirs": [str(r) for r in roots],
        "rules": lib.get("rules") or "",
        "sort_order": int(lib.get("sort_order") or 0),
        # 刮削出版成品目录（第 18 期）：副本落点，供外部阅读器挂载；空 = 未启用
        "publish_path": pub_raw,
        "publish_exists": bool(pub) and pub.is_dir(),
        "publish_writable": _writable_dir(pub) if pub and pub.is_dir() else False,
        # 逐库扫描调度（第 17 期 T2）
        "watch": int(lib.get("watch", 1) or 0),
        "scan_interval": int(lib.get("scan_interval", 0) or 0),
        "scan_cron": lib.get("scan_cron") or "",
        # 新库向导三列（第 40 期）：图标 / 允许的格式 / 排除图案
        "icon": str(lib.get("icon") or ""),
        # ⚠️ 空数组 = **没设过**（读时回落库类型默认），不是「一个格式都不收」：
        # 前端据此显示「继承默认」态。`exts_effective` 是回落之后的**真实**白名单 ——
        # 界面要展示「默认会收哪些」就用它，别在前端再推一遍（那是第二个真相源）。
        "allowed_exts": list(library.parse_exts(lib.get("allowed_exts"))),
        "exts_effective": list(library.exts_for_library(lib)),
        "exclude": list(library.parse_excludes(lib.get("exclude"))),
        "book_count": int((counts or {}).get(str(lib.get("id")), 0)),
        "exists": any(r.is_dir() for r in roots),
        "writable": any(_writable_dir(r) for r in roots if r.is_dir()),
        "last_scan_at": float(lib.get("last_scan_at") or 0),
        "last_scan_note": lib.get("last_scan_note") or "",
    }


def _libraries_changed() -> None:
    """书库**增 / 删 / 改**之后统一要做的两件事。

    ① 失效扫描缓存（否则界面继续显示旧口径）；
    ② 清掉 watcher 的失败计数 —— 第 37 期必需：没有可接收的库时投递会被**拒收**
       （`library_rules.resolve_target` 的 root 为 None），而失败计数到上限就永久跳过。
       用户照着提示建完库，原先投递过的文件应当自己就被收进去，
       而不是要求他再投一次 —— 那与本期的语义无关，纯属实现的副作用。
    """
    library.invalidate()
    w = WATCHER
    if w is not None:
        try:
            w.forget_failures()
        except Exception:                              # noqa: BLE001
            pass


def _book_counts() -> dict:
    """``{library_id: 书数}``（一次扫描全库，避免逐库重扫）。"""
    out: dict = {}
    for b in library.books():
        k = str(b.get("library_id") or "")
        out[k] = out.get(k, 0) + 1
    return out


def _new_library_id(seed: str) -> str:
    """库 id：ASCII 名做 slug，否则用短哈希（URL 安全、单段）。"""
    s = re.sub(r"[^a-z0-9]+", "-", str(seed or "").lower()).strip("-")
    if s and 2 <= len(s) <= 32:
        return s
    return "lib-" + hashlib.sha1(str(seed or "").encode("utf-8")).hexdigest()[:8]


def _norm_rules(raw) -> str:
    """库的 ``rules`` 统一存 JSON 字符串（关键词 / 来源子目录）。

    前端可能传对象、数组，或一句「科幻, 太空」—— 一律归一，别让三种形状在库里并存。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return ""
        if text.startswith("{"):
            try:
                json.loads(text)
                return text
            except Exception:
                pass
        return json.dumps(
            {"keywords": [p.strip() for p in re.split(r"[,、;]", text) if p.strip()]},
            ensure_ascii=False,
        )
    if isinstance(raw, dict):
        return json.dumps(raw, ensure_ascii=False)
    if isinstance(raw, list):
        return json.dumps({"keywords": [str(x) for x in raw]}, ensure_ascii=False)
    return ""


# ---------------- 新库向导三列（第 40 期）----------------
#: 图标名的**形状**校验。⚠️ 刻意**不校验白名单** —— 44 个合法键的唯一真值源在前端
#: `lib/icons.ts` 的 `ICONS`（`IconName = keyof typeof ICONS` 是编译期闭合）。
#: 在 Python 里再抄一份就是第二个真相源，加图标时必然漂移。前端渲染是**常量表查表**，
#: 未知键查不到就是「没有图标」（惰性失败），不会注入任何东西。
_ICON_RE = re.compile(r"^[a-z][A-Za-z0-9]{0,31}$")
#: 扩展名形状：点 + 1–8 位小写字母数字（先经 ``library.norm_ext`` 归一才判）。
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,8}$")
#: 列表上限 —— 只防手滑塞进一坨，不是产品约束（上游那份格式清单是 16 项）。
_MAX_LIST = 64


def _norm_icon(raw) -> str:
    """图标名：形状合法才收；空串 = 不显示图标。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    if not _ICON_RE.match(s):
        raise HTTPException(400, "图标名非法（只允许字母开头的字母数字，如 book / arrowLeft）")
    return s


def _norm_exts(raw) -> str:
    """「允许的格式」→ JSON 数组文本。

    ⚠️ 空列表归一成 ``''``（=**没设过**，读时回落库类型默认），**不是** ``'[]'`` ——
    后者在扫描侧的含义是「一个格式都不收」，会造出一个永远扫不出东西的死库。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        raw = [p for p in re.split(r"[,、;\s]+", raw) if p]
    if not isinstance(raw, (list, tuple)):
        raise HTTPException(400, "允许的格式必须是数组")
    if len(raw) > _MAX_LIST:
        raise HTTPException(400, f"允许的格式最多 {_MAX_LIST} 项")
    out: list = []
    for v in raw:
        e = library.norm_ext(v)
        if not _EXT_RE.match(e):
            raise HTTPException(400, f"允许的格式里有非法扩展名：{v!r}")
        if e not in out:
            out.append(e)
    return json.dumps(out, ensure_ascii=False) if out else ""


def _norm_excludes(raw) -> str:
    """「排除图案」→ JSON 数组文本；空列表 ⇒ ``''``（=不过滤）。

    图案可以含 ``/``（含斜杠的按**相对库根的路径**匹，见 ``library._excluded``），
    所以这里**只**挡控制字符与超长 —— 不挡分隔符。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        raw = [p for p in re.split(r"[,、;]", raw) if p.strip()]
    if not isinstance(raw, (list, tuple)):
        raise HTTPException(400, "排除图案必须是数组")
    if len(raw) > _MAX_LIST:
        raise HTTPException(400, f"排除图案最多 {_MAX_LIST} 项")
    out: list = []
    for v in raw:
        p = str(v or "").strip()
        if not p:
            continue
        if len(p) > 128 or any(ch in p for ch in "\x00\r\n"):
            raise HTTPException(400, f"排除图案非法：{p!r}")
        if p not in out:
            out.append(p)
    return json.dumps(out, ensure_ascii=False) if out else ""


@app.get("/api/libraries")
def api_libraries():
    """**库实体**列表（含书数 / 是否存在 / 可写）。格式分面见 ``/api/library-facets``。"""
    counts = _book_counts()
    items = [_library_dto(l, counts) for l in library.libraries()]
    items.sort(key=lambda x: (x["sort_order"], x["name"]))
    return {
        "items": items, "total": len(items),
        # 第 40 期：`exts` = 该类型的**默认扫描白名单**，供新建向导的「允许的格式」
        # 一选类型就带出默认勾选集（前端不许自己抄一份 —— 抄了就会与扫描口径走散）。
        "types": [{"value": t, "label": _LIB_TYPE_LABELS.get(t, t),
                   "exts": list(library._exts_for_type(t))} for t in db.LIBRARY_TYPES],
        # 第 41 期：已配置的来源根（向导按这些根浏览 / 下钻，数量不定）。
        "source_roots": [{"name": r["name"], "path": str(r["path"])}
                         for r in config.LIBRARY_SOURCE_ROOTS],
    }


@app.get("/api/reading-thresholds")
def api_reading_thresholds(library_id: str = ""):
    """阅读状态口径（第 40 期）：``{library_id, started, finished}``。

    ``library_id`` 为空 → **全局值**（书架 / 仪表盘这类跨库视图用）；
    给了库 → 该库的**生效值**（每库覆写 ?? 全局，与 ``lib_settings`` 同口径）。

    这是全站取阅读阈值的**唯一入口** —— 前端 ``lib/readingThresholds.ts`` 消费它。
    ⚠️ 界面别自己再写 ``99.5``：那会与统计 / 成就对不上（同一本书在统计里算已读完、
    在书架上还是在读）。「哪几项被本库覆写过」看既有的
    ``GET /api/libraries/{lid}/settings`` 的 ``overridden``，不在这里重复一套。
    """
    lid = str(library_id or "").strip()
    if lid and not db.get_library(lid):
        raise HTTPException(404, "书库不存在")
    started, finished = lib_settings.reading_thresholds(lid or None)
    return {"library_id": lid, "started": started, "finished": finished}


@app.get("/api/features")
def api_features(library_id: str = ""):
    """当前库（或全部书库）的**能力清单** —— 前端据此裁剪导航 / 工具标签 / 设置 / 仪表盘。

    不传 ``library_id``（= 「全部书库」）时返回全部能力，**不做裁剪**。
    """
    lib = db.get_library(library_id) if library_id else None
    ltype = str((lib or {}).get("type") or "") if library_id else ""
    return {
        "library_id": library_id,
        "library_type": ltype,
        "features": features.features_for(ltype),
        "matrix": features.matrix(),
    }


@app.get("/api/library-facets")
def api_library_facets():
    """按格式 / 待修复 / 无封面的**分面**（原 ``/api/libraries`` 的语义，第 10 期改址）。

    侧栏不再展示它（ShelfView 本就有格式筛选），保留给需要的页面与既有调用方。
    """
    return {"items": library.library_groups()}


@app.get("/api/libraries/source-dirs")
def api_library_source_dirs(root: int = None, path: str = ""):
    """多来源根目录树。

    - 不传参数：返回所有已配置来源根（``roots``），每张含索引 / 名称 / 路径 / 子项数。
    - 传 ``root=索引&path=相对子目录``：返回该根下某目录的子项（下钻），供向导弹出下一级文件夹。
    """
    roots = config.LIBRARY_SOURCE_ROOTS
    if root is None:
        out = []
        for i, r in enumerate(roots):
            p = pathlib.Path(r["path"])
            n = 0
            try:
                for _c in p.iterdir():
                    n += 1
                    if n >= 500:        # 只报「有多少」，不为一个巨大目录白跑一遍
                        break
            except Exception:
                pass
            out.append({"index": i, "name": r["name"], "path": str(p),
                        "exists": p.is_dir(), "entries": n})
        return {"roots": out}
    if root < 0 or root >= len(roots):
        raise HTTPException(400, "来源根索引越界")
    base = pathlib.Path(roots[root]["path"])
    target = (base / path) if path else base
    if not target.is_absolute():
        raise HTTPException(400, "路径非法")
    # 安全：必须位于该来源根之内（不能越界到其它根 / 系统目录）
    try:
        target.resolve().relative_to(base.resolve())
    except Exception:
        raise HTTPException(400, "路径必须位于来源根内")
    entries = []
    try:
        for p in sorted(target.iterdir()):
            if p.name.startswith("."):
                continue
            entries.append({"name": p.name, "path": str(p),
                            "type": "dir" if p.is_dir() else "file"})
    except Exception:
        pass
    return {"root_index": root, "root_name": roots[root]["name"],
            "base": str(base), "path": str(target), "entries": entries}


@app.post("/api/libraries")
def api_create_library(payload: dict = Body(...)):
    """新建书库。**只登记，不动文件**（文件搬迁归迁移流程管）。

    第 41 期：内容来源改为**多个文件夹**（source_dirs，绝对路径数组），每个文件夹必须
    落在某个已配置来源根之内（就地引用语义，跨根合法）。不再有「归属模式」概念。
    """
    p = payload or {}
    name = str(p.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "库名不能为空")
    ltype = str(p.get("type") or "mixed")
    if ltype not in db.LIBRARY_TYPES:
        raise HTTPException(400, "库类型非法")
    # 新库向导三列（第 40 期）：形状校验放在**建目录之前** ——
    # 参数非法就不该留下一个空的库根目录。
    icon = _norm_icon(p.get("icon"))
    allowed_exts = _norm_exts(p.get("allowed_exts"))
    exclude = _norm_excludes(p.get("exclude"))
    # 第 41 期：内容来源 = 多个文件夹（就地引用）。边界校验在 config.normalize_source_dirs 内。
    raw_dirs = p.get("source_dirs") or []
    if isinstance(raw_dirs, str):
        try:
            raw_dirs = json.loads(raw_dirs)
        except Exception:
            raw_dirs = []
    try:
        dirs = config.normalize_source_dirs(raw_dirs)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not dirs:
        raise HTTPException(400, "至少选择一个内容来源文件夹")
    lid = _new_library_id(p.get("id") or name)
    if db.get_library(lid):
        raise HTTPException(400, f"库标识已存在：{lid}")
    try:
        sort_order = int(p.get("sort_order") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "sort_order 必须是整数")
    watch = 1
    if "watch" in p:
        try:
            watch = int(p.get("watch") or 0)
        except (TypeError, ValueError):
            watch = 1
    scan_interval = 0
    if "scan_interval" in p:
        try:
            scan_interval = int(p.get("scan_interval") or 0)
        except (TypeError, ValueError):
            scan_interval = 0
    scan_cron = (str(p.get("scan_cron") or "").strip()) if "scan_cron" in p else ""
    # 刮削出版成品目录（第 18 期）：可选。给了就校验边界并预先建出来，
    # 免得界面显示「已配置」、首次刮削才发现目录不存在。
    publish = _publish_path_allowed(p.get("publish_path"),
                                   _own_roots([str(d) for d in dirs]))
    if publish:
        try:
            publish.mkdir(parents=True, exist_ok=True)
        except Exception as e:                          # noqa: BLE001
            raise HTTPException(400, f"无法创建成品目录：{e}")
    lib = db.create_library(lid, name, ltype,
                            source_dirs=[str(d) for d in dirs],
                            rules=_norm_rules(p.get("rules")), sort_order=sort_order,
                            watch=watch, scan_interval=scan_interval, scan_cron=scan_cron,
                            publish_path=str(publish or ""),
                            icon=icon, allowed_exts=allowed_exts, exclude=exclude)
    _libraries_changed()
    activity_log.log(activity_log.ACTION_LAYOUT, name, activity_log.STATUS_OK,
                     detail=f"新建书库：{ltype} / 多文件夹 {len(dirs)}"
                            + (f" / 成品目录 {publish}" if publish else ""), source="api")
    return {"ok": True, "library": _library_dto(lib or {}, {})}


@app.patch("/api/libraries/{lid}")
def api_update_library(lid: str, payload: dict = Body(...)):
    """改库属性。改 ``source_dirs`` **只改登记，不搬文件**（搬用迁移流程）。

    第 41 期：内容来源改为多文件夹（source_dirs）；不再有归属模式 / 单 root_path。
    """
    if not db.get_library(lid):
        raise HTTPException(404, "书库不存在")
    p = payload or {}
    fields: dict = {}
    if "name" in p:
        nm = str(p.get("name") or "").strip()
        if not nm:
            raise HTTPException(400, "库名不能为空")
        fields["name"] = nm
    if "type" in p:
        if str(p["type"]) not in db.LIBRARY_TYPES:
            raise HTTPException(400, "库类型非法")
        fields["type"] = str(p["type"])
    # 第 41 期：内容来源 = 多文件夹（就地引用）。边界校验在 config.normalize_source_dirs 内。
    if "source_dirs" in p:
        raw_dirs = p["source_dirs"]
        if isinstance(raw_dirs, str):
            try:
                raw_dirs = json.loads(raw_dirs)
            except Exception:
                raw_dirs = []
        try:
            dirs = config.normalize_source_dirs(raw_dirs)
        except ValueError as e:
            raise HTTPException(400, str(e))
        fields["source_dirs"] = json.dumps([str(d) for d in dirs], ensure_ascii=False)
    if "rules" in p:
        fields["rules"] = _norm_rules(p.get("rules"))
    if "sort_order" in p:
        try:
            fields["sort_order"] = int(p.get("sort_order") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "sort_order 必须是整数")
    # 逐库扫描调度字段（第 17 期 T2）
    if "watch" in p:
        try:
            fields["watch"] = int(p.get("watch") or 0)
        except (TypeError, ValueError):
            fields["watch"] = 1
    if "scan_interval" in p:
        try:
            fields["scan_interval"] = int(p.get("scan_interval") or 0)
        except (TypeError, ValueError):
            fields["scan_interval"] = 0
    if "scan_cron" in p:
        fields["scan_cron"] = str(p.get("scan_cron") or "").strip()
    # 刮削出版成品目录（第 18 期）：传空串 = 关闭该库的副本产出。
    # ⚠️ 改这一项**不动已有副本**（副本的清理由刮削页显式操作），只影响后续刮削落点。
    if "publish_path" in p:
        cur = db.get_library(lid) or {}
        # 用**改完之后**的库根做校验：同一次请求里同时改了 source_dirs 与
        # publish_path 时，只按旧值校验会放过「改完就重叠」的组合。
        new_roots = _roots_of({"source_dirs": fields.get("source_dirs", cur.get("source_dirs", ""))})
        pub = _publish_path_allowed(p.get("publish_path"), _own_roots([str(r) for r in new_roots]))
        if pub:
            try:
                pub.mkdir(parents=True, exist_ok=True)
            except Exception as e:                      # noqa: BLE001
                raise HTTPException(400, f"无法创建成品目录：{e}")
        fields["publish_path"] = str(pub or "")
    # 新库向导三列（第 40 期）：传空串 / 空数组 = 恢复「没设过」（继承库类型默认）。
    # ⚠️ 收窄 allowed_exts 会让原本扫得到的书**从书目里消失**（排除图案同理）——
    # 这是用户显式操作的结果，不额外拦；但 `library._books_of` 的目录指纹含这两项，
    # 所以缓存会失效、列表当场刷新（不然用户改完看不见效果，会以为没生效）。
    if "icon" in p:
        fields["icon"] = _norm_icon(p.get("icon"))
    if "allowed_exts" in p:
        fields["allowed_exts"] = _norm_exts(p.get("allowed_exts"))
    if "exclude" in p:
        fields["exclude"] = _norm_excludes(p.get("exclude"))
    if not fields:
        raise HTTPException(400, "没有可更新的字段")
    lib = db.update_library(lid, **fields)
    _libraries_changed()
    activity_log.log(activity_log.ACTION_LAYOUT, str(p.get("name") or lid),
                     activity_log.STATUS_OK,
                     detail="更新书库：" + "、".join(sorted(fields)), source="api")
    return {"ok": True, "library": _library_dto(lib or {}, _book_counts())}


@app.delete("/api/libraries/{lid}")
def api_delete_library(lid: str, force: bool = False):
    """**只移除登记，绝不删文件**。库里还有书时默认拒绝（先迁移或清空）。

    第 37 期起**没有任何库是不可删的**：以前那条「默认书库不可删除」的护栏随默认库
    概念一起下线。book_id 形如 ``库$哈希``，库没了它的书就从书目里消失（进度 / 批注
    变成「库不存在的行」，孤儿清理**刻意不碰**它们，见 `_orphan_refs`）。
    「库里还有书」的拦截仍在下面，那才是真正的数据保护。
    """
    if not db.get_library(lid):
        raise HTTPException(404, "书库不存在")
    n = _book_counts().get(str(lid), 0)
    if n and not force:
        raise HTTPException(400, f"该库还有 {n} 本书：请先迁移走，"
                                 f"或加 force=1 仅移除登记（文件留在原地）")
    db.delete_library(lid)
    # 库没了，刮削台账行也没有意义（UI 会显示一堆属于不存在书库的条目）。
    # **只删登记，副本文件留在成品目录里**，与「移除库不删文件」一致。
    db.scrape_delete_by_library(lid)
    _libraries_changed()
    activity_log.log(activity_log.ACTION_LAYOUT, str(lid), activity_log.STATUS_OK,
                     detail=f"移除书库登记（文件保留在原地）· 当时 {n} 本", source="api")
    return {"ok": True, "removed": str(lid), "books_left_on_disk": n}


@app.post("/api/libraries/{lid}/scan")
def api_scan_library(lid: str):
    """重新扫描单个库（失效该库缓存 + 记一次扫描时间）。

    第 18 期起，扫描后**顺带把该库的书排进刮削队列**（若开了自动刮削）——
    这正是用户要的「扫描 → 刮削 → 在新目录硬链接出成品」那一道工序：新书入库与
    手工重扫都会收敛到同一条流水。刮削本身是异步的（worker 串行跑，进度看 /api/scrape/state）。
    """
    lib = db.get_library(lid)
    if not lib:
        raise HTTPException(404, "书库不存在")
    library.invalidate(lid)
    bs = library.books(lid, force=True)
    db.set_library_scan(lid, note=f"手动扫描：{len(bs)} 本")
    # 若该库有来源子目录且 watcher 在跑，立即触发一次来源目录扫描（摄入新文件）
    if WATCHER is not None and WATCHER.is_running():
        try:
            WATCHER.scan_library_now(lid)
        except Exception:
            pass
    try:
        queued = _enqueue_scrape_for(lid)
    except Exception as e:  # noqa: BLE001 —— 刮削是旁路，绝不因它让扫描报错
        logging.getLogger("novelforge").exception("扫描后入队刮削失败：%s", e)
        queued = 0
    # 扫描 = 书集可能变了 ⇒ 后台补算一轮语义向量（有单飞闸 + 节流，扫描不受它拖慢）
    _schedule_embed_refresh()
    return {"ok": True, "id": lid, "count": len(bs), "scrape_queued": queued}


def _enqueue_scrape_for(library_id=None) -> int:
    """按自动开关把书排进刮削队列并唤醒 worker；返回新入队条数。

    **自动开关只管这里** —— 页面上的「开始刮削」走 ``/api/scrape/run``，
    不受开关限制（用户点了就该跑）。
    """
    lid = str(library_id or "")
    if lid and not scrape.enabled(lid):
        return 0
    if not lid:
        # 全部库：只处理开了自动刮削的库（逐库判断，避免给关掉的库排一堆待办）
        enabled = [str(l.get("id")) for l in library.libraries()
                   if scrape.enabled(str(l.get("id")))]
        if not enabled:
            return 0
        queued = sum(_enqueue_scrape_for(x) for x in enabled)
        return queued
    res = scrape.enqueue_library(lid)
    queued = int(res.get("queued") or 0)
    if queued:
        scrape.start()
        scrape.wake()
    return queued


# ---- 每库覆盖（第 13 期）----
# 生效值 = 每库覆写 ?? 全局值，落点仍是 ``libraries.settings`` 的稀疏 JSON
# （见 core/lib_settings 的模块注释）。这里只做「校验 + 落库 + 回显」：
# 校验与归一化**全部复用** lib_settings —— 界面拒了而内核收了（或反之）就是两套口径。

def _library_settings_or_404(lid: str) -> None:
    if not db.get_library(lid):
        raise HTTPException(404, "书库不存在")


@app.get("/api/libraries/{lid}/settings")
def api_library_settings(lid: str):
    """该库的生效设置 + 哪些项被本库覆写过（界面据此显示「已覆盖 / 恢复继承」）。

    返回项已按**库类型能力**收窄：漫画库不会返回元数据策略这类它根本用不上的项。
    """
    _library_settings_or_404(lid)
    return lib_settings.effective(lid)


@app.put("/api/libraries/{lid}/settings")
def api_set_library_settings(lid: str, payload: dict = Body(...)):
    """写入覆盖项：``{键: 值}``。**值传 ``null`` = 该项恢复继承全局**。

    ``metadata_fetch.fields`` 支持**字段级**恢复（``{"fields": {"tags": null}}``）。
    键名一律用全局配置的点分路径（``output.layout`` / ``naming.pattern`` …）。
    """
    _library_settings_or_404(lid)
    body = payload if isinstance(payload, dict) else {}
    if not body:
        raise HTTPException(400, "没有可更新的覆盖项")
    try:
        res = lib_settings.set_overrides(lid, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    activity_log.log(activity_log.ACTION_PREFS, str(res.get("name") or lid),
                     activity_log.STATUS_OK,
                     detail="更新每库设置：" + "、".join(sorted(str(k) for k in body)),
                     source="api")
    return res


@app.delete("/api/libraries/{lid}/settings")
def api_clear_library_settings(lid: str, keys: str = ""):
    """恢复继承：``keys`` 逗号分隔时只清这几项；不给 = **全部**回到全局值。"""
    _library_settings_or_404(lid)
    ks = [k.strip() for k in str(keys or "").split(",") if k.strip()] or None
    try:
        res = lib_settings.clear_overrides(lid, ks)
    except ValueError as e:
        raise HTTPException(400, str(e))
    activity_log.log(activity_log.ACTION_PREFS, str(res.get("name") or lid),
                     activity_log.STATUS_OK,
                     detail="恢复继承全局：" + ("、".join(ks) if ks else "全部项"),
                     source="api")
    return res


# ---------------- 刮削出版（第 18 期）----------------
# ⚠️ **字面量路径必须注册在带路径参数的路径之前**：``/api/scrape/run`` 与
# ``/api/scrape/{bid}/resolve`` 若顺序颠倒，"run" 会被当成 book_id 吃掉
# （与 ``/api/books/{bid}`` 那次踩坑同源，见 tests 里的注册顺序断言）。

#: 状态 → 界面徽标文案（真值源放后端，免得前后端各写一套文案）
_SCRAPE_LABELS = {
    "pending": "待刮削", "running": "进行中", "ok": "已出版",
    "failed": "失败", "skipped": "跳过", "removed": "待确认",
    "kept": "已保留", "orphan": "孤本", "source_removed": "原文件已回收",
}


def _scrape_actions(status: str) -> list:
    """该状态下**允许**用户做的处置（界面据此渲染按钮，后端仍会二次校验）。"""
    st = str(status or "")
    if st == "removed":
        return ["delete_source", "keep_source", "rebuild"]
    if st == "orphan":
        return ["keep_copy", "recycle_copy"]
    if st in ("kept", "failed", "skipped"):
        return ["rebuild"]
    return []


@app.get("/api/scrape/state")
def api_scrape_state(library_id: str = "", status: str = "", q: str = ""):
    """刮削台账：概览计数 + 条目列表 + worker 运行态（页面轮询此端点）。

    列表带出书名 / 作者 / 源路径 / 副本路径 / 模式 / 已写字段 / 失败原因 / 可用动作。
    书籍信息来自 ``library.books()``（已有 5s 扫描缓存），**不逐条查库**。
    """
    lid = str(library_id or "").strip()
    rows = db.scrape_list(library_id=lid or None, status=status or None)
    books = {str(b.get("id")): b for b in library.books(lid or None)}
    lib_names = {str(l.get("id")): str(l.get("name") or "")
                 for l in library.libraries()}
    items = []
    keyword = str(q or "").strip().lower()
    for r in rows:
        bid = str(r.get("book_id"))
        b = books.get(bid) or {}
        name = str(r.get("source_rel") or b.get("name") or "")
        title = str(b.get("title") or "") or name
        author = str(b.get("author") or "")
        if keyword and keyword not in f"{name} {title} {author}".lower():
            continue
        l_id = str(r.get("library_id") or "")
        pdir = publish.publish_dir(l_id)
        rel = str(r.get("link_rel") or "")
        st = str(r.get("status") or "")
        items.append({
            "book_id": bid, "library_id": l_id,
            "library_name": lib_names.get(l_id, ""),
            "name": name, "title": title, "author": author,
            "status": st, "status_label": _SCRAPE_LABELS.get(st, st),
            # 第 41 期：直接用书籍自身记录的绝对路径（多文件夹库下 root_path 已无意义）。
            "source_path": str(b.get("path") or ""),
            "copy_path": str(pdir / rel) if (pdir and rel) else "",
            "link_rel": rel, "link_mode": str(r.get("link_mode") or ""),
            "shared": bool(r.get("link_shared")),
            "embedded": [x for x in str(r.get("embedded") or "").split(",") if x],
            "has_cover": bool(r.get("has_cover")),
            "error": str(r.get("error") or ""),
            "attempts": int(r.get("attempts") or 0),
            "removed_at": float(r.get("removed_at") or 0),
            "removed_path": str(r.get("removed_path") or ""),
            "confirmed_at": float(r.get("confirmed_at") or 0),
            "updated_at": float(r.get("updated_at") or 0),
            "actions": _scrape_actions(st),
            "degraded": st in ("removed", "orphan"),
        })
    counts = db.scrape_counts(lid or None)
    # 当前筛选范围内有没有「配了成品目录」的库？没有的话，空状态要给的是
    # 「去书库管理设置成品目录」而不是含糊的「暂无记录」—— 否则用户会以为功能坏了。
    if lid:
        publish_ok = publish.publish_dir(lid) is not None
    else:
        publish_ok = any(publish.publish_dir(str(l.get("id")))
                         for l in library.libraries())
    return {
        "items": items, "count": len(items), "counts": counts,
        "total": sum(counts.values()),
        "pending": int(counts.get("pending", 0)) + int(counts.get("running", 0)),
        "needs_confirm": int(counts.get("removed", 0)) + int(counts.get("orphan", 0)),
        "worker": scrape.worker_state(),
        "labels": _SCRAPE_LABELS,
        "actions": scrape.ACTIONS,
        "auto_enabled": scrape.enabled(lid or None),
        "publish_configured": publish_ok,
    }


@app.post("/api/scrape/run")
def api_scrape_run(payload: dict = Body(default=None)):
    """开始刮削 / 重新刮削：入队 + 唤醒 worker（**异步**，进度看 /state 轮询）。

    ``{library_id?, force?, only_failed?}``：
    - 不带 ``library_id`` = 全部**配置了成品目录**的库；
    - ``force=True`` = 忽略「已是最新」，强制重新抓取并重建副本；
    - ``only_failed=True`` = 只重排当前失败的条目（轻量重试）。
    """
    p = payload or {}
    lid = str(p.get("library_id") or "").strip()
    force = bool(p.get("force"))
    if p.get("only_failed"):
        rows = db.scrape_list(library_id=lid or None, status="failed")
        queued = 0
        for r in rows:
            b = library.by_id(r.get("book_id"))
            if b and scrape.enqueue(b, force=True, reason="retry").get("queued"):
                queued += 1
        total = len(rows)
    else:
        res = scrape.enqueue_library(lid or None, force=force)
        total, queued = int(res.get("total") or 0), int(res.get("queued") or 0)
    started = scrape.start()
    scrape.wake()
    activity_log.log(activity_log.ACTION_SCRAPE, lid or "全部书库",
                     activity_log.STATUS_OK,
                     detail=f"{'强制重新' if force else ''}刮削：排队 {queued} / 共 {total}",
                     source="api")
    return {"ok": True, "queued": queued, "total": total, "started": started}


@app.post("/api/scrape/verify")
def api_scrape_verify(library_id: str = ""):
    """校验副本是否还在：缺失 → 标记「待确认」，源不在 → 标记「孤本」。

    ⚠️ **只标记、不处置** —— 不删源文件、不自动重建（用户空闲时在页面上确认）。
    """
    res = scrape.verify(str(library_id or "").strip() or None)
    return {"ok": True, **res}


@app.post("/api/scrape/{bid}/resolve")
def api_scrape_resolve(bid: str, payload: dict = Body(default=None)):
    """对某本书执行用户显式处置（删原文件 / 保留 / 重建 / 清理副本）。

    这是**唯一**能把降级状态（待确认 / 孤本）带回已出版的入口。
    """
    action = str((payload or {}).get("action") or "").strip()
    if action not in scrape.ACTIONS:
        raise HTTPException(400, "未知处置动作")
    res = scrape.resolve(bid, action)
    if not res.get("ok"):
        raise HTTPException(400, str(res.get("error") or "处置失败"))
    return res


# ---- 同名冲突（book_id 撞车）修复（第 13 期）----
# ``book_id`` 由 basename 派生（见 core/library.py），于是「A 库有三体.epub、B 库也有
# 三体.epub」会撞上同一个 id：进度 / 批注 / 评分只有一份，``library.by_id`` 会抛
# ``BookIdConflict``，详情页与进度接口都打不开那本书。入库侧新产生的冲突已被
# `library_rules` 拦掉，但**老库里可能已经躺着**这种数据（拦截是第 13 期才补的），
# 所以这个「清单 + 一键改名」的修复入口是必需的，不是可选的。

@app.get("/api/library-conflicts")
def api_library_conflicts():
    """同名冲突清单：按 ``book_id`` 聚合，只留命中多本的组（跨库的排前面）。

    每组带 ``keep``（保留项）与每个待改名项的 ``suggest``（建议名），
    前端据此直接渲染表格、无需自己算一套建议名口径。
    """
    groups = library.id_conflicts()
    return {
        "groups": groups, "total": len(groups),
        "cross_library": len([g for g in groups if g["cross_library"]]),
        "libraries": [{"id": l["id"], "name": l["name"]} for l in library.libraries()],
    }


@app.post("/api/library-conflicts/apply")
def api_library_conflicts_apply(payload: dict = Body(...)):
    """执行改名修复（**真改磁盘**，逐条独立，一条失败不影响其余）。

    与其它工具同一范式：先看清单（已带建议名）、再应用，应用只认前端回传的
    ``{old, new, library_id}`` 条目。改名会换 ``book_id``，关联数据一并搬
    （见 ``fileops.apply_conflict_rename``）。
    """
    try:
        return fileops.apply_conflict_rename((payload or {}).get("items"))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---- 迁移（预览 / 计划 / 执行 / 回滚 / 门禁）----

@app.get("/api/library-migrations/preview")
def api_mig_preview(targets: str = ""):
    """待迁移概览。``targets`` 传 JSON（如 ``{"comic": "comic-2"}``）用于指定同类多库时的目标。"""
    t: dict = {}
    if targets.strip():
        try:
            parsed = json.loads(targets)
            if not isinstance(parsed, dict):
                raise ValueError
            t = parsed
        except Exception:
            raise HTTPException(400, "targets 必须是 JSON 对象")
    return migrate.preview(t)


@app.post("/api/library-migrations/plan")
def api_mig_plan(payload: dict = Body(None)):
    """生成/复用迁移批次（**只写台账，不搬文件**）。"""
    targets = (payload or {}).get("targets")
    return migrate.plan(targets if isinstance(targets, dict) else None)


@app.post("/api/library-migrations/apply")
def api_mig_apply(payload: dict = Body(...)):
    """执行迁移批次（**真移文件**；逐条独立，一条失败不影响其余）。"""
    bid = str((payload or {}).get("batch_id") or "").strip()
    if not bid:
        raise HTTPException(400, "缺少 batch_id")
    try:
        return migrate.execute(bid)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/library-migrations/rollback")
def api_mig_rollback(payload: dict = Body(None)):
    """一键回滚（默认最近一次迁移批次）。"""
    bid = str((payload or {}).get("batch_id") or "").strip() or migrate.last_batch("move")
    if not bid:
        raise HTTPException(400, "没有可回滚的批次")
    try:
        return migrate.rollback(bid)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/library-migrations/batches")
def api_mig_batches():
    return {"items": migrate.pending_batches(), "gate": migrate.gate_state()}


@app.post("/api/library-migrations/dismiss")
def api_mig_dismiss(payload: dict = Body(None)):
    """「暂不迁移」：记下来，之后不再每次启动阻塞提示。"""
    return {"ok": True, "gate": migrate.dismiss(str((payload or {}).get("note") or ""))}


@app.post("/api/library-migrations/reset-gate")
def api_mig_reset_gate():
    """让启动提示重新出现（管理页 / 设置页用）。"""
    return {"ok": True, "gate": migrate.reset_gate()}


# ---- 跨库移动（用户点选：可选目标库 / 预检 / 计划 / 执行 / 回滚）----
# 与上面的「自动归库」共用 core/migrate.py 里同一台机器（manifest 批次 / 逐条独立 /
# remap / 回滚），但**入口刻意分开**：自动归库的批次槽位（``last_batch("move")``）与
# 门禁是第 10 期定下的，用户的点选移动不去占用它，两边的回滚也不会互相按错批次。
#
# 全部走 POST：选择集可能几十本、book_id 里带 ``$`` 与哈希，塞进 query string 迟早
# 撞长度上限；这组接口没有缓存需求，用 body 传更省事。

def _book_move_ids(payload: dict) -> list:
    """请求体里的 ``book_ids`` → 去重保序的字符串列表（空 / 非法一律 400）。"""
    ids = (payload or {}).get("book_ids")
    if not isinstance(ids, list):
        raise HTTPException(400, "book_ids 必须是数组")
    out: list = []
    seen: set = set()
    for x in ids:
        s = str(x or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    if not out:
        raise HTTPException(400, "没有选中的书")
    return out


def _book_move_dst(payload: dict) -> str:
    """请求体里的目标库 id，立即校验存在性（不存在是客户端错误，400）。"""
    dst = str((payload or {}).get("dst_library_id") or "").strip()
    if not dst or not library.get_library(dst):
        raise HTTPException(400, "目标书库不存在")
    return dst


@app.post("/api/book-move/targets")
def api_book_move_targets(payload: dict = Body(...)):
    """**可选的目标库**清单（含相容判定与理由）—— 前端据此置灰并原样显示原因。

    理由由 :func:`migrate.compat_reason` 给出，与 ``/plan`` 拒绝时用的是同一句话：
    前端置灰说的原因与后端真拒绝的原因不会两样。
    """
    return migrate.move_targets(_book_move_ids(payload))


@app.post("/api/book-move/preflight")
def api_book_move_preflight(payload: dict = Body(...)):
    """逐本预检：「能不能搬 / 为什么不能 / 副本会去哪」。**只读**，正常一律 200。

    这里**不**因为「某本不相容」而报错 —— 预检的职责就是把逐本的理由如实列出来给用户看
    （让他去掉那一本或换个库）。真正不许发生的事由 ``/plan`` 拦（见下）。
    """
    ids = _book_move_ids(payload)
    dst = _book_move_dst(payload)
    try:
        return migrate.move_preview(ids, dst, (payload or {}).get("decisions"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/book-move/plan")
def api_book_move_plan(payload: dict = Body(...)):
    """落成批次（只写台账，不搬文件）。

    **相容闸门在这里翻 400**：请求里只要混进一本进不去这个库的书，整批拒绝、不落行 ——
    不「悄悄搬能搬的那几本」，否则用户会以为全搬好了。前端把不相容的库置灰是体验，
    这道闸门才是契约（库扫描白名单决定文件在那个库里**根本不出现在书目中**，
    不是半可见，所以放过去就是把书搬没了）。
    """
    ids = _book_move_ids(payload)
    dst = _book_move_dst(payload)
    decisions = (payload or {}).get("decisions")
    try:
        pv = migrate.move_preview(ids, dst, decisions)
    except ValueError as e:
        raise HTTPException(400, str(e))
    bad = [i for i in pv["items"] if i.get("blocked_kind") == "compat"]
    if bad:
        raise HTTPException(400, f"{len(bad)} 本不能进「{pv['dst_library_name']}」："
                                 f"{bad[0]['reason']}")
    try:
        return migrate.move_plan(ids, dst, decisions)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/book-move/apply")
async def api_book_move_apply(payload: dict = Body(...)):
    """执行批次（**真移文件**）：立刻返回 ``task_id``，搬运在后台跑，前端照旧轮询任务行。

    不引入 SSE：进度就是「已完成 / 总数」两个真值，任务表足够表达。
    """
    bid = str((payload or {}).get("batch_id") or "").strip()
    if not bid:
        raise HTTPException(400, "缺少 batch_id")
    try:
        s = migrate.move_summary(bid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if s["direction"] != migrate.DIR_BOOKMOVE:
        # 自动归库的批次有它自己的执行入口（书库管理页）；从这里执行会把两套语义混起来
        raise HTTPException(400, "这个批次不是跨库移动，请到「书库管理」执行")
    tid = uuid.uuid4().hex
    db.task_create(tid, "bookmove", f"移动到「{s['dst_library_name']}」",
                   detail=f"{s['src_library_name']} → {s['dst_library_name']} · {s['total']} 本")
    db.task_prune()
    asyncio.create_task(_run_book_move(tid, bid, s["total"]))
    return {"task_id": tid, "batch_id": bid}


def _book_move_progress(tid: str, total: int):
    """逐本进度回调：每搬完一条就把 ``done/total`` 的真实比例写进任务行。

    回调在**工作线程**里跑（``asyncio.to_thread``），写库走 ``db`` 的锁 —— 与刮削工作线程
    同一套既有做法，不是为了这个功能新开的口子。
    """
    def cb(done: int, total_now: int, name: str) -> None:
        db.task_update(tid, progress=round(done * 100.0 / max(1, total_now), 1),
                       detail=f"正在移动：{name}")
    return cb


async def _run_book_move(tid: str, batch_id: str, total: int):
    db.task_update(tid, status="running", progress=0.0)
    try:
        res = await asyncio.to_thread(
            migrate.execute, batch_id,
            on_row=_book_move_progress(tid, total), watcher=WATCHER)
    except Exception as e:
        db.task_update(tid, status="failed", progress=100.0, error=str(e))
        return
    # 只报真值：搬了几本、副本跟没跟过来、跳过了几本 —— 三项都是 execute 数出来的
    parts = [f"移动 {res['moved']} 本"]
    if res["copies"]:
        parts.append(f"副本随迁 {res['copies']} 本")
    if res["copies_left"]:
        parts.append(f"副本留在原库 {res['copies_left']} 本")
    if res["skipped"]:
        parts.append(f"跳过 {res['skipped']} 本")
    if res["failed"]:
        parts.append(f"失败 {res['failed']} 本")
    notice = "、".join(parts)
    if res["notes"]:
        notice = f"{notice}；{res['notes'][0]['note']}"
    if res["failed"]:
        err = (res["errors"] or [{}])[0].get("error") or "未知原因"
        db.task_update(tid, status="failed", progress=100.0, notice=notice,
                       error=f"{res['failed']} 本没搬成：{err}")
        return
    # 刻意**不写 result**：任务行在有 result 时会渲染成「下载」按钮，而移动没有产物可下
    db.task_update(tid, status="done", progress=100.0, notice=notice)


@app.post("/api/book-move/rollback")
def api_book_move_rollback(payload: dict = Body(None)):
    """一键撤回本次移动（不传 batch_id 则取最近一次跨库移动批次）。

    同步执行：回滚要马上把「文件回来了没 / 副本回来了没」如实答出来，中途状态对用户没有
    意义。搬回的量级与搬过去相同，都是本地 rename（跨卷时才退化为复制）。
    """
    bid = (str((payload or {}).get("batch_id") or "").strip()
           or migrate.last_batch(migrate.DIR_BOOKMOVE))
    if not bid:
        raise HTTPException(400, "没有可回滚的移动批次")
    try:
        s = migrate.move_summary(bid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if s["direction"] != migrate.DIR_BOOKMOVE:
        raise HTTPException(400, "这个批次不是跨库移动")
    try:
        return migrate.rollback(bid, watcher=WATCHER)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/book-move/batches")
def api_book_move_batches(limit: int = 10):
    """最近的跨库移动批次 —— 书架的「撤销本次移动」条用它（带 real 计数）。"""
    return {"items": migrate.move_batches(limit)}


# ---------------- 收藏夹（用户自建，持久化于 SQLite）----------------

@app.get("/api/collections")
def api_collections():
    items = db.list_collections()
    for it in items:
        bid = it.get("first_book_id")
        b = library.by_id(bid) if bid else None
        it["first_book_has_cover"] = bool(b and b.get("has_cover"))
    return {"items": items}


@app.post("/api/collections")
def api_create_collection(payload: dict = Body(...)):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "收藏夹名称不能为空")
    try:
        cid = db.create_collection(name)
    except Exception:
        raise HTTPException(409, "同名收藏夹已存在")
    return {"id": cid, "name": name}


@app.get("/api/collections/{cid}")
def api_collection_detail(cid: int):
    c = db.get_collection(cid)
    if not c:
        raise HTTPException(404, "收藏夹不存在")
    books = [b for bid in db.collection_book_ids(cid) if (b := library.by_id(bid))]
    return {"id": c["id"], "name": c["name"], "books": books}


@app.delete("/api/collections/{cid}")
def api_delete_collection(cid: int):
    db.delete_collection(cid)
    return {"ok": True}


@app.patch("/api/collections/{cid}")
def api_rename_collection(cid: int, payload: dict = Body(...)):
    """重命名收藏夹（第 47 期：收藏夹总览行内重命名用）。"""
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "收藏夹名称不能为空")
    try:
        ok = db.update_collection(cid, name)
    except Exception:
        # UNIQUE(name) 冲突：同名收藏夹已存在
        raise HTTPException(409, "同名收藏夹已存在")
    if not ok:
        raise HTTPException(404, "收藏夹不存在")
    return {"ok": True, "id": cid, "name": name}


@app.post("/api/collections/{cid}/books")
def api_collection_add(cid: int, payload: dict = Body(...)):
    if not db.get_collection(cid):
        raise HTTPException(404, "收藏夹不存在")
    bid = str(payload.get("book_id") or "")
    if not library.by_id(bid):
        raise HTTPException(404, "书籍不存在")
    db.add_book_to_collection(cid, bid)
    return {"ok": True}


@app.delete("/api/collections/{cid}/books/{bid}")
def api_collection_remove(cid: int, bid: str):
    db.remove_book_from_collection(cid, bid)
    return {"ok": True}


@app.get("/api/books/{bid}/collections")
def api_book_collections(bid: str):
    """某本书已归入的收藏夹 id 列表（详情页「加入收藏」用）。"""
    return {"items": db.collections_of_book(bid)}


# ---------------- 自定义智能书架 ----------------
# 规则存储在后端、求值在前端（书单整体下发，筛选不必再打接口）。
# 字段/操作白名单在这里与前端 lib/smartScope.ts 各留一份，改动需两边同步。

SCOPE_FIELDS = {
    "title", "author", "series", "publisher", "language",
    "tag", "format", "status", "stars", "year",
    # 第 37 期补的两个数值字段：侧栏那 5 条内置智能书架下线之后，「最近添加」「有批注」
    # 这两个视图**只能**靠规则重建，所以字段必须补齐（否则是能力净损失）。
    #   · `annotations` = 批注数（`at_least 1` 就是「有批注」）
    #   · `added`       = 入库天数（距今天数，`at_most 30` 就是「最近 30 天入库」）
    "annotations", "added",
}
SCOPE_OPS = {
    "title": {"contains", "not_contains", "equals"},
    "author": {"contains", "not_contains", "equals"},
    "series": {"contains", "not_contains", "equals"},
    "publisher": {"contains", "not_contains", "equals"},
    "language": {"contains", "not_contains", "equals"},
    "tag": {"contains", "not_contains", "equals"},
    "format": {"equals"},
    "status": {"equals"},
    "stars": {"at_least", "at_most"},
    "year": {"at_least", "at_most"},
    "annotations": {"at_least", "at_most"},
    "added": {"at_least", "at_most"},
}


def _check_rules(rules) -> list:
    """结构校验：非空数组、字段在白名单、操作与字段匹配。原样返回干净的三元组列表。"""
    if not isinstance(rules, list) or not rules:
        raise HTTPException(400, "rules 必须为非空数组")
    out = []
    for r in rules:
        if not isinstance(r, dict):
            raise HTTPException(400, "规则必须是对象")
        field, op = r.get("field"), r.get("op")
        value = str(r.get("value") or "")
        if field not in SCOPE_FIELDS:
            raise HTTPException(400, f"未知规则字段：{field}")
        if op not in SCOPE_OPS[field]:
            raise HTTPException(400, f"字段 {field} 不支持操作 {op}")
        out.append({"field": field, "op": op, "value": value})
    return out


@app.get("/api/smart-scopes")
def api_smart_scopes():
    out = []
    for s in db.list_scopes():
        try:
            rules = json.loads(s["rules"])
        except (ValueError, TypeError):
            rules = []
        out.append({**s, "rules": rules})
    return {"items": out}


@app.post("/api/smart-scopes")
def api_create_smart_scope(payload: dict = Body(...)):
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name 不能为空")
    rules = _check_rules(payload.get("rules"))
    match = payload.get("match") or "all"
    if match not in ("all", "any"):
        raise HTTPException(400, "match 必须是 all 或 any")
    return db.create_scope(name, json.dumps(rules, ensure_ascii=False), match)


@app.put("/api/smart-scopes/{sid}")
def api_update_smart_scope(sid: int, payload: dict = Body(...)):
    if not db.get_scope(sid):
        raise HTTPException(404, "智能书架不存在")
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name 不能为空")
    rules = _check_rules(payload.get("rules"))
    match = payload.get("match") or "all"
    if match not in ("all", "any"):
        raise HTTPException(400, "match 必须是 all 或 any")
    return db.update_scope(sid, name, json.dumps(rules, ensure_ascii=False), match)


@app.delete("/api/smart-scopes/{sid}")
def api_delete_smart_scope(sid: int):
    if not db.delete_scope(sid):
        raise HTTPException(404, "智能书架不存在")
    return {"ok": True}


# ---------------- 偏好模式 / 设备（按设备的偏好同步）----------------
# 语义（与前端 stores/prefSync.ts 对齐）：
#   · payload 是**不透明 JSON**，后端只做浅校验（顶层块名白名单 + 每块为对象 + 64KB 上限）；
#   · 「应用模式」= 把模式 payload **拷贝**到设备 → 之后设备独立演进，改模式本体不影响它；
#   · 删模式只把引用设备的 active_profile_id 置空（来源标记），设备配置不动；
#   · 设备上报（PUT）不写活动日志（每次启动都发生，无审计价值），只有模式变更写。

PREFS_BLOCKS = {"reader", "pdf", "comic", "audio", "appearance", "cover", "shelf"}
PREFS_MAX_BYTES = 64 * 1024
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _check_device_id(device_id: str) -> str:
    did = str(device_id or "").strip()
    if not _DEVICE_ID_RE.match(did):
        raise HTTPException(400, "设备 id 非法")
    return did


def _check_payload(raw) -> str:
    """浅校验并返回 JSON 字符串。

    刻意**不做字段级深校验**：偏好字段随功能演进（本期才加了 PDF/漫画），
    深校验会导致「前端加一个偏好字段就得改后端，且老数据被拒」—— 两端耦死。
    payload 内不含敏感值（LLM api_key 在 config.yaml，不在此处）。
    """
    if not isinstance(raw, dict) or not raw:
        raise HTTPException(400, "payload 必须是非空对象")
    unknown = sorted(k for k in raw if k not in PREFS_BLOCKS)
    if unknown:
        raise HTTPException(400, f"未知的偏好块：{', '.join(unknown)}")
    for k, v in raw.items():
        if not isinstance(v, dict):
            raise HTTPException(400, f"偏好块 {k} 必须是对象")
    text = json.dumps(raw, ensure_ascii=False)
    if len(text.encode("utf-8")) > PREFS_MAX_BYTES:
        raise HTTPException(413, f"偏好数据超过 {PREFS_MAX_BYTES // 1024} KB 上限")
    return text


def _load_payload(text) -> dict:
    try:
        data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _profile_out(row: dict) -> dict:
    return {**row, "payload": _load_payload(row.get("payload"))}


def _device_out(row: dict) -> dict:
    return {**row, "payload": _load_payload(row.get("payload"))}


# ---- 模式 ----

@app.get("/api/prefs/profiles")
def api_pref_profiles():
    return {"items": [_profile_out(p) for p in db.list_profiles()]}


@app.post("/api/prefs/profiles")
def api_pref_profile_create(payload: dict = Body(...)):
    name = str((payload or {}).get("name") or "").strip()[:64]
    if not name:
        raise HTTPException(400, "name 不能为空")
    text = _check_payload((payload or {}).get("payload"))
    row = db.create_profile(name, text)
    activity_log.log(activity_log.ACTION_PREFS, name, activity_log.STATUS_OK,
                     detail="新建模式", source="api")
    return _profile_out(row)


@app.put("/api/prefs/profiles/{pid}")
def api_pref_profile_update(pid: int, payload: dict = Body(...)):
    if not db.get_profile(pid):
        raise HTTPException(404, "模式不存在")
    name = str((payload or {}).get("name") or "").strip()[:64]
    if not name:
        raise HTTPException(400, "name 不能为空")
    text = _check_payload((payload or {}).get("payload"))
    row = db.update_profile(pid, name, text)
    activity_log.log(activity_log.ACTION_PREFS, name, activity_log.STATUS_OK,
                     detail="更新模式（已应用该模式的设备不受影响）", source="api")
    return _profile_out(row)


@app.delete("/api/prefs/profiles/{pid}")
def api_pref_profile_delete(pid: int):
    res = db.delete_profile(pid)
    if not res["deleted"]:
        raise HTTPException(404, "模式不存在")
    activity_log.log(activity_log.ACTION_PREFS, f"模式 #{pid}", activity_log.STATUS_OK,
                     detail=f'删除模式，{res["detached_devices"]} 台设备解除引用（设备配置不变）',
                     source="api")
    return {"ok": True, **res}


# ---- 设备 ----

@app.get("/api/prefs/devices")
def api_pref_devices():
    return {"items": [_device_out(d) for d in db.list_devices()]}


@app.get("/api/prefs/devices/{device_id}")
def api_pref_device(device_id: str):
    """取本设备记录。不存在 → 404：前端据此判断「新设备」，用本机配置去创建。"""
    did = _check_device_id(device_id)
    row = db.get_device(did)
    if not row:
        raise HTTPException(404, "设备未登记")
    return _device_out(row)


@app.put("/api/prefs/devices/{device_id}")
def api_pref_device_upsert(device_id: str, payload: dict = Body(...)):
    """设备上报配置（也用于首次登记）。

    `active_profile_id` **不传即保留原值**（推送配置时不该顺手清掉来源标记）；
    显式传 null / "" 才清空。
    """
    did = _check_device_id(device_id)
    body = payload or {}
    name = str(body.get("name") or "").strip()[:64]
    text = _check_payload(body.get("payload"))
    if "active_profile_id" in body:
        raw = body.get("active_profile_id")
        pid = None if raw in (None, "") else int(raw)
        if pid is not None and not db.get_profile(pid):
            raise HTTPException(400, "active_profile_id 指向的模式不存在")
        row = db.upsert_device(did, name, text, active_profile_id=pid)
    else:
        row = db.upsert_device(did, name, text)
    return _device_out(row)


@app.post("/api/prefs/devices/{device_id}/apply/{pid}")
def api_pref_device_apply(device_id: str, pid: int):
    """把模式**拷贝**到该设备（快照语义：之后设备独立演进，改模式本体不影响它）。"""
    did = _check_device_id(device_id)
    prof = db.get_profile(pid)
    if not prof:
        raise HTTPException(404, "模式不存在")
    prev = db.get_device(did) or {}
    row = db.upsert_device(did, prev.get("name") or "", prof.get("payload") or "{}",
                           active_profile_id=int(pid))
    return _device_out(row)


@app.delete("/api/prefs/devices/{device_id}")
def api_pref_device_delete(device_id: str):
    did = _check_device_id(device_id)
    if not db.delete_device(did):
        raise HTTPException(404, "设备不存在")
    return {"ok": True}


# ---------------- 阅读字体（上传 / 列表 / 分发）----------------
# 本项目是单用户部署：上游的「阅读字体（每用户，上限 50）」与「服务端字体（上限 200）」
# 在这里是**同一份库** —— 两个设置页读写同一组接口，上限取服务端口径。

@app.get("/api/fonts")
def api_fonts():
    return fonts.list_fonts()


@app.post("/api/fonts")
async def api_upload_font(file: UploadFile = File(...)):
    """上传字体。分块读取并限大小（超限 413），与其它上传接口同一口径。"""
    data = await _read_capped(file, fonts.MAX_FONT_BYTES)
    try:
        item = fonts.save_font(file.filename or "font.ttf", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    activity_log.log(activity_log.ACTION_FONT, item["id"], activity_log.STATUS_OK,
                     detail=f'{item["name"]}（{item["format"]}）', size=item["size"], source="upload")
    return item


@app.delete("/api/fonts/{fid}")
def api_delete_font(fid: str):
    if not fonts.delete_font(fid):
        raise HTTPException(404, "字体不存在")
    activity_log.log(activity_log.ACTION_FONT, fid, activity_log.STATUS_OK, detail="删除", source="api")
    return {"ok": True}


@app.get("/api/fonts/{fid}/file")
def api_font_file(fid: str):
    """分发字体文件。@font-face 的 src 指向这里（用 ?token= 鉴权，见 _MEDIA_TOKEN_PATHS）。"""
    p = fonts.font_path(fid)
    if not p:
        raise HTTPException(404, "字体不存在")
    media = {".ttf": "font/ttf", ".otf": "font/otf",
             ".woff": "font/woff", ".woff2": "font/woff2"}.get(p.suffix.lower(), "application/octet-stream")
    # 字体内容不会变（改了就是新文件），长缓存安全
    return FileResponse(p, media_type=media, headers={"Cache-Control": "public, max-age=86400"})


# ---------------- 阅读时长（会话上报）----------------

@app.post("/api/books/{bid}/session")
def api_record_session(bid: str, payload: dict = Body(...)):
    """阅读器前台计时后上报一段会话（秒）。仅接受合理范围，避免脏数据。"""
    try:
        seconds = float(payload.get("seconds", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "seconds 必须为数字")
    if seconds <= 0 or seconds > 86400:
        raise HTTPException(400, "seconds 超出合理范围")
    if not library.by_id(bid):
        raise HTTPException(404, "书籍不存在")
    db.add_session(bid, seconds)
    return {"ok": True}


# ---------------- 数据统计 ----------------

@app.get("/api/stats")
def api_stats(
    days: int = Query(28, ge=7, le=365),
    top: int = Query(8, ge=1, le=50),
    library_id: str = Query(""),
):
    """统计聚合。days 控制节奏图窗口（dashboard 用默认 28，统计页可传 7/28/90）；
    top 控制 Top 榜长度（统计页可展开到 50）。

    ``library_id`` 第 30 期新增：**空串 = 全部书库**（默认，输出与加该参数之前逐字节
    一致）；给了库 id 就只统计该库。未知库 = 空库，不 404（与 `/api/duplicates`
    的 `library_id: str = ""` 同一条惯例）。阅读会话没有库维度，按「书属于哪个库」判。
    """
    return stats.overview(days, top, library_id)


@app.get("/api/browse-counts")
def api_browse_counts(library_id: str = Query("")):
    """侧栏「浏览」组的三计数：作者 / 系列 / 批注（第 34 期）。

    **刻意不塞进 `/api/stats`**：那个接口的既有键有测试钉住、只增不删，
    而这个计数要 60 秒节流（统计接口不能缓存，否则切库/改数据后页面就是旧的）。

    ``library_id`` 空串 = 全部书库（侧栏用这个 —— 作者 / 系列 / 批注三页目前都是跨库的，
    计数必须跨库才对得上）；浏览页传当前库，取该库自己的数字。
    未知库 → 空集合（全 0），**不 404**，与 `/api/stats` / `/api/reading-activity` 同惯例。
    """
    return browse_counts.counts(library_id)


@app.get("/api/reading-activity")
def api_reading_activity(
    library_id: str = Query(""),
    year: int = Query(None),
    limit: int = Query(120, ge=1, le=500),
):
    """阅读活动：贡献热力图（按日阅读分钟）+ 时间轴（会话/批注/成就合并）。

    第 31 期新增。``library_id`` 空串 = 全部书库（与 ``/api/stats`` 同惯例）；
    ``year`` 过滤热力图年份（None = 不过滤）；``limit`` 限制时间轴条数。
    空库时 heatmap.days / timeline.events 均为空列表，不补假数据。
    """
    return activity.reading_activity(library_id, year, limit)


# ---------------- 应用设置（服务端持久化 → settings.json）----------------
# 与上游 BookOrbit 的 settings 一致：设置存服务端、前端读写。
# 只暴露**真正生效**的配置键（见 config.DEFAULTS 与 detect / watcher / network 的读取处）；
# output.format 目前固定 epub，故只做只读展示，不开放编辑。

EDITABLE: dict = {
    "chapter_detection": {"mode", "context_lines", "fallback"},
    "traditionalize": None,  # None = 标量键，直接取值
    "output": {"format", "layout"},
    "naming": {"pattern", "scope"},
    "llm": {"api_key", "base_url", "model"},
    "watcher": {
        "enabled", "interval", "recursive", "settle_seconds", "stable_rounds",
        "copy_non_txt", "process_existing", "max_retries", "ignore",
    },
    "network": {"max_retries", "host_replace"},
    "download": {"enabled", "public_only"},
    # retention 是嵌套块（第 52 期）：与 integrations 同口径，整块取值，
    # 免得将来往留存策略里加键时还要再改一次白名单。
    "logging": {"dir", "max_entries", "retention"},
    "upload": {"max_bytes", "max_source_rules_bytes"},
    "achievements": {"enabled"},
    "opds": {"enabled", "expose"},
    "koreader": {"enabled", "username", "key"},
    # 整块覆盖：三家服务的字段各不相同，逐键白名单只会让新增字段时漏改
    "integrations": {"hardcover", "readwise", "storygraph"},
    # 元数据抓取：顶层子键白名单（`fields` 这类嵌套结构不再逐层校验 ——
    # 它们的形状由前端页面保证，后端只在应用时逐字段判定合法性）。
    # 注意 `None` 是「标量/整块取值」的意思（见 _sanitize_config），这里**刻意不用 None**，
    # 免得将来有人往前端配置里塞任意键。
    # ⚠️ 第 35 期起 `custom_fields` **不在白名单里**了（自定义字段改为 DB 里的定义 + 按书值）。
    #    顺带的好处：保存端点是段级合并，而不在白名单里的子键会被 _sanitize_config 丢掉 ——
    #    所以下一次保存设置就会把盘上残留的旧键自然清掉。
    "metadata_fetch": {
        "enabled", "sources", "limit", "threshold", "fields", "auto_on_import",
        "genre_blocklist", "googlebooks_api_key", "authors",
        # 第 57 期：另三家的密钥（与 core/metasources 注册表的 key_field 对应）
        "hardcover_api_token", "comicvine_api_key", "aladin_ttbkey",
    },
    # Komga 兼容服务端：开关 + Basic 用户名 + 可选 API Key
    # `expose` = 全局默认「书库是否对客户端暴露」（每库可在书库管理里覆写）
    "komga": {"enabled", "username", "api_key", "expose"},
    # 多书库：跨库策略开关（库实体本身存 SQLite，不走 config）
    "libraries": {"auto_migrate"},
    # 阅读状态口径（第 40 期）：全站「在读 / 已读完」判定的**全局默认值**。
    # 每库可在「书库管理 → 每库设置」覆写（走 lib_settings），这里只管全局。
    # ⚠️ 值域 0–100（`percent` 类型，**不是** number 的 0–1）。越界不在这里拦 ——
    #    `lib_settings._pct` 读时一律回落默认值，与「手改坏 config 不该把统计弄挂」同口径。
    "reading": {"started_threshold", "finished_threshold"},
}

# api_key 掩码：前端回显该值即表示「不修改」
_KEY_MASK = "••••••••"

# 允许的输出格式：epub 必产；mobi/azw3 需 Calibre 派生
FORMAT_CHOICES = ("epub", *ebook_convert.SUPPORTED)


def _flatten_overrides(data: dict, prefix: str = "") -> list:
    """把覆盖层展开成点号键列表，便于界面提示「哪些键被覆盖了」。"""
    out: list = []
    for k, v in (data or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.extend(_flatten_overrides(v, f"{key}."))
        else:
            out.append(key)
    return out


def _backup_config() -> str:
    """把当前 config.yaml 备份到 BACKUP_DIR；返回备份文件名（无可备份时为空串）。

    文件名带**微秒**：同一秒内的多次保存（或「还原前先备份」）不会互相覆盖 ——
    否则还原时可能先把源备份覆盖掉，导致「还原无效」。
    """
    if not config.CONFIG_FILE.is_file():
        return ""
    try:
        config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1e6) % 1000000:06d}"
        dst = config.BACKUP_DIR / f"config-{stamp}.yaml"
        shutil.copy2(config.CONFIG_FILE, dst)
        return dst.name
    except Exception:
        return ""


def _sanitize_config(payload: dict) -> dict:
    """按白名单裁剪前端提交的配置，避免写入任意键。"""
    out: dict = {}
    for key, fields in EDITABLE.items():
        if key not in payload:
            continue
        val = payload[key]
        if fields is None:
            out[key] = val
            continue
        if not isinstance(val, dict):
            continue
        picked = {k: v for k, v in val.items() if k in fields}
        if picked:
            out[key] = picked
    return out


def _apply_watcher_config():
    """把最新配置热更新到监听器（间隔 / 递归 / 忽略规则 / 启停）。"""
    if WATCHER is None:
        return
    cfg = config.load_config()
    w = cfg.get("watcher") or {}
    WATCHER.cfg = cfg
    try:
        if w.get("interval"):
            WATCHER.interval = float(w["interval"])
        if "recursive" in w:
            WATCHER.recursive = bool(w["recursive"])
        if "copy_non_txt" in w:
            WATCHER.copy_non_txt = bool(w["copy_non_txt"])
        if w.get("ignore"):
            WATCHER.ignore = list(w["ignore"])
        if "max_retries" in w:
            WATCHER.max_retries = max(0, int(w["max_retries"]))
    except Exception:
        pass
    enabled = bool(w.get("enabled", True))
    try:
        if enabled and not WATCHER.is_running():
            WATCHER.start()
        elif not enabled and WATCHER.is_running():
            WATCHER.stop()
    except Exception:
        pass


@app.get("/api/config")
def api_get_config():
    cfg = config.load_config()
    llm = dict(cfg.get("llm") or {})
    has_key = bool((llm.get("api_key") or "").strip())
    llm["api_key"] = _KEY_MASK if has_key else ""
    return {
        "config": {
            "chapter_detection": cfg.get("chapter_detection") or {},
            "traditionalize": bool(cfg.get("traditionalize", False)),
            "output": cfg.get("output") or {},
            "llm": {**llm, "has_key": has_key},
            "watcher": cfg.get("watcher") or {},
            "network": cfg.get("network") or {},
            "download": cfg.get("download") or {},
            "logging": cfg.get("logging") or {},
            # 注意：这里是**硬编码键列表**，不随 EDITABLE 自动同步 ——
            # 新增可写配置项时，EDITABLE 与本列表都要加，否则会出现「能写进 settings.json 但读不回来」。
            "naming": cfg.get("naming") or {},
            "upload": cfg.get("upload") or {},
            "achievements": cfg.get("achievements") or {},
            "opds": cfg.get("opds") or {},
            # koreader.key 是「密码的 MD5」，等同凭据 —— 一律不回显（与 llm.api_key 同约定）。
            # ⚠️ 硬编码键列表：新增可写配置项时这里也要加，否则「能写进 settings.json 但读不回来」。
            "koreader": {
                "enabled": bool((cfg.get("koreader") or {}).get("enabled")),
                "username": str((cfg.get("koreader") or {}).get("username") or ""),
                "key": _KEY_MASK if ((cfg.get("koreader") or {}).get("key") or "").strip() else "",
            },
            # 三家外部服务的凭据——同样一律掩码（等同凭据，明文回显没有意义只有风险）
            "integrations": _mask_integrations(cfg.get("integrations") or {}),
            # 元数据抓取：只有 API Key 需要掩码，其余是普通配置
            "metadata_fetch": _mask_metadata_fetch(cfg.get("metadata_fetch") or {}),
            # Komga 兼容服务端：api_key 是凭据 → 掩码
            "komga": {
                "enabled": bool((cfg.get("komga") or {}).get("enabled")),
                "username": str((cfg.get("komga") or {}).get("username") or "admin"),
                "api_key": _KEY_MASK if str((cfg.get("komga") or {}).get("api_key") or "").strip() else "",
                "has_api_key": bool(str((cfg.get("komga") or {}).get("api_key") or "").strip()),
                "expose": bool((cfg.get("komga") or {}).get("expose", True)),
            },
            # 多书库：跨库策略开关（库实体本身存 SQLite，走 /api/libraries）
            "libraries": {
                "auto_migrate": bool((cfg.get("libraries") or {}).get("auto_migrate")),
            },
            # 阅读状态口径的全局默认值（第 40 期）。每库生效值另走
            # `GET /api/reading-thresholds?library_id=`（含覆写合并），不在这里算。
            "reading": cfg.get("reading") or {},
        },
        "overrides": config.load_overrides(),
        "overridden": _flatten_overrides(config.load_overrides()),
        "config_file": str(config.CONFIG_FILE),
        "settings_file": str(config.SETTINGS_FILE),
        "backup_dir": str(config.BACKUP_DIR),
        "capabilities": {"ebook_convert": ebook_convert.capability()},
    }


@app.put("/api/config")
def api_put_config(payload: dict = Body(...)):
    patch = _sanitize_config(payload or {})
    if not patch:
        raise HTTPException(400, "没有可保存的配置项")

    fmt = str(((patch.get("output") or {}).get("format")) or "").strip().lower()
    if fmt and fmt not in FORMAT_CHOICES:
        raise HTTPException(400, "输出格式仅支持 " + " / ".join(FORMAT_CHOICES))

    # 上传上限必须是正整数。拒绝 0 / 负数 / 非数字 —— 否则「限 0」会被误读成「无限制」，
    # 正好把这次要修的风险又放回去。
    up = patch.get("upload")
    if isinstance(up, dict):
        for key in ("max_bytes", "max_source_rules_bytes"):
            if key not in up:
                continue
            try:
                val = int(up[key])
            except (TypeError, ValueError):
                raise HTTPException(400, "上传上限必须是整数（字节）")
            if val <= 0:
                raise HTTPException(400, "上传上限必须大于 0")
            up[key] = val

    ov = config.load_overrides()
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(ov.get(k), dict):
            ov[k] = {**ov[k], **v}
        else:
            ov[k] = v

    # api_key 为掩码 / 空 → 沿用现有值，避免「回显即覆盖」
    llm_ov = ov.get("llm")
    if isinstance(llm_ov, dict):
        key = (llm_ov.get("api_key") or "").strip()
        if key in ("", _KEY_MASK):
            llm_ov.pop("api_key", None)
            if not llm_ov:
                ov.pop("llm", None)

    config.save_overrides(ov)
    _apply_watcher_config()
    # 第 52 期：留存策略在日志模块里有 5 秒缓存，配置一改就必须失效 ——
    # 否则刚开启留存，页面上的「存盘情况」仍按旧值显示未启用。
    activity_log.invalidate_retention_cache()
    return {"ok": True, "overrides": ov}


@app.post("/api/cache/clear")
def api_clear_cache():
    """清空缓存目录（AI 分章缓存 + 监听状态）。

    ⚠️ **跳过回收目录**：``fileops.recycle_dir()`` 就位于 CACHE_DIR 内部，而原实现
    对 CACHE_DIR 下每个子目录无脑 ``shutil.rmtree`` —— 也就是「清空缓存」会顺手把
    回收站一起删掉。而「重复书籍 / 缺失资源」两个工具页明确向用户承诺
    「不是真删，移入回收目录，随时可以人工找回」，清一次缓存就把这个承诺作废了。
    那属于数据丢失，不属于缓存清理，因此这里显式跳过。
    """
    removed = 0
    recycle = fileops.recycle_dir()
    try:
        for f in config.CACHE_DIR.iterdir():
            try:
                if f.resolve() == recycle.resolve():
                    continue          # 回收站保留，它有自己的清理入口（/api/maintenance/recycle/clear）
                if f.is_dir():
                    shutil.rmtree(f)
                else:
                    f.unlink()
                removed += 1
            except Exception:
                continue
    except Exception:
        pass
    return {"ok": True, "removed": removed, "preserved": str(recycle)}


# ---------------- 维护页（对应上游 Maintenance 页）----------------
# 上游分组为 UPLOADS / IMPORT / RECOMMENDATIONS / ACHIEVEMENTS / UPDATES。
# 本项目能真实落地的只有「上传上限」与「目录/回收站/索引」这几项，其余保持明确未支持。

def _dir_usage(d) -> dict:
    """目录占用（文件数 + 总字节）。目录不存在或无权限时返回 0，不抛错。"""
    n, total = 0, 0
    try:
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            n += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    except Exception:
        pass
    return {"files": n, "bytes": total}


@app.get("/api/maintenance")
def api_maintenance():
    """维护页的**只读**总览。

    刻意不在这里做任何写操作：页面据此渲染，具体动作各走自己的 POST 接口，
    避免「打开页面就顺手改了东西」。
    """
    recycle = fileops.recycle_dir()
    cache = _dir_usage(config.CACHE_DIR)
    rec = _dir_usage(recycle)
    return {
        "upload": {
            "max_bytes": _upload_limit("max_bytes"),
            "max_source_rules_bytes": _upload_limit("max_source_rules_bytes"),
        },
        "overridden": _flatten_overrides(config.load_overrides()),
        "dirs": {
            "input": {"path": str(config.INPUT_DIR), **_dir_usage(config.INPUT_DIR)},
            "output": {"path": str(config.OUTPUT_DIR), **_dir_usage(config.OUTPUT_DIR)},
            # 缓存目录的统计**扣掉回收站**，否则同一批字节会在两个卡片里各算一次
            "cache": {"path": str(config.CACHE_DIR), "files": cache["files"] - rec["files"],
                      "bytes": cache["bytes"] - rec["bytes"]},
            "backups": {"path": str(config.BACKUP_DIR), **_dir_usage(config.BACKUP_DIR)},
            "recycle": {"path": str(recycle), **rec},
        },
        "library": {"books": len(library.books())},
        "capabilities": {"ebook_convert": ebook_convert.capability()},
    }


@app.post("/api/maintenance/library/rebuild")
def api_rebuild_library():
    """重建书库索引：清缓存后强制重扫 OUTPUT_DIR（只读操作，不改任何文件）。"""
    library.invalidate()
    items = library.books(force=True)
    return {"ok": True, "books": len(items)}


@app.post("/api/maintenance/recycle/clear")
def api_clear_recycle():
    """清空回收目录。

    这是**真删**、不可恢复 —— 回收站本身已是最后一道防线，清空它需要用户在界面上
    明确确认。有意的破坏性操作，因此单独一个入口，不与「清缓存」混在一起。
    """
    d = fileops.recycle_dir()
    removed, freed = 0, 0
    try:
        for p in list(d.rglob("*")):
            if not p.is_file():
                continue
            try:
                freed += p.stat().st_size
                p.unlink()
                removed += 1
            except OSError:
                continue
    except Exception:
        pass
    activity_log.log(activity_log.ACTION_RECYCLE, "回收站", activity_log.STATUS_OK,
                     detail=f"清空回收站：删除 {removed} 个文件，释放 {_human_size(freed)}",
                     source="api")
    return {"ok": True, "removed": removed, "freed": freed}


# ---------------- 成就（单用户口径）----------------
# 目录与判定全在 core/achievements.py：目录是数据、进度实时算、只解锁不回退。

@app.get("/api/achievements")
def api_achievements():
    """成就总览：逐条进度 + 解锁态 + 分组汇总。

    ⚠️ 这个 GET **会顺带解锁**达标项。在 GET 里做写操作不常见，但这里是自然语义：
    「进度已达成」本身就不需要用户再点一次确认，且解锁只增不退、幂等。
    """
    return achievements.evaluate()


@app.post("/api/achievements/backfill")
def api_achievements_backfill():
    """重算全部成就（对应上游 Maintenance 页的 ``Backfill achievements``）。

    语义即「重算」：会清空解锁记录再按当前数据重新判定，**解锁时间被重置为此刻**。
    """
    return achievements.backfill()


# ---------------- 孤儿记录（引用了已不存在的书的行）----------------
# 上游 Maintenance 页把这类东西叫 orphans。本项目的对应物**不是**「孤儿封面目录」
# （封面在 EPUB 内部，没有独立目录），而是数据库里指向已消失书籍的行：
# 书从 OUTPUT_DIR 移走后，progress / annotations / reading_sessions / collection_items
# 里仍留着它 —— 界面上再也走不到，却一直占着库。

def _orphan_refs() -> dict:
    """各表里**真正的**孤儿 book_id：``{表名: [book_id]}``。

    ⚠️ 第 37 期新增的第二道判据：「**书所属的库已经不存在**」的行不算孤儿。
    那之前书库表为空会自动播一条默认库，所以「书目为空」≈「书真没了」；现在没有
    默认库了，用户可以一个库都不建、也可以把库移除登记 —— 那时它的书只是**界面上
    看不见**，文件和进度 / 批注都还在原地。漏掉这道判据，「清空全部书库 → 点清理
    孤儿」就是一次不可恢复的数据大清洗。

    ``book_id`` 形如 ``库$哈希``（见 `library._book_id`）；没有 ``$`` 的是第 17 期
    库维度化之前的旧 id，无法归属到任何库，按老口径处理（不在书目里就算孤儿）。
    """
    valid = {b["id"] for b in library.books()}
    try:
        lib_ids = {str(l.get("id") or "") for l in library.libraries()}
    except Exception:
        lib_ids = set()
    refs = db.book_id_refs()
    return {
        name: [i for i in ids
               if i not in valid and str(i).split("$", 1)[0] in lib_ids]
        for name, ids in refs.items()
    }


def _orphans() -> dict:
    """算出各表中的孤儿 book_id（不改任何数据）。"""
    refs = db.book_id_refs()
    orphans = _orphan_refs()
    tables: dict = {}
    total = 0
    for name, ids in refs.items():
        bad = orphans.get(name) or []
        total += len(bad)
        tables[name] = {"books": len(bad), "sample": bad[:10]}
    return {"tables": tables, "total": total,
            "library_books": len(library.books())}


@app.get("/api/maintenance/orphans")
def api_orphans():
    """孤儿记录扫描结果（只读）。"""
    return _orphans()


@app.post("/api/maintenance/orphans/clear")
def api_orphans_clear():
    """清理孤儿记录。

    ⚠️ **不可恢复**，但这些行的主键是文件名派生的 book_id ——
    把同一个文件放回 OUTPUT_DIR，进度与批注会**重新关联上**。
    也就是说清掉的是「可能还有用」的数据，因此必须由用户在界面上显式确认。
    """
    orphans = _orphan_refs()          # 与扫描口径**同源**，绝不各写一份判据
    removed = db.delete_orphans(orphans)
    total = sum(removed.values())
    activity_log.log(activity_log.ACTION_RECYCLE, "孤儿记录", activity_log.STATUS_OK,
                     detail=f"清理孤儿记录：{total} 行（{removed}）", source="api")
    return {"ok": True, "removed": removed, "total": total}


# ---------------- 高级：直接编辑 config.yaml（含备份 / 还原 / 重置）----------------
# 与常规分区不同，这里改的就是 config.yaml 原文 —— 会丢失其注释与排版，
# 因此每次保存前自动备份到 BACKUP_DIR，并提供还原与重置。

@app.get("/api/config/raw")
def api_get_raw_config():
    path = config.CONFIG_FILE
    if not path.is_file():
        return {"exists": False, "text": "", "path": str(path), "mtime": 0, "size": 0}
    try:
        st = path.stat()
        return {
            "exists": True,
            "text": path.read_text(encoding="utf-8"),
            "path": str(path),
            "mtime": st.st_mtime,
            "size": st.st_size,
        }
    except Exception as e:
        raise HTTPException(500, f"读取失败：{e}")


@app.put("/api/config/raw")
def api_put_raw_config(payload: dict = Body(...)):
    text = str((payload or {}).get("text") or "")
    if not text.strip():
        raise HTTPException(400, "配置内容不能为空")
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        raise HTTPException(400, f"YAML 语法错误：{e}")
    if not isinstance(data, dict):
        raise HTTPException(400, "配置根节点必须是键值映射")

    backup = _backup_config()
    tmp = config.CONFIG_FILE.with_name("config.yaml.tmp")
    try:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(config.CONFIG_FILE)  # 原子替换
    except Exception as e:
        raise HTTPException(500, f"写入失败：{e}")
    _apply_watcher_config()
    return {"ok": True, "backup": backup}


@app.get("/api/config/backups")
def api_list_backups():
    out = []
    try:
        for f in sorted(config.BACKUP_DIR.glob("config-*.yaml"), reverse=True):
            st = f.stat()
            out.append({"name": f.name, "mtime": st.st_mtime, "size": st.st_size})
    except Exception:
        pass
    return {"items": out}


@app.post("/api/config/restore")
def api_restore_backup(payload: dict = Body(...)):
    name = str((payload or {}).get("name") or "")
    # 只允许 BACKUP_DIR 下的文件，拒绝路径分隔符（防目录穿越）
    if not name or "/" in name or "\\" in name or not name.endswith(".yaml"):
        raise HTTPException(400, "备份名不合法")
    src = config.BACKUP_DIR / name
    if not src.is_file():
        raise HTTPException(404, "备份不存在")
    backup = _backup_config()
    try:
        shutil.copy2(src, config.CONFIG_FILE)
    except Exception as e:
        raise HTTPException(500, f"还原失败：{e}")
    _apply_watcher_config()
    return {"ok": True, "restored": name, "backup": backup}


@app.post("/api/config/reset")
def api_reset_config():
    """重置为内置默认（由 config.DEFAULTS 序列化），重置前自动备份。"""
    backup = _backup_config()
    try:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(config.DEFAULTS, allow_unicode=True, sort_keys=False)
        config.CONFIG_FILE.write_text(text, encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"重置失败：{e}")
    _apply_watcher_config()
    return {"ok": True, "backup": backup}


@app.delete("/api/config/overrides")
def api_clear_overrides():
    """清空 settings.json 覆盖层 —— 让 config.yaml 里的值真正生效。"""
    try:
        if config.SETTINGS_FILE.is_file():
            config.SETTINGS_FILE.unlink()
    except Exception as e:
        raise HTTPException(500, f"清除失败：{e}")
    _apply_watcher_config()
    return {"ok": True}


# ---------------- 目录监听（input → output）----------------

def _get_watcher():
    """惰性构造监听器（未启用监听时，手动扫描 / 查状态也要能用）。"""
    global WATCHER
    if WATCHER is None:
        WATCHER = watcher_mod.FolderWatcher(cfg=config.load_config())
    WATCHER.on_scan = bookdock.note_scan      # 幂等绑定收书目录回调
    return WATCHER


@app.get("/api/watcher")
def api_watcher_status():
    return _get_watcher().status()


@app.post("/api/watcher/start")
def api_watcher_start():
    return {"ok": True, **_start_watcher(config.load_config()).status()}


@app.post("/api/watcher/stop")
def api_watcher_stop():
    if WATCHER is not None:
        WATCHER.stop()
    return {"ok": True, "running": False}


@app.post("/api/scan")
async def api_scan():
    """立即扫描一轮输入目录（不等下个轮询周期）。"""
    w = _get_watcher()
    w.cfg = config.load_config()
    return await asyncio.to_thread(w.scan_once)


# ---------------- 收书目录条目（Book Dock 五态流水线，第 7 期）----------------
# 列表接口在 GET 时**懒对账**（bookdock.payload → reconcile）：把投递目录里
# 尚未登记的文件补成 pending / needs_review，清掉文件已消失的悬空条目。
# 三个单项操作：rescan（重跑管线）/ ignore（登记运行时忽略）/ delete（移入回收目录）。

@app.get("/api/book-dock")
def api_book_dock(status: str = ""):
    w = _get_watcher()
    return bookdock.payload(w, status=(status or None))


@app.post("/api/book-dock/{item_id}/rescan")
def api_book_dock_rescan(item_id: str):
    try:
        item = bookdock.rescan(_get_watcher(), item_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "item": item}


@app.post("/api/book-dock/{item_id}/ignore")
def api_book_dock_ignore(item_id: str):
    try:
        item = bookdock.ignore(_get_watcher(), item_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "item": item}


@app.post("/api/book-dock/{item_id}/delete")
def api_book_dock_delete(item_id: str):
    try:
        res = bookdock.remove(_get_watcher(), item_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return res


# ---------------- 元数据完整度评分（B2）----------------
# 权重模型与分位聚合都在 core/metascore.py，这里只做透传。
# force=true 绕过 library 的 5 秒缓存重算 —— 对应页面上的「重新计算」。

@app.get("/api/metadata-score")
def api_metadata_score(force: bool = False):
    return metascore.payload(library.books(force=force))


# ---------------- 活动日志 ----------------

@app.get("/api/logs")
def api_logs(limit: int = Query(200, ge=1, le=5000), action: str = "",
             status: str = "", q: str = "", actor: str = ""):
    return {
        "items": activity_log.recent(limit=limit, action=action, status=status, q=q,
                                     actor=actor),
        "count": activity_log.count(),
        "dir": str(activity_log.log_dir()),
        # 操作者下拉的候选：**不受 actor 参数影响**（否则选中一个就切不回来）。
        "actors": activity_log.actors(),
        # 第 52 期：存盘情况（当前字节数 / 归档份数 / 生效的留存策略）—— 审计页据此展示。
        "storage": activity_log.storage_info(),
    }


def _notif_id(entry: dict) -> str:
    """通知条目的稳定 id。

    活动日志是追加写的 jsonl，条目**没有自增主键**，所以用
    「毫秒时间戳 + 动作 + 文件名 + 结果」取 sha1 前 16 位作为指纹。
    同一毫秒内「同文件同动作同结果」的重复条目会撞成同一 id —— 可接受：
    最坏也只是两条一模一样的事被当成同一条标了已读。
    """
    raw = "|".join(str(entry.get(k) or "") for k in ("ts_epoch", "action", "file", "status"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@app.get("/api/notifications")
def api_notifications(limit: int = Query(100, ge=1, le=1000)):
    """通知列表（新 → 旧），**在活动日志之上附加已读态**。

    不改变日志本身：已读只是围绕日志条目的一个标记表，
    清空日志时标记一并清掉（见 api_logs_clear）。
    """
    items = activity_log.recent(limit=limit)
    read_ids = db.notification_read_ids()
    for it in items:
        it["id"] = _notif_id(it)
        it["read"] = it["id"] in read_ids

    # `unread` 只数本页；顶栏浮层角标需要**全量**未读数，所以另算 `unread_total`。
    # 上限取 1000：日志内存缓冲是 2000 条（core/activity_log._memory），一半足以覆盖实际使用。
    total_unread = 0
    for entry in activity_log.recent(limit=1000):
        if _notif_id(entry) not in read_ids:
            total_unread += 1

    return {
        "items": items,
        "count": len(items),
        "unread": sum(1 for it in items if not it["read"]),
        "unread_total": total_unread,
    }


@app.post("/api/notifications/read")
def api_notifications_read(payload: dict = Body(...)):
    """标记已读。body：``{"ids": [...]}`` 或 ``{"all": true}``（最近 1000 条）。

    ⚠️ 这里刻意**不做**「自动清理过期标记」：列表一次只取 N 条，
    若按当前页裁剪标记，会把「标了 1000 条、列表只显示 100 条」时的另外 900 条误删。
    """
    payload = payload or {}
    if payload.get("all"):
        ids = [_notif_id(e) for e in activity_log.recent(limit=1000)]
    else:
        ids = [str(i) for i in (payload.get("ids") or [])]
    if not ids:
        raise HTTPException(400, "没有要标记的通知")
    return {"ok": True, "marked": db.mark_notifications_read(ids)}


@app.get("/api/logs/download")
def api_logs_download():
    p = activity_log.log_path()
    if not p.is_file():
        raise HTTPException(404, "暂无日志")
    return FileResponse(p, filename="activity.log")


@app.delete("/api/logs")
def api_logs_clear():
    """清空活动日志。日志没了，围绕它的已读标记也就没有意义，一并清掉。"""
    ok = activity_log.clear()
    cleared = db.clear_notifications_read()
    return {"ok": ok, "read_marks_cleared": cleared}


# ---------------- 工具页：实体管理 / 重排册号 / 重复书籍 / 缺失资源 ----------------
# 数据源统一是扫描 OUTPUT_DIR（见 core/library.py）；会改磁盘的动作一律
# 「先预览、再应用」，删除类走回收目录，全部写活动日志（见 core/fileops.py）。
# 业务逻辑都在 core/ 里，这里只做参数校验与胶水。
#
# 第 13 期起这几个工具支持**库维度**（工具页的「范围：当前库 / 全部书库」）。
# 约定：``library_id`` 为空 = 全部书库 = **与加参数之前完全一致**（零行为变化）。


def _opt_library(library_id) -> str:
    """工具页「范围」参数：空 = 全部书库；给了就校验存在（不存在 → 404）。

    返回 ``str``；调用 core 时一律写成 ``_opt_library(x) or None`` —— core 侧
    约定 ``None`` 才是「全部」，空串会被当成某个具体库从而筛出空结果。
    """
    lid = str(library_id or "").strip()
    if lid and not db.get_library(lid):
        raise HTTPException(404, "书库不存在")
    return lid


@app.get("/api/entities")
def api_entities(type_: str = Query("author", alias="type"), library_id: str = ""):
    if type_ not in ("author", "series"):
        raise HTTPException(400, "type 只能是 author 或 series")
    return library.entities(type_, _opt_library(library_id) or None)


@app.post("/api/entities/rename/preview")
def api_entity_rename_preview(payload: dict = Body(...)):
    type_ = str(payload.get("type") or "author")
    if type_ not in ("author", "series"):
        raise HTTPException(400, "type 只能是 author 或 series")
    try:
        return fileops.plan_entity_rename(
            type_,
            str(payload.get("from") or ""),
            str(payload.get("to") or ""),
            _opt_library(payload.get("library_id")) or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/entities/rename/apply")
def api_entity_rename_apply(payload: dict = Body(...)):
    """执行实体改名 / 合并：**只写服务端元数据**（``meta_override``），源文件名与字节原样。

    第 28 期起连同文件名都不改了：改名只剩「按命名规则重出版**副本**」一条落盘路径
    （``/api/naming/apply``），源文件名没有任何入口可改。

    契约 ``{type, from, to, library_id?}`` —— **不收 items**：要改哪些书由服务端按
    ``from`` 自己算（见 ``fileops.apply_entity_rename``），预览过期也改不错。
    列表 / 详情 / 实体聚合按新名字走（见 ``library._scan_once`` 的批量合并）。
    """
    type_ = str(payload.get("type") or "author")
    if type_ not in ("author", "series"):
        raise HTTPException(400, "type 只能是 author 或 series")
    try:
        return fileops.apply_entity_rename(
            type_,
            str(payload.get("from") or ""),
            str(payload.get("to") or ""),
            _opt_library(payload.get("library_id")) or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/entities/merge")
def api_entity_merge(payload: dict = Body(...)):
    """合并实体：与改名同构（源名 → 目标名），只返回预览，不直接改文件。"""
    type_ = str(payload.get("type") or "author")
    if type_ not in ("author", "series"):
        raise HTTPException(400, "type 只能是 author 或 series")
    try:
        return fileops.plan_merge(
            type_,
            str(payload.get("source") or ""),
            str(payload.get("target") or ""),
            _opt_library(payload.get("library_id")) or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/naming/preview")
def api_naming_preview(payload: dict = Body(default=None)):
    """按命名规则预览**副本名**的变化（只算不改）。

    ``{library_id?, pattern?, scope?}``：pattern / scope 缺省回退**该库的生效命名
    规则**（每库覆写 ?? 全局，见 ``core/lib_settings.config_for``）—— 没给
    ``library_id`` 时就是全局值，「设置 → 文件命名」保存的规则照旧直接生效。

    规则的口径只有一个：**成品目录里的副本名**（第 28 期起与批量重命名合并，
    源文件名不再有任何入口可改）。
    """
    p = payload or {}
    lid = _opt_library(p.get("library_id"))
    pattern = str(p.get("pattern") or "")
    if pattern.strip():
        try:
            pattern = fileops.validate_pattern(pattern)
        except ValueError as e:
            raise HTTPException(400, str(e))
    plan = scrape.plan_naming(lid or None, pattern, str(p.get("scope") or ""))
    if not plan["pattern"]:
        raise HTTPException(400, "命名规则为空：请先填写或保存一条规则")
    return plan


@app.post("/api/naming/apply")
async def api_naming_apply(payload: dict = Body(default=None)):
    """按**已保存**的命名规则重出版：只动硬链接副本，源文件只读。

    ``{library_id?, book_ids?}``。逐本重建副本（``scrape.resolve(bid,'rebuild')``
    即 ``process(bid, fetch=False)``，**不外呼**），旧副本移入回收站，不留双份。
    整批跑在 to_thread 里 —— 是同步文件 I/O，不能占着事件循环（同 mark_processed）。
    """
    p = payload or {}
    lid = _opt_library(p.get("library_id"))
    sub = p.get("book_ids") or None
    if sub is not None and not isinstance(sub, list):
        raise HTTPException(400, "book_ids 必须是数组")
    res = await asyncio.to_thread(scrape.republish, sub, lid or None)
    activity_log.log(activity_log.ACTION_SCRAPE, lid or "全部书库",
                     activity_log.STATUS_OK,
                     detail=f"按命名规则重出版：成功 {res['done']} / 共 {res['total']}"
                            f"（跳过 {res['skipped']}）",
                     source="api")
    return res


# ---------------- Komga 库布局（输出侧）----------------
# 把已入库的书整理成 Komga 认识的结构：``系列名/系列名 #N.ext``（见 core/komga.py）。
# 范式与其它改动型工具一致：**先预览、再应用** —— 预览只算不改，应用只认回传的
# ``{old, new}`` 条目并再校验一遍。这里**真改 basename**（布局整理就是搬文件），
# 所以应用时必须搬关联数据（db.remap_book_id），否则整理一次就把阅读进度丢了。

@app.post("/api/komga/layout/preview")
def api_komga_layout_preview():
    return fileops.plan_komga_layout()


@app.post("/api/komga/layout/apply")
def api_komga_layout_apply(payload: dict = Body(...)):
    try:
        return fileops.apply_komga_layout(payload.get("items"))
    except ValueError as e:
        raise HTTPException(400, str(e))



# ---------------- KOReader 进度互通（kosync 协议服务端）----------------
# ⚠️ 与 /opds 同理：**刻意不用 /api/ 前缀**（中间件对 /api/ 一律要 Bearer Token），
#    而 KOReader 发的是自定义头 x-auth-user / x-auth-key。
# 协议细节（partialMD5 采样点、XPointer、各响应字段）见 core/koreader.py 的模块注释。
#
# 客户端对响应的判定（据 kosync 插件源码）：register/authorize 只要 2xx 即成功、
# 失败读 body.message；推送进度时 **401 是唯一被识别的鉴权失败**（且不入重试队列）；
# 拉取进度时 body 里没有 percentage 就提示「No progress found」。

def _ko_cfg() -> dict:
    return config.load_config().get("koreader") or {}


def _ko_guard(request: Request) -> None:
    """校验 KOReader 凭据头（key = 密码的 MD5）。

    - 未启用 → 404：401 会让客户端反复重试并报认证错误，404 更贴近「没开这个功能」。
    - 未设密钥 → 401（客户端会提示认证失败，用户回到设置页设置）。
    """
    cfg = _ko_cfg()
    if not cfg.get("enabled"):
        raise HTTPException(404, "KOReader 同步未启用")
    stored = str(cfg.get("key") or "").strip().lower()
    if not stored:
        raise HTTPException(401, "尚未设置同步密钥")
    user = (request.headers.get("x-auth-user") or "").strip()
    key = (request.headers.get("x-auth-key") or "").strip().lower()
    if user != str(cfg.get("username") or "").strip() or not hmac.compare_digest(key, stored):
        raise HTTPException(401, "用户名或密码不正确")


@app.get("/koreader/healthcheck")
def ko_healthcheck():
    """kosync 客户端会先探这个（本项目不校验凭据，与官方实现一致）。"""
    return {"state": "OK"}


@app.get("/koreader/users/auth")
def ko_auth(request: Request):
    _ko_guard(request)
    return {"authorized": "OK"}


@app.post("/koreader/users/create")
def ko_create(request: Request, payload: dict = Body(...)):
    """客户端注册。

    本项目**不新建账号**（账号在「设置 → KOReader」里设定），只做兼容：
    凭据与已配置的一致 → 201（让客户端认为注册成功，继续走同步流程）；
    否则 402（kosync 语义：注册被拒）。
    """
    cfg = _ko_cfg()
    if not cfg.get("enabled"):
        raise HTTPException(404, "KOReader 同步未启用")
    stored = str(cfg.get("key") or "").strip().lower()
    user = str((payload or {}).get("username") or "").strip()
    key = str((payload or {}).get("password") or "").strip().lower()
    if stored and user == str(cfg.get("username") or "").strip() and hmac.compare_digest(key, stored):
        return JSONResponse({"message": "Account already exists"}, status_code=201)
    return JSONResponse(
        {"message": "注册被拒绝：账号请在 NovelForge 的「设置 → KOReader」中设置"},
        status_code=402,
    )


@app.put("/koreader/syncs/progress")
def ko_put_progress(request: Request, payload: dict = Body(...)):
    _ko_guard(request)
    doc = str((payload or {}).get("document") or "").strip().lower()
    row = db.find_koreader_doc(doc)
    if not row:
        raise HTTPException(404, "文档不在书库索引里：请先在「设置 → KOReader」扫描书库")
    locator, percent = koreader.to_nf(payload)
    db.set_progress(row["book_id"], locator, percent)
    return {"document": doc, "timestamp": int(time.time())}


@app.get("/koreader/syncs/progress/{document}")
def ko_get_progress(request: Request, document: str):
    _ko_guard(request)
    row = db.find_koreader_doc(document)
    if not row:
        raise HTTPException(404, "文档不在书库索引里")
    book = library.by_id(row["book_id"])
    if not book:
        raise HTTPException(404, "书已不在库中")
    prog = db.get_progress(row["book_id"]) or {}
    out = koreader.from_nf(book, prog)
    # KOReader 用 timestamp 与本机的翻页时间比较来决定要不要采用远端进度；
    # 没有记录（从没在本项目里读过）时给「现在」——刚拉到的就是最新状态，语义是对的。
    if not out.get("timestamp"):
        out["timestamp"] = int(time.time())
    out["document"] = str(document).strip().lower()
    return out


# ---- 管理接口（走 /api/，Bearer 鉴权）----

@app.get("/api/koreader")
def api_koreader_status():
    cfg = _ko_cfg()
    return {
        "enabled": bool(cfg.get("enabled")),
        "username": str(cfg.get("username") or ""),
        "has_key": bool(str(cfg.get("key") or "").strip()),
        "doc_count": len(db.list_koreader_docs()),
        "book_count": len(library.books()),
    }


@app.put("/api/koreader")
def api_koreader_save(payload: dict = Body(...)):
    """保存设置。``password`` 留空 = 不修改密钥；服务端只存 **md5(密码)**（协议本就如此）。"""
    cur = _ko_cfg()
    patch = {
        "enabled": bool((payload or {}).get("enabled")),
        "username": str((payload or {}).get("username") or "").strip() or "koreader",
        "key": str(cur.get("key") or "").strip(),
    }
    pw = str((payload or {}).get("password") or "")
    if pw and pw != _KEY_MASK:
        patch["key"] = hashlib.md5(pw.encode("utf-8")).hexdigest()
    if patch["enabled"] and not patch["key"]:
        raise HTTPException(400, "开启前请先设置同步密码")
    ov = config.load_overrides()
    ov["koreader"] = patch
    config.save_overrides(ov)
    return {"ok": True}


@app.post("/api/koreader/scan")
def api_koreader_scan():
    """重建文档索引（为每本书算 partialMD5）。书库改动后需重扫。"""
    # 多书库：按**各自的库根**建索引（partialMD5 与路径相关，用错根会把进度同步到错书）
    rows: list = []
    for lib in library.libraries():
        for root in _roots_of(lib):
            rows.extend(koreader.scan_books(library.books(lib["id"]), root))
    return {"ok": True, "scanned": db.replace_koreader_docs(rows)}


@app.get("/api/koreader/docs")
def api_koreader_docs():
    bs = {b["id"]: b for b in library.books()}
    out = []
    for d in db.list_koreader_docs():
        b = bs.get(d["book_id"]) or {}
        out.append({**d, "title": b.get("title") or "", "name": b.get("name") or ""})
    return {"items": out}


# ---------------- 外部服务集成（Hardcover / Readwise / StoryGraph）----------------
# 凭据存 settings.json 覆盖层，一律掩码回显、提交掩码 = 不修改。
# 目标都在**公网**（与 OPDS / KOReader 的内网相反），所以验证请求保留 httpx 默认的
# 系统代理行为 —— 用户很可能正需要靠代理访问（见 core/integrations.py 的注释）。
#
# ⚠️ **同步任务尚未实现**：把阅读状态/书评推到这些服务，先得做书籍匹配
#    （ISBN / 标题模糊匹配）再适配各家 GraphQL / REST 语义，是独立的一大块。
#    按执行约定「不做假交互」，这里**不放同步按钮** —— 一个点了没用的按钮比没有更糟。

_INTEGRATION_SERVICES = ("hardcover", "readwise", "storygraph")


def _mask_integrations(sec: dict) -> dict:
    """整块掩码：**凭据字段**有值给掩码、无值给空串（供 GET /api/config 回显）。

    ⚠️ 非凭据字段（第 52 期的 ``auto_push`` 布尔）必须**原样回显** ——
    否则配置页会把 `True` 当成「已设置的密钥」渲染成一串掩码。
    """
    out = {}
    for name in _INTEGRATION_SERVICES:
        cur = sec.get(name) or {}
        keys = set(_integration_field_keys(name))
        out[name] = {
            k: ((_KEY_MASK if str(v or "").strip() else "") if k in keys else bool(v))
            for k, v in cur.items()
        }
    return out


def _mask_metadata_fetch(sec: dict) -> dict:
    """元数据抓取的配置回显：**按注册表循环掩码所有密钥**，其余原样。

    第 57 期起密钥不止一个（Google Books / Hardcover / Comic Vine / Aladin），所以这里
    改成**跟着 `metasources.SOURCES[*].key_field` 走** —— 注册表加一家带 Key 的源，
    掩码与 `has_<键名>` 回显自动跟上，不会出现「前端渲染了输入框、后端却回显明文/漏掩」。
    """
    out = dict(sec or {})
    for field in sorted({metasources.key_field_of(s) for s in metasources.SOURCES} - {""}):
        has = bool(str(out.get(field) or "").strip())
        out[field] = _KEY_MASK if has else ""
        out[f"has_{field}"] = has
    # 兼容旧字段名（前端历史版本可能还在读），值等同于 googlebooks 那项
    out["has_googlebooks_key"] = bool(out.get("has_googlebooks_api_key"))
    return out


def _integration_field_keys(service: str) -> list:
    return [f["key"] for f in (integrations.spec(service).get("fields") or [])]


@app.get("/api/integrations")
def api_integrations():
    """三家的字段定义 + 当前状态。字段定义由后端给，前端不重复维护一份。"""
    cfg = config.load_config().get("integrations") or {}
    items = []
    for name in _INTEGRATION_SERVICES:
        meta = integrations.spec(name)
        cur = cfg.get(name) or {}
        keys = _integration_field_keys(name)
        items.append({
            "id": name,
            "label": meta.get("label") or name,
            "desc": meta.get("desc") or "",
            "fields": meta.get("fields") or [],
            "verify": bool(meta.get("verify")),
            "doc": meta.get("doc") or "",
            "note": meta.get("note") or "",
            # 第 52 期：同步能力。sync=False 的服务（StoryGraph）前端不渲染预览/同步按钮。
            "sync": bool(meta.get("sync")),
            "auto_push": bool(cur.get("auto_push")),
            # values 是掩码（用于显示「已设置」），has 是布尔（用于逻辑判断）
            "values": {k: (_KEY_MASK if str(cur.get(k) or "").strip() else "") for k in keys},
            "has": {k: bool(str(cur.get(k) or "").strip()) for k in keys},
        })
    return {"items": items}


@app.put("/api/integrations/{service}")
def api_integration_save(service: str, payload: dict = Body(None)):
    """保存凭据。提交掩码或空串（None）= 不修改该字段。"""
    if service not in _INTEGRATION_SERVICES:
        raise HTTPException(404, "未知服务")
    ov = config.load_overrides()
    cur = dict(((ov.get("integrations") or {}).get(service)) or {})
    for k in _integration_field_keys(service):
        v = (payload or {}).get(k)
        if v is None:
            continue
        v = str(v)
        if v == _KEY_MASK:      # 掩码 = 保持原值
            continue
        cur[k] = v.strip()
    # 第 52 期：自动推送开关（布尔，不是掩码字段，故单独处理；不传 = 保持原值）
    if "auto_push" in (payload or {}):
        cur["auto_push"] = bool((payload or {}).get("auto_push"))
    ov["integrations"] = {**(ov.get("integrations") or {}), service: cur}
    config.save_overrides(ov)
    return {"ok": True}


def _sync_auto_push(book_id: str, request: Request) -> None:
    """写入后触发外部服务同步（**旁路、默认关、失败不影响本次写入**）。

    操作者必须在**请求线程内**取好再交给后台线程 —— 新线程的 ContextVar 是空的，
    不传会把「谁做的」记成未记录。
    """
    sync.auto_push(book_id, base_url=str(request.base_url),
                   actor=activity_log.current_actor())


@app.post("/api/integrations/{service}/preview")
def api_integration_preview(service: str):
    """同步预览：**只算不改、零外呼**。

    Hardcover 侧的匹配要查对方库才知道有没有这本，所以预览给的是「本地待推条数」，
    匹配发生在同步时（结果里带跳过计数）。
    """
    if service not in _INTEGRATION_SERVICES:
        raise HTTPException(404, "未知服务")
    if not integrations.spec(service).get("sync"):
        raise HTTPException(400, "该服务不支持同步")
    return sync.preview(service)


@app.post("/api/integrations/{service}/sync")
def api_integration_sync(service: str, request: Request, payload: dict = Body(None)):
    """执行一次同步（**会向对方写入**）。未配置凭据 → 400 并说明原因。"""
    if service not in _INTEGRATION_SERVICES:
        raise HTTPException(404, "未知服务")
    if not integrations.spec(service).get("sync"):
        raise HTTPException(400, "该服务不支持同步")
    ids = (payload or {}).get("book_ids")
    book_ids = [str(x) for x in ids] if isinstance(ids, list) and ids else None
    return sync.run(service, book_ids, base_url=str(request.base_url),
                    actor=activity_log.current_actor())


@app.post("/api/integrations/{service}/test")
def api_integration_test(service: str, payload: dict = Body(None)):
    """真实连通性验证。

    body 里可带**尚未保存**的字段值（用户填完直接点验证，不必先保存）；
    没带的字段用已保存的值。
    """
    if service not in _INTEGRATION_SERVICES:
        raise HTTPException(404, "未知服务")
    creds = dict(((config.load_config().get("integrations") or {}).get(service)) or {})
    for k, v in (payload or {}).items():
        if str(v) and str(v) != _KEY_MASK:
            creds[k] = str(v)
    return integrations.verify(service, creds)


# ---------------- 元数据抓取与治理（第 5 期）----------------
# 与「先预览、再应用」同一范式：/plan 只算不改，/apply 只认前端回传的具体值。
#
# ⚠️ `/plan` 每本书都要对每个启用的源各发一次外呼 —— 全库一次跑完必然超时
#    （17 本 × 2 源 ≈ 34 次请求）。所以它**一次只处理传入的那几本**（默认 1 本，
#    上限 10 本），由前端逐本循环、逐本显示进度与结果。

@app.get("/api/metadata/sources")
def api_metadata_sources():
    """可用元数据源 + 当前启用情况（兼容端点；第 57 期起设置页改用 /providers）。"""
    mf = config.load_config().get("metadata_fetch") or {}
    active = mf.get("sources") or list(metasources.DEFAULT_ORDER)
    return {
        "items": [{**meta, "id": sid, "active": sid in active}
                  for sid, meta in metasources.SOURCES.items()],
        "enabled": bool(mf.get("enabled")),
        "has_googlebooks_key": bool(str(mf.get("googlebooks_api_key") or "").strip()),
    }


@app.get("/api/metadata/providers")
def api_metadata_providers():
    """提供商目录 + 启用 / 配置现状（第 57 期「提供商」页的唯一数据源）。

    出参形状对齐上游那页要的字段：分组、每组条目、`已启用 N/总数`、以及每个源的
    「是否已实现 / 是否需要设置 / 是否已配置」。**未实现的源照常列出但不给开关** ——
    目录本身是信息（用户能看到「这家还没接」），可点的开关才是承诺。

    `enabled` 的真值源仍是 `metadata_fetch.sources`（启用 = 在列表里，顺序即优先级）；
    本端点只做「注册表 + 配置」的聚合，不新开一份状态。
    """
    mf = config.load_config().get("metadata_fetch") or {}
    active = [s for s in (mf.get("sources") or list(metasources.DEFAULT_ORDER))
              if s in metasources.SOURCES]
    catalog = metasources.provider_catalog()
    items = []
    for meta in catalog:
        sid = meta["id"]
        key_field = meta.get("key_field") or ""
        has_key = bool(str(mf.get(key_field) or "").strip()) if key_field else False
        items.append({
            **meta,
            "active": sid in active,
            "order": (active.index(sid) + 1) if sid in active else 0,
            "has_config": has_key,
            # 「需要设置」= 需要 Key 但还没填。已实现的源即便 needs_config=False 也可能有
            # 可选的 Key（Google Books），那种情况归到「已配置/未配置」而不阻断使用。
            "needs_setup": bool(meta.get("needs_config")) and not has_key,
        })
    groups = {g: [i for i in items if i.get("group") == g] for g in metasources.GROUPS}
    return {
        "items": items,
        "groups": [{"name": g, "items": v} for g, v in groups.items() if v],
        "enabled": bool(mf.get("enabled")),
        "active_count": len(active),
        "total": len(items),
        "implemented_count": sum(1 for i in items if i.get("implemented")),
    }


@app.post("/api/metadata/probe")
def api_metadata_probe(payload: dict = Body(None)):
    """源连通性自检（真的外呼：点一次测一次，结果只回给这次请求）。"""
    mf = config.load_config().get("metadata_fetch") or {}
    wanted = (payload or {}).get("sources") or list(metasources.SOURCES)
    out = {}
    for sid in wanted:
        if sid not in metasources.SOURCES:
            continue
        key_field = metasources.key_field_of(sid)
        cfg = {"api_key": str(mf.get(key_field) or "")} if key_field else None
        # 需要 Key 却没填 ⇒ 直接如实回报，**不发外呼**（省一次注定失败的请求）
        if metasources.needs_key(sid) and not (cfg or {}).get("api_key"):
            out[sid] = {"ok": False, "message": "需要设置：尚未填写该来源的密钥", "ms": 0}
            continue
        out[sid] = metasources.probe(sid, cfg)
    return {"items": out}


@app.post("/api/metadata/plan")
def api_metadata_plan(payload: dict = Body(None)):
    """抓取预览（只算不改）。body: ``{names?: [...], limit?: n}``。"""
    p = payload or {}
    names = p.get("names") or []
    if not isinstance(names, list):
        raise HTTPException(400, "names 必须是数组")
    if len(names) > 10:
        raise HTTPException(400, "一次最多预览 10 本：每本都要外呼，多了会超时")
    limit = p.get("limit")
    try:
        return metafetch.plan(names=names or None, cfg=config.load_config(),
                              limit=int(limit) if limit else None)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"参数非法：{e}")


@app.post("/api/metadata/apply")
def api_metadata_apply(payload: dict = Body(...)):
    """应用抓取结果。body: ``{items: [{name, fields: {...}, cover: {url} | null}]}``。"""
    items = (payload or {}).get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "items 必须是非空数组")
    res = metafetch.apply(items, cfg=config.load_config())
    for a in res.get("applied", []):
        activity_log.log(
            activity_log.ACTION_METADATA, a["name"], activity_log.STATUS_OK,
            output=a["name"], source="api",
            detail=f"补全 {len(a['fields'])} 个字段" + ("，含封面" if a.get("cover") else ""),
        )
    for f in res.get("failed", []):
        activity_log.log(activity_log.ACTION_METADATA, f["name"], activity_log.STATUS_FAIL,
                         source="api", detail=f["error"])
    return res


# ---------------- Komga v1 兼容服务端（第 5 期）----------------
# 让第三方 Komga 客户端把本应用当成 Komga 服务器（协议细节见 core/komga_api.py）。
# 认证走 Basic / X-API-Key / 会话 cookie，由 komga_api.verify 负责；
# 中间件已对 `/api/v1/` 前缀放行（见 _auth_middleware）。
#
# ⚠️ **路由注册顺序**：FastAPI 按注册顺序匹配，所以 `/books/latest`、`/books/ondeck`
#    必须注册在 `/books/{book_id}` **之前**，否则 "latest" 会被当成 bookId 吞掉
#    （本项目在 `/api/books/export` 与 `/opds/all` 上踩过同一个坑）。

_KO_PAGE = Query(0, ge=0)
_KO_SIZE = Query(20, ge=1, le=500)
_KO_401 = {"WWW-Authenticate": 'Basic realm="Komga"'}


def _ko_guard(request: Request) -> str:
    """统一鉴权入口。未启用 → 404（401 会让客户端反复弹密码框）。"""
    try:
        return komga_api.verify(request)
    except komga_api.KomgaAuthError as e:
        if str(e) == "disabled":
            raise HTTPException(404, "Komga 兼容服务未启用")
        raise HTTPException(401, "凭据无效", headers=_KO_401)


def _ko_404(msg: str = "不存在"):
    raise HTTPException(404, msg)


def _ko_sorted(items: list, sort: str, default: str = "name") -> list:
    """`sort=field,asc|desc`。**不认识的字段按 default 排，不报错** ——
    客户端传的排序字段五花八门，为一个排序把整页打回失败不值得。"""
    field, _, direction = (sort or "").partition(",")
    field = field.strip() or default
    desc = direction.strip().lower() in ("desc", "descending")
    keys = {
        "name": lambda x: str(x.get("name") or "").lower(),
        "title": lambda x: str((x.get("metadata") or {}).get("title") or "").lower(),
        "createdDate": lambda x: str(x.get("created") or ""),
        "lastModifiedDate": lambda x: str(x.get("lastModified") or ""),
        "fileSize": lambda x: x.get("sizeBytes") or 0,
        "sizeBytes": lambda x: x.get("sizeBytes") or 0,
        "booksCount": lambda x: x.get("booksCount") or 0,
        "releaseDate": lambda x: str((x.get("metadata") or {}).get("releaseDate") or ""),
        "metadata.releaseDate": lambda x: str((x.get("metadata") or {}).get("releaseDate") or ""),
        "readProgress.lastModified": lambda x: str((x.get("readProgress") or {}).get("lastModified") or ""),
    }
    return sorted(items, key=keys.get(field) or keys[default], reverse=desc)


def _ko_read_filter(payload: dict):
    """把 Komga 的 SearchCondition 翻成过滤函数；``None`` 表示不过滤。

    **只支持最常见的几个条件**（libraryId / readStatus / mediaStatus / seriesId / tag / title），
    其余一概忽略 —— 宁可多返回，也不让客户端因为一个陌生的过滤条件整页失败
    （失败还很难排查：客户端只会显示「加载失败」）。
    """
    cond = (payload or {}).get("condition") or {}
    clauses = cond.get("allOf") or ([cond] if cond else [])
    # 第 40 期：readStatus 的三档也走配置阈值。过滤函数是**逐本**调用的，所以解析器
    # 在这里建一次、闭包捕获（见 komga_api.threshold_resolver）。
    th = komga_api.threshold_resolver()
    tests = []
    for cl in clauses:
        if not isinstance(cl, dict):
            continue
        if "libraryId" in cl:
            want = ((cl["libraryId"] or {}).get("in") or [])
            if want:
                wset = {str(x) for x in want}
                # 老客户端可能仍发兜底常量（单库时代的「就那一个库」）；第 37 期起没有
                # 默认库可对应，改成**展开成全部书库** —— 它想表达的就是「别筛」。
                if komga_api.LIBRARY_ID in wset:
                    wset.discard(komga_api.LIBRARY_ID)
                    wset.update(str(l.get("id") or "") for l in library.libraries())
                tests.append(lambda b, _w=wset: komga_api.book_library_id(b) in _w)
        if "readStatus" in cl:
            want = [str(s).upper() for s in ((cl["readStatus"] or {}).get("in") or [])]
            if want:
                def _read(b, _w=want, _th=th):
                    pct = float((db.get_progress(b["id"]) or {}).get("percent") or 0)
                    started, finished = komga_api.thresholds_of(_th, b)
                    st = ("READ" if pct >= finished
                          else ("IN_PROGRESS" if pct > started else "UNREAD"))
                    return st in _w
                tests.append(_read)
        if "mediaStatus" in cl:
            want = [str(s).upper() for s in ((cl["mediaStatus"] or {}).get("in") or [])]
            if want and "READY" not in want:
                tests.append(lambda b: False)
        if "seriesId" in cl:
            want = set((cl["seriesId"] or {}).get("in") or [])
            if want:
                tests.append(lambda b, _w=want: komga_api.series_id(
                    komga_api.series_name_of(b)) in _w)
        if "tag" in cl:
            want = [str(t).lower() for t in ((cl["tag"] or {}).get("in") or [])]
            if want:
                def _tag(b, _w=want):
                    have = [str(t).lower() for t in (b.get("tags") or [])]
                    return any(t in have for t in _w)
                tests.append(_tag)
        if "title" in cl:
            want = str((cl["title"] or {}).get("contains") or "").lower()
            if want:
                tests.append(lambda b, _w=want: _w in str(b.get("title") or "").lower())
    if not tests:
        return None
    return lambda b: all(t(b) for t in tests)


# ---- 按库过滤（第 15 期）----
# 多书库之后，客户端在库视图里选了某个库，看到的却仍是全部书库混在一起（系列侧甚至完全
# 忽略筛选条件）。这里把库维度接到 Komga 出口，口径照抄第 14 期的 OPDS 按库暴露：
# **默认等于今天的行为**（不传库 = 全部**可见**库），且可见性判定只有这一处。


def _ko_visible_libraries() -> list:
    """对 Komga 客户端可见的书库：库类型具备 ``komga`` 能力，**且开关开着**（第 22 期）。

    **有声书库天然不具备**（见 `features.FEATURES_BY_TYPE`）：Komga 没有音频模型，
    有声书落到客户端就是打不开的坏条目 —— 所以从**书库**这一层挡掉，而不是让每本书
    各自判断（口径只留一处，库类型改了会自动跟着变）。

    ``komga.expose`` 是**叠加的第二层**（每库覆写 ?? 全局），写法与第 14 期的
    ``_opds_visible_libraries`` 逐行同构：全局默认 True = 全部符合条件的库都暴露，
    与加这个开关之前的行为完全一致；关掉后该库对客户端就是「不存在」。
    """
    cfg = config.load_config()
    default = bool((cfg.get("komga") or {}).get("expose", True))
    out = []
    for lib in library.libraries():
        lid = str(lib.get("id") or "")
        if not features.allows_setting(str(lib.get("type") or "mixed"), "komga.expose"):
            continue                        # 库类型没这能力 → 覆写即便残留也不生效
        ov = lib_settings.overrides(lid).get("komga.expose")
        if not (default if ov is None else bool(ov)):
            continue
        out.append(lib)
    return out


def _ko_visible_ids() -> set:
    return {str(l.get("id") or "") for l in _ko_visible_libraries()}


def _ko_books(library_id=None) -> list:
    """Komga 视图下的书目：只含可见库；不给库时按可见库逐个取再合并。"""
    lid = str(library_id or "").strip()
    if lid:
        if lid not in _ko_visible_ids():
            return []                    # 不可见的库对客户端就是「没有」
        return library.books(library_id=lid)
    out = []
    for lib in _ko_visible_libraries():
        out.extend(library.books(library_id=str(lib.get("id") or "")))
    return out


def _ko_series_key(b: dict):
    """系列内排序键（与 `komga_api.grouped` 内部同一口径）。"""
    try:
        return (float(str(b.get("series_index") or "").strip() or 1e9),
                str(b.get("title") or ""))
    except ValueError:
        return (1e9, str(b.get("title") or ""))


def _ko_grouped(library_id=None) -> dict:
    """可见库范围内的 ``{系列名: [书…]}``。"""
    lid = str(library_id or "").strip()
    if lid:
        if lid not in _ko_visible_ids():
            return {}
        return komga_api.grouped(lid)
    out: dict = {}
    for lib in _ko_visible_libraries():
        for name, items in komga_api.grouped(str(lib.get("id") or "")).items():
            out.setdefault(name, []).extend(items)
    for items in out.values():           # 跨库同名系列合并后要重排一次
        items.sort(key=_ko_series_key)
    return out


def _ko_book(bid: str):
    """Komga 视图下按 id 取单本书：**不在可见库里的书对客户端等于不存在**（返回 ``None``）。

    不能直接返回 `library.by_id` 的结果 —— 关掉某库的「对 Komga 暴露」后，
    它的书不该还能靠 id 直连读到（那样开关只是把书从列表里藏起来，形同虚设）。
    """
    b = library.by_id(bid)
    if not b:
        return None
    return b if str(b.get("library_id") or "") in _ko_visible_ids() else None


def _ko_find_series(key: str):
    """在**可见库**范围内按系列 id / 名字找系列（找不到返回 ``None``）。

    与 `komga_api.find_series` 匹配规则相同（名字或 ``series_id`` 命中），
    但只遍历可见库 —— 关掉暴露的库，其系列的单系列地址也一并 404。
    """
    for sname, items in _ko_grouped().items():
        if sname == key or komga_api.series_id(sname) == key:
            return (sname, items)
    return None


def _ko_library_id_of(payload: dict) -> str:
    """从 Komga 的 SearchCondition 里取 libraryId（取第一个即可）。

    老客户端会发单库时代的兜底常量 `komga_api.LIBRARY_ID` —— 那个常量想表达的是
    「就那一个库」。第 37 期起没有默认库可对应，映射成**空串 = 全部可见书库**
    （与 `_ko_read_filter` 里「展开成全部书库」同一个口径）。
    """
    cond = (payload or {}).get("condition") or {}
    for cl in (cond.get("allOf") or ([cond] if cond else [])):
        if not isinstance(cl, dict) or "libraryId" not in cl:
            continue
        for raw in ((cl["libraryId"] or {}).get("in") or []):
            lid = str(raw or "").strip()
            if not lid:
                continue
            return "" if lid == komga_api.LIBRARY_ID else lid
    return ""


# ---- 认证 / 用户 ----

@app.post("/api/v1/login")
def ko_login(request: Request):
    """校验凭据 + 发会话 cookie（无状态签名）。204 是 Komga 的语义。"""
    user = _ko_guard(request)
    resp = Response(status_code=204)
    resp.set_cookie(komga_api.SESSION_COOKIE, komga_api.session_token(user),
                    httponly=True, samesite="lax")
    return resp


@app.post("/api/logout")
def ko_logout():
    resp = Response(status_code=204)
    resp.delete_cookie(komga_api.SESSION_COOKIE)
    return resp


@app.get("/api/v1/users/me")
def ko_me(request: Request):
    """客户端「测试连接」常调它。"""
    user = _ko_guard(request)
    return {
        "id": "1", "email": f"{user}@novelforge.local",
        "roles": ["ADMIN", "USER"], "labelsAllow": [], "labelsExclude": [],
        "sharedLibraries": [
            {"libraryId": lib["id"], "userId": "1", "role": "ADMIN"}
            for lib in library.libraries()
        ],
    }


# ---- 库 ----

@app.get("/api/v1/libraries")
def ko_libraries(request: Request):
    """客户端第一步就调它（多书库后**逐库**返回；有声书库不进 Komga）。"""
    _ko_guard(request)
    return [komga_api.library_dto(lib) for lib in _ko_visible_libraries()]


# ---- 系列（latest 必须先于 {series_id}）----

def _ko_series_page(page: int, size: int, sort: str, library_id: str = "") -> dict:
    """``library_id`` 为空 = 全部**可见**书库（与加参数前一致）。"""
    # 列表端点遍历**全部**系列 → 走轻量分层（不聚合），一次取全元数据行
    rows = db.all_series_meta()
    th = komga_api.threshold_resolver()      # 第 40 期：一次解析、逐系列复用（见 komga_api）
    items = [komga_api.series_dto(name, bs, series_meta.effective_light(name, rows.get(name) or {}),
                                  th)
             for name, bs in _ko_grouped(library_id).items()]
    return komga_api.paginate(_ko_sorted(items, sort, "name"), page, size)


@app.get("/api/v1/series")
def ko_series_get(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE,
                  sort: str = "", library_id: str = ""):
    """已弃用（1.19+ 推 `POST /series/list`），但**老客户端仍在用**，必须保留。

    ``library_id`` 为空 = 全部**可见**书库（与加参数前一致）。
    """
    _ko_guard(request)
    return _ko_series_page(page, size, sort, library_id)


@app.post("/api/v1/series/list")
def ko_series_list(request: Request, payload: dict = Body(None),
                   page: int = _KO_PAGE, size: int = _KO_SIZE, sort: str = ""):
    """筛选条件里的 ``libraryId`` 现在真的生效（此前 payload 被整个丢掉）。"""
    _ko_guard(request)
    return _ko_series_page(page, size, sort, _ko_library_id_of(payload))


@app.get("/api/v1/series/latest")
def ko_series_latest(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE,
                     library_id: str = ""):
    _ko_guard(request)
    rows = db.all_series_meta()
    th = komga_api.threshold_resolver()
    items = [komga_api.series_dto(n, bs, series_meta.effective_light(n, rows.get(n) or {}), th)
             for n, bs in _ko_grouped(library_id).items()]
    return komga_api.paginate(_ko_sorted(items, "lastModifiedDate,desc"), page, size)


@app.get("/api/v1/series/{series_id}")
def ko_series_one(request: Request, series_id: str):
    _ko_guard(request)
    found = _ko_find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    name, items = found
    # 单系列查询：完整分层（含成员书聚合），成本可接受
    return komga_api.series_dto(name, items, series_meta.effective(name),
                                komga_api.threshold_resolver())


@app.get("/api/v1/series/{series_id}/books")
def ko_series_books(request: Request, series_id: str, page: int = _KO_PAGE,
                    size: int = _KO_SIZE, sort: str = ""):
    _ko_guard(request)
    found = _ko_find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    name, items = found
    th = komga_api.threshold_resolver()
    dtos = [komga_api.book_dto(b, name, th) for b in items]
    return komga_api.paginate(_ko_sorted(dtos, sort, "name"), page, size)


@app.get("/api/v1/series/{series_id}/thumbnail")
def ko_series_thumb(request: Request, series_id: str):
    """系列封面 = 该系列**第一本有封面的书**的封面。"""
    _ko_guard(request)
    found = _ko_find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    _name, items = found
    for b in items:
        if b.get("has_cover"):
            return api_book_cover(b["id"])
    _ko_404("该系列没有可用封面")


# ---- 书籍（latest / ondeck 必须先于 {book_id}）----

def _ko_books_dto(sort: str = "", library_id: str = "") -> list:
    th = komga_api.threshold_resolver()      # 第 40 期：逐本构造 DTO，解析器必须只建一次
    return _ko_sorted([komga_api.book_dto(b, th=th) for b in _ko_books(library_id)], sort, "name")


@app.get("/api/v1/books")
def ko_books_get(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE,
                 sort: str = "", library_id: str = ""):
    """已弃用但老客户端在用（同系列）。

    ``library_id`` 为空 = 全部**可见**书库（与加参数前一致）。
    """
    _ko_guard(request)
    return komga_api.paginate(_ko_books_dto(sort, library_id), page, size)


@app.post("/api/v1/books/list")
def ko_books_list(request: Request, payload: dict = Body(None),
                  page: int = _KO_PAGE, size: int = _KO_SIZE, sort: str = ""):
    _ko_guard(request)
    bs = _ko_books()                     # 可见库范围内（有声书库不进 Komga）
    flt = _ko_read_filter(payload)
    if flt:
        bs = [b for b in bs if flt(b)]
    th = komga_api.threshold_resolver()
    items = _ko_sorted([komga_api.book_dto(b, th=th) for b in bs], sort, "name")
    return komga_api.paginate(items, page, size)


@app.get("/api/v1/books/latest")
def ko_books_latest(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE,
                    library_id: str = ""):
    _ko_guard(request)
    return komga_api.paginate(_ko_sorted(_ko_books_dto("", library_id),
                                         "lastModifiedDate,desc"), page, size)


@app.get("/api/v1/books/ondeck")
def ko_books_ondeck(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE):
    """待读：**系列里已有在读书**时，该系列的第一本未读书（Komga 的语义）。"""
    _ko_guard(request)
    th = komga_api.threshold_resolver()
    out = []
    for name, items in _ko_grouped().items():
        pcts = [float((db.get_progress(b["id"]) or {}).get("percent") or 0) for b in items]
        # 「在读」= 过了该书的开始阈值、且还没到它的读完阈值（第 40 期：口径随书所属库）
        fin = [komga_api.thresholds_of(th, b)[1] for b in items]
        sta = [komga_api.thresholds_of(th, b)[0] for b in items]
        if not any(s < p < f for p, s, f in zip(pcts, sta, fin)):
            continue
        nxt = next((b for b, p, f in zip(items, pcts, fin) if p < f), None)
        if nxt:
            out.append(komga_api.book_dto(nxt, name, th))
    return komga_api.paginate(out, page, size)


@app.post("/api/v1/series/{series_id}/read-progress")
def ko_series_mark_read(request: Request, series_id: str):
    """标记整个系列为**已读**（Komga 官方：``POST`` → 204，无 body）。

    **保留每本书的原位置、只把 percent 顶到 100** —— 「标已读」不该把读者送回第一页
    （见 `komga_api.mark_series_read`）。
    """
    _ko_guard(request)
    found = _ko_find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    komga_api.mark_series_read(found[1], completed=True)
    return Response(status_code=204)


@app.delete("/api/v1/series/{series_id}/read-progress")
def ko_series_mark_unread(request: Request, series_id: str):
    """标记整个系列为**未读**（Komga 官方：``DELETE`` → 204）。"""
    _ko_guard(request)
    found = _ko_find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    komga_api.mark_series_read(found[1], completed=False)
    return Response(status_code=204)


@app.get("/api/v1/books/{book_id}")
def ko_book_one(request: Request, book_id: str):
    _ko_guard(request)
    b = _ko_book(book_id) or _ko_404("书不存在")
    return komga_api.book_dto(b, th=komga_api.threshold_resolver())


@app.get("/api/v1/books/{book_id}/thumbnail")
def ko_book_thumb(request: Request, book_id: str):
    _ko_guard(request)
    if not _ko_book(book_id):
        _ko_404("书不存在")
    return api_book_cover(book_id)


@app.get("/api/v1/books/{book_id}/file")
def ko_book_file(request: Request, book_id: str):
    _ko_guard(request)
    b = _ko_book(book_id) or _ko_404("书不存在")
    path = library.root_of(b) / b["name"]
    if not path.is_file():
        _ko_404("文件不存在")
    return FileResponse(path, media_type="application/octet-stream",
                        filename=pathlib.PurePosixPath(b["name"]).name)


@app.get("/api/v1/books/{book_id}/pages")
def ko_book_pages(request: Request, book_id: str):
    _ko_guard(request)
    b = _ko_book(book_id) or _ko_404("书不存在")
    pages = komga_api.pages_for(b)
    if not pages:
        raise HTTPException(400, "该格式不支持页面流：请下载文件后本地阅读")
    return pages


@app.get("/api/v1/books/{book_id}/pages/{number}")
def ko_book_page(request: Request, book_id: str, number: int, convert: str = ""):
    _ko_guard(request)
    b = _ko_book(book_id) or _ko_404("书不存在")
    data, media = komga_api.page_image(b, number, convert)
    if not data:
        _ko_404("页不存在")
    return Response(content=data, media_type=media)


@app.get("/api/v1/books/{book_id}/manifest")
def ko_book_manifest(request: Request, book_id: str):
    _ko_guard(request)
    b = _ko_book(book_id) or _ko_404("书不存在")
    return Response(content=json.dumps(komga_api.manifest_for(b), ensure_ascii=False),
                    media_type="application/webpub+json")


@app.put("/api/v1/books/{book_id}/read-progress")
def ko_put_read_progress(request: Request, book_id: str, payload: dict = Body(None)):
    _ko_guard(request)
    b = _ko_book(book_id) or _ko_404("书不存在")
    locator, percent = komga_api.apply_read_progress(b, payload)
    db.set_progress(book_id, locator, percent)
    return Response(status_code=204)


@app.delete("/api/v1/books/{book_id}/read-progress")
def ko_delete_read_progress(request: Request, book_id: str):
    _ko_guard(request)
    if not _ko_book(book_id):
        _ko_404("书不存在")
    db.set_progress(book_id, 0, 0)
    return Response(status_code=204)


@app.patch("/api/v1/books/{book_id}/read-progress")
def ko_patch_read_progress(request: Request, book_id: str, payload: dict = Body(None)):
    """官方新客户端用 ``PATCH``（老客户端用 ``PUT``）—— 两者语义完全一致。"""
    return ko_put_read_progress(request, book_id, payload)


# ---- Collections（第 16 期：映射本项目的收藏夹，可写）----
# Komga 的 Collection 装的是**系列**，本项目收藏夹装的是 **book_id** → 成员先按书归到
# 各自系列再给出去。成员一律过 Komga 可见性过滤：有声书库的书不会从收藏夹漏进客户端。


def _ko_collection_groups(cid) -> dict:
    """收藏夹成员 → ``{系列名: [书…]}``（只保留对 Komga 可见的书）。"""
    visible = {str(b.get("id") or ""): b for b in _ko_books()}
    out: dict = {}
    for bid in db.collection_book_ids(cid):
        b = visible.get(str(bid or ""))
        if not b:
            continue                     # 越库 / 不进 Komga 的库里的书，直接跳过
        out.setdefault(komga_api.series_name_of(b), []).append(b)
    for items in out.values():
        items.sort(key=_ko_series_key)
    return out


def _ko_series_books(ids: list) -> list:
    """系列 id（或名字）列表 → 这些系列里的书；同一系列只算一次。"""
    out, seen = [], set()
    for sid in ids or []:
        found = _ko_find_series(str(sid))
        if not found:
            continue
        name, items = found
        if name in seen:
            continue
        seen.add(name)
        out.extend(items)
    return out


def _ko_collection_or_404(cid) -> dict:
    row = db.get_collection(int(cid))
    if not row:
        _ko_404("收藏夹不存在")
    return row


@app.get("/api/v1/collections")
def ko_collections(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE,
                   sort: str = ""):
    _ko_guard(request)
    items = [komga_api.collection_dto(r["id"], r["name"], r.get("created_at"),
                                      _ko_collection_groups(r["id"]))
             for r in db.list_collections()]
    return komga_api.paginate(_ko_sorted(items, sort, "name"), page, size)


@app.post("/api/v1/collections")
def ko_collection_create(request: Request, payload: dict = Body(None)):
    body = payload or {}
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "收藏夹名称不能为空")
    _ko_guard(request)
    try:
        cid = db.create_collection(name)
    except Exception:                    # noqa: BLE001 —— 靠 name 的 UNIQUE 撞库判重
        raise HTTPException(409, "同名收藏夹已存在") from None
    for b in _ko_series_books(body.get("seriesIds") or []):
        db.add_book_to_collection(cid, str(b.get("id") or ""))
    return komga_api.collection_dto(cid, name, time.time(), _ko_collection_groups(cid))


@app.get("/api/v1/collections/{cid}")
def ko_collection_one(request: Request, cid: int):
    _ko_guard(request)
    row = _ko_collection_or_404(cid)
    return komga_api.collection_dto(row["id"], row["name"], row.get("created_at"),
                                    _ko_collection_groups(cid))


@app.patch("/api/v1/collections/{cid}")
def ko_collection_rename(request: Request, cid: int, payload: dict = Body(None)):
    _ko_guard(request)
    row = _ko_collection_or_404(cid)
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(400, "收藏夹名称不能为空")
    try:
        if not db.update_collection(cid, name):
            _ko_404("收藏夹不存在")
    except Exception:                    # noqa: BLE001 —— 同上，重名撞 UNIQUE
        raise HTTPException(409, "同名收藏夹已存在") from None
    return komga_api.collection_dto(cid, name, row.get("created_at"),
                                    _ko_collection_groups(cid))


@app.delete("/api/v1/collections/{cid}")
def ko_collection_delete(request: Request, cid: int):
    _ko_guard(request)
    _ko_collection_or_404(cid)
    db.delete_collection(cid)
    return Response(status_code=204)


@app.get("/api/v1/collections/{cid}/series")
def ko_collection_series(request: Request, cid: int, page: int = _KO_PAGE,
                         size: int = _KO_SIZE):
    _ko_guard(request)
    _ko_collection_or_404(cid)
    rows = db.all_series_meta()
    th = komga_api.threshold_resolver()
    items = [komga_api.series_dto(n, bs, series_meta.effective_light(n, rows.get(n) or {}), th)
             for n, bs in _ko_collection_groups(cid).items()]
    return komga_api.paginate(_ko_sorted(items, "", "name"), page, size)


@app.put("/api/v1/collections/{cid}/series")
def ko_collection_replace_series(request: Request, cid: int, payload: dict = Body(None)):
    """**整体替换**（Komga 的语义）：先清空，再按给定的系列逐本加入。"""
    _ko_guard(request)
    row = _ko_collection_or_404(cid)
    db.clear_collection(cid)
    for b in _ko_series_books((payload or {}).get("seriesIds") or []):
        db.add_book_to_collection(cid, str(b.get("id") or ""))
    return komga_api.collection_dto(cid, row["name"], row.get("created_at"),
                                    _ko_collection_groups(cid))


@app.delete("/api/v1/collections/{cid}/series/{series_id}")
def ko_collection_remove_series(request: Request, cid: int, series_id: str):
    _ko_guard(request)
    _ko_collection_or_404(cid)
    found = _ko_find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    for b in found[1]:
        db.remove_book_from_collection(cid, str(b.get("id") or ""))
    return Response(status_code=204)


@app.get("/api/v1/collections/{cid}/thumbnail")
def ko_collection_thumb(request: Request, cid: int):
    """夹封面 = 成员里**第一本有封面**的书。"""
    _ko_guard(request)
    _ko_collection_or_404(cid)
    for items in _ko_collection_groups(cid).values():
        for b in items:
            if b.get("has_cover"):
                return api_book_cover(b["id"])
    _ko_404("该收藏夹没有可用封面")


@app.post("/api/v1/collections/{cid}/thumbnail")
@app.put("/api/v1/collections/{cid}/thumbnail")
@app.delete("/api/v1/collections/{cid}/thumbnail")
def ko_collection_thumb_unsupported(request: Request, cid: int):
    """自定义封面不做（夹封面一律取成员书的封面）——**明确报错**，不假装成功。"""
    _ko_guard(request)
    raise HTTPException(403, "不支持自定义收藏夹封面：封面取成员书的封面")


# ---- Readlists / Referential / 单库 / 上一本下一本 / analyze（第 16 期）----
# 这批端点的共同点：**客户端会来问**。没有对应概念的（Readlist）就诚实返回空，
# 而不是编造数据或让客户端撞 404 报错页。


def _ko_siblings(b: dict) -> list:
    """同系列的书（系列内已排好序）；取不到就退化成「只有自己」。"""
    found = _ko_find_series(komga_api.series_name_of(b))
    return list(found[1]) if found else [b]


def _ko_sibling(b: dict, offset: int):
    """系列内偏移 ``offset`` 本的邻居；没有就返回 ``None``。"""
    items = _ko_siblings(b)
    ids = [str(x.get("id") or "") for x in items]
    try:
        idx = ids.index(str(b.get("id") or ""))
    except ValueError:
        return None
    nxt = idx + offset
    return items[nxt] if 0 <= nxt < len(items) else None


@app.get("/api/v1/readlists")
def ko_readlists(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE):
    """本项目**没有阅读清单**这个概念 → 诚实返回空分页，不编造条目。"""
    _ko_guard(request)
    return komga_api.paginate([], page, size)


@app.get("/api/v1/readlists/{rid}")
def ko_readlist_one(request: Request, rid: str):  # noqa: ARG001 —— 任何 id 都不存在
    _ko_guard(request)
    _ko_404("本项目没有阅读清单")


@app.get("/api/v1/readlists/{rid}/books")
def ko_readlist_books(request: Request, rid: str,  # noqa: ARG001
                      page: int = _KO_PAGE, size: int = _KO_SIZE):
    _ko_guard(request)
    return komga_api.paginate([], page, size)


@app.post("/api/v1/readlists")
@app.post("/api/v1/readlists/import")
def ko_readlists_unsupported(request: Request):
    _ko_guard(request)
    raise HTTPException(403, "不支持阅读清单：本项目没有这个概念")


@app.get("/api/v1/referential")
def ko_referential(request: Request):
    """客户端启动时可能取的引用表（作者 / 系列 / 标签 …）。

    给**真实值**（基于对 Komga 可见的书目），字段一律齐全 —— 缺字段会让部分客户端崩。
    """
    _ko_guard(request)
    authors, series, tags, langs, pubs, years = set(), set(), set(), set(), set(), set()
    for b in _ko_books():
        if b.get("author"):
            authors.add(str(b["author"]).strip())
        if b.get("series"):
            series.add(str(b["series"]).strip())
        if b.get("language"):
            langs.add(str(b["language"]).strip())
        if b.get("publisher"):
            pubs.add(str(b["publisher"]).strip())
        if b.get("year"):
            years.add(str(b["year"]).strip())
        tags.update(str(t).strip() for t in (b.get("tags") or []) if str(t).strip())
    return {
        "id": "referential",
        "authors": sorted(authors), "series": sorted(series), "tags": sorted(tags),
        "languages": sorted(langs), "publishers": sorted(pubs),
        "seriesReleaseDates": sorted(years), "ageRatings": [], "sharingLabels": [],
    }


@app.get("/api/v1/libraries/{library_id}")
def ko_library_one(request: Request, library_id: str):
    """单库详情（对 Komga 不可见的库与不存在一律 404）。"""
    _ko_guard(request)
    for lib in _ko_visible_libraries():
        if str(lib.get("id") or "") == str(library_id):
            return komga_api.library_dto(lib)
    _ko_404("书库不存在")


@app.get("/api/v1/books/{book_id}/previous")
def ko_book_previous(request: Request, book_id: str):
    _ko_guard(request)
    b = _ko_book(book_id) or _ko_404("书不存在")
    prev = _ko_sibling(b, -1)
    if not prev:
        _ko_404("没有上一本")
    return komga_api.book_dto(prev, komga_api.series_name_of(prev),
                              komga_api.threshold_resolver())


@app.get("/api/v1/books/{book_id}/next")
def ko_book_next(request: Request, book_id: str):
    _ko_guard(request)
    b = _ko_book(book_id) or _ko_404("书不存在")
    nxt = _ko_sibling(b, 1)
    if not nxt:
        _ko_404("没有下一本")
    return komga_api.book_dto(nxt, komga_api.series_name_of(nxt),
                              komga_api.threshold_resolver())


@app.post("/api/v1/series/{series_id}/analyze")
def ko_series_analyze(request: Request, series_id: str):
    """「重新分析」：本项目书目是**实时扫描**的，没有这一步 → 返回 204 的空实现。

    客户端点了不该报错；但也**不假装真的分析了什么**。
    """
    _ko_guard(request)
    if not _ko_find_series(series_id):
        _ko_404("系列不存在")
    return Response(status_code=204)


# ---- 反向查询（第 20 期封口）----
# 客户端在「书籍信息 / 系列信息」里会问「这本属于哪些清单」「这个系列在哪些合集里」。

@app.get("/api/v1/series/{series_id}/collections")
def ko_series_collections(request: Request, series_id: str, page: int = _KO_PAGE,
                          size: int = _KO_SIZE):
    """该系列在哪些收藏夹里（Komga 的 *List series' collections*）。

    Collections 在第 16 期已映射为**真实收藏夹**，所以这里是真实数据：逐夹判断
    成员书里是否有属于该系列的书。系列不存在 → 404（不静默给空列表）。
    """
    _ko_guard(request)
    found = _ko_find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    name, _items = found
    rows = []
    for row in db.list_collections():
        groups = _ko_collection_groups(row["id"])
        if name in groups:
            rows.append(komga_api.collection_dto(row["id"], row["name"],
                                                row.get("created_at"), groups))
    return komga_api.paginate(rows, page, size)


@app.get("/api/v1/books/{book_id}/readlists")
def ko_book_readlists(request: Request, book_id: str, page: int = _KO_PAGE,
                      size: int = _KO_SIZE):
    """该书属于哪些阅读清单 —— 本项目**没有阅读清单**概念，诚实返回空分页。

    书不存在仍按 Komga 惯例 404（先确认它在可见书目里）。
    """
    _ko_guard(request)
    if not _ko_book(book_id):
        _ko_404("书不存在")
    return komga_api.paginate([], page, size)


@app.get("/api/duplicates")
def api_duplicates(threshold: int = Query(85, ge=50, le=100), library_id: str = ""):
    """重复书目。threshold 为书名相似度阈值（%，同 Calibre 的 Similar-title threshold）。

    ``library_id`` 为空 = 全部书库（与加参数前一致），给定时只在该库内比对。
    组上的 ``cross_library`` = **跨库重复**（分属不同库）——最该先处理的那批：
    它们往往同时撞 ``book_id``，会连带出「进度张冠李戴」的冲突（见 /api/library-conflicts）。
    """
    return library.duplicate_groups(threshold, _opt_library(library_id) or None)


@app.post("/api/duplicates/resolve")
def api_duplicates_resolve(payload: dict = Body(...)):
    try:
        return fileops.resolve_duplicates(
            str(payload.get("keep") or ""),
            payload.get("remove") or [],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/missing")
def api_missing(library_id: str = ""):
    """零字节 / 解析失败 / 缺封面的条目。``library_id`` 为空 = 全部书库。"""
    return library.missing_items(_opt_library(library_id) or None)


# ---------------- 兼容旧接口（脚本 / 油猴等）----------------

async def _log_dispatch(src: pathlib.Path, action: str, result, source: str, size=None, detail=""):
    """把一次分发结果写入活动日志，并登记为已处理（避免监听线程重复转换）。

    mark_processed 涉及同步文件 I/O 与 watcher 的 state 锁，用 to_thread 跑，
    避免阻塞 asyncio 事件循环（否则转换大文件时整个 Web 服务会冻结）。
    """
    out_name = pathlib.Path(result).name if result else ""
    act = activity_log.ACTION_CONVERT if action == "convert" else activity_log.ACTION_ADD
    activity_log.log(act, src.name, activity_log.STATUS_OK, output=out_name,
                     size=size, source=source, detail=detail)
    if WATCHER is not None:
        try:
            await asyncio.to_thread(WATCHER.mark_processed, src)
        except Exception:
            pass


@app.post("/convert")
async def convert(file: UploadFile = File(...), traditionalize: bool = Form(False)):
    # B1 上传多格式：放开 .txt 限制，允许 pipeline.EBOOK_EXT 直接入库（.txt 仍走转换）。
    # 第 9 期起 EBOOK_EXT 含漫画（.cbz/.cbr）与音频（.mp3/.m4b…）；其余类型（如 .docx）明确拒绝。
    _name = file.filename or ""
    _ext = pathlib.Path(_name).suffix.lower()
    _allowed = {".txt", *pipeline.EBOOK_EXT}
    if _ext not in _allowed:
        raise HTTPException(400, "仅支持 .txt 与电子书格式：" + ", ".join(sorted(_allowed)))
    src = INPUT_DIR / file.filename
    opts = {"traditionalize": traditionalize, "force": True, "merge": True, "cfg": config.load_config()}
    # 多书库：上传件按归库规则决定落点。**先判落点在不在**，没有可接收的库就直接 400 ——
    # 免得先把文件写进 input/ 再拒，留下一个每轮扫描都被拒一次的孤儿。
    out_dir = library_rules.target_root(src=src, name=_name, meta=opts.get("meta"),
                                        base_dir=INPUT_DIR)
    if out_dir is None:
        raise HTTPException(400, library_rules.no_library_reason(name=_name))
    data = await _read_capped(file, _upload_limit("max_bytes"))
    with open(src, "wb") as f:
        f.write(data)
    try:
        # 同步转换可能耗时数十秒，放到线程池跑，避免阻塞事件循环（其它请求无响应）
        action, result = await asyncio.to_thread(pipeline.dispatch, src, out_dir, opts)
    except Exception as e:
        activity_log.log_convert_fail(file.filename, f"{type(e).__name__}: {e}",
                                      size=len(data), source="upload")
        raise
    await _log_dispatch(src, action, result, "upload", size=len(data), detail=opts.get("_notice", ""))
    return FileResponse(result, filename=pathlib.Path(result).name)


@app.post("/convert-path")
async def convert_path(path: str = Form(...), traditionalize: bool = Form(False)):
    src = INPUT_DIR / path
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "文件不存在")
    opts = {"traditionalize": traditionalize, "force": True, "merge": True, "cfg": config.load_config()}
    # 多书库：按归库规则决定落点（来源子目录名 → 格式 → 关键词）；判不出 ⇒ 400 拒收
    out_dir = library_rules.target_root(src=src, name=src.name, meta=opts.get("meta"),
                                        base_dir=INPUT_DIR)
    if out_dir is None:
        raise HTTPException(400, library_rules.no_library_reason(name=src.name))
    try:
        # 同步转换可能耗时数十秒，放到线程池跑，避免阻塞事件循环
        action, result = await asyncio.to_thread(pipeline.dispatch, src, out_dir, opts)
    except Exception as e:
        activity_log.log_convert_fail(src.name, f"{type(e).__name__}: {e}", source="api")
        raise
    await _log_dispatch(src, action, result, "api", size=src.stat().st_size, detail=opts.get("_notice", ""))
    # 与 /convert 同口径：直接返回文件流，真实文件名由 FileResponse 在
    # Content-Disposition 里给（前端据此命名，杜绝「x.epub.epub」这类错名；
    # 也不在前端再发明一套展开名逻辑）。src 已校验为单文件，result 必为文件。
    return FileResponse(result, filename=pathlib.Path(result).name)


@app.get("/content")
async def content(url: str = Query(..., description="章节 / 书籍页 URL")):
    name = next((n for n, c in REGISTRY.items() if c().supports_url(url)), None)
    if not name:
        raise HTTPException(404, "没有已注册的书源支持该 URL")
    src = REGISTRY[name]()
    from .core import network

    async with network.BrowserClient(name, cookie_dir=str(config.COOKIE_DIR), headers=getattr(src, "headers", None)) as c:
        html = await src.render(c, url)
    return HTMLResponse(html or "<p>（空内容）</p>")
