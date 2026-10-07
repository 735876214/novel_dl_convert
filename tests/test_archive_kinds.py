"""`.rar` / `.7z` 容器按内容分派（第 111 期）：与 `.zip` 同一套判据，只是换了个壳。

需求来源：`User said (m00001)：梳理增加对 mobi、zip、rar等格式书籍直接阅读的能力` ——
第 110 期交付了 MOBI 直读，本期补齐**容器**这一半（`.zip` 第 87 期已在）。

⚠️ 用例**自己造归档、不用样本文件**（理由同 `tests/test_zip_dispatch.py`：分派的全部要点就在
「后缀相同、内容不同」，固定样例会越测越像在测那个样本）：

- **`.7z` 能真造**（`py7zr` 可写）⇒ 分派 / 归一成 CBZ / 页字节 / 展开落盘**整条链路真跑**；
- **`.rar` 造不出来**（`rarfile` 只读，写要 rar 归档器；本机虽装了 WinRAR，但 `rarfile`
  找不到可用的外部解压器 —— 实测 `tool_setup()` 抛 `RarCannotExec`）⇒ `.rar` 只测
  **能力缺失时的诚实路径**与判定档位，绝不伪造一个「读过 RAR」的结论；
- 缺 `py7zr` 的情形用 monkeypatch 模拟（本机装着它，否则那条分支测不到）。

零网络：全部是本机文件读写。
"""
import pathlib

import pytest

py7zr = pytest.importorskip("py7zr", reason="`.7z` 后端未安装 ⇒ 如实跳过，不伪造能读")

from novelforge.core import comics, library, zipkind  # noqa: E402


