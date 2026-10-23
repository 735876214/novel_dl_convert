"""系列兜底推断（第 137 期）：漫画库「一层目录 = 一个系列」在**扫描期**落地。

背景：漫画包（一话一 zip / 一卷一 cbz）的文件里没有任何系列元数据，盘上就是
652 个 `001 預告.zip`。此前扫描期只认 EPUB 的 `calibre:series`，于是漫画库整库
`series` 全空；而书架恰好按 `series` 折叠 ⇒ 退化成「一书一卡 + 满屏同名 Vol.03」。

这一轮把「顶层目录名 = 系列名、文件名 = 卷号」放进扫描期（`library.series_of_rel`），
并且**只对漫画库启用** —— 电子书 / 有声书库的顶层目录常是作者名或整张专辑目录。
"""

import pathlib

import pytest

from novelforge.core import catalog, library


# ---------------------------------------------------------------- 纯函数口径

@pytest.mark.parametrize(
    "rel, want",
    [
        # 中文漫画包的通行命名：`[作品名][作者][范围]`，作品名在**第一个**括号里
        ("[神之塔][SIU][Chap.000-Chap.651]/001 預告.zip", ("神之塔", "1")),
        # 首括号是**作者列表**（含 `×`）⇒ 作品名在后面那个括号里
        ("[中村力斗×野澤ゆき子][超超超超喜欢你的100个女孩子][东立][14未]/Vol.01.zip",
         ("超超超超喜欢你的100个女孩子", "1")),
        # 首括号是**单个作者**：文件名里出现的是第二个括号 ⇒ 以文件名为证
        ("[よのき][鬼畜英雄][ 一二三書房][Zero有水印][5未]/鬼畜英雄 Vol.01.zip",
         ("鬼畜英雄", "1")),
        # 目录名残缺（左边少一个 `[`，收书源头如此）⇒ 取第一个 `]` 之前那段
        ("封神演义 全彩版][藤崎龙][23完]/Vol.01.zip", ("封神演义 全彩版", "1")),
        # 没括号就整个目录名当系列名（本库里有 3 个这样的目录）
        ("史诗级领地设计师/001 第1話.zip", ("史诗级领地设计师", "1")),
        # `【】` 是**汉化组**标记而不是作品名标记 ⇒ 不切，整个目录名当系列名
        ("【UA汉化组】某作品/某作品#7.zip", ("【UA汉化组】某作品", "7")),
        # 系列名**原样保留**（全角冒号不能被 NFKC 改成半角：目录名是这条数据的真值源）
        ("[无限危机：为多元宇宙而战][DC Comics][36卷][完]/Vol.01.zip",
         ("无限危机：为多元宇宙而战", "1")),
    ],
)
def test_系列名取目录首括号(rel, want):
    assert library.series_of_rel(rel) == want


@pytest.mark.parametrize(
    "rel, want_index",
    [
        # 前导枚举号必须压过标题里的话数：652 话的文件名里两者都有，
        # 按「第1話」排会把整部漫画挤到 1 号（真序是枚举号）
        ("[神之塔][SIU][x]/002 [第1話] HEADON's Floor.zip", "2"),
        # 帧繁体的「話」也要认
        ("甲/第12話.zip", "12"),
        # 卷在**中段**也认（`komga.infer` 要求卷号在结尾，覆盖不了这个）
        ("乙/乙 Vol.03 封神计划发动.cbz", "3"),
        # 汉化组期号
        ("丙/丙#4.cbz", "4"),
        # 末尾括号号（漫画包最常见的卷号写法）
        ("[丁][作者][東立][08]/[丁][作者][東立][08].zip", "8"),
        # 副本后缀排在明确写法之后 ⇒ 仍取 Vol.01，不会被读成 2
        ("[蝙蝠侠v3]/蝙蝠侠v3 Vol.01 (2).cbz", "1"),
        # 什么都推不出就留空 —— 不猜位置（既有纪律）
        ("[世代破碎][DC Comics][1卷][完]/【UA汉化组】世代破碎.zip", ""),
    ],
)
def test_卷号取值顺序(rel, want_index):
    assert library.series_of_rel(rel)[1] == want_index


