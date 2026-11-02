"""书目规则引擎（第 218 期）：字段 / 操作清单、求值语义、服务端筛选与计数。

第 218 期把智能书架求值从前端搬到 ``core/bookrules.py``（**唯一实现**）：
字段规格、校验、求值三处共用同一份 :data:`bookrules.FIELDS`；前端表单从
``GET /api/book-rules`` 取清单，不再静态抄一份。
"""
from __future__ import annotations

from novelforge.core import bookrules, db, library


def _rule(field, op, value="") -> dict:
    return {"field": field, "op": op, "value": value}


# ---------------------------------------------------------------------------
# 清单与校验
# ---------------------------------------------------------------------------

def test_字段与操作清单覆盖扩展项():
    s = bookrules.schema()
    keys = {f["key"] for f in s["fields"]}
    # 第 218 期新增：演播者 / 收藏夹 / 文件问题 / 布尔与数值字段
    for k in ("narrator", "collection", "issue", "has_cover", "has_description",
              "fixed_layout", "percent", "size_mb", "pages", "tracks",
              "collection_count", "name", "isbn", "library", "library_type"):
        assert k in keys, k
    ops = {o["key"]: o for o in s["ops"]}
    assert ops["is_empty"]["needs_value"] is False
    assert ops["at_least"]["needs_value"] is True
    # 前端的字段 → 可用操作直接从这份清单取，不允许再抄
    tag = next(f for f in s["fields"] if f["key"] == "tag")
    assert "starts_with" not in tag["ops"] and "is_empty" in tag["ops"]


def test_校验_未知字段与数值值():
    try:
        bookrules.validate([_rule("nope", "equals", "x")])
    except ValueError as e:
        assert "nope" in str(e)
    else:                                             # pragma: no cover
        raise AssertionError("未知字段必须被拒")

    try:
        bookrules.validate([_rule("stars", "at_least", "很多")])
    except ValueError as e:
        assert "stars" in str(e) and "数字" in str(e)
    else:                                             # pragma: no cover
        raise AssertionError("数值字段的非法值必须被拒")

    # 无值操作允许空值（「没有 ISBN」这类规则）
    rules, match = bookrules.validate([_rule("isbn", "is_empty", "")])
    assert rules == [{"field": "isbn", "op": "is_empty", "value": ""}] and match == "all"


# ---------------------------------------------------------------------------
# 求值语义（纯函数，不碰库）
# ---------------------------------------------------------------------------

def _book(**kw) -> dict:
    base = {"title": "三体", "author": "刘慈欣", "series": "地球往事", "tags": ["科幻"],
            "narrators": [], "format": "EPUB", "status": None, "percent": 0.0,
            "stars": 0, "year": "2008", "issues": [], "collection_ids": [],
            "has_cover": True, "has_description": True, "fixed_layout": False,
            "size": 1024 * 1024, "pages": 300, "tracks": 0, "annotation_count": 0,
            "library_id": "lib$1", "added_at": 0}
    base.update(kw)
    return base


def test_文本与列表语义():
    b = _book()
    assert bookrules.evaluate([b], [_rule("title", "contains", "三体")]) == [b]
    assert bookrules.evaluate([b], [_rule("author", "starts_with", "刘")]) == [b]
    assert bookrules.evaluate([b], [_rule("series", "ends_with", "往事")]) == [b]
    assert bookrules.evaluate([b], [_rule("author", "not_equals", "别人")]) == [b]
    assert bookrules.evaluate([b], [_rule("tag", "contains", "科幻")]) == [b]
    assert bookrules.evaluate([b], [_rule("narrator", "is_empty")]) == [b]
    assert bookrules.evaluate([b], [_rule("isbn", "is_empty")]) == [b]
    assert bookrules.evaluate([b], [_rule("title", "contains", "银河")]) == []


