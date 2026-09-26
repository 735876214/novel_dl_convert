"""SQLite → PostgreSQL 一次性数据搬迁（第 62 期）。

这一批用例**只有 PG 后端能跑**（SQLite 后端下没有「搬迁」这件事），所以除最后一例外
全部挂 ``pg_only``：离线全量（默认 sqlite）里它们计为 skip，不会把 939 例的基线搅浑；
PG 侧跑法见 README「第 62 期」一节。

两条主线：

1. **搬得对**：老库的行原样落到 PG；列对不齐（老库少列）不整表炸；重跑不覆盖
   PG 上已有的行（``DO NOTHING``）；派生表（``book_index``）不搬。
2. **搬在建账号之前**：这是本期最容易写反、且**写反了完全不报错**的一处 ——
   ``db.init()`` 里如果 ``_seed_user`` 排在搬迁前面，空 PG 上会先冒出一个
   ``admin/changeme``，随后搬迁来的 ``users`` 行撞 UNIQUE 被丢掉，用户升级完
   发现**口令被静默重置**。所以这里既钉正例（老库的口令赢），也钉反例
   （关掉自动搬迁时确实是 seed 赢）—— 只钉正例的话，「两个都不生效」也会绿。
"""
import hashlib
import os
import pathlib
import sqlite3

import pytest

from novelforge import config
from novelforge.core import db, pg, pgmigrate, sqlcompat

#: 逐例挂而不是挂模块级 ``pytestmark``：文件里有一例（``test_migrate_refuses_on_sqlite``）
#: 验的恰恰是「SQLite 后端下会拒绝」，模块级标记会把它一起跳掉。
pg_only = pytest.mark.skipif(
    not sqlcompat.is_pg(),
    reason="数据搬迁只在 PG 后端下存在；SQLite 后端跑法见 README 第 62 期",
)
sqlite_only = pytest.mark.skipif(
    sqlcompat.is_pg(), reason="这一例验的是 SQLite 后端下的拒绝行为",
)

#: 老库里那个「真正的」口令散列。用一个**明显不是 sha256 正常产物**的串：
#: 断言挂掉时一眼能看出「这是老库那一行」，而不是去比对一坨十六进制。
OLD_PIN_HASH = "老库里的真散列"


