"""序号单元的**扫描链路**（第 73 期）：枚举 / 探测 / 增量闸门 / 索引自愈 / 搬家判据。

判据本体（`units.parse_unit` / `is_unit_dir` / `shape_of`）在 ``tests/test_units.py``；
这里只钉「链路有没有接对」——同一棵树放进不同类型的库、放进索引、搬去另一个库，
书架上的结果必须一致，而且**改口径之后存量索引要能自愈**。

链路侧最要紧的两条（都曾经是静默缺陷）：

1. **增量闸门的递归性**：改造前目录条目用 ``audio.dir_size_and_mtime``（只看**直接**
   子文件），而嵌套树里一话都不在根上 ⇒ 指纹恒为 ``(0, 0.0)`` ⇒ 加了一话书架上是
   0 变化、也不报错（第 73 期修）。
2. **口径版本**：条目边界变了（一棵树由 43 本变成 1 本）之后，存量索引行永远不会重探
   ⇒ 用户升级后看到的还是 43 本，且不报错（第 72 期同一个坑，第 73 期补上自愈通道）。
"""
import pathlib
from contextlib import contextmanager

from novelforge.core import catalog, db, library, migrate, units


@contextmanager
def _counting_probes():
    """把 ``library._probe_entry`` 换成**计数桩**（``with`` 块里收集被探测的条目）。

    这是唯一能在功能测试里钉住「有没有做某件昂贵的事」的手法：全量重探与增量刷新
    在**结果上完全相同**，只有次数不同。
    """
    calls: list = []
    real = library._probe_entry
    library._probe_entry = lambda f: (calls.append(str(f)), real(f))[1]
    try:
        yield calls
    finally:
        library._probe_entry = real


def _tree(root, rel: str, names) -> pathlib.Path:
    """在 ``root/rel`` 下造一棵树（``names`` 里带 ``/`` 的自动建子目录）。"""
    d = pathlib.Path(root) / rel
    d.mkdir(parents=True, exist_ok=True)
    for name in names:
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4 fake")
    return d


#: 用户实况：老书写法不统一（`第1话` / `第二话` / `第03话` / `4 第4话`）+ 一层子目录
BOOK_DIR = "《转生魔女宣告毁灭（1-43话）》"
BOOK_FILES = ["第1卷/第1话.pdf", "第1卷/第二话.pdf", "第1卷/第03话.pdf", "第1卷/4 第4话.pdf"]


# ---------------------------------------------------------------------------
# ① 枚举 + 探测：一棵树 = 一本书
# ---------------------------------------------------------------------------

def test_用户实况的树在漫画库里是一本书(isolated, tmp_path, make_library):  # noqa: ARG001
    """4 个 PDF ⇒ **恰好一本**：`format == "UNITS"`、`tracks == 4`、话序 1..4。

    ⚠️ **改造前必红**：那时按「一个文件 = 一本书」处理，而且是**只下探一层** ⇒
    书架上是 4 本各自独立的书（书名就是「第1话」…），既看不出同属一本，
    也读不成连续的一话。这就是用户报的那件事。
    """
    root = tmp_path / "comic"
    lib = make_library("c1", "漫画库", "comic", root)
    _tree(root, BOOK_DIR, BOOK_FILES)

    books = library.books(lib["id"])
    assert [b["name"] for b in books] == [BOOK_DIR], "树根目录本身就是**那本书**"
    b = books[0]
    assert b["format"] == "UNITS" and b["tracks"] == 4
    # 书名自动修订为《转生魔女宣告毁灭》（用户要求的第二条）——剥备注在
    # `metadata.from_filename` 里，判据本体见 `tests/test_book_title.py`
    assert b["title"] == "转生魔女宣告毁灭", f"书名没剥掉集数备注：{b['title']!r}"
    # 卡片字段与全量扫盘逐字段一致（索引是副本，副本必须等于真相）
    assert b == library._scan_once(db.get_library(lib["id"]))[0]

    detail = library.book_detail(BOOK_DIR, lib["id"])
    assert [it["name"] for it in detail["units"]] == [
        "第1卷/第1话.pdf", "第1卷/第二话.pdf", "第1卷/第03话.pdf", "第1卷/4 第4话.pdf"], \
        "话清单的 `name` 是**相对树根**的 posix 路径，要能直接下发给前端"


