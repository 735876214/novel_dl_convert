"""Komga 兼容面**第三轮**审计的契约（第 268 期）。

这一轮的角度：**筛选条件的两种形态**、**写后读回**、**条件请求**、**HTTP 方法语义**，
以及「上一轮的修复有没有覆盖全」。

1. `POST /series/list` **只认 `libraryId`**：`fullTextSearch` / `allOf.title` / `anyOf`
   全部被忽略（实测搜「三体」回全部系列，连 `allOf.title.contains` 都不过滤）——
   第 266 期给 books 补的那套没覆盖到这里，是**半截修复**。
2. `condition.anyOf` 在 books 那边也被忽略：Komga 的 `SearchCondition` 有**两半**
   （`allOf` = AND、`anyOf` = OR），此前只读了一半 ⇒ 只发 `anyOf` 的客户端拿到全量。
3. `DELETE /books/{id}/read-progress` 写的是 `percent=0` 的一行 ⇒ `readProgress` **不是 null**，
   客户端仍显示「继续阅读第 1 页」，而用户点的是「标为未读」。
4. `/file` 发 ETag 却从不回 **304** ⇒ 每次取书重传整本。
5. `HEAD` 对 FastAPI 的 GET 路由一律 **404**（`HEAD /health` 也 404）⇒ 客户端探存在性时误判。
"""
import io
import json
import pathlib
import zipfile

import pytest

from novelforge import config
from novelforge.core import db, library


@pytest.fixture
def komga_on():
    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        yield {"X-API-Key": "test-key"}
    finally:
        config.save_overrides({})


def _cbz(path: pathlib.Path, pages: int = 3) -> pathlib.Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(pages):
            b = io.BytesIO()
            Image.new("RGB", (40, 50), (i * 20, 0, 0)).save(b, "PNG")
            z.writestr(f"{i + 1:03d}.png", b.getvalue())
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture
def three_series(client, auth_headers, make_library, tmp_path):
    root = tmp_path / "L"
    root.mkdir(parents=True, exist_ok=True)
    make_library("L", "库", "comic", root)
    for nm in ("三体", "球状闪电", "超新星纪元"):
        _cbz(root / nm / (nm + " #1.cbz"))
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    return root


def _series_names(resp) -> list:
    assert resp.status_code == 200, resp.text
    return [s["name"] for s in resp.json()["content"]]


def _book_names(resp) -> list:
    assert resp.status_code == 200, resp.text
    return [b["name"] for b in resp.json()["content"]]


# ---------------------------------------------------------------- 1. 系列侧真的会筛

def test_系列列表的搜索真的会筛(client, komga_on, three_series):   # noqa: ARG001
    """回归点：`POST /series/list` 此前只认 `libraryId`，搜索等于没做。"""
    got = _series_names(client.post("/api/v1/series/list",
                                    json={"fullTextSearch": "三体"}, headers=komga_on))
    assert got == ["三体"], got


def test_系列列表的_allOf_与_anyOf_都会筛(client, komga_on, three_series):   # noqa: ARG001
    got = _series_names(client.post(
        "/api/v1/series/list",
        json={"condition": {"allOf": [{"title": {"contains": "球状"}}]}}, headers=komga_on))
    assert got == ["球状闪电"], got
    got = _series_names(client.post(
        "/api/v1/series/list",
        json={"condition": {"anyOf": [{"title": {"contains": "球状"}},
                                      {"title": {"contains": "超新"}}]}}, headers=komga_on))
    assert set(got) == {"球状闪电", "超新星纪元"}, got


def test_系列列表不筛时仍是全部(client, komga_on, three_series):   # noqa: ARG001
    """「会筛」不许变成「没条件也筛」（那会把整个书架筛空）。"""
    assert len(_series_names(client.post("/api/v1/series/list", json={},
                                         headers=komga_on))) == 3
    assert len(_series_names(client.get("/api/v1/series?size=20",
                                        headers=komga_on))) == 3


# ---------------------------------------------------------------- 2. books 的 anyOf

def test_书的_anyOf_是或而_allOf_是与(client, komga_on, three_series):   # noqa: ARG001
    or_got = _book_names(client.post(
        "/api/v1/books/list",
        json={"condition": {"anyOf": [{"title": {"contains": "球状"}},
                                      {"title": {"contains": "超新"}}]}}, headers=komga_on))
    assert set(or_got) == {"球状闪电 #1.cbz", "超新星纪元 #1.cbz"}, or_got

    and_got = _book_names(client.post(
        "/api/v1/books/list",
        json={"condition": {"allOf": [{"title": {"contains": "三体"}}]}}, headers=komga_on))
    assert and_got == ["三体 #1.cbz"], and_got


