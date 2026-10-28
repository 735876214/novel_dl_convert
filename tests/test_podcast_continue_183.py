"""播客版「继续收听」（第 183 期）。

只列「听过但没听完」的单集（position>0 且 played_at=0），按最近播放倒序；
已播 / 从未播放 / 所属订阅已移除的都不出现。
"""
from __future__ import annotations

import time

from novelforge.core import podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>测试播客</title>
  <item><title>A</title><guid>g1</guid><enclosure url="https://cdn/a.mp3"/></item>
  <item><title>B</title><guid>g2</guid><enclosure url="https://cdn/b.mp3"/></item>
  <item><title>C</title><guid>g3</guid><enclosure url="https://cdn/c.mp3"/></item>
</channel></rss>
"""


def _setup(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    pid = client.post("/api/podcasts", headers=auth_headers,
                      json={"feed_url": "https://example.com/feed.xml"}).json()["podcast"]["id"]
    eps = {e["title"]: e["id"] for e in
           client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]}
    return pid, eps


def test_继续收听排序与排除(client, auth_headers, monkeypatch):
    pid, eps = _setup(client, auth_headers, monkeypatch)
    # A 先听，B 后听；C 标已播
    client.post(f"/api/podcasts/episodes/{eps['A']}/progress", headers=auth_headers,
                json={"position_sec": 30, "duration_sec": 100})
    time.sleep(0.05)
    client.post(f"/api/podcasts/episodes/{eps['B']}/progress", headers=auth_headers,
                json={"position_sec": 50, "duration_sec": 100})
    client.post(f"/api/podcasts/episodes/{eps['C']}/played", headers=auth_headers,
                json={"played": True})

    items = client.get("/api/podcasts/continue", headers=auth_headers).json()["items"]
    assert [x["title"] for x in items] == ["B", "A"]
    assert all(x["podcast_title"] == "测试播客" for x in items)
    assert items[0]["position_sec"] == 50

    # 限流参数生效
    assert len(client.get("/api/podcasts/continue?limit=1", headers=auth_headers)
               .json()["items"]) == 1

    # 移除订阅后不再出现
    assert client.delete(f"/api/podcasts/{pid}", headers=auth_headers).status_code == 200
    assert client.get("/api/podcasts/continue", headers=auth_headers).json()["items"] == []
