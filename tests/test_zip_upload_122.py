"""zip 上传与归库契约（第 122 期）。

**用户报的**：「zip 格式的书导入后不能识别」。查下来是**两处**各自独立的问题，
都会让同一份内容「存成 .cbz 能进、存成 .zip 进不去」：

1. **投递链路（后端，真缺陷）**：`_dispatch_into_library` 原来「先判落点、后落盘」——
   而通用容器（`.zip` / `.rar` / `.7z`）的形态**只能看内容**（`zipkind.analyze`），
   判落点那会儿文件还不存在 ⇒ 每个 zip 都被判成「没有可接收这个文件的书库」。
   现在改成「先写一份点号前缀的临时件 → 判完落点 → 原子改名成真名」，拒收时临时件删掉。
2. **本地转换页（前端，白名单漂移）**：见 `tests/test_upload_exts_contract.py`。

另外钉住「格式 → 库类型」的唯一真值源：`library.type_for_ext()`。此前
`library_rules` 自抄了一份元组、漏了 `.azw`，于是 `.azw` 上传过得了
`pipeline.EBOOK_EXT` 那一关、却在归库时判不出类型而被拒收。
"""

from __future__ import annotations

import base64
import pathlib
import zipfile

import pytest

from novelforge import config, server
from novelforge.core import db, library

# 1×1 的合法 PNG（不引 Pillow，避免用例依赖图片库的编码结果）
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _comic_zip(tmp_path: pathlib.Path, name: str = "漫画上传.zip") -> pathlib.Path:
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("01.png", _PNG)
        z.writestr("02.png", _PNG)
    return p


def _upload(client, headers, path: pathlib.Path, name: str):
    return client.post(
        "/convert",
        files={"file": (name, path.read_bytes())},
        headers=headers,
    )


def test_type_for_ext_是格式到类型的唯一真值源():
    assert library.type_for_ext(".azw") == "ebook"
    assert library.type_for_ext(".AZW3") == "ebook"
    assert library.type_for_ext("epub") == "ebook"
    assert library.type_for_ext(".cbz") == "comic"
    assert library.type_for_ext(".mp3") == "audiobook"
    # `.pdf` / 容器类后缀同时出现在漫画与电子书白名单里：按电子书算（漫画靠内容判）
    assert library.type_for_ext(".pdf") == "ebook"
    assert library.type_for_ext(".zip") == "ebook"
    # 认不出来就空串（调用方走「不按格式路由」，如实拒收，不猜）
    assert library.type_for_ext(".docx") == ""
    assert library.type_for_ext("") == ""


def test_漫画zip上传进漫画库(client, auth_headers, make_library, tmp_path):
    """修前：同样内容存成 `.cbz` 能进、存成 `.zip` 一律 400（判落点时文件还不存在）。"""
    make_library("comic1", "漫画库", "comic", tmp_path / "libraries" / "漫画库")
    r = _upload(client, auth_headers, _comic_zip(tmp_path), "漫画上传.zip")
    assert r.status_code == 200, r.text
    books = client.get("/api/books", headers=auth_headers).json()["items"]
    names = [b["name"] for b in books]
    assert "漫画上传.zip" in names


def test_漫画zip在只有电子书库时说出识别结果(client, auth_headers, tmp_path, monkeypatch):
    """没有漫画库时不能只说「规则都不命中」—— 要说清「这是图片包、要有漫画库」。"""
    db.update_library("default", type="ebook")
    library.invalidate()
    r = _upload(client, auth_headers, _comic_zip(tmp_path), "漫画上传.zip")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "图片" in detail, detail
    assert "漫画" in detail, detail
    assert "张图片" in detail, detail


def test_上传被拒后不留临时件(client, auth_headers, tmp_path):
    """拒收路径必须把点号临时件删掉 —— 否则收书目录里每轮扫描都会撞见一个孤儿。"""
    db.update_library("default", type="ebook")
    library.invalidate()
    inp = pathlib.Path(server.INPUT_DIR)
    r = _upload(client, auth_headers, _comic_zip(tmp_path), "漫画上传.zip")
    assert r.status_code == 400
    leftovers = [p.name for p in inp.iterdir() if p.name.startswith(".upload-")]
    assert leftovers == [], leftovers


def test_上传的临时件不会以真名留下半成品(client, auth_headers, make_library, tmp_path):
    """成功路径也必须只剩真名那一份（临时件是原子改名走的，不该有第二个文件）。"""
    make_library("comic2", "漫画库", "comic", tmp_path / "libraries" / "漫画库")
    r = _upload(client, auth_headers, _comic_zip(tmp_path), "漫画上传.zip")
    assert r.status_code == 200, r.text
    inp = pathlib.Path(server.INPUT_DIR)
    names = sorted(p.name for p in inp.iterdir())
    assert names == ["漫画上传.zip"], names


def test_azw上传不再被判没有库(client, auth_headers, make_library, tmp_path):
    """`.azw` 第 110 期就进了 `pipeline.EBOOK_EXT`，但归库侧漏了它 → 上传直接 400。"""
    make_library("ebook1", "电子书库", "ebook", tmp_path / "libraries" / "电子书库")
    r = client.post(
        "/convert",
        files={"file": ("某书.azw", b"not-a-real-mobi-but-the-suffix-is-what-matters")},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("ext", [".zip", ".rar", ".7z"])
def test_容器后缀都在后端允许集里(ext):
    from novelforge.core import pipeline

    assert ext in pipeline.EBOOK_EXT
    assert ext in library.BOOK_EXTS
