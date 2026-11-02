"""书目列表热路径的两个优化（第 233 期）与它们的**口径不变**保证。

## 优化了什么（实测数据）

2309 本的库，`catalog.books_of()` 的耗时构成（`cProfile`）：

| 环节 | 优化前 | 优化后 |
|---|---|---|
| `_book_of_row` 里逐行 `str(pathlib.Path(root) / rel)` | **146 ms / 3 次**（占一半） | 拼字符串，不再逐行解析根路径 |
| `db.get_effective_meta` 逐字段试 `_META_FIELDS`（25 个） | 66 ms / 3 次 | 只遍历「真的有值」的字段 |
| 合计 `books_of` | 120 ms | **86 ms**（−28%） |

## 为什么要有这些用例

两处都是**「快路径」改动** —— 一旦归一口径变了，**定位会错**（`path` 是对外字段，
`/api/books/{bid}/local-paths` 等按它找文件），而那种错**不报错**、只在特定路径下现形。

所以这里钉两件事：

1. **拼出来的 path 与 `pathlib` 逐字相同**（含 Windows 的分隔符与盘符归一）；
2. **一个库有多个来源根时，各根下的同名文件各算各的**（第 41 期起 `source_dirs` 是数组）。
"""
from __future__ import annotations

import json
import os
import pathlib

from novelforge.core import catalog, db


def test_拼出来的_path_与_pathlib_逐字相同():
    """归一口径变了 ⇒ 对外的 `path` 就变了 ⇒ 定位会错。"""
    cases = [
        ("C:/books", "a/b.epub"),
        ("C:/books/", "x.epub"),
        ("C:\\books", "a/b.epub"),
        ("/srv/lib", "子/书.epub"),
        ("", "a.epub"),
    ]
    for root, rel in cases:
        want = str(pathlib.Path(root) / rel) if root else root
        prefix = catalog._root_prefix(root)
        got = os.path.join(prefix, rel.replace("/", os.sep)) if prefix else root
        assert got == want, (root, rel, want, got)


def test_多个来源根各算各的(isolated, tmp_path, make_library):
    """一个库有两个来源根、两本同名书 ⇒ 各自的 path 必须指向**自己那个根**。"""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "同名.epub").write_bytes(b"EPUB")
    (b / "同名.epub").write_bytes(b"EPUB")

    lib = make_library("multi", "多根库", "mixed", a)
    # ⚠️ 必须走 json.dumps（Windows 路径里的反斜杠在 JSON 里是转义符）
    db.update_library(lib["id"], source_dirs=json.dumps([str(a), str(b)], ensure_ascii=False))

    from novelforge.core import library

    library.invalidate()
    books = library.books(lib["id"])
    paths = sorted(x["path"] for x in books)
    assert len(paths) == 2, paths
    # 两个 path 必须落在**不同的根**下（同名文件不能都算成 a 根）
    assert str(a) in paths[0] or str(a) in paths[1], paths
    assert str(b) in paths[0] or str(b) in paths[1], paths
    assert paths[0] != paths[1], paths


def test_有效元数据合并只遍历有值的字段_结果不变(isolated):
    """优化后的合并（只遍历有值的字段）必须与「逐字段试」**结果一致**。

    ⚠️ 权威字段集仍是 `_META_FIELDS`：不在它里面的键**不参与合并** ——
    「快路径」不能偷偷放行新字段。
    """
    db.set_override("b1", "title", "覆盖的书名")
    db.set_override("b1", "series_index", "-")        # 显式无值哨兵
    db.set_override("b2", "tags", "['科幻', '经典']")
    db.set_override("b3", "不在权威字段集里的键", "x")

    out = db.get_effective_meta(["b1", "b2", "b3", "b4"])
    assert out["b1"]["title"] == "覆盖的书名"
    # 哨兵：必须**带着无值**并进结果（否则「清空」等于没做）
    assert "series_index" in out["b1"]
    assert out["b1"]["series_index"] == ""
    assert out["b2"]["tags"] == ["科幻", "经典"]
    # 不在 `_META_FIELDS` 里的键不参与合并
    assert "不在权威字段集里的键" not in out.get("b3", {})
    # 没有任何值的书不进结果
    assert "b4" not in out
