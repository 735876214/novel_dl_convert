import asyncio
import contextlib
import logging
import pathlib
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Body, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .core import pipeline, activity_log
from .core import watcher as watcher_mod
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
    elif WATCHER.is_running():
        return WATCHER
    WATCHER.cfg = cfg
    WATCHER.start()
    return WATCHER


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = config.load_config()
    _init_logging(cfg)
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

# 后台下载任务表（进程内；重启即清空，符合 NAS 单机场景）
TASKS: dict = {}


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


@app.post("/api/sources")
async def api_add_sources(request: Request):
    text = (await request.body()).decode("utf-8", errors="ignore")
    rules = _parse_rules_text(text)
    if not rules:
        raise HTTPException(400, "无法解析书源：请粘贴 JSON 对象 / 数组 / JSONL")
    return _add_rules_list(rules)


@app.post("/api/sources/upload")
async def api_upload_sources(file: UploadFile = File(...)):
    text = (await file.read()).decode("utf-8", errors="ignore")
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


@app.post("/api/download")
async def api_download(item: dict = Body(...)):
    tid = uuid.uuid4().hex
    TASKS[tid] = {"status": "pending", "result": None, "error": None, "name": None}
    asyncio.create_task(_run_download(tid, item))
    return {"task_id": tid}


async def _run_download(tid: str, item: dict):
    TASKS[tid]["status"] = "running"
    try:
        mgr = _manager()
        res = await mgr.download_to(
            item, OUTPUT_DIR, INPUT_DIR, {"force": True, "merge": True, "cfg": mgr.cfg}
        )
        name = pathlib.Path(res).name
        TASKS[tid].update(status="done", result=f"/download/{name}", name=name)
        activity_log.log_convert_ok(
            item.get("title") or name, name, source="download",
            size=(pathlib.Path(res).stat().st_size if pathlib.Path(res).exists() else None),
        )
        # 下载已顺带生成 EPUB，把刚落盘的 txt 登记为已处理，避免监听线程重复转换
        if WATCHER is not None:
            await asyncio.to_thread(WATCHER.mark_recent, seconds=30, suffix=".txt")
    except Exception as e:
        TASKS[tid].update(status="failed", error=str(e))
        activity_log.log_convert_fail(
            item.get("title") or item.get("url") or "(未命名)",
            f"{type(e).__name__}: {e}", source="download",
        )


@app.get("/api/tasks/{tid}")
def api_task(tid: str):
    t = TASKS.get(tid)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


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


# ---------------- 目录监听（input → output）----------------

def _get_watcher():
    """惰性构造监听器（未启用监听时，手动扫描 / 查状态也要能用）。"""
    global WATCHER
    if WATCHER is None:
        WATCHER = watcher_mod.FolderWatcher(cfg=config.load_config())
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


# ---------------- 活动日志 ----------------

@app.get("/api/logs")
def api_logs(limit: int = Query(200, ge=1, le=5000), action: str = "",
             status: str = "", q: str = ""):
    return {
        "items": activity_log.recent(limit=limit, action=action, status=status, q=q),
        "count": activity_log.count(),
        "dir": str(activity_log.log_dir()),
    }


@app.get("/api/logs/download")
def api_logs_download():
    p = activity_log.log_path()
    if not p.is_file():
        raise HTTPException(404, "暂无日志")
    return FileResponse(p, filename="activity.log")


@app.delete("/api/logs")
def api_logs_clear():
    return {"ok": activity_log.clear()}


# ---------------- 兼容旧接口（脚本 / 油猴等）----------------

async def _log_dispatch(src: pathlib.Path, action: str, result, source: str, size=None):
    """把一次分发结果写入活动日志，并登记为已处理（避免监听线程重复转换）。

    mark_processed 涉及同步文件 I/O 与 watcher 的 state 锁，用 to_thread 跑，
    避免阻塞 asyncio 事件循环（否则转换大文件时整个 Web 服务会冻结）。
    """
    out_name = pathlib.Path(result).name if result else ""
    act = activity_log.ACTION_CONVERT if action == "convert" else activity_log.ACTION_ADD
    activity_log.log(act, src.name, activity_log.STATUS_OK, output=out_name,
                     size=size, source=source)
    if WATCHER is not None:
        try:
            await asyncio.to_thread(WATCHER.mark_processed, src)
        except Exception:
            pass


@app.post("/convert")
async def convert(file: UploadFile = File(...), traditionalize: bool = Form(False)):
    if not (file.filename or "").endswith(".txt"):
        raise HTTPException(400, "仅支持 .txt")
    src = INPUT_DIR / file.filename
    data = await file.read()
    with open(src, "wb") as f:
        f.write(data)
    try:
        # 同步转换可能耗时数十秒，放到线程池跑，避免阻塞事件循环（其它请求无响应）
        action, result = await asyncio.to_thread(
            pipeline.dispatch, src, OUTPUT_DIR,
            {"traditionalize": traditionalize, "force": True, "merge": True, "cfg": config.load_config()},
        )
    except Exception as e:
        activity_log.log_convert_fail(file.filename, f"{type(e).__name__}: {e}",
                                      size=len(data), source="upload")
        raise
    await _log_dispatch(src, action, result, "upload", size=len(data))
    return FileResponse(result, filename=pathlib.Path(result).name)


@app.post("/convert-path")
async def convert_path(path: str = Form(...), traditionalize: bool = Form(False)):
    src = INPUT_DIR / path
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "文件不存在")
    try:
        # 同步转换可能耗时数十秒，放到线程池跑，避免阻塞事件循环
        action, result = await asyncio.to_thread(
            pipeline.dispatch, src, OUTPUT_DIR,
            {"traditionalize": traditionalize, "force": True, "merge": True, "cfg": config.load_config()},
        )
    except Exception as e:
        activity_log.log_convert_fail(src.name, f"{type(e).__name__}: {e}", source="api")
        raise
    await _log_dispatch(src, action, result, "api", size=src.stat().st_size)
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
