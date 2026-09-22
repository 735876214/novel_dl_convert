"""Komga 兼容服务端补齐（第 15 期）：按库过滤 / 有声书不进 Komga / 系列级已读。

钉住四条口径：

1. **默认等于今天的行为** —— 不传库时是「全部**可见**书库」，老客户端的 `GET /series`
   与 `GET /books` 不会因为加了过滤参数而改变既有输出；
2. **系列侧真的生效** —— `POST /series/list` 的筛选条件此前被整个丢掉，现在 `libraryId` 生效；
3. **有声书库不进 Komga** —— Komga 没有音频模型，从**书库**这一层挡掉（按能力矩阵，
   不是让每本书自己判断），否则客户端拿到的是打不开的坏条目；
4. **系列级已读保留位置** —— 只把 percent 顶到 100，不把读者送回第一页。

全程离线：不触外部网络；Komga 开关用配置覆盖层（用完还原）。
"""
import pathlib

import pytest

from novelforge import config
from novelforge.core import db, komga_api, library


def _put(root, name: str, content: bytes = b"EPUB") -> pathlib.Path:
    """占位书文件（扫描只按扩展名收书，不需要真实 EPUB）。"""
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _put_audio_dir(root, name: str) -> pathlib.Path:
    """有声书目录形态（一章一文件）：目录 = 一本书。"""
    d = pathlib.Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "01.mp3").write_bytes(b"MP3")
    return d


def _new_library(client, headers, name: str, root, ltype: str) -> dict:
    r = client.post("/api/libraries", headers=headers,
                    json={"name": name, "type": ltype,
                          "source_dirs": [str(root)]})
    assert r.status_code == 200, r.text
    library.invalidate()
    return r.json()["library"]


@pytest.fixture
def enable_komga():
    """临时开启 Komga 兼容服务端（默认关闭）+ Basic 凭据。"""
    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        yield ("admin", "test1234")
    finally:
        config.save_overrides({})


# ---------------------------------------------------------------------------
# 按库过滤
# ---------------------------------------------------------------------------

def test_系列列表按库过滤(client, auth_headers, enable_komga, default_root):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    lib_b = _new_library(client, auth_headers, "漫画库", src / "comics", "comic")
    _put(default_root, "甲.epub")
    _put(src / "comics", "乙.cbz")
    library.invalidate()

    # 不传条件 = 全部可见库（与加过滤之前一致）
    all_series = client.post("/api/v1/series/list", auth=enable_komga).json()
    assert all_series["totalElements"] == 2

    # 只给漫画库 → 只剩它的系列
    only_b = client.post("/api/v1/series/list", auth=enable_komga,
                         json={"condition": {"libraryId": {"in": [lib_b["id"]]}}}).json()
    assert only_b["totalElements"] == 1
    assert only_b["content"][0]["libraryId"] == lib_b["id"]

    # 老客户端的 GET 端点同样支持（此前完全没有过滤）
    got = client.get("/api/v1/series", params={"library_id": lib_b["id"]},
                     auth=enable_komga).json()
    assert got["totalElements"] == 1


def test_书籍列表按库过滤(client, auth_headers, enable_komga, default_root):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    lib_b = _new_library(client, auth_headers, "漫画库", src / "comics", "comic")
    _put(default_root, "甲.epub")
    _put(src / "comics", "乙.cbz")
    library.invalidate()

    got = client.get("/api/v1/books", params={"library_id": lib_b["id"]},
                     auth=enable_komga).json()
    assert got["totalElements"] == 1
    assert got["content"][0]["libraryId"] == lib_b["id"]

    everything = client.get("/api/v1/books", auth=enable_komga).json()
    assert everything["totalElements"] == 2


# ---------------------------------------------------------------------------
# 有声书不进 Komga
# ---------------------------------------------------------------------------

def test_有声书库不出现在Komga(client, auth_headers, enable_komga, default_root):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    audio = _new_library(client, auth_headers, "有声书库", src / "audio", "audiobook")
    _put(default_root, "甲.epub")
    _put_audio_dir(src / "audio", "一本有声书")
    library.invalidate()

    libs = client.get("/api/v1/libraries", auth=enable_komga).json()
    ids = [l["id"] for l in libs]
    assert "default" in ids
    assert audio["id"] not in ids, "有声书库不该对 Komga 可见（Komga 没有音频模型）"

    # 它的书也不该从书籍 / 系列列表里漏出来
    books = client.get("/api/v1/books", auth=enable_komga).json()
    assert books["totalElements"] == 1
    series = client.post("/api/v1/series/list", auth=enable_komga).json()
    assert series["totalElements"] == 1


# ---------------------------------------------------------------------------
# CBR 媒体类型
# ---------------------------------------------------------------------------

def test_CBR有正确的媒体类型(client, auth_headers, enable_komga, default_root):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    comic = _new_library(client, auth_headers, "漫画库", src / "comics", "comic")
    _put(src / "comics", "一本.cbr", b"Rar!")
    library.invalidate()

    books = client.get("/api/v1/books", params={"library_id": comic["id"]},
                       auth=enable_komga).json()
    assert books["totalElements"] == 1
    media = books["content"][0]["media"]
    assert media["mediaType"] == "application/vnd.comicbook-rar"
    assert media["mediaProfile"] == "DIVINA"


