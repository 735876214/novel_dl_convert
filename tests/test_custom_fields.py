"""第 35 期：自定义字段（定义 + 按书的值）。

这个域的两条设计要点，本文件重点钉住：

1. **key 稳定、label 可改**：值表按 key 引用 ⇒ 改显示名不该动任何一本书的值；
   key 由显示名派生一次后不再变（纯中文名走名字摘要，**不是**随机值）。
2. **「行存在」= 被管过了**：抓取只在**没有值行**时补默认值 ⇒
   「清空成空串」不会被下一次抓取填回来（清空 ≠ 删行）。

其余覆盖：类型校验、适用书库过滤、归档、垃圾桶（软删保留值 / purge 连带清值）、
排序、旧配置项迁移（幂等 + 顺手清盘上旧键）、book_id 级联、接口全流程。

全部离线：抓取相关用例 monkeypatch 掉 metasources。
"""
import json
import pathlib

import pytest

from novelforge import config
from novelforge.core import customfields, db, epub_builder, library, metafetch, metasources


def _real_epub(root, name: str, title: str, author: str = "作者") -> pathlib.Path:
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": author, "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    return path


def _fake_search(entries, best="first"):
    return lambda *a, **k: {
        "entries": entries,
        "sources": {"openlibrary": {"ok": True, "count": len(entries), "error": ""}},
        "best": (entries[0] if entries else None) if best == "first" else best,
    }


def _cand(title: str, **kw) -> dict:
    base = {"source": "openlibrary", "title": title, "author": "", "description": "",
            "publisher": "", "year": "", "language": "", "tags": [], "isbn": "",
            "cover_url": "", "score": 0.9}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# slug 与类型
# ---------------------------------------------------------------------------

def test_slug稳定且中英文都有可用的key(isolated):  # noqa: ARG001
    assert customfields.slug("Catalog") == "catalog"
    assert customfields.slug("印刷批次") == customfields.slug("印刷批次"), "同一名字必须同 key"
    assert customfields.slug("印刷批次") != customfields.slug("验收批次")
    assert customfields.slug("印刷批次").isascii(), "key 只留 ASCII（值表引用它，不该带中文）"
    assert customfields.slug("   ")  # 空名也给一个（调用方负责拒绝空显示名）


def test_类型校验(isolated):  # noqa: ARG001
    assert customfields.normalize("number", "12.5") == "12.5"
    with pytest.raises(ValueError):
        customfields.normalize("number", "十二")
    assert customfields.normalize("list", "科幻、悬疑") == "['科幻', '悬疑']"
    assert customfields.normalize("list", ["a", "b", ""]) == "['a', 'b']"
    # date 不做格式强校验（只管是不是字符串）；text 原样
    assert customfields.normalize("date", "2024-01-02") == "2024-01-02"
    assert customfields.normalize("text", "  x  ") == "x"


def test_对外值按类型还原(isolated):  # noqa: ARG001
    assert customfields.out_value("list", "['a', 'b']") == ["a", "b"]
    assert customfields.out_value("list", "坏值") == []
    assert customfields.out_value("text", None) == ""


# ---------------------------------------------------------------------------
# 定义：建 / 改标签 / 排序 / 适用书库 / 归档 / 垃圾桶
# ---------------------------------------------------------------------------

def test_建定义与按position排序(isolated):  # noqa: ARG001
    a = db.create_custom_field("catalog", "目录号")
    b = db.create_custom_field("batch", "批次")
    assert [d["key"] for d in db.list_custom_fields()] == ["catalog", "batch"]
    db.reorder_custom_fields([b["id"], a["id"]])
    assert [d["key"] for d in db.list_custom_fields()] == ["batch", "catalog"]
    assert a["position"] == 0 and a["label"] == "目录号"


def test_同key不能建两次(isolated):  # noqa: ARG001
    db.create_custom_field("catalog", "目录号")
    with pytest.raises(ValueError):
        db.create_custom_field("catalog", "另一个名字")


def test_改标签不动值(isolated):  # noqa: ARG001
    """key 与 label 分离的全部意义：值表按 key 引用，改名是纯显示层的事。"""
    d = db.create_custom_field("catalog", "目录号")
    db.set_custom_field_values("b1", {"catalog": "A-102"})
    db.update_custom_field(d["id"], label="编目号")
    assert db.get_custom_field(d["id"])["label"] == "编目号"
    assert db.custom_field_values("b1") == {"catalog": "A-102"}


