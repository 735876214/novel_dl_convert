import pathlib

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Body
from fastapi.responses import FileResponse, HTMLResponse

from .core import pipeline
from . import config
from .sources import REGISTRY, DownloadManager

# 启动即确保输入 / 导出 / 配置 / cookie / 缓存目录存在
config.ensure_dirs()

app = FastAPI(title="NovelForge", version="0.3.0")

INPUT_DIR = config.INPUT_DIR
OUTPUT_DIR = config.OUTPUT_DIR


def _manager():
    return DownloadManager(config.load_config())


@app.get("/health")
def health():
    return {"status": "ok", "input": str(INPUT_DIR), "output": str(OUTPUT_DIR)}


@app.get("/")
def index():
    files = [f.name for f in sorted(INPUT_DIR.iterdir()) if f.is_file()]
    items = "".join(
        f"<li><a href='/convert-path-form?path={f}'>{f}</a></li>" for f in files
    ) or "<li>（输入目录为空）</li>"
    return HTMLResponse(
        f"""<html><body>
<h1>NovelForge</h1>
<p>输入目录：<code>{INPUT_DIR}</code> ｜ 导出目录：<code>{OUTPUT_DIR}</code></p>
<h2>① 上传 TXT 直接转换</h2>
<form action='/convert' method='post' enctype='multipart/form-data'>
<input type='file' name='file' accept='.txt'/>
<label><input type='checkbox' name='traditionalize' value='true'/> 繁体转简体</label>
<button type='submit'>转换为 EPUB</button></form>
<h2>② 输入目录文件（点击转换并下载）</h2>
<ul>{items}</ul>
<h2>③ 在线书源（需开启 download）</h2>
<form action='/search' method='post'>书名：<input name='title'/>
<button>搜索</button></form>
<h2>④ 内容预览 API</h2>
<p><code>GET /content?url=https://.../chapter/1</code> 即时抓取清洗（不落盘）</p>
<p><code>GET /supported?url=...</code> 判断该 URL 是否支持</p>
</body></html>"""
    )


@app.post("/convert")
async def convert(file: UploadFile = File(...), traditionalize: bool = Form(False)):
    """上传 txt → 存入输入目录 → 转换 → 成品落到导出目录 → 直接下载。"""
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
    """按输入目录内的相对路径转换（供脚本 / 油猴调用）。"""
    src = INPUT_DIR / path
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "文件不存在")
    action, result = pipeline.dispatch(
        src, OUTPUT_DIR,
        {"traditionalize": traditionalize, "force": True, "merge": True, "cfg": config.load_config()},
    )
    return {"action": action, "result": str(result)}


@app.get("/convert-path-form")
def convert_path_form(path: str):
    """Web 上的「点击转换」：转换完成后跳转到下载。"""
    src = INPUT_DIR / path
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "文件不存在")
    action, result = pipeline.dispatch(
        src, OUTPUT_DIR, {"traditionalize": False, "force": True, "merge": True, "cfg": config.load_config()}
    )
    name = pathlib.Path(result).name
    return HTMLResponse(
        f"<p>已{ '转换' if action=='convert' else '复制' }：{name}</p>"
        f"<p><a href='/download/{name}'>下载 {name}</a></p>"
        f"<p><a href='/'>返回</a></p>"
    )


@app.get("/files")
def list_files():
    """列出输入与导出目录的文件，便于 NAS 上查看状态。"""
    return {
        "input": [f.name for f in sorted(INPUT_DIR.iterdir()) if f.is_file()],
        "output": [f.name for f in sorted(OUTPUT_DIR.iterdir()) if f.is_file()],
    }


@app.get("/download/{name}")
def download_file(name: str):
    """从导出目录下载成品。"""
    target = OUTPUT_DIR / name
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target, filename=name)


# ---- 在线书源 / 内容预览 API（对应 denovel 的内容服务 API）----
@app.get("/supported")
def supported(url: str = Query(..., description="待判断的 URL")):
    """判断该 URL 由哪个已注册书源处理。"""
    name = next((n for n, c in REGISTRY.items() if c().supports_url(url)), None)
    return {"url": url, "source": name}


@app.get("/content")
async def content(url: str = Query(..., description="章节 / 书籍页 URL")):
    """即时抓取并清洗为 HTML 预览，不落盘（即使不下载也可完美预览）。"""
    name = next((n for n, c in REGISTRY.items() if c().supports_url(url)), None)
    if not name:
        raise HTTPException(404, "没有已注册的书源支持该 URL")
    src = REGISTRY[name]()
    from .core import network

    async with network.BrowserClient(name, cookie_dir=str(config.COOKIE_DIR), headers=getattr(src, "headers", None)) as c:
        html = await src.render(c, url)
    return HTMLResponse(html or "<p>（空内容）</p>")


@app.get("/sources")
def sources():
    return {
        "sources": [
            {"name": n, "public": getattr(c, "public", True), "domains": getattr(c, "domains", [])}
            for n, c in REGISTRY.items()
        ]
    }


@app.post("/search")
async def search(title: str = Form(...)):
    """跨已注册（公开）书源搜索。"""
    mgr = _manager()
    if not mgr.enabled and mgr.public_only:
        # 未开启 download 时仅允许搜索公开源；否则按配置
        pass
    results = await mgr.search(title)
    return {"count": len(results), "results": results}


@app.post("/download")
async def download_book(item: dict = Body(...)):
    """根据搜索结果条目下载并转为 EPUB（需开启 download）。"""
    mgr = _manager()
    if not mgr.enabled:
        raise HTTPException(403, "download 未开启（见 config.yaml 的 download.enabled）")
    result = await mgr.fetch_and_convert(item, OUTPUT_DIR, {"force": True, "merge": True, "cfg": config.load_config()})
    name = pathlib.Path(result).name
    return {"result": str(result), "download": f"/download/{name}"}