def _old_db(path: pathlib.Path, rows) -> pathlib.Path:
    """造一个**老版本**的 SQLite 库：`progress` 表刻意少几列（没有 cfi）。

    少列不是偷懒，是**老库的真实形态**：这一仓的表是靠 ``db.init()`` 的补列迁移
    一步步长起来的，任何一份真实的老库都缺后加的列。搬迁必须靠「源表 ∩ 目标表」
    的列交集活下来，而不是假定两边一样。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE progress (book_id TEXT NOT NULL, locator INTEGER NOT NULL, "
                 "percent REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL, UNIQUE(book_id))")
    conn.executemany("INSERT INTO progress(book_id, locator, percent, updated_at) "
                     "VALUES(?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


def _pg(sql, params=()):
    return db._connect().execute(sql, params).fetchall()


def _source(isolated) -> pathlib.Path:  # noqa: ARG001 —— 要的是它切过的 DATA_DIR
    return pathlib.Path(config.DATA_DIR) / "novelforge.db"


@pg_only
def test_migrate_copies_rows(isolated, tmp_path):  # noqa: ARG001
    """老库的行原样进 PG；老库缺的列由 PG 的 DEFAULT 补上。"""
    src = _old_db(_source(isolated), [("lib$aaa", 7, 12.5, 1000.0), ("lib$bbb", 3, 90.0, 1001.0)])
    out = pgmigrate.migrate(src)
    assert out["rows"] == 2 and out["tables"]["progress"] == 2
    rows = {r["book_id"]: r for r in _pg("SELECT * FROM progress")}
    assert set(rows) == {"lib$aaa", "lib$bbb"}
    assert (rows["lib$aaa"]["locator"], rows["lib$aaa"]["percent"]) == (7, 12.5)
    # 老库没有 cfi 列 → 走 PG 的 DEFAULT ''（而不是 NULL：读点按字符串用）
    assert rows["lib$aaa"]["cfi"] == ""
    # id 是 IDENTITY，源里没给 → 必须由 PG 自动分配（两个都是真整数且不相等）
    assert isinstance(rows["lib$aaa"]["id"], int)
    assert rows["lib$aaa"]["id"] != rows["lib$bbb"]["id"]


@pg_only
def test_migrate_is_idempotent_and_does_not_clobber(isolated, tmp_path):  # noqa: ARG001
    """重跑不产生重复行，也不覆盖 PG 上**已经改过**的数据。

    后半条是这次搬迁的语义核心：用户在 PG 上读了几章之后，任何人再手滑跑一次
    搬迁，进度都不该被打回老库那一刻。
    """
    src = _old_db(_source(isolated), [("lib$aaa", 7, 12.5, 1000.0)])
    pgmigrate.migrate(src)
    assert pgmigrate.already_migrated() is True
    # 用户在 PG 侧动过：第 7 章 → 第 42 章
    db._connect().execute("UPDATE progress SET locator=42, percent=88.0 WHERE book_id='lib$aaa'")
    db._connect().commit()
    pgmigrate.migrate(src, force=True)                     # 无视标记重跑
    rows = _pg("SELECT locator, percent FROM progress WHERE book_id='lib$aaa'")
    assert len(rows) == 1, "重跑产生了重复行"
    assert (rows[0]["locator"], rows[0]["percent"]) == (42, 88.0), "重跑把 PG 上的新进度盖回去了"


@pg_only
def test_migrate_skips_book_index(isolated, tmp_path):  # noqa: ARG001
    """派生表不搬 —— ``book_index`` 是磁盘的投影，不是用户数据。

    它行里存着**绝对 root 路径**，换机器/换挂载点就不成立；而它对增量刷新是自愈的
    （下次扫描按 (size, mtime) 判一遍）。搬过去只会先灌一堆指向不存在路径的行。
    """
    src = _old_db(_source(isolated), [("lib$aaa", 1, 1.0, 1.0)])
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE book_index (library_id TEXT, rel TEXT, book_id TEXT, root TEXT, "
                 "size INTEGER, mtime REAL, format TEXT, title TEXT)")
    conn.execute("INSERT INTO book_index VALUES('default','三体.epub','default$x','/老机器/书库',1,2.0,'epub','三体')")
    conn.commit()
    conn.close()
    out = pgmigrate.migrate(src)
    assert "book_index" not in out["tables"]
    assert _pg("SELECT * FROM book_index") == []


@pg_only
def test_migrate_missing_source_is_not_an_error(isolated):  # noqa: ARG001
    """盘上没有老库 = 全新部署，是**正常路径**：不抛、不写标记。"""
    out = pgmigrate.migrate(_source(isolated))
    assert out["exists"] is False and out["rows"] == 0
    assert pgmigrate.already_migrated() is False


@pg_only
def test_auto_migrate_wins_over_seed_user(isolated, monkeypatch):  # noqa: ARG001
    """**顺序契约**：自动搬迁必须排在 ``_seed_user`` 前面（见模块文档）。"""
    src = _source(isolated)
    src.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                 "pin_hash TEXT NOT NULL, created_at REAL NOT NULL)")
    conn.execute("INSERT INTO users(username, pin_hash, created_at) VALUES('admin',?,1.0)",
                 (OLD_PIN_HASH,))
    conn.commit()
    conn.close()
    db.close()
    pg.drop_schema()                                       # 丢掉刚才那套库（等价于 SQLite 侧换个 DATA_DIR）
    monkeypatch.setattr(pgmigrate, "auto_enabled", lambda: True)
    db.init()         # 真实启动路径：建表 → 搬迁 → 建账号（顺序本身就是被测对象）
    row = _pg("SELECT pin_hash FROM users WHERE username='admin'")
    assert len(row) == 1
    assert row[0]["pin_hash"] == OLD_PIN_HASH, (
        "搬迁没跑在建账号之前：老库的账号被 _seed_user 抢先，口令被静默重置"
    )
    assert pgmigrate.already_migrated() is True


@pg_only
def test_seed_user_wins_when_auto_migrate_is_off(isolated):  # noqa: ARG001
    """上一例的**反例**（同一份源库）：自动搬迁关掉时，确实是 seed 赢、老库那行被丢。

    没有这一例，上一例在「搬迁其实压根没生效」的实现下同样是绿的 —— 两个断言
    各自满足不了对方要钉的东西。
    """
    src = _source(isolated)
    src.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                 "pin_hash TEXT NOT NULL, created_at REAL NOT NULL)")
    conn.execute("INSERT INTO users(username, pin_hash, created_at) VALUES('admin',?,1.0)",
                 (OLD_PIN_HASH,))
    conn.commit()
    conn.close()
    db.close()
    pg.drop_schema()
    db.init()                                # auto_enabled 在 PG_RESET=1 下本来就是 False
    row = _pg("SELECT pin_hash FROM users WHERE username='admin'")
    pin = os.getenv("AUTH_PIN", "changeme")
    expect = hashlib.sha256(f"admin:{pin}".encode("utf-8")).hexdigest()
    assert len(row) == 1 and row[0]["pin_hash"] == expect
    assert row[0]["pin_hash"] != OLD_PIN_HASH
    assert pgmigrate.already_migrated() is False, "自动搬迁被关掉了，标记不该被写"


@sqlite_only
def test_migrate_refuses_on_sqlite(isolated):  # noqa: ARG001
    """SQLite 后端下调搬迁必须**明确报错**，不能静默变成一次空操作。

    「静默空操作」是最坏的形态：运维看到命令成功退出，以为数据过去了。
    """
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        pgmigrate.migrate(_source(isolated))