def _7z(path, entries):
    """造一个 7z（`entries` = [(条目名, 字节)]）。

    ⚠️ `py7zr.SevenZipFile.writestr` 的参数顺序是 ``(data, arcname)`` —— 与 ``zipfile``
    相反（实测踩过：写成 zipfile 的顺序会抛 `TypeError: argument should be a str…`）。
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(data, name)
    return path


def _image_7z(path, n=3):
    return _7z(path, [(f"{i:03d}.jpg", b"JPG") for i in range(1, n + 1)])


def _fake_rar(path, *, body=b"\x00" * 64):
    """一个**只有魔数像 RAR** 的文件（够用来测「缺能力」的文案与判定档位）。"""
    path = pathlib.Path(path)
    path.write_bytes(b"Rar!\x1a\x07\x00" + body)
    return path


# ---------------- 判定本身 ----------------

def test_7z图片档判成漫画且可读(tmp_path):
    """`.7z` 里是图片序列 ⇒ 与 `.cbz` 完全同等待遇（页序 / 封面 / 逐页接口全部复用）。"""
    v = zipkind.analyze(_image_7z(tmp_path / "x.7z", 5))
    assert v["kind"] == "comic" and v["readable"] is True
    assert v["format"] == "CBZ"
    assert v["evidence"]["images"] == 5


def test_7z_的容器自身标签是_7Z(tmp_path):
    """**判不出形态时 format 必须是容器自身**（`ZIP` / `RAR` / `7Z`）。

    它决定「待展开清单」筛不筛得到这本书（`library.container_books`）—— 第 111 期之前
    `analyze` 这里写死 `"ZIP"`，`.rar` / `.7z` 一进来就会**从清单里消失**，
    而且界面上一个字都不提。
    """
    multi = zipkind.analyze(_7z(tmp_path / "两本.7z", [("a.pdf", b"%PDF"), ("b.pdf", b"%PDF")]))
    assert multi["kind"] == "multi" and multi["format"] == "7Z" and multi["needs_unwrap"] is True
    nested = zipkind.analyze(_7z(tmp_path / "套.7z", [("inner.zip", b"PK\x03\x04")]))
    assert nested["kind"] == "nested" and nested["format"] == "7Z"
    assert zipkind.CONTAINER_FORMATS == ("ZIP", "RAR", "7Z"), "清单由 CONTAINER_EXTS 派生"


def test_7z内部是文档时如实报需要展开(tmp_path):
    p = _7z(tmp_path / "内页.7z", [("mimetype", b"application/epub+zip"),
                                  ("META-INF/container.xml", b"<container/>")])
    v = zipkind.analyze(p)
    assert v["kind"] == "epub" and v["readable"] is False and v["needs_unwrap"] is True
    assert "展开" in v["reason"]


def test_坏_7z_不抛异常(tmp_path):
    broken = tmp_path / "broken.7z"
    broken.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 32)
    v = zipkind.analyze(broken)                       # 魔数对、内容坏
    assert v["kind"] == "broken" and v["readable"] is False


# ---------------- 缺能力：必须如实，不许静默 ----------------

def test_缺py7zr时如实报缺能力而不是坏包(tmp_path, monkeypatch):
    """**本期最容易写错的一条**：缺 `py7zr` 时若只走 `except`，用户看到的是
    「不是可读的压缩包（ModuleNotFoundError）」⇒ 他会去怀疑自己的文件。"""
    p = _image_7z(tmp_path / "漫画.7z", 3)
    monkeypatch.setattr(comics, "seven_available", lambda: False)

    assert "py7zr" in comics.backend_problem(p)
    v = zipkind.analyze(p)
    assert v["kind"] == "broken" and "py7zr" in v["reason"]
    assert zipkind.unpack_plan(p)["ok"] is False
    # ⚠️ 这里**只**模拟「能力判据说不可用」，`py7zr` 本身仍在 sys.modules 里 ⇒ `comics.pages`
    # 照样列得出条目。真实缺包时 `_open` 会抛（也被 `analyze` 的 except 接住、由上面的
    # 能力判据给出可读文案），而**接口侧**一律先过 `backend_problem` ⇒ 503，不会静默回空页。


def test_缺RAR工具时说缺什么_而坏包不说缺(tmp_path, monkeypatch):
    fake = _fake_rar(tmp_path / "坏.rar")
    monkeypatch.setattr(comics, "rar_available", lambda: False)
    assert "bsdtar" in comics.backend_problem(fake)
    assert "bsdtar" in zipkind.analyze(fake)["reason"]

    # 工具**在**的时候，同一个坏文件不该被说成「缺能力」—— 那是两码事，文案必须分开
    monkeypatch.setattr(comics, "rar_available", lambda: True)
    assert comics.backend_problem(fake) == ""
    assert "bsdtar" not in zipkind.analyze(fake)["reason"]


def test_魔数认不出时按后缀判能力(tmp_path, monkeypatch):
    """半截下载 / 占位文件魔数落空，但后缀已经说明它需要哪个后端 —— 那时该先报能力。"""
    p = tmp_path / "占位.cbr"
    p.write_bytes(b"")                                  # 0 字节：魔数什么都认不出
    monkeypatch.setattr(comics, "rar_available", lambda: False)
    assert "bsdtar" in comics.backend_problem(p)


# ---------------- 与库扫描 / 阅读链路的接线 ----------------

def test_漫画库里_7z_被扫到且归一成_cbz(tmp_path):
    _image_7z(tmp_path / "漫画.7z", 7)
    got = library._iter_book_entries(tmp_path, library._COMIC_EXTS, None, "comic")
    assert [f.name for f in got] == ["漫画.7z"], "白名单必须收 .7z，否则用户看不见自己的书"
    p = library._probe_entry(got[0])
    assert p["format"] == "CBZ", "归一成真实形态，上层（封面/页接口/阅读器）才能零分支"
    assert p["pages"] == 7 and p["pages_source"] == "archive" and p["has_cover"] is True
    assert p["unparsable"] is False
    data, media = comics.page_bytes(got[0], 0)          # 真的读得出来（7z 的内存工厂路径）
    assert data == b"JPG" and media.startswith("image/")


def test_三类库的白名单都收_rar与_7z(tmp_path):  # noqa: ARG001
    for t in ("comic", "ebook", "mixed"):
        for ext in (".rar", ".7z"):
            assert ext in library._exts_for_type(t), f"{t} 库漏收 {ext}"


def test_待展开清单认得_7z_容器(isolated, tmp_path, make_library):  # noqa: ARG001
    """`.7z` 里装的是文档 ⇒ 它该出现在「待展开的压缩包」里，且能说清展开后得到什么。"""
    root = tmp_path / "libs" / "ebook"
    make_library("ebook", "电子书库", "ebook", root)
    _7z(root / "两本.7z", [("a.pdf", b"%PDF-1.4"), ("b.pdf", b"%PDF-1.4")])
    library.invalidate()

    books = [b for b in library.books() if b["name"] == "两本.7z"]
    assert books, "容器必须入库（文件在盘上、书目里找不到 = 隐形文件）"
    assert str(books[0]["format"]).upper() == "7Z"
    # ⚠️ `books()` 给的是**卡片字段**（没有 `unparsable`）—— 那是探针的产物，要问 `_probe_entry`
    assert library._probe_entry(root / "两本.7z")["unparsable"] is True, \
        "分派不出形态 ⇒ 如实记「无法解析」"

    items = library.container_books()
    mine = [i for i in items if i["name"] == "两本.7z"]
    assert mine, f"待展开清单漏了 .7z 容器：{items}"
    assert mine[0]["unpackable"] is True
    assert sorted(mine[0]["targets"]) == ["a.pdf", "b.pdf"]


def test_7z展开真的落盘且源不动(tmp_path):
    """展开 = 逐条提取（`_Archive.read` 的 7z 分支）：原子写、不覆盖、不动源。"""
    p = _7z(tmp_path / "包.7z", [("a.pdf", b"%PDF-1.4"), ("b.pdf", b"%PDF-1.4")])
    before = p.read_bytes()

    res = zipkind.unpack(p)
    assert res["ok"] is True, res
    assert sorted(r["name"] for r in res["actions"]) == ["a.pdf", "b.pdf"]
    assert (tmp_path / "a.pdf").read_bytes() == b"%PDF-1.4"
    assert (tmp_path / "b.pdf").read_bytes() == b"%PDF-1.4"
    assert not list(tmp_path.glob("*.part")), "半成品不许留在盘上"
    assert p.read_bytes() == before, "默认不动源容器（第 96 期起回收也只是移入回收站）"

    again = zipkind.unpack(p)                            # 撞名：跳过并如实报，不覆盖
    assert again["ok"] is False
    assert all("已存在" in r["note"] for r in again["actions"])
