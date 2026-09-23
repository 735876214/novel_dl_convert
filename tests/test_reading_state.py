"""第 34 期：重置阅读状态（「从头开始」）。

这项能力**只删服务端 DB 里的四处「读出来的痕迹」**（会话 / 进度 / 状态 / 阅读尝试
—— 最后一处是第 43 期加的），所以两件事最容易做错，各钉一批：

1. **删过头**：批注 / 书签 / 评分 / 收藏 / 元数据覆盖都是「关于这本书的内容」，
   不是「读过」的痕迹；顺手删掉就是把用户的笔记一起清了。已解锁的成就同样不回退。
2. **碰到文件**：源不可变是全局硬约定 —— 重置必须**只动 DB 行**，
   文件指纹（inode / 大小 / mtime / 哈希）分毫不动。
"""
import hashlib
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


def _fingerprint(path: pathlib.Path) -> tuple:
    """(inode, 大小, mtime_ns, sha256) —— 源不可变的判据。"""
    st = path.stat()
    return (st.st_ino, st.st_size, st.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest())


def _seed(client, headers, bid: str) -> None:
    """把四处记录都铺上：会话一条、进度一条、状态 reading（进 reading 会自动开一轮阅读尝试）。"""
    assert client.put(f"/api/books/{bid}/progress", json={"locator": 3, "percent": 42.0},
                      headers=headers).status_code == 200
    assert client.post(f"/api/books/{bid}/session", json={"seconds": 600},
                       headers=headers).status_code == 200
    assert client.put(f"/api/books/{bid}/status", json={"status": "reading"},
                      headers=headers).status_code == 200


def test_三处记录归零(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    _seed(client, auth_headers, bid)

    # 前置：确实都写进去了（否则「归零」断言可能是空库自带的假通过）
    assert client.get(f"/api/books/{bid}/progress", headers=auth_headers).json()["percent"] == 42.0
    assert client.get(f"/api/books/{bid}/status", headers=auth_headers).json()["status"] == "reading"

    r = client.post(f"/api/books/{bid}/reset-reading-state", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == {"sessions": 1, "progress": 1, "status": 1, "attempts": 1}

    assert client.get(f"/api/books/{bid}/progress", headers=auth_headers).json() == \
        {"locator": 0, "percent": 0}, "进度该回到零"
    assert client.get(f"/api/books/{bid}/status", headers=auth_headers).json()["status"] == "unread"
    # 阅读记录里这本书应当消失（会话没了就聚合不出来）
    log = client.get("/api/reading-log", headers=auth_headers).json()
    assert bid not in {row["book_id"] for row in log["by_book"]}, log["by_book"]


def test_幂等_空状态重置不报错(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    r = client.post(f"/api/books/{bid}/reset-reading-state", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == {"sessions": 0, "progress": 0, "status": 0, "attempts": 0}


def test_不碰文件指纹(client, auth_headers, default_root):
    """重置是**纯 DB 操作** —— 源文件指纹必须分毫不动（源不可变）。"""
    bid = _scan_one(default_root)
    path = pathlib.Path(default_root) / "三体.epub"
    before = _fingerprint(path)
    _seed(client, auth_headers, bid)

    assert client.post(f"/api/books/{bid}/reset-reading-state",
                       headers=auth_headers).status_code == 200

    assert _fingerprint(path) == before, "重置动了源文件（inode/大小/mtime/哈希）"


def test_只删读出来的痕迹_内容一律保留(client, auth_headers, default_root):
    """批注 / 书签 / 评分 / 收藏 / 元数据覆盖都不属于「读过的痕迹」，一个都不许掉。"""
    bid = _scan_one(default_root)
    _seed(client, auth_headers, bid)

    aid = client.post(f"/api/books/{bid}/annotations",
                      json={"quote": "摘录", "chapter": 1, "color": "yellow", "note": "笔记"},
                      headers=auth_headers).json()["id"]
    bmid = client.post(f"/api/books/{bid}/bookmarks",
                       json={"anchor": "1:0.5000", "chapter": 1, "percent": 20.0, "label": "书签"},
                       headers=auth_headers).json()["id"]
    assert client.put(f"/api/books/{bid}/rating", json={"stars": 5},
                      headers=auth_headers).status_code == 200
    cid = client.post("/api/collections", json={"name": "收藏夹"}, headers=auth_headers).json()["id"]
    assert client.post(f"/api/collections/{cid}/books", json={"book_id": bid},
                       headers=auth_headers).status_code == 200
    assert client.post(f"/api/books/{bid}/metadata", json={"fields": {"publisher": "本地出版社"}},
                       headers=auth_headers).status_code == 200

    assert client.post(f"/api/books/{bid}/reset-reading-state",
                       headers=auth_headers).status_code == 200

    assert [a["id"] for a in client.get(f"/api/books/{bid}/annotations",
                                        headers=auth_headers).json()["items"]] == [aid]
    assert [b["id"] for b in client.get(f"/api/books/{bid}/bookmarks",
                                        headers=auth_headers).json()["items"]] == [bmid]
    meta = client.get(f"/api/books/{bid}/metadata", headers=auth_headers).json()
    assert meta["fields"]["publisher"] == "本地出版社"
    assert db.collection_book_ids(cid) == [bid]
    ratings = db._connect().execute(
        "SELECT stars FROM ratings WHERE book_id=?", (bid,)
    ).fetchone()
    assert ratings is not None and ratings["stars"] == 5


def test_已解锁成就不回退(client, auth_headers, default_root):
    """成就的既定机制是「只解锁不回退」—— 重置阅读状态不该把它连坐。"""
    bid = _scan_one(default_root)
    _seed(client, auth_headers, bid)
    db.unlock_achievement("first_book")
    unlocked = set(db.unlocked_map())

    assert client.post(f"/api/books/{bid}/reset-reading-state",
                       headers=auth_headers).status_code == 200

    assert set(db.unlocked_map()) == unlocked == {"first_book"}


def test_未知书返回404(client, auth_headers, default_root):
    _scan_one(default_root)
    r = client.post("/api/books/不存在的书/reset-reading-state", headers=auth_headers)
    assert r.status_code == 404


def test_重置写审计日志(client, auth_headers, default_root):
    bid = _scan_one(default_root)
    _seed(client, auth_headers, bid)
    client.post(f"/api/books/{bid}/reset-reading-state", headers=auth_headers)

    logs = client.get("/api/logs", headers=auth_headers).json()
    hits = [x for x in logs["items"] if x.get("action") == "重置"]
    assert hits, f"重置没留审计痕迹：{logs['items'][:3]}"
    entry = hits[0]
    assert entry["file"] == "三体.epub", f"审计日志该记文件名：{entry}"
    assert entry["status"] == "成功"
    assert "仅服务端记录" in entry["detail"]
