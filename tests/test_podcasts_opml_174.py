"""播客订阅管理（第 174 期）：OPML 导入导出 + 订阅健康 + 批量刷新。

全程离线（`_fetch` 打桩）：
- OPML 导入按 outline 的 `xmlUrl` 去重、逐条回报；导出是合法 OPML；
- 刷新失败只**落账**（fail_count / last_error / last_attempt_at），不动已抓到的单集；
- 下一次成功把失败计数清零并更新 last_ok_at；
- 批量刷新逐条隔离：一条失败不影响其它。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from novelforge.core import podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel><title>测试播客</title>
<item><title>第 1 集</title><guid>g1</guid><enclosure url="https://cdn/1.mp3" type="audio/mpeg"/></item>
</channel></rss>
"""

OPML = """<?xml version="1.0"?>
<opml version="2.0"><body>
  <outline text="分组">
    <outline type="rss" text="A" xmlUrl="https://a/feed.xml"/>
    <outline type="rss" text="B" xmlUrl="https://b/feed.xml"/>
    <outline type="rss" text="A 重复" xmlUrl="https://a/feed.xml"/>
  </outline>
</body></opml>
"""


def test_opml_导出与导入(client, auth_headers, monkeypatch):
    seen = []

    def fake_fetch(url):
        seen.append(url)
        return RSS

    monkeypatch.setattr(podcasts, "_fetch", fake_fetch)
    r = client.post("/api/podcasts/opml", headers=auth_headers, json={"opml": OPML})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and body["added"] == 2 and body["failed"] == []
    assert sorted(seen) == ["https://a/feed.xml", "https://b/feed.xml"]

    out = client.get("/api/podcasts/opml", headers=auth_headers)
    assert out.status_code == 200, out.text
    root = ET.fromstring(out.json()["opml"])
    urls = [e.get("xmlUrl") for e in root.iter("outline") if e.get("xmlUrl")]
    assert sorted(urls) == ["https://a/feed.xml", "https://b/feed.xml"]

    # 再导入一次：全部“刷新”，不新增
    again = client.post("/api/podcasts/opml", headers=auth_headers, json={"opml": OPML})
    assert again.json()["added"] == 0 and again.json()["refreshed"] == 2


def test_刷新失败落账_成功清零(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    pid = client.post("/api/podcasts", headers=auth_headers,
                      json={"feed_url": "https://a/feed.xml"}).json()["podcast"]["id"]

    def boom(url):
        raise ValueError("抓取订阅失败：HTTP 500")

    monkeypatch.setattr(podcasts, "_fetch", boom)
    assert client.post(f"/api/podcasts/{pid}/refresh", headers=auth_headers).status_code == 400
    p = next(x for x in client.get("/api/podcasts", headers=auth_headers).json()["items"]
             if x["id"] == pid)
    assert p["fail_count"] == 1
    assert "HTTP 500" in p["last_error"]
    assert p["last_attempt_at"] > 0
    # 失败不动已有单集
    eps = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
    assert [e["title"] for e in eps] == ["第 1 集"]

    # 恢复：失败计数清零、last_ok_at 有值
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    assert client.post(f"/api/podcasts/{pid}/refresh", headers=auth_headers).status_code == 200
    p2 = next(x for x in client.get("/api/podcasts", headers=auth_headers).json()["items"]
              if x["id"] == pid)
    assert p2["fail_count"] == 0 and p2["last_error"] == "" and p2["last_ok_at"] > 0


def test_批量刷新逐条隔离(client, auth_headers, monkeypatch):
    def fetch(url):
        if "bad" in url:
            raise ValueError("抓取订阅失败：超时")
        return RSS

    monkeypatch.setattr(podcasts, "_fetch", fetch)
    assert client.post("/api/podcasts", headers=auth_headers,
                       json={"feed_url": "https://ok/feed.xml"}).status_code == 200
    # 坏源订阅当场失败（不建行）
    assert client.post("/api/podcasts", headers=auth_headers,
                       json={"feed_url": "https://bad/feed.xml"}).status_code == 400
    items = client.get("/api/podcasts", headers=auth_headers).json()["items"]
    assert len(items) == 1
    ok_id = items[0]["id"]

    # 再建一条好订阅；随后让它“挂掉”（模拟订阅后源站不可用）
    pid2 = client.post("/api/podcasts", headers=auth_headers,
                       json={"feed_url": "https://ok2/feed.xml"}).json()["podcast"]["id"]

    def fetch2(url):
        if url == "https://ok2/feed.xml":
            raise ValueError("抓取订阅失败：超时")
        return RSS

    monkeypatch.setattr(podcasts, "_fetch", fetch2)
    r = client.post("/api/podcasts/refresh-all", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] == 1 and body["failed"] == 1
    assert {x["id"] for x in body["items"]} == {ok_id, pid2}