@pytest.mark.parametrize("rel", ["三体.epub", "某漫画.cbz", ""])
def test_平铺条目没有系列(rel):
    """库根下的散文件：一个文件 = 一个独立系列，不猜（返回空串让书架照旧显示单卡）。"""
    assert library.series_of_rel(rel) == ("", "")


# ---------------------------------------------------------------- 扫描期落地

def _put(root: pathlib.Path, rel: str, data: bytes = b"x") -> pathlib.Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _books(lib):
    return {b["name"]: b for b in catalog.books_of(lib)}


def test_漫画库扫描期写入系列与序号(isolated, tmp_path, make_library):  # noqa: ARG001
    root = tmp_path / "comic"
    root.mkdir()
    lib = make_library("c137", "漫画库", "comic", root)
    _put(root, "[神之塔][SIU][Chap.000-Chap.651]/001 預告.zip")
    _put(root, "[神之塔][SIU][Chap.000-Chap.651]/002 [第1話] HEADON's Floor.zip")
    _put(root, "史诗级领地设计师/001 第1話.zip")

    catalog.refresh_library(lib, force=True)
    books = _books(lib)
    assert books["[神之塔][SIU][Chap.000-Chap.651]/001 預告.zip"]["series"] == "神之塔"
    assert books["[神之塔][SIU][Chap.000-Chap.651]/001 預告.zip"]["series_index"] == "1"
    assert books["[神之塔][SIU][Chap.000-Chap.651]/002 [第1話] HEADON's Floor.zip"]["series"] == "神之塔"
    assert books["[神之塔][SIU][Chap.000-Chap.651]/002 [第1話] HEADON's Floor.zip"]["series_index"] == "2"
    assert books["史诗级领地设计师/001 第1話.zip"]["series"] == "史诗级领地设计师"


def test_电子书库不按目录推系列(isolated, tmp_path, make_library):  # noqa: ARG001
    """同样的目录布局，ebook 库**不**开这道兜底：顶层目录常是作者名，
    照搬会把作者的四本书凑成一个假系列。"""
    root = tmp_path / "ebook"
    root.mkdir()
    lib = make_library("e137", "电子书库", "ebook", root)
    _put(root, "刘慈欣/三体.epub", b"EPUB")
    _put(root, "刘慈欣/球状闪电.epub", b"EPUB")

    catalog.refresh_library(lib, force=True)
    for row in _books(lib).values():
        assert row["series"] == ""
        assert row["series_index"] == ""


def test_有声书库不按目录推系列(isolated, tmp_path, make_library):  # noqa: ARG001
    """有声书的顶层目录常常是**整张专辑**（`神奇图书馆1-凯叔-…-MP3-256kbps`），
    专辑里的每条音轨是同一本书的一部分，不是一本书一个系列。"""
    root = tmp_path / "audio"
    root.mkdir()
    lib = make_library("a137", "有声书库", "audiobook", root)
    _put(root, "专辑/01.mp3", b"ID3" + b"\x00" * 64)
    _put(root, "专辑/02.mp3", b"ID3" + b"\x00" * 64)

    catalog.refresh_library(lib, force=True)
    for row in _books(lib).values():
        assert row["series"] == ""


def test_文件内元数据优先于目录推断(isolated, tmp_path, make_library):  # noqa: ARG001
    """顺序是 override > 文件内元数据 > 目录推断：`_row_of` 只在元数据**缺席**时兜底，
    否则按目录名重算会把用户在 OPF / 覆盖层里写好的系列冲掉。"""
    root = tmp_path / "comic"
    root.mkdir()
    lib = make_library("p137", "漫画库", "comic", root)
    f = _put(root, "[占位目录]/第3卷.cbz")

    p = library._probe_entry(f)
    p["series"], p["series_index"] = "元数据系列", "7"
    row = library._row_of(lib, root, f, p)
    assert (row["series"], row["series_index"]) == ("元数据系列", "7")
