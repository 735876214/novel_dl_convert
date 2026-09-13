import pathlib

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from .core import pipeline
from . import config

# 启动即确保输入 / 导出目录存在（容器内由 compose 挂载，本地运行也能自洽）
config.ensure_dirs()

app = FastAPI(title="NovelForge", version="0.2.0")

INPUT_DIR = config.INPUT_DIR
OUTPUT_DIR = config.OUTPUT_DIR


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
        src, OUTPUT_DIR, {"traditionalize": traditionalize, "force": True, "merge": True}
    )
    return FileResponse(result, filename=pathlib.Path(result).name)


@app.post("/convert-path")
def convert_path(path: str = Form(...), traditionalize: bool = Form(False)):
    """按输入目录内的相对路径转换（供脚本 / 油猴调用）。"""
    src = INPUT_DIR / path
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "文件不存在")
    action, result = pipeline.dispatch(
        src, OUTPUT_DIR, {"traditionalize": traditionalize, "force": True, "merge": True}
    )
    return {"action": action, "result": str(result)}


@app.get("/convert-path-form")
def convert_path_form(path: str):
    """Web 上的「点击转换」：转换完成后跳转到下载。"""
    src = INPUT_DIR / path
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "文件不存在")
    action, result = pipeline.dispatch(
        src, OUTPUT_DIR, {"traditionalize": False, "force": True, "merge": True}
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
def download(name: str):
    """从导出目录下载成品。"""
    target = OUTPUT_DIR / name
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target, filename=name)
