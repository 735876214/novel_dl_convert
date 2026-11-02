"""分页的**提前切片**（第 233 期）：结果必须与「全量拼装后再切」**逐字相同**。

## 改了什么

`GET /api/books?limit=N&offset=M` 原先的路径是：

```
全量 books → enrich 全量 → 筛选 → 切片
```

即**一页要付全库的钱**（实测 2309 本的库：全量 enrich 83 ms，而这一页只要 120 本 ≈ 6 ms）。

现在（**没有规则筛选 + 单库**时）走：

```
books_of(lib, limit, offset) → enrich 这一页 → 切片（不再切）
```

而 `total` 用一次 `COUNT` 取（不拼装全库）。

## 这里钉三件事

1. **结果逐字相同**：提前切出来的这一页 == 全量路径切出来的这一页（逐字段）。
2. **总数不变**：`total` 是**未切片前**的总数（前端据此算「已显示 N / 共 M」）。
3. **规则筛选时**不许提前切（规则要遍历**全部**候选才能判命中）—— 那一路仍是全量。
"""
from __future__ import annotations

import json

from novelforge.core import catalog, db, library


def _seed(tmp_path, make_library, make_book, n: int = 30):
    lib = make_library("lib$page", "分页库", "ebook", tmp_path / "lib")
    root = tmp_path / "lib"
    for i in range(n):
        make_book(root, "书%02d.epub" % i)
    library.invalidate()
    by_name = {b["name"]: b for b in library.books("lib$page")}
    for i, b in enumerate(by_name.values()):
        db.set_override(b["id"], "title", "标题%02d" % i)
        db.set_rating(b["id"], (i % 5) + 1)
        db.set_status(b["id"], "reading")
    library.invalidate()
    return lib


def test_提前切页的结果与全量路径逐字相同(client, auth_headers, isolated, tmp_path,
                                     make_library, make_book):
    _seed(tmp_path, make_library, make_book, 30)

    for lim, off in ((10, 0), (10, 10), (5, 25), (30, 0), (100, 0)):
        paged = client.get("/api/books", headers=auth_headers,
                           params={"limit": lim, "offset": off}).json()
        full = client.get("/api/books", headers=auth_headers).json()
        want = full["items"][off:off + lim]
        assert paged["items"] == want, (lim, off, paged["items"][:2], want[:2])
        # total 始终是**未切片前**的总数
        assert paged["total"] == full["total"] == 30, (lim, off, paged["total"])


def test_提前切页时总数不因分页而变(client, auth_headers, isolated, tmp_path,
                                     make_library, make_book):
    _seed(tmp_path, make_library, make_book, 30)
    r = client.get("/api/books", headers=auth_headers,
                   params={"limit": 10, "offset": 0}).json()
    assert r["total"] == 30
    assert len(r["items"]) == 10
    assert r["has_more"] is True
    r2 = client.get("/api/books", headers=auth_headers,
                    params={"limit": 10, "offset": 25}).json()
    assert len(r2["items"]) == 5
    assert r2["has_more"] is False


def test_只给_offset_不给_limit_等于不限(client, auth_headers, isolated,
                                                  tmp_path, make_library, make_book):
    """`limit=0` 的语义是「**不限**」（不是「取 0 条」）。

    ⚠️ 这条是第一版 DB 侧取页踩的坑：按页取时把 `limit=0` 当成了「取 0 条」，
    结果「只给 offset」的分页请求返回了**空列表**。
    """
    _seed(tmp_path, make_library, make_book, 30)
    full = client.get("/api/books", headers=auth_headers).json()["items"]
    body = client.get("/api/books", headers=auth_headers,
                      params={"offset": 5}).json()
    assert [x["id"] for x in body["items"]] == [x["id"] for x in full[5:]]
    assert body["total"] == 30


def test_规则筛选时不提前切(client, auth_headers, isolated,
                                          tmp_path, make_library, make_book):
    """规则要判命中 ⇒ 必须看**全部**书；提前切会把后面的书漏掉。"""
    _seed(tmp_path, make_library, make_book, 30)
    # 「标题29」在第 30 本 —— 只看第一页就找不到
    payload = json.dumps({"rules": [{"field": "title", "op": "equals", "value": "标题29"}],
                         "match": "all"}, ensure_ascii=False)
    r = client.get("/api/books", headers=auth_headers,
                   params={"limit": 10, "offset": 0, "rules": payload}).json()
    assert r["total"] == 1
    assert [x["title"] for x in r["items"]] == ["标题29"]


def test_多库时不提前切(client, auth_headers, isolated,
                                       tmp_path, make_library, make_book):
    """多库合并时切页会漏掉后面的库 ⇒ 那一路仍是全量。"""
    make_library("lib$a", "A 库", "ebook", tmp_path / "a")
    make_library("lib$b", "B 库", "ebook", tmp_path / "b")
    for root, n in ((tmp_path / "a", 3), (tmp_path / "b", 3)):
        root.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (root / ("%s%02d.epub" % (root.name, i))).write_bytes(b"EPUB")
    library.invalidate()
    r = client.get("/api/books", headers=auth_headers,
                   params={"limit": 2, "offset": 0}).json()
    # 6 本在两个库里；总数不能因为切页而变成 2
    assert r["total"] == 6, r["total"]
