"""播客单集下载（第 175 期）：队列、本地播放、清理入回收站。

离线：`_fetch`（RSS）与 `_download_bytes`（音频）都打桩，不触网。
钉住：下载状态机（downloading → downloaded / failed）、本地播放出口、
清理**移入回收站**（不是删除）、批量下载只排未下载的、失败如实落库。
"""
from __future__ import annotations

import time

from novelforge.core import fileops, podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>测试播客</title>
  <item><title>第 1 集</title><guid>g1</guid>
    <enclosure url="https://cdn/1.mp3" type="audio/mpeg"/></item>
  <item><title>第 2 集</title><guid>g2</guid>
    <enclosure url="https://cdn/2.mp3" type="audio/mpeg"/></item>
</channel></rss>
"""

AUDIO = b"ID3" + b"x" * 1024


def _setup(client, auth_headers, monkeypatch):
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    r = client.post("/api/podcasts", headers=auth_headers,
                    json={"feed_url": "https://example.com/feed.xml"})
    assert r.status_code == 200, r.text
    pid = r.json()["podcast"]["id"]
    eps = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
    return pid, {e["title"]: e["id"] for e in eps}


def _wait(client, auth_headers, pid: str, eid: str, want: str, timeout: float = 5.0):
    end = time.time() + timeout
    while time.time() < end:
        items = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
        st = next((e["download_state"] for e in items if e["id"] == eid), "")
        if st == want:
            return st
        time.sleep(0.02)
    raise AssertionError(f"{eid} 没有到达状态 {want}（最后是 {st!r}）")


def test_下载_本地播放_清理入回收站(client, auth_headers, monkeypatch):
    pid, ids = _setup(client, auth_headers, monkeypatch)
    eid = ids["第 1 集"]

    # 未下载时本地出口 404（前端据此回退远端地址）
    assert client.get(f"/api/podcasts/episodes/{eid}/audio", headers=auth_headers).status_code == 404

    monkeypatch.setattr(podcasts, "_download_bytes",
                        lambda url, tmp: (tmp.write_bytes(AUDIO), len(AUDIO))[1])
    r = client.post(f"/api/podcasts/episodes/{eid}/download", headers=auth_headers)
    assert r.status_code == 200 and r.json()["state"] == "downloading"
    _wait(client, auth_headers, pid, eid, "downloaded")

    audio = client.get(f"/api/podcasts/episodes/{eid}/audio", headers=auth_headers)
    assert audio.status_code == 200 and audio.content == AUDIO

    # 已下载再点：幂等，不重新排队
    again = client.post(f"/api/podcasts/episodes/{eid}/download", headers=auth_headers)
    assert again.json()["state"] == "downloaded"

    # 清理：状态清空，文件进回收站（不是被删）
    before = {p.name for p in fileops.recycle_dir().iterdir()}
    cleaned = client.delete(f"/api/podcasts/episodes/{eid}/download", headers=auth_headers)
    assert cleaned.status_code == 200 and cleaned.json()["moved_to"]
    after = {p.name for p in fileops.recycle_dir().iterdir()}
    assert after - before, "清理必须把文件移入回收站"
    items = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
    assert next(e for e in items if e["id"] == eid)["download_state"] == ""


def test_批量下载只排未下载_失败落库(client, auth_headers, monkeypatch):
    pid, ids = _setup(client, auth_headers, monkeypatch)
    calls = []

    def fake(url, tmp):
        calls.append(url)
        if "2.mp3" in url:
            raise RuntimeError("连接被重置")
        tmp.write_bytes(AUDIO)
        return len(AUDIO)

    monkeypatch.setattr(podcasts, "_download_bytes", fake)
    r = client.post(f"/api/podcasts/{pid}/download-all", headers=auth_headers)
    assert r.status_code == 200 and r.json()["queued"] == 2

    _wait(client, auth_headers, pid, ids["第 1 集"], "downloaded")
    _wait(client, auth_headers, pid, ids["第 2 集"], "failed")
    items = {e["id"]: e for e in client.get(f"/api/podcasts/{pid}/episodes",
                                            headers=auth_headers).json()["items"]}
    assert "连接被重置" in items[ids["第 2 集"]]["download_error"]

    # 再跑一次批量：只排“失败/未下载”的那一集（已下载的不重复）
    n = len(calls)
    r2 = client.post(f"/api/podcasts/{pid}/download-all", headers=auth_headers)
    assert r2.json()["queued"] == 1
    end = time.time() + 5
    while time.time() < end and len(calls) < n + 1:
        time.sleep(0.02)
    assert len(calls) == n + 1
