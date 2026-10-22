"""第 141 期（第七轮审计：错误处理与降级路径）。

四条判据（全都是「失败被折成成功」，用户看到的是「没有」而不是「出错」）：

1. **书源目录式取整本不交半本** —— 单章抓取失败曾被写成正文
   ``"（第 N 章抓取失败：…）"`` 交出去：那行字进留档 txt、进 EPUB、进索引，
   **永久占着第 N 章**（追更只从「已有的最后一章」往后取，这一章再也不会重抓）。
2. **「清空回收站」不许在没删干净时报成功** —— 逐个 `OSError: continue` +
   无条件清台账 ⇒ 文件还在盘上、台账的还原路径没了、界面说「已清空」。
3. **索引刷新的失败原因不许丢** —— 「扫描完成，0 本」与「库根没挂上」必须分得开。
4. **配置读坏 / 健康检查要说真话** —— `config.yaml` 解析失败曾静默回落默认值；
   `/health` 的 `status` 曾写死 `"ok"`，库连不上也永远「健康」。
"""
import asyncio
import pathlib
import socket

import pytest

from novelforge import config
from novelforge.core import catalog, db, fileops, library, metafetch, updater
from novelforge.sources import rules


# ---------------- ① 取整本：要么完整，要么报错 ----------------

def _fake_source(links, fail_first: int = 0, always_fail: set | None = None):
    """造一个只实现 `chapter_links` / `chapter_body` 的「书源」，不碰网络。"""
    src = object.__new__(rules.RuleBasedSource)
    src._concurrency = 4
    called: dict = {}

    async def chapter_links(client, book_url):
        return links

    async def chapter_body(client, url):
        n = called[url] = called.get(url, 0) + 1
        if always_fail and url in always_fail:
            raise RuntimeError("HTTP 503")
        if n <= fail_first:
            raise RuntimeError("HTTP 503")
        return f"正文 {url}"

    src.chapter_links = chapter_links
    src.chapter_body = chapter_body
    return src, called


def test_整本下载_单章始终失败则整本报错且正文无错误串():
    links = [{"title": "第一章", "url": "u1"}, {"title": "第二章", "url": "u2"}]
    src, _ = _fake_source(links, always_fail={"u2"})
    with pytest.raises(rules.ChapterFetchError) as ei:
        asyncio.run(src._fetch_toc(None, "book"))
    msg = str(ei.value)
    assert "1/2 章抓取失败" in msg and "第二章" in msg and "503" in msg


def test_整本下载_抖动一次靠重试抹平且不留错误串():
    links = [{"title": "第一章", "url": "u1"}, {"title": "第二章", "url": "u2"}]
    src, called = _fake_source(links, fail_first=1)
    chaps = asyncio.run(src._fetch_toc(None, "book"))
    assert [c["body"] for c in chaps] == ["正文 u1", "正文 u2"]
    assert all("抓取失败" not in c["body"] for c in chaps)
    assert called["u1"] == 2, "失败章必须重试一次"


def test_目录为空返回空清单而不是零章空书():
    src, _ = _fake_source([])
    assert asyncio.run(src._fetch_toc(None, "book")) == []


# ---------------- ② 清空回收站：没删干净就不许报成功 ----------------

def test_清空回收站有删不掉的文件时保留台账(client, auth_headers, isolated, monkeypatch):  # noqa: ARG001
    d = fileops.recycle_dir()
    d.mkdir(parents=True, exist_ok=True)
    # 回收站目录是**整个测试会话共用**的（`isolated` 只隔离目录树）—— 别的用例留下的文件
    # 会把 `removed` 计数带跑，这里先清干净，让「删掉 1 个、留 1 个」成为唯一可能的事实。
    for leftover in list(d.rglob("*")):
        if leftover.is_file():
            leftover.unlink()
    good, bad = d / "能删.txt", d / "删不掉.txt"
    good.write_text("a", encoding="utf-8")
    bad.write_text("b", encoding="utf-8")
    db.recycle_add("/books/x.epub", "能删.txt", why="测试", size=1)
    db.recycle_add("/books/y.epub", "删不掉.txt", why="测试", size=1)

    real_unlink = pathlib.Path.unlink

    def _unlink(self, *a, **kw):
        if self.name == "删不掉.txt":
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "unlink", _unlink)
    r = client.post("/api/maintenance/recycle/clear", headers=auth_headers)
    body = r.json()
    assert body["ok"] is False, body
    assert body["removed"] == 1 and body["failed"], body
    assert good.exists() is False and bad.exists() is True, "删不掉的必须留在盘上"
    assert body["ledger_cleared"] == 0
    # 台账原样保留（它记的正是「这些文件还能还原」）
    assert db.recycle_clear() >= 2


