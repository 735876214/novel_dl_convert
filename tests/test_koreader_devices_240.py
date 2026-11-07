"""KOReader 重置凭据 + 设备列表（第 240 期）。

## 三条纪律（各有用例）

1. **重置只清凭据**：key 清空 + 自动关闭；**已经同步过来的进度一行不动**
   （换密码不该丢阅读进度）。
2. **重置必须显式确认**：没带 ``confirm=true`` ⇒ 400（这是不可逆的「断开全部设备」）。
3. **设备列表只读**：设备信息是「写进度时顺手记的一行」，**不另存一份真值源**。
"""
from __future__ import annotations

import hashlib

from novelforge.core import db, library


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _set_ko(client, auth_headers, *, enabled: bool, key: str = "") -> None:
    r = client.put("/api/config", headers=auth_headers,
                   json={"koreader": {"enabled": enabled, "username": "koreader", "key": key}})
    assert r.status_code == 200, r.text


def test_重置清凭据但不动进度(client, auth_headers, isolated):
    key = _md5("pass123")
    _set_ko(client, auth_headers, enabled=True, key=key)
    db.set_progress("book-1", "chapter/3", 42.0)

    r = client.post("/api/koreader/reset", headers=auth_headers, json={"confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    st = client.get("/api/koreader", headers=auth_headers).json()
    assert st["enabled"] is False
    assert st["has_key"] is False

    # ⚠️ 进度**不动** —— 换密码不该丢阅读进度
    prog = db.get_progress("book-1")
    assert prog and prog.get("percent") == 42.0


def test_重置必须显式确认(client, auth_headers, isolated):
    _set_ko(client, auth_headers, enabled=True, key=_md5("pass123"))
    r = client.post("/api/koreader/reset", headers=auth_headers, json={})
    assert r.status_code == 400
    st = client.get("/api/koreader", headers=auth_headers).json()
    assert st["enabled"] is True


def test_写进度会记下设备(client, auth_headers, make_library, tmp_path):
    key = _md5("pass123")
    _set_ko(client, auth_headers, enabled=True, key=key)
    # ⚠️ 第 271 期：索引行必须指向**真实存在的**书 —— `PUT /syncs/progress` 现在会校验
    # （此前不校验，给一本已删的书也能写进度，留下谁都清不掉的孤儿行）。
    # 本用例关心的是「设备被记下来」，所以造一本真书来承载它。
    root = tmp_path / "K"
    root.mkdir(parents=True, exist_ok=True)
    make_library("k", "K 库", "comic", root)
    (root / "书.cbz").write_bytes(bytes.fromhex("504b0304") + bytes(32))
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    bid = library.books()[0]["id"]
    db.replace_koreader_docs([
        {"book_id": bid, "doc_md5": "aaa", "alt_md5": "bbb", "size": 1, "mtime": 0},
    ])
    h = {"x-auth-user": "koreader", "x-auth-key": key}
    r = client.put("/koreader/syncs/progress", headers=h, json={
        "document": "aaa", "device_id": "dev-1", "username": "koreader",
        "progress": "chapter/3", "percentage": 42.0,
    })
    assert r.status_code == 200, r.text

    data = client.get("/api/koreader/devices", headers=auth_headers).json()
    assert len(data["items"]) == 1
    d = data["items"][0]
    assert d["device_id"] == "dev-1"
    assert d["sync_count"] == 1
    assert d["last_sync"] > 0


def test_设备列表只读_没有设备就是空(client, auth_headers, isolated):
    data = client.get("/api/koreader/devices", headers=auth_headers).json()
    assert data["items"] == []


def test_状态里有设备数(client, auth_headers, isolated):
    db.touch_koreader_device("dev-9", "koreader")
    st = client.get("/api/koreader", headers=auth_headers).json()
    assert st["device_count"] == 1