def test_不合并的库类型里形态与改造前逐字相同(isolated, tmp_path, make_library):  # noqa: ARG001
    """护栏：**没嵌套**的同一棵树在 **ebook / mixed** 库里仍是 4 本独立书。

    用户拍板的口径是「这类形态只在漫画库 / 有声书库出现」；ebook 的语义就是
    「一个文件一本」，mixed 是「什么都收」的兜底类型 —— 在兜底类型上猜意图，
    猜错就是把用户几本独立的书粘成一本（只能靠改目录名来救）。**改库类型即可启用**。

    ⚠️ 顺带钉住一件**改造前就是如此**的事：嵌套的树（`树根/第1卷/第1话.pdf`）在
    不合并的库里是**看不见**的 —— 枚举只下探一层，那一层里没有媒体文件。
    这不是本期引入的（改造前对所有库都是这样），但它正是不合并的库与漫画库的
    **真实差别**，所以如实写进用例而不是假装它不存在。
    """
    flat_files = ["第1话.pdf", "第二话.pdf", "第03话.pdf", "4 第4话.pdf"]
    root = tmp_path / "ebooks"
    ebook = make_library("e1", "电子书库", "ebook", root)
    _tree(root, BOOK_DIR, flat_files)
    names = sorted(b["name"] for b in library.books(ebook["id"]))
    assert names == sorted(f"{BOOK_DIR}/{n}" for n in flat_files)
    assert all(b["format"] == "PDF" for b in library.books(ebook["id"]))
    # 书名也不动：`第1话.pdf` 之类没有「集数备注」可剥（`（1-43话）` 那种才剥）
    assert sorted(b["title"] for b in library.books(ebook["id"])) == \
        sorted(pathlib.Path(n).stem for n in flat_files)

    mixed_root = tmp_path / "mixed"
    mixed = make_library("m1", "混合库", "mixed", mixed_root)
    _tree(mixed_root, BOOK_DIR, flat_files)
    assert [b["name"] for b in library.books(mixed["id"])] == names

    nested_root = tmp_path / "nested"
    nested = make_library("e2", "电子书库二", "ebook", nested_root)
    _tree(nested_root, BOOK_DIR, BOOK_FILES)
    assert library.books(nested["id"]) == [], "只下探一层：嵌套的树在这里本来就不出现"


def test_嵌套有声书是一本书(isolated, tmp_path, make_library):  # noqa: ARG001
    """`《书名》/第1卷/第1话.mp3` ×3 ⇒ **一本**、`tracks == 3`、`format == "AUDIO"`。

    ⚠️ **改造前必红**：嵌套音频目录既不是「直接含音频文件的目录」（`is_audio_dir`
    只看直接子文件），也不再下探一层 ⇒ 书架上一本都没有，文件在磁盘上却查不到。
    全是音频话 ⇒ 仍进播放器（`format == "AUDIO"`），所以前端不用为它改协议。
    """
    root = tmp_path / "audio"
    lib = make_library("a1", "有声书库", "audiobook", root)
    _tree(root, "《书名》", ["第1卷/第1话.mp3", "第1卷/第2话.mp3", "第1卷/第3话.mp3"])

    books = library.books(lib["id"])
    assert [b["name"] for b in books] == ["《书名》"]
    assert books[0]["format"] == "AUDIO" and books[0]["tracks"] == 3
    # 「轨」与「话」是同一份清单：音频端点读的也是它（`tracks_of`）
    assert [it["name"] for it in library.book_detail("《书名》", lib["id"])["audio_tracks"]] == [
        "第1卷/第1话.mp3", "第1卷/第2话.mp3", "第1卷/第3话.mp3"]


def test_平铺音频目录与编号轨行为不变(isolated, tmp_path, make_library):  # noqa: ARG001
    """护栏：`01.mp3`…`03.mp3` 仍是一本「3 轨」的书（不是「3 话」的单元树）。

    编号轨的有声书是常态，而「N 轨 + 播放器」是改造前就有的行为 ⇒
    `shape_of` 让**平铺音频优先**，这条用例钉住它没有因为单元判据上线而变样。
    """
    root = tmp_path / "audio"
    lib = make_library("a2", "有声书库", "audiobook", root)
    _tree(root, "编号轨", ["01.mp3", "02.mp3", "03.mp3"])
    assert units.shape_of(root / "编号轨") == "audio"

    b = library.books(lib["id"])[0]
    assert (b["format"], b["tracks"]) == ("AUDIO", 3)
    assert [it["name"] for it in library.book_detail("编号轨", lib["id"])["audio_tracks"]] == [
        "01.mp3", "02.mp3", "03.mp3"], "排序仍是自然序（01 < 02 < 03），不是 units 的顺序"


