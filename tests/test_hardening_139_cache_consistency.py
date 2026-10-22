"""第 139 期（第五轮审计：缓存与索引一致性）。

五条判据，每条都对应一种「界面上看不出来、但数字会说谎」的情形：

1. **全库失效必须能删掉「本进程只读过、没写过」的列表键** —— 原登记表只在**写**
   缓存时登记，重启后 Redis 里已有的键对 ``invalidate(None)`` 隐形，旧标题/旧作者
   会一直占住 ``TTL_LIST``（120s）。用例把进程登记表清空（模拟重启）后走一次**命中**，
   再验全库失效真的删了键。
2. **写缓存前要比对脏计数** —— ``fresh_enough`` 在 SELECT 之前求值、``set_json`` 在其后，
   并发的写先删键、本次读再把旧行写回去。用例让「写」恰好发生在 SELECT 之后。
3. **收藏夹的「N 本」与点进去的列表同一判据** —— 裸 ``COUNT(*)`` 会把已不在盘上的
   成员算进去（侧栏 5、点进去 4，永不收敛）。
4. **侧栏三计数（60s 进程内缓存）跟着 ``library.invalidate()`` 失效** —— 它的
   ``invalidate`` 此前只有测试在调。
5. **``/opds`` 根导航的每库书数与书架同源** —— 此前逐库再调一次
   ``library.books(library_id=…)``，那是同一指标的第二份实现。
"""
import base64
import pathlib

import pytest

from novelforge.core import browse_counts, cache, catalog, db, epub_builder, library

from conftest import TEST_PIN, TEST_USER


@pytest.fixture
def mem_cache(monkeypatch):
    """把缓存层换成进程内字典 —— 不依赖真 Redis，而且能观察键。"""
    store: dict = {}

    def _set(k, v, ttl=None):                      # noqa: ARG001 —— 签名对齐
        store[k] = v

    monkeypatch.setattr(cache, "get_json", lambda k: store.get(k))
    monkeypatch.setattr(cache, "set_json", _set)
    monkeypatch.setattr(cache, "drop", lambda *keys: [store.pop(k, None) for k in keys])
    # 进程登记表也清干净 —— 「刚重启」的状态（这正是第 139 期 H1 的前提）。
    monkeypatch.setattr(catalog, "_cached_libs", set())
    return store


def _lib_root(tmp_path: pathlib.Path, lid: str = "novels") -> pathlib.Path:
    root = tmp_path / "libraries" / lid
    root.mkdir(parents=True, exist_ok=True)
    db.create_library(lid, "小说库", "ebook", source_dirs=str(root))
    library.invalidate()
    return root


def _put_epub(root, name: str) -> pathlib.Path:
    src = pathlib.Path(root) / name
    src.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": name.split(".")[0], "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}],
                            str(src), nav=False)
    library.invalidate()
    return src


def _only_lib() -> dict:
    return library.libraries()[0]


# ---------------- ① 全库失效 vs「只读过」的键 ----------------

def test_全库失效能删掉只读过没写过的列表键(isolated, tmp_path, mem_cache):  # noqa: ARG001
    root = _lib_root(tmp_path)
    _put_epub(root, "甲.epub")
    lib = _only_lib()
    key = cache.book_list_key(str(lib["id"]))

    catalog.books_of(lib)                      # 写缓存 + 登记
    assert cache.get_json(key) is not None

    # 「重启」：进程内存登记表空了，键还留在 Redis 里
    catalog._cached_libs.clear()
    assert catalog.books_of(lib) == cache.get_json(key)      # 这一次是**命中**

    catalog.invalidate(None)                   # 不带 library_id 的写 → 全库失效
    assert cache.get_json(key) is None, "命中过的键没登记 ⇒ 全库失效删不到它（H1 回归）"


# ---------------- ② SELECT 期间被标脏 ⇒ 不许写缓存 ----------------

def test_读期间被标脏就不写缓存(isolated, tmp_path, mem_cache, monkeypatch):  # noqa: ARG001
    root = _lib_root(tmp_path)
    _put_epub(root, "乙.epub")
    lib = _only_lib()
    key = cache.book_list_key(str(lib["id"]))

    real_rows = catalog._rows_of
    fired = {"done": False}

    def rows_of(l):
        out = real_rows(l)
        if not fired["done"]:
            fired["done"] = True
            # 模拟「写操作恰好落在 SELECT 之后、set_json 之前」
            catalog.invalidate(str(lib["id"]))
        return out

    monkeypatch.setattr(catalog, "_rows_of", rows_of)
    catalog.books_of(lib)
    assert cache.get_json(key) is None, "读期间被标脏了还把旧值写进缓存（M1 回归）"


# ---------------- ③ 收藏夹计数与详情页同一判据 ----------------

def test_收藏夹计数丢掉已不在盘上的成员(client, auth_headers, isolated, tmp_path):  # noqa: ARG001
    root = _lib_root(tmp_path)
    book = _put_epub(root, "丙.epub")
    bid = library.books("novels")[0]["id"]

    cid = client.post("/api/collections", headers=auth_headers,
                      json={"name": "夹"}).json()["id"]
    ok = client.post(f"/api/collections/{cid}/books", headers=auth_headers,
                     json={"book_id": bid})
    assert ok.status_code == 200, ok.text
    # 幽灵成员：书已经不在了（删书 / 移除书库之后留下的那种行）
    db.add_book_to_collection(cid, "幽灵.epub")

    items = client.get("/api/collections", headers=auth_headers).json()["items"]
    item = next(i for i in items if i["id"] == cid)
    detail = client.get(f"/api/collections/{cid}", headers=auth_headers).json()

    assert item["count"] == len(detail["books"]) == 1, "侧栏数与会页面条数必须同一判据（H2 回归）"
    assert item["first_book_id"] == bid
    del book


# ---------------- ④ 侧栏三计数跟着失效 ----------------

def test_侧栏三计数跟着library_invalidate失效(isolated, tmp_path):  # noqa: ARG001
    root = _lib_root(tmp_path)
    _put_epub(root, "丁.epub")

    first = browse_counts.counts("")
    assert first["cached"] is False and first["books"] == 1
    assert browse_counts.counts("")["cached"] is True          # 60s 内命中

    _put_epub(root, "戊.epub")                                 # 写操作（内部会 invalidate）
    again = browse_counts.counts("")
    assert again["cached"] is False, "写完之后 60s 内还回旧数字（H3 回归）"
    assert again["books"] == 2


# ---------------- ⑤ /opds 根导航不再逐库重算 ----------------

def test_opds根导航不逐库重算书数(client, isolated, tmp_path, monkeypatch):  # noqa: ARG001
    from novelforge import config

    _lib_root(tmp_path, "novels")
    _put_epub(tmp_path / "libraries" / "novels", "己.epub")

    calls: list = []
    real_books = library.books

    def spy(library_id=None):
        if library_id:
            calls.append(str(library_id))
        return real_books(library_id)

    monkeypatch.setattr(library, "books", spy)
    config.save_overrides({"opds": {"enabled": True}})
    try:
        raw = f"{TEST_USER}:{TEST_PIN}".encode()
        r = client.get("/opds",
                       headers={"Authorization": "Basic " + base64.b64encode(raw).decode()})
        assert r.status_code == 200, r.text
    finally:
        config.save_overrides({})
    assert calls == [], f"/opds 又按库重算了一遍书数（M4 回归）：{calls}"
