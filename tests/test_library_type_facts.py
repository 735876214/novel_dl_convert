"""第 86 期：重建书库时按**文件夹里真实装的东西**校正类型 / 白名单。

用户报的缺陷：对同一个漫画文件夹「先删库、再添加回来」，库里读不到任何内容，
而**本地原件还在原位置**。根因：库配置不会随文件夹复原 —— 向导默认
``type='ebook'``，而 ``_EBOOK_EXTS`` 不含 ``.cbz/.cbr``；目录型漫画还要求
``type∈{comic,audiobook}`` 才会被合并成一本书。

口径（**只在会变成空库时动手**，正常配置一概不碰）：
1. 目录里有本库白名单收得下的文件 ⇒ 原样返回；
2. 一个都收不下、但目录里确实有媒体 ⇒ 按实际内容补白名单；目录型（≥2 个单元文件一层）
   ⇒ 同时把类型校正为 comic / audiobook；
3. 目录本来就是空的 ⇒ 原样返回（不猜）。
"""
import pathlib

from novelforge import server
from novelforge.core import comics


def _cbz(p: pathlib.Path) -> pathlib.Path:
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    return p


def test_只有cbz而类型是ebook时按事实校正(tmp_path):
    """**用户报的那一种**：文件夹里全是 .cbz，库类型是 ebook ⇒ 一本都读不到。"""
    _cbz(tmp_path / "第一卷.cbz")
    _cbz(tmp_path / "第二卷.cbz")
    ltype, exts = server._fix_empty_library("ebook", "", [str(tmp_path)])
    assert ".cbz" in server.library.parse_exts(exts), "漫画扩展名必须进白名单，否则书架永远是空的"
    eff = server.library.exts_for_library({"type": ltype, "allowed_exts": exts})
    assert ".cbz" in eff, "校正后的配置必须真的能收下 .cbz"


def test_正常配置一概不碰(tmp_path):
    """目录里有 epub（白名单收得下）⇒ 不许动用户的类型与白名单。"""
    (tmp_path / "书.epub").write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    _cbz(tmp_path / "漫画.cbz")
    before = ("ebook", "")
    assert server._fix_empty_library(*before, [str(tmp_path)]) == before, \
        "非空库不该被改配置（否则就是「我以为我没改，其实被改了」）"


def test_空目录不猜(tmp_path):
    assert server._fix_empty_library("ebook", "", [str(tmp_path)]) == ("ebook", "")
    assert server._fix_empty_library("ebook", "", []) == ("ebook", "")
    assert server._fix_empty_library("ebook", "", ["/根本没有这个目录"]) == ("ebook", "")


def test_目录型漫画要同时校正类型(tmp_path):
    """目录型漫画（一层里多个 .cbz 单元）只有 comic/audiobook 才会被合并成一本书。"""
    d = tmp_path / "某漫画"
    d.mkdir()
    _cbz(d / "第1话.cbz")
    _cbz(d / "第2话.cbz")
    ltype, exts = server._fix_empty_library("ebook", "", [str(tmp_path)])
    assert ltype == "comic", "目录型内容必须把类型校正到合并得起来的那个"
    assert ".cbz" in server.library.parse_exts(exts)


def test_有声书目录校正成audiobook(tmp_path):
    d = tmp_path / "某有声书"
    d.mkdir()
    for n in (1, 2):
        (d / f"第{n}话.mp3").write_bytes(b"ID3\x03\x00" + b"\x00" * 16)
    ltype, _ = server._fix_empty_library("ebook", "", [str(tmp_path)])
    assert ltype == "audiobook"


def test_显式白名单不被无端扩大(tmp_path):
    """用户**显式**配了白名单 ⇒ 说明是有意过滤；但仍不许出现「配置收不下、目录里全是它」。"""
    _cbz(tmp_path / "漫画.cbz")
    ltype, exts = server._fix_empty_library("comic", ".cbz", [str(tmp_path)])
    assert (ltype, exts) == ("comic", ".cbz"), "本来就收得下 ⇒ 一个字都不改"
    assert comics.is_comic(tmp_path / "漫画.cbz")
