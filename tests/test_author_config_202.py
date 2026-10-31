"""作者抓取配置接通（第 202 期）：enabled / fetch_bio / fetch_photo / sources 都有真实读点。"""
from __future__ import annotations

from types import SimpleNamespace

from novelforge.core import authors, db


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _cfg(monkeypatch, **author_cfg):
    base = {"enabled": True, "fetch_bio": True, "fetch_photo": True,
            "sources": ["openlibrary"]}
    base.update(author_cfg)
    monkeypatch.setattr(authors.config, "load_config",
                        lambda: {"metadata_fetch": {"authors": base}})


def test_关闭时批量抓取如实跳过(monkeypatch, isolated):
    _cfg(monkeypatch, enabled=False)
    r = authors.fetch_all()
    assert r["skipped"] == "作者抓取未开启" and r["ok"] == 0 and r["failed"] == 0


def test_传记与头像都关闭时拒绝(monkeypatch, isolated):
    _cfg(monkeypatch, fetch_bio=False, fetch_photo=False)
    r = authors.fetch_author("某人")
    assert r["ok"] is False and "都已关闭" in r["error"]

    _cfg(monkeypatch, sources=["googlebooks"])
    r = authors.fetch_author("某人")
    assert r["ok"] is False and "openlibrary" in r["error"]


def test_只抓传记不下载头像(monkeypatch, isolated):
    _cfg(monkeypatch, fetch_photo=False)

    def fake_get(url, **kw):
        if "search/authors" in url:
            return _Resp({"docs": [{"key": "/authors/OL1A", "name": "某人"}]})
        return _Resp({"bio": "一段传记", "photos": [123]})

    called = []
    monkeypatch.setattr(authors.httpx, "get", fake_get)
    monkeypatch.setattr(authors, "_download_photo",
                        lambda *a, **k: called.append(1) or "x.jpg")
    r = authors.fetch_author("某人")
    assert r["ok"] and r["bio"] == "一段传记" and r["has_photo"] is False
    assert called == []
    assert db.get_author("某人")["bio"] == "一段传记"


def test_只抓头像不写传记(monkeypatch, isolated):
    _cfg(monkeypatch, fetch_bio=False)

    def fake_get(url, **kw):
        if "search/authors" in url:
            return _Resp({"docs": [{"key": "/authors/OL1A", "name": "某人"}]})
        return _Resp({"bio": "不应写入", "photos": [123]})

    monkeypatch.setattr(authors.httpx, "get", fake_get)
    monkeypatch.setattr(authors, "_download_photo", lambda *a, **k: "photo.jpg")
    r = authors.fetch_author("某人")
    assert r["ok"] and r["bio"] == "" and r["has_photo"] is True
    row = db.get_author("某人")
    assert row["bio"] == "" and row["photo_path"] == "photo.jpg"