def test_同一个目录里几本独立漫画仍是一本一个(isolated, tmp_path, make_library):  # noqa: ARG001
    """护栏：`《甲》(第1卷).cbz` + `《乙》(第2卷).cbz` ⇒ **2 本**，不是一部连载。"""
    root = tmp_path / "comic"
    lib = make_library("c2", "漫画库", "comic", root)
    _tree(root, "散本", ["《甲》(第1卷).cbz", "《乙》(第2卷).cbz"])
    assert sorted(b["name"] for b in library.books(lib["id"])) == [
        "散本/《乙》(第2卷).cbz", "散本/《甲》(第1卷).cbz"], "顺序按路径码点（乙 < 甲）"


# ---------------------------------------------------------------------------
# ①b 前缀 + 尾部编号（第 79 期）：一级子文件夹内的「标题+编号」散文件合成一本
# ---------------------------------------------------------------------------

def test_同前缀子文件夹是一本合集(isolated, tmp_path, make_library):  # noqa: ARG001
    """`超人前传/超人前传0904.pdf` + `超人前传1408.pdf` ⇒ **一本**合集（第 79 期）。

    这是用户报的那件事：一部作品被拆成一堆「标题+编号」的散文件，书架上是 N 本各自
    独立的书（书名就是文件名）。落点是 `units._TAIL_NUM_RE`（尾部编号形态，编号去前导零）
    与 `is_unit_dir` 的「同前缀」闸。

    ⚠️ **改造前必红**：那时 `超人前传0904` 解析不出序号 ⇒ `is_unit_dir` 为假 ⇒
    退回「一个文件一本书」，书架上是 2 本。
    """
    root = tmp_path / "comic"
    lib = make_library("c80", "漫画库", "comic", root)
    _tree(root, "超人前传", ["超人前传0904.pdf", "超人前传1408.pdf"])

    books = library.books(lib["id"])
    assert [b["name"] for b in books] == ["超人前传"], "文件夹本身就是那本合集"
    b = books[0]
    assert b["format"] == "UNITS" and b["tracks"] == 2
    assert b["title"] == "超人前传"
    assert [it["name"] for it in library.book_detail("超人前传", lib["id"])["units"]] == [
        "超人前传0904.pdf", "超人前传1408.pdf"], "话序按**序号**（904 < 1408），不是按名字"


def test_混前缀不合并(isolated, tmp_path, make_library):  # noqa: ARG001
    """护栏：同一个文件夹里两种前缀 ⇒ 各自一本（宁可少合并，不可错合并）。

    `超人前传0904.pdf` 与 `另一部作品0905.pdf` 都解析得出序号，但那是**两部作品** ——
    只看「≥2 个不同序号」会把它们粘成一本，而错合并之后用户只能靠改目录名自救
    （本项目承诺源不可变）。
    """
    root = tmp_path / "comic"
    lib = make_library("c81", "漫画库", "comic", root)
    _tree(root, "两部作品", ["超人前传0904.pdf", "另一部作品0905.pdf"])
    assert sorted(b["name"] for b in library.books(lib["id"])) == [
        "两部作品/另一部作品0905.pdf", "两部作品/超人前传0904.pdf"]


def test_平铺库根的散文件不合并(isolated, tmp_path, make_library):  # noqa: ARG001
    """护栏：**平铺在库根**的同类散文件仍是各自一本（用户确认的口径）。

    合并判据只对**目录**生效（`_iter_book_entries` 的目录分支），库根的文件是
    「文件条目」、永远不走 `is_unit_dir` ⇒ 「库根不合并」天然成立，**没有**任何
    「库根例外」分支。使用方式因此是「把同类文件放进一个子文件夹」。
    """
    root = tmp_path / "comic"
    lib = make_library("c82", "漫画库", "comic", root)
    for n in ("超人前传0904.pdf", "超人前传1408.pdf"):
        (root / n).write_bytes(b"%PDF-1.4 fake")
    books = library.books(lib["id"])
    assert sorted(b["name"] for b in books) == ["超人前传0904.pdf", "超人前传1408.pdf"]
    assert all(b["format"] == "PDF" for b in books)


