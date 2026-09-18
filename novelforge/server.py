import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import mimetypes
import pathlib
import re
import shutil
import time
import uuid
import zipfile
from urllib.parse import unquote

import yaml

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Body, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .core import pipeline, activity_log, library, fileops
from .core import watcher as watcher_mod
from .core import (db, stats, auth as auth_mod, ebook_convert, achievements, recommend,
                   fonts, comics, opds, opds_client, komga, koreader, integrations,
                   metasources, metafetch, metastore, komga_api, bookdock, metascore,
                   authors as authors_mod)
from . import config
from .sources import REGISTRY, DownloadManager
from .sources import store

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
    if (cfg.get("watcher") or {}).get("enabled", True):
        w = _start_watcher(cfg)
        # 启动信息只进标准日志（docker logs），不污染「转换 / 添加」活动日志
        logging.getLogger("novelforge").info(
            "目录监听已启动：%s → %s（间隔 %ss）", w.input_dir, w.output_dir, w.interval
        )
    yield
    if WATCHER is not None:
        WATCHER.stop()


app = FastAPI(title="NovelForge", version="0.5.0", lifespan=lifespan)

STATIC_DIR = pathlib.Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

INPUT_DIR = config.INPUT_DIR
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
        opts = {"force": True, "merge": True, "cfg": mgr.cfg}
        res = await mgr.download_to(item, OUTPUT_DIR, INPUT_DIR, opts)
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
    return _opds_xml(opds.navigation_feed(_opds_base(request), counts), "navigation")


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
    return _opds_xml(opds.group_navigation(_opds_base(request), "按系列", "series", s,
                                           _opds_updated(bs)), "navigation")


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
    return _opds_xml(opds.acquisition_feed(_opds_base(request), f"系列：{target}", "series",
                                           bs, page=page))


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
    path = config.OUTPUT_DIR / b["name"]
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
def api_set_rating(bid: str, payload: dict = Body(...)):
    """给书评分（1–5 星）。对应上游成就体系里 4 条依赖评分的条目。"""
    if not library.by_id(bid):
        raise HTTPException(404, "书籍不存在")
    try:
        return db.set_rating(bid, (payload or {}).get("stars"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/books/{bid}/rating")
def api_clear_rating(bid: str):
    """取消评分。"""
    return {"ok": True, "cleared": db.clear_rating(bid)}


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
    path = config.OUTPUT_DIR / b["name"]
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
    ``meta`` 是逐字段明细（在线建议值 / 是否已被用户本地覆盖），供编辑器渲染
    「已本地修改」徽标与「恢复为在线值」按钮。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    return {
        "id": b["id"],
        "name": b["name"],
        "format": (b.get("format") or "").upper(),
        # 非 EPUB 没有可改写的 OPF，前端据此把表单置为只读并说明原因
        "editable": (b.get("format") or "").upper() == "EPUB",
        # 生效值：用户覆盖 > 在线抓取 > OPF 原值
        "fields": metastore.effective(b),
        # 逐字段明细（含在线建议 / 是否已本地覆盖）
        "meta": metastore.state(b),
    }


@app.post("/api/books/{bid}/metadata")
def api_set_book_metadata(bid: str, payload: dict = Body(...)):
    """改写单本书的 EPUB 内嵌元数据，并记录用户覆盖（受抓取保护）。

    边界：
      · 只接受 ``fileops.METADATA_FIELDS`` 里的字段，其余**不写**（并在响应里回报）；
      · 只支持 EPUB —— 其它格式没有可改写的 OPF；
      · 改完必须 ``library.invalidate()``，否则扫描缓存会让界面继续显示旧值；
      · **不动文件名**：文件名归「批量重命名」管；
      · 与 OPF 原值**不同**的字段记入 ``meta_override``（用户本地修正，再抓取不冲掉）；
        与 OPF **一致**的字段若此前有覆盖则撤销，回到「跟随在线 / OPF」。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    if (b.get("format") or "").upper() != "EPUB":
        raise HTTPException(400, "仅支持改写 EPUB 的内嵌元数据")

    raw = (payload or {}).get("fields")
    if not isinstance(raw, dict):
        raise HTTPException(400, "fields 必须是对象")
    unknown = sorted(k for k in raw if k not in fileops.METADATA_FIELDS)
    accepted = {k: v for k, v in raw.items() if k in fileops.METADATA_FIELDS}
    if not accepted:
        raise HTTPException(
            400, "没有可改写的字段" + (f"（不支持：{', '.join(unknown)}）" if unknown else "")
        )

    before = {f: _meta_value(b, f) for f in accepted}
    try:
        written = fileops.patch_epub_meta(config.OUTPUT_DIR / b["name"], accepted)
    except ValueError as e:
        raise HTTPException(500, str(e))

    # 与 OPF 原值不同的才记为用户覆盖（并记下编辑前原值 orig，供无在线值时回退）；
    # 与 OPF 一致的字段若此前有覆盖则撤销，回到「跟随在线 / OPF」。
    for f in accepted:
        new_val = str(accepted[f] or "").strip()
        if new_val != str(before[f] or "").strip():
            db.set_override(bid, f, new_val, orig=before[f])
        else:
            db.set_override(bid, f, "")

    library.invalidate()
    fresh = library.by_id(bid) or {}
    changed = sorted(f for f in accepted if before.get(f) != _meta_value(fresh, f))
    activity_log.log(activity_log.ACTION_RENAME, b["name"], activity_log.STATUS_OK,
                     detail="编辑元数据：" + ("、".join(changed) if changed else "无实际变化"),
                     source="api")
    return {
        "ok": True,
        "written": written,
        "changed": changed,
        "unknown": unknown,
        # 回写生效值 + 逐字段明细，前端直接据此刷新表单
        "fields": metastore.effective(fresh),
        "meta": metastore.state(fresh),
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
    """把指定字段恢复为在线值：撤销用户覆盖，并把 OPF 也写回在线值（外部阅读器保持一致）。

    仅 EPUB。恢复的在线值优先用实时检索；检索失败则回退到上次抓取的 ``meta_online`` 缓存。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    if (b.get("format") or "").upper() != "EPUB":
        raise HTTPException(400, "仅支持 EPUB")
    fields = (payload or {}).get("fields") or []
    if not isinstance(fields, list) or not fields:
        raise HTTPException(400, "fields 必须是非空数组")
    fields = [f for f in fields if f in fileops.METADATA_FIELDS]
    if not fields:
        raise HTTPException(400, "没有可恢复的字段")

    # 在线值：先实时检索，失败回退到 meta_online 缓存
    cand = metafetch.online_candidate(b, cfg=config.load_config())
    online_vals = (cand or {}).get("values") or {}
    stored = db.get_online(bid)

    def _online_of(f: str) -> str:
        v = str(online_vals.get(f) or "").strip()
        if v:
            return v
        return str((stored.get(f) or {}).get("value") or "").strip()

    updates = {}
    for f in fields:
        row = db.get_override_row(bid, f)
        ov = _online_of(f)
        if ov:
            target = ov                              # 有在线值：把 OPF 写回在线值
        elif row is not None:
            target = str(row.get("orig") or "")      # 无在线值：还原到编辑前原值（可能为空 = 清空）
        else:
            target = None
        db.set_override(bid, f, "")                  # 撤销覆盖
        if target is not None:
            updates[f] = target
    if updates:
        try:
            fileops.patch_epub_meta(config.OUTPUT_DIR / b["name"], updates)
        except ValueError as e:
            raise HTTPException(500, str(e))
    library.invalidate()
    fresh = library.by_id(bid) or {}
    return {
        "ok": True,
        "fields": metastore.effective(fresh),
        "meta": metastore.state(fresh),
        "recovered": sorted(updates.keys()),
    }


@app.get("/api/books/{bid}/cover")
def api_book_cover(bid: str):
    """书籍封面（EPUB 内嵌的那一张）。

    为什么单独开接口，而不是让前端自己拼 `/asset?p=<zip 内路径>`：
      · 「封面是哪一张」由 OPF 决定，解析逻辑属于服务端；
      · 前端只需要一个不含内部路径的稳定 URL，拿不到就 404、回退渐变占位；
      · 系列 / 作者页的封面载荷里只有 id，没有 zip 路径（见 api_series / api_authors）。

    CBZ（漫画）的封面 = 第一页，因此这里比 EPUB 多一条分支。
    其余非 EPUB（mobi/pdf/txt）不解析封面，直接 404 —— 与 has_cover 的口径一致。
    """
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    fmt = (b.get("format") or "").upper()
    path = config.OUTPUT_DIR / b["name"]

    if fmt == "CBZ":
        entry = comics.cover_entry(path)
        if not entry:
            raise HTTPException(404, "该漫画没有图片")
        try:
            with zipfile.ZipFile(path) as z:
                data = z.read(entry)
        except Exception as e:
            raise HTTPException(500, f"读取封面失败：{e}")
        return Response(
            content=data, media_type=mimetypes.guess_type(entry)[0] or "image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    if fmt != "EPUB":
        raise HTTPException(404, "该格式没有内嵌封面")
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
    path = config.OUTPUT_DIR / b["name"]
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=3600"})


# ---------------- 漫画（CBZ）----------------
# 只支持 CBZ。CBR 需要 RAR 解压依赖，不为单一格式引入系统级二进制依赖（见 core/comics.py）。

@app.get("/api/books/{bid}/comic")
def api_comic_pages(bid: str):
    """漫画页清单。前端按 index 逐页取图（配合懒加载预取邻页），不一次拉全部。"""
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    if (b.get("format") or "").upper() != "CBZ":
        raise HTTPException(400, "仅 CBZ 支持漫画阅读（CBR 需 RAR 依赖，本项目不支持）")
    return comics.pages(config.OUTPUT_DIR / b["name"])


@app.get("/api/books/{bid}/comic/{index}")
def api_comic_page(bid: str, index: int):
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    if (b.get("format") or "").upper() != "CBZ":
        raise HTTPException(400, "仅 CBZ 支持漫画阅读")
    data, media = comics.page_bytes(config.OUTPUT_DIR / b["name"], index)
    if data is None:
        raise HTTPException(404, "页不存在")
    return Response(content=data, media_type=media,
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/books/{bid}/chapter/{index}")
def api_book_chapter(bid: str, index: int):
    b = library.by_id(bid)
    if not b:
        raise HTTPException(404, "书籍不存在")
    path = config.OUTPUT_DIR / b["name"]
    if path.suffix.lower() != ".epub":
        raise HTTPException(400, "仅 EPUB 支持在线阅读")
    try:
        return library.chapter_html(path, index, bid)
    except IndexError:
        raise HTTPException(404, "章节不存在")


@app.get("/api/books/{bid}/progress")
def api_get_progress(bid: str):
    p = db.get_progress(bid)
    return p or {"locator": 0, "percent": 0}


@app.put("/api/books/{bid}/progress")
def api_set_progress(bid: str, payload: dict = Body(...)):
    try:
        locator = int(payload.get("locator", 0))
        percent = float(payload.get("percent", 0.0))
    except (TypeError, ValueError):
        raise HTTPException(400, "locator/percent 必须为数字")
    db.set_progress(bid, locator, percent)
    return {"ok": True}


# ---------------- 阅读状态 / 书评 / 相似书 ----------------

@app.get("/api/books/{bid}/status")
def api_get_status(bid: str):
    return db.get_status(bid)


@app.put("/api/books/{bid}/status")
def api_set_status(bid: str, payload: dict = Body(...)):
    """设置阅读状态。可选 `started_at` / `finished_at`（epoch 秒，0 = 清除后按规则重记）。"""
    try:
        return db.set_status(
            bid,
            str(payload.get("status") or ""),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/books/{bid}/review")
def api_get_review(bid: str):
    return db.get_review(bid)


@app.put("/api/books/{bid}/review")
def api_set_review(bid: str, payload: dict = Body(...)):
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
    return {"ok": True, **db.get_review(bid)}


@app.get("/api/books/{bid}/similar")
def api_similar(bid: str, limit: int = Query(6, ge=1, le=24)):
    """相似书：内容重合度派生（同作者 / 题材 / 同系列），不落库。

    得分为 0 的书不返回 —— 毫无关系的推荐只会消耗界面的信任。
    """
    return {"items": recommend.similar_books(bid, library.books(), limit)}


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
        by_book.append({
            "id": bid,
            "title": (b or {}).get("title") or bid,
            "author": (b or {}).get("author") or "",
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
def api_add_annotation(bid: str, payload: dict = Body(...)):
    quote = str(payload.get("quote", "") or "").strip()
    if not quote:
        raise HTTPException(400, "quote 不能为空")
    rid = db.add_annotation(
        bid,
        int(payload.get("chapter", 0) or 0),
        quote,
        str(payload.get("color", "yellow") or "yellow"),
        str(payload.get("note", "") or ""),
    )
    return {"id": rid, "ok": True}


@app.delete("/api/books/{bid}/annotations/{aid}")
def api_delete_annotation(bid: str, aid: int):
    db.delete_annotation(bid, aid)
    return {"ok": True}


# ---------------- 系列（浏览 / 系列详情）----------------
# 系列名来自 EPUB 元数据（见 library.series_list），无独立实体表。

@app.get("/api/series")
def api_series():
    items = library.series_list()
    return {
        "items": [
            {
                "name": s["name"],
                "count": s["count"],
                "authors": sorted({b["author"] for b in s["books"] if b.get("author")})[:3],
                "covers": [
                    {"id": b["id"], "title": b["title"], "c1": b["c1"], "c2": b["c2"],
                     "has_cover": b.get("has_cover", False)}
                    for b in s["books"][:4]
                ],
            }
            for s in items
        ],
        "total": len(items),
    }


@app.get("/api/series/{name}")
def api_series_detail(name: str):
    bs = library.series_books(name)
    if not bs:
        raise HTTPException(404, "系列不存在")
    return {"name": name, "count": len(bs), "books": bs}


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
def api_all_annotations():
    out = []
    for a in db.all_annotations():
        b = library.by_id(a["book_id"])
        out.append({
            **a,
            "book_title": b["title"] if b else a["book_id"],
            "book_author": b["author"] if b else "",
        })
    return {"items": out, "total": len(out)}


# ---------------- 库（真实分组：格式 / 待修复 / 无封面）----------------

@app.get("/api/libraries")
def api_libraries():
    return {"items": library.library_groups()}


# ---------------- 收藏夹（用户自建，持久化于 SQLite）----------------

@app.get("/api/collections")
def api_collections():
    return {"items": db.list_collections()}


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

PREFS_BLOCKS = {"reader", "pdf", "comic", "appearance", "cover"}
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
def api_stats(days: int = Query(28, ge=7, le=365), top: int = Query(8, ge=1, le=50)):
    """统计聚合。days 控制节奏图窗口（dashboard 用默认 28，统计页可传 7/28/90）；
    top 控制 Top 榜长度（统计页可展开到 50）。"""
    return stats.overview(days, top)


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
    "logging": {"dir", "max_entries"},
    "upload": {"max_bytes", "max_source_rules_bytes"},
    "achievements": {"enabled"},
    "opds": {"enabled"},
    "koreader": {"enabled", "username", "key"},
    # 整块覆盖：三家服务的字段各不相同，逐键白名单只会让新增字段时漏改
    "integrations": {"hardcover", "readwise", "storygraph"},
    # 元数据抓取：顶层子键白名单（`fields` / `custom_fields` 这类嵌套结构不再逐层校验 ——
    # 它们的形状由前端页面保证，后端只在应用时逐字段判定合法性）。
    # 注意 `None` 是「标量/整块取值」的意思（见 _sanitize_config），这里**刻意不用 None**，
    # 免得将来有人往前端配置里塞任意键。
    "metadata_fetch": {
        "enabled", "sources", "limit", "threshold", "fields", "auto_on_import",
        "genre_blocklist", "custom_fields", "googlebooks_api_key", "authors",
    },
    # Komga 兼容服务端：开关 + Basic 用户名 + 可选 API Key
    "komga": {"enabled", "username", "api_key"},
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
            },
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

def _orphans() -> dict:
    """算出各表中的孤儿 book_id（不改任何数据）。"""
    valid = {b["id"] for b in library.books()}
    refs = db.book_id_refs()
    tables: dict = {}
    total = 0
    for name, ids in refs.items():
        bad = [i for i in ids if i not in valid]
        total += len(bad)
        tables[name] = {"books": len(bad), "sample": bad[:10]}
    return {"tables": tables, "total": total, "library_books": len(valid)}


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
    valid = {b["id"] for b in library.books()}
    refs = db.book_id_refs()
    orphans = {t: [i for i in ids if i not in valid] for t, ids in refs.items()}
    removed = db.delete_orphans(orphans)
    total = sum(removed.values())
    activity_log.log(activity_log.ACTION_RECYCLE, "孤儿记录", activity_log.STATUS_OK,
                     detail=f"清理孤儿记录：{total} 行（{removed}）", source="api")
    return {"ok": True, "removed": removed, "total": total}


# ---------------- 求书（Requests）：页面与接口保留、功能后置 ----------------
# 依据 docs/bookorbit-capability-gap.md §9：
#   · 接口必须**存在且返回明确空态**，而不是 404；
#   · 配置结构照上游三段（Sources / Download clients / Automation）定义；
#   · 本组接口**全部只读** —— 求书本体排在后期。
# 刻意不做任何写入：否则会出现「界面上能配、其实后端没生效」的假交互。

REQUEST_SECTIONS = [
    {
        "key": "sources",
        "label": "Sources",
        "state": "unavailable",
        "desc": "单文件插件式索引器与 Torznab / Newznab 接入。",
        "items": [
            {"label": "Install a plugin", "detail": "单文件插件，自备并填配置"},
            {"label": "Add an indexer", "detail": "Torznab / Newznab feed 接入"},
        ],
    },
    {
        "key": "download_clients",
        "label": "Download clients",
        "state": "unavailable",
        "desc": "把索引器返回的链接交给下载客户端。",
        "items": [
            {"label": "客户端类型与地址", "detail": "上游支持多种下载客户端"},
            {"label": "凭据", "detail": "上游需要 BOOK_REQUEST_ENCRYPTION_KEY 才能保存密码"},
        ],
    },
    {
        "key": "automation",
        "label": "Automation",
        "state": "unavailable",
        "desc": "下载完成后的处理流程。",
        "items": [
            {"label": "下载完成后的自动化", "detail": "导入、命名、元数据补全"},
        ],
    },
]


@app.get("/api/requests/config")
def api_requests_config():
    """求书配置的**只读结构**（三段 + 明确空态）。

    返回的是「本页支持什么、不支持什么」，不是可用配置 ——
    因为求书功能后置，这里没有任何可写项。
    """
    dl = config.load_config().get("download") or {}
    enabled = bool(dl.get("enabled", False))
    try:
        total_sources = len(store.list_sources())
    except Exception:
        total_sources = 0

    return {
        "stage": "skeleton",
        "note": "页面与接口保留、功能后置（docs/bookorbit-capability-gap.md §9）。"
                "本页只做只读结构对照，不产生任何后端写入。",
        "sections": REQUEST_SECTIONS,
        # 本项目真正的「从外部获取书」能力是**数据驱动的书源规则**，不是插件 / indexer。
        # 如实指向替代路径，而不是假装这里有等价能力。
        "alternative": {
            "label": "本项目的替代路径",
            "desc": "本项目用书源规则（JSON）检索与下载外部书籍，形态与上游的插件 / indexer 不同。",
            "download_enabled": enabled,
            "public_only": bool(dl.get("public_only", True)),
            "source_count": total_sources,
            "guidance": ""
            if (enabled and total_sources)
            else "尚未配置可用的搜索源：需在「网络与下载」中开启下载功能，并确保存在可用的书源规则。",
            "settings_link": "/settings/ext/network",
            "tools_link": "/tools/sources",
        },
    }


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
             status: str = "", q: str = ""):
    return {
        "items": activity_log.recent(limit=limit, action=action, status=status, q=q),
        "count": activity_log.count(),
        "dir": str(activity_log.log_dir()),
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


# ---------------- 工具页：实体管理 / 批量重命名 / 重复书籍 / 缺失资源 ----------------
# 数据源统一是扫描 OUTPUT_DIR（见 core/library.py）；会改磁盘的动作一律
# 「先预览、再应用」，删除类走回收目录，全部写活动日志（见 core/fileops.py）。
# 业务逻辑都在 core/ 里，这里只做参数校验与胶水。


@app.get("/api/entities")
def api_entities(type_: str = Query("author", alias="type")):
    if type_ not in ("author", "series"):
        raise HTTPException(400, "type 只能是 author 或 series")
    return library.entities(type_)


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
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/entities/rename/apply")
def api_entity_rename_apply(payload: dict = Body(...)):
    type_ = str(payload.get("type") or "author")
    if type_ not in ("author", "series"):
        raise HTTPException(400, "type 只能是 author 或 series")
    try:
        return fileops.apply_rename(
            payload.get("items"),
            meta_field="author" if type_ == "author" else "series",
            meta_value=str(payload.get("to") or ""),
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
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/rename/preview")
def api_rename_preview(payload: dict = Body(...)):
    """按规则生成改名预览（只算不改）。

    pattern / scope 缺省时回退到服务端保存的命名规则（「设置 → 文件命名」维护），
    这样工具页可以直接预览「已保存的规则」，无需每次重打一遍。
    """
    saved = (config.load_config() or {}).get("naming") or {}
    scope = str(payload.get("scope") or saved.get("scope") or "all")
    pattern = str(payload.get("pattern") or saved.get("pattern") or "")
    if not pattern.strip():
        raise HTTPException(400, "命名规则为空：请先在「设置 → 文件命名」保存一条规则")
    try:
        plan = fileops.plan_pattern_rename(scope, pattern)
        # 回显实际使用的规则，便于前端确认「用的是保存值还是本次传入值」
        plan["scope"] = scope
        plan["pattern"] = pattern
        return plan
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/rename/apply")
def api_rename_apply(payload: dict = Body(...)):
    try:
        return fileops.apply_rename(payload.get("items"))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------- Komga 库布局（输出侧）----------------
# 把已入库的书整理成 Komga 认识的结构：``系列名/系列名 #N.ext``（见 core/komga.py）。
# 与批量重命名同一范式：**先预览、再应用** —— 预览只算不改，应用只认回传的
# ``{old, new}`` 条目并再校验一遍。会改 basename 的条目在应用时自动搬关联数据
# （db.remap_book_id），否则整理一次就把阅读进度丢了。

@app.post("/api/komga/layout/preview")
def api_komga_layout_preview():
    return fileops.plan_komga_layout()


@app.post("/api/komga/layout/apply")
def api_komga_layout_apply(payload: dict = Body(...)):
    try:
        return fileops.apply_komga_layout(payload.get("items"))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------- OPDS 客户端（订阅远程 OPDS 源）----------------
# 与上面的 OPDS **服务**方向相反：这里去读别人的 feed
# （Komga / Calibre-Web / 任何标准 OPDS 源，见 core/opds_client.py）。
# 密码回显一律掩码，提交掩码 = 不修改（与 llm.api_key 同一约定，见 _KEY_MASK）。

_OPDS_SRC_MASK = "••••••••"


def _opds_src_public(s: dict) -> dict:
    out = {k: v for k, v in s.items() if k != "password"}
    out["password"] = _OPDS_SRC_MASK if (s.get("password") or "") else ""
    out["has_password"] = bool(s.get("password"))
    return out


def _opds_src_fields(payload: dict) -> tuple:
    name = str((payload or {}).get("name") or "").strip()
    url = str((payload or {}).get("url") or "").strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "地址必须以 http:// 或 https:// 开头")
    return name, url


@app.get("/api/opds/sources")
def api_opds_sources():
    return {"items": [_opds_src_public(s) for s in db.list_opds_sources()]}


@app.post("/api/opds/sources")
def api_opds_source_create(payload: dict = Body(...)):
    name, url = _opds_src_fields(payload)
    return _opds_src_public(db.create_opds_source(
        name, url,
        str((payload or {}).get("username") or ""),
        str((payload or {}).get("password") or ""),
    ))


@app.put("/api/opds/sources/{sid}")
def api_opds_source_update(sid: int, payload: dict = Body(...)):
    if not db.get_opds_source(sid):
        raise HTTPException(404, "订阅源不存在")
    name, url = _opds_src_fields(payload)
    pw = (payload or {}).get("password")
    # 空串或掩码都表示「保留原密码」：前端没改密码时提交的正是掩码
    keep = pw is None or str(pw) == "" or str(pw) == _OPDS_SRC_MASK
    return _opds_src_public(db.update_opds_source(
        sid, name, url, str((payload or {}).get("username") or ""),
        None if keep else str(pw),
    ))


@app.delete("/api/opds/sources/{sid}")
def api_opds_source_delete(sid: int):
    if not db.delete_opds_source(sid):
        raise HTTPException(404, "订阅源不存在")
    return {"ok": True}


@app.post("/api/opds/sources/{sid}/browse")
def api_opds_source_browse(sid: int, payload: dict = Body(...)):
    """抓取并解析 feed。href 为空时用源地址（即订阅入口）。"""
    s = db.get_opds_source(sid)
    if not s:
        raise HTTPException(404, "订阅源不存在")
    try:
        return opds_client.fetch(s, str((payload or {}).get("href") or ""))
    except opds_client.OpdsError as e:
        raise HTTPException(400, str(e))


@app.post("/api/opds/sources/{sid}/download")
def api_opds_source_download(sid: int, payload: dict = Body(...)):
    """下载一本书 → 落进导出目录，与转换产出的书同等对待（按 output.layout 归位）。"""
    s = db.get_opds_source(sid)
    if not s:
        raise HTTPException(404, "订阅源不存在")
    p = payload or {}
    href = str(p.get("href") or "").strip()
    if not href.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "下载地址非法")

    stem, ext = opds_client.split_name(str(p.get("title") or ""), str(p.get("type") or ""))
    stem = komga.clean_segment(stem) or "未命名"
    # 系列：先看标题，再看 feed 里的 dc:isPartOf（Komga 会给「系列 #3」这种值）
    series, index = komga.infer(stem)
    if not series:
        series, index = komga.infer(str(p.get("series") or ""))
    layout = str((config.load_config().get("output") or {}).get("layout") or "flat").strip().lower()
    rel = komga.relpath_for(stem, ext.lstrip("."), series, index, layout)
    target = config.OUTPUT_DIR / rel
    if target.exists():
        raise HTTPException(400, f"已存在同名文件：{rel}")
    try:
        r = opds_client.download(s, href, target.parent, target.name)
    except opds_client.OpdsError as e:
        raise HTTPException(400, str(e))
    library.invalidate()
    activity_log.log(activity_log.ACTION_ADD, rel, activity_log.STATUS_OK,
                     output=rel, source="opds", detail=f"来自订阅源「{s['name']}」")
    return {"ok": True, "name": rel, "bytes": r["bytes"]}


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
    rows = koreader.scan_books(library.books(), config.OUTPUT_DIR)
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
    """整块掩码：字段有值给掩码、无值给空串（供 GET /api/config 回显）。"""
    out = {}
    for name in _INTEGRATION_SERVICES:
        cur = sec.get(name) or {}
        out[name] = {k: (_KEY_MASK if str(v or "").strip() else "") for k, v in cur.items()}
    return out


def _mask_metadata_fetch(sec: dict) -> dict:
    """元数据抓取的配置回显：**只掩码 API Key**，其余原样（都是普通配置项）。"""
    out = dict(sec or {})
    has_key = bool(str(out.get("googlebooks_api_key") or "").strip())
    out["googlebooks_api_key"] = _KEY_MASK if has_key else ""
    out["has_googlebooks_key"] = has_key
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
    ov["integrations"] = {**(ov.get("integrations") or {}), service: cur}
    config.save_overrides(ov)
    return {"ok": True}


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
    """可用元数据源 + 当前启用情况（设置页据此渲染）。"""
    mf = config.load_config().get("metadata_fetch") or {}
    active = mf.get("sources") or list(metasources.DEFAULT_ORDER)
    return {
        "items": [{**meta, "id": sid, "active": sid in active}
                  for sid, meta in metasources.SOURCES.items()],
        "enabled": bool(mf.get("enabled")),
        "has_googlebooks_key": bool(str(mf.get("googlebooks_api_key") or "").strip()),
    }


@app.post("/api/metadata/probe")
def api_metadata_probe(payload: dict = Body(None)):
    """源连通性自检（真的外呼：点一次测一次，结果只回给这次请求）。"""
    mf = config.load_config().get("metadata_fetch") or {}
    key = str(mf.get("googlebooks_api_key") or "")
    wanted = (payload or {}).get("sources") or list(metasources.SOURCES)
    out = {}
    for sid in wanted:
        if sid in metasources.SOURCES:
            out[sid] = metasources.probe(sid, {"api_key": key} if sid == "googlebooks" else None)
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
    tests = []
    for cl in clauses:
        if not isinstance(cl, dict):
            continue
        if "libraryId" in cl:
            want = ((cl["libraryId"] or {}).get("in") or [])
            if want and komga_api.LIBRARY_ID not in want:
                tests.append(lambda b: False)
        if "readStatus" in cl:
            want = [str(s).upper() for s in ((cl["readStatus"] or {}).get("in") or [])]
            if want:
                def _read(b, _w=want):
                    pct = float((db.get_progress(b["id"]) or {}).get("percent") or 0)
                    st = "READ" if pct >= 99.5 else ("IN_PROGRESS" if pct > 0 else "UNREAD")
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
        "sharedLibraries": [{"libraryId": komga_api.LIBRARY_ID, "userId": "1", "role": "ADMIN"}],
    }


# ---- 库 ----

@app.get("/api/v1/libraries")
def ko_libraries(request: Request):
    """客户端第一步就调它。"""
    _ko_guard(request)
    return [komga_api.library_dto()]


# ---- 系列（latest 必须先于 {series_id}）----

def _ko_series_page(page: int, size: int, sort: str) -> dict:
    items = [komga_api.series_dto(name, bs) for name, bs in komga_api.grouped().items()]
    return komga_api.paginate(_ko_sorted(items, sort, "name"), page, size)


@app.get("/api/v1/series")
def ko_series_get(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE, sort: str = ""):
    """已弃用（1.19+ 推 `POST /series/list`），但**老客户端仍在用**，必须保留。"""
    _ko_guard(request)
    return _ko_series_page(page, size, sort)


@app.post("/api/v1/series/list")
def ko_series_list(request: Request, payload: dict = Body(None),
                   page: int = _KO_PAGE, size: int = _KO_SIZE, sort: str = ""):
    _ko_guard(request)
    return _ko_series_page(page, size, sort)


@app.get("/api/v1/series/latest")
def ko_series_latest(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE):
    _ko_guard(request)
    items = [komga_api.series_dto(n, bs) for n, bs in komga_api.grouped().items()]
    return komga_api.paginate(_ko_sorted(items, "lastModifiedDate,desc"), page, size)


@app.get("/api/v1/series/{series_id}")
def ko_series_one(request: Request, series_id: str):
    _ko_guard(request)
    found = komga_api.find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    name, items = found
    return komga_api.series_dto(name, items)


@app.get("/api/v1/series/{series_id}/books")
def ko_series_books(request: Request, series_id: str, page: int = _KO_PAGE,
                    size: int = _KO_SIZE, sort: str = ""):
    _ko_guard(request)
    found = komga_api.find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    name, items = found
    dtos = [komga_api.book_dto(b, name) for b in items]
    return komga_api.paginate(_ko_sorted(dtos, sort, "name"), page, size)


@app.get("/api/v1/series/{series_id}/thumbnail")
def ko_series_thumb(request: Request, series_id: str):
    """系列封面 = 该系列**第一本有封面的书**的封面。"""
    _ko_guard(request)
    found = komga_api.find_series(series_id)
    if not found:
        _ko_404("系列不存在")
    _name, items = found
    for b in items:
        if b.get("has_cover"):
            return api_book_cover(b["id"])
    _ko_404("该系列没有可用封面")


# ---- 书籍（latest / ondeck 必须先于 {book_id}）----

def _ko_books_dto(sort: str = "") -> list:
    return _ko_sorted([komga_api.book_dto(b) for b in library.books()], sort, "name")


@app.get("/api/v1/books")
def ko_books_get(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE, sort: str = ""):
    """已弃用但老客户端在用（同系列）。"""
    _ko_guard(request)
    return komga_api.paginate(_ko_books_dto(sort), page, size)


@app.post("/api/v1/books/list")
def ko_books_list(request: Request, payload: dict = Body(None),
                  page: int = _KO_PAGE, size: int = _KO_SIZE, sort: str = ""):
    _ko_guard(request)
    bs = library.books()
    flt = _ko_read_filter(payload)
    if flt:
        bs = [b for b in bs if flt(b)]
    items = _ko_sorted([komga_api.book_dto(b) for b in bs], sort, "name")
    return komga_api.paginate(items, page, size)


@app.get("/api/v1/books/latest")
def ko_books_latest(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE):
    _ko_guard(request)
    return komga_api.paginate(_ko_sorted(_ko_books_dto(), "lastModifiedDate,desc"), page, size)


@app.get("/api/v1/books/ondeck")
def ko_books_ondeck(request: Request, page: int = _KO_PAGE, size: int = _KO_SIZE):
    """待读：**系列里已有在读书**时，该系列的第一本未读书（Komga 的语义）。"""
    _ko_guard(request)
    out = []
    for name, items in komga_api.grouped().items():
        pcts = [float((db.get_progress(b["id"]) or {}).get("percent") or 0) for b in items]
        if not any(0 < p < 99.5 for p in pcts):
            continue
        nxt = next((b for b, p in zip(items, pcts) if p < 99.5), None)
        if nxt:
            out.append(komga_api.book_dto(nxt, name))
    return komga_api.paginate(out, page, size)


@app.get("/api/v1/books/{book_id}")
def ko_book_one(request: Request, book_id: str):
    _ko_guard(request)
    b = library.by_id(book_id) or _ko_404("书不存在")
    return komga_api.book_dto(b)


@app.get("/api/v1/books/{book_id}/thumbnail")
def ko_book_thumb(request: Request, book_id: str):
    _ko_guard(request)
    if not library.by_id(book_id):
        _ko_404("书不存在")
    return api_book_cover(book_id)


@app.get("/api/v1/books/{book_id}/file")
def ko_book_file(request: Request, book_id: str):
    _ko_guard(request)
    b = library.by_id(book_id) or _ko_404("书不存在")
    path = config.OUTPUT_DIR / b["name"]
    if not path.is_file():
        _ko_404("文件不存在")
    return FileResponse(path, media_type="application/octet-stream",
                        filename=pathlib.PurePosixPath(b["name"]).name)


@app.get("/api/v1/books/{book_id}/pages")
def ko_book_pages(request: Request, book_id: str):
    _ko_guard(request)
    b = library.by_id(book_id) or _ko_404("书不存在")
    pages = komga_api.pages_for(b)
    if not pages:
        raise HTTPException(400, "该格式不支持页面流：请下载文件后本地阅读")
    return pages


@app.get("/api/v1/books/{book_id}/pages/{number}")
def ko_book_page(request: Request, book_id: str, number: int, convert: str = ""):
    _ko_guard(request)
    b = library.by_id(book_id) or _ko_404("书不存在")
    data, media = komga_api.page_image(b, number, convert)
    if not data:
        _ko_404("页不存在")
    return Response(content=data, media_type=media)


@app.get("/api/v1/books/{book_id}/manifest")
def ko_book_manifest(request: Request, book_id: str):
    _ko_guard(request)
    b = library.by_id(book_id) or _ko_404("书不存在")
    return Response(content=json.dumps(komga_api.manifest_for(b), ensure_ascii=False),
                    media_type="application/webpub+json")


@app.put("/api/v1/books/{book_id}/read-progress")
def ko_put_read_progress(request: Request, book_id: str, payload: dict = Body(None)):
    _ko_guard(request)
    b = library.by_id(book_id) or _ko_404("书不存在")
    locator, percent = komga_api.apply_read_progress(b, payload)
    db.set_progress(book_id, locator, percent)
    return Response(status_code=204)


@app.delete("/api/v1/books/{book_id}/read-progress")
def ko_delete_read_progress(request: Request, book_id: str):
    _ko_guard(request)
    if not library.by_id(book_id):
        _ko_404("书不存在")
    db.set_progress(book_id, 0, 0)
    return Response(status_code=204)


@app.get("/api/duplicates")
def api_duplicates(threshold: int = Query(85, ge=50, le=100)):
    """重复书目。threshold 为书名相似度阈值（%，同 Calibre 的 Similar-title threshold）。"""
    return library.duplicate_groups(threshold)


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
def api_missing():
    return library.missing_items()


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
    # 其余类型（如 .docx/.cbr）明确拒绝。CBR 因 RAR 系统依赖未做，不在白名单内。
    _name = file.filename or ""
    _ext = pathlib.Path(_name).suffix.lower()
    _allowed = {".txt", *pipeline.EBOOK_EXT}
    if _ext not in _allowed:
        raise HTTPException(400, "仅支持 .txt 与电子书格式：" + ", ".join(sorted(_allowed)))
    src = INPUT_DIR / file.filename
    data = await _read_capped(file, _upload_limit("max_bytes"))
    with open(src, "wb") as f:
        f.write(data)
    opts = {"traditionalize": traditionalize, "force": True, "merge": True, "cfg": config.load_config()}
    try:
        # 同步转换可能耗时数十秒，放到线程池跑，避免阻塞事件循环（其它请求无响应）
        action, result = await asyncio.to_thread(pipeline.dispatch, src, OUTPUT_DIR, opts)
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
    try:
        # 同步转换可能耗时数十秒，放到线程池跑，避免阻塞事件循环
        action, result = await asyncio.to_thread(pipeline.dispatch, src, OUTPUT_DIR, opts)
    except Exception as e:
        activity_log.log_convert_fail(src.name, f"{type(e).__name__}: {e}", source="api")
        raise
    await _log_dispatch(src, action, result, "api", size=src.stat().st_size, detail=opts.get("_notice", ""))
    return {"action": action, "result": str(result)}


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
