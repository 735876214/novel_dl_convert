"""第 93 期 E3/E4/E5：源站的内容**落到这本书自己**上 —— 首次落地、对齐追加、对不上不写。

用户拍板的口径（2026-10-03 原话）见 `core/landing` 的模块文档。本文件钉的是那句
「默认将本地书进行覆盖」在我们这里**具体等于什么文件动作**，以及**绝不允许**发生什么：

1. **同名 ⇒ 同一个 `book_id`**：落地/更新之后书架上**还是那一条**，进度 / 绑定 / 批注
   因此全部保留（绝不新建第二条书目）—— 这条是第 87 期同名判定的直接后果，也是本文件的
   一等公民（每个用例都数一遍 `library.books()` 的长度）。
2. **对齐才追加**：源站目录尾部与本地同序号对上（D 的 5 章窗口规则）才动文件；
   追加走**追更同一函数**（只追加 / 原子写 / 既有条目字节不变 ⇒ index 不漂移）。
3. **对不上一个字都不写**：盘上文件**零改动**，报告里如实写明原因 ——
   宁可报清楚，也不静默把一本书改坏。
4. **留档指向别的源就拒绝**：本地副本是另一个来源下载来的，把两套目录混在一起追加，
   会写出一本前后接不上的书。
5. **定时轮次不整本落地**（`allow_first=False`）：用户没读过的书不该被后台线程悄悄下一本。

书源是桩（零网络），但 EPUB 是**真产物**（`epub_builder` 造、`epub_update` 追加），
所以「既有条目一字不动」拿字节与条目名验，不靠「看起来对」。
"""
import asyncio
import json
import pathlib
import zipfile

import pytest

from novelforge import config
from novelforge.core import (db, epub_builder, fileops, landing, library,
                             watcher as watcher_mod)
from novelforge.sources import REGISTRY, store
from novelforge.sources.base import SourceAdapter
from novelforge.sources.manager import DownloadManager


class _StubClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _rule(name: str = "land-demo", *, mode: str = "toc") -> dict:
    return {"name": name, "display_name": name, "domains": ["d.com"], "public": False,
            "search": {"url": "https://d.com/s?q={title}", "mode": "css", "container": ".i",
                       "fields": {"title": ".t", "url": "a::attr(href)"}},
            "book": {"mode": mode, "toc": {"mode": "css", "container": "a"},
                     "content": {"mode": "css", "container": "#c"}}}


def _install_src(monkeypatch, chapters: list, *, name: str = "land-demo"):
    """装一个**支持在线读**的桩源（落地要用的两件能力：目录 + 正文），返回下载器。

    桩继承 `SourceAdapter`（与 `test_online_read.make_src` 同一手法的简化版）：
    `online_support` / `online_mode` 是 `online.py` 问的两件事，
    `fetch_book_chapters` 是 `download_to` / `update_report` 取整本的唯一入口。
    """

    class _Src(SourceAdapter):
        display_name = f"{name} 展示名"

        def online_support(self) -> str:
            return ""

        def online_mode(self) -> str:
            return "toc"

        def content_may_be_html(self) -> bool:
            return False

        async def chapter_links(self, client, book_url):    # noqa: ANN001, ARG002
            return [{"title": t, "url": f"{book_url}#{i}"}
                    for i, (t, _b) in enumerate(chapters)]

        async def chapter_body(self, client, url):         # noqa: ANN001, ARG002
            return chapters[int(str(url).rsplit("#", 1)[1])][1]

        async def fetch_book_chapters(self, client, item):  # noqa: ANN001, ARG002
            return [{"title": t, "body": b} for t, b in chapters]

        async def search(self, client, title):             # noqa: ANN001, ARG002
            raise AssertionError("落地用例不该搜索")

        async def fetch_book(self, client, item):          # noqa: ANN001, ARG002
            raise AssertionError("这个桩走 fetch_book_chapters")

    _Src.__name__ = f"Stub_{name}"
    monkeypatch.setitem(REGISTRY, name, _Src)
    monkeypatch.setattr(DownloadManager, "_client", lambda self, src: _StubClient())
    return DownloadManager({"download": {"enabled": True}})