def test_数值_布尔_状态与上下文():
    b = _book(percent=100.0, stars=5, collection_ids=[7], status=None)
    ctx = {"thresholds": (0.0, 99.5), "library_names": {"lib$1": "主书库"},
           "collection_names": {7: "待读"}}
    assert bookrules.evaluate([b], [_rule("percent", "at_least", "99")], thresholds=(0.0, 99.5)) == [b]
    assert bookrules.evaluate([b], [_rule("stars", "equals", "5")]) == [b]
    # 老数据里可能存着非法数值（新规则在保存时就会被拒）：**不命中**，不能当成「全部」
    assert bookrules.evaluate([b], [_rule("stars", "at_least", "很多")]) == []
    assert bookrules.evaluate([b], [_rule("has_cover", "equals", "yes")]) == [b]
    assert bookrules.evaluate([b], [_rule("fixed_layout", "equals", "no")]) == [b]
    assert bookrules.evaluate([b], [_rule("collection", "contains", "待读")], **ctx) == [b]
    assert bookrules.evaluate([b], [_rule("library", "equals", "主书库")], **ctx) == [b]
    # 没有状态行 ⇒ 按进度 + 阈值兜底成 finished
    assert bookrules.evaluate([b], [_rule("status", "equals", "finished")], **ctx) == [b]
    # 没标年份的书不参与年份比较
    assert bookrules.evaluate([_book(year="")], [_rule("year", "at_most", "2020")]) == []
    # 入库天数按 added_at（用户可改写的入库时间），不是文件 mtime
    import time as _time
    b2 = _book(added_at=_time.time() - 10 * 86400, mtime=_time.time())
    assert bookrules.evaluate([b2], [_rule("added", "at_most", "11")]) == [b2]
    assert bookrules.evaluate([b2], [_rule("added", "at_most", "9")]) == []


def test_all_any_与空规则():
    a = _book(title="甲", tags=["科幻"])
    b = _book(title="乙", tags=["武侠"])
    assert bookrules.evaluate([a, b], [_rule("title", "contains", "甲"),
                                       _rule("tag", "contains", "武侠")], "all") == []
    assert bookrules.evaluate([a, b], [_rule("title", "contains", "甲"),
                                       _rule("tag", "contains", "武侠")], "any") == [a, b]
    assert bookrules.evaluate([a, b], [], "all") == [a, b]


# ---------------------------------------------------------------------------
# 接口：/api/books?scope_id / 计数 / 预览
# ---------------------------------------------------------------------------

def _seed(tmp_path, make_library, make_book):
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


def _create_scope(client, headers, rules, match="all") -> int:
    r = client.post("/api/smart-scopes", headers=headers,
                    json={"name": "测试", "rules": rules, "match": match})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_服务端筛选_分页与错误(client, auth_headers, isolated, tmp_path,
                              make_library, make_book):
    _lib, _books = _seed(tmp_path, make_library, make_book)
    sid = _create_scope(client, auth_headers, [_rule("tag", "contains", "科幻")])

    r = client.get("/api/books", headers=auth_headers, params={"scope_id": sid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert {b["title"] for b in body["items"]} == {"甲", "丙"}

    page = client.get("/api/books", headers=auth_headers,
                      params={"scope_id": sid, "limit": 1, "offset": 0}).json()
    assert len(page["items"]) == 1 and page["total"] == 2 and page["has_more"] is True
    page2 = client.get("/api/books", headers=auth_headers,
                       params={"scope_id": sid, "limit": 1, "offset": 1}).json()
    assert len(page2["items"]) == 1 and page2["has_more"] is False

    assert client.get("/api/books", headers=auth_headers,
                      params={"scope_id": "abc"}).status_code == 400
    assert client.get("/api/books", headers=auth_headers,
                      params={"scope_id": 99999}).status_code == 404


def test_计数_与预览走同一求值路径(client, auth_headers, isolated, tmp_path,
                                   make_library, make_book):
    _seed(tmp_path, make_library, make_book)
    sid = _create_scope(client, auth_headers, [_rule("author", "contains", "刘慈欣")])

    listed = client.get("/api/smart-scopes", headers=auth_headers,
                        params={"library_id": "lib$1"}).json()["items"]
    assert [s["count"] for s in listed if s["id"] == sid] == [2]

    prev = client.post("/api/smart-scopes/preview", headers=auth_headers,
                       json={"rules": [_rule("author", "contains", "刘慈欣")],
                             "match": "all", "library_id": "lib$1"})
    assert prev.status_code == 200 and prev.json() == {"count": 2, "total": 3}

    # 同一组规则、同一批数据：计数 / 预览 / 书目三处必须一致
    listed_books = client.get("/api/books", headers=auth_headers,
                              params={"scope_id": sid}).json()
    assert listed_books["total"] == prev.json()["count"] == 2


def test_新字段可直接用于规则(client, auth_headers, isolated, tmp_path,
                              make_library, make_book):
    _seed(tmp_path, make_library, make_book)
    # 评分字段（第 218 期扩展操作：equals / not_equals 也合法）
    sid = _create_scope(client, auth_headers, [_rule("stars", "equals", "5")])
    got = client.get("/api/books", headers=auth_headers,
                     params={"scope_id": sid}).json()
    assert [b["title"] for b in got["items"]] == ["丙"]

    # 无值操作：没有 ISBN 的书（三本都没有）
    sid2 = _create_scope(client, auth_headers, [_rule("isbn", "is_empty")])
    got2 = client.get("/api/books", headers=auth_headers,
                      params={"scope_id": sid2}).json()
    assert got2["total"] == 3
