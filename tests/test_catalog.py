"""书目索引（第 62 期）：``catalog`` 与「全量扫盘」**逐字段对拍** + 增量语义。

这个文件存在的理由只有一个：**索引化的书目必须与扫盘算出来的逐字段一致**。

「索引」天然会漂移 —— 它存的是一份副本，而副本总有一天会与真相分家。分家的
后果不是报错，是**静默的错数据**：书的页数停在昨天、作者的改名没生效、
一本书从列表里凭空消失。所以这里不去断言「索引里有什么」，而是拿
``library._scan_once``（改造前的唯一实现，改造后仍是「正确」的定义，
只是不再挂在请求路径上）当基准做**对拍**：同一份磁盘状态，两条链路必须给出
一模一样的书。

第二条主线是**增量判据**（``(size, mtime)`` 闸门）。它一旦失效就退化成
「每轮全量重探」，也就是把线上那 42 秒原样搬回来 —— 而且**功能上完全正常**，
只是慢，任何功能用例都测不出来。所以这里用「把探测函数换成会爆炸的桩」来证明
「没变就真的没探」：这是唯一能在功能测试里钉住「没有做某件昂贵的事」的手法。
"""
import json
import pathlib

import pytest

from novelforge.core import catalog, db, epub_builder, library


def _build_epub(root, rel: str, title: str = "三体", author: str = "刘慈欣") -> pathlib.Path:
    """造一个**真 EPUB**（元数据要读真实 OPF，占位字节串会让探测走 unparsable 分支）。"""
    p = pathlib.Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": author, "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(p),
    )
    return p


def _put(root, rel: str, data: bytes = b"x") -> pathlib.Path:
    p = pathlib.Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture
def cat_lib(isolated, tmp_path, make_library):  # noqa: ARG001 —— isolated 负责切目录
    """一个就地库（混合类型，收全格式）+ 根目录路径。"""
    root = tmp_path / "root"
    lib = make_library("cat", "索引库", "mixed", root, source_subdir="cat")
    return lib, root


def _pairs(bs: list) -> dict:
    """按 id 建索引，便于逐字段比对（顺序另测）。"""
    return {b["id"]: b for b in bs}


def _assert_same(reference: list, indexed: list) -> None:
    """**逐字段**比对两份书目。字段集与值都必须一致，顺序也一致。

    逐字段而不是整体 ``==``：整体相等只告诉你「有地方不一样」，而这里的失败
    几乎总是「某一列忘了存 / 忘了读回」—— 报出**哪个字段、哪本书**能一眼定位。
    """
    assert [b["id"] for b in reference] == [b["id"] for b in indexed], \
        "书目顺序变了（顺序是 BookIdConflict 的「保留项」判据，不能随便动）"
    r, i = _pairs(reference), _pairs(indexed)
    assert set(r) == set(i), f"书目集合不一致：仅扫盘有 {set(r) - set(i)}，仅索引有 {set(i) - set(r)}"
    for bid in r:
        a, b = r[bid], i[bid]
        assert set(a) == set(b), f"{a['name']} 的字段集不一致：{set(a) ^ set(b)}"
        for k in a:
            assert a[k] == b[k], f"{a['name']} 的 {k} 不一致：扫盘={a[k]!r} 索引={b[k]!r}"


# ---------------------------------------------------------------------------
# 对拍：索引 == 扫盘
# ---------------------------------------------------------------------------

def test_索引与全量扫盘逐字段一致(cat_lib):
    """**本文件的核心用例**：各种形态的条目各来一份，两条链路必须给出同一份书目。

    刻意把「每种条目类型」都放一份：EPUB（真 OPF 元数据）、解析不了的假 EPUB
    （unparsable + no-cover）、CBZ（pages_source=archive）、零字节文件
    （zero-bytes）、带封面与多轨的音频目录（体积/轨数/演播者都走另一条分支）、
    系列子目录（Komga 布局，name 含 `/`）、被排除的文件。
    """
    lib, root = cat_lib
    _build_epub(root, "三体.epub", title="三体", author="刘慈欣")
    # 系列目录（name 形如 "银河系/基地.epub"）+ 系列序号写在 OPF 里由 _series_of 解析
    _build_epub(root, "银河系/基地.epub", title="基地", author="阿西莫夫")
    _put(root, "假书.epub", b"EPUB")                 # 打不开 ⇒ unparsable
    _put(root, "零字节.epub", b"")                   # 0 字节 ⇒ zero-bytes
    _put(root, "漫画.cbz", b"not-a-real-zip")        # 归档探测失败但条目仍在
    _put(root, "说明.txt", "纯文本".encode("utf-8"))
    _put(root, "文档.pdf", b"%PDF-1.4")
    # 音频目录：两轨 + 封面（封面让它多一个 has_cover 分支）
    _put(root, "有声书/01.mp3", b"ID3" + b"\x00" * 64)
    _put(root, "有声书/02.mp3", b"ID3" + b"\x00" * 32)
    _put(root, "有声书/cover.jpg", b"\xff\xd8\xff" + b"\x00" * 2048)
    # 隐藏文件与排除图案都不该进书目（_iter_book_entries 与索引必须同源）
    _put(root, ".隐藏.epub", b"x")
    _put(root, "草稿.draft.epub", b"x")
    db.update_library(lib["id"], exclude='["*.draft.*"]')

    reference = library._scan_once(db.get_library(lib["id"]))
    assert len(reference) >= 9, f"基准本身就不对，用例没在测它想测的东西：{len(reference)}"

    # 走索引（第一次读 = 冷启动，catalog 会同步扫一遍）
    indexed = library.books(lib["id"])
    _assert_same(reference, indexed)


