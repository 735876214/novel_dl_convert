"""第 27 期：批注域补齐 —— 软删除 / 垃圾桶 / 来源列 / Hub 统计。

钉住三件最容易静默回归的事：

1. **删除是软删除**：行留在表内、可恢复；真删是另一条独立出口（`purge`），
   且 `purge` 只肯删垃圾桶里的条目。
2. **垃圾桶不得污染统计**：`db.annotation_counts` 有 3 处下游（统计页 /
   书目列表的 `annotation_count` / CSV 导出的「批注数」列），改一处漏两处不报错。
3. **软删除列不得破坏两条级联逻辑**：book_id 改名搬迁（`remap_book_id`）与
   孤儿清理（`book_id_refs` + 孤儿端点）。
"""
import csv
import io
import pathlib
import time

from novelforge import config
from novelforge.core import db, library


def _scan_one(root, name: str = "三体.epub") -> str:
    """在默认书库放一本书并扫描，返回它的 book_id。"""
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"EPUB")
    library.invalidate()
    books = [b for b in library.books() if b["name"].endswith(name)]
    assert books, f"扫描没找到 {name}"
    return books[0]["id"]


def _add(client, headers, bid: str, quote: str = "测试摘录", **kw) -> int:
    body = {"quote": quote, "chapter": 1, "color": "yellow", **kw}
    r = client.post(f"/api/books/{bid}/annotations", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _active(client, headers, bid: str) -> list:
    r = client.get(f"/api/books/{bid}/annotations", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _row(aid: int):
    """直查表里那一行（绕过接口的过滤），用于断言「行其实还在」。"""
    return db._connect().execute(
        "SELECT id, deleted_at FROM annotations WHERE id=?", (aid,)
    ).fetchone()


# ---------------------------------------------------------------------------
# 1. 软删除 / 恢复 / 彻底删除
# ---------------------------------------------------------------------------

def test_delete_is_soft_so_row_survives(client, auth_headers, default_root):
    """删除 = 移入垃圾桶：接口看不见了，但行仍在表内且 deleted_at > 0。"""
    bid = _scan_one(default_root)
    aid = _add(client, auth_headers, bid)

    r = client.delete(f"/api/books/{bid}/annotations/{aid}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["trashed"] is True

    assert _active(client, auth_headers, bid) == [], "垃圾桶条目不该出现在列表里"
    row = _row(aid)
    assert row is not None, "软删除绝不能真删行 —— 否则「恢复」无从谈起"
    assert row["deleted_at"] > 0


def test_restore_puts_it_back(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    aid = _add(client, auth_headers, bid)
    client.delete(f"/api/books/{bid}/annotations/{aid}", headers=auth_headers)

    r = client.post(f"/api/books/{bid}/annotations/{aid}/restore", headers=auth_headers)
    assert r.status_code == 200
    assert [a["id"] for a in _active(client, auth_headers, bid)] == [aid]
    assert _row(aid)["deleted_at"] == 0


def test_restore_rejects_unknown_or_active_entry(client, auth_headers, default_root):
    """恢复只对「垃圾桶里」的条目成立；活跃条目再恢复是矛盾的，要报错而不是假装成功。"""
    bid = _scan_one(default_root)
    aid = _add(client, auth_headers, bid)

    r = client.post(f"/api/books/{bid}/annotations/{aid}/restore", headers=auth_headers)
    assert r.status_code == 404


def test_purge_requires_trash_first_then_hard_deletes(client, auth_headers, default_root):
    """彻底删除是独立出口：活跃条目必须先删除（移入垃圾桶）才能 purge。"""
    bid = _scan_one(default_root)
    aid = _add(client, auth_headers, bid)

    # 活跃状态下不许直接彻底删 —— 防误点一次就永久丢失
    r = client.delete(f"/api/books/{bid}/annotations/{aid}/purge", headers=auth_headers)
    assert r.status_code == 400
    assert _row(aid) is not None

    client.delete(f"/api/books/{bid}/annotations/{aid}", headers=auth_headers)
    r = client.delete(f"/api/books/{bid}/annotations/{aid}/purge", headers=auth_headers)
    assert r.status_code == 200
    assert _row(aid) is None, "purge 必须是真删"


# ---------------------------------------------------------------------------
# 2. 垃圾桶不得污染统计（3 处下游逐个钉）
# ---------------------------------------------------------------------------

def _csv_annotation_counts(client, headers) -> dict:
    """CSV 导出的「批注数」列，按文件名索引。"""
    r = client.get("/api/books/export", headers=headers)
    assert r.status_code == 200, r.text
    rows = csv.DictReader(io.StringIO(r.text.lstrip("﻿")))
    return {row["文件名"]: int(row["批注数"]) for row in rows}


def test_trashed_does_not_pollute_the_three_count_consumers(client, auth_headers, default_root):
    """一条批注进垃圾桶，三处统计都必须纹丝不动。

    `annotation_counts` 是裸 `GROUP BY`，加不加 `deleted_at=0` 决定了这三处的对错 ——
    只测统计页会漏掉书目列表与 CSV 导出。
    """
    bid = _scan_one(default_root)
    name = "三体.epub"
    keep = _add(client, auth_headers, bid, quote="留下的")
    drop = _add(client, auth_headers, bid, quote="丢掉的")

    def snapshot():
        stats_r = client.get("/api/stats", headers=auth_headers)
        assert stats_r.status_code == 200, stats_r.text
        books_r = client.get("/api/books", headers=auth_headers)
        assert books_r.status_code == 200, books_r.text
        book = next(b for b in books_r.json()["items"] if b["id"] == bid)
        return (
            stats_r.json()["reading"]["annotations"],   # 下游 1：统计页
            book["annotation_count"],                   # 下游 2：书目列表（喂「有批注」智能书架）
            _csv_annotation_counts(client, auth_headers)[name],  # 下游 3：CSV 导出
        )

    before = snapshot()
    assert before == (2, 2, 2), f"前置状态不对：{before}"

    client.delete(f"/api/books/{bid}/annotations/{drop}", headers=auth_headers)

    # 三处都应只剩「留下的」那一条。若 `annotation_counts` 漏了 deleted_at 过滤，
    # 这里会原样停在 (2, 2, 2) —— 而且三处一起错，不会报任何错。
    assert snapshot() == (1, 1, 1), "垃圾桶条目被算进了统计口径"
    # 总览列表同步少一条，证明删除本身生效（不是三处都没动）
    body = client.get("/api/annotations", headers=auth_headers).json()
    assert [a["id"] for a in body["items"]] == [keep]


# ---------------------------------------------------------------------------
# 3. 两条级联逻辑不被软删除列破坏
# ---------------------------------------------------------------------------

def test_remap_does_not_strand_active_annotations(isolated):
    """新 id 上只有垃圾桶批注时，旧 id 的**活跃**批注仍必须被搬过去。

    这是软删除引入的坑：`remap_book_id` 用「新 id 上是否已有行」决定要不要搬，
    若那个探测不看 `deleted_at`，新 id 上的垃圾桶条目会让整张表被跳过更新 ——
    旧 id 的活跃批注就此被搁浅成孤儿，且**不报错**。
    """
    old, new = "lib$oldbook", "lib$newbook"
    db.add_annotation(old, 1, "旧书的活跃批注", "yellow", "")
    victim = db.add_annotation(new, 1, "新书的垃圾桶批注", "yellow", "")
    db.delete_annotation(new, victim)

    db.remap_book_id(old, new)

    assert [a["quote"] for a in db.list_annotations(new)] == ["旧书的活跃批注"], \
        "旧 id 的活跃批注被搁浅了"
    assert db.list_annotations(old) == []
    # 搬迁搬**全部**行：垃圾桶条目也属于这本书，该跟着走
    assert len(db.trashed_annotations(new)) == 1


def test_orphan_clear_spares_live_book_trash_but_reaps_dead_book(client, auth_headers, default_root, test_lib_id):
    """孤儿判据是「book_id 已不在书库」，与垃圾桶状态无关。

    - 书**仍存在** → 它的垃圾桶批注不算孤儿，清理不许碰（否则用户一确认，
      垃圾桶里还等着恢复的东西就被永久删了）。
    - 书**已不存在** → 它的批注（含垃圾桶）就该可清理，否则永远清不掉的隐形垃圾。
    """
    live = _scan_one(default_root)
    live_aid = _add(client, auth_headers, live)
    client.delete(f"/api/books/{live}/annotations/{live_aid}", headers=auth_headers)

    # ⚠️ 必须挂在**真实存在**的库上：第 37 期起「库已不存在的行」不算孤儿
    #    （那些书只是界面上看不见，进度/批注还得留着），见 server._orphan_refs。
    dead = f"{test_lib_id}$deleted-book"
    db.add_annotation(dead, 1, "已删书的批注", "yellow", "")
    dead_trashed = db.add_annotation(dead, 1, "已删书的垃圾桶批注", "yellow", "")
    db.delete_annotation(dead, dead_trashed)

    orphans = client.get("/api/maintenance/orphans", headers=auth_headers)
    assert orphans.status_code == 200, orphans.text
    listed = orphans.json()["tables"]["annotations"]["sample"]
    assert dead in listed and live not in listed, f"孤儿清点不对：{listed}"

    r = client.post("/api/maintenance/orphans/clear", headers=auth_headers)
    assert r.status_code == 200, r.text

    assert _row(live_aid) is not None, "书还在，它的垃圾桶批注不该被孤儿清理带走"
    assert db.list_annotations(dead) == []
    assert db.trashed_annotations(dead) == []


def test_库被移除登记后它的书不算孤儿(client, auth_headers, default_root, test_lib_id):
    """第 37 期加的第二道判据：**库已不存在**的行不是孤儿，清理**不许**碰。

    场景是真实存在的：用户把一条库「移除登记」（或压根没建库），文件与进度都还在
    磁盘上，只是界面上看不见了。把「书目为空」当成「所有的书都没了」，一次
    「清理孤儿记录」就是一次不可恢复的进度/批注大清洗 —— 这条测试就是那道闸门。
    """
    bid = _scan_one(default_root)
    aid = _add(client, auth_headers, bid)
    assert bid.startswith(f"{test_lib_id}$"), "前置：书的 id 应当带库前缀"

    # 把库移除登记（库里还有书，走 force 只移除登记、不动文件）
    r = client.delete(f"/api/libraries/{test_lib_id}?force=1", headers=auth_headers)
    assert r.status_code == 200, r.text
    library.invalidate()

    listed = client.get("/api/maintenance/orphans", headers=auth_headers).json()
    assert listed["tables"]["annotations"]["books"] == 0, "库没了 ≠ 书没了，不该算孤儿"

    assert client.post("/api/maintenance/orphans/clear",
                       headers=auth_headers).status_code == 200
    assert _row(aid) is not None, "库只是移除登记，进度/批注必须原样留着"


# ---------------------------------------------------------------------------
# 4. Hub 总览：计数与周节拍
# ---------------------------------------------------------------------------

def test_overview_counts_and_weekly_cadence(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    keep = _add(client, auth_headers, bid, quote="留下的")
    drop = _add(client, auth_headers, bid, quote="丢掉的")
    client.delete(f"/api/books/{bid}/annotations/{drop}", headers=auth_headers)

    r = client.get("/api/annotations/overview", headers=auth_headers)
    assert r.status_code == 200, r.text
    ov = r.json()

    assert ov["active"] == 1 and ov["trashed"] == 1
    assert ov["weeks"] == 1, "两条都在本周，只算一周"
    assert ov["longest_quiet_weeks"] == 0, "本周刚批注过，没有「空档」"
    # 刻意不返回上游的 needsReview / devices：本项目无对应数据源，返回恒值就是假数据
    assert "needs_review" not in ov and "devices" not in ov
    assert keep  # 保留项确实活着


def test_overview_is_zeroed_when_there_are_no_annotations(client, auth_headers, default_root):
    _scan_one(default_root)
    ov = client.get("/api/annotations/overview", headers=auth_headers).json()
    assert ov == {"active": 0, "trashed": 0, "weeks": 0, "longest_quiet_weeks": 0}


def test_longest_quiet_weeks_measures_the_gap(isolated):
    """空档按周序号做差 —— 这正是不能用 `year*53+week` 的原因（跨年算错）。"""
    now = time.time()
    week = 7 * 86400
    # 三周前一条、本周一条 → 中间空了两周
    db.add_annotation("lib$b", 1, "三周前", "yellow", "")
    db._connect().execute(
        "UPDATE annotations SET created_at=? WHERE quote='三周前'", (now - 3 * week,)
    )
    db.add_annotation("lib$b", 1, "本周", "yellow", "")
    db._connect().commit()

    ov = db.annotation_overview()
    assert ov["weeks"] == 2
    assert ov["longest_quiet_weeks"] == 2, f"应空两周，实际 {ov}"


# ---------------------------------------------------------------------------
# 5. 向后兼容与存量库迁移
# ---------------------------------------------------------------------------

def test_all_annotations_default_hides_trashed(client, auth_headers, default_root):
    """无参调用是既有契约（图书详情批注 tab / 每日划线 widget 都不传参）——
    默认必须只给活跃批注，且 total 与 items 对得上。"""
    bid = _scan_one(default_root)
    keep = _add(client, auth_headers, bid, quote="活跃")
    drop = _add(client, auth_headers, bid, quote="垃圾桶")
    client.delete(f"/api/books/{bid}/annotations/{drop}", headers=auth_headers)

    body = client.get("/api/annotations", headers=auth_headers).json()
    assert [a["id"] for a in body["items"]] == [keep]
    assert body["total"] == len(body["items"]) == 1
    assert all(a["deleted_at"] == 0 for a in body["items"])

    # 显式要垃圾桶时两条都在，且能分辨
    body = client.get("/api/annotations?include_trashed=1", headers=auth_headers).json()
    assert {a["id"] for a in body["items"]} == {keep, drop}
    assert {a["id"]: a["deleted_at"] > 0 for a in body["items"]}[drop] is True


def test_legacy_db_gets_new_columns_without_losing_rows(client, auth_headers, default_root):
    """老库（annotations 表没有 origin / deleted_at）打开后自动补列、存量行照旧可读。

    仓库测试此前没有「手工造老形状表」的先例：用私有的 `db._connect()` 建表 +
    插行，再 `close()` + `init()` 触发 PRAGMA 守卫的 ALTER。
    """
    c = db._connect()
    c.execute("DROP TABLE annotations")
    c.execute(
        """CREATE TABLE annotations (
            id         INTEGER PRIMARY KEY,
            book_id    TEXT NOT NULL,
            chapter    INTEGER NOT NULL,
            quote      TEXT NOT NULL,
            color      TEXT NOT NULL DEFAULT 'yellow',
            note       TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )"""
    )
    c.execute(
        "INSERT INTO annotations(book_id, chapter, quote, color, note, created_at) "
        "VALUES('lib$legacy', 1, '老批注', 'green', '老笔记', ?)",
        (time.time(),),
    )
    c.commit()
    db.close()
    db.init()  # 触发轻量迁移

    cols = {r["name"] for r in db._connect().execute("PRAGMA table_info(annotations)")}
    assert {"origin", "deleted_at"} <= cols

    items = db.list_annotations("lib$legacy")
    assert len(items) == 1, "存量行必须照旧可见"
    assert items[0]["quote"] == "老批注" and items[0]["note"] == "老笔记"
    assert items[0]["origin"] == "web", "老批注确实都来自 Web 阅读器"
    assert db.list_annotations("lib$legacy")[0]["color"] == "green", "颜色值不该被迁移改动"