def test_适用书库过滤与归档(isolated):  # noqa: ARG001
    wide = db.create_custom_field("wide", "通用")
    narrow = db.create_custom_field("narrow", "只在漫画库", library_ids=["comic-lib"])
    arch = db.create_custom_field("old", "归档了")
    db.update_custom_field(arch["id"], archived=True)

    got = [d["key"] for d in customfields.applicable(db.list_custom_fields(), "comic-lib")]
    assert got == ["wide", "narrow"]
    got = [d["key"] for d in customfields.applicable(db.list_custom_fields(), "ebook-lib")]
    assert got == ["wide"], "适用书库不含该库 ⇒ 不进编辑界面；归档项同理"
    assert wide["library_ids"] == []


def test_垃圾桶保留值恢复后还在(isolated):  # noqa: ARG001
    d = db.create_custom_field("catalog", "目录号")
    db.set_custom_field_values("b1", {"catalog": "A-102"})
    assert db.delete_custom_field(d["id"]) == 1
    assert db.list_custom_fields() == [] and len(db.trashed_custom_fields()) == 1
    assert db.custom_field_values("b1") == {"catalog": "A-102"}, "垃圾桶里的定义，值不该被清"
    assert db.restore_custom_field(d["id"]) == 1
    assert db.custom_field_values("b1") == {"catalog": "A-102"}


def test_purge门槛与连带清值(isolated):  # noqa: ARG001
    d = db.create_custom_field("catalog", "目录号")
    db.set_custom_field_values("b1", {"catalog": "A-102"})
    assert db.purge_custom_field(d["id"]) == 0, "活跃条目不许真删（与批注 / 书签同一条纪律）"
    db.delete_custom_field(d["id"])
    assert db.purge_custom_field(d["id"]) == 1
    assert db.custom_field_values("b1") == {}, "定义没了，值再没有归属 ⇒ 一起清掉"


# ---------------------------------------------------------------------------
# 按书的值
# ---------------------------------------------------------------------------

def test_写值与空串也算写入(isolated):  # noqa: ARG001
    db.create_custom_field("catalog", "目录号")
    db.set_custom_field_values("b1", {"catalog": "A-102"})
    assert db.custom_field_values("b1") == {"catalog": "A-102"}
    db.set_custom_field_values("b1", {"catalog": ""})
    assert db.custom_field_values("b1") == {"catalog": ""}, "清空 = 写空串（行仍在）"


def test_state只给适用且未归档的值(isolated):  # noqa: ARG001
    db.create_custom_field("catalog", "目录号", default_value="D")
    db.create_custom_field("narrow", "漫画专用", library_ids=["comic-lib"])
    db.set_custom_field_values("b1", {"catalog": "A-102", "narrow": "不该出现"})
    st = customfields.state({"id": "b1", "library_id": "ebook-lib"})
    assert st == [{"key": "catalog", "label": "目录号", "type": "text",
                   "default_value": "D", "value": "A-102"}]


def test_write只收适用键并回报忽略项(isolated):  # noqa: ARG001
    db.create_custom_field("catalog", "目录号")
    db.create_custom_field("narrow", "漫画专用", library_ids=["comic-lib"])
    res = customfields.write({"id": "b1", "library_id": "ebook-lib"},
                             {"catalog": "A-102", "narrow": "x", "不存在": "y"})
    assert res["saved"] == ["catalog"]
    assert res["ignored"] == ["narrow", "不存在"], "忽略项是排序后的（中文排在 ASCII 之后）"
    assert db.custom_field_values("b1") == {"catalog": "A-102"}


def test_write按类型报错(isolated):  # noqa: ARG001
    db.create_custom_field("pages", "页数", type="number")
    with pytest.raises(ValueError):
        customfields.write({"id": "b1"}, {"pages": "很多"})


# ---------------------------------------------------------------------------
# 旧配置迁移
# ---------------------------------------------------------------------------

