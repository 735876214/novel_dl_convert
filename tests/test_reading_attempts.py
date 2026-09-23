"""第 43 期：阅读尝试（轮次）—— 与 `set_status` 的联动、reset 四清、remap/孤儿契约。

一轮 = 「开始读 → 读完」；读完后重新开始＝新一轮（`round` 递增）。
钉住四条最容易在重构里静默改坏的语义：
1. **自动维护**：`set_status` 进 reading 开轮、进 finished 收尾（没有进行中的就补一条单轮）；
2. **搁置不抹轮**：paused / abandoned 不是「读完」，进行中的那一轮原样留着；
3. **幂等**：`start_attempt` 已有进行中的轮次就原样返回，不重复开；
4. **不被遗忘**：`reset_reading_state` 一并清轮次；改名要跟着搬；书删了要能当孤儿清。
"""
from __future__ import annotations

from novelforge.core import db, library


def _bid(root, make_book, name: str = "三体.epub") -> str:
    make_book(root, name)
    library.invalidate()
    books = [b for b in library.books() if b["name"].endswith(name)]
    assert books, f"扫描没找到 {name}"
    return books[0]["id"]


# ---------------------------------------------------------------------------
# 1. 与状态联动
# ---------------------------------------------------------------------------

def test_标记在读开一轮_标记读完收尾(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)

    db.set_status(bid, "reading")
    items = db.list_attempts(bid)
    assert len(items) == 1
    assert items[0]["round"] == 1
    assert items[0]["finished_at"] == 0

    db.set_status(bid, "finished")
    items = db.list_attempts(bid)
    assert len(items) == 1
    assert items[0]["finished_at"] > 0
    assert items[0]["status"] == "finished"


def test_读完后再读是新的一轮(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)
    db.set_status(bid, "reading")
    db.set_status(bid, "finished")

    db.set_status(bid, "reading")          # 重读

    items = db.list_attempts(bid)
    assert [a["round"] for a in items] == [1, 2]
    assert items[1]["finished_at"] == 0


def test_直接标记读完也记一轮(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)

    db.set_status(bid, "finished")         # 没有「在读」前置

    items = db.list_attempts(bid)
    assert len(items) == 1
    assert items[0]["status"] == "finished"
    assert items[0]["finished_at"] > 0


def test_搁置不抹掉进行中的轮次(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)
    db.set_status(bid, "reading")

    db.set_status(bid, "paused")

    items = db.list_attempts(bid)
    assert len(items) == 1
    assert items[0]["finished_at"] == 0, "搁置不是「读完」，进行中的那一轮要留着"


# ---------------------------------------------------------------------------
# 2. 手动出口
# ---------------------------------------------------------------------------

def test_start_attempt幂等(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)
    first = db.start_attempt(bid)
    again = db.start_attempt(bid)
    assert first["id"] == again["id"]
    assert len(db.list_attempts(bid)) == 1


def test_finish_attempt没有进行中就返回None(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)
    assert db.finish_attempt(bid) is None
    assert db.list_attempts(bid) == [], "不凭空造行"


# ---------------------------------------------------------------------------
# 3. 不被遗忘：reset / remap / orphan
# ---------------------------------------------------------------------------

def test_重置阅读状态一并清轮次(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)
    db.set_status(bid, "finished")
    assert db.list_attempts(bid)

    removed = db.reset_reading_state(bid)

    assert removed["attempts"] == 1
    assert db.list_attempts(bid) == []


def test_改名把轮次搬过去(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)
    db.set_status(bid, "reading")

    moved = db.remap_book_id(bid, "default$newbook")

    assert moved.get("reading_attempts", 0) == 1
    assert db.list_attempts("default$newbook")
    assert db.list_attempts(bid) == [], "旧 id 不留残留"


def test_孤儿清理含阅读尝试(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)
    db.set_status(bid, "reading")

    assert "reading_attempts" in db.ORPHAN_TABLES
    assert "reading_attempts" in db.REMAP_TABLES
    removed = db.delete_orphans({"reading_attempts": [bid]})

    assert removed["reading_attempts"] == 1


# ---------------------------------------------------------------------------
# 4. 历史补录
# ---------------------------------------------------------------------------

def test_从历史补录只补没有轮次的书(isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)
    # 直接写 status 行（绕过 set_status 的自动开轮），模拟本期之前就存在的既有数据
    c = db._connect()
    c.execute(
        "INSERT INTO reading_status(book_id, status, started_at, finished_at, updated_at) "
        "VALUES(?,?,?,?,?)",
        (bid, "finished", 100.0, 200.0, 200.0),
    )
    c.commit()
    assert db.list_attempts(bid) == []

    res = db.backfill_attempts()

    assert res["created"] == 1
    items = db.list_attempts(bid)
    assert items[0]["round"] == 1
    assert items[0]["finished_at"] == 200.0
    assert db.backfill_attempts()["created"] == 0, "再跑一次不重复补"


# ---------------------------------------------------------------------------
# 5. 接口
# ---------------------------------------------------------------------------

def test_接口_重读与收尾(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)

    r = client.post(f"/api/books/{bid}/reading-attempts", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["attempt"]["round"] == 1

    r2 = client.post(f"/api/books/{bid}/reading-attempts/finish", headers=auth_headers)
    assert r2.status_code == 200, r2.text

    got = client.get(f"/api/books/{bid}/reading-attempts", headers=auth_headers)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["total"] == 1
    assert body["current"] is None


def test_接口_收尾没有进行中的轮次返回404(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book)
    r = client.post(f"/api/books/{bid}/reading-attempts/finish", headers=auth_headers)
    assert r.status_code == 404
