"""第 34 期：本地书签 —— 位置去重 / 墓碑复活 / 软删除 / 并发合并。

书签的软删除语义与批注同构（第 27 期那套），但另有三件**只属于书签**的事，
每件都容易在重构里被静默改坏，故逐条钉住：

1. **位置去重**：`UNIQUE(book_id, anchor)` —— 同一位置反复加书签恒为同一条，
   不然阅读器里点两次「加书签」就会长出两条一模一样的记录。
2. **tombstone 复活**：位置被删过（墓碑行还在），再加同位置要**复活那一行**
   而不是插新行 —— 否则每条被删过的书签都会漏成一条永久墓碑。
3. **并发合并**：客户端回传它看到的那一版时间戳，库里更新则**服务端胜**且不改库。
   这条最容易做成「谁最后写谁赢」的假合并（静默覆盖掉另一端刚改的备注）。
"""
import pathlib

from novelforge.core import db, library


def _scan_one(root, name: str = "三体.epub") -> str:
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"EPUB")
    library.invalidate()
    books = [b for b in library.books() if b["name"].endswith(name)]
    assert books, f"扫描没找到 {name}"
    return books[0]["id"]


def _add(client, headers, bid: str, anchor: str = "3:0.25", **kw) -> dict:
    body = {"anchor": anchor, "chapter": 3, "percent": 12.5, "label": "", **kw}
    r = client.post(f"/api/books/{bid}/bookmarks", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _active(client, headers, bid: str) -> list:
    r = client.get(f"/api/books/{bid}/bookmarks", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _trash(client, headers, bid: str) -> list:
    r = client.get(f"/api/books/{bid}/bookmarks?include_trashed=1", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["trashed"]


def _row(bmid: int):
    """直查表里那一行（绕过接口过滤），用于断言「行其实还在」以及改版本戳。"""
    return db._connect().execute(
        "SELECT id, label, deleted_at, created_at, updated_at FROM bookmarks WHERE id=?", (bmid,)
    ).fetchone()


def _bump(bmid: int, seconds: float) -> None:
    """把库里的版本戳推向未来（模拟「另一端刚改过」），比 sleep 稳。"""
    c = db._connect()
    c.execute("UPDATE bookmarks SET updated_at=updated_at+? WHERE id=?", (seconds, bmid))
    c.commit()


# ---------------------------------------------------------------------------
# 1. 位置去重
# ---------------------------------------------------------------------------

def test_同位置重复添加恒为同一条(client, auth_headers, default_root):
    bid = _scan_one(default_root)

    first = _add(client, auth_headers, bid, "5:0.5", label="第一次")
    assert first["created"] is True

    second = _add(client, auth_headers, bid, "5:0.5", label="第二次")
    assert second["id"] == first["id"], "同一位置必须落在同一行上，否则点两次会长出两条"
    assert second["created"] is False

    items = _active(client, auth_headers, bid)
    assert len(items) == 1
    assert items[0]["label"] == "第二次", "upsert：内容按本次传的来"


def test_不同位置各占一条(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    a = _add(client, auth_headers, bid, "1:0.1")
    b = _add(client, auth_headers, bid, "1:0.6")
    assert a["id"] != b["id"]
    assert [x["id"] for x in _active(client, auth_headers, bid)] == [a["id"], b["id"]], \
        "同章内按位置升序"


def test_空位置锚被拒(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    r = client.post(f"/api/books/{bid}/bookmarks", json={"anchor": "  "}, headers=auth_headers)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 2. tombstone 复活
# ---------------------------------------------------------------------------

def test_删除后再加同位置是复活那一行(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    first = _add(client, auth_headers, bid, "2:0.3", label="原备注")
    bmid = first["id"]
    created_at = _row(bmid)["created_at"]

    client.delete(f"/api/books/{bid}/bookmarks/{bmid}", headers=auth_headers)
    assert _active(client, auth_headers, bid) == []
    assert _row(bmid) is not None, "软删除绝不能真删行 —— 否则「复活」无从谈起"

    again = _add(client, auth_headers, bid, "2:0.3", label="复活后备注")
    assert again["id"] == bmid, "同位置再加应当复活墓碑行，而不是插一条新行"
    assert again["revived"] is True and again["created"] is False
    assert _row(bmid)["deleted_at"] == 0
    assert _row(bmid)["created_at"] == created_at, "复活要保住原始创建时间"
    assert [x["label"] for x in _active(client, auth_headers, bid)] == ["复活后备注"]
    # 墓碑没有漏成两行：表里这个位置永远只有一行
    n = db._connect().execute(
        "SELECT COUNT(*) AS n FROM bookmarks WHERE book_id=? AND anchor=?", (bid, "2:0.3")
    ).fetchone()["n"]
    assert n == 1


# ---------------------------------------------------------------------------
# 3. 软删除 / 恢复 / 彻底删除
# ---------------------------------------------------------------------------

def test_恢复只对垃圾桶成立(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    bmid = _add(client, auth_headers, bid)["id"]

    r = client.post(f"/api/books/{bid}/bookmarks/{bmid}/restore", headers=auth_headers)
    assert r.status_code == 404, "活跃条目「恢复」是矛盾的，要报错而不是假装成功"

    client.delete(f"/api/books/{bid}/bookmarks/{bmid}", headers=auth_headers)
    assert client.post(f"/api/books/{bid}/bookmarks/{bmid}/restore",
                       headers=auth_headers).status_code == 200
    assert [x["id"] for x in _active(client, auth_headers, bid)] == [bmid]


def test_purge_必须先入垃圾桶(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    bmid = _add(client, auth_headers, bid)["id"]

    r = client.delete(f"/api/books/{bid}/bookmarks/{bmid}/purge", headers=auth_headers)
    assert r.status_code == 400, "活跃条目不许直接彻底删（防误点一次就永久丢失）"
    assert _row(bmid) is not None

    client.delete(f"/api/books/{bid}/bookmarks/{bmid}", headers=auth_headers)
    assert client.delete(f"/api/books/{bid}/bookmarks/{bmid}/purge",
                         headers=auth_headers).status_code == 200
    assert _row(bmid) is None, "purge 必须是真删"


def test_垃圾桶视图与活跃视图互斥(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    keep = _add(client, auth_headers, bid, "1:0.2")["id"]
    drop = _add(client, auth_headers, bid, "1:0.8")["id"]
    client.delete(f"/api/books/{bid}/bookmarks/{drop}", headers=auth_headers)

    assert [x["id"] for x in _active(client, auth_headers, bid)] == [keep]
    trash = _trash(client, auth_headers, bid)
    assert [x["id"] for x in trash] == [drop]
    assert trash[0]["deleted_at"] > 0


def test_改备注只对活跃书签成立(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    bmid = _add(client, auth_headers, bid, "4:0.4")["id"]

    r = client.patch(f"/api/books/{bid}/bookmarks/{bmid}", json={"label": "改过的"},
                     headers=auth_headers)
    assert r.status_code == 200 and r.json()["applied"] is True
    assert _active(client, auth_headers, bid)[0]["label"] == "改过的"

    client.delete(f"/api/books/{bid}/bookmarks/{bmid}", headers=auth_headers)
    r = client.patch(f"/api/books/{bid}/bookmarks/{bmid}", json={"label": "再改"},
                     headers=auth_headers)
    assert r.status_code == 404, "垃圾桶里的书签不该还能改"


# ---------------------------------------------------------------------------
# 4. 并发合并（乐观并发：库里更新则服务端胜）
# ---------------------------------------------------------------------------

def test_服务端更新时服务端胜且不改库(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    first = _add(client, auth_headers, bid, "6:0.15", label="原备注")
    bmid, base = first["id"], first["server"]["updated_at"]

    # 另一端刚改过（库里版本变新），此时客户端带着**旧版本**回来
    db._connect().execute("UPDATE bookmarks SET label='别端改的' WHERE id=?", (bmid,))
    db._connect().commit()
    _bump(bmid, 10)

    r = client.post(f"/api/books/{bid}/bookmarks",
                    json={"anchor": "6:0.15", "chapter": 6, "percent": 20.0,
                          "label": "我改的", "updated_at": base},
                    headers=auth_headers)
    body = r.json()
    assert body["applied"] is False, "服务端版本更新时不该被客户端覆盖"
    assert body["server"]["label"] == "别端改的", "服务端现值要回给客户端供其合并"
    assert _row(bmid)["label"] == "别端改的", "库里必须原样未动"

    # 客户端合并后带着新版本再来 → 这次应用
    r2 = client.post(f"/api/books/{bid}/bookmarks",
                     json={"anchor": "6:0.15", "chapter": 6, "percent": 20.0, "label": "我改的",
                           "updated_at": body["server"]["updated_at"]},
                     headers=auth_headers)
    assert r2.json()["applied"] is True
    assert _active(client, auth_headers, bid)[0]["label"] == "我改的"


def test_不传版本戳时无条件写入(client, auth_headers, default_root):
    """不带 `updated_at` 的调用方（阅读器点一下加书签）保持简单：不做并发保护。"""
    bid = _scan_one(default_root)
    _add(client, auth_headers, bid, "7:0.1", label="旧")
    _bump(_active(client, auth_headers, bid)[0]["id"], 10)
    r = _add(client, auth_headers, bid, "7:0.1", label="新")
    assert r["applied"] is True
    assert _active(client, auth_headers, bid)[0]["label"] == "新"


def test_客户端快照之后被删的位置不会复活(client, auth_headers, default_root):
    """「并发」的另一面：客户端拿着一份快照来加书签，而那个位置在快照之后被删了。

    库里那条墓碑比客户端快照**更新** ⇒ 服务端胜、保持删除状态，
    并把 `server.deleted_at > 0` 回给客户端（它据此知道「这条已经被删了」）。
    """
    bid = _scan_one(default_root)
    first = _add(client, auth_headers, bid, "8:0.7")
    bmid, base = first["id"], first["server"]["updated_at"]
    client.delete(f"/api/books/{bid}/bookmarks/{bmid}", headers=auth_headers)

    r = client.post(f"/api/books/{bid}/bookmarks",
                    json={"anchor": "8:0.7", "chapter": 8, "percent": 40.0,
                          "updated_at": base},
                    headers=auth_headers)
    body = r.json()
    assert body["applied"] is False and body["revived"] is False
    assert body["server"]["deleted_at"] > 0
    assert _active(client, auth_headers, bid) == []


# ---------------------------------------------------------------------------
# 5. 改名搬迁 / 孤儿清理（与批注同一组级联逻辑）
# ---------------------------------------------------------------------------

def test_改名后活跃书签被搬走且垃圾桶同行(isolated):
    old, new = "lib$oldbook", "lib$newbook"
    db.save_bookmark(old, "1:0.1", label="旧书的活跃书签")
    victim = db.save_bookmark(new, "2:0.9", label="新书的垃圾桶书签")["id"]
    db.delete_bookmark(new, victim)

    db.remap_book_id(old, new)

    assert [b["label"] for b in db.list_bookmarks(new)] == ["旧书的活跃书签"], \
        "旧 id 的活跃书签被搁浅了（探测漏了 deleted_at 过滤）"
    assert db.list_bookmarks(old) == []
    assert len(db.trashed_bookmarks(new)) == 1, "垃圾桶条目也属于这本书，该跟着走"


def test_改名时同位置的墓碑不挡住搬迁(isolated):
    """唯一索引的真边界：新旧 id 在**同一位置**各有一行，整体 UPDATE 会撞唯一约束、
    被 `remap_book_id` 的 `except` 静默吞成「搬了 0 行」⇒ 旧书签凭空消失。
    """
    old, new = "lib$oldbook", "lib$newbook"
    keep = db.save_bookmark(old, "3:0.5", label="旧书的活跃书签")["id"]
    dead = db.save_bookmark(new, "3:0.5", label="新书的同位置墓碑")["id"]
    db.delete_bookmark(new, dead)

    moved = db.remap_book_id(old, new)

    assert moved.get("bookmarks") == 1, f"搬迁被唯一约束挡掉了：{moved}"
    assert [b["id"] for b in db.list_bookmarks(new)] == [keep]
    assert db.trashed_bookmarks(new) == [], "让位的墓碑不该留下（否则同一位置有两行）"
    assert db.list_bookmarks(old) == []


def test_孤儿清理不碰仍在书库的书(client, auth_headers, default_root, test_lib_id):
    live = _scan_one(default_root)
    live_bmid = _add(client, auth_headers, live)["id"]
    client.delete(f"/api/books/{live}/bookmarks/{live_bmid}", headers=auth_headers)

    # ⚠️ 必须挂在**真实存在**的库上：第 37 期起「库已不存在的行」不算孤儿
    #    （那些书只是界面上看不见，进度/批注还得留着），见 server._orphan_refs。
    dead = f"{test_lib_id}$deleted-book"
    db.save_bookmark(dead, "1:0.1", label="已删书的书签")
    dead_trashed = db.save_bookmark(dead, "2:0.1", label="已删书的垃圾桶书签")["id"]
    db.delete_bookmark(dead, dead_trashed)

    listed = client.get("/api/maintenance/orphans", headers=auth_headers).json()
    sample = listed["tables"]["bookmarks"]["sample"]
    assert dead in sample and live not in sample, f"孤儿清点不对：{sample}"

    assert client.post("/api/maintenance/orphans/clear", headers=auth_headers).status_code == 200
    assert _row(live_bmid) is not None, "书还在，它的垃圾桶书签不该被孤儿清理带走"
    assert db.list_bookmarks(dead) == [] and db.trashed_bookmarks(dead) == []


# ---------------------------------------------------------------------------
# 6. 存量库：老库里没有 bookmarks 表
# ---------------------------------------------------------------------------

def test_老库打开时自动建书签表(client, auth_headers, default_root):
    """老库（第 34 期之前建的）没有 bookmarks 表 —— `init()` 要能补上并可直接写入。"""
    c = db._connect()
    c.execute("DROP TABLE bookmarks")
    c.commit()
    db.close()
    db.init()  # 触发建表

    cols = {r["name"] for r in db._connect().execute("PRAGMA table_info(bookmarks)")}
    assert {"anchor", "chapter", "percent", "label", "updated_at", "deleted_at"} <= cols

    bid = _scan_one(default_root)
    assert _add(client, auth_headers, bid)["created"] is True
