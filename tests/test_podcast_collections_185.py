"""播客合集（第 185 期）。

合集只装订阅（节目），不装单集 / 不装书；成员按**未软删**的订阅过滤 ——
移除订阅后计数归零，重订阅同一 feed 复活后合集位置恢复。
"""
from __future__ import annotations

from novelforge.core import podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>测试播客</title>
  <item><title>A</title><guid>g1</guid><enclosure url="https://cdn/a.mp3"/></item>
</channel></rss>
"""


def _pod(client, auth_headers, monkeypatch, url="https://example.com/feed.xml"):
    monkeypatch.setattr(podcasts, "_fetch", lambda u: RSS)
    r = client.post("/api/podcasts", headers=auth_headers, json={"feed_url": url})
    return r.json()["podcast"]


def test_合集增删改与名称校验(client, auth_headers):
    assert client.post("/api/podcast-collections", headers=auth_headers,
                       json={"name": "  "}).status_code == 400
    assert client.post("/api/podcast-collections", headers=auth_headers,
                       json={"name": "x" * 81}).status_code == 400

    r = client.post("/api/podcast-collections", headers=auth_headers, json={"name": " 科技 "})
    assert r.status_code == 200
    c = r.json()
    assert c["name"] == "科技" and c["count"] == 0 and c["podcast_ids"] == []
    cid = c["id"]

    # 重名拒绝（建 / 改名两条路都要拦）
    assert client.post("/api/podcast-collections", headers=auth_headers,
                       json={"name": "科技"}).status_code == 400
    other = client.post("/api/podcast-collections", headers=auth_headers,
                        json={"name": "新闻"}).json()
    assert client.put(f"/api/podcast-collections/{cid}", headers=auth_headers,
                      json={"name": "新闻"}).status_code == 400
    r = client.put(f"/api/podcast-collections/{cid}", headers=auth_headers, json={"name": "故事"})
    assert r.status_code == 200 and r.json()["name"] == "故事"

    items = client.get("/api/podcast-collections", headers=auth_headers).json()["items"]
    assert [x["name"] for x in items] == ["新闻", "故事"] or {x["name"] for x in items} == {"新闻", "故事"}

    assert client.delete(f"/api/podcast-collections/{cid}", headers=auth_headers).status_code == 200
    assert client.delete(f"/api/podcast-collections/{cid}", headers=auth_headers).status_code == 404
    assert client.get("/api/podcast-collections", headers=auth_headers).json()["total"] == 1
    assert other["name"] == "新闻"


def test_成员幂等_软删过滤与复活(client, auth_headers, monkeypatch):
    p1 = _pod(client, auth_headers, monkeypatch, "https://example.com/1.xml")
    p2 = _pod(client, auth_headers, monkeypatch, "https://example.com/2.xml")
    cid = client.post("/api/podcast-collections", headers=auth_headers,
                      json={"name": "科技"}).json()["id"]

    # 未知合集 / 未知订阅 404
    assert client.post("/api/podcast-collections/9999/items", headers=auth_headers,
                       json={"podcast_id": p1["id"]}).status_code == 404
    assert client.post(f"/api/podcast-collections/{cid}/items", headers=auth_headers,
                       json={"podcast_id": "nope"}).status_code == 404

    # 重复加入幂等
    for _ in range(2):
        r = client.post(f"/api/podcast-collections/{cid}/items", headers=auth_headers,
                        json={"podcast_id": p1["id"]})
        assert r.status_code == 200
    client.post(f"/api/podcast-collections/{cid}/items", headers=auth_headers,
                json={"podcast_id": p2["id"]})
    c = client.get("/api/podcast-collections", headers=auth_headers).json()["items"][0]
    assert c["count"] == 2 and set(c["podcast_ids"]) == {p1["id"], p2["id"]}

    # 移除订阅：成员行保留但不再出现在列表 / 计数里
    assert client.delete(f"/api/podcasts/{p1['id']}", headers=auth_headers).status_code == 200
    c = client.get("/api/podcast-collections", headers=auth_headers).json()["items"][0]
    assert c["count"] == 1 and c["podcast_ids"] == [p2["id"]]

    # 重订阅同一 feed：复用原行复活，合集位置恢复
    _pod(client, auth_headers, monkeypatch, "https://example.com/1.xml")
    c = client.get("/api/podcast-collections", headers=auth_headers).json()["items"][0]
    assert c["count"] == 2

    # 移出：幂等（第二次也 200，只是 rowcount=0）
    assert client.delete(f"/api/podcast-collections/{cid}/items/{p1['id']}",
                         headers=auth_headers).status_code == 200
    assert client.delete(f"/api/podcast-collections/{cid}/items/{p1['id']}",
                         headers=auth_headers).status_code == 200
    c = client.get("/api/podcast-collections", headers=auth_headers).json()["items"][0]
    assert c["count"] == 1 and c["podcast_ids"] == [p2["id"]]
