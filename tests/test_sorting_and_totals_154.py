"""收藏夹 / 智能书架 / 书库的手动排序 + 全库汇总（第 154 期）。

三条契约：
1. `reorder` 只接受「当前全部 id 的一个排列」——少一个、重复一个、混入未知 id 都 400；
2. 落库后 `GET` 的顺序与提交顺序一致（`sort_order` 0..n 的唯一写点）；
3. `/api/libraries` 的 `totals.libraries` 与 `items` 一致，`books` 与各库 `book_count` 之和一致。
"""
from __future__ import annotations


def _create_collections(client, auth_headers, names):
    ids = []
    for name in names:
        r = client.post("/api/collections", headers=auth_headers, json={"name": name})
        assert r.status_code == 200, r.text
        ids.append(int(r.json()["id"]))
    return ids


def _create_scopes(client, auth_headers, names):
    ids = []
    rules = [{"field": "title", "op": "contains", "value": "x"}]
    for name in names:
        r = client.post("/api/smart-scopes", headers=auth_headers,
                        json={"name": name, "rules": rules, "match": "all"})
        assert r.status_code == 200, r.text
        ids.append(int(r.json()["id"]))
    return ids


def test_收藏夹手动排序落库且顺序一致(client, auth_headers):
    ids = _create_collections(client, auth_headers, ["甲", "乙", "丙"])
    want = [ids[2], ids[0], ids[1]]
    r = client.post("/api/collections/reorder", headers=auth_headers, json={"ids": want})
    assert r.status_code == 200, r.text
    items = client.get("/api/collections", headers=auth_headers).json()["items"]
    got = [int(it["id"]) for it in items]
    assert got == want
    assert [int(it["sort_order"]) for it in items] == [0, 1, 2]


def test_收藏夹排序拒绝非完整排列(client, auth_headers):
    ids = _create_collections(client, auth_headers, ["甲", "乙"])
    for bad in ([ids[0]], [ids[0], ids[0]], [ids[0], 99999], "not-a-list"):
        r = client.post("/api/collections/reorder", headers=auth_headers, json={"ids": bad})
        assert r.status_code == 400, (bad, r.text)


def test_智能书架手动排序落库且顺序一致(client, auth_headers):
    ids = _create_scopes(client, auth_headers, ["一", "二", "三"])
    want = [ids[1], ids[2], ids[0]]
    r = client.post("/api/smart-scopes/reorder", headers=auth_headers, json={"ids": want})
    assert r.status_code == 200, r.text
    items = client.get("/api/smart-scopes", headers=auth_headers).json()["items"]
    assert [int(it["id"]) for it in items] == want


def test_智能书架排序拒绝非完整排列(client, auth_headers):
    ids = _create_scopes(client, auth_headers, ["一", "二"])
    r = client.post("/api/smart-scopes/reorder", headers=auth_headers,
                    json={"ids": [ids[0]]})
    assert r.status_code == 400


def test_书库手动排序落库且顺序一致(client, auth_headers, make_library, tmp_path):
    a = make_library("lib-a", "甲库", "ebook", tmp_path / "a")
    b = make_library("lib-b", "乙库", "ebook", tmp_path / "b")
    items = client.get("/api/libraries", headers=auth_headers).json()["items"]
    current = [str(it["id"]) for it in items]
    # 必须是**全部**库的一个排列：把 a/b 提前，其余保持原序
    want = [str(b["id"]), str(a["id"])] + [
        lid for lid in current if lid not in {str(a["id"]), str(b["id"])}
    ]
    r = client.post("/api/libraries/reorder", headers=auth_headers, json={"ids": want})
    assert r.status_code == 200, r.text
    got = [str(it["id"]) for it in
           client.get("/api/libraries", headers=auth_headers).json()["items"]]
    assert got == want


def test_书库排序拒绝非完整排列(client, auth_headers, make_library, tmp_path):
    make_library("lib-a", "甲库", "ebook", tmp_path / "a")
    make_library("lib-b", "乙库", "ebook", tmp_path / "b")
    r = client.post("/api/libraries/reorder", headers=auth_headers, json={"ids": ["lib-a"]})
    assert r.status_code == 400


def test_书库列表带全库汇总(client, auth_headers, make_library, tmp_path):
    make_library("lib-a", "甲库", "ebook", tmp_path / "a")
    make_library("lib-b", "乙库", "ebook", tmp_path / "b")
    body = client.get("/api/libraries", headers=auth_headers).json()
    t = body["totals"]
    assert t["libraries"] == len(body["items"])
    assert t["books"] == sum(int(it["book_count"]) for it in body["items"])
    assert t["bytes"] >= 0
    assert t["missing_covers"] >= 0
