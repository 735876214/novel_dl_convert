"""批量写失败时必须**整体回滚**（第 284 期）。

审计发现（实测）：SQLite 的隐式事务只在 `commit()` 时落盘 —— 批量写中途抛错时，
前面已写进事务的行**不会消失**；紧接着任何一次无关写操作的 `commit()` 会把它们
一起落盘：

```
set_progress_many([b1, b2])  → 第 2 行失败（模拟）
save_bookmark("zz")          → 无关写，commit
新连接 SELECT progress       → [('b1', 0.1)]    ← 接口回了 500，却「一半生效了」
```

修法：新增 `db._tx()`（成功 commit / 异常 rollback 再抛），所有「一条事务」的批量
写（进度 / 收藏夹成员 / 评分 / 阅读状态 / 元数据覆盖）都改走它。

⚠️ 为什么不是「每条写都包」：单条写与派生缓存（toc_map / 覆盖层重建）失败后会被
下一次重建覆盖，唯一需要的是**用户可见的批量动作**要么全成、要么全不成。
"""
import sqlite3

from novelforge.core import db


def _rows(sql: str, args=()) -> list:
    """**新连接**读库 —— 只有 `commit()` 过的数据它才看得见。"""
    con = sqlite3.connect(str(db.db_path()))
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _boom_after_first(monkeypatch):
    real = db._Conn.executemany

    def boom(self, sql, seq):
        real(self, sql, list(seq)[:1])      # 先真写第 1 行
        raise RuntimeError("模拟第 2 行写入失败")

    monkeypatch.setattr(db._Conn, "executemany", boom)
    return real


def test_进度批量写失败_半截数据不许被后续提交(isolated, monkeypatch):
    real = _boom_after_first(monkeypatch)
    try:
        db.set_progress_many([("b1", 0, 0.1), ("b2", 0, 0.2)])
        raise AssertionError("应当抛错")
    except RuntimeError:
        pass
    monkeypatch.setattr(db._Conn, "executemany", real)

    db.save_bookmark("zz", "anchor", percent=1.0)       # 一次无关的写 → commit
    assert _rows("SELECT book_id FROM progress") == [], "半截进度被后续 commit 落盘了"


def test_收藏夹批量加入失败_不留半个成员(isolated, monkeypatch):
    cid = db.create_collection("回滚夹")
    real = _boom_after_first(monkeypatch)
    try:
        db.add_books_to_collection(cid, ["b1", "b2"])
        raise AssertionError("应当抛错")
    except RuntimeError:
        pass
    monkeypatch.setattr(db._Conn, "executemany", real)

    db.save_bookmark("zz", "anchor", percent=1.0)
    assert _rows("SELECT book_id FROM collection_items") == []


def test_阅读状态批量写失败_不留半截状态(isolated, monkeypatch):
    calls = {"n": 0}
    real_sync = db._sync_attempt

    def sync(c, bid, status, st, fin, now):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("模拟第 2 本写轮次失败")
        return real_sync(c, bid, status, st, fin, now)

    monkeypatch.setattr(db, "_sync_attempt", sync)
    try:
        db.set_statuses(["b1", "b2"], "finished")
        raise AssertionError("应当抛错")
    except RuntimeError:
        pass

    db.save_bookmark("zz", "anchor", percent=1.0)
    assert _rows("SELECT book_id FROM reading_status") == []


def test_成功路径照旧一次提交(isolated):
    """回滚不能把正常路径也废掉：两行都该在新连接里看得见。"""
    assert db.set_progress_many([("b1", 0, 0.1), ("b2", 0, 0.2)]) == 2
    got = {r[0] for r in _rows("SELECT book_id FROM progress")}
    assert got == {"b1", "b2"}