def _enable_download(monkeypatch, tmp_path) -> None:
    """让闸门放行（与 `test_online_read._set_download` 同一手法）。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"download": {"enabled": True}})


def _make_book(root: pathlib.Path, stem: str, chapters: int):
    """造一本真 EPUB（`chapters` 章）并返回它的书目条目。`chapters=0` ⇒ 造一个**坏文件**
    （在册、但解析不出任何章节 —— 就是「本地读不了」的现场）。

    ⚠️ 用 `epub_builder` 的默认形态（``nav=True``）：成品 EPUB 的 spine 首条是 nav 目录页
    ⇒ **本地 index 比源站章号大 1**，这正是真机验证里「一本都对不上」的那个坑，
    用例必须长成真实产物的样子（见 `test_online_align` 的位移用例）。
    """
    path = root / f"{stem}.epub"
    if chapters:
        epub_builder.build_epub(
            {"title": stem, "author": "x", "language": "zh"},
            [{"title": f"第 {i} 章", "body_html": f"<p>正文 {i}</p>"}
             for i in range(1, chapters + 1)], str(path))
    else:
        path.write_bytes(b"PK\x03\x04 not a real zip")
    library.invalidate()
    return next(b for b in library.books() if b["name"] == f"{stem}.epub")


def _make_txt_book(root: pathlib.Path, stem: str, chapters: int):
    """造一本**用户自己的** `.txt`（就在书库来源目录里 —— 本项目没碰过它）。

    与 :func:`_make_book` 的区别正是本组用例要证的东西：它的路径**既不是**收书目录里的
    原件、也不是本项目产出的成品 EPUB ⇒ 自动追更改不到它。章名与源站同形（`第 N 章`，
    归一会去空白），所以「对得上」那一步会过，用例才走到「改得到吗」这一问。
    """
    path = root / f"{stem}.txt"
    path.write_text("\n\n".join(f"第{n}章\n正文 {n}" for n in range(1, chapters + 1)),
                    encoding="utf-8")
    library.invalidate()
    return next(b for b in library.books() if b["name"] == f"{stem}.txt")


def _titles(root: pathlib.Path, stem: str) -> list:
    """本地章节标题（含 nav 目录页那条 —— 判「本地读不了」看的正是这张表）。"""
    library.invalidate()
    return [c["title"] for c in landing.local_chapters(
        next(b for b in library.books() if b["name"] == f"{stem}.epub"))]


def _entries(epub: pathlib.Path) -> list:
    with zipfile.ZipFile(epub) as z:
        return z.namelist()


def _bind(book: dict, *, source: str = "land-demo", url: str = "https://d.com/b") -> dict:
    return db.online_bind_put(book["id"], library_id=book["library_id"],
                              source=source, url=url, title=book["title"])


@pytest.fixture
def ctx(tmp_path, monkeypatch, isolated, make_library):  # noqa: ARG001
    """一条真书库 + **隔离的在线缓存根**（`CACHE_DIR` 是会话级的，不隔离会串味）。"""
    root = tmp_path / "landlib"
    make_library("landlib", "落地库", "ebook", root)
    store.add_rule(_rule())
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    return root


def _source_toc(count: int, *, start: int = 1) -> list:
    return [(f"第 {i} 章", f"源站正文 {i}") for i in range(start, start + count)]


# ---------------- 判据：什么时候触发 ----------------

def test_读满5章才触发_且只触发一次():
    """触发门槛（用户口径「在线阅读超过 5 章」）与「只触发一次」两条判据。

    `seen` 是**去重**的（`db.online_bind_mark_seen`），所以「反复翻回第 2 章」刷不过门槛；
    `auto_task` 非空即表示已经触发过 —— 失败也不重试轰炸（重试的依据在任务中心）。
    """
    row = {"seen": [], "auto_task": ""}
    ok, why = landing.should_sync(row)
    assert not ok and f"超过 {landing.SYNC_AFTER} 章" in why

    row["seen"] = list(range(landing.SYNC_AFTER))           # 正好 5 章
    assert not landing.should_sync(row)[0], "「超过 5 章」不含第 5 章本身"

    row["seen"] = list(range(landing.SYNC_AFTER + 1))       # 第 6 章
    assert landing.should_sync(row)[0]

    row["auto_task"] = "t1"
    ok, why = landing.should_sync(row)
    assert not ok and "已经触发过" in why, why
    assert not landing.should_sync(None)[0], "没绑定就没什么可落地的"


def test_对齐认得出本地多一条目录页并给出已落地章数(ctx):        # noqa: ARG001
    """`aligned_tail` 的返回：``(shift, known)``，且 ``known`` 是**源站章号**不是本地条数。

    本地 3 条（nav + 2 章）、源站 4 章 ⇒ 位移 -1、已落地 2 章 —— 追更要照 **2** 追加，
    报 3 就会**少下一章**（而且两边都不报错）。
    """
    _make_book(ctx, "三体", 2)
    local = landing.local_chapters(library.books()[0])
    titles = [t for t, _b in _source_toc(4)]
    assert landing.aligned_tail(titles, local) == (-1, 2)
    assert landing.aligned_tail([f"无关{i}" for i in range(6)], local) is None


# ---------------- E4：对齐 ⇒ 追加 ----------------

def test_对齐就追加新章_同一条书目(ctx, monkeypatch):        # noqa: ARG001
    """**本期核心**：源站多了 2 章 ⇒ 追加到**这本书自己**的 EPUB 末尾。

    三件事一起断言，因为它们一起才等于「用户的进度没错位」：
    ① 书架上**还是那一条**（`book_id` 不变 ⇒ 进度 / 绑定 / 批注全部保留）；
    ② 既有章节条目一字不动，只有新章进包（`zipfile` 条目名集合对比）；
    ③ 留档被写到**收书目录**（`autoupdate.sidecar_of` 那一处拼法），且 `output_dir`
       指向这本书所在的目录、`chapters` 是**源站章号**（追更下次还要靠这两个字段找回来）。
    """
    book = _make_book(ctx, "三体", 2)
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(4))
    old_ids = {b["id"] for b in library.books()}
    old_names = _entries(ctx / "三体.epub")

    rep = asyncio.run(landing.sync(mgr, book, row))

    assert rep["mode"] == "append", rep
    assert rep["added"] == 2, rep
    books = library.books()
    assert len(books) == 1 and {b["id"] for b in books} == old_ids, "就地更新不许多出一条"
    assert {b["name"] for b in books} == {"三体.epub"}
    names = _entries(ctx / "三体.epub")
    assert set(old_names) <= set(names), "既有条目必须还在（index 不漂移）"
    assert sorted(set(names) - set(old_names)) == ["EPUB/c0002.xhtml", "EPUB/c0003.xhtml"]
    assert _titles(ctx, "三体")[-2:] == ["第 3 章", "第 4 章"], "新章要真的读得出来"

    sidecar = pathlib.Path(config.INPUT_DIR) / "三体.meta.json"
    assert sidecar.is_file(), "留档要落在收书目录（原件旁边）"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["source"] == "land-demo" and meta["url"] == "https://d.com/b"
    assert meta["chapters"] == 4, "留档要推进到「本地现在有几章（源站章号）」"
    assert meta["output_dir"] == str(ctx), "output_dir 必须是这本书自己的目录"


def test_源不比本地多就如实说没得追加(ctx, monkeypatch):              # noqa: ARG001
    """源站章数 ≤ 本地已落地 ⇒ **不是**「对不上」，是「没有可追加的章」—— 两句话要分开说。"""
    book = _make_book(ctx, "三体", 3)
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(3))
    before = (ctx / "三体.epub").read_bytes()

    rep = asyncio.run(landing.sync(mgr, book, row))

    assert rep["mode"] == "skip" and "不比本地已落地的 3 章多" in rep["note"], rep
    assert (ctx / "三体.epub").read_bytes() == before


def test_对不上就一个字都不写(ctx, monkeypatch):                       # noqa: ARG001
    """源站换了版 / 目录缺章 ⇒ **盘上文件零改动** + 如实说明 + 指一条明路。

    把新章追加到错位的目录后面，会写出一本前后接不上的书，而进度按**章号**对齐
    ⇒ 读者被送到错的地方。所以这里的正确行为是「什么都不做，但说清楚」。
    """
    book = _make_book(ctx, "三体", 3)
    row = _bind(book)
    mgr = _install_src(monkeypatch, [(f"完全不同的第 {i} 章", "x") for i in range(1, 5)])
    before = (ctx / "三体.epub").read_bytes()
    sidecar = pathlib.Path(config.INPUT_DIR) / "三体.meta.json"

    rep = asyncio.run(landing.sync(mgr, book, row))

    assert rep["mode"] == "skip", rep
    assert "未自动写入" in rep["note"] and "用源站整本覆盖本地" in rep["note"], rep["note"]
    assert (ctx / "三体.epub").read_bytes() == before, "对不上还动文件了"
    assert not sidecar.exists(), "对不上不该留下半份留档"


def test_用户自己导入的书追更改不到_如实拒绝且零写入(ctx, monkeypatch):   # noqa: ARG001
    """**真机验证逮到的假报告**：用户自己导入的书（不在收书目录、也不是本项目的成品）

    追更**根本改不到它** —— `manager._update_report_locked` 只写「收书目录里的原件 txt」
    与「``output_dir`` 下的成品 EPUB」两份，两处都不是这本书。原先照样调下去，于是：
    报告写「对齐后追加了 12 章」，而这本书的字节与执行前**完全一致**，还在收书目录里
    凭空留下一个只有新章的 txt（监听器没登记的话就会被收成第二条书目）。

    正确行为 = :func:`landing.updatable` 先问一句「改得到吗」，问不到就什么都别做。
    """
    book = _make_txt_book(ctx, "三体", 2)                    # 用户自己的 .txt
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(4))
    before = (ctx / "三体.txt").read_bytes()
    before_books = len(library.books())

    rep = asyncio.run(landing.sync(mgr, book, row))

    assert rep["mode"] == "skip", rep
    assert "自动追更只写" in rep["note"] and "用源站整本覆盖本地" in rep["note"], rep["note"]
    assert (ctx / "三体.txt").read_bytes() == before, "用户的原文件被动了"
    assert len(library.books()) == before_books, "不许多出一条书目"
    left = [p.name for p in pathlib.Path(config.INPUT_DIR).iterdir()]
    assert left == [], f"什么都没做，就不该在收书目录里留东西：{left}"


def test_本地原件就在收书目录时照常追加(ctx, monkeypatch, tmp_path, make_library):  # noqa: ARG001
    """判据的另一半：原件 txt **就是**书架上的那一本时（单目录部署 / 只有 txt 产物），

    追更改得到它 ⇒ 照常追加。别把 :func:`landing.updatable` 写成「只认 EPUB」——
    那会让一批本来能自动更新的部署突然什么都不做。
    """
    root = tmp_path / "inputlib"
    make_library("inputlib", "收书目录库", "ebook", root)
    monkeypatch.setattr(config, "INPUT_DIR", root)          # 收书目录 == 书库根
    book = _make_txt_book(root, "三体", 2)
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(4))

    rep = asyncio.run(landing.sync(mgr, book, row))

    assert rep["mode"] == "append" and rep["added"] == 2, rep
    assert "第 4 章" in (root / "三体.txt").read_text(encoding="utf-8")
    assert len(library.books()) == 1, "同一本书，不许多出一条"


def test_留档指向别的源就拒绝写入(ctx, monkeypatch):                    # noqa: ARG001
    """本地这本是**另一个来源**下载来的 ⇒ 不追加，并把这件事说出来。

    （把两套目录混在一起追加会写出一本前后接不上的书；而用户多半只是把「在线读」
    绑到了另一个站上，并不想把本地副本换掉。）
    """
    book = _make_book(ctx, "三体", 3)
    row = _bind(book)
    sidecar = pathlib.Path(config.INPUT_DIR) / "三体.meta.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({"source": "别家源", "url": "https://other/b",
                                   "chapters": 3, "output_dir": str(ctx)}),
                       encoding="utf-8")
    mgr = _install_src(monkeypatch, _source_toc(4))
    before = (ctx / "三体.epub").read_bytes()

    rep = asyncio.run(landing.sync(mgr, book, row))

    assert rep["mode"] == "skip" and "另一个来源" in rep["note"], rep
    assert (ctx / "三体.epub").read_bytes() == before
    assert json.loads(sidecar.read_text(encoding="utf-8"))["source"] == "别家源", \
        "拒绝写入时不许顺手改掉别人的留档"


def test_留档同源同页就沿用它_不重算章数(ctx, monkeypatch):              # noqa: ARG001
    """留档已经指向**同一个源与同一页** ⇒ 原样沿用（那份是权威，追更一直在维护它）。

    重写它等于把权威换成一份我们自己算的近似值 —— 而 `chapters` 一旦算错，
    下次追更就从错误的位置开始（静默丢章 / 重复追加）。
    """
    book = _make_book(ctx, "三体", 2)
    row = _bind(book)
    sidecar = pathlib.Path(config.INPUT_DIR) / "三体.meta.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({"source": "land-demo", "url": "https://d.com/b",
                                   "chapters": 2, "output_dir": str(ctx),
                                   "last_title": "第 2 章"}), encoding="utf-8")
    mgr = _install_src(monkeypatch, _source_toc(3))

    rep = asyncio.run(landing.sync(mgr, book, row))

    assert rep["mode"] == "append" and rep["added"] == 1, rep
    assert len(library.books()) == 1


# ---------------- E3：首次落地 ----------------

def test_首次落地落到这本书自己的名字上(ctx, monkeypatch):              # noqa: ARG001
    """本地读不了 ⇒ 整本抓下来落到**这本书自己的目录与名字**上（同名 ⇒ 同一个 id）。

    落点是**读出来的**（`book["path"]` 的父目录 + `book["name"]`），不是 `resolve_target`
    猜出来的库根 —— 猜错的代价是书架上多一本同名的，而进度还留在旧的那本上。
    暂存目录（`.nfstage-*`）必须收干净：它是「先落到同盘暂存、再原子搬过去」的那一半。
    """
    book = _make_book(ctx, "坏书", 0)
    assert landing.local_chapters(book) == [], "起手就要是「本地读不了」"
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(3))
    old_ids = {b["id"] for b in library.books()}

    rep = asyncio.run(landing.sync(mgr, book, row, allow_first=True))

    assert rep["mode"] == "first", rep
    books = library.books()
    assert len(books) == 1 and {b["id"] for b in books} == old_ids, \
        "落地必须落回**这本书**，不许新建第二条书目"
    assert books[0]["name"] == "坏书.epub"
    assert _titles(ctx, "坏书")[1:] == ["第 1 章", "第 2 章", "第 3 章"], \
        "落地后的成品要真的读得出来（首条是 nav 目录页，见 `_make_book`）"
    assert not list(ctx.glob(".nfstage-*")), "暂存目录要收干净"

    sidecar = pathlib.Path(config.INPUT_DIR) / "坏书.meta.json"
    assert sidecar.is_file()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["output_dir"] == str(ctx) and meta["chapters"] == 3


def test_首次落地到txt书要落txt_不许把EPUB字节塞进txt(ctx, monkeypatch):   # noqa: ARG001
    """**真机验证逮到的名不副实**：本地这本是 `.txt`，而管线产出的是 EPUB。

    照搬原本的「认产物 → 搬到 `book["name"]`」会把 **EPUB 的字节写进 `.txt` 的名字**
    （磁盘上开头就是 ``PK\\x03\\x04``）：扫描器按后缀派阅读器，TXT 阅读器拿 zip 当文本解
    ⇒ 打开是一屏乱码。所以产物形态要跟**这本书自己的后缀**走 —— `.txt` 书取管线的
    源文本原件，其余格式没有对应产物时如实拒绝（另有用例）。
    """
    book = _make_txt_book(ctx, "三体", 0)
    assert landing.local_chapters(book) == [], "起手就要是「本地读不了」"
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(3))
    old_ids = {b["id"] for b in library.books()}

    rep = asyncio.run(landing.sync(mgr, book, row, allow_first=True))

    assert rep["mode"] == "first", rep
    data = (ctx / "三体.txt").read_bytes()
    assert not data.startswith(b"PK"), "把 EPUB 的字节写进了 .txt（打开就是乱码）"
    assert "源站正文 3" in data.decode("utf-8"), "落的要是源站那本书的内容"
    books = library.books()
    assert len(books) == 1 and {b["id"] for b in books} == old_ids, \
        "落地必须落回**这本书**（同名含后缀 ⇒ 同一个 id）"
    assert [c["title"] for c in landing.local_chapters(books[0])] == \
        ["第 1 章", "第 2 章", "第 3 章"], "落地后的 txt 要真的读得出来"

    sidecar = pathlib.Path(config.INPUT_DIR) / "三体.meta.json"
    assert sidecar.is_file() and (pathlib.Path(config.INPUT_DIR) / "三体.txt").is_file(), \
        "留档（原件 txt + sidecar）要落在收书目录 —— 追更下次靠它找回来"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["output_dir"] == str(ctx)


def test_首次落地覆盖前先把原文件移入回收站(ctx, monkeypatch):            # noqa: ARG001
    """**覆盖是可撤销的**（第 96 期）：盖到这本书自己头上之前，旧的那一份先进回收站。

    这是本模块唯一会盖到用户文件的地方 —— 此前盖掉就没了（第 95 期审计批次 8 的真缺口
    不是「没二次确认」，而是「不可撤销」）。钉三件事：旧字节完整留在回收站、台账记下原路径、
    报告如实说明「已移入回收站」。
    """
    book = _make_book(ctx, "坏书", 0)               # ctx/坏书.epub = 坏字节（本地读不了）
    before = (ctx / "坏书.epub").read_bytes()
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(3))

    rep = asyncio.run(landing.sync(mgr, book, row, allow_first=True))

    assert rep["mode"] == "first", rep
    recycled = [q for q in fileops.recycle_dir().iterdir() if q.is_file()]
    assert len(recycled) == 1 and recycled[0].read_bytes() == before, \
        "被替换的那一份必须逐字节躺在回收站里"
    rows = db.recycle_list()
    assert len(rows) == 1 and rows[0]["orig_path"] == str(ctx / "坏书.epub")
    assert "回收站" in rep["detail"], rep
    assert len(library.books()) == 1, "留档不影响「绝不新建第二条书目」"


def test_首次落地到txt书_两份落点都先留档(ctx, monkeypatch):             # noqa: ARG001
    """txt 书的**两个**落点（书库内 `dest` + 收书目录留档 `txt_dest`）都可能已有旧内容 ⇒ 都先回收。"""
    book = _make_txt_book(ctx, "三体", 0)
    assert landing.local_chapters(book) == [], "起手就要是「本地读不了」"
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(2))
    input_txt = pathlib.Path(config.INPUT_DIR) / "三体.txt"
    input_txt.parent.mkdir(parents=True, exist_ok=True)
    input_txt.write_text("旧的留档", encoding="utf-8")

    rep = asyncio.run(landing.sync(mgr, book, row, allow_first=True))

    assert rep["mode"] == "first", rep
    blobs = sorted(q.read_bytes() for q in fileops.recycle_dir().iterdir() if q.is_file())
    assert blobs == [b"", "旧的留档".encode("utf-8")], \
        f"书库内那份（空文件）与收书目录那份（旧留档）都要留档，实得 {blobs}"
    assert len(db.recycle_list()) == 2


def test_覆盖前回收失败就中止_盘上零改动(ctx, monkeypatch):              # noqa: ARG001
    """移不动就**如实拒绝**：宁可这次不落地，也不做一次不可撤销的覆盖。"""
    book = _make_book(ctx, "坏书", 0)
    before = (ctx / "坏书.epub").read_bytes()
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(2))

    def _boom(*a, **k):
        raise OSError("回收目录写不进去")

    monkeypatch.setattr(landing.publish, "recycle", _boom)
    rep = asyncio.run(landing.sync(mgr, book, row, allow_first=True))

    assert rep["mode"] == "skip" and "回收站失败" in rep["note"], rep
    assert (ctx / "坏书.epub").read_bytes() == before, "盘上必须零改动"
    assert not list(ctx.glob(".nfstage-*")), "暂存目录仍要收干净（finally 那一步）"


def test_落地写的留档txt要登记为已处理(ctx, monkeypatch):                # noqa: ARG001
    """落地写在**被监听**的收书目录里，不登记就会被监听线程当成新文件再收一次
    ⇒ 书架上多出一本 `<名>.txt`（正是「绝不新建第二条书目」要避免的事）。

    这里用假监听器钉住「登记了**那一个**文件」：`_run_download` 用的是
    `mark_recent(30, ".txt")`（把最近 30 秒里所有 txt 都盖掉）—— 落地知道确切名字，
    就只该盖那一份（同一时间窗里用户自己丢进来的文件不该被顺手跳过）。
    """
    calls: list = []

    class _FakeWatcher:
        def mark_processed(self, path):
            calls.append(pathlib.Path(path))

    monkeypatch.setattr(watcher_mod, "_current", _FakeWatcher())
    book = _make_book(ctx, "坏书", 0)
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(2))

    rep = asyncio.run(landing.sync(mgr, book, row, allow_first=True))

    assert rep["mode"] == "first", rep
    assert calls == [pathlib.Path(config.INPUT_DIR) / "坏书.txt"], calls


def test_定时轮次不整本落地(ctx, monkeypatch):                          # noqa: ARG001
    """`allow_first=False` ⇒ 本地读不了时**只说明、不下载**（定时线程不替用户下书）。"""
    book = _make_book(ctx, "坏书", 0)
    row = _bind(book)
    mgr = _install_src(monkeypatch, _source_toc(1))
    before = (ctx / "坏书.epub").read_bytes()

    rep = asyncio.run(landing.sync(mgr, book, row, allow_first=False))

    assert rep["mode"] == "skip" and "读满" in rep["note"], rep
    assert (ctx / "坏书.epub").read_bytes() == before
    assert not (pathlib.Path(config.INPUT_DIR) / "坏书.meta.json").exists()


def test_整本覆盖会重写第一章的内容(ctx, monkeypatch):                   # noqa: ARG001
    """`overwrite=True`（用户显式动作）⇒ 无视本地内容，整本按源站那一版重来。

    代价写在明处：章节结构变了，进度按**章号**重新对齐。默认路径**永不**走这里。
    """
    book = _make_book(ctx, "三体", 3)
    row = _bind(book)
    mgr = _install_src(monkeypatch, [("源站第 1 章", "全新内容 A"), ("源站第 2 章", "全新内容 B")])

    rep = asyncio.run(landing.sync(mgr, book, row, overwrite=True))

    assert rep["mode"] == "first", rep
    assert _titles(ctx, "三体")[1:] == ["源站第 1 章", "源站第 2 章"]
    assert len(library.books()) == 1
    # 第 96 期：显式覆盖同样**先留档**（这本本来是能读的 3 章，不是「本地读不了」）
    recycled = [q.read_bytes() for q in fileops.recycle_dir().iterdir() if q.is_file()]
    assert len(recycled) == 1 and recycled[0].startswith(b"PK\x03\x04"), \
        "被覆盖掉的那本 EPUB 要先躺进回收站"
    assert "覆盖" in rep["detail"] and "回收站" in rep["detail"], rep["detail"]


def test_漫画与有声本期不自动落地(ctx):
    """`kind != "text"` ⇒ 如实说明「本期只支持文本」，**不猜、不下错东西**。"""
    store.add_rule(_rule("comic-demo", mode="comic"))
    book = _make_book(ctx, "三体", 2)
    row = _bind(book, source="comic-demo")
    before = (ctx / "三体.epub").read_bytes()

    rep = asyncio.run(landing.sync(None, book, row))

    assert rep["mode"] == "skip" and "漫画" in rep["note"], rep
    assert (ctx / "三体.epub").read_bytes() == before


# ---------------- E5：接口「检查更新」 ----------------

def test_检查更新_未知书报404(client, auth_headers):
    r = client.post("/api/books/nope/check-update", headers=auth_headers, json={})
    assert r.status_code == 404, r.text


def test_检查更新_两者都没有就如实说明(client, auth_headers, ctx,       # noqa: ARG001
                                              monkeypatch, tmp_path):
    """既没有留档、也没有绑定 ⇒ 400 + 告诉他该干什么（不建一个注定失败的任务）。"""
    _enable_download(monkeypatch, tmp_path)
    book = _make_book(ctx, "三体", 2)
    r = client.post(f"/api/books/{book['id']}/check-update", headers=auth_headers, json={})
    assert r.status_code == 400, r.text
    assert "在线阅读" in r.json()["detail"], r.json()
    assert db.task_list(limit=5) == [] or not db.task_list(limit=5), "不许留下空任务"


def test_检查更新_闸门关着就400并原文照给(client, auth_headers, ctx,       # noqa: ARG001
                                                  monkeypatch, tmp_path):
    """闸门唯一（`gate_reason()`），文案逐字来自它 —— 与 `/api/download` 同一口径。

    ⚠️ 顺序是刻意的：**先问闸门**再问「有没有源」—— 下载关着的时候，用户该做的事是
    去设置里打开（而不是去绑书源），所以先告诉他更外层的那条。
    """
    book = _make_book(ctx, "三体", 2)
    _bind(book)
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"download": {"enabled": False}})

    r = client.post(f"/api/books/{book['id']}/check-update", headers=auth_headers, json={})

    assert r.status_code == 400, r.text
    assert "下载功能未开启" in r.json()["detail"], r.json()


def test_检查更新_绑了源就起后台任务(client, auth_headers, ctx,          # noqa: ARG001
                                            monkeypatch, tmp_path):
    """闸门与源都齐 ⇒ 建任务并返回 task_id（报告写进任务行，**不占着请求等外呼**）。"""
    _enable_download(monkeypatch, tmp_path)
    book = _make_book(ctx, "三体", 2)
    _bind(book)
    _install_src(monkeypatch, _source_toc(4))

    r = client.post(f"/api/books/{book['id']}/check-update", headers=auth_headers, json={})

    assert r.status_code == 200, r.text
    tid = r.json()["task_id"]
    assert tid and r.json()["source"] == "land-demo"
    task = db.task_get(tid)
    assert task and task["type"] == "check-update" and task["title"] == book["title"], task


# ---------------- E3 的触发：读满 6 章自动落地，且只触发一次 ----------------

def _read_chapter(client, headers, bid, index):
    return client.get(f"/api/books/{bid}/online/chapter/{index}", headers=headers)


def test_读满六章自动起落地任务且只触发一次(client, auth_headers, ctx,   # noqa: ARG001
                                                    monkeypatch, tmp_path):
    """在线阅读的**触发点**：`seen` 超过 5 章 ⇒ 起一个 `online-land` 任务并记 `auto_task`。

    之后继续读第 7、8 章**不再起第二个**（`auto_task` 就是那份凭据）——
    否则同一本书会被反复下一次（而且失败还会重试轰炸）。
    """
    _enable_download(monkeypatch, tmp_path)
    book = _make_book(ctx, "坏书", 0)          # 本地读不了 = 「读前 5 章时本地还没有书」
    _bind(book)
    _install_src(monkeypatch, _source_toc(9))

    for i in range(landing.SYNC_AFTER):
        r = _read_chapter(client, auth_headers, book["id"], i)
        assert r.status_code == 200, r.text
        assert not db.online_bind_get(book["id"])["auto_task"], "5 章（含）以内不该触发"

    r = _read_chapter(client, auth_headers, book["id"], landing.SYNC_AFTER)
    assert r.status_code == 200, r.text
    tid = db.online_bind_get(book["id"])["auto_task"]
    assert tid, "第 6 章读过了就该触发"
    task = db.task_get(tid)
    assert task and task["type"] == "online-land" and "自动落地" in (task["detail"] or ""), task

    _read_chapter(client, auth_headers, book["id"], landing.SYNC_AFTER + 1)
    _read_chapter(client, auth_headers, book["id"], landing.SYNC_AFTER + 2)
    assert db.online_bind_get(book["id"])["auto_task"] == tid, "只许触发一次"


def test_定时轮次对绑定书用绑定驱动更新且不整本落地(ctx, monkeypatch, tmp_path):
    """`autoupdate.candidates()` 要把**只有绑定**的书也列进来（用户要的「书源自动搜更新」）。

    但它走的是 `landing.sync(allow_first=False)`：本地读不了时只报「没到门槛」，
    **不替用户下一本**（用户没读过的书不该被后台线程悄悄下）。
    """
    from novelforge.core import autoupdate
    book = _make_book(ctx, "三体", 2)
    _bind(book)
    _install_src(monkeypatch, _source_toc(4))

    mine = [c for c in autoupdate.candidates() if c["book"]["id"] == book["id"]]
    assert [c["kind"] for c in mine] == ["binding"], mine
    assert mine[0]["row"]["source"] == "land-demo"

    # 本地读不了的那本**不该被这一轮**整本下下来（`allow_first=False`）：
    # 触发器只有「用户自己读满 5 章」那一处。
    broken = _make_book(ctx, "坏书", 0)
    _bind(broken)
    _enable_download(monkeypatch, tmp_path)
    before = (ctx / "坏书.epub").read_bytes()

    rep = autoupdate.tick()

    assert rep["total"] == 2, rep
    assert rep["added"] == 2, rep                     # 三体：对齐后追加源站多的那 2 章
    assert (ctx / "坏书.epub").read_bytes() == before, "定时轮次不许整本落地"
    assert not pathlib.Path(config.INPUT_DIR, "坏书.meta.json").exists()
    assert any("坏书" in n and "读满" in n for n in rep.get("notes") or []), rep
    library.invalidate()
    assert len(library.books()) == 2, "不许凭空多出书目"

    # 追更写下的留档让这本书**只走追更**：两套机制对同一本书各跑一遍会把同一批新章
    # 追加两次（而且两边都报成功）。
    mine = [c for c in autoupdate.candidates() if c["book"]["id"] == book["id"]]
    assert [c["kind"] for c in mine] == ["sidecar"], "有留档又有绑定不许列出两条"
