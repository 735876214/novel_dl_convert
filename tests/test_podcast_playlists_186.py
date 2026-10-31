"""播客智能播放列表（第 186 期）。

规则存服务端、求值在前端（`lib/episodeScope.ts`）；后端只做形状校验与存储。
kind=queue 存队列快照（从播放队列保存），不是规则。
"""
from __future__ import annotations

from novelforge.core import podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>测试播客</title>
  <item><title>A</title><guid>g1</guid><enclosure url="https://cdn/a.mp3"/></item>
  <item><title>B</title><guid>g2</guid><enclosure url="https://cdn/b.mp3"/></item>
</channel></rss>
"""


def _pod(client, auth_headers, monkeypatch, url="https://example.com/feed.xml"):
    monkeypatch.setattr(podcasts, "_fetch", lambda u: RSS)
    return client.post("/api/podcasts", headers=auth_headers,
                       json={"feed_url": url}).json()["podcast"]


def test_规则播放列表的校验与增删改(client, auth_headers):
    url = "/api/podcast-playlists"
    bad = [
        {"name": " ", "rules": [{"field": "status", "op": "equals", "value": "unplayed"}]},
        {"name": "x", "kind": "nope", "rules": []},
        {"name": "x", "rules": []},
        {"name": "x", "rules": [{"field": "nope", "op": "equals", "value": "1"}]},
        {"name": "x", "rules": [{"field": "status", "op": "at_least", "value": "1"}]},
        {"name": "x", "rules": [{"field": "status", "op": "equals", "value": "paused"}]},
        {"name": "x", "rules": [{"field": "duration", "op": "at_most", "value": "abc"}]},
        {"name": "x", "rules": [{"field": "downloaded", "op": "equals", "value": "maybe"}]},
    ]
    for body in bad:
        assert client.post(url, headers=auth_headers, json=body).status_code == 400, body

    body = {
        "name": "未播短集", "kind": "rules", "match": "all",
        "rules": [
            {"field": "status", "op": "equals", "value": "unplayed"},
            {"field": "duration", "op": "at_most", "value": "30"},
        ],
    }
    r = client.post(url, headers=auth_headers, json=body)
    assert r.status_code == 200
    pl = r.json()
    assert pl["kind"] == "rules" and len(pl["rules"]) == 2 and pl["items"] == []
    assert client.post(url, headers=auth_headers, json=body).status_code == 400  # 重名

    r = client.put(f"{url}/{pl['id']}", headers=auth_headers,
                   json={**body, "name": "未播长集", "match": "any"})
    assert r.status_code == 200 and r.json()["name"] == "未播长集" and r.json()["match"] == "any"
    assert client.put(f"{url}/{pl['id']}", headers=auth_headers,
                      json={"name": "x", "rules": []}).status_code == 400

    assert [x["name"] for x in client.get(url, headers=auth_headers).json()["items"]] == ["未播长集"]
    assert client.delete(f"{url}/{pl['id']}", headers=auth_headers).status_code == 200
    assert client.delete(f"{url}/{pl['id']}", headers=auth_headers).status_code == 404


def test_队列快照播放列表(client, auth_headers):
    url = "/api/podcast-playlists"
    assert client.post(url, headers=auth_headers,
                       json={"name": "空队列", "kind": "queue", "items": []}).status_code == 400
    body = {
        "name": "队列快照", "kind": "queue",
        "items": [{"episode_id": "e1", "title": "A", "podcast_id": "p1", "podcast_title": "测试播客"}],
    }
    r = client.post(url, headers=auth_headers, json=body)
    assert r.status_code == 200
    pl = r.json()
    assert pl["kind"] == "queue" and pl["items"][0]["episode_id"] == "e1" and pl["rules"] == []


def test_全部单集取源与软删过滤(client, auth_headers, monkeypatch):
    p = _pod(client, auth_headers, monkeypatch)
    r = client.get("/api/podcasts/episodes", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert {x["title"] for x in items} == {"A", "B"}
    assert all(x["podcast_title"] == "测试播客" for x in items)
    assert all("transcript_text" not in x for x in items)

    # 移除订阅：单集不再出现在取源里（JOIN podcasts.deleted_at=0）
    assert client.delete(f"/api/podcasts/{p['id']}", headers=auth_headers).status_code == 200
    assert client.get("/api/podcasts/episodes", headers=auth_headers).json()["items"] == []