def test_多文件夹库的两个根都进索引(isolated, tmp_path, make_library):  # noqa: ARG001
    """一个库可以持有多个来源文件夹（第 41 期）—— 两个根的书都要在，顺序按根序。"""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    lib = make_library("multi", "多根库", "mixed", a)
    _build_epub(a, "甲.epub", title="甲")
    _build_epub(b, "乙.epub", title="乙")
    # ⚠️ 必须走 json.dumps，**不能**手写 f'["{a}", "{b}"]' —— Windows 路径里的反斜杠
    # 在 JSON 里是转义符（`\U` 直接非法），手写的那个字符串 `roots_of` 解析不出任何根，
    # 库会安静地变成「空库」，用例只会看到一份空书目而看不出是路径写坏了。
    db.update_library(lib["id"], source_dirs=json.dumps([str(a), str(b)], ensure_ascii=False))
    lib = db.get_library(lib["id"])

    indexed = library.books(lib["id"])
    assert [x["name"] for x in indexed] == ["甲.epub", "乙.epub"]
    _assert_same(library._scan_once(lib), indexed)


def test_顺序在父目录与同名文件共存时也对得上(cat_lib):
    """``abc/`` 与 ``abc.epub`` 共存 —— 顺序必须与 ``_iter_book_entries`` 完全一致。

    ⚠️ 这条盯的是一个**很容易写错**的地方：遍历顺序是「先序遍历」（``sorted(iterdir)``
    排的是整条绝对路径，子条目紧跟在父目录之后），按 ``rel`` **整串**比较则会把
    ``abc.epub`` 排在 ``abc/x.epub`` 前面（``.``=0x2E < ``/``=0x2F）。
    顺序不是纯粹的美观问题：``id_conflicts`` 把每组第一条当**保留项**，
    顺序变了「一键改名」改掉的就是另一本。所以判据是分段比较，不是整串比较。
    """
    lib, root = cat_lib
    _build_epub(root, "abc/内页.epub", title="内页")
    _build_epub(root, "abc.epub", title="外层")
    _build_epub(root, "abd.epub", title="后继")
    ref = library._scan_once(db.get_library(lib["id"]))
    assert [b["name"] for b in ref] == ["abc/内页.epub", "abc.epub", "abd.epub"], \
        "基准顺序与预期不符，说明 _iter_book_entries 的遍历语义变了"
    assert [b["name"] for b in library.books(lib["id"])] == [b["name"] for b in ref]


def test_同库两个根下的同名书不合并_仍然报冲突(isolated, tmp_path, make_library):  # noqa: ARG001
    """⚠️ 索引主键是 ``(library_id, root, rel)`` 而**不是** ``(library_id, rel)``。

    两个来源文件夹下各有一本 ``三体.epub`` ⇒ 同一个 ``book_id`` 命中两本，
    ``by_id`` 必须抛 ``BookIdConflict``（进度 / 批注只有一份，取错书比报错糟得多）。
    用 ``(library_id, rel)`` 当主键会把这两本**静默合并成一本**，冲突从此消失。
    """
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    lib = make_library("dup", "同根库", "mixed", a)
    _build_epub(a, "三体.epub")
    _build_epub(b, "三体.epub")
    db.update_library(lib["id"], source_dirs=json.dumps([str(a), str(b)], ensure_ascii=False))

    assert len(library.books(lib["id"])) == 2, "两个根下的同名书都必须留在书目里"
    with pytest.raises(library.BookIdConflict):
        library.by_id(library.book_id("三体.epub", "dup"))


