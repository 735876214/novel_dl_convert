import asyncio
import pathlib
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Body, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .core import pipeline
from . import config
from .sources import REGISTRY, DownloadManager
from .sources import store

# 启动即确保输入 / 导出 / 配置 / cookie / 缓存 / 用户书源目录存在
# （用户书源在 novelforge.sources 包导入时已自动加载）
config.ensure_dirs()

app = FastAPI(title="NovelForge", version="0.4.0")

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
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
def health():
    return {"status": "ok", "input": str(INPUT_DIR), "output": str(OUTPUT_DIR)}


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
    except Exception as e:
        TASKS[tid].update(status="failed", error=str(e))


@app.get("/api/tasks/{tid}")
def api_task(tid: str):
    t = TASKS.get(tid)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


# ---------------- 文件列表 / 下载成品 ----------------

@app.get("/api/files")
def list_files():
    return {
        "input": [f.name for f in sorted(INPUT_DIR.iterdir()) if f.is_file()],
        "output": [f.name for f in sorted(OUTPUT_DIR.iterdir()) if f.is_file()],
    }


@app.get("/download/{name}")
def download_file(name: str):
    target = OUTPUT_DIR / name
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target, filename=name)


# ---------------- 兼容旧接口（脚本 / 油猴等）----------------

@app.post("/convert")
async def convert(file: UploadFile = File(...), traditionalize: bool = Form(False)):
    if not (file.filename or "").endswith(".txt"):
        raise HTTPException(400, "仅支持 .txt")
    src = INPUT_DIR / file.filename
    with open(src, "wb") as f:
        f.write(await file.read())
    action, result = pipeline.dispatch(
        src, OUTPUT_DIR,
        {"traditionalize": traditionalize, "force": True, "merge": True, "cfg": config.load_config()},
    )
    return FileResponse(result, filename=pathlib.Path(result).name)


@app.post("/convert-path")
def convert_path(path: str = Form(...), traditionalize: bool = Form(False)):
    src = INPUT_DIR / path
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "文件不存在")
    action, result = pipeline.dispatch(
        src, OUTPUT_DIR,
        {"traditionalize": traditionalize, "force": True, "merge": True, "cfg": config.load_config()},
    )
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
