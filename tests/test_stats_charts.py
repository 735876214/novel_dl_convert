"""第 32 期：统计接口的 8 条图表序列。

上游统计页是「一张图一个 composable 一次请求」，本项目是**单接口共享一份 overview**
（``GET /api/stats``），所以这 8 条序列一次算齐、并随 ``library_id`` 一起收窄。

书库侧 5 条：``by_language`` / ``by_format_size`` / ``pages_by_format`` /
``added_monthly`` / ``publication_yearly``；阅读侧 3 条：``progress_funnel`` /
``completion_monthly`` / ``weekdays``。

这个文件钉三件事：

1. **既有键一个不丢** —— 8 个仪表盘部件与既有契约测试都读它们（第 29/30 期立的规矩）；
2. **新序列跟随按库筛选** —— 书库侧从 ``bs`` 算，阅读侧靠 ``ids`` 过滤（阅读会话
   没有库维度，故「某库的阅读」靠「这本书属于哪个库」判定）；
3. **口径诚实** —— 页数 0 是「不知道」不是「0 页」，不进分布；进度漏斗必须单调；
   空库给空序列而不是 0 假数据。
"""
from __future__ import annotations

import pathlib
import time

from novelforge import config
from novelforge.core import db, epub_builder, fileops, library, stats, watcher

#: 第 32 期之前就有的顶层键。新序列一律**增补**，这些一个都不能少。
_OLD_KEYS = (
    "books", "authors", "series", "publishers", "genres", "years", "avg_progress",
    "integrity", "metadata_score", "largest", "reading", "window", "library_id",
    "added_28d", "added_month", "hours", "reading_28d", "recent",
)

#: 第 32 期新增的图表序列。
_NEW_KEYS = (
    "by_language", "by_format_size", "pages_by_format", "added_monthly",
    "publication_yearly", "progress_funnel", "completion_monthly", "weekdays",
)