def test_同前缀音频文件夹仍是平铺音频形态(isolated, tmp_path, make_library):  # noqa: ARG001
    """护栏：有声书库里「同前缀音频」**本来就是一本多轨的书**，本期行为逐字不变。

    `shape_of` 的顺序是**先平铺音频、后序号单元** ⇒ 直接含音频文件的目录取 `"audio"`
    形态（N 轨 + 播放器，改造前就有的行为）。新增的尾部编号形态对它没有影响：
    卡片上显示的仍应是「N 轨」而不是「N 话」。
    """
    root = tmp_path / "audio"
    lib = make_library("a80", "有声书库", "audiobook", root)
    d = _tree(root, "超人前传", ["超人前传0904.mp3", "超人前传1408.mp3"])
    assert units.shape_of(d) == "audio"
    b = library.books(lib["id"])[0]
    assert (b["format"], b["tracks"]) == ("AUDIO", 2)
    assert [it["name"] for it in library.book_detail("超人前传", lib["id"])["audio_tracks"]] == [
        "超人前传0904.mp3", "超人前传1408.mp3"], "仍是自然序（904 < 1408）"


# ---------------------------------------------------------------------------
# ② 增量闸门：树深处的变化也必须被看见
# ---------------------------------------------------------------------------

def test_增量刷新看得见树深处新增的一话(isolated, tmp_path, make_library):  # noqa: ARG001
    """**不 force** 的增量刷新也要发现「子目录里多了一话」。

    ⚠️ **改造前必红**：闸门当时是 ``audio.dir_size_and_mtime``（只看**直接**子文件），
    而这棵树一话都不在根上 ⇒ 指纹恒为 ``(0, 0.0)`` ⇒ 新增的一话对增量刷新**完全
    不可见**：用户加了一话、书架上是 0 变化，也不报错。今天走
    `units.dir_fingerprint`（递归全部文件）。
    """
    root = tmp_path / "comic"
    lib = make_library("c3", "漫画库", "comic", root)
    d = _tree(root, BOOK_DIR, ["第1卷/第1话.pdf", "第1卷/第2话.pdf"])
    lib = db.get_library(lib["id"])
    catalog.refresh_library(lib, force=True)
    assert library.books(lib["id"])[0]["tracks"] == 2

    _tree(root, BOOK_DIR, ["第1卷/第3话.pdf"])
    out = catalog.refresh_library(lib)                 # ← 不 force：走 `(size, mtime)` 闸门
    assert out["added"] == 1 or out["unchanged"] == 0
    assert library.books(lib["id"])[0]["tracks"] == 3, "新增的一话没被看见（闸门漏了）"
    assert d.is_dir(), "扫描绝不改动源目录"


# ---------------------------------------------------------------------------
# ③ 存量索引的自愈通道：扫描口径版本
# ---------------------------------------------------------------------------

def test_口径版本不一致时全量重探一次(isolated, tmp_path, make_library):  # noqa: ARG001
    """落盘口径版本对不上 ⇒ 下一次刷新按 ``force`` 跑一次，之后就回落增量。

    这是**存量索引唯一的自愈通道**：条目边界或卡片字段口径一变（第 73 期：一棵树由
    43 本合成 1 本；第 79 期：一级子文件夹里的「前缀 + 尾部编号」散文件也并为合集），
    `(size, mtime)` 完全没有变化 ⇒ 不重探就永远显示旧结果，而且不报错、不重建。
    第 72 期正是同一个坑（改了分章判据，存量书照旧）。
    """
    # ⚠️ 条目边界口径变了就必须 +1，否则存量书架永远自愈不了。再改「条目边界 / 卡片字段
    # 口径」时，这一行要同步成下一个数 —— 它是「有没有忘记 +1」的探针。
    assert library.SCAN_RULE_VERSION == 2, "第 79 期改了条目边界 ⇒ 版本应为 2"
    root = tmp_path / "comic"
    lib = make_library("c4", "漫画库", "comic", root)
    _tree(root, BOOK_DIR, BOOK_FILES)
    lib = db.get_library(lib["id"])
    catalog.refresh_library(lib, force=True)
    assert db.state_get(catalog._rule_key(lib["id"])) == str(library.SCAN_RULE_VERSION)

    with _counting_probes() as calls:
        # 抹掉这个库的版本（= 存量索引：这份索引是旧口径算出来的）
        db.state_delete(catalog._rule_key(lib["id"]))
        catalog.refresh_library(lib)
        assert calls, "口径版本不一致却没有全量重探 —— 存量索引永远不会自愈"

        calls.clear()
        catalog.refresh_library(lib)          # 版本已写回 ⇒ 回到增量 ⇒ 一条都不探
        assert calls == [], "第二轮不该再全量重探（自愈只发生一次）"