# ---------------- ③ 索引刷新失败原因要留档 ----------------

def test_库根消失时刷新报告带原因(isolated, make_library, tmp_path):  # noqa: ARG001
    import shutil

    lib = make_library("novels", "小说库", "ebook", tmp_path / "lib")
    (tmp_path / "lib" / "书.epub").write_bytes(b"EPUB")
    library.invalidate()
    assert library.books("novels", force=True), "先得索引到一本书，才谈得上「根掉了」"
    shutil.rmtree(tmp_path / "lib")
    library.invalidate()
    library.books("novels", force=True)
    rep = catalog.last_report().get("novels") or {}
    assert rep.get("reason") == "root_unavailable", rep


# ---------------- ④ 配置与健康检查说真话 ----------------

def test_健康检查有真探针格式(client):
    body = client.get("/health").json()
    assert body["status"] in ("ok", "degraded"), body
    for k in ("db", "config_dir_writable", "watcher_running", "dirs_ok", "config_yaml"):
        assert k in body["checks"], body["checks"]


def test_库连不上时健康检查回503(client, monkeypatch):
    monkeypatch.setattr(db, "ping", lambda: False)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "down"
    assert any("数据库" in p for p in r.json()["problems"])


def test_config_destroyed要能看见(client, auth_headers, isolated):  # noqa: ARG001
    cfg_file = config.CONFIG_DIR / "config.yaml"
    backup = cfg_file.read_text(encoding="utf-8") if cfg_file.exists() else None
    try:
        cfg_file.write_text("a: [\n  bad: yaml\n", encoding="utf-8")
        config.load_config()
        err = config.config_error()
        assert err, "解析失败必须留证（否则设置页展示的是默认值，用户以为配置还在）"
        body = client.get("/api/config", headers=auth_headers).json()
        # 诊断键在 `config` 块里（与可保存配置同层，前端草稿才读得到）
        assert body["config"]["_config_error"]
    finally:
        if backup is None:
            cfg_file.unlink(missing_ok=True)
        else:
            cfg_file.write_text(backup, encoding="utf-8")
        config.load_config()


# ---------------- ⑤ 封面失败要归到封面，而不是「没内容」 ----------------

def test_封面下载失败时错误信息指向封面(isolated, make_library, tmp_path, monkeypatch):  # noqa: ARG001
    make_library("novels", "小说库", "ebook", tmp_path / "lib")
    (tmp_path / "lib" / "书A.epub").write_bytes(b"EPUB")
    library.invalidate()

    def _boom(url):
        raise ValueError("图片类型不支持：text/html")

    monkeypatch.setattr(metafetch, "_download_cover", _boom)
    res = metafetch.apply([{"name": "书A.epub", "fields": {},
                            "cover": {"url": "http://example.invalid/c.jpg"}}])
    assert res["failed"], res
    err = res["failed"][0]["error"]
    assert "封面下载失败" in err and "图片类型不支持" in err, err


# ---------------- ⑥ 一键更新可用性：socket 在 ≠ 能用 ----------------

def test_没挂docker_sock时给出原因(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "DOCKER_SOCK", str(tmp_path / "nope.sock"))
    ok, why = updater.updater_probe(force=True)
    assert ok is False and "未挂载" in why


def test_通道与探活是两件事(monkeypatch, tmp_path):
    """`updater_available()` 只判「通道在不在」，通不通由 `updater_probe()` 说（第 141 期）。

    ⚠️ 这两个判据**不许合并**：合成一个的话，要么界面说「可用」而点了必失（旧缺陷），
    要么宿主慢半秒就把整条更新路径判成不可用（拉镜像前的探活抖动）。
    """
    sock = tmp_path / "docker.sock"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(str(sock))
        monkeypatch.setattr(updater, "DOCKER_SOCK", str(sock))
        monkeypatch.setattr(updater, "_probe_cache", (9e18, False, ""))
        assert updater.updater_available() is True, "socket 在 = 有通道"
        ok, why = updater.updater_probe(force=True)
        assert ok is False and why, "没人监听就必须报不可用并给原因"
    finally:
        srv.close()

    plain = tmp_path / "plain.file"
    plain.write_text("not a socket")
    monkeypatch.setattr(updater, "DOCKER_SOCK", str(plain))
    assert updater.updater_available() is False, "挂成普通文件 = 没通道"


def test_socket挂成目录时不报可用(monkeypatch, tmp_path):
    fake = tmp_path / "docker.sock"
    fake.mkdir()
    monkeypatch.setattr(updater, "DOCKER_SOCK", str(fake))
    ok, why = updater.updater_probe(force=True)
    assert ok is False and why, "socket 存在但连不上时不能报「可用」"