# ---------------------------------------------------------------------------
# 增量判据：没变就**不许**重探
# ---------------------------------------------------------------------------

def test_没变化时不重探任何条目(cat_lib, monkeypatch):
    """把探测函数换成**会爆炸的桩**：第二次刷新若还去探，用例就红。

    这是唯一能在功能测试里钉住「没有做某件昂贵的事」的手法 —— 增量闸门失效
    （比如判据算错、或 force 传成了 True）时，功能上一切正常，只是每轮把
    266 次开 zip 全做一遍，也就是线上那 42 秒原样搬回来。没有任何断言看得出来。
    """
    lib, root = cat_lib
    for i in range(5):
        _build_epub(root, f"书{i}.epub", title=f"书{i}")
    lib = db.get_library(lib["id"])
    first = catalog.refresh_library(lib, force=True)
    assert first["added"] == 5 and first["unchanged"] == 0

    def _boom(*a, **kw):                       # pragma: no cover —— 被调到就是失败
        raise AssertionError("条目没变却重新探测了：增量闸门失效")

    monkeypatch.setattr(library, "probe_epub", _boom)
    monkeypatch.setattr(library, "_probe_entry", _boom)

    again = catalog.refresh_library(lib)
    assert again["unchanged"] == 5
    assert again["added"] == 0 and again["removed"] == 0


def test_增量刷新每文件只问一次文件系统(cat_lib, monkeypatch):
    """每文件 1 次 stat —— 拿**计数**钉住，因为这一条在本机怎么改都是绿的。

    第 62 期实测（300 本的书库）：增量刷新改造前对书库目录发 903 次 syscall
    （每文件 3 次：``is_file`` + ``stat`` + ``is_dir``），改后 304 次（每文件 1 次）。
    线上 42.4s ÷ 266 本 ≈ 158ms/本 反推每次 syscall 都在付毫秒级往返 —— 3 次与 1 次
    在那边就是一倍的时间差；而本机 SSD 上两者都是几十毫秒，上面那些功能用例一条都不红。
    所以这里与「不重探」那条同样手法：钉住「**没有**做某件昂贵的事」。

    只数 ``Path.stat``：``Path.is_file()`` / ``Path.is_dir()`` 内部走的也是它，
    所以退回「每文件问三遍」的写法会让计数直接翻三倍。
    """
    lib, root = cat_lib
    for i in range(5):
        _put(root, f"书{i}.epub", b"EPUB")
    lib = db.get_library(lib["id"])
    catalog.refresh_library(lib, force=True)           # 先建索引，这一轮不计入

    hits: list = []
    root_s = str(pathlib.Path(root).resolve())
    real_stat = pathlib.Path.stat

    def counting_stat(self, *a, **kw):
        if str(self).startswith(root_s):
            hits.append(str(self))
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "stat", counting_stat)
    out = catalog.refresh_library(lib)                 # unchanged 的那一轮 = 线上每 60 秒走的路
    assert out["unchanged"] == 5

    # 5 本各 1 次，外加库根解析之类的常数几次。留常数余量，但**不留**「每文件多一次」的余量。
    assert len(hits) <= 8, f"增量刷新问了 {len(hits)} 次文件系统（目标每文件 1 次）：{hits}"


def test_内容变了才重探并更新索引(cat_lib):
    """改一个字节 + 换 mtime ⇒ 那一本要重探并覆盖索引行（``ON CONFLICT DO UPDATE``）。"""
    lib, root = cat_lib
    p = _build_epub(root, "甲.epub", title="旧名")
    _build_epub(root, "乙.epub", title="乙")
    lib = db.get_library(lib["id"])
    catalog.refresh_library(lib, force=True)
    assert _pairs(library.books(lib["id"]))[library.book_id("甲.epub", "cat")]["title"] == "旧名"

    # 换一本**内容不同**的同名 EPUB（体积与 mtime 都会变）
    p.unlink()
    _build_epub(root, "甲.epub", title="新名", author="新作者")
    out = catalog.refresh_library(lib)
    assert out["added"] == 1 and out["unchanged"] == 1
    b = _pairs(library.books(lib["id"]))[library.book_id("甲.epub", "cat")]
    assert b["title"] == "新名" and b["author"] == "新作者"