def test_口径版本按库记_别的库不受影响(isolated, tmp_path, make_library):  # noqa: ARG001
    """一个库的口径版本被抹掉，**不影响**另一个库（标记按库分键）。

    记成全局一个版本号的话，只有第一个来刷新的库会被治好、其余库照旧 ——
    而那是「一部分书对了、一部分没变」这种最难查的状态。
    """
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    la = make_library("la", "库甲", "comic", root_a)
    lb = make_library("lb", "库乙", "comic", root_b)
    _tree(root_a, BOOK_DIR, ["第1卷/第1话.pdf", "第1卷/第2话.pdf"])
    _tree(root_b, BOOK_DIR, ["第1卷/第1话.pdf", "第1卷/第2话.pdf"])
    catalog.refresh_library(db.get_library(la["id"]), force=True)
    catalog.refresh_library(db.get_library(lb["id"]), force=True)
    assert db.state_get(catalog._rule_key(la["id"])) and db.state_get(catalog._rule_key(lb["id"]))

    db.state_delete(catalog._rule_key(la["id"]))          # 只让甲库过期
    with _counting_probes() as calls:
        catalog.refresh_library(db.get_library(lb["id"]))
        assert calls == [], "乙库的口径版本还在，不该被甲库带着重探"
        catalog.refresh_library(db.get_library(la["id"]))
        assert calls, "甲库的版本被抹掉了，必须重探"


# ---------------------------------------------------------------------------
# ④ 搬家判据与扫描同源
# ---------------------------------------------------------------------------

def test_搬家相容判据与扫描同源(isolated, tmp_path, make_library):  # noqa: ARG001
    """单元树在两个漫画库之间搬 ⇒ **相容**；搬进不看这类形态的库 ⇒ 拦下并说明理由。

    ⚠️ **改造前必红**：判据当时是一句「白名单含音频扩展名」的字面量，PDF 单元树
    一个音频扩展名都不含 ⇒ 理由是「认不出有声书目录」，而事实是它扫得到 ——
    判据与事实不符，用户看到的是「这本书搬不过去」这种假限制。
    """
    root_a = tmp_path / "a"
    lib = make_library("c5", "漫画库甲", "comic", root_a)
    _tree(root_a, BOOK_DIR, BOOK_FILES)
    book = library.books(lib["id"])[0]

    same = make_library("c6", "漫画库乙", "comic", tmp_path / "b")
    other = make_library("a3", "有声书库", "audiobook", tmp_path / "c")
    assert migrate.compat_reason(book, db.get_library(same["id"])) == "", \
        "同一类型之间搬一本单元树必须相容（搬完还认得出这本书）"
    why = migrate.compat_reason(book, db.get_library(other["id"]))
    assert why.startswith("「有声书库」只收") and "目录" in why


def test_合集的目标库类型取它所在的库(isolated, tmp_path, make_library):  # noqa: ARG001
    """`migrate.target_type_of`：合集**没有扩展名可判** ⇒ 取它所在库的类型。

    它是「自动归库」与「系列页按媒体分组」共用的判据。少了这一条，合集会被
    **静默跳过**：自动归库预览里少一行（不报错），系列页里掉进「其它」分组。
    """
    root = tmp_path / "comic"
    lib = make_library("c7", "漫画库", "comic", root)
    _tree(root, BOOK_DIR, BOOK_FILES)
    b = library.books(lib["id"])[0]
    assert b["library_type"] == "comic" and migrate.target_type_of(b) == "comic"
    assert migrate.TYPE_LABELS[migrate.target_type_of(b)] == "漫画库"

    aroot = tmp_path / "audio"
    alib = make_library("a4", "有声书库", "audiobook", aroot)
    _tree(aroot, "《书名》", ["第1卷/第1话.mp3", "第1卷/第2话.mp3"])
    assert migrate.target_type_of(library.books(alib["id"])[0]) == "audiobook"
