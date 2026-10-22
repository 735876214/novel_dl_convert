"""第 140 期（第六轮审计：数据库层）。

五条判据（每条都是「库里的坏值 / 半截状态在界面上看不见，但在下一层翻车」）：

1. **时间戳一律过 `numbers.epoch`** —— `1e400` 会被 `json` 解析成 `inf`，`float(inf)`
   不抛；写进 `reading_status` / `reading_attempts` 之后又被并进 `GET /api/books`
   的响应 ⇒ 书架首页此后**恒 500**（JSON 序列化非有限值），无自愈。批量端点与
   「再来一遍」两条路曾绕过 `_bounded`。
2. **`remap_book_id` 不许逐表吞异常** —— PG 上一条失败会把**已成功的表一起回滚**，
   而返回值照样报搬运行数 ⇒「日志说搬了 N 行、实际一行没动」。搬不动就得抛。
3. **`upgrade_book_ids` 读表失败时不许写幂等标记** —— 否则那张表整批旧 id 的
   进度 / 批注「迁移完成」却一条没搬，且永不重试。
4. **`session_uid` 唯一索引独立成幂等段** —— 它此前嵌在「列不存在」分支里，
   列一旦补上就再也不会执行，而 `upsert_session` 的 `ON CONFLICT` 硬依赖它。
5. **`ratings` / `reading_status` 进 `ORPHAN_TABLES`**、**按库统计在 SQL 里过滤**。
"""
import json

import pytest

from novelforge.core import db, library

from conftest import TEST_PIN, TEST_USER  # noqa: F401 —— 与其它 hardening 用例同一取法


def _login(client) -> dict:
    r = client.post("/api/auth/login", json={"user": "admin", "pin": "test1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _post_raw(client, url: str, body: str, headers: dict):
    """**原文**发送（`json=` 会把 inf 变成 `Infinity` 字面量，测不出 1e400 那条路）。"""
    return client.post(url, content=body,
                       headers={**headers, "Content-Type": "application/json"})


def _put_book(make_library, tmp_path, name: str = "书A.epub") -> str:
    lib = make_library("novels", "小说库", "ebook", tmp_path / "lib")
    root = tmp_path / "lib"
    (root / name).write_bytes(b"EPUB")
    library.invalidate()
    books = library.books("novels")
    assert books, f"书没扫到：{lib}"
    return books[0]["id"]


# ---------------- ① 非有限时间戳进不了库 ----------------

def test_批量设状态带inf不会让书架恒500(client, isolated, make_library, tmp_path):  # noqa: ARG001
    headers = _login(client)
    bid = _put_book(make_library, tmp_path)
    body = json.dumps({"action": "set_status", "ids": [bid],
                       "params": {"status": "reading", "started_at": 1e400}})
    # json.dumps(inf) 会给出 Infinity；要的是 1e400 这个**字面量**
    body = body.replace("Infinity", "1e400")

    r = _post_raw(client, "/api/books/batch", body, headers)
    # 整批拒掉是对的：坏的是**参数**（不是某一本书），而「夹住 inf」没有意义
    assert r.status_code == 400, r.text
    assert "有限" in r.text

    st = db.get_status(bid) or {}
    assert float(st.get("started_at") or 0) != float("inf"), "inf 落库了"
    # 真正要命的那一步：书架首页还能打开（回归前这里恒 500）
    assert client.get("/api/books", headers=headers).status_code == 200


def test_再来一遍带inf被拒(client, isolated, make_library, tmp_path):  # noqa: ARG001
    headers = _login(client)
    bid = _put_book(make_library, tmp_path, "书B.epub")
    r = _post_raw(client, f"/api/books/{bid}/reading-attempts",
                  '{"started_at": 1e400}', headers)
    assert r.status_code == 400, r.text
    items = client.get(f"/api/books/{bid}/reading-attempts", headers=headers).json()["items"]
    assert all(float(a.get("started_at") or 0) != float("inf") for a in items)


# ---------------- ② 搬迁失败必须抛，且不留半截 ----------------

def test_搬迁失败要抛而不是静默记0(isolated, monkeypatch):  # noqa: ARG001
    db.set_progress("旧.epub", 0, 42.0)
    monkeypatch.setattr(db, "REMAP_TABLES", db.REMAP_TABLES + ("没有这张表",))
    with pytest.raises(RuntimeError):
        db.remap_book_id("旧.epub", "新.epub")
    # 回滚：进度还在旧 id 上，没被「搬走一半」
    assert (db.get_progress("旧.epub") or {}).get("percent") == 42.0
    assert db.get_progress("新.epub") is None


# ---------------- ③ 读表失败不写幂等标记 ----------------

def test_升级bookid读表失败时不写幂等标记(isolated, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(db, "REMAP_TABLES", db.REMAP_TABLES + ("没有这张表",))
    res = db.upgrade_book_ids()
    assert res.get("failed_tables") == ["没有这张表"], res
    assert db.state_get("bookid_v2") != "1", "标记写了 ⇒ 这张表整批永远不迁移"


# ---------------- ④ 唯一索引幂等创建 ----------------

def test_会话唯一索引一定建出来(isolated):  # noqa: ARG001
    idx = {r["name"] for r in db._connect().execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='reading_sessions'").fetchall()}
    assert "idx_session_uid" in idx, f"upsert_session 的 ON CONFLICT 会持续失败：{idx}"


# ---------------- ⑤ 孤儿清理看得见评分与阅读状态 ----------------

def test_书没了评分与阅读状态进孤儿清单(isolated, make_library, tmp_path):  # noqa: ARG001
    bid = _put_book(make_library, tmp_path, "书C.epub")
    db.set_rating(bid, 4)
    db.set_status(bid, "finished")
    (tmp_path / "lib" / "书C.epub").unlink()
    library.invalidate()

    refs = db.book_id_refs()
    assert bid in refs["ratings"], "评分没进孤儿清单 ⇒ 永久占库"
    assert bid in refs["reading_status"]


def test_按书过滤的阅读统计仍对(isolated):  # noqa: ARG001
    db.add_session("甲.epub", seconds=10)
    db.add_session("乙.epub", seconds=5)
    all_ = db.reading_totals()
    assert (all_["seconds"], all_["sessions"]) == (15.0, 2)
    one = db.reading_totals({"甲.epub"})
    assert (one["seconds"], one["sessions"]) == (10.0, 1)
    assert db.reading_totals(set()) == {"seconds": 0.0, "sessions": 0}
