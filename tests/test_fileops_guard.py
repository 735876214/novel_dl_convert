"""路径安全边界（`core/fileops.py`）。

`safe_path` 是「工具页会真动磁盘」这条链路的**唯一闸门**：改名、回收、整理布局
都要先过它。多书库之后它的基根变成「该书所属库根」，于是多了一类新风险 ——
**跨库穿越**（拿 A 库的库根去解析 B 库的文件）。本文件正反例都钉。

⚠️ 比较路径时统一 `.resolve()`：macOS 的 `/tmp` 是 `/private/tmp` 的符号链接，
不 resolve 会假失败。
"""
import pathlib

import pytest

from novelforge import config
from novelforge.core import fileops, library


def _p(*parts) -> pathlib.Path:
    return pathlib.Path(*parts).resolve()


# ---------------------------------------------------------------------------
# 正常路径
# ---------------------------------------------------------------------------

def test_平铺文件名(isolated, default_root):  # noqa: ARG001
    assert fileops.safe_path("三体.epub") == _p(default_root, "三体.epub")


def test_允许一层系列目录(isolated, default_root):  # noqa: ARG001
    """Komga 布局是 `系列名/书`，所以要放开一层；再深就一律拒绝。"""
    assert fileops.safe_path("三体/三体 #1.epub") == _p(default_root, "三体", "三体 #1.epub")


def test_反斜杠被当成路径分隔符(isolated, default_root):  # noqa: ARG001
    assert fileops.safe_path("三体\\三体 #1.epub") == _p(default_root, "三体", "三体 #1.epub")


# ---------------------------------------------------------------------------
# 安全负例：穿越 / 绝对路径 / 层级 / 非法字符
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "../etc/passwd",
    "a/../../etc",
    "../../../../etc/passwd",
    "系列/../../etc/passwd",
])
def test_拒绝上级目录穿越(isolated, bad):  # noqa: ARG001
    with pytest.raises(ValueError):
        fileops.safe_path(bad)


@pytest.mark.parametrize("bad", ["/etc/passwd", "/tmp/x.epub"])
def test_拒绝绝对路径(isolated, bad):  # noqa: ARG001
    with pytest.raises(ValueError):
        fileops.safe_path(bad)


def test_拒绝超深层级(isolated):  # noqa: ARG001
    with pytest.raises(ValueError):
        fileops.safe_path("a/b/c.epub")


@pytest.mark.parametrize("bad", [
    "", "   ",
    "a:b.epub", "a*b.epub", "a?b.epub", 'a"b.epub', "a|b.epub", "a<b>.epub", "a\x00b.epub",
])
def test_拒绝空名与非法字符(isolated, bad):  # noqa: ARG001
    with pytest.raises(ValueError):
        fileops.safe_path(bad)


# ---------------------------------------------------------------------------
# 多书库：基根由所属库决定
# ---------------------------------------------------------------------------

def test_按所属库解析路径(isolated, tmp_path, make_library):  # noqa: ARG001
    src = tmp_path / "libs"
    make_library("comic", "漫画库", "comic", src / "comics")

    assert fileops.safe_path("测试漫画.cbz", "comic") == _p(src, "comics", "测试漫画.cbz")
    # 不给 library_id → 默认库根（兼容既有单库调用方）
    assert fileops.safe_path("三体.epub") == _p(config.OUTPUT_DIR, "三体.epub")


def test_跨库穿越被拒(isolated, tmp_path, make_library):  # noqa: ARG001
    """拿漫画库的根去解析「跑到别的库」的路径必须被拒 —— 否则改名/回收会动到别的库。"""
    src = tmp_path / "libs"
    make_library("comic", "漫画库", "comic", src / "comics")

    with pytest.raises(ValueError):
        fileops.safe_path("../../output/三体.epub", "comic")
    with pytest.raises(ValueError):
        fileops.safe_path("../ebooks/三体.epub", "comic")


def test_两个库同名文件解析到各自库根(isolated, tmp_path, make_library):  # noqa: ARG001
    src = tmp_path / "libs"
    make_library("comic", "漫画库", "comic", src / "comics")
    make_library("ebook", "电子书库", "ebook", src / "ebooks")

    a = fileops.safe_path("同名.epub", "comic")
    b = fileops.safe_path("同名.epub", "ebook")
    assert a != b
    assert a.parent.name == "comics" and b.parent.name == "ebooks"


# ---------------------------------------------------------------------------
# 库归属判定（改名 / 回收都靠它把基根定对）
# ---------------------------------------------------------------------------

def test_库归属_回传优先(isolated, tmp_path, make_library):  # noqa: ARG001
    src = tmp_path / "libs"
    make_library("comic", "漫画库", "comic", src / "comics")
    assert fileops._lib_of("随便什么.epub", {"library_id": "comic"}) == "comic"


def test_库归属_按名反查回退(isolated, default_root, make_book, test_lib_id):  # noqa: ARG001
    make_book(default_root, "三体.epub")
    library.invalidate()
    assert fileops._lib_of("三体.epub", None) == test_lib_id
    assert fileops._lib_of("三体.epub", {}) == test_lib_id


def test_库归属_查不到时交给调用方兜底(isolated):  # noqa: ARG001
    # 不能瞎猜一个库：返回 None 让 safe_path 退回 OUTPUT_DIR（多库下猜错会改错文件）
    assert fileops._lib_of("不存在的书.epub", None) is None
