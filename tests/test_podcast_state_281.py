"""「残留下载」复位必须是 compare-and-set（第 281 期）。

背景（实测复现，见本期 roadmap）：`_stale_download()` 判的是**快照**，而
`reset_stale_in()` / `reset_stale_downloads()` 原先判完就**无条件**把状态写成 ``''``。
判定与写入之间 worker 可能刚好完成（`os.replace` 落盘 + 置 ``downloaded``）——
于是列表接口把**刚下完**的一集写回「未下载」：

```
AnyIO worker thread  set 8adf945d downloading
podcast-download     set 8adf945d downloaded     ← worker 完成
AnyIO worker thread  set 8adf945d ''             ← 列表接口按旧快照复位，把结果抹掉
```

用户看到「未下载」，再点一次又下一遍；`auto_clean` 也不再清它
（`_maybe_clean` 的判据是 `download_state == "downloaded"`）。

修法：DB 层 `reset_episode_download_if_stale()` 用
``UPDATE … WHERE id=? AND download_state='downloading'`` 做 compare-and-set。
下面钉住两件事：CAS 本身；以及「列表接口读到旧快照、worker 在写入前完成」这个真实交错。
"""
from novelforge.core import db, podcasts

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>测试播客</title>
  <item><title>唯一</title><guid>g1</guid><pubDate>Mon, 03 Oct 2022 10:00:00 GMT</pubDate>
    <enclosure url="https://cdn/1.mp3" type="audio/mpeg"/></item>
</channel></rss>
"""


def _podcast(client, auth_headers, monkeypatch) -> tuple:
    monkeypatch.setattr(podcasts, "_fetch", lambda url: RSS)
    pid = client.post("/api/podcasts", headers=auth_headers,
                      json={"feed_url": "https://example.com/feed.xml"}).json()["podcast"]["id"]
    items = client.get(f"/api/podcasts/{pid}/episodes", headers=auth_headers).json()["items"]
    return pid, items[0]["id"]


def test_复位只对仍在下载中的行生效(client, auth_headers, monkeypatch):
    _pid, eid = _podcast(client, auth_headers, monkeypatch)

    db.set_episode_download(eid, "downloading")
    assert db.reset_episode_download_if_stale(eid) is True
    assert db.get_podcast_episode(eid)["download_state"] == ""

    # 已经下完 ⇒ 复位必须**一个字都不写**（否则文件在、状态却是未下载）
    db.set_episode_download(eid, "downloaded", local_path="/tmp/x.mp3", size=1)
    assert db.reset_episode_download_if_stale(eid) is False
    ep = db.get_podcast_episode(eid)
    assert ep["download_state"] == "downloaded"
    assert ep["local_path"] == "/tmp/x.mp3"


def test_列表接口不会把刚下完的一集写回未下载(client, auth_headers, monkeypatch):
    """真实交错：列表接口拿到「downloading、无本地文件」的快照 → worker 完成 → 接口才写。"""
    pid, eid = _podcast(client, auth_headers, monkeypatch)
    db.set_episode_download(eid, "downloading")

    real = podcasts._stale_download

    def racy(e, ep):
        stale = real(e, ep)                      # 按旧快照判：是残留
        # 判定之后、写入之前 —— worker 恰好完成（落盘 + 置 downloaded）。
        db.set_episode_download(e, "downloaded", local_path="/tmp/x.mp3", size=1)
        return stale

    monkeypatch.setattr(podcasts, "_stale_download", racy)
    assert client.get(f"/api/podcasts/{pid}/episodes",
                      headers=auth_headers).status_code == 200

    ep = db.get_podcast_episode(eid)
    assert ep["download_state"] == "downloaded", "刚下完的一集被复位成未下载了"
    assert ep["local_path"] == "/tmp/x.mp3"
