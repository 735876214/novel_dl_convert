"""分页**不得污染全量书目的缓存键**（第 244 期）。

## 缺陷

第 233 期给 `/api/books` 加了「提前切片」（一页不必为全库付费），走的是
`catalog.books_of(lib, limit, offset)`。而 `books_of` 的缓存键
`cache.book_list_key(lid)` **只含库 id**（全量语义），分页那次却把
**一页**的结果写进了同一个键 ⇒

- 之后任何**不分页**的读（侧栏 / 统计 / 第三方 / 不分页的视图）命中它，
  把 30 本当成**全库**返回 ⇒ 「书架突然只剩 30 本」「共 N 本对不上」；
- 反向同样成立：`offset=120` 的第二页把「第 121–150 本」写进同一个键。

不报错、不为空，就是「少了一截」，最多 TTL_LIST=120s 或下一次写操作才自愈。

## 为什么这个用例要自带假缓存

⚠️ 默认部署**不配 Redis**（缓存层是空操作，见 `core/cache.py` 的文件头）
⇒ 「缓存没失效 / 缓存串了」这类缺陷在离线环境**根本观测不到**，
用例会恒绿（假绿）。所以这里把 `cache._get/_set/_del` 换成一个进程内 dict，
模拟「配了 Redis」的部署，判据才有牙齿。
"""
from __future__ import annotations

from novelforge.core import catalog, library


def _seed(tmp_path, default_root, make_book, n: int = 30):
    """把 n 本书放进**起手那条库**（`default`）。

    ⚠️ 必须只用**一个**库：`api_books` 的提前切片只在「单库 + 无规则筛选」时启用
    （多库合并要逐库拼接，切在合并前会漏掉后面的库 ⇒ 那一路仍是全量）。
    另建一个库就变成多库 ⇒ 分页路径根本没走 ⇒ 用例假绿。
    """
    for i in range(n):
        make_book(default_root, "书%02d.epub" % i)
    library.invalidate()


def test_分页不得写进全量缓存键(client, auth_headers, isolated, tmp_path,
                                default_root, make_book, fake_redis):
    """分页之后，全量列表必须仍然是**全量**。"""
    _seed(tmp_path, default_root, make_book, 30)

    # 先做一次分页请求（它会走 `books_of(lib, limit=10, offset=0)`）
    r = client.get("/api/books", headers=auth_headers,
                   params={"limit": 10, "offset": 0}).json()
    assert len(r["items"]) == 10, len(r["items"])

    # 缓存里**不得**出现分页的结果
    key = catalog.cache.book_list_key("default")
    hit = catalog.cache.get_json(key)
    assert hit is None or len(hit) == 30, (
        "分页结果被写进了全量缓存键：%d 条" % len(hit or []))

    # 全量请求必须拿到 30 本
    full = client.get("/api/books", headers=auth_headers).json()
    assert full["total"] == 30, full["total"]
    assert len(full["items"]) == 30, len(full["items"])


def test_第二页也不得污染全量键(client, auth_headers, isolated, tmp_path,
                               default_root, make_book, fake_redis):
    """第二页写进去的是「第 121–150 本」那一段 —— 同样不能当全量。"""
    _seed(tmp_path, default_root, make_book, 30)

    r = client.get("/api/books", headers=auth_headers,
                   params={"limit": 10, "offset": 20}).json()
    assert len(r["items"]) == 10, len(r["items"])

    key = catalog.cache.book_list_key("default")
    hit = catalog.cache.get_json(key)
    assert hit is None or len(hit) == 30, (
        "第二页写进了全量缓存键：%d 条" % len(hit or []))

    full = client.get("/api/books", headers=auth_headers).json()
    assert len(full["items"]) == 30, len(full["items"])


def test_分页与全量交替也不能互相污染(client, auth_headers, isolated, tmp_path,
                                      default_root, make_book, fake_redis):
    """交替请求（真实前端翻页的形态）：两种口径必须各自稳定。"""
    _seed(tmp_path, default_root, make_book, 30)

    for _ in range(3):
        paged = client.get("/api/books", headers=auth_headers,
                           params={"limit": 7, "offset": 0}).json()
        assert len(paged["items"]) == 7, len(paged["items"])
        full = client.get("/api/books", headers=auth_headers).json()
        assert len(full["items"]) == 30, len(full["items"])
        assert full["total"] == 30, full["total"]