def test_文件没了索引行跟着删(cat_lib):
    """磁盘上删掉 ⇒ 索引行删除（不删的话书目会永远多一本已经不在的书）。"""
    lib, root = cat_lib
    _put(root, "要删.epub", b"EPUB")
    _put(root, "留下.epub", b"EPUB")
    lib = db.get_library(lib["id"])
    catalog.refresh_library(lib, force=True)
    assert len(library.books(lib["id"])) == 2

    (pathlib.Path(root) / "要删.epub").unlink()
    out = catalog.refresh_library(lib)
    assert out["removed"] == 1
    assert [b["name"] for b in library.books(lib["id"])] == ["留下.epub"]


def test_标脏后的读会看到新书(cat_lib):
    """``library.invalidate()`` = 标脏 ⇒ 下一次读**同步**增量刷一次。

    这条语义是全仓 20 多处写操作之后 ``library.invalidate()`` 的依据 ——
    改成「只标脏、等后台」的话，界面上就会短暂显示旧书目，而那些调用点的
    注释与用例都建立在「下一次读必然是新状态」上。
    """
    lib, root = cat_lib
    _put(root, "第一本.epub", b"EPUB")
    assert [b["name"] for b in library.books(lib["id"])] == ["第一本.epub"]

    _put(root, "第二本.epub", b"EPUB")
    library.invalidate(lib["id"])
    assert sorted(b["name"] for b in library.books(lib["id"])) == ["第一本.epub", "第二本.epub"]


def test_不标脏时读不会看到新书(cat_lib):
    """反向钉住上一条：**没有**标脏时读索引、不扫盘 —— 这正是 42 秒的消失方式。

    没有这条，把 ``invalidate`` 改成「每次都全量重扫」也能让上一条通过 ——
    而那正好是本期要消掉的行为。
    """
    lib, root = cat_lib
    _put(root, "第一本.epub", b"EPUB")
    assert len(library.books(lib["id"])) == 1

    _put(root, "偷偷加的.epub", b"EPUB")     # 不调 invalidate（模拟后台线程的视角）
    assert len(library.books(lib["id"])) == 1, "没有标脏却扫了盘：索引白建了"


# ---------------------------------------------------------------------------
# 读路径的几个入口
# ---------------------------------------------------------------------------

def test_by_id走索引且语义不变(cat_lib):
    lib, root = cat_lib
    _build_epub(root, "三体.epub", title="三体")
    bid = library.book_id("三体.epub", "cat")
    b = library.by_id(bid)
    assert b and b["title"] == "三体" and b["name"] == "三体.epub"
    assert library.by_id("不存在的id") is None


def test_by_id自己会把索引刷到不脏(cat_lib):
    """``by_id`` 必须自己 ``_settle`` —— 「标脏 → 立刻按 id 读」是全仓的一条固定链路。

    ``fileops`` / 改名 / 上传封面 / 改元数据全是 ``library.invalidate()`` 紧接着
    ``library.by_id(bid)`` 取改完的结果（server.py 里多处 ``fresh = library.by_id(bid)``）。
    少了这一步，冷启动时按 id 的接口一律 404，而「改完立刻读」会读到**旧行** ——
    界面表现是「改完没反应」，而不是报错，所以功能用例【必须】单独钉住它。

    这条用例把「直接读 by_id」放在标脏之后的**第一次读**，不先读 ``books()`` ——
    先读 books 会把索引刷好，掩盖掉 by_id 自己不 settle 的事实。
    """
    lib, root = cat_lib
    _build_epub(root, "三体.epub", title="旧名")
    bid = library.book_id("三体.epub", "cat")
    assert library.by_id(bid) is not None          # 冷启动：by_id 得自己把索引建起来

    _build_epub(root, "三体.epub", title="新名")   # 换内容（体积/mtime 都变）
    library.invalidate(lib["id"])
    assert library.by_id(bid)["title"] == "新名", "标脏后 by_id 读到了旧行"


def test_by_id不返回已移除登记的库里的书(cat_lib):
    """索引是缓存、库表才是真相源 —— 库被删了它在索引里的行不该还能取到。"""
    lib, root = cat_lib
    _build_epub(root, "三体.epub")
    bid = library.book_id("三体.epub", "cat")
    assert library.by_id(bid) is not None

    db.delete_library("cat")
    assert library.by_id(bid) is None


def test_counts与书目长度一致(cat_lib):
    lib, root = cat_lib
    for i in range(3):
        _put(root, f"书{i}.epub", b"EPUB")
    _put(root, "另一库.epub", b"EPUB")
    other = cat_lib[0]
    assert catalog.counts().get("cat") == 4
    assert catalog.counts().get("cat") == len(library.books("cat"))
    assert other["id"] == "cat"          # 夹具只建了一个库，这里只是把关系写清楚


