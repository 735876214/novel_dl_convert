"""`.zip` 内容分派（第 87 期）：**容器看内容，不看后缀**。

⚠️ 这些用例自己造 zip，不用仓库里的样本文件 —— 分派的全部要点就在「后缀相同、
内容不同」，靠固定样例会越测越像在测那个样本本身。

零网络：全部是本机文件读写。
"""
import zipfile

from novelforge.core import comics, library, zipkind


def _zip(path, entries):
    """造一个 zip（`entries` = [(条目名, 字节)]）。"""
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return path


def _image_zip(path, n=3):
    return _zip(path, [(f"{i:03d}.jpg", b"JPG") for i in range(1, n + 1)])


# ---------------- 判定本身（纯函数）----------------

def test_图片档判成漫画且可读(tmp_path):
    v = zipkind.analyze(_image_zip(tmp_path / "x.zip", 5))
    assert v["kind"] == "comic" and v["readable"] is True
    assert v["format"] == "CBZ"
    assert v["evidence"]["images"] == 5


def test_改了后缀的_epub_如实报需要展开(tmp_path):
    """容器内有 `mimetype` / `container.xml` ⇒ 它其实是一份 EPUB（只是改了后缀）。

    这一档**不能假装能读**：认成 EPUB 会让前端去开 EPUB 阅读器，而文件本身
    打不开 —— 那就是「入口在、点了失败」的静默失败。
    """
    p = _zip(tmp_path / "书.zip", [
        ("mimetype", b"application/epub+zip"),
        ("META-INF/container.xml", b"<container/>"),
        ("OEBPS/cover.jpg", b"JPG"),
    ])
    v = zipkind.analyze(p)
    assert v["kind"] == "epub" and v["readable"] is False and v["needs_unwrap"] is True
    assert "展开" in v["reason"]


def test_内部恰好一份_pdf_报需要展开(tmp_path):
    v = zipkind.analyze(_zip(tmp_path / "a.zip", [("内页.pdf", b"%PDF-1.4")]))
    assert v["kind"] == "pdf" and v["format"] == "PDF" and v["needs_unwrap"] is True


def test_内层还是压缩包_报需要展开(tmp_path):
    v = zipkind.analyze(_zip(tmp_path / "b.zip", [("inner.cbz", b"PK\x03\x04")]))
    assert v["kind"] == "nested" and v["needs_unwrap"] is True and "压缩包" in v["reason"]


def test_图文混装与多份文档都判不出_不猜(tmp_path):
    mixed = zipkind.analyze(_zip(tmp_path / "m.zip",
                                [("001.jpg", b"JPG"), ("a.pdf", b"%PDF")]))
    assert mixed["kind"] == "mixed" and mixed["readable"] is False
    assert "不猜" in mixed["reason"]
    multi = zipkind.analyze(_zip(tmp_path / "n.zip",
                                 [("a.pdf", b"%PDF"), ("b.epub", b"PK")]))
    assert multi["kind"] == "multi" and multi["readable"] is False


def test_坏包与空包(tmp_path):
    """坏包如实报、空包如实报 —— 两者都**不抛异常**（与 comics.probe 同口径）。"""
    broken = tmp_path / "broken.zip"
    broken.write_bytes("这不是压缩包".encode("utf-8"))
    v = zipkind.analyze(broken)
    assert v["kind"] == "broken" and v["readable"] is False
    empty = zipfile.ZipFile(tmp_path / "empty.zip", "w")
    empty.close()
    v2 = zipkind.analyze(tmp_path / "empty.zip")
    assert v2["kind"] == "empty" and v2["readable"] is False


def test_垃圾条目不算内容(tmp_path):
    """`__MACOSX/` 与隐藏文件不算「里面有什么」（与取页同一套过滤）。"""
    p = _zip(tmp_path / "j.zip", [("__MACOSX/._001.jpg", b"x"), (".DS_Store", b"x")])
    assert zipkind.analyze(p)["kind"] == "empty"


# ---------------- 与库扫描的接线 ----------------

def test_漫画库里被扫到且归一成_cbz(tmp_path):
    """`.zip`（图片档）在漫画库里与 `.cbz` 同等待遇：format 归一到 CBZ、页数真实、有封面。"""
    _image_zip(tmp_path / "漫画.zip", 7)
    got = library._iter_book_entries(tmp_path, library._COMIC_EXTS, None, "comic")
    assert [f.name for f in got] == ["漫画.zip"], "白名单必须收 .zip，否则用户看不见自己的书"
    p = library._probe_entry(got[0])
    assert p["format"] == "CBZ", "归一成真实形态，上层（封面/页接口/阅读器）才能零分支"
    assert p["pages"] == 7 and p["pages_source"] == "archive" and p["has_cover"] is True
    assert p["unparsable"] is False
    # 真的读得出来（第 0 页 = 封面那张）
    data, media = comics.page_bytes(got[0], 0)
    assert data == b"JPG" and media.startswith("image/")


def test_内部是别的文档的_zip_不假装能读(tmp_path):
    """不能读的 zip **照样入库**（否则文件在盘上、书目里找不到 = 隐形文件），
    但必须显式记成「无法解析」，让它出现在「待修复」里。"""
    _zip(tmp_path / "包.zip", [("mimetype", b"application/epub+zip"),
                              ("META-INF/container.xml", b"<container/>")])
    got = library._iter_book_entries(tmp_path, library._COMIC_EXTS, None, "comic")
    p = library._probe_entry(got[0])
    assert p["unparsable"] is True
    assert p["format"] == "ZIP", "不能报成 EPUB：那会让前端去开一个打不开的阅读器"
    assert p["pages"] == 0


def test_页序是自然序不是字典序(tmp_path):
    p = _image_zip(tmp_path / "s.zip", 12)
    with comics._open(str(p)) as arc:
        names = [n for n, _ in arc.entries()]
    assert names[1].endswith("002.jpg") and names[-1].endswith("012.jpg")


def test_三类库的白名单都收_zip(tmp_path):  # noqa: ARG001
    """需求「格式支持一致性」：容器在三类库里都要能被扫到（收进来后再按内容分派形态）。"""
    for t in ("comic", "ebook", "mixed"):
        assert ".zip" in library._exts_for_type(t), f"{t} 库漏收 .zip"


def test_原有_cbz_行为不变(tmp_path):
    """.zip 上线不能动到 .cbz 的老行为（同一套解析，但白名单与判定路径都改过）。"""
    _image_zip(tmp_path / "老.cbz", 4)
    got = library._iter_book_entries(tmp_path, library._COMIC_EXTS, None, "comic")
    p = library._probe_entry(got[0])
    assert p["format"] == "CBZ" and p["pages"] == 4 and p["unparsable"] is False