# ---------------------------------------------------------------------------
# 系列级已读标记
# ---------------------------------------------------------------------------

def test_系列级已读与未读(client, auth_headers, enable_komga, default_root):
    _put(default_root, "甲.epub")
    _put(default_root, "乙.epub")
    library.invalidate()

    sid = client.post("/api/v1/series/list", auth=enable_komga).json()["content"][0]["id"]
    items = komga_api.find_series(sid)[1]
    assert len(items) == 1
    bid = items[0]["id"]

    # 先停在中间位置，标记已读后位置必须**保留**
    db.set_progress(bid, 5, 40.0)

    r = client.post(f"/api/v1/series/{sid}/read-progress", auth=enable_komga)
    assert r.status_code == 204, r.text
    prog = db.get_progress(bid) or {}
    assert float(prog.get("percent") or 0) == 100.0
    assert int(prog.get("locator") or 0) == 5

    dto = client.get(f"/api/v1/series/{sid}", auth=enable_komga).json()
    assert dto["booksReadCount"] == 1 and dto["booksUnreadCount"] == 0

    r = client.delete(f"/api/v1/series/{sid}/read-progress", auth=enable_komga)
    assert r.status_code == 204, r.text
    prog = db.get_progress(bid) or {}
    assert float(prog.get("percent") or 0) == 0.0
    dto = client.get(f"/api/v1/series/{sid}", auth=enable_komga).json()
    assert dto["booksReadCount"] == 0 and dto["booksUnreadCount"] == 1


def test_系列标记不存在的系列返回404(client, auth_headers, enable_komga):
    assert client.post("/api/v1/series/没有这个系列/read-progress",
                       auth=enable_komga).status_code == 404


# ---------------------------------------------------------------------------
# 书级 PATCH（官方新口径）
# ---------------------------------------------------------------------------

def test_书级PATCH与PUT等价(client, auth_headers, enable_komga, default_root):
    _put(default_root, "甲.epub")
    library.invalidate()
    bid = client.get("/api/v1/books", auth=enable_komga).json()["content"][0]["id"]

    r = client.patch(f"/api/v1/books/{bid}/read-progress", auth=enable_komga,
                     json={"completed": True})
    assert r.status_code == 204, r.text
    assert float((db.get_progress(bid) or {}).get("percent") or 0) == 100.0


# ---------------------------------------------------------------------------
# 逐库「对 Komga 暴露」（第 22 期）
# ---------------------------------------------------------------------------

def test_逐库关闭对Komga暴露(client, auth_headers, enable_komga, default_root):
    """关掉某库的 ``komga.expose`` 后它对客户端就是「不存在」：不进书库列表、
    系列 / 书籍从列表消失、**直连单本也 404**（否则开关只是把书藏起来，形同虚设）。

    默认 True = 全部符合条件的库都暴露 —— 与加这个开关之前的行为一致。
    """
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    lib_b = _new_library(client, auth_headers, "漫画库", src / "comics", "comic")
    _put(src / "comics", "乙.cbz")
    library.invalidate()

    assert config.load_config()["komga"]["expose"] is True          # 全局默认 = 暴露
    ids = [l["id"] for l in client.get("/api/v1/libraries", auth=enable_komga).json()]
    assert lib_b["id"] in ids
    book = next(b for b in client.get("/api/v1/books", auth=enable_komga).json()["content"]
                if b["libraryId"] == lib_b["id"])
    bid, sid = book["id"], book["seriesId"]
    assert client.get(f"/api/v1/books/{bid}", auth=enable_komga).status_code == 200

    r = client.put(f"/api/libraries/{lib_b['id']}/settings", headers=auth_headers,
                   json={"komga.expose": False})
    assert r.status_code == 200, r.text
    library.invalidate()

    assert lib_b["id"] not in [l["id"] for l in
                               client.get("/api/v1/libraries", auth=enable_komga).json()]
    assert all(b["libraryId"] != lib_b["id"] for b in
               client.get("/api/v1/books", auth=enable_komga).json()["content"])
    assert all(s["libraryId"] != lib_b["id"] for s in
               client.post("/api/v1/series/list", auth=enable_komga).json()["content"])
    # 直连单本 / 单系列 / 进度写入一律当不存在
    assert client.get(f"/api/v1/books/{bid}", auth=enable_komga).status_code == 404
    assert client.get(f"/api/v1/series/{sid}", auth=enable_komga).status_code == 404
    assert client.put(f"/api/v1/books/{bid}/read-progress", auth=enable_komga,
                      json={"completed": True}).status_code == 404

    # 打开 → 立刻回来
    client.put(f"/api/libraries/{lib_b['id']}/settings", headers=auth_headers,
               json={"komga.expose": True})
    library.invalidate()
    assert client.get(f"/api/v1/books/{bid}", auth=enable_komga).status_code == 200
