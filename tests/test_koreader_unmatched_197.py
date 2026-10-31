"""KOReader 未匹配文档（第 197 期）：书没了，索引还在时要看得见、可清掉。"""
from __future__ import annotations

from novelforge.core import db


def test_未匹配文档计数与标记(client, auth_headers, isolated):
    db.replace_koreader_docs([
        {"book_id": "gone-book", "doc_md5": "aaa", "alt_md5": "bbb", "size": 1, "mtime": 0},
    ])
    st = client.get("/api/koreader", headers=auth_headers).json()
    assert st["doc_count"] == 1 and st["unmatched_docs"] == 1

    data = client.get("/api/koreader/docs", headers=auth_headers).json()
    assert data["unmatched"] == 1
    assert data["items"][0]["matched"] is False
    assert data["items"][0]["book_id"] == "gone-book"

    # 重建索引（扫描）会清掉陈旧行
    client.post("/api/koreader/scan", headers=auth_headers)
    st = client.get("/api/koreader", headers=auth_headers).json()
    assert st["doc_count"] == 0 and st["unmatched_docs"] == 0
