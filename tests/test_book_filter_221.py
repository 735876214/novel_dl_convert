"""书目**规则筛选**（第 221 期）：内联规则 + 服务端筛选分页。

第 218 期把智能书架的求值搬到服务端；本期把**临时筛选**也搬过去 ——
`GET /api/books` 接受一条内联规则（`rules` 参数），与 `scope_id` 共用同一条求值路径。

这里钉三件事：

1. **内联规则真的筛了**（不是客户端筛）；
2. **非法规则一律 400**（未知字段 / 非法操作 / 非法数值 / 超过 60 条），且带原因；
3. **`scope_id` 优先于 `rules`**（已存的书架更具体）。
"""
from __future__ import annotations

import json

from novelforge.core import bookfilter


def _rule(field, op, value="") -> dict:
    return {"field": field, "op": op, "value": value}


def _seed(tmp_path, make_library, make_book):
    from novelforge.core import db, library

    lib = make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    root = tmp_path / "lib"
    for name in ("a.epub", "b.epub", "c.epub"):
        make_book(root, name)
    library.invalidate()
    by_name = {b["name"]: b for b in library.books("lib$1")}
    db.set_override(by_name["a.epub"]["id"], "title", "甲")
    db.set_override(by_name["a.epub"]["id"], "author", "刘慈欣")
    db.set_override(by_name["a.epub"]["id"], "tags", "科幻")
    db.set_override(by_name["b.epub"]["id"], "title", "乙")
    db.set_override(by_name["b.epub"]["id"], "author", "金庸")
    db.set_override(by_name["b.epub"]["id"], "tags", "武侠")
    db.set_override(by_name["c.epub"]["id"], "title", "丙")
    db.set_override(by_name["c.epub"]["id"], "author", "刘慈欣")
    db.set_override(by_name["c.epub"]["id"], "tags", "科幻")
    db.set_rating(by_name["c.epub"]["id"], 5)
    library.invalidate()
    return lib, by_name


# ---------------------------------------------------------------------------
# 纯函数：解析与上限
# ---------------------------------------------------------------------------

def test_内联规则解析_空即不筛选():
    assert bookfilter.parse_inline(None) == ([], "all")
    assert bookfilter.parse_inline({}) == ([], "all")
    assert bookfilter.parse_inline({"rules": []}) == ([], "all")


def test_内联规则解析_非法的一律拒():
    for bad in (
        {"rules": "不是数组"},
        {"rules": [_rule("不是字段", "equals", "x")]},
        {"rules": [_rule("status", "at_least", "3")]},
        {"rules": [_rule("stars", "at_least", "很多")]},
        {"rules": [_rule("tag", "equals", "x")], "match": "some"},
    ):
        try:
            bookfilter.parse_inline(bad)
        except ValueError:
            continue
        raise AssertionError(f"这条必须被拒：{bad}")


def test_内联规则有上限():
    many = {"rules": [_rule("tag", "contains", f"t{i}") for i in range(bookfilter.MAX_INLINE_RULES + 1)]}
    try:
        bookfilter.parse_inline(many)
    except ValueError as e:
        assert str(bookfilter.MAX_INLINE_RULES) in str(e)
    else:
        raise AssertionError("超过上限必须被拒")


def test_查询串不是合法_JSON_报错():
    try:
        bookfilter.rules_from_query("{不是 json")
    except ValueError:
        pass
    else:
        raise AssertionError("坏 JSON 必须被拒")


# ---------------------------------------------------------------------------
# 接口：GET /api/books?rules=...
# ---------------------------------------------------------------------------

def test_内联规则筛选并分页(client, auth_headers, isolated, tmp_path,
                          make_library, make_book):
    _seed(tmp_path, make_library, make_book)
    payload = json.dumps({"rules": [_rule("tag", "contains", "科幻")], "match": "all"},
                         ensure_ascii=False)
    r = client.get("/api/books", headers=auth_headers, params={"rules": payload})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert {b["title"] for b in body["items"]} == {"甲", "丙"}

    page = client.get("/api/books", headers=auth_headers,
                      params={"rules": payload, "limit": 1, "offset": 0}).json()
    assert len(page["items"]) == 1 and page["total"] == 2 and page["has_more"] is True


def test_内联规则与智能书架_同一套口径(client, auth_headers, isolated, tmp_path,
                                     make_library, make_book):
    _seed(tmp_path, make_library, make_book)
    rules = [_rule("author", "contains", "刘慈欣")]
    payload = json.dumps({"rules": rules, "match": "all"}, ensure_ascii=False)

    inline = client.get("/api/books", headers=auth_headers,
                        params={"rules": payload}).json()
    assert inline["total"] == 2

    # 存成智能书架后，同一条规则命中数必须**完全一样**（同一求值路径）
    sid = client.post("/api/smart-scopes", headers=auth_headers,
                      json={"name": "刘", "rules": rules, "match": "all"}).json()["id"]
    scope = client.get("/api/books", headers=auth_headers,
                       params={"scope_id": sid}).json()
    assert scope["total"] == inline["total"]
    listed = client.get("/api/smart-scopes", headers=auth_headers,
                        params={"library_id": "lib$1"}).json()["items"]
    assert [s["count"] for s in listed if s["id"] == sid] == [inline["total"]]


def test_scope_id_优先于内联规则(client, auth_headers, isolated, tmp_path,
                                  make_library, make_book):
    _seed(tmp_path, make_library, make_book)
    sid = client.post("/api/smart-scopes", headers=auth_headers,
                      json={"name": "科幻",
                            "rules": [_rule("tag", "contains", "科幻")],
                            "match": "all"}).json()["id"]
    # 内联规则指向另一个集合；给了 scope_id 时以 scope_id 为准
    payload = json.dumps({"rules": [_rule("author", "contains", "金庸")], "match": "all"},
                         ensure_ascii=False)
    body = client.get("/api/books", headers=auth_headers,
                      params={"scope_id": sid, "rules": payload}).json()
    assert {b["title"] for b in body["items"]} == {"甲", "丙"}


def test_内联规则非法一律_400(client, auth_headers, isolated, tmp_path,
                               make_library, make_book):
    _seed(tmp_path, make_library, make_book)
    bad = json.dumps({"rules": [_rule("不是字段", "equals", "x")]}, ensure_ascii=False)
    r = client.get("/api/books", headers=auth_headers, params={"rules": bad})
    assert r.status_code == 400
    assert "不是字段" in r.json()["detail"]

    r2 = client.get("/api/books", headers=auth_headers, params={"rules": "{不是 json"})
    assert r2.status_code == 400


def test_不给_rules_时逐字不变(client, auth_headers, isolated, tmp_path,
                                make_library, make_book):
    """不带 `rules` ⇒ 与改造前一致（全量、顺序不变）。"""
    _seed(tmp_path, make_library, make_book)
    body = client.get("/api/books", headers=auth_headers).json()
    assert body["total"] == 3
    assert [b["title"] for b in body["items"]] == ["甲", "乙", "丙"]
