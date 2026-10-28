"""播客订阅内核（第 173 期）：RSS 解析 + 订阅 / 刷新 / 软删除。

全程离线：`podcasts._fetch` 被替换成返回固定 XML，绝不真出网。

钉住：
- RSS 2.0 的频道 / 单集字段（含 itunes 命名空间、`1:02:03` 时长、封面两种写法）；
- **没有 enclosure 的单集不建条目**（没音频地址没法播）；
- Atom 明确拒绝（没有真实样本，不猜着解析）；
- 订阅 → 刷新（更新 + 新增）→ 软删除 → 重订阅复活（同一行，不撞 feed UNIQUE）。
"""
from __future__ import annotations

from novelforge.core import podcasts

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>测试播客</title>
  <itunes:author>某某</itunes:author>
  <description>一个 &lt;b&gt;测试&lt;/b&gt; 播客</description>
  <itunes:image href="https://cdn.example/cover.jpg"/>
  <itunes:category text="科技"/>
  <itunes:explicit>no</itunes:explicit>
  <item>
    <title>第 1 集</title><guid>ep1</guid>
    <description>简介 1</description>
    <pubDate>Mon, 02 Oct 2023 10:00:00 GMT</pubDate>
    <itunes:duration>1:02:03</itunes:duration>
    <itunes:episode>1</itunes:episode>
    <enclosure url="https://cdn.example/1.mp3" type="audio/mpeg" length="123"/>
  </item>
  <item>
    <title>第 2 集</title><guid>ep2</guid>
    <pubDate>Fri, 01 Sep 2023 10:00:00 GMT</pubDate>
    <itunes:duration>59</itunes:duration>
    <enclosure url="https://cdn.example/2.mp3" type="audio/mpeg" length="99"/>
  </item>
  <item>
    <title>无音频的条目</title><guid>ep3</guid>
  </item>
</channel>
</rss>
"""

RSS2 = RSS.replace("<title>第 1 集</title>", "<title>第 1 集（重制）</title>").replace(
    "</channel>",
    """  <item>
    <title>第 4 集</title><guid>ep4</guid>
    <pubDate>Thu, 02 Nov 2023 10:00:00 GMT</pubDate>
    <itunes:duration>10:00</itunes:duration>
    <enclosure url="https://cdn.example/4.mp3" type="audio/mpeg"/>
  </item>
</channel>""",
)

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>"""


def test_解析_rss_频道与单集():
    meta, eps = podcasts.parse_feed(RSS)
    assert meta["title"] == "测试播客"
    assert meta["author"] == "某某"
    assert "<b>" not in meta["description"] and "测试" in meta["description"]
    assert meta["artwork_url"] == "https://cdn.example/cover.jpg"
    assert meta["categories"] == ["科技"]
    assert meta["explicit"] is False
    assert [e["guid"] for e in eps] == ["ep1", "ep2"]          # 无 enclosure 的被跳过
    assert eps[0]["duration_sec"] == 3723
    assert eps[1]["duration_sec"] == 59
    assert eps[0]["episode_no"] == 1
    assert eps[0]["published_at"] > 0


def test_时长解析与_atom_拒绝():
    assert podcasts.parse_duration("1234") == 1234
    assert podcasts.parse_duration("12:34") == 754
    assert podcasts.parse_duration("1:02:03") == 3723
    assert podcasts.parse_duration("坏值") == 0
    assert podcasts.parse_duration("") == 0
    try:
        podcasts.parse_feed(ATOM)
    except ValueError as e:
        assert "Atom" in str(e)
    else:                                                       # pragma: no cover
        raise AssertionError("Atom 源必须明确拒绝")


def _subscribe(client, auth_headers, monkeypatch, xml: str):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: xml)
    return client.post("/api/podcasts", headers=auth_headers,
                       json={"feed_url": "https://example.com/feed.xml"})


def test_订阅_刷新_软删除_重订阅复活(client, auth_headers, monkeypatch):
    r = _subscribe(client, auth_headers, monkeypatch, RSS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True and body["added"] == 2
    pid = body["podcast"]["id"]

    items = client.get("/api/podcasts", headers=auth_headers).json()["items"]
    assert [p["id"] for p in items] == [pid]
    eps = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
    assert [e["title"] for e in eps] == ["第 1 集", "第 2 集"]   # 按发布时间倒序

    # 刷新：ep1 标题更新、ep4 新增
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS2)
    rr = client.post(f"/api/podcasts/{pid}/refresh", headers=auth_headers)
    assert rr.status_code == 200, rr.text
    assert rr.json()["added"] == 1 and rr.json()["updated"] == 2
    titles = [e["title"] for e in client.get(f"/api/podcasts/{pid}/episodes",
                                             headers=auth_headers).json()["items"]]
    assert "第 1 集（重制）" in titles and "第 4 集" in titles

    # 软删除：列表为空，详情 404
    assert client.delete(f"/api/podcasts/{pid}", headers=auth_headers).status_code == 200
    assert client.get("/api/podcasts", headers=auth_headers).json()["items"] == []
    assert client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).status_code == 404

    # 重订阅同一 feed：复活同一行（不撞 UNIQUE），created=False
    again = _subscribe(client, auth_headers, monkeypatch, RSS)
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    assert again.json()["podcast"]["id"] == pid


def test_坏源与不存在的订阅(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: "<html>not rss</html>")
    assert client.post("/api/podcasts", headers=auth_headers,
                       json={"feed_url": "https://example.com/x"}).status_code == 400
    assert client.post("/api/podcasts", headers=auth_headers,
                       json={"feed_url": "file:///etc/passwd"}).status_code == 400
    assert client.post("/api/podcasts/不存在/refresh", headers=auth_headers).status_code == 404
    assert client.get("/api/podcasts/不存在/episodes", headers=auth_headers).status_code == 404
    assert client.delete("/api/podcasts/不存在", headers=auth_headers).status_code == 404
