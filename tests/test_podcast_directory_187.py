"""播客目录搜索（第 187 期）。

默认开启、可关（`podcasts.directory_search`）；只在用户点搜索时出网，
失败降级到手动填 RSS 地址。只返回带 feedUrl 的结果（可直接订阅）。
"""
from __future__ import annotations

import json

from novelforge.core import podcasts

RESULTS = {
    "resultCount": 4,
    "results": [
        {"collectionName": "示例播客", "artistName": "主播",
         "feedUrl": "https://cdn.example.com/feed.xml",
         "artworkUrl600": "https://cdn.example.com/a.jpg",
         "genres": ["科技", "新闻"], "trackCount": 12, "collectionId": 123},
        # 重复 feed：去重
        {"collectionName": "示例播客副本", "artistName": "主播",
         "feedUrl": "https://cdn.example.com/feed.xml"},
        # 没有 feedUrl：不可订阅，丢弃
        {"collectionName": "没有 RSS", "artistName": "某人"},
    ],
}


def test_目录搜索解析_去重与丢弃无_feed(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: json.dumps(RESULTS, ensure_ascii=False))
    r = client.get("/api/podcasts/directory?q=示例", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0] == {
        "title": "示例播客", "author": "主播",
        "feed_url": "https://cdn.example.com/feed.xml",
        "artwork_url": "https://cdn.example.com/a.jpg",
        "categories": ["科技", "新闻"], "episode_count": 12, "itunes_id": "123",
    }


def test_目录搜索开关关闭_403(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts.config, "load_config",
                        lambda: {"podcasts": {"directory_search": False}})
    r = client.get("/api/podcasts/directory?q=示例", headers=auth_headers)
    assert r.status_code == 403
    assert "关闭" in r.json()["detail"]


def test_目录搜索入参与坏响应(client, auth_headers, monkeypatch):
    assert client.get("/api/podcasts/directory?q=", headers=auth_headers).status_code == 400

    monkeypatch.setattr(podcasts, "_fetch", lambda url: "not json")
    r = client.get("/api/podcasts/directory?q=示例", headers=auth_headers)
    assert r.status_code == 400
    assert "JSON" in r.json()["detail"]

    monkeypatch.setattr(podcasts, "_fetch", lambda url: '{"results": "nope"}')
    assert client.get("/api/podcasts/directory?q=示例", headers=auth_headers).status_code == 400