def test_空库也能建索引且不会反复重试(cat_lib):
    """没有来源文件夹的库（空库）要被标成「已就绪」 —— 否则每次读都试一遍全量刷新。"""
    lib, root = cat_lib
    db.update_library(lib["id"], source_dirs="[]")
    assert library.books(lib["id"]) == []
    assert library.books(lib["id"]) == []          # 第二次同样安静
    assert catalog.counts().get("cat", 0) == 0


def test_forget清掉某库的索引行(cat_lib):
    """``forget`` = 删行 + 忘掉「已就绪」，库里**还在册**时下一次读会重新扫出来。

    真实调用点只有一处：库被删掉登记之后（server 的删除书库分支）。那时库已不在
    ``libraries()`` 里，``books`` / ``by_id`` 都按「仍登记在册」过滤，这些行再也不会
    被读到 —— ``forget`` 是为了**不留下无主垃圾行**，不是为了把书藏起来。
    所以「同 id 的库重新登记 ⇒ 重新扫出来」是正确行为（删了再建同一个 id 很常见），
    这条用例把它写清楚，免得后人把它当 bug「修」成永久黑名单。
    """
    lib, root = cat_lib
    _put(root, "书.epub", b"EPUB")
    assert library.books(lib["id"])

    def _rows() -> int:
        # 直接查表：`counts()` / `books()` 都会顺手 `_settle` 重扫一遍，
        # 拿它们观察「删没删掉」会被重扫盖过去，只能直接看表。
        return int(catalog._exec(
            f"SELECT COUNT(*) AS n FROM {catalog.TABLE} WHERE library_id=?",
            ("cat",)).fetchone()["n"])

    assert _rows() == 1, "用例前提不成立：索引里本来就没有这一行"
    catalog.forget("cat")
    assert _rows() == 0, "forget 没删掉索引行（无主垃圾行会一直留在表里）"

    # 同 id 重新登记 ⇒ 重新扫出来。删了再建同一个 id 很常见，forget 不能是永久黑名单
    assert [b["name"] for b in library.books(lib["id"])] == ["书.epub"]


# ---------------------------------------------------------------------------
# 服务端元数据覆盖层（第 17 期 T3）—— 索引路径**也必须**过这一层
# ---------------------------------------------------------------------------

def test_服务端元数据在索引路径上照常生效(cat_lib):
    """改造前这一层挂在 ``_scan_once`` 的末尾；索引化之后它必须在**读取**时生效。

    漏了它的后果很隐蔽：文件里的书名照常显示，用户在设置里改过的书名 / 抓回来的
    简介却「改完没反应」—— 而详情页（走 metastore）显示的是新值，两处对不上。
    """
    lib, root = cat_lib
    _build_epub(root, "三体.epub", title="文件里的书名")
    bid = library.book_id("三体.epub", "cat")
    assert library.by_id(bid)["title"] == "文件里的书名"

    db.set_override(bid, "title", "服务端的书名")
    b = library.by_id(bid)
    assert b["title"] == "服务端的书名", "索引路径没过元数据覆盖层"
    assert _pairs(library.books(lib["id"]))[bid]["title"] == "服务端的书名"


def test_服务端封面撤掉no_cover(cat_lib):
    """扫描期判定的 ``no-cover`` 在服务端有封面时必须撤掉（第 17 期的既有口径）。

    ``issues`` **刻意不入库**：它的 ``no-cover`` 一条取决于「服务端有没有封面」，
    而那是会变的（用户随时能上传封面）。存进索引就会在用户上传封面之后
    一直显示「缺封面」。所以索引里存的是判据（unparsable / has_cover / size /
    是否目录），``issues`` 在读取时现算 —— 这条用例钉住这个分工。
    """
    lib, root = cat_lib
    # 真 EPUB 且不带封面 ⇒ 能解析、但没有封面 ⇒ 扫描期判 no-cover
    _build_epub(root, "缺封面.epub")
    bid = library.book_id("缺封面.epub", "cat")
    b = _pairs(library.books(lib["id"]))[bid]
    assert not b["has_cover"], "用例前提不成立：这本应当判为没有封面"
    assert "no-cover" in b["issues"], f"扫描期应判 no-cover，实际 {b['issues']}"

    db.set_cover(bid, b"\xff\xd8\xff" + b"\x00" * 16)
    b2 = _pairs(library.books(lib["id"]))[bid]
    assert b2["has_cover"] is True and "no-cover" not in b2["issues"]
