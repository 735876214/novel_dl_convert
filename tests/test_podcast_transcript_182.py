"""播客官方转录（第 182 期）。

离线（RSS 与转录文件都打桩）：
- 只读 feed 的 `<podcast:transcript>`；没有就如实返回「不做 ASR」，不假装能写；
- VTT / SRT 的头部与时间码被剥掉，只留文本；JSON 规范取 segments；
- 抓取结果缓存到库，第二次不再出网。
"""
from __future__ import annotations

from novelforge.core import podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel><title>测试播客</title>
  <item><title>有转录</title><guid>g1</guid>
    <enclosure url="https://cdn/1.mp3" type="audio/mpeg"/>
    <podcast:transcript url="https://cdn/1.vtt" type="text/vtt"/>
  </item>
  <item><title>无转录</title><guid>g2</guid>
    <enclosure url="https://cdn/2.mp3" type="audio/mpeg"/>
  </item>
</channel></rss>
"""

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
第一句

00:00:03.500 --> 00:00:05.000
第二句
"""


def _episodes(client, auth_headers):
    pid = client.post("/api/podcasts", headers=auth_headers,
                      json={"feed_url": "https://example.com/feed.xml"}).json()["podcast"]["id"]
    items = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
    return pid, {e["title"]: e for e in items}


def test_转录抓取_剥时间码_并缓存(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    pid, eps = _episodes(client, auth_headers)
    assert eps["有转录"]["has_transcript"] is True
    assert eps["有转录"]["transcript_type"] == "text/vtt"
    assert eps["无转录"]["has_transcript"] is False

    calls = []

    def fetch(url):
        calls.append(url)
        return VTT

    monkeypatch.setattr(podcasts, "_fetch", fetch)
    r = client.get(f"/api/podcasts/episodes/{eps['有转录']['id']}/transcript",
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["text"] == "第一句\n第二句"
    assert calls == ["https://cdn/1.vtt"]

    # 第二次走缓存，不再出网
    r2 = client.get(f"/api/podcasts/episodes/{eps['有转录']['id']}/transcript",
                    headers=auth_headers)
    assert r2.json()["text"] == body["text"]
    assert calls == ["https://cdn/1.vtt"]


def test_无转录如实说明_与_404(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    pid, eps = _episodes(client, auth_headers)
    r = client.get(f"/api/podcasts/episodes/{eps['无转录']['id']}/transcript",
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert "ASR" in body["reason"]
    assert client.get("/api/podcasts/episodes/不存在/transcript",
                      headers=auth_headers).status_code == 404


def test_json_转录取_segments():
    raw = '{"segments":[{"text":"甲"},{"body":"乙"},{"text":""}]}'
    assert podcasts._plain_transcript(raw, "application/json") == "甲\n乙"