def test_迁移旧配置并清掉盘上旧键(isolated, tmp_path, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"metadata_fetch": {"custom_fields": [
        {"name": "Catalog", "value": "A-102"},
        {"name": "印刷批次", "value": "2024-01"},
        {"name": "", "value": "空名丢弃"},
    ]}})
    cfg = {"metadata_fetch": {"custom_fields": [{"name": "Catalog", "value": "A-102"},
                                                {"name": "印刷批次", "value": "2024-01"}]}}

    created = customfields.migrate_from_config(cfg)
    assert created == ["catalog", customfields.slug("印刷批次")]
    items = db.list_custom_fields()
    assert [(d["key"], d["label"], d["default_value"]) for d in items] == [
        ("catalog", "Catalog", "A-102"), (customfields.slug("印刷批次"), "印刷批次", "2024-01")]
    # 配置项下线：settings.json 里那枚旧键被删掉（否则段级合并会把它永远留在盘上）
    ov = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert "custom_fields" not in (ov.get("metadata_fetch") or {})


def test_迁移是幂等的(isolated, tmp_path, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    cfg = {"metadata_fetch": {"custom_fields": [{"name": "Catalog", "value": "A-102"}]}}
    assert customfields.migrate_from_config(cfg) == ["catalog"]
    assert customfields.migrate_from_config(cfg) == [], "第二次跑不该重复建定义"
    assert len(db.list_custom_fields()) == 1


def test_迁移不覆盖同key的垃圾桶条目(isolated, tmp_path, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    d = db.create_custom_field("catalog", "我自己建的")
    db.delete_custom_field(d["id"])
    assert customfields.migrate_from_config({"metadata_fetch": {"custom_fields": [
        {"name": "catalog", "value": "x"}]}}) == []
    assert db.list_custom_fields() == [], "同 key 已在垃圾桶 ⇒ 跳过，不新建一份重复定义"


# ---------------------------------------------------------------------------
# 级联（改名 / 删书）
# ---------------------------------------------------------------------------

def test_值表进级联清单(isolated):  # noqa: ARG001
    assert "book_custom_values" in db.ORPHAN_TABLES
    assert "book_custom_values" in db.REMAP_TABLES
    assert "book_custom_values" not in db.REMAP_MERGE_TABLES, \
        "值表没有软删 ⇒ 探测即精确判据，不需要「标记型表」那套豁免"


def test_改名把值搬过去(isolated):  # noqa: ARG001
    db.set_custom_field_values("lib$old", {"catalog": "A-102"})
    moved = db.remap_book_id("lib$old", "lib$new")
    assert moved["book_custom_values"] == 1
    assert db.custom_field_values("lib$new") == {"catalog": "A-102"}
    assert db.custom_field_values("lib$old") == {}


def test_删书清行(isolated):  # noqa: ARG001
    db.set_custom_field_values("gone", {"catalog": "A-102"})
    assert db.book_id_refs()["book_custom_values"] == ["gone"]
    assert db.delete_orphans({"book_custom_values": ["gone"]})["book_custom_values"] == 1
    assert db.custom_field_values("gone") == {}


# ---------------------------------------------------------------------------
# 抓取：默认值只补「还没有值行」的书
# ---------------------------------------------------------------------------

@pytest.fixture
def one_book(isolated, default_root):  # noqa: ARG001
    _real_epub(default_root, "自定义.epub", title="自定义")
    library.invalidate()
    return library.books()[0]


def _plan(book, monkeypatch, **mf) -> dict:
    monkeypatch.setattr(metasources, "search_all",
                        _fake_search([_cand("自定义", author="在线作者")]))
    monkeypatch.setattr(metasources, "search_by_isbn", lambda *a, **k: None)
    cfg = {"metadata_fetch": {"enabled": True, "sources": ["openlibrary"],
                              "threshold": 0.9, "fields": {"author": "overwrite"}, **mf}}
    return metafetch.plan(names=[book["name"]], cfg=cfg, limit=1)["items"][0]


def test_抓取补默认值(one_book, monkeypatch):
    db.create_custom_field("catalog", "目录号", default_value="A-102")
    it = _plan(one_book, monkeypatch)
    assert it["changes"]["catalog"]["to"] == "A-102"
    assert it["changes"]["catalog"]["source"] == "自定义字段"


def test_没有值行才补(one_book, monkeypatch):
    db.create_custom_field("catalog", "目录号", default_value="A-102")
    db.set_custom_field_values(one_book["id"], {"catalog": ""})     # 管过了（清空）
    it = _plan(one_book, monkeypatch)
    assert "catalog" not in it["changes"], "行存在即「被管过了」，默认值不该再填回来"


def test_没有默认值就不参与抓取(one_book, monkeypatch):
    db.create_custom_field("note", "备注")
    it = _plan(one_book, monkeypatch)
    assert "note" not in it["changes"]


def test_不适用的书库不补(one_book, monkeypatch):
    db.create_custom_field("catalog", "目录号", default_value="A-102",
                           library_ids=["comic-lib"])
    it = _plan(one_book, monkeypatch)
    assert "catalog" not in it["changes"]


def test_锁挡住自定义字段(one_book, monkeypatch):
    db.create_custom_field("catalog", "目录号", default_value="A-102")
    db.set_lock(one_book["id"], "catalog")
    it = _plan(one_book, monkeypatch)
    assert "catalog" not in it["changes"]
    assert "catalog" in it["locked"]


def test_没有在线候选也补自定义默认值(one_book, monkeypatch):
    db.create_custom_field("catalog", "目录号", default_value="A-102")
    monkeypatch.setattr(metasources, "search_all", _fake_search([], best=None))
    monkeypatch.setattr(metasources, "search_by_isbn", lambda *a, **k: None)
    it = metafetch.plan(names=[one_book["name"]],
                        cfg={"metadata_fetch": {"enabled": True, "threshold": 0.9}},
                        limit=1)["items"][0]
    assert not it["best_score"] and it["error"], "这一条本来就是「没有候选」"
    assert it["changes"]["catalog"]["to"] == "A-102", "自定义字段不依赖在线源"


def test_apply写入自定义字段(one_book, monkeypatch):
    db.create_custom_field("catalog", "目录号")
    monkeypatch.setattr(metasources, "search_by_isbn", lambda *a, **k: None)
    res = metafetch.apply([{"name": one_book["name"], "book_id": one_book["id"],
                            "fields": {"catalog": "A-102", "author": "在线作者"}}],
                          cfg={"metadata_fetch": {"enabled": True}})
    assert res["applied"][0]["fields"] == ["author", "catalog"], "两处落点都要如实回报"
    assert db.custom_field_values(one_book["id"]) == {"catalog": "A-102"}
    assert db.get_online(one_book["id"])["author"]["value"] == "在线作者", "元数据仍走 meta_online"


def test_apply按类型拒绝坏值(one_book, monkeypatch):
    db.create_custom_field("pages", "页数", type="number")
    monkeypatch.setattr(metasources, "search_by_isbn", lambda *a, **k: None)
    res = metafetch.apply([{"name": one_book["name"], "book_id": one_book["id"],
                            "fields": {"pages": "很多"}}],
                          cfg={"metadata_fetch": {"enabled": True}})
    assert res["applied"] == [] and res["failed"], "坏值不该落库"
    assert db.custom_field_values(one_book["id"]) == {}


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------

def _book(client, headers) -> dict:
    r = client.get("/api/books", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_接口定义全流程(client, auth_headers):  # noqa: ARG001
    r = client.post("/api/custom-fields", headers=auth_headers,
                    json={"label": "Catalog", "type": "text", "default_value": "A-102"})
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["key"] == "catalog" and item["default_value"] == "A-102"
    cid = item["id"]

    # 列表带类型表（前端下拉直接用，不必写死一份）
    got = client.get("/api/custom-fields", headers=auth_headers).json()
    assert [t["key"] for t in got["types"]] == list(customfields.TYPE_KEYS)
    assert len(got["items"]) == 1

    # 改标签 + 归档
    r = client.patch(f"/api/custom-fields/{cid}", headers=auth_headers,
                     json={"label": "编目号", "archived": True})
    assert r.json()["item"]["label"] == "编目号" and r.json()["item"]["archived"] is True

    # 排序（⚠️ 纯中文显示名派生不出 ASCII key，会回落成名字摘要 ⇒ 想要 ASCII key 就显式给 key）
    second = client.post("/api/custom-fields", headers=auth_headers,
                         json={"label": "批次", "key": "batch"}).json()["item"]
    assert second["key"] == "batch"
    r = client.post("/api/custom-fields/reorder", headers=auth_headers,
                    json={"ids": [second["id"], cid]})
    assert [d["key"] for d in r.json()["items"]] == ["batch", "catalog"]

    # 垃圾桶：软删 → 恢复 → 软删 → 彻底删
    assert client.delete(f"/api/custom-fields/{cid}", headers=auth_headers).json()["trashed"] is True
    assert client.get("/api/custom-fields?include_trashed=1",
                      headers=auth_headers).json()["trashed"]
    assert client.post(f"/api/custom-fields/{cid}/restore",
                       headers=auth_headers).status_code == 200
    client.delete(f"/api/custom-fields/{cid}", headers=auth_headers)
    assert client.delete(f"/api/custom-fields/{cid}/purge", headers=auth_headers).status_code == 200
    assert [d["key"] for d in client.get("/api/custom-fields",
                                         headers=auth_headers).json()["items"]] == ["batch"]


def test_接口拒绝坏类型与空标签(client, auth_headers):  # noqa: ARG001
    assert client.post("/api/custom-fields", headers=auth_headers,
                       json={"label": ""}).status_code == 400
    assert client.post("/api/custom-fields", headers=auth_headers,
                       json={"label": "x", "type": "图表"}).status_code == 400
    assert client.post("/api/custom-fields", headers=auth_headers,
                       json={"label": "x", "type": "number",
                             "default_value": "十二"}).status_code == 400


def test_接口purge活跃条目被拒(client, auth_headers):  # noqa: ARG001
    cid = client.post("/api/custom-fields", headers=auth_headers,
                      json={"label": "x"}).json()["item"]["id"]
    assert client.delete(f"/api/custom-fields/{cid}/purge", headers=auth_headers).status_code == 400
    assert client.post("/api/custom-fields/999999/restore",
                       headers=auth_headers).status_code == 404
    assert client.patch("/api/custom-fields/999999", headers=auth_headers,
                        json={"label": "x"}).status_code == 404


def test_接口不存在的库id被丢掉(client, auth_headers):  # noqa: ARG001
    r = client.post("/api/custom-fields", headers=auth_headers,
                    json={"label": "x", "library_ids": ["没有这个库"]})
    assert r.json()["item"]["library_ids"] == [], "丢掉的语义退化成「全部书库」而非写进一个死 id"


def test_接口单书读写自定义值(client, auth_headers, default_root):  # noqa: ARG001
    _real_epub(default_root, "接口自定义.epub", title="接口自定义")
    library.invalidate()
    b = _book(client, auth_headers)
    cid = client.post("/api/custom-fields", headers=auth_headers,
                      json={"label": "目录号", "key": "catalog", "type": "text",
                            "default_value": "A-102"}).json()["item"]["id"]

    meta = client.get(f"/api/books/{b['id']}/metadata", headers=auth_headers).json()
    assert meta["custom"] == [{"key": "catalog", "label": "目录号", "type": "text",
                               "default_value": "A-102", "value": ""}]

    r = client.post(f"/api/books/{b['id']}/metadata", headers=auth_headers,
                    json={"custom": {"catalog": "B-7", "不存在": "x"}})
    assert r.status_code == 200, r.text
    assert r.json()["custom_saved"] == ["catalog"] and r.json()["custom_ignored"] == ["不存在"]
    assert r.json()["custom"][0]["value"] == "B-7"

    # 归档之后就不再下发给详情页
    client.patch(f"/api/custom-fields/{cid}", headers=auth_headers, json={"archived": True})
    assert client.get(f"/api/books/{b['id']}/metadata",
                      headers=auth_headers).json()["custom"] == []


def test_接口只提交自定义值也能保存(client, auth_headers, default_root):  # noqa: ARG001
    """详情页整张表单一起提交；只改动自定义字段那一栏时也不该被「没有可改写字段」拒掉。"""
    _real_epub(default_root, "只自定义.epub", title="只自定义")
    library.invalidate()
    b = _book(client, auth_headers)
    client.post("/api/custom-fields", headers=auth_headers, json={"label": "目录号"})
    r = client.post(f"/api/books/{b['id']}/metadata", headers=auth_headers,
                    json={"custom": {"catalog": "C-1"}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == []


def test_接口坏值返回400(client, auth_headers, default_root):  # noqa: ARG001
    _real_epub(default_root, "坏值.epub", title="坏值")
    library.invalidate()
    b = _book(client, auth_headers)
    client.post("/api/custom-fields", headers=auth_headers,
                json={"label": "页数", "key": "pages", "type": "number"})
    r = client.post(f"/api/books/{b['id']}/metadata", headers=auth_headers,
                    json={"custom": {"pages": "很多"}})
    assert r.status_code == 400 and "数字" in r.json()["detail"]


def test_接口未登录401(client):  # noqa: ARG001
    assert client.get("/api/custom-fields").status_code == 401
    assert client.post("/api/custom-fields", json={"label": "x"}).status_code == 401
