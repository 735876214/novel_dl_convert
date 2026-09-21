"""第 35 期：元数据**字段级锁定**（`meta_locks`）。

锁的语义只有一条，但它是**显式**的（这是它与既有的「改过就受保护」的本质区别）：

- 作用面**只到抓取**：上锁后在线抓取永不改写该字段（即使策略写着「总是覆盖」）；
- **不挡手动编辑**：用户当下改一手的意志走在最顶层（`meta_override`），
  不该被一个更早的标记拦下；
- 与 `overridden` **正交**：可以「没改过但锁上」，也可以「改过但没锁（抓取之后可再接管）」。

因此本文件重点钉四类边界：
1. 锁的存取（含封面用的独立键 `cover`）；
2. 抓取的两道闸（`plan` 不产生改动、`apply` 不落库）—— 后者防的是「预览页是上锁之前渲染的」；
3. 级联：改名搬迁（`PRIMARY KEY(book_id, field)` ⇒ 必须逐行，且**标记型表不做整表跳过**）、
   删书孤儿清理；
4. 接口层：上锁 / 解锁 / 非法字段 / 书不存在 / 未登录。

全部离线：`metasources` 的外呼一律被 monkeypatch 顶掉。
"""
import pathlib

import pytest

from novelforge.core import db, fileops, library, metafetch, metasources, metastore
from novelforge.core import epub_builder


