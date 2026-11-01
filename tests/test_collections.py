"""收藏夹：增删改 + 列表字段（第 47 期深化总览卡用）。

- POST 建夹、PATCH 重命名（空名 400 / 重名 409 / 不存在 404）
- GET 列表返回 updated_at / first_book_id / first_book_has_cover / count
- 成员增删会刷新 updated_at 与首书
"""
import pathlib

from novelforge import config
from novelforge.core import db, library


def _make_book(make_library, tmp_path, lid, name):
    src = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"])
    make_library(lid, lid, "ebook", src / lid)
    (src / lid).mkdir(parents=True, exist_ok=True)
    (src / lid / name).write_bytes(b"EPUB")
    library.invalidate()
    return library.books(lid)[0]["id"]


def _create(client, auth_headers, name):
    return client.post(
        "/api/collections", headers=auth_headers, json={"name": name}
    )


def test_rename_and_list_fields(client, auth_headers):
    r = _create(client, auth_headers, "我的收藏")
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    lst = client.get("/api/collections", headers=auth_headers).json()
    item = next(i for i in lst["items"] if i["id"] == cid)
    assert item["name"] == "我的收藏"
    assert item["count"] == 0
    assert item["first_book_id"] is None
    assert item["first_book_has_cover"] is False
    assert item["updated_at"] > 0

    # 重命名
    rp = client.patch(
        f"/api/collections/{cid}", headers=auth_headers, json={"name": "已改名"}
    )
    assert rp.status_code == 200, rp.text
    assert rp.json()["name"] == "已改名"

    lst2 = client.get("/api/collections", headers=auth_headers).json()
    assert next(i for i in lst2["items"] if i["id"] == cid)["name"] == "已改名"


def test_rename_validation(client, auth_headers):
    r = _create(client, auth_headers, "待校验")
    cid = r.json()["id"]

    # 空名 → 400
    bad = client.patch(f"/api/collections/{cid}", headers=auth_headers, json={"name": "  "})
    assert bad.status_code == 400

    # 重名 → 409
    _create(client, auth_headers, "重名冲突")
    dup = client.patch(
        f"/api/collections/{cid}", headers=auth_headers, json={"name": "重名冲突"}
    )
    assert dup.status_code == 409

    # 不存在 → 404
    miss = client.patch(
        "/api/collections/999999", headers=auth_headers, json={"name": "x"}
    )
    assert miss.status_code == 404


def test_member_changes_first_book_and_updated_at(client, auth_headers, make_library, tmp_path):
    r = _create(client, auth_headers, "夹")
    cid = r.json()["id"]
    before = client.get("/api/collections", headers=auth_headers).json()
    before_ts = next(i for i in before["items"] if i["id"] == cid)["updated_at"]

    bid = _make_book(make_library, tmp_path, "coll-lib", "书X.epub")
    add = client.post(
        f"/api/collections/{cid}/books", headers=auth_headers, json={"book_id": bid}
    )
    assert add.status_code == 200, add.text

    after = client.get("/api/collections", headers=auth_headers).json()
    item = next(i for i in after["items"] if i["id"] == cid)
    assert item["count"] == 1
    assert item["first_book_id"] == bid
    assert item["updated_at"] >= before_ts  # 成员变动刷新「最后修改」


def test_收藏夹书目分页(client, auth_headers, make_library, tmp_path):
    """第 207 期：limit/offset 与 total/has_more；冲突 / 已消失的 id 跳过。"""
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "coll-page"
    make_library("coll-page-lib", "分页库", "ebook", root)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("一.epub", "二.epub", "三.epub"):
        (root / name).write_bytes(b"EPUB")
    library.invalidate()
    bids = [b["id"] for b in library.books("coll-page-lib")]
    assert len(bids) == 3

    cid = _create(client, auth_headers, "分页夹").json()["id"]
    for bid in bids:
        assert client.post(f"/api/collections/{cid}/books", headers=auth_headers,
                           json={"book_id": bid}).status_code == 200

    r = client.get(f"/api/collections/{cid}/books",
                   params={"limit": 2, "offset": 0}, headers=auth_headers).json()
    assert r["total"] == 3 and len(r["items"]) == 2
    assert r["has_more"] is True and r["next_offset"] == 2
    r2 = client.get(f"/api/collections/{cid}/books",
                    params={"limit": 2, "offset": 2}, headers=auth_headers).json()
    assert len(r2["items"]) == 1 and r2["has_more"] is False and r2["next_offset"] is None

    assert client.get("/api/collections/999999/books",
                      headers=auth_headers).status_code == 404
