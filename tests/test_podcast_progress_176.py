"""播客单集播放进度与已播状态（第 176 期）。

离线（RSS 打桩）：
- 位置**只增不减**（重听不会把「听到 80%」改回 20%）；
- 听满 95% 才记 `played_at`（第一次）；手动「标未播」同时清零位置；
- 非有限 / 负数位置 400，未知单集 404。
"""
from __future__ import annotations

from novelforge.core import podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>测试播客</title>
  <item><title>第 1 集</title><guid>g1</guid>
    <enclosure url="https://cdn/1.mp3" type="audio/mpeg"/></item>
</channel></rss>
"""


def _episode(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    pid = client.post("/api/podcasts", headers=auth_headers,
                      json={"feed_url": "https://example.com/feed.xml"}).json()["podcast"]["id"]
    eid = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"][0]["id"]
    return pid, eid


def _get(client, auth_headers, pid: str, eid: str) -> dict:
    eps = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
    return next(e for e in eps if e["id"] == eid)


def test_进度只增不减_听满记已播(client, auth_headers, monkeypatch):
    pid, eid = _episode(client, auth_headers, monkeypatch)
    r = client.post(f"/api/podcasts/episodes/{eid}/progress", headers=auth_headers,
                    json={"position_sec": 30, "duration_sec": 100})
    assert r.status_code == 200, r.text
    ep = _get(client, auth_headers, pid, eid)
    assert ep["position_sec"] == 30 and ep["played_at"] == 0

    # 拖回去重听：位置不减小
    client.post(f"/api/podcasts/episodes/{eid}/progress", headers=auth_headers,
                json={"position_sec": 10, "duration_sec": 100})
    assert _get(client, auth_headers, pid, eid)["position_sec"] == 30

    # 听满 95% ⇒ 记 played_at
    client.post(f"/api/podcasts/episodes/{eid}/progress", headers=auth_headers,
                json={"position_sec": 96, "duration_sec": 100})
    ep = _get(client, auth_headers, pid, eid)
    assert ep["played_at"] > 0 and ep["position_sec"] == 96


def test_手动标未播清零_与坏入参(client, auth_headers, monkeypatch):
    pid, eid = _episode(client, auth_headers, monkeypatch)
    client.post(f"/api/podcasts/episodes/{eid}/progress", headers=auth_headers,
                json={"position_sec": 50, "duration_sec": 100})
    r = client.post(f"/api/podcasts/episodes/{eid}/played", headers=auth_headers,
                    json={"played": True})
    assert r.status_code == 200 and r.json()["played_at"] > 0

    r2 = client.post(f"/api/podcasts/episodes/{eid}/played", headers=auth_headers,
                     json={"played": False})
    assert r2.status_code == 200
    ep = _get(client, auth_headers, pid, eid)
    assert ep["played_at"] == 0 and ep["position_sec"] == 0

    for bad in ({"position_sec": -1}, {"position_sec": "inf"}, {"position_sec": "x"}):
        assert client.post(f"/api/podcasts/episodes/{eid}/progress", headers=auth_headers,
                           json=bad).status_code == 400, bad
    assert client.post("/api/podcasts/episodes/不存在/progress", headers=auth_headers,
                       json={"position_sec": 1}).status_code == 404
    assert client.post("/api/podcasts/episodes/不存在/played", headers=auth_headers,
                       json={"played": True}).status_code == 404