def _real_epub(root, name: str, title: str, author: str = "作者") -> pathlib.Path:
    """真实可解析的 EPUB（`plan()` 要读文件里的原值来判断「要不要改」）。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": author, "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    return path


def _fake_search(entries, best=None):
    """顶掉在线检索（`search_all` 的形状）；`best` 缺省取第一条。"""
    return lambda *a, **k: {
        "entries": entries,
        "sources": {"openlibrary": {"ok": True, "count": len(entries), "error": ""}},
        "best": best if best is not None else (entries[0] if entries else None),
    }


def _cand(title: str, **kw):
    base = {"source": "openlibrary", "title": title, "author": "", "description": "",
            "publisher": "", "year": "", "language": "", "tags": [], "isbn": "",
            "cover_url": "", "score": 0.9}
    base.update(kw)
    return base


@pytest.fixture
def lock_book(isolated, default_root):  # noqa: ARG001 —— 依赖 isolated 切目录
    """库里只有一本《锁测》，且**没有被编辑过**（用来证明锁能落在没改过的字段上）。"""
    _real_epub(default_root, "锁测.epub", title="锁测", author="原值作者")
    library.invalidate()
    books = library.books()
    assert len(books) == 1, [b["name"] for b in books]
    return books[0]


def _plan(book, monkeypatch, cand=None, **mf):
    """跑一次 `plan(names=[这本书])`，返回它那一条 item。**只算不改**。"""
    # ⚠️ 候选值必须与文件里的原值**都不同**，否则「原值 == 候选」会被 plan 判为无需改动
    # （EPUB 夹具的 language 就是 zh，这里刻意给 en）
    cand = cand or _cand("在线标题", author="在线作者", description="在线简介",
                         publisher="在线出版社", year="2001", language="en",
                         isbn="9787000000001", tags=["科幻"])
    monkeypatch.setattr(metasources, "search_all", _fake_search([cand]))
    monkeypatch.setattr(metasources, "search_by_isbn", lambda *a, **k: None)
    cfg = {"metadata_fetch": {"enabled": True, "sources": ["openlibrary"],
                              "threshold": 0.5, "limit": 5, **mf}}
    res = metafetch.plan(names=[book["name"]], cfg=cfg, limit=5)
    assert res["enabled"], res
    assert res["items"], res
    return res["items"][0]


# ---------------------------------------------------------------------------
# 存取：上锁 / 解锁 / 全量取
# ---------------------------------------------------------------------------

def test_上锁解锁与全量取(isolated):  # noqa: ARG001
    assert db.get_locks("b1") == set()
    assert db.set_lock("b1", "author") is True
    db.set_lock("b1", db.LOCK_COVER)
    assert db.get_locks("b1") == {"author", db.LOCK_COVER}
    assert db.set_lock("b1", "author", False) is False
    assert db.get_locks("b1") == {db.LOCK_COVER}
    assert db.all_locks() == {"b1": {db.LOCK_COVER}}


def test_解不存在的锁是幂等的(isolated):  # noqa: ARG001
    assert db.set_lock("b1", "title", False) is False
    assert db.get_locks("b1") == set()


def test_锁与覆盖分表互不影响(isolated):  # noqa: ARG001
    """锁必须能存在于**没有被覆盖**的字段上（这正是它与 override 分表的理由）。"""
    db.set_lock("b1", "series_index")            # 从没被编辑过的字段
    assert db.get_overrides("b1") == {}
    assert metastore.state({"id": "b1"})["series_index"]["locked"] is True
    assert metastore.state({"id": "b1"})["series_index"]["overridden"] is False


def test_state下发locked且两种组合都成立(isolated):  # noqa: ARG001
    db.set_override("b1", "publisher", "我自己填的")   # 改过、没锁
    db.set_lock("b1", "language")                    # 没改过、锁了
    st = metastore.state({"id": "b1"})
    assert st["publisher"]["overridden"] is True and st["publisher"]["locked"] is False
    assert st["language"]["overridden"] is False and st["language"]["locked"] is True
    # 锁不参与生效值：生效值仍是 override > online > opf
    assert st["publisher"]["value"] == "我自己填的"


def test_locked_fields按字段表顺序并含封面(isolated):  # noqa: ARG001
    for f in ("isbn", "title", db.LOCK_COVER, "author"):
        db.set_lock("b1", f)
    assert metastore.locked_fields({"id": "b1"}) == ["title", "author", "isbn", db.LOCK_COVER]
    assert metastore.locked_fields({}) == []          # 没 id 不算


# ---------------------------------------------------------------------------
# 抓取闸门一：plan 不产生改动
# ---------------------------------------------------------------------------

def test_没上锁时照常给出改动(lock_book, monkeypatch):
    """对照组：不上锁 ⇒ 每个字段都按「总是覆盖」产生改动（证明下面的断言不是因为没候选）。"""
    it = _plan(lock_book, monkeypatch, fields={f: "overwrite" for f in fileops.METADATA_FIELDS})
    assert {"title", "author", "description", "publisher", "language", "isbn"} <= set(it["changes"])
    assert it["locked"] == []


def test_锁定字段不进改动即使策略是总是覆盖(lock_book, monkeypatch):
    db.set_lock(lock_book["id"], "author")
    db.set_lock(lock_book["id"], "publisher")
    it = _plan(lock_book, monkeypatch, fields={f: "overwrite" for f in fileops.METADATA_FIELDS})
    assert "author" not in it["changes"], "锁比策略更硬：overwrite 也不能动它"
    assert "publisher" not in it["changes"]
    # 只挡被锁的那两个，其余照旧
    assert {"title", "description", "language", "isbn"} <= set(it["changes"])
    assert it["locked"] == ["author", "publisher"]


def test_锁定封面后不给封面建议(lock_book, monkeypatch):
    cand = _cand("锁测", cover_url="https://example.invalid/c.jpg")
    db.set_lock(lock_book["id"], db.LOCK_COVER)
    it = _plan(lock_book, monkeypatch, cand)
    assert it["cover"] is None
    assert db.LOCK_COVER in it["locked"]


def test_没锁封面时给出封面建议(lock_book, monkeypatch):
    cand = _cand("锁测", cover_url="https://example.invalid/c.jpg")
    it = _plan(lock_book, monkeypatch, cand)
    assert it["cover"] and it["cover"]["url"] == "https://example.invalid/c.jpg"


# ---------------------------------------------------------------------------
# 抓取闸门二：apply 不落库（防「预览页是上锁之前渲染的」）
# ---------------------------------------------------------------------------

def _apply_one(book, monkeypatch, fields, cover=None):
    monkeypatch.setattr(metasources, "search_by_isbn", lambda *a, **k: None)
    return metafetch.apply([{"name": book["name"], "book_id": book["id"],
                             "fields": fields, "cover": cover}],
                           cfg={"metadata_fetch": {"enabled": True}})


def test_apply不写被锁字段并说明原因(lock_book, monkeypatch):
    db.set_lock(lock_book["id"], "author")
    res = _apply_one(lock_book, monkeypatch, {"author": "在线作者", "publisher": "在线出版社"})
    # 被锁的那个没写，同批未被锁的照写
    assert res["applied"] == [{"name": lock_book["name"], "fields": ["publisher"], "cover": False}]
    online = db.get_online(lock_book["id"])
    assert "author" not in online and online["publisher"]["value"] == "在线出版社"


def test_apply整批都被锁时如实报错(lock_book, monkeypatch):
    db.set_lock(lock_book["id"], "author")
    res = _apply_one(lock_book, monkeypatch, {"author": "在线作者"})
    assert res["applied"] == []
    assert res["failed"] and "author" in res["failed"][0]["error"]
    assert db.get_online(lock_book["id"]) == {}, "锁着就一个字都不许落库"


def test_apply不下载被锁封面(lock_book, monkeypatch):
    db.set_lock(lock_book["id"], db.LOCK_COVER)
    # 封面下载被顶掉：真的去下载会因外呼而失败，这里断言的是「压根没试」
    called = []
    monkeypatch.setattr(metafetch, "_download_cover",
                        lambda url: (called.append(url), (b"x" * 3000, "image/jpeg"))[1])
    res = _apply_one(lock_book, monkeypatch, {"publisher": "在线出版社"},
                     cover={"url": "https://example.invalid/c.jpg"})
    assert called == [], "封面被锁时不该发起下载"
    assert res["applied"][0]["cover"] is False
    assert db.get_cover(lock_book["id"]) is None


# ---------------------------------------------------------------------------
# 级联：改名搬迁 / 删书孤儿清理
# ---------------------------------------------------------------------------

def test_改名把字段锁搬过去(isolated):  # noqa: ARG001
    old, new = "lib$oldbook", "lib$newbook"
    db.set_lock(old, "author")
    db.set_lock(old, db.LOCK_COVER)

    moved = db.remap_book_id(old, new)

    assert moved["meta_locks"] == 2
    assert db.get_locks(new) == {"author", db.LOCK_COVER}
    assert db.get_locks(old) == set()


def test_改名时同字段冲突保留目标锁(isolated):  # noqa: ARG001
    """`PRIMARY KEY(book_id, field)`：整体 UPDATE 会撞主键、异常被 `except` 吞成
    「搬 0 行」⇒ 旧书的锁静默消失。逐行处理后，两边都锁同一字段时留着目标行即可。"""
    old, new = "lib$oldbook", "lib$newbook"
    db.set_lock(old, "author")
    db.set_lock(new, "author")

    moved = db.remap_book_id(old, new)

    assert moved["meta_locks"] == 0, "目标已有同字段的锁 ⇒ 不必搬"
    assert db.get_locks(new) == {"author"}
    assert db.get_locks(old) == set(), "旧行要被清掉，不能留下同一字段的两行"


def test_改名时目标已有别的锁也不跳过(isolated):  # noqa: ARG001
    """「标记型」表刻意豁免整表跳过探测（见 `REMAP_MERGE_TABLES`）：
    目标上别的锁不该让旧书的锁丢掉。"""
    old, new = "lib$oldbook", "lib$newbook"
    db.set_lock(old, "author")
    db.set_lock(new, "title")            # 目标已有**另一个**字段的锁

    moved = db.remap_book_id(old, new)

    assert moved["meta_locks"] == 1
    assert db.get_locks(new) == {"author", "title"}


def test_孤儿清理含字段锁(isolated):  # noqa: ARG001
    assert "meta_locks" in db.ORPHAN_TABLES
    assert "meta_locks" in db.REMAP_TABLES
    db.set_lock("gone", "author")
    assert db.book_id_refs()["meta_locks"] == ["gone"]
    assert db.delete_orphans({"meta_locks": ["gone"]})["meta_locks"] == 1
    assert db.get_locks("gone") == set()


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------

def _one_book(client, headers):
    r = client.get("/api/books", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_接口上锁与解锁(client, auth_headers, default_root):  # noqa: ARG001
    _real_epub(default_root, "接口锁.epub", title="接口锁")
    library.invalidate()
    b = _one_book(client, auth_headers)

    r = client.post(f"/api/books/{b['id']}/metadata/lock", headers=auth_headers,
                    json={"field": "author", "locked": True})
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is True and r.json()["locked_fields"] == ["author"]

    # 详情下发里也带上了 locked
    meta = client.get(f"/api/books/{b['id']}/metadata", headers=auth_headers).json()["meta"]
    assert meta["author"]["locked"] is True and meta["title"]["locked"] is False

    r = client.post(f"/api/books/{b['id']}/metadata/lock", headers=auth_headers,
                    json={"field": "author", "locked": False})
    assert r.json()["locked"] is False and r.json()["locked_fields"] == []


def test_接口支持锁封面(client, auth_headers, default_root):  # noqa: ARG001
    _real_epub(default_root, "封面锁.epub", title="封面锁")
    library.invalidate()
    b = _one_book(client, auth_headers)
    r = client.post(f"/api/books/{b['id']}/metadata/lock", headers=auth_headers,
                    json={"field": "cover"})
    assert r.status_code == 200 and r.json()["locked_fields"] == ["cover"]


def test_接口拒绝非法字段(client, auth_headers, default_root):  # noqa: ARG001
    _real_epub(default_root, "非法字段.epub", title="非法字段")
    library.invalidate()
    b = _one_book(client, auth_headers)
    for bad in ("", "pages", "cover_url", "nope"):
        r = client.post(f"/api/books/{b['id']}/metadata/lock", headers=auth_headers,
                        json={"field": bad})
        assert r.status_code == 400, f"{bad!r} 不该被接受"


def test_接口书不存在404(client, auth_headers):  # noqa: ARG001
    r = client.post("/api/books/不存在的书/metadata/lock", headers=auth_headers,
                    json={"field": "author"})
    assert r.status_code == 404


def test_接口未登录401(client):  # noqa: ARG001
    assert client.post("/api/books/x/metadata/lock", json={"field": "author"}).status_code == 401
