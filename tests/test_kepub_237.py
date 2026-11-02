"""KEPUB 导出（第 237 期）—— 给 Kobo 用的 EPUB 副本。

## 三条纪律（各有用例）

1. **源文件只读**：导出全程只 `read`，源书**一个字节不改**；
2. **Kobo 要的三样东西都在**：`META-INF/encryption.xml`（无 DRM）、
   `META-INF/com.apple.ibooks.display-options.xml`、OPF 里的 `dcterms:modified`；
3. **`mimetype` 仍是第一个条目且不压缩**（EPUB 规范 —— 压了或换序，部分阅读器直接打不开）。

另外：**目标与源同一个文件 ⇒ 拒绝**（那会把源书改坏）。
"""
from __future__ import annotations

import pathlib
import zipfile

import pytest

from novelforge.core import kepub


def _make_epub(path: pathlib.Path, with_encryption: bool = False) -> pathlib.Path:
    """造一本最小 EPUB（够 Kobo 那边读）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    opf = ('<?xml version="1.0" encoding="utf-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
           'unique-identifier="uid">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:title>测试书</dc:title><dc:identifier id="uid">u1</dc:identifier>'
           '<dc:language>zh</dc:language></metadata>'
           '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
           '<spine><itemref idref="c1"/></spine></package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/c1.xhtml", "<html><body>x</body></html>")
        if with_encryption:
            z.writestr("META-INF/encryption.xml", "<encryption>旧的</encryption>")
    return path


def test_导出后有三样_kobo_要的东西(tmp_path):
    src = _make_epub(tmp_path / "a.epub")
    dest = kepub.export_kepub(src, tmp_path / "a.kepub.epub")
    with zipfile.ZipFile(dest) as z:
        names = set(z.namelist())
        assert "META-INF/encryption.xml" in names
        assert "META-INF/com.apple.ibooks.display-options.xml" in names
        opf = z.read("OEBPS/content.opf").decode("utf-8")
        assert "dcterms:modified" in opf
        assert "dcterms:date" in opf


def test_源文件一个字节不改(tmp_path):
    """⚠️ 源是**只读**的 —— 导出不能碰它。"""
    src = _make_epub(tmp_path / "a.epub")
    before = src.read_bytes()
    kepub.export_kepub(src, tmp_path / "out.kepub.epub")
    assert src.read_bytes() == before


def test_源里已有的_encryption_不照抄(tmp_path):
    """⚠️ 照抄对方的 encryption.xml 会把「无 DRM」声明变成别的东西。"""
    src = _make_epub(tmp_path / "a.epub", with_encryption=True)
    dest = kepub.export_kepub(src, tmp_path / "a.kepub.epub")
    with zipfile.ZipFile(dest) as z:
        enc = z.read("META-INF/encryption.xml").decode("utf-8")
    assert "旧的" not in enc
    assert "EncryptedData" in enc


def test_mimetype_仍是第一个且不压缩(tmp_path):
    """⚠️ EPUB 规范：`mimetype` 必须是**第一个**条目且**不压缩**。"""
    src = _make_epub(tmp_path / "a.epub")
    dest = kepub.export_kepub(src, tmp_path / "a.kepub.epub")
    with zipfile.ZipFile(dest) as z:
        infos = z.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED


def test_目标与源同文件要拒绝(tmp_path):
    src = _make_epub(tmp_path / "a.epub")
    with pytest.raises(ValueError):
        kepub.export_kepub(src, src)


def test_源不存在如实报错(tmp_path):
    with pytest.raises(FileNotFoundError):
        kepub.export_kepub(tmp_path / "没有.epub", tmp_path / "out.epub")


def test_按书导出_非_epub_如实说明(client, auth_headers, isolated, tmp_path,
                                   make_library, make_book):
    """Kobo 读不了 PDF / 漫画 / 有声书 ⇒ 如实说，不导出一个打不开的文件。"""
    make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    make_book(tmp_path / "lib", "书.pdf", b"%PDF-1.4")
    from novelforge.core import library
    library.invalidate()
    bid = library.books("lib$1")[0]["id"]
    res = kepub.export_book(bid)
    assert res["ok"] is False
    assert "EPUB" in res["message"]
