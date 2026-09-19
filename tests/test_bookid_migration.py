"""第 17 期 T1：book_id 库维度化 + 一次性迁移。

旧 id = basename 的 12 位哈希；新 id = ``库$哈希``。迁移要把 progress / annotations /
ratings / reading_status / collection_items / reading_sessions / koreader_docs 里
按旧 id 存的行搬到新 id；跨库同名从此得到两个不同 id，进度 / 批注互不串。
"""
import hashlib
import pathlib

import pytest

from novelforge import config
from novelforge.core import db, library


def _legacy_id(name: str) -> str:
    """旧 id 算法（迁移时按文件名 basename 反算，不依赖当前 _book_id 定义）。"""
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 跨库同名：得到两个不同 id（核心新行为）
# ---------------------------------------------------------------------------

def test_cross_library_same_name_gets_distinct_ids(isolated, make_library, make_book, tmp_path):
    a, b = "lib-a", "lib-b"
    root_a = tmp_path / "libraries" / a
    root_b = tmp_path / "libraries" / b
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "三体.epub")
    make_book(root_b, "三体.epub")
    library.invalidate()

    ids = {x["id"] for x in library.books() if x["name"].endswith("三体.epub")}
    assert len(ids) == 2, "跨库同名必须得到两个不同 id"
    for bid in ids:
        assert "$" in bid, "新 id 形如 库$哈希"
    # by_id 不再因跨库同名抛 BookIdConflict
    for bid in ids:
        assert library.by_id(bid) is not None


def test_scan_id_is_library_scoped(isolated, make_library, make_book, tmp_path):
    a = "lib-a"
    root_a = tmp_path / "libraries" / a
    make_library(a, "甲库", "ebook", root_a)
    make_book(root_a, "三体.epub")
    library.invalidate()

    bid = library.book_id("三体.epub", a)
    assert bid == f"{a}${_legacy_id('三体.epub')}", "扫描侧 id 带库前缀"
    assert library.book_id("三体.epub") == _legacy_id("三体.epub"), \
        "不带库时退化成旧算法（仅迁移反查用）"


# ---------------------------------------------------------------------------
# 一次性迁移：把按旧 id 存的关联行搬到新 id
# ---------------------------------------------------------------------------

def test_upgrade_book_ids_remaps_association_rows(isolated, make_book):
    root = pathlib.Path(config.OUTPUT_DIR)
    make_book(root, "三体.epub")
    legacy = _legacy_id("三体.epub")
    new_id = f"default${legacy}"

    # 模拟迁移前的关联数据（按旧 id 写）
    db.set_progress(legacy, 7, 33.0)
    db.set_rating(legacy, 5)

    res = db.upgrade_book_ids()
    assert res["skipped"] is False
    assert res["moved"] >= 2, "progress + rating 都搬了"

    prog = db.get_progress(new_id)
    assert prog is not None and prog["locator"] == 7, "进度搬到新 id"
    assert db.get_progress(legacy) is None, "旧 id 不留残留"
    assert db.get_rating(new_id) == 5, "评分也搬到新 id"

    # 幂等：再跑一次应跳过
    res2 = db.upgrade_book_ids()
    assert res2["skipped"] is True


def test_upgrade_book_ids_handles_two_libraries(isolated, make_library, make_book, tmp_path):
    """两个库各放同名书，迁移后各自的关联数据落到各自的 库$旧id，互不串。"""
    a, b = "lib-a", "lib-b"
    root_a = tmp_path / "libraries" / a
    root_b = tmp_path / "libraries" / b
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "三体.epub")
    make_book(root_b, "三体.epub")

    legacy = _legacy_id("三体.epub")
    db.set_progress(legacy, 1, 10.0)  # 旧系统两本共用这一行（id 撞车）

    res = db.upgrade_book_ids()
    assert res["skipped"] is False

    # 迁移只能把这一行搬到一个库（旧系统本就分不清），但至少要落到某个 库$旧id
    moved = 0
    for lid in (a, b):
        if db.get_progress(f"{lid}${legacy}") is not None:
            moved += 1
    assert moved == 1, "旧系统的共用行迁移后归一到一个库（不再两本共享）"
    assert db.get_progress(legacy) is None