def test_allOf_与_anyOf_同时出现在_与_优先(client, komga_on, three_series):   # noqa: ARG001
    """`allOf` 是 AND、`anyOf` 是 OR：两者同时给时都要成立（AND(OR(...), ...)）。"""
    got = _book_names(client.post(
        "/api/v1/books/list",
        json={"condition": {
            "allOf": [{"title": {"contains": "超新"}}],
            "anyOf": [{"title": {"contains": "超新"}}, {"title": {"contains": "三体"}}],
        }}, headers=komga_on))
    assert got == ["超新星纪元 #1.cbz"], got


# ---------------------------------------------------------------- 3. 删除 = 真的没有

def test_删除进度之后_读回是_null(client, auth_headers, make_library, tmp_path,
                                komga_on):
    """Komga 用 `readProgress: null` 表示「未读」；写一个 `percent=0` 的行不算。"""
    root = tmp_path / "D"
    _cbz(root / "s" / "s #1.cbz", pages=5)
    make_library("D", "库D", "comic", root)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    b = client.get("/api/v1/books?size=1", headers=komga_on).json()["content"][0]
    bid = b["id"]

    client.put("/api/v1/books/" + bid + "/read-progress", json={"page": 3},
               headers=komga_on)
    assert client.get("/api/v1/books/" + bid, headers=komga_on).json()["readProgress"]

    r = client.delete("/api/v1/books/" + bid + "/read-progress", headers=komga_on)
    assert r.status_code == 204
    dto = client.get("/api/v1/books/" + bid, headers=komga_on).json()
    assert dto["readProgress"] is None, dto["readProgress"]
    assert db.get_progress(bid) is None, "库里还留着进度行（写 0 而不是删）"


def test_系列标记未读也是真删(client, auth_headers, make_library, tmp_path, komga_on):
    root = tmp_path / "S"
    for i in range(1, 4):
        _cbz(root / "大系列" / f"大系列 #{i}.cbz", pages=2)
    make_library("S", "库S", "comic", root)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    s = client.get("/api/v1/series?size=5", headers=komga_on).json()["content"][0]
    assert client.post(f"/api/v1/series/{s['id']}/read-progress",
                       headers=komga_on).status_code == 204
    assert client.delete(f"/api/v1/series/{s['id']}/read-progress",
                         headers=komga_on).status_code == 204
    bs = client.get(f"/api/v1/series/{s['id']}/books?size=50",
                    headers=komga_on).json()["content"]
    assert all(b["readProgress"] is None for b in bs)


def test_未读的书根本不报_readProgress(client, auth_headers, make_library, tmp_path,
                                  komga_on):
    root = tmp_path / "N"
    _cbz(root / "s" / "s #1.cbz")
    make_library("N", "库N", "comic", root)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    b = client.get("/api/v1/books?size=1", headers=komga_on).json()["content"][0]
    assert b["readProgress"] is None


# ---------------------------------------------------------------- 4/5. 条件请求与 HEAD

def test_文件下载支持条件请求(client, auth_headers, make_library, tmp_path, komga_on):
    root = tmp_path / "F"
    _cbz(root / "s" / "s #1.cbz")
    make_library("F", "库F", "comic", root)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    b = client.get("/api/v1/books?size=1", headers=komga_on).json()["content"][0]
    url = "/api/v1/books/" + b["id"] + "/file"

    r1 = client.get(url, headers=komga_on)
    assert r1.status_code == 200
    etag = r1.headers.get("etag")
    assert etag, "没有 ETag"
    r2 = client.get(url, headers={**komga_on, "If-None-Match": etag})
    assert r2.status_code == 304, f"带 If-None-Match 仍回 {r2.status_code}（整本重传）"
    assert not r2.content


def test_文件与页都支持_HEAD(client, auth_headers, make_library, tmp_path, komga_on):
    root = tmp_path / "H"
    _cbz(root / "s" / "s #1.cbz", pages=2)
    make_library("H", "库H", "comic", root)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    b = client.get("/api/v1/books?size=1", headers=komga_on).json()["content"][0]
    bid = b["id"]

    r = client.head("/api/v1/books/" + bid + "/file", headers=komga_on)
    assert r.status_code == 200, f"HEAD /file -> {r.status_code}"
    assert r.headers.get("content-length")
    assert r.headers.get("accept-ranges") == "bytes"

    r = client.head("/api/v1/books/" + bid + "/pages/1", headers=komga_on)
    assert r.status_code == 200, f"HEAD /pages/1 -> {r.status_code}"
    assert r.headers.get("content-type", "").startswith("image/")
    assert int(r.headers.get("content-length") or 0) > 0


def test_HEAD_也查可见性(client, auth_headers, make_library, tmp_path, komga_on):
    """HEAD 不是后门：不可见的书照样 404。"""
    root = tmp_path / "V"
    _cbz(root / "s" / "s #1.cbz")
    make_library("V", "库V", "comic", root)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    b = client.get("/api/v1/books?size=1", headers=komga_on).json()["content"][0]
    assert client.head("/api/v1/books/" + b["id"] + "/file",
                       headers=komga_on).status_code == 200
    assert client.head("/api/v1/books/根本没有这个id/file",
                       headers=komga_on).status_code == 404
