"""播客自动下载 / 听完清理（第 181 期）。

离线（RSS 与音频下载都打桩）：
- 「自动下载最新 N 集」在**刷新之后**执行，只排未下载的；
- 听完清理只在 `played_at` 被记下且订阅开了 auto_clean 时触发，且**只清本地副本**
  （移入回收站，状态清空）；
- `auto_keep` 0 = 关闭自动下载；越界 400。
"""
from __future__ import annotations

import time

from novelforge.core import fileops, podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>测试播客</title>
  <item><title>最新</title><guid>g1</guid><pubDate>Mon, 03 Oct 2022 10:00:00 GMT</pubDate>
    <enclosure url="https://cdn/1.mp3" type="audio/mpeg"/></item>
  <item><title>中间</title><guid>g2</guid><pubDate>Sun, 02 Oct 2022 10:00:00 GMT</pubDate>
    <enclosure url="https://cdn/2.mp3" type="audio/mpeg"/></item>
  <item><title>最旧</title><guid>g3</guid><pubDate>Sat, 01 Oct 2022 10:00:00 GMT</pubDate>
    <enclosure url="https://cdn/3.mp3" type="audio/mpeg"/></item>
</channel></rss>
"""

AUDIO = b"ID3" + b"x" * 64


def _setup(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    pid = client.post("/api/podcasts", headers=auth_headers,
                      json={"feed_url": "https://example.com/feed.xml"}).json()["podcast"]["id"]
    eps = {e["title"]: e["id"] for e in
           client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]}
    return pid, eps


def _wait_state(client, auth_headers, pid, eid, want, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        items = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
        st = next((e["download_state"] for e in items if e["id"] == eid), "")
        if st == want:
            return
        time.sleep(0.02)
    raise AssertionError(f"{eid} 未到 {want}（最后 {st!r}）")


def test_自动下载最新N集_听完清理(client, auth_headers, monkeypatch):
    pid, eps = _setup(client, auth_headers, monkeypatch)
    r = client.patch(f"/api/podcasts/{pid}/auto", headers=auth_headers,
                     json={"auto_keep": 2})
    assert r.status_code == 200, r.text
    assert r.json() == {"auto_download": True, "auto_keep": 2, "auto_clean": False}

    monkeypatch.setattr(podcasts, "_download_bytes",
                        lambda url, tmp: (tmp.write_bytes(AUDIO), len(AUDIO))[1])
    rr = client.post(f"/api/podcasts/{pid}/refresh", headers=auth_headers)
    assert rr.status_code == 200, rr.text
    assert rr.json()["auto_queued"] == 2                 # 只排最新两集

    _wait_state(client, auth_headers, pid, eps["最新"], "downloaded")
    _wait_state(client, auth_headers, pid, eps["中间"], "downloaded")
    assert next(e for e in client.get(f"/api/podcasts/{pid}/episodes",
                                      headers=auth_headers).json()["items"]
                if e["id"] == eps["最旧"])["download_state"] == ""

    # 听完清理：开 auto_clean，把「最新」标已播 ⇒ 本地副本进回收站、状态清空
    client.patch(f"/api/podcasts/{pid}/auto", headers=auth_headers,
                 json={"auto_clean": True})
    before = {p.name for p in fileops.recycle_dir().iterdir()}
    assert client.post(f"/api/podcasts/episodes/{eps['最新']}/played",
                       headers=auth_headers, json={"played": True}).status_code == 200
    after = {p.name for p in fileops.recycle_dir().iterdir()}
    assert after - before
    ep = next(e for e in client.get(f"/api/podcasts/{pid}/episodes",
                                    headers=auth_headers).json()["items"]
              if e["id"] == eps["最新"])
    assert ep["download_state"] == "" and ep["played_at"] > 0
    # 「中间」没标已播 ⇒ 副本还在
    assert next(e for e in client.get(f"/api/podcasts/{pid}/episodes",
                                      headers=auth_headers).json()["items"]
                if e["id"] == eps["中间"])["download_state"] == "downloaded"


def test_关闭与坏入参(client, auth_headers, monkeypatch):
    pid, _ = _setup(client, auth_headers, monkeypatch)
    assert client.patch(f"/api/podcasts/{pid}/auto", headers=auth_headers,
                        json={"auto_keep": 0}).json()["auto_download"] is False
    assert client.patch(f"/api/podcasts/{pid}/auto", headers=auth_headers,
                        json={"auto_keep": 999}).status_code == 400
    assert client.patch("/api/podcasts/不存在/auto", headers=auth_headers,
                        json={"auto_keep": 1}).status_code == 404
    assert client.get("/api/podcasts/不存在/auto", headers=auth_headers).status_code == 404
