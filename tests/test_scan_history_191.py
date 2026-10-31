"""每库扫描历史（第 191 期）。"""
from __future__ import annotations

import pathlib

from novelforge import config
from novelforge.core import epub_builder


def _setup(client, auth_headers, make_library):
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "scanhist"
    make_library("lib-hist", "扫描历史库", "ebook", root)
    epub_builder.build_epub({"title": "一", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body": "<p>正文</p>"}],
                            str(root / "一.epub"), nav=False)
    client.get("/api/books", headers=auth_headers)
    return root


def test_手动扫描落历史_最近在前(client, auth_headers, make_library):
    root = _setup(client, auth_headers, make_library)
    r1 = client.post("/api/libraries/lib-hist/scan", headers=auth_headers)
    assert r1.status_code == 200 and r1.json()["history_id"] > 0

    epub_builder.build_epub({"title": "二", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body": "<p>正文</p>"}],
                            str(root / "二.epub"), nav=False)
    r2 = client.post("/api/libraries/lib-hist/scan", headers=auth_headers)
    assert r2.json()["count"] >= 2

    data = client.get("/api/libraries/lib-hist/scan-history",
                      headers=auth_headers).json()
    items = data["items"]
    assert data["total"] == 2
    assert items[0]["id"] > items[1]["id"]          # 最近在前
    assert items[0]["status"] == "ok"
    assert items[0]["books"] >= 2
    assert items[0]["added"] >= 1
    assert "手动扫描" in items[0]["note"]
    assert items[0]["finished_at"] >= items[0]["started_at"] > 0

    assert len(client.get("/api/libraries/lib-hist/scan-history",
                          params={"limit": 1}, headers=auth_headers).json()["items"]) == 1
    assert client.get("/api/libraries/nope/scan-history",
                      headers=auth_headers).status_code == 404
