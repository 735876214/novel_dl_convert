"""第 43 期：作者排序键派生与批量回填。

最重要的那条：**只写派生态列 `sort_name`，绝不动用户覆盖列 `sort_name_local`** ——
写后者等于冒充用户改过，界面会误显示「已覆盖」、并从此挡住抓取。
"""
from __future__ import annotations

import pathlib

from novelforge.core import authors, db, epub_builder, library


def _epub(root, name: str, author: str) -> pathlib.Path:
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": path.stem, "author": author, "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    return path


def test_派生规则():
    assert authors.derive_sort_name("John Doe") == "Doe, John"
    assert authors.derive_sort_name("Ursula K. Le Guin") == "Le Guin, Ursula K."
    assert authors.derive_sort_name("Doe, John") == "Doe, John", "已是「姓, 名」就原样"
    assert authors.derive_sort_name("刘慈欣") == "刘慈欣", "CJK 没有「姓, 名」写法"
    assert authors.derive_sort_name("") == ""


def test_回填只写派生态列且跳过CJK(client, auth_headers, isolated, default_root):  # noqa: ARG001
    _epub(default_root, "一.epub", "John Doe")
    _epub(default_root, "二.epub", "刘慈欣")
    library.invalidate()

    r = client.post("/api/authors/sort-name/backfill", headers=auth_headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filled"] == 1, "只补拉丁名；CJK 派生结果与显示名相同 ⇒ 跳过"
    assert db.get_author("John Doe")["sort_name"] == "Doe, John"
    assert (db.get_author("John Doe").get("sort_name_local") or "") == "", "不碰用户覆盖列"
    assert (db.get_author("刘慈欣") or {}).get("sort_name", "") == "", "填了等于没填 ⇒ 不填（本就没有行）"


def test_已有派生值不覆盖(client, auth_headers, isolated, default_root):  # noqa: ARG001
    _epub(default_root, "一.epub", "John Doe")
    library.invalidate()

    client.post("/api/authors/sort-name/backfill", headers=auth_headers)
    again = client.post("/api/authors/sort-name/backfill", headers=auth_headers).json()

    assert again["filled"] == 0


def test_不动已有用户覆盖(client, auth_headers, isolated, default_root):  # noqa: ARG001
    _epub(default_root, "一.epub", "John Doe")
    library.invalidate()
    # 用户显式设过覆盖：回填既不该改它，也不该被它挡住（各写各的列）
    client.post("/api/authors/John Doe/sort-name", headers=auth_headers,
                json={"sort_name": "用户取的键"})

    client.post("/api/authors/sort-name/backfill", headers=auth_headers)

    row = db.get_author("John Doe")
    assert row["sort_name_local"] == "用户取的键"
    assert row["sort_name"] == "Doe, John"
    assert authors.sort_name_of(row) == "用户取的键", "展示仍取本地覆盖优先"
