"""**残留的 ``downloading`` 必须能自愈**（第 242 期）。

缺陷：`download_state='downloading'` **只被设置、从不被清理** —— 进程被 kill / 容器重启后，
那一集永远卡在「下载中」；而 `enqueue_download` 见到 `downloading` 会**直接跳过** ⇒
**那一集再也下不了**（用户只能删了重订）。

修法：判据「既没有 ``.part`` 临时件、也没有已完成的副本 ⇒ 此刻没人在下它」——
`podcasts._stale_download` 判定，`enqueue_download` 里复位成「未下载」并允许重排。

⚠️ 这条用例必须**真的**造出「状态是 downloading、但盘上什么都没有」的残留行 ——
只改状态不改文件，才能证明判据认的是「有没有人在下」而不是「状态写着什么」。
"""
from __future__ import annotations

import pytest

from novelforge.core import db, podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>测试播客</title>
  <item><title>第 1 集</title><guid>g1</guid>
    <enclosure url="https://cdn/1.mp3" type="audio/mpeg"/></item>
</channel></rss>
"""


@pytest.fixture
def episode(client, auth_headers, monkeypatch):
    """造一集（有 audio_url），返回它。"""
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    r = client.post("/api/podcasts", headers=auth_headers,
                    json={"feed_url": "https://example.com/feed.xml"})
    assert r.status_code == 200, r.text
    pid = r.json()["podcast"]["id"]
    eps = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
    assert eps, "没造出单集"
    return eps[0]


def test_残留的_downloading_被复位且允许重排(episode):
    """状态写着「下载中」，但盘上既无 ``.part`` 也无成品 ⇒ 判为残留 ⇒ 复位成「未下载」。"""
    eid = str(episode["id"])
    db.set_episode_download(eid, "downloading")

    assert podcasts._stale_download(eid, db.get_podcast_episode(eid)) is True, \
        "没有临时件也没有成品的 downloading 应判为残留"

    assert podcasts.reset_stale_downloads() >= 1
    assert db.get_podcast_episode(eid)["download_state"] != "downloading"


def test_真的在下_不算残留(episode):
    """有 ``.part`` 临时件 ⇒ 此刻真的在下 ⇒ **不能**复位（否则会把正在下的打断）。"""
    eid = str(episode["id"])
    db.set_episode_download(eid, "downloading")
    d = podcasts._download_dir(str(episode["podcast_id"]))
    part = d / "x.part"
    part.write_bytes(b"partial")

    try:
        assert podcasts._stale_download(eid, db.get_podcast_episode(eid)) is False, \
            "有 .part 临时件时不该判为残留"
    finally:
        part.unlink(missing_ok=True)


def test_已完成的下载不算残留(episode):
    """状态是 downloading、但已有成品文件 ⇒ 不是「没人在下」的残留。"""
    eid = str(episode["id"])
    db.set_episode_download(eid, "downloading")
    d = podcasts._download_dir(str(episode["podcast_id"]))
    done = d / "done.mp3"
    done.write_bytes(b"audio")
    db.set_episode_download(eid, "downloading", local_path=str(done))

    try:
        assert podcasts._stale_download(eid, db.get_podcast_episode(eid)) is False
    finally:
        done.unlink(missing_ok=True)
