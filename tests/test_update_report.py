"""第 86 期第 6 步：追更 `manager.update_report` —— 「**只追加**」的可执行断言。

书源用桩（零网络），但 **EPUB 是真产物**（`epub_builder` 造），所以「既有条目一字不动」
是拿字节验证的，不是「看起来对」。

要钉住的四件事（前三条都是旧实现的静默出错点）：
1. 起点按「本地已有几章」算，**不按章名找**（站点给章名加个「（上）」不该导致整本重追加）；
2. EPUB 走 `append_chapters`：既有章节**编号/顺序/内容**不变 ⇒ 阅读数据 index 不漂移；
3. txt 留档**带标题**（旧实现只写 body）；
4. 源上少了章 / 没有新章 ⇒ **只报告、绝不动文件**。
"""
import asyncio
import json
import pathlib
import shutil
import zipfile

import pytest

from novelforge.core import epub_builder, epub_update
from novelforge.sources import store
from novelforge.sources.manager import DownloadManager


class _StubClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _rule(name: str = "update-demo") -> dict:
    return {"name": name, "display_name": name, "domains": ["d.com"], "public": False,
            "search": {"url": "https://d.com/s?q={title}", "mode": "css", "container": ".i",
                       "fields": {"title": ".t", "url": "a::attr(href)"}},
            "book": {"mode": "toc", "toc": {"mode": "css", "container": "a"},
                     "content": {"mode": "css", "container": "#c"}}}


def _setup(tmp_path, isolated, monkeypatch, *, local_chapters: int, source_chapters: list):
    """造一套「已下载 2 章」的现场（真 EPUB + txt + sidecar），并让源返回给定章节。"""
    store.add_rule(_rule())
    d = tmp_path / "lib"
    d.mkdir()
    txt = d / "书.txt"
    txt.write_text("".join(f"第 {i} 章\n正文 {i}\n\n" for i in range(1, local_chapters + 1)),
                   encoding="utf-8")
    epub = d / "书.epub"
    epub_builder.build_epub(
        {"title": "书", "author": "x", "language": "zh"},
        [{"title": f"第 {i} 章", "body_html": f"<p>正文 {i}</p>"}
         for i in range(1, local_chapters + 1)], str(epub))
    (d / "书.meta.json").write_text(json.dumps({
        "source": "update-demo", "url": "https://d.com/b", "title": "书",
        "output_dir": str(d), "chapters": local_chapters,
        "last_title": f"第 {local_chapters} 章"}, ensure_ascii=False), encoding="utf-8")

    class _Src:
        name = "update-demo"

        async def fetch_book_chapters(self, client, item):
            return [{"title": t, "body": b} for t, b in source_chapters]

    monkeypatch.setattr(DownloadManager, "_client", lambda self, src: _StubClient())
    monkeypatch.setattr("novelforge.sources.manager.REGISTRY",
                        {"update-demo": _Src}, raising=False)
    mgr = DownloadManager({"download": {"enabled": True}})
    return mgr, txt, epub


def _chapters(*pairs):
    return list(pairs)


def test_只追加新章且既有epub条目一字不动(tmp_path, isolated, monkeypatch):        # noqa: ARG001
    src_ch = _chapters(("第 1 章", "正文 1"), ("第 2 章", "正文 2"),
                       ("第 3 章", "新正文 3"), ("第 4 章", "新正文 4"))
    mgr, txt, epub = _setup(tmp_path, isolated, monkeypatch, local_chapters=2,
                            source_chapters=src_ch)
    before = tmp_path / "before.epub"
    shutil.copyfile(epub, before)

    rep = asyncio.run(mgr.update_report(txt, {}))
    assert rep["added"] == 2 and rep["missing"] == 0
    assert rep["epub"] == str(epub)
    # ① EPUB：新章入包，**既有条目一字不动**（既有章节 index 不漂移才有这一条）
    assert epub_update.verify_unchanged(
        before, epub, added={"EPUB/c0002.xhtml", "EPUB/c0003.xhtml"},
        replaced={"EPUB/content.opf", "EPUB/nav.xhtml", "EPUB/toc.ncx"}) == []
    # ② txt 留档**带标题**
    text = txt.read_text(encoding="utf-8")
    assert "第 3 章\n新正文 3" in text and "第 4 章\n新正文 4" in text
    # ③ sidecar 推进到「本地现在 4 章」
    meta = json.loads((txt.with_suffix(".meta.json")).read_text(encoding="utf-8"))
    assert meta["chapters"] == 4 and meta["last_title"] == "第 4 章"