def _epub(root, name: str, *, title: str = "书", author: str = "作者",
          language: str = "zh", meta: dict | None = None) -> pathlib.Path:
    """真 EPUB（能解析出元数据），``meta`` 里的字段额外写进 OPF。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": author, "language": language},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    if meta:
        assert fileops.patch_epub_meta(path, meta), f"OPF 改写失败：{name}"
    return path


def _scan() -> None:
    library.invalidate()


# ---------------------------------------------------------------------------
# ① 增补语义：既有键一个不丢
# ---------------------------------------------------------------------------

def test_新序列是增补_既有键一个不丢(default_root):  # noqa: ARG001
    ov = stats.overview()

    for k in _OLD_KEYS:
        assert k in ov, f"既有键丢了：{k}"
    for k in _NEW_KEYS:
        assert k in ov, f"第 32 期新键缺失：{k}"


def test_空库给空序列不炸(isolated):  # noqa: ARG001
    """统计是展示型接口：空库要得体降级，不是 400 也不是一堆假 0。"""
    ov = stats.overview()

    assert ov["by_language"] == {}
    assert ov["by_format_size"] == {}
    assert ov["pages_by_format"] == []
    assert ov["added_monthly"] == []
    assert ov["publication_yearly"] == []
    assert ov["completion_monthly"] == []
    assert ov["progress_funnel"] == {
        "started": 0, "reached25": 0, "reached50": 0, "reached75": 0, "completed": 0,
    }
    # 周几分布：没有阅读故秒数全 0，但**窗口里的天数是真实的**（不该假装窗口也是空的）
    assert len(ov["weekdays"]) == 7
    assert all(w["seconds"] == 0 for w in ov["weekdays"])
    assert sum(w["days"] for w in ov["weekdays"]) == 365


# ---------------------------------------------------------------------------
# ② 书库侧序列
# ---------------------------------------------------------------------------

def test_语言分布_未知归到问号(default_root, make_book):  # noqa: ARG001
    """未知语言归到 ``"?"`` —— 照 ``by_format`` 的既成惯例，不新造一个 null 维度。"""
    _epub(default_root, "甲.epub", title="甲", language="zh")
    _epub(default_root, "乙.epub", title="乙", language="en")
    make_book(default_root, "丙.epub", b"EPUB")   # 解析不出语言
    _scan()

    assert stats.overview()["by_language"] == {"zh": 1, "en": 1, "?": 1}


def test_格式体积之和等于总量(default_root, make_book):  # noqa: ARG001
    _epub(default_root, "甲.epub", title="甲")
    make_book(default_root, "乙.epub", b"x" * 500)
    _scan()

    ov = stats.overview()
    by_fmt = ov["by_format_size"]

    assert by_fmt.get("EPUB", 0) > 0
    assert sum(by_fmt.values()) == ov["books"]["size"], "分格式体积必须加起来等于总量"


def test_页数分布只收有页数的书(default_root, make_book):  # noqa: ARG001
    """⚠️ ``pages`` 的 0 是「不知道」不是「0 页」（EPUB 是估算、漫画是归档实际值、
    其余格式恒 0）。0 若进了分布，PDF / 有声书会在箱线图上压出一根假底线。
    """
    _epub(default_root, "真.epub", title="真")
    for i in range(3):
        make_book(default_root, f"假{i}.epub", b"EPUB")
    _scan()

    bs = library.books()
    with_pages = [b for b in bs if int(b.get("pages") or 0) > 0]
    groups = stats.overview()["pages_by_format"]

    assert sum(g["count"] for g in groups) == len(with_pages), "进分布的必须是 pages>0 的书"
    assert sum(g["count"] for g in groups) < len(bs), "本次数据里确实有 pages=0 的书被排除"
    for g in groups:
        assert g["count"] >= 1
        assert g["min"] <= g["q1"] <= g["median"] <= g["q3"] <= g["max"], "五数概括必须单调"
        assert g["sources"], "来源构成要如实带上（estimate / archive）"


def test_入库月序列与出版年序列(default_root):  # noqa: ARG001
    _epub(default_root, "一.epub", title="一", meta={"date": "2012"})
    _epub(default_root, "二.epub", title="二", meta={"date": "2012"})
    _epub(default_root, "三.epub", title="三", meta={"date": "1998"})
    _scan()

    ov = stats.overview()
    yearly = ov["publication_yearly"]

    assert [x["year"] for x in yearly] == [1998, 2012], "逐年序列按年份升序"
    y2012 = next(x for x in yearly if x["year"] == 2012)
    assert y2012["count"] == 2
    assert y2012["top_titles"] == ["一", "二"], "该年样例书名（tooltip 用）取稳定排序"
    # 逐年与十年聚合同源，不该各说各话
    assert sum(x["count"] for x in yearly) == sum(d["count"] for d in ov["years"]["decades"])

    # 入库月：三本书都是刚写的，落在同一个月
    monthly = ov["added_monthly"]
    assert sum(x["count"] for x in monthly) == 3
    assert monthly[-1]["year"] == time.localtime().tm_year
    assert monthly[-1]["month"] == time.localtime().tm_mon
    assert monthly[-1]["count"] == 3


# ---------------------------------------------------------------------------
# ③ 阅读侧序列
# ---------------------------------------------------------------------------

def test_进度漏斗按进度分档且单调(default_root, make_book):  # noqa: ARG001
    for i in range(5):
        make_book(default_root, f"p{i}.epub", b"EPUB")
    _scan()

    bs = library.books()
    assert len(bs) == 5
    for b, pct in zip(bs, (10.0, 30.0, 60.0, 80.0, 100.0)):
        db.set_progress(b["id"], 0, pct)

    f = stats.overview()["progress_funnel"]

    assert f["started"] == 5      # 翻过至少一页
    assert f["reached25"] == 4    # 30 / 60 / 80 / 100
    assert f["reached50"] == 3    # 60 / 80 / 100
    assert f["reached75"] == 2    # 80 / 100
    assert f["completed"] == 1    # 100（阈值 99.5，与模块既有的「已读完」口径一致）
    # 漏斗图的硬要求：各档单调包含
    assert (f["started"] >= f["reached25"] >= f["reached50"]
            >= f["reached75"] >= f["completed"])


def test_进度漏斗走进度而不是真实状态(default_root, make_book):  # noqa: ARG001
    """真实状态允许把一本 20% 的书手工标成 finished。漏斗若跟着它走，就会出现
    「后档比前档多」的畸形图 —— 故漏斗只看 percent；阅读状态侧照旧尊重真实状态。
    """
    make_book(default_root, "x.epub", b"EPUB")
    _scan()

    b = library.books()[0]
    db.set_progress(b["id"], 0, 20.0)
    db.set_status(b["id"], "finished")   # 手工标读完，但进度只有 20%

    ov = stats.overview()
    assert ov["progress_funnel"]["started"] == 1
    assert ov["progress_funnel"]["completed"] == 0, "漏斗必须走进度，不走真实状态"
    # 两套口径各司其职：阅读状态侧仍然认这个手工状态
    assert ov["reading"]["finished"] == 1


def test_周几分布按本地日聚合(default_root, make_book):  # noqa: ARG001
    make_book(default_root, "s.epub", b"EPUB")
    _scan()

    bid = library.books()[0]["id"]
    now = time.time()
    db.add_session(bid, 600.0, started_at=now - 60, ended_at=now)
    db.add_session(bid, 300.0, started_at=now - 60, ended_at=now)

    weekdays = stats.overview()["weekdays"]

    assert len(weekdays) == 7
    assert sum(w["seconds"] for w in weekdays) == 900.0
    # 索引 0 = 周日（与前端 Date.getDay() 一致）
    today_index = (time.localtime(now).tm_wday + 1) % 7
    assert weekdays[today_index]["seconds"] == 900.0
    assert sum(w["days"] for w in weekdays) == 365, "窗口天数要如实给出（界面据此算日均）"


def test_按月读完数只看已读完的日期(default_root, make_book):  # noqa: ARG001
    """``finished_at`` 只在「已读完」时有值：离开 finished 会被清零，
    故「读完月序列」不会把改回过状态的书算进去。"""
    for i in range(2):
        make_book(default_root, f"f{i}.epub", b"EPUB")
    _scan()

    a, b = library.books()[0]["id"], library.books()[1]["id"]
    db.set_status(a, "finished")
    db.set_status(b, "finished")
    db.set_status(b, "reading")   # 又改回在读 ⇒ finished_at 清零

    monthly = stats.overview()["completion_monthly"]

    assert len(monthly) == 1
    assert monthly[0]["count"] == 1, "改回在读的那本不该还留在读完月序列里"


# ---------------------------------------------------------------------------
# ④ 按库筛选必须对新序列生效（第 30 期立的规矩）
# ---------------------------------------------------------------------------

def test_新序列跟随按库筛选(make_library, tmp_path):  # noqa: ARG001
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    for lid, lang, year in (("sc-a", "zh", "2012"), ("sc-b", "en", "1998")):
        make_library(lid, lid, "ebook", tmp_path / f"st_{lid}",
                     mode="import", source_subdir=lid)
        d = src / lid
        d.mkdir(parents=True, exist_ok=True)
        _epub(d, f"{lid}.epub", title=lid, language=lang, meta={"date": year})
        watcher.FolderWatcher(cfg=config.load_config()).scan_library_now(lid)
    library.invalidate()

    a = stats.overview(library_id="sc-a")
    b = stats.overview(library_id="sc-b")

    assert a["by_language"] == {"zh": 1}
    assert b["by_language"] == {"en": 1}
    assert [x["year"] for x in a["publication_yearly"]] == [2012]
    assert [x["year"] for x in b["publication_yearly"]] == [1998]
    # 体积也随库收窄：两库各一本书，各自的总量该等于自己的分格式体积
    for ov in (a, b):
        assert sum(ov["by_format_size"].values()) == ov["books"]["size"]

    # 未知库 = 空集合（不 404，与 /api/duplicates 同一条惯例）
    none = stats.overview(library_id="没有这个库")
    assert none["by_language"] == {}
    assert none["by_format_size"] == {}
    assert none["publication_yearly"] == []
    assert none["pages_by_format"] == []


# ---------------------------------------------------------------------------
# ⑤ 接口层：新序列真的下发
# ---------------------------------------------------------------------------

def test_接口_stats下发新序列(client, auth_headers, default_root):  # noqa: ARG001
    _epub(default_root, "甲.epub", title="甲", language="zh", meta={"date": "2012"})
    _scan()

    r = client.get("/api/stats", headers=auth_headers)
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["by_language"] == {"zh": 1}
    assert body["publication_yearly"][0]["year"] == 2012
    assert body["by_format_size"].get("EPUB", 0) > 0
    assert set(body["progress_funnel"]) == {
        "started", "reached25", "reached50", "reached75", "completed",
    }
    assert len(body["weekdays"]) == 7
