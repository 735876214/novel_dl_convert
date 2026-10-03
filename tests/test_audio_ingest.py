"""第 86 期：有声书「从书源下载 → 落成目录型有声书」（零网络，客户端全用桩）。

核心不是「把字节写下来」，而是**落成一个书架认得的形状**：

- 一本 = 一个目录，轨名必须是 `units` 认得的**序号词**（`第N话`）—— 换个名字
  （`track_1.mp3`）书架看到的就是一堆散装音频，而不是一本书；
- **轨序 = 站点给的顺序**（音频唯一可依的顺序）；
- **失败不留半个目录**（空目录在书架上是一条点开什么都没有的书）。
"""
import asyncio
import pathlib

import pytest

from novelforge.core import audio as audio_mod
from novelforge.core import units
from novelforge.sources import store
from novelforge.sources.manager import DownloadManager

MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64      # 带 ID3 头的假 mp3（字节级真断言）


class _StubClient:
    def __init__(self, html: str = "", blobs: dict = None):
        self.html, self.blobs = html, blobs or {}
        self.got: list = []

    async def get_text(self, url: str) -> str:
        return self.html

    async def get_bytes(self, url: str) -> bytes:
        self.got.append(url)
        return self.blobs[url]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _audio_rule(name: str = "audio-demo", domain: str = "audio-demo.com") -> dict:
    return {
        "name": name, "display_name": name, "domains": [domain], "public": False,
        "search": {"url": f"https://{domain}/s?q={{title}}", "mode": "css", "container": ".i",
                   "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": "audio", "audio": {"mode": "css", "container": "#list a"}},
    }


def _run(tmp_path, isolated, monkeypatch, *, html, blobs):      # noqa: ARG001
    store.add_rule(_audio_rule())
    monkeypatch.setattr(DownloadManager, "_client", lambda self, src: _StubClient(html, blobs))
    mgr = DownloadManager({"download": {"enabled": True}})
    item = {"title": "示例有声书", "url": "https://audio-demo.com/book/1",
            "source": "audio-demo", "_source": "audio-demo"}
    return asyncio.run(mgr.download_audio(item, tmp_path))


def test_落成书架认得的目录型有声书(tmp_path, isolated, monkeypatch):            # noqa: ARG001
    html = '<div id="list"><a href="/t1.mp3">一</a><a href="/t2.mp3">二</a><a href="/t3.mp3">三</a></div>'
    blobs = {f"https://audio-demo.com/t{i}.mp3": MP3 for i in (1, 2, 3)}
    dest = _run(tmp_path, isolated, monkeypatch, html=html, blobs=blobs)

    assert dest.is_dir() and dest.name == "示例有声书"
    assert sorted(p.name for p in dest.iterdir()) == ["第1话.mp3", "第2话.mp3", "第3话.mp3"]
    assert (dest / "第1话.mp3").read_bytes() == MP3, "字节要一致（走 get_bytes，不是 get_text）"
    # 书架认不认，才是这条链路成不成立的关键
    assert units.parse_unit("第1话") == 1
    assert units.is_unit_file(dest / "第2话.mp3")
    assert units.collected_by(dest, [".mp3"], allow_units=False) == "audio", \
        "白名单含音频、目录里全是音频轨 ⇒ 书架把它收成一条音频书"


def test_无扩展名的地址兜底成mp3(tmp_path, isolated, monkeypatch):              # noqa: ARG001
    html = '<div id="list"><a href="/audio?id=1">一</a></div>'
    dest = _run(tmp_path, isolated, monkeypatch, html=html,
                blobs={"https://audio-demo.com/audio?id=1": MP3})
    assert [p.name for p in dest.iterdir()] == ["第1话.mp3"]
    assert audio_mod.is_audio_dir(dest) or audio_mod.is_audio(dest / "第1话.mp3")


def test_没有音频地址就报错且不留空目录(tmp_path, isolated, monkeypatch):          # noqa: ARG001
    with pytest.raises(ValueError, match="没有给出任何音频地址"):
        _run(tmp_path, isolated, monkeypatch, html="<p>页面变了</p>", blobs={})
    assert not (tmp_path / "示例有声书").exists(), "失败不许留下一个点开什么都没有的空目录"


def test_中途失败不留半个目录(tmp_path, isolated, monkeypatch):                  # noqa: ARG001
    """第 2 轨取不回来时，第 1 轨也不该留在磁盘上（否则书架里是一条能播一话的残书）。"""
    html = '<div id="list"><a href="/t1.mp3">一</a><a href="/t2.mp3">二</a></div>'
    with pytest.raises(KeyError):
        _run(tmp_path, isolated, monkeypatch, html=html,
             blobs={"https://audio-demo.com/t1.mp3": MP3})       # t2 故意不给
    assert not (tmp_path / "示例有声书").exists()