def test_起点不靠章名_站点改章名也不会整本重追加(tmp_path, isolated, monkeypatch):   # noqa: ARG001
    """旧实现按 `last_title` 找起点：章名一变就找不到 ⇒ start=0 ⇒ **整本再追加一遍**。"""
    src_ch = _chapters(("第 1 章（上）", "正文 1"), ("第 2 章（上）", "正文 2"),
                       ("第 3 章（上）", "新正文 3"))
    mgr, txt, epub = _setup(tmp_path, isolated, monkeypatch, local_chapters=2,
                            source_chapters=src_ch)
    rep = asyncio.run(mgr.update_report(txt, {}))
    assert rep["added"] == 1, "章名变了也只该追加第 3 章（按已有章数算起点）"
    text = txt.read_text(encoding="utf-8")
    assert text.count("正文 1") == 1, "已读过的章不许被再追加一遍"


def test_没有新章就不碰任何文件(tmp_path, isolated, monkeypatch):                  # noqa: ARG001
    src_ch = _chapters(("第 1 章", "正文 1"), ("第 2 章", "正文 2"))
    mgr, txt, epub = _setup(tmp_path, isolated, monkeypatch, local_chapters=2,
                            source_chapters=src_ch)
    t_before, e_before, s_before = txt.read_bytes(), epub.read_bytes(), \
        txt.with_suffix(".meta.json").read_bytes()
    rep = asyncio.run(mgr.update_report(txt, {}))
    assert rep["added"] == 0 and "没有新章节" in rep["note"]
    assert txt.read_bytes() == t_before and epub.read_bytes() == e_before
    assert txt.with_suffix(".meta.json").read_bytes() == s_before


def test_源上少了章只报告绝不删本地(tmp_path, isolated, monkeypatch):                # noqa: ARG001
    mgr, txt, epub = _setup(tmp_path, isolated, monkeypatch, local_chapters=2,
                            source_chapters=_chapters(("第 1 章", "正文 1")))
    t_before, e_before = txt.read_bytes(), epub.read_bytes()
    rep = asyncio.run(mgr.update_report(txt, {}))
    assert rep["missing"] == 1 and rep["added"] == 0 and "只追加" in rep["note"]
    assert txt.read_bytes() == t_before and epub.read_bytes() == e_before, \
        "少章是「报告」而不是「删除本地已有的章」"


def test_找不到epub就如实说并只留档txt(tmp_path, isolated, monkeypatch):            # noqa: ARG001
    mgr, txt, epub = _setup(tmp_path, isolated, monkeypatch, local_chapters=2,
                            source_chapters=_chapters(("第 1 章", "正文 1"),
                                                      ("第 2 章", "正文 2"),
                                                      ("第 3 章", "新正文 3")))
    epub.unlink()
    rep = asyncio.run(mgr.update_report(txt, {}))
    assert rep["added"] == 1 and rep["epub"] == "" and "没找到同名 EPUB" in rep["note"], \
        "找不到 EPUB 要如实说，不能假装更新成功"


def test_兼容壳仍返回Path(tmp_path, isolated, monkeypatch):                        # noqa: ARG001
    mgr, txt, _ = _setup(tmp_path, isolated, monkeypatch, local_chapters=2,
                         source_chapters=_chapters(("第 1 章", "正文 1"), ("第 2 章", "正文 2"),
                                                   ("第 3 章", "新正文 3")))
    assert asyncio.run(mgr.update(txt, {})) == txt, "旧调用方拿到的仍是 Path"
