"""收藏夹成员的展示顺序必须是**全序**（第 281 期）。

审计发现（实测）：`db.add_books_to_collection()` 给整批成员写的是**同一个**
`time.time()` —— 一次加入 6 本，`collection_items.added_at` 只有 **1 个不同值**。
而 `collection_book_ids()` 原先只按 `added_at DESC` 排：

- 这批成员的相对顺序**不是 SQL 保证的**（SQLite 恰好按插入序返回；PostgreSQL 的
  `ORDER BY` 在键值相同的情况下**不保证**跨请求稳定）；
- `GET /api/collections/{cid}/books` 是 **offset 分页**，而它建立在这个顺序上
  ⇒ 换 PostgreSQL 后跨页可能**重复或漏项**；详情页与分页端点也会对不上。

修法：`ORDER BY added_at DESC, id ASC`（插入序兜底 —— 与 SQLite 现状一致，
批量加入时显示的就是「选择他们的顺序」）。下面钉住：

1. 批量加入后全体成员共享同一 `added_at`（**缺陷前提**，将来改实现也要知道）；
2. 顺序确定、可重复（多次读取一致）；
3. 分页拼接 == 详情顺序 == `db.collection_book_ids()`（跨页不重不漏）；
4. 逐个加入（时间戳不同）时仍是「最新在前」—— 兜底键不改变 DESC 语义。
"""
import pathlib

from novelforge.core import db, epub_builder, library


def _epub(root, name: str) -> pathlib.Path:
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": name, "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(p))
    return p


def _setup(client, auth_headers, make_library, tmp_path, n: int = 6) -> list:
    root = tmp_path / "L"
    for i in range(n):
        _epub(root, f"b{i}.epub")
    make_library("L", "库", "ebook", root)
    assert client.post("/api/scan", headers=auth_headers).status_code == 200
    library.invalidate()
    ids = [b["id"] for b in client.get("/api/books", headers=auth_headers).json()["items"]]
    assert len(ids) == n
    return ids


def _collection(client, auth_headers, name: str = "夹") -> int:
    r = client.post("/api/collections", headers=auth_headers, json={"name": name})
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


def _batch_add(client, auth_headers, cid: int, ids: list) -> None:
    r = client.post("/api/books/batch", headers=auth_headers,
                    json={"action": "add_to_collection", "ids": ids,
                          "params": {"collection_id": cid}})
    assert r.status_code == 200, r.text
    assert r.json()["succeeded"] == ids


def test_批量加入的成员共享同一时间戳(client, auth_headers, make_library, tmp_path):
    """缺陷前提：一次批量加入写的是**一个** `time.time()`，不是逐本取时间。"""
    ids = _setup(client, auth_headers, make_library, tmp_path)
    cid = _collection(client, auth_headers)
    _batch_add(client, auth_headers, cid, ids)

    rows = db._connect().execute(
        "SELECT id, book_id, added_at FROM collection_items"
        " WHERE collection_id=? ORDER BY id", (cid,)).fetchall()
    assert [r["book_id"] for r in rows] == ids
    assert len({r["added_at"] for r in rows}) == 1, \
        "批量加入的时间戳居然不同了 —— 先确认 `add_books_to_collection` 的实现"


def test_顺序确定且可重复(client, auth_headers, make_library, tmp_path):
    """同一个查询连读 5 次必须同序（键值相同时不能靠 SQL 的偶然顺序）。"""
    ids = _setup(client, auth_headers, make_library, tmp_path)
    cid = _collection(client, auth_headers)
    _batch_add(client, auth_headers, cid, ids)

    got = db.collection_book_ids(cid)
    assert got == ids, "批量加入应按插入序（与 SQLite 现状一致）"
    for _ in range(5):
        assert db.collection_book_ids(cid) == got


def test_分页拼接等于详情顺序(client, auth_headers, make_library, tmp_path):
    """offset 分页建立在同一份顺序上：跨页不重复、不遗漏。"""
    ids = _setup(client, auth_headers, make_library, tmp_path)
    cid = _collection(client, auth_headers)
    _batch_add(client, auth_headers, cid, ids)

    pages, off = [], 0
    while True:
        r = client.get(f"/api/collections/{cid}/books?limit=2&offset={off}",
                       headers=auth_headers).json()
        pages += [b["id"] for b in r["items"]]
        if not r["has_more"]:
            break
        off = r["next_offset"]
    detail = [b["id"] for b in
              client.get(f"/api/collections/{cid}", headers=auth_headers).json()["books"]]

    assert pages == detail == db.collection_book_ids(cid)
    assert len(pages) == len(set(pages)) == len(ids), "分页重复或漏项"


def test_逐个加入时仍是最新在前(client, auth_headers, make_library, tmp_path):
    """时间戳不同时，`added_at DESC` 的语义不变（兜底键只在相等时起作用）。"""
    ids = _setup(client, auth_headers, make_library, tmp_path, n=3)
    cid = _collection(client, auth_headers)

    c = db._connect()
    with db._lock:
        for i, bid in enumerate(ids):
            c.execute("INSERT INTO collection_items(collection_id, book_id, added_at)"
                      " VALUES(?,?,?)", (cid, bid, 100.0 + i))
        c.commit()
    assert db.collection_book_ids(cid) == list(reversed(ids))
