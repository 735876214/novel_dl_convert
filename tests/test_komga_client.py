"""Komga 客户端兼容收尾（第 16 期）与「删除 OPDS 订阅」的防回归。

钉住四条口径：

1. **Collections 是真实收藏夹**：装的是 book_id，映射时按书归到各自系列；可新建 / 加系列 /
   移出 / 重命名 / 删除，写操作真的落到 `collections` 表。
2. **越库的书不进 Komga**：收藏夹是全局的（可以装有声书库的书），但从 Komga 侧看必须
   过滤掉 —— 否则客户端拿到打不开的坏条目。
3. **没有的概念诚实为空**：Readlist 返回空分页而不是编造；不支持的写操作给 403 而不是假装成功。
4. **删掉的能力要真消失**：`/api/opds/sources` 必须 404（接入外部 OPDS 源已删除）。

全程离线；Komga / OPDS 开关用配置覆盖层（用完还原）。
"""
import pathlib
import xml.etree.ElementTree as ET

import pytest

from novelforge import config
from novelforge.core import db, epub_builder, fileops, komga_api, library


def _epub(root, name: str, title: str, series: str = "", index: str = "") -> pathlib.Path:
    """造一本真 EPUB（`series` 给定时改写 OPF），扫描才认得出系列。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": "测试作者", "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    if series:
        assert fileops.patch_epub_meta(path, {"series": series, "series_index": index or "1"})
    return path


def _audio_dir(root, name: str) -> pathlib.Path:
    d = pathlib.Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "01.mp3").write_bytes(b"MP3")
    return d


def _new_library(client, headers, name: str, root, ltype: str) -> dict:
    r = client.post("/api/libraries", headers=headers,
                    json={"name": name, "type": ltype, "mode": "inplace",
                          "root_path": str(root)})
    assert r.status_code == 200, r.text
    library.invalidate()
    return r.json()["library"]


@pytest.fixture
def enable_komga():
    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        yield ("admin", "test1234")
    finally:
        config.save_overrides({})


@pytest.fixture
def two_book_series(client, auth_headers, enable_komga, default_root):  # noqa: ARG001
    """一个两册系列 → 返回 (系列 id, [book_id…])。"""
    _epub(default_root, "甲.epub", title="甲", series="银河帝国", index="1")
    _epub(default_root, "乙.epub", title="乙", series="银河帝国", index="2")
    library.invalidate()
    sid = client.get("/api/v1/series", auth=enable_komga).json()["content"][0]["id"]
    ids = [b["id"] for b in client.get(f"/api/v1/series/{sid}/books",
                                       auth=enable_komga).json()["content"]]
    return sid, ids


# ---------------------------------------------------------------------------
# Collections = 真实收藏夹
# ---------------------------------------------------------------------------

def test_收藏夹映射为Komga集合(client, auth_headers, enable_komga, two_book_series):
    sid, ids = two_book_series
    r = client.post("/api/v1/collections", auth=enable_komga,
                    json={"name": "科幻", "seriesIds": [sid]})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert r.json()["seriesCount"] == 1 and r.json()["seriesIds"] == [sid]

    # 真的落到收藏夹里（按书存，不是按系列）
    assert sorted(db.collection_book_ids(int(cid))) == sorted(ids)

    listed = client.get("/api/v1/collections", auth=enable_komga).json()
    assert listed["totalElements"] == 1
    assert listed["content"][0]["seriesIds"] == [sid]

    inside = client.get(f"/api/v1/collections/{cid}/series", auth=enable_komga).json()
    assert inside["totalElements"] == 1
    assert inside["content"][0]["id"] == sid


def test_收藏夹整体替换与移出系列(client, auth_headers, enable_komga, two_book_series):
    sid, ids = two_book_series
    cid = client.post("/api/v1/collections", auth=enable_komga,
                      json={"name": "科幻"}).json()["id"]
    assert db.collection_book_ids(int(cid)) == []

    # PUT = 整体替换
    r = client.put(f"/api/v1/collections/{cid}/series", auth=enable_komga,
                   json={"seriesIds": [sid]})
    assert r.status_code == 200 and len(db.collection_book_ids(int(cid))) == 2

    # DELETE 单个系列 = 把该系列的书全部移出
    assert client.delete(f"/api/v1/collections/{cid}/series/{sid}",
                         auth=enable_komga).status_code == 204
    assert db.collection_book_ids(int(cid)) == []

    # 不存在的系列 → 404（不要静默 200）
    assert client.delete(f"/api/v1/collections/{cid}/series/没有这个系列",
                         auth=enable_komga).status_code == 404


def test_收藏夹里的越库书不进Komga(client, auth_headers, enable_komga, two_book_series):
    """收藏夹是全局的（能装有声书库的书），但 Komga 侧必须把它过滤掉。"""
    sid, ids = two_book_series
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    audio = _new_library(client, auth_headers, "有声书库", src / "audio", "audiobook")
    _audio_dir(src / "audio", "一本有声书")
    library.invalidate()

    cid = client.post("/api/v1/collections", auth=enable_komga,
                      json={"name": "混合", "seriesIds": [sid]}).json()["id"]
    audio_books = [b["id"] for b in library.books(library_id=audio["id"])]
    assert audio_books
    db.add_book_to_collection(int(cid), audio_books[0])   # 直接塞进收藏夹

    # 收藏夹里确实有它，但 Komga 看到的系列只算可见书
    assert audio_books[0] in db.collection_book_ids(int(cid))
    dto = client.get(f"/api/v1/collections/{cid}", auth=enable_komga).json()
    assert dto["seriesIds"] == [sid]
    inside = client.get(f"/api/v1/collections/{cid}/series", auth=enable_komga).json()
    assert inside["totalElements"] == 1


def test_收藏夹重命名与删除(client, auth_headers, enable_komga, two_book_series):
    cid = client.post("/api/v1/collections", auth=enable_komga,
                      json={"name": "甲"}).json()["id"]
    assert client.patch(f"/api/v1/collections/{cid}", auth=enable_komga,
                        json={"name": "乙"}).json()["name"] == "乙"

    # 重名 → 409（靠 collections.name 的 UNIQUE，不预查）
    client.post("/api/v1/collections", auth=enable_komga, json={"name": "丙"})
    assert client.patch(f"/api/v1/collections/{cid}", auth=enable_komga,
                        json={"name": "丙"}).status_code == 409
    # 空名 → 400
    assert client.patch(f"/api/v1/collections/{cid}", auth=enable_komga,
                        json={"name": "  "}).status_code == 400

    assert client.delete(f"/api/v1/collections/{cid}", auth=enable_komga).status_code == 204
    assert client.get(f"/api/v1/collections/{cid}", auth=enable_komga).status_code == 404


def test_自定义收藏夹封面明确报错(client, auth_headers, enable_komga, two_book_series):
    cid = client.post("/api/v1/collections", auth=enable_komga,
                      json={"name": "科幻"}).json()["id"]
    for method in ("post", "put", "delete"):
        r = getattr(client, method)(f"/api/v1/collections/{cid}/thumbnail", auth=enable_komga)
        assert r.status_code == 403, (method, r.status_code)


# ---------------------------------------------------------------------------
# 没有的概念：诚实为空 / 明确报错
# ---------------------------------------------------------------------------

def test_阅读清单诚实为空(client, auth_headers, enable_komga):
    r = client.get("/api/v1/readlists", auth=enable_komga)
    assert r.status_code == 200 and r.json()["totalElements"] == 0
    assert client.post("/api/v1/readlists", auth=enable_komga).status_code == 403
    assert client.post("/api/v1/readlists/import", auth=enable_komga).status_code == 403


def test_引用表字段齐全且有真实值(client, auth_headers, enable_komga, two_book_series):
    ref = client.get("/api/v1/referential", auth=enable_komga).json()
    for key in ("authors", "series", "tags", "languages", "publishers",
                "seriesReleaseDates", "ageRatings", "sharingLabels"):
        assert key in ref, f"缺字段 {key}"
    assert "测试作者" in ref["authors"]
    assert "银河帝国" in ref["series"]


# ---------------------------------------------------------------------------
# 单库 / 上一本下一本 / analyze
# ---------------------------------------------------------------------------

def test_单库详情与不可见库(client, auth_headers, enable_komga):
    one = client.get("/api/v1/libraries/default", auth=enable_komga)
    assert one.status_code == 200 and one.json()["id"] == "default"
    assert client.get("/api/v1/libraries/没有这个库", auth=enable_komga).status_code == 404


def test_系列内上一本下一本(client, auth_headers, enable_komga, two_book_series):
    _sid, ids = two_book_series
    books = client.get("/api/v1/books", auth=enable_komga).json()["content"]
    by_title = {b["metadata"]["title"]: b["id"] for b in books}
    first, second = by_title["甲"], by_title["乙"]

    nxt = client.get(f"/api/v1/books/{first}/next", auth=enable_komga)
    assert nxt.status_code == 200 and nxt.json()["id"] == second
    assert client.get(f"/api/v1/books/{first}/previous", auth=enable_komga).status_code == 404

    prev = client.get(f"/api/v1/books/{second}/previous", auth=enable_komga)
    assert prev.status_code == 200 and prev.json()["id"] == first

    assert client.get("/api/v1/books/没有这本书/next", auth=enable_komga).status_code == 404


def test_分析是空实现(client, auth_headers, enable_komga, two_book_series):
    sid, _ids = two_book_series
    assert client.post(f"/api/v1/series/{sid}/analyze", auth=enable_komga).status_code == 204
    assert client.post("/api/v1/series/没有这个系列/analyze",
                       auth=enable_komga).status_code == 404


# ---------------------------------------------------------------------------
# OPDS：搜索描述文档（对外能力）
# ---------------------------------------------------------------------------

def test_OPDS搜索描述文档(client):
    config.save_overrides({"opds": {"enabled": True}})
    try:
        r = client.get("/opds/search/description", auth=("admin", "test1234"))
        assert r.status_code == 200, r.text
        assert "opensearchdescription" in r.headers.get("content-type", "")
        root = ET.fromstring(r.text)
        assert root.tag.endswith("OpenSearchDescription")
        tmpl = root.find("{http://a9.com/-/spec/opensearch/1.1/}Url").get("template")
        assert "search?q={searchTerms}" in tmpl

        # 根 feed 的 search link 必须指向它（否则客户端不认搜索）
        feed = ET.fromstring(client.get("/opds", auth=("admin", "test1234")).text)
        links = [l for l in feed.findall("{http://www.w3.org/2005/Atom}link")
                 if l.get("rel") == "search"]
        assert links and links[0].get("type") == "application/opensearchdescription+xml"
        assert links[0].get("href", "").endswith("/opds/search/description")
    finally:
        config.save_overrides({})


# ---------------------------------------------------------------------------
# 防回归：删除掉的能力必须真的消失
# ---------------------------------------------------------------------------

def test_外部OPDS订阅接口已删除(client, auth_headers):
    """接入外部 OPDS 源的能力已删除：带令牌请求应当 404（不是 200，也不是空列表）。"""
    assert client.get("/api/opds/sources", headers=auth_headers).status_code == 404
    assert client.post("/api/opds/sources", headers=auth_headers,
                       json={"name": "x", "url": "https://example.com"}).status_code == 404


# ---------------------------------------------------------------------------
# 反向查询（第 17 期封口）
# ---------------------------------------------------------------------------

def test_系列反向查收藏夹(client, auth_headers, enable_komga, two_book_series, default_root):
    sid, _ids = two_book_series
    _epub(default_root, "单独的.epub", title="单独的")      # 造第二个系列做对照
    library.invalidate()
    others = [s for s in client.get("/api/v1/series", auth=enable_komga).json()["content"]
              if s["id"] != sid]
    assert others, "应当有第二个系列"

    cid = client.post("/api/v1/collections", auth=enable_komga,
                      json={"name": "科幻", "seriesIds": [sid]}).json()["id"]

    inside = client.get(f"/api/v1/series/{sid}/collections", auth=enable_komga)
    assert inside.status_code == 200, inside.text
    body = inside.json()
    assert body["totalElements"] == 1
    assert body["content"][0]["id"] == str(cid)

    # 不在任何收藏夹里的系列 → 空分页（不是 404）
    outside = client.get(f"/api/v1/series/{others[0]['id']}/collections", auth=enable_komga)
    assert outside.status_code == 200 and outside.json()["totalElements"] == 0

    # 系列不存在 → 404（不静默给空）
    assert client.get("/api/v1/series/没有这个系列/collections",
                      auth=enable_komga).status_code == 404


def test_书籍反向查阅读清单恒空(client, auth_headers, enable_komga, two_book_series):
    _sid, ids = two_book_series
    r = client.get(f"/api/v1/books/{ids[0]}/readlists", auth=enable_komga)
    assert r.status_code == 200
    assert r.json()["totalElements"] == 0          # 本项目没有阅读清单概念，诚实为空
    assert client.get("/api/v1/books/没有这本书/readlists",
                      auth=enable_komga).status_code == 404
