"""Hardcover **阅读进度**同步（第 225 期）。

⚠️ 本期最要紧的两条纪律：

1. **只在低频点推**（换章 / 手动），**绝不**挂在每一次翻页上 —— 进度是翻页级高频写，
   逐次外呼纯属浪费。判据在 ``sync._should_push_progress``。
2. **0 与「没读过」是两件事**：0 意味着「翻到了第一页」，没有进度行意味着「没读过」。
   推给外部时前者要推 0、后者**不推**。
"""
from __future__ import annotations

import json

from novelforge.core import db, library, sync


def _seed_book(tmp_path, make_library, make_book, name: str = "进度书.epub",
                title: str = "进度书", author: str = "作者甲") -> str:
    make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    make_book(tmp_path / "lib", name)
    library.invalidate()
    bid = library.books("lib$1")[0]["id"]
    db.set_override(bid, "title", title)
    db.set_override(bid, "author", author)
    library.invalidate()
    return bid


# ---------------------------------------------------------------------------
# 进度口径
# ---------------------------------------------------------------------------

def test_进度_没有进度行是_None_不是_0(client, auth_headers, isolated, tmp_path,
                                  make_library, make_book):
    """「没读过」与「翻到第一页」是**两件事** —— 前者不推、后者推 0。"""
    bid = _seed_book(tmp_path, make_library, make_book)
    assert sync.progress_of(bid) is None

    db.set_progress(bid, 0, 0.0)
    assert sync.progress_of(bid) == 0.0


def test_进度_按百分比换算成_0到1(client, auth_headers, isolated, tmp_path,
                                  make_library, make_book):
    bid = _seed_book(tmp_path, make_library, make_book)
    db.set_progress(bid, 3, 42.0)
    assert sync.progress_of(bid) == 0.42


def test_进度_越界夹住(client, auth_headers, isolated, tmp_path,
                       make_library, make_book):
    bid = _seed_book(tmp_path, make_library, make_book)
    db.set_progress(bid, 1, 150.0)
    assert sync.progress_of(bid) == 1.0


# ---------------------------------------------------------------------------
# 触发时机（低频）
# ---------------------------------------------------------------------------

def test_换章才推_同章内翻页不推():
    """同章内的连续写入**不推**（翻页级高频）；换章才推。"""
    sync._PROGRESS_PUSHED.clear()
    assert sync._should_push_progress("b1", 5) is True
    assert sync._should_push_progress("b1", 5) is False      # 同章
    assert sync._should_push_progress("b1", 6) is True       # 换章


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------

def test_进度接口_没凭据如实说明(client, auth_headers, isolated, tmp_path,
                               make_library, make_book):
    bid = _seed_book(tmp_path, make_library, make_book)
    db.set_progress(bid, 1, 50.0)
    r = client.post("/api/integrations/hardcover/progress", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "凭据" in body["message"]


def test_进度接口_推给_Hardcover(client, auth_headers, isolated, tmp_path,
                                make_library, make_book, monkeypatch):
    """有凭据 + 有进度 ⇒ 真的外呼一次，且带上比例。"""
    bid = _seed_book(tmp_path, make_library, make_book)
    db.set_progress(bid, 2, 30.0)

    seen: list = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"insert_user_book": {"user_book": {"id": 1, "progress": 0.3}}}}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            seen.append(json)
            return _Resp()

    monkeypatch.setattr(sync, "_config", lambda: {
        "integrations": {"hardcover": {"token": "tok"}},
    })
    monkeypatch.setattr(sync, "_local_books", lambda: [
        {"id": bid, "title": "进度书", "author": "作者甲", "isbn": ""},
    ])
    # 匹配直接给 id（省掉一次 search 请求）
    monkeypatch.setattr(sync, "_hardcover_find_book_id", lambda c, t, b: (4321, ""))
    monkeypatch.setattr(sync.httpx, "Client", lambda **kw: _Client())

    r = client.post("/api/integrations/hardcover/progress", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["pushed"] == 1
    # 真的发了那条 mutation，且比例是 0.3
    assert seen, "没有外呼"
    payload = seen[0]
    assert "insert_user_book" in payload["query"]
    assert payload["variables"]["progress"] == 0.3
    assert payload["variables"]["book_id"] == 4321


def test_进度接口_没进度的书不推(client, auth_headers, isolated, tmp_path,
                               make_library, make_book, monkeypatch):
    """没读过的书**不推**（0 与「没读过」是两件事）。"""
    bid = _seed_book(tmp_path, make_library, make_book)

    calls: list = []

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            calls.append(a)
            raise AssertionError("不该外呼")

    monkeypatch.setattr(sync, "_config", lambda: {
        "integrations": {"hardcover": {"token": "tok"}},
    })
    monkeypatch.setattr(sync, "_local_books", lambda: [
        {"id": bid, "title": "进度书", "author": "作者甲"},
    ])
    monkeypatch.setattr(sync.httpx, "Client", lambda **kw: _Client())

    r = client.post("/api/integrations/hardcover/progress", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pushed"] == 0
    assert not calls, "没有进度的书被推了"
