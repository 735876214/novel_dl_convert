"""第 86 期第 6 步：音频 / 漫画的**追加写回**（零网络，客户端用桩）。

追更的承诺是「只追加」。对这两类产物，「只追加」意味着：
① **既有条目的字节一个都不动**（漫画：既有页的压缩数据；音频：既有文件根本不重写）；
② 新内容续着**既有编号**排（页号 / 话号），既有顺序因此不变 —— 阅读进度按序号记录，
   这一条就是它不漂移的根据；
③ 撞名跳号，**绝不覆盖**；失败不留半个文件。
"""
import asyncio
import pathlib
import zipfile

from novelforge.core import comics, units
from novelforge.sources.manager import DownloadManager

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082")
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


class _StubClient:
    def __init__(self, blobs):
        self.blobs = blobs
        self.got = []

    async def get_bytes(self, url):
        self.got.append(url)
        return self.blobs[url]


# ---------------- 漫画：追加页 ----------------

def test_漫画追加页且既有页字节不变(tmp_path):
    cbz = tmp_path / "书.cbz"
    comics.write_cbz(cbz, [("0001.jpg", PNG), ("0002.jpg", PNG)])
    with zipfile.ZipFile(cbz) as z:
        before = {n: z.read(n) for n in z.namelist()}

    res = comics.append_pages(cbz, [(".jpg", PNG), (".jpg", PNG)])
    assert res["added"] == ["0003.jpg", "0004.jpg"] and res["start"] == 3

    with zipfile.ZipFile(cbz) as z:
        names = z.namelist()
        assert names[:2] == ["0001.jpg", "0002.jpg"], "既有页序不变"
        assert {n: z.read(n) for n in names[:2]} == before, "既有页的字节一个都不许动"
    assert comics.pages(cbz)["total"] == 4, "追加完本项目自己的读入口要认得"


def test_漫画撞名跳号不覆盖(tmp_path):
    cbz = tmp_path / "书.cbz"
    comics.write_cbz(cbz, [("0001.jpg", PNG), ("0002.jpg", PNG)])
    # 故意给一个已占用的编号：实现必须跳号，而不是把既有页盖掉
    res = comics.append_pages(cbz, [(".jpg", b"NEW")])
    assert res["added"] == ["0003.jpg"]
    with zipfile.ZipFile(cbz) as z:
        assert z.read("0001.jpg") == PNG


def test_漫画没有新页不碰文件(tmp_path):
    cbz = tmp_path / "书.cbz"
    comics.write_cbz(cbz, [("0001.jpg", PNG)])
    before = cbz.read_bytes()
    assert comics.append_pages(cbz, [])["added"] == []
    assert cbz.read_bytes() == before


# ---------------- 有声书：追加轨 ----------------

def _audio_mgr():
    return DownloadManager({"download": {"enabled": True}})


def test_音频追加轨续着既有话号(tmp_path):
    d = tmp_path / "有声书"
    d.mkdir()
    (d / "第1话.mp3").write_bytes(MP3)
    (d / "第2话.mp3").write_bytes(MP3)
    before = {p.name: p.read_bytes() for p in d.iterdir()}

    blobs = {"https://a.com/t3.mp3": MP3, "https://a.com/audio?id=4": MP3}
    res = asyncio.run(_audio_mgr().append_audio(
        _StubClient(blobs), d, ["https://a.com/t3.mp3", "https://a.com/audio?id=4"]))

    assert res["added"] == ["第3话.mp3", "第4话.mp3"] and res["start"] == 3
    assert not list(d.glob("*.part")), "先写 .part 再替换：不许留下半成品"
    assert {p.name: p.read_bytes() for p in d.iterdir()} == {
        **before, "第3话.mp3": MP3, "第4话.mp3": MP3}, "既有轨一个字节都不许动"
    # 书架认不认，才是这条链路成不成立的关键
    assert units.parse_unit("第3话") == 3
    assert sorted(p.name for p in d.iterdir()) != [], "目录里必须有东西"
    assert units.collected_by(d, [".mp3"], allow_units=False) == "audio"


def test_音频撞名跳号且无扩展名兜底mp3(tmp_path):
    d = tmp_path / "有声书"
    d.mkdir()
    (d / "第1话.mp3").write_bytes(MP3)
    res = asyncio.run(_audio_mgr().append_audio(
        _StubClient({"https://a.com/x": MP3}), d, ["https://a.com/x"]))
    assert res["added"] == ["第2话.mp3"], "续号 + 没有扩展名时兜底 .mp3"


def test_音频没有新轨不建目录(tmp_path):
    d = tmp_path / "不存在"
    assert asyncio.run(_audio_mgr().append_audio(_StubClient({}), d, []))["added"] == []
    assert not d.exists(), "没有新轨就不该凭空建一个目录（书架里会多一本空书）"
