"""播客单集书签（第 177 期）。

离线（RSS 打桩）：同集同秒幂等（更新标题/备注）、软删除后再添加是复活（同 id）、
坏入参与不存在的单集/书签有明确状态码。
"""
from __future__ import annotations

from novelforge.core import podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>测试播客</title>
  <item><title>第 1 集</title><guid>g1</guid>
    <enclosure url="https://cdn/1.mp3" type="audio/mpeg"/></item>
</channel></rss>
"""


def _episode(client, auth_headers, monkeypatch) -> str:
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    pid = client.post("/api/podcasts", headers=auth_headers,
                      json={"feed_url": "https://example.com/feed.xml"}).json()["podcast"]["id"]
    return client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"][0]["id"]


def test_书签幂等_软删复活(client, auth_headers, monkeypatch):
    eid = _episode(client, auth_headers, monkeypatch)
    r = client.post(f"/api/podcasts/episodes/{eid}/bookmarks", headers=auth_headers,
                    json={"position_sec": 30.7, "title": "开场"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["position_sec"] == 30 and b["title"] == "开场"

    # 同集同秒：更新而不是新增
    r2 = client.post(f"/api/podcasts/episodes/{eid}/bookmarks", headers=auth_headers,
                     json={"position_sec": 30, "title": "开场（改）", "note": "备注"})
    assert r2.json()["id"] == b["id"]
    items = client.get(f"/api/podcasts/episodes/{eid}/bookmarks", headers=auth_headers).json()
    assert items["total"] == 1 and items["items"][0]["title"] == "开场（改）"

    # 删除 = 软删除；同位置再加 = 复活同一行
    assert client.delete(f"/api/podcasts/episode-bookmarks/{b['id']}",
                         headers=auth_headers).status_code == 200
    assert client.get(f"/api/podcasts/episodes/{eid}/bookmarks",
                      headers=auth_headers).json()["items"] == []
    r3 = client.post(f"/api/podcasts/episodes/{eid}/bookmarks", headers=auth_headers,
                     json={"position_sec": 30, "title": "复活"})
    assert r3.json()["id"] == b["id"]

    # 另一位置是新条目，按位置升序返回
    client.post(f"/api/podcasts/episodes/{eid}/bookmarks", headers=auth_headers,
                json={"position_sec": 5, "title": "开头"})
    positions = [x["position_sec"] for x in
                 client.get(f"/api/podcasts/episodes/{eid}/bookmarks", headers=auth_headers).json()["items"]]
    assert positions == [5, 30]


def test_坏入参(client, auth_headers, monkeypatch):
    eid = _episode(client, auth_headers, monkeypatch)
    assert client.post(f"/api/podcasts/episodes/{eid}/bookmarks", headers=auth_headers,
                       json={"position_sec": -1}).status_code == 400
    assert client.post(f"/api/podcasts/episodes/{eid}/bookmarks", headers=auth_headers,
                       json={"position_sec": "x"}).status_code == 400
    assert client.get("/api/podcasts/episodes/不存在/bookmarks", headers=auth_headers).status_code == 404
    assert client.post("/api/podcasts/episodes/不存在/bookmarks", headers=auth_headers,
                       json={"position_sec": 1}).status_code == 404
    assert client.delete("/api/podcasts/episode-bookmarks/不存在", headers=auth_headers).status_code == 404
