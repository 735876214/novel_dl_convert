"""收书目录的**入库前预览**（第 224 期）：名字 / 封面 / 查重 —— **只读**。

本期补的是「投递之后、入库之前」那一段的可见性：用户原先只能等条目变成「就绪」，
再去书库里核对。预览让这三件事**入库前**就能看到。

这里钉四件事：

1. **落点名与实际落盘同一份判据**（`publish.relpath_for`）—— 预览名与实际名各说各话
   是最难查的一类缺陷；
2. **查重只提示、不拦截**（收书目录的语义是「用户已经决定要收」）；
3. **坏文件也能预览**（预览是「尽力给信息」，不能因一个怪文件炸掉）；
4. **没指定目标库时不猜**（预览名必须有来源）。
"""
from __future__ import annotations

import json
import pathlib

from novelforge.core import db, dockpreview, library


def _write_epub(path: pathlib.Path, title: str = "预览书", author: str = "作者甲",
                isbn: str = "") -> pathlib.Path:
    """造一本最小 EPUB（带 OPF 元数据）。"""
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:identifier id="uid">{isbn or 'test-uuid'}</dc:identifier>
    <dc:language>zh</dc:language>
  </metadata>
  <manifest><item id="c1" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="c1"/></spine>
</package>
"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/c.xhtml", "<html><body>x</body></html>")
    return path


class _FakeWatcher:
    """只提供 `input_dir` —— 预览只用它定位投递目录里的文件。"""

    def __init__(self, root: pathlib.Path):
        self.input_dir = root


def _seed_dock(root: pathlib.Path, name: str = "预览.epub") -> str:
    """在投递目录里放一个文件，并在 dock 表登记它。"""
    src = root / name
    _write_epub(src)
    db.dock_upsert(name, name, ext=".epub", size=src.stat().st_size, status="pending")
    return name


# ---------------------------------------------------------------------------
# 纯函数：元数据探测与查重
# ---------------------------------------------------------------------------

def test_探测元数据_坏文件不抛(tmp_path):
    """坏 EPUB ⇒ 空元数据（预览要能继续，不能因一个坏文件炸掉）。

    ⚠️ 第 233 期修：原用例把**开发者本机的绝对路径**写死
    （`C:/Users/qingr/AppData/Local/Temp/nf-bad.epub`）⇒ 本机绿、**CI（Linux）必红**
    （`FileNotFoundError`，见 CI run 41388057583）。改用 pytest 的 `tmp_path` 夹具。
    """
    bad = tmp_path / "坏文件.epub"
    bad.write_bytes(b"not a zip")
    meta = dockpreview._probe_meta(bad)
    assert meta == {} or meta.get("unparsable")


def test_查重_同书名同作者算重复(client, auth_headers, isolated, tmp_path,
                              make_library, make_book):
    """同作者 + 书名完全相同 ⇒ 命中重复。"""
    make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    make_book(tmp_path / "lib", "同名书.epub")
    library.invalidate()
    # 夹具书是占位 EPUB（没有 OPF 元数据）⇒ 用覆盖层给它书名 / 作者
    bid = library.books("lib$1")[0]["id"]
    db.set_override(bid, "title", "同名书")
    db.set_override(bid, "author", "作者甲")
    library.invalidate()

    lib = library.get_library("lib$1")
    prev = {"title": "同名书", "author": "作者甲"}
    out = dockpreview.find_duplicates(prev, lib)
    assert out, out
    assert any("书名与作者完全相同" in r for d in out for r in d["reasons"])


def test_查重_没有书名就不查():
    """读不出书名 ⇒ 不给重复候选（不拿空书名去比）。"""
    lib = {"id": "lib$1", "name": "主书库"}
    assert dockpreview.find_duplicates({"title": "", "author": "作者甲"}, lib) == []


# ---------------------------------------------------------------------------
# 接口：GET /api/book-dock/{id}/preview
# ---------------------------------------------------------------------------

def test_预览接口_给出落点名与元数据(client, auth_headers, isolated, tmp_path,
                                   make_library):
    lib = make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    name = _seed_dock(tmp_path / "input")

    r = client.get(f"/api/book-dock/{name}/preview", headers=auth_headers,
                   params={"library_id": "lib$1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item_id"] == name
    assert body["title"] == "预览书"
    assert body["author"] == "作者甲"
    # 落点名按**目标库的命名规则**算（与实际落盘同一份判据）
    assert body["target_rel"], body
    assert body["target_rel"].endswith(".epub")
    assert body["target_library"] == "lib$1"


def test_预览接口_没指定目标库时不猜(client, auth_headers, isolated, tmp_path,
                                     make_library):
    make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    name = _seed_dock(tmp_path / "input")
    r = client.get(f"/api/book-dock/{name}/preview", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # 没给库 ⇒ 不算落点名，但**如实说明为什么**
    assert body["target_rel"] == ""
    assert any("书库" in w for w in body["warnings"]), body["warnings"]


def test_预览接口_条目不存在_404(client, auth_headers, isolated):
    r = client.get("/api/book-dock/根本没有这个.epub/preview", headers=auth_headers)
    assert r.status_code == 404


def test_预览接口_坏文件也能预览(client, auth_headers, isolated, tmp_path,
                                 make_library):
    """坏 EPUB ⇒ 预览仍返回（书名读不出 ⇒ 如实说），不 500。"""
    make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    src = tmp_path / "input" / "坏的.epub"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"not a zip")
    db.dock_upsert("坏的.epub", "坏的.epub", ext=".epub", size=src.stat().st_size,
                   status="needs_review")

    r = client.get("/api/book-dock/坏的.epub/preview", headers=auth_headers,
                   params={"library_id": "lib$1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == ""
    assert any("书名" in w for w in body["warnings"]), body["warnings"]


def test_预览不写库(client, auth_headers, isolated, tmp_path, make_library):
    """预览是**只读**的：跑完 dock 表与书目都不该变。"""
    make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    name = _seed_dock(tmp_path / "input")
    before = db.dock_get(name)
    books_before = len(library.books("lib$1"))

    client.get(f"/api/book-dock/{name}/preview", headers=auth_headers,
               params={"library_id": "lib$1"})

    assert db.dock_get(name) == before
    assert len(library.books("lib$1")) == books_before
