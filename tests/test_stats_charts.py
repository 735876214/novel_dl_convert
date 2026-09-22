"""第 32/33 期：统计接口的图表序列。

上游统计页是「一张图一个 composable 一次请求」，本项目是**单接口共享一份 overview**
（``GET /api/stats``），所以这些序列一次算齐、并随 ``library_id`` 一起收窄。

第 32 期 8 条 —— 书库侧 5 条：``by_language`` / ``by_format_size`` / ``pages_by_format`` /
``added_monthly`` / ``publication_yearly``；阅读侧 3 条：``progress_funnel`` /
``completion_monthly`` / ``weekdays``。

第 33 期 10 条 —— 书库侧 5 条：``metadata_fields``（按字段覆盖率）/ ``library_metadata``
（按 库 × 字段，heatmap）/ ``genre_cooccurrence``（题材共现，弦图）/
``format_share_monthly``（格式 × 月份）/ ``acquisition_lag``（出版 → 入库滞后）；
阅读侧 5 条：``completion_latency``（完成耗时分布）/ ``genre_reading``（题材 × 时长）/
``reading_pace``（阅读速度）/ ``session_timeline``（会话时间轴）/
``session_archetypes``（会话形态）。

这个文件钉四件事：

1. **既有键一个不丢** —— 8 个仪表盘部件与既有契约测试都读它们（第 29/30 期立的规矩）；
2. **新序列跟随按库筛选** —— 书库侧从 ``bs`` 算，阅读侧靠 ``ids`` 过滤（阅读会话
   没有库维度，故「某库的阅读」靠「这本书属于哪个库」判定）；
3. **口径诚实** —— 页数 0 是「不知道」不是「0 页」，不进分布；进度漏斗必须单调；
   空库给空序列而不是 0 假数据；阅读侧三处**与上游不同**的地方如实钉住（见模块头
   的口径差异说明）：``reading_pace`` 是按书聚合而非 per-session、``session_timeline``
   只读、``genre_reading`` 有扇出且漏掉没打题材的书；
4. ⚠️ **``library_metadata`` 是唯一的例外**（第 33 期）—— 它是「库之间横向比」的图，
   跟随 ``library_id`` 就退化成一行、图本身失去意义，故**始终覆盖全部书库**。
   其余序列都收窄、这一条不收窄；下面对按库筛选的正反两个用例并排钉住这个差别。
"""
from __future__ import annotations

import pathlib
import time

import pytest

from novelforge import config
from novelforge.core import db, epub_builder, fileops, library, metascore, stats, watcher

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

#: 第 33 期新增的书库侧图表序列。
_NEW_KEYS_33_LIB = (
    "metadata_fields", "library_metadata", "genre_cooccurrence",
    "format_share_monthly", "acquisition_lag",
)

#: 第 33 期新增的阅读侧图表序列。
_NEW_KEYS_33_READ = (
    "completion_latency", "genre_reading", "reading_pace",
    "session_timeline", "session_archetypes",
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
    for k in _NEW_KEYS_33_LIB + _NEW_KEYS_33_READ:
        assert k in ov, f"第 33 期新键缺失：{k}"
    # 元数据分位数是第 33 期增补的两个键（P25/P75），既有的 P50/P90 一个不动
    for k in ("p25", "p50", "p75", "p90"):
        assert k in ov["metadata_score"], f"metadata_score 缺分位键：{k}"


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

    # 第 33 期：空库也要给**结构完整**的空序列（12 个字段照列、分母为 0），
    # 而不是空数组 —— 形状随数据变会让前端得写两套渲染路径
    assert [x["key"] for x in ov["metadata_fields"]] == list(metascore.FIELDS)
    assert all(x["total"] == 0 and x["present"] == 0 for x in ov["metadata_fields"])
    assert all(x["percent"] == 0.0 for x in ov["metadata_fields"])
    assert ov["genre_cooccurrence"] == {"nodes": [], "links": []}
    assert ov["format_share_monthly"] == []
    assert ov["acquisition_lag"] == []
    # 按库热力图：默认库那一行照出（12 条 0/0），不是空数组 —— 库存在就是 0 本书
    assert ov["library_metadata"], "按库热力图不该是空的：库存在即应有行"
    assert all(x["total"] == 0 for x in ov["library_metadata"])

    # 第 33 期阅读侧五条：空库同样是「形状完整的空」，分位点尤其不能给 0
    # （0 天会被读成「当天就读完了」，那不是「没有数据」）
    assert ov["genre_reading"] == []
    assert ov["reading_pace"] == []
    assert ov["session_timeline"] == []
    assert ov["session_archetypes"] == []
    lat = ov["completion_latency"]
    assert lat["total"] == 0
    assert (lat["median_days"], lat["p75_days"], lat["p90_days"]) == (None, None, None)
    assert len(lat["buckets"]) == 7, "空库也要给全 7 档（形状随数据变会让前端写两套渲染）"
    assert all(x["count"] == 0 for x in lat["buckets"])


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

@pytest.fixture
def two_libs(make_library, tmp_path):  # noqa: ARG001 —— 依赖 isolated 切目录
    """两个库各一本真 EPUB：``sc-a`` 中文/2012/题材「题-sc-a」、``sc-b`` 英文/1998/「题-sc-b」。

    走 watcher **真导入**（与生产同一条路径），故两库的书目内容确实不同 ——
    下面「按库筛选生效」与「按库热力图不跟随筛选」两个用例共用这一份数据。
    题材**按库名区分**：阅读侧的题材时长也靠它验收窄（一本书只该看到自己那个题材）。
    """
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    for lid, lang, year in (("sc-a", "zh", "2012"), ("sc-b", "en", "1998")):
        make_library(lid, lid, "ebook", src / lid)
        d = src / lid
        d.mkdir(parents=True, exist_ok=True)
        _epub(d, f"{lid}.epub", title=lid, language=lang,
              meta={"date": year, "tags": [f"题-{lid}"]})
    library.invalidate()


def test_新序列跟随按库筛选(two_libs):  # noqa: ARG001
    a = stats.overview(library_id="sc-a")
    b = stats.overview(library_id="sc-b")

    assert a["by_language"] == {"zh": 1}
    assert b["by_language"] == {"en": 1}
    assert [x["year"] for x in a["publication_yearly"]] == [2012]
    assert [x["year"] for x in b["publication_yearly"]] == [1998]
    # 体积也随库收窄：两库各一本书，各自的总量该等于自己的分格式体积
    for ov in (a, b):
        assert sum(ov["by_format_size"].values()) == ov["books"]["size"]

    # 第 33 期的四条也随库收窄（`library_metadata` 是例外，见下一个用例）
    assert all(x["total"] == 1 for x in a["metadata_fields"]), "字段覆盖率的分母要随库变成该库本数"
    assert [x["format"] for x in a["format_share_monthly"]] == ["EPUB"]
    assert [x["lag_years"] for x in a["acquisition_lag"]] == [time.localtime().tm_year - 2012]
    assert [x["lag_years"] for x in b["acquisition_lag"]] == [time.localtime().tm_year - 1998]
    # 题材：每库一本各带一个自己的题材，共现图里因此只有节点、没有弦（单本配不成对）
    assert [n["name"] for n in a["genre_cooccurrence"]["nodes"]] == ["题-sc-a"]
    assert a["genre_cooccurrence"]["links"] == []

    # 未知库 = 空集合（不 404，与 /api/duplicates 同一条惯例）
    none = stats.overview(library_id="没有这个库")
    assert none["by_language"] == {}
    assert none["by_format_size"] == {}
    assert none["publication_yearly"] == []
    assert none["pages_by_format"] == []
    assert none["format_share_monthly"] == []
    assert none["acquisition_lag"] == []
    assert none["genre_cooccurrence"] == {"nodes": [], "links": []}
    # 字段覆盖率形状不变、分母归零（不是空数组：形状随数据变会让前端写两套渲染）
    assert [x["key"] for x in none["metadata_fields"]] == list(metascore.FIELDS)
    assert all(x["total"] == 0 and x["percent"] == 0.0 for x in none["metadata_fields"])


def test_阅读侧新序列跟随按库筛选(two_libs):  # noqa: ARG001
    """会话本身没有库维度（``reading_sessions`` 只有 ``book_id``），「某库的阅读」
    全靠「这本书属于哪个库」判定 —— 这条把五个键**各自**用两库不同的数据钉一遍：
    每库的书只看到自己那次会话，串台就说明过滤漏了。
    """
    idx = {b["title"]: b["id"] for b in library.books()}
    now = time.time()
    # sc-a：30 分钟会话 + 90 天前开始读、今天读完
    db.add_session(idx["sc-a"], 1800.0, started_at=now - 1800, ended_at=now)
    db.set_progress(idx["sc-a"], 0, 50.0)
    db.set_status(idx["sc-a"], "finished", started_at=now - 90 * 86400, finished_at=now)
    # sc-b：60 分钟会话，没有读完
    db.add_session(idx["sc-b"], 3600.0, started_at=now - 3600, ended_at=now)

    a = stats.overview(library_id="sc-a")
    b = stats.overview(library_id="sc-b")

    assert [x["book_id"] for x in a["session_timeline"]] == [idx["sc-a"]]
    assert [x["book_id"] for x in b["session_timeline"]] == [idx["sc-b"]]
    assert [x["minutes"] for x in a["session_archetypes"]] == [30.0]
    assert [x["minutes"] for x in b["session_archetypes"]] == [60.0]
    assert [x["genre"] for x in a["genre_reading"]] == ["题-sc-a"]
    assert [x["genre"] for x in b["genre_reading"]] == ["题-sc-b"]
    # 时长也要跟着走：a 的题材拿到 1800 秒，b 的拿到 3600 秒
    assert [x["seconds"] for x in a["genre_reading"]] == [1800.0]
    assert [x["seconds"] for x in b["genre_reading"]] == [3600.0]
    assert [x["book_id"] for x in a["reading_pace"]] == [idx["sc-a"]]
    assert b["reading_pace"] == [], "b 那本没有进度，不该进阅读速度点集"
    assert a["completion_latency"]["total"] == 1
    assert b["completion_latency"]["total"] == 0
    assert a["completion_latency"]["median_days"] == 90.0
    # 两库各自的会话时长之和 = 该库的阅读总时长（同一份 ids 过滤，不该各走一套）
    assert a["reading"]["seconds"] == 1800.0
    assert b["reading"]["seconds"] == 3600.0


def test_按库热力图刻意不跟随统计范围(two_libs):  # noqa: ARG001
    """⚠️ ``library_metadata`` 是**唯一**不跟随 ``library_id`` 的序列（见模块头第 4 条）。

    它回答的是「哪个库的元数据更完整」——**对比**才是它的用途；跟随筛选就只剩当前库
    那一行，图直接失去意义。这条与上一条**并排**放着，就是为了让「顺手统一」的人先看到
    这个差别：同一份响应里，别的序列都收窄、只有它不收窄。
    """
    a = stats.overview(library_id="sc-a")
    rows = a["library_metadata"]

    names = {x["library_name"] for x in rows}
    assert {"sc-a", "sc-b"} <= names, "必须覆盖全部书库，而不是只看当前库"
    # 同一份响应里其余序列确实收窄了
    assert a["books"]["total"] == 1
    assert a["by_language"] == {"zh": 1}

    # 结构：行 = 库 × 字段，列顺序由后端定死（前端照单渲染，不按出现顺序自己排）
    assert len(rows) == len(names) * len(metascore.FIELDS)
    for name in ("sc-a", "sc-b"):
        assert [x["key"] for x in rows if x["library_name"] == name] == list(metascore.FIELDS)

    # 每个库的分母是**该库**的本数（不是全部书的总数），百分比能从它自己算回来
    for x in rows:
        assert x["percent"] == (round(x["present"] / x["total"] * 100, 1) if x["total"] else 0.0)
    mine = next(x for x in rows if x["library_id"] == "sc-a" and x["key"] == "title")
    assert (mine["total"], mine["present"], mine["percent"]) == (1, 1, 100.0)

    # 没有书的库（`isolated` 落的默认库）照样出行：0/0 全 0%，藏掉会让人以为库不存在
    empty = [x for x in rows if x["total"] == 0]
    assert empty, "本用例里默认库没有书 —— 它必须有行"
    assert all(x["present"] == 0 and x["percent"] == 0.0 for x in empty)


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
    # 第 33 期的五条也要真的过一遍 HTTP（序列算出来但没下发，等于没做）
    assert [x["key"] for x in body["metadata_fields"]] == list(metascore.FIELDS)
    assert set(body["genre_cooccurrence"]) == {"nodes", "links"}
    assert body["format_share_monthly"], "格式 × 月份 序列下发"
    assert body["acquisition_lag"], "出版 → 入库滞后序列下发"
    assert body["library_metadata"], "按库热力图始终有行（库存在即有）"
    # 阅读侧五条同样要过一遍 HTTP：算出来但没下发 = 没做
    assert set(body["completion_latency"]) == {
        "total", "median_days", "p75_days", "p90_days", "buckets",
    }
    assert len(body["completion_latency"]["buckets"]) == 7
    for k in ("genre_reading", "reading_pace", "session_timeline", "session_archetypes"):
        assert k in body and isinstance(body[k], list), f"{k} 没下发"


# ---------------------------------------------------------------------------
# ⑥ 第 33 期：书库侧第二批序列逐条口径
# ---------------------------------------------------------------------------

def test_逐字段覆盖率与元数据页同口径(default_root):  # noqa: ARG001
    """分母是**全部在册书**，与元数据页 ``metascore.payload()`` 的字段覆盖率是同一个数。

    两处各算各的就会出现「元数据页说出版社覆盖 50%、统计页说 33%」这种自相矛盾 ——
    故这里不重算，直接把两个来源的数字并排比一遍。
    """
    _epub(default_root, "全.epub", title="全", meta={"publisher": "社", "tags": ["科幻"]})
    _epub(default_root, "薄.epub", title="薄")
    _scan()

    ov = stats.overview()
    fields = {x["key"]: x for x in ov["metadata_fields"]}

    assert [x["key"] for x in ov["metadata_fields"]] == list(metascore.FIELDS), "字段顺序由后端定死"
    assert all(x["total"] == ov["books"]["total"] == 2 for x in ov["metadata_fields"])
    assert fields["publisher"]["present"] == 1 and fields["publisher"]["percent"] == 50.0
    assert fields["series"]["present"] == 0 and fields["series"]["percent"] == 0.0
    assert fields["title"]["percent"] == 100.0, "书名可由文件名推断，两本都有"

    page = metascore.payload()
    cov = {f["key"]: f["coverage"] for g in page["groups"] for f in g["fields"]}
    for x in ov["metadata_fields"]:
        assert x["percent"] == cov[x["key"]], f"{x['key']} 的覆盖率与元数据页对不上"


def test_题材共现按无序对记(default_root):  # noqa: ARG001
    """两本书的题材顺序相反，共现只该记**一条**弦、值为 2。

    按「书里写的顺序」记成有向对的话，(科幻,短篇) 与 (短篇,科幻) 会各记一份 ——
    弦图上同一条弦被拆成两条细的，读数直接减半。顺带钉住「书内重复题材先去重」：
    不去重的话一本书会自己跟自己配一对。
    """
    _epub(default_root, "甲.epub", title="甲", meta={"tags": ["科幻", "短篇"]})
    _epub(default_root, "乙.epub", title="乙", meta={"tags": ["短篇", "科幻", "科幻"]})
    _scan()

    chord = stats.overview()["genre_cooccurrence"]

    assert {n["name"] for n in chord["nodes"]} == {"科幻", "短篇"}
    assert all(n["count"] == 2 for n in chord["nodes"]), "书内重复题材不该抬高单本计数"
    assert chord["links"] == [{"source": "短篇", "target": "科幻", "value": 2}]


def test_题材共现节点收敛且不引用集外题材(default_root):  # noqa: ARG001
    """节点上限见 ``stats._CHORD_NODES``（12）：弦图靠弧长与弦的粗细读数，节点一多
    就糊成一团。收敛节点之后**只保留两端都在节点集里的边** —— 否则会画出指向不存在
    节点的弦（ECharts 会悄悄丢掉或画到原点，看图的人无从察觉）。
    """
    for i in range(13):
        _epub(default_root, f"g{i:02d}.epub", title=f"g{i:02d}",
              meta={"tags": [f"题材{i:02d}", f"题材{(i + 1) % 13:02d}"]})
    _scan()

    chord = stats.overview()["genre_cooccurrence"]
    names = {n["name"] for n in chord["nodes"]}

    assert len(chord["nodes"]) == 12, "节点必须收敛到 _CHORD_NODES 条"
    assert all(l["source"] in names and l["target"] in names for l in chord["links"])
    assert len(chord["links"]) < 12 * 11 // 2, "不是全连接：只留两端都在节点集里的边"


def test_格式月份交叉序列与入库月同源(default_root, make_book):  # noqa: ARG001
    """「格式 × 月份」不是另起一套口径：它的月度合计必须与 ``added_monthly`` 逐月相等。

    两处都从文件 mtime 出发 —— 哪天有人只改了其中一边的取月方式，这条会立刻炸。
    """
    _epub(default_root, "甲.epub", title="甲")
    make_book(default_root, "乙.pdf", b"%PDF")
    _scan()

    ov = stats.overview()
    share = ov["format_share_monthly"]
    now = time.localtime()

    assert sum(x["count"] for x in share) == sum(x["count"] for x in ov["added_monthly"])
    cur = [x for x in share if (x["year"], x["month"]) == (now.tm_year, now.tm_mon)]
    assert {x["format"] for x in cur} == set(ov["books"]["by_format"]), "当月的格式集合应与 by_format 一致"
    assert sum(x["count"] for x in cur) == 2


def test_入库滞后只收出版年已知的书(default_root):  # noqa: ARG001
    """滞后 = 入库年 − 出版年。「不知道出版年」≠「滞后 0 年」，故那本书**不进点集**；
    界面用 ``books.total − Σcount`` 反推未标注年份的本数写进脚注。
    """
    this_year = time.localtime().tm_year
    _epub(default_root, "老.epub", title="老", meta={"date": "2000"})
    _epub(default_root, "新.epub", title="新", meta={"date": str(this_year)})
    _epub(default_root, "无年.epub", title="无年")
    _scan()

    ov = stats.overview()
    lag = ov["acquisition_lag"]
    got = {x["lag_years"]: x["count"] for x in lag}

    assert sum(1 for b in library.books() if str(b.get("year") or "").strip()) == 2, \
        "前提：三本里只有两本标了出版年"
    assert all(x["added_year"] == this_year for x in lag), "入库年取文件 mtime 的年份"
    assert got.get(this_year - 2000) == 1
    assert got.get(0) == 1
    assert sum(x["count"] for x in lag) == 2, "无年份那本不该被当成滞后 0 混进来"
    assert ov["books"]["total"] - sum(x["count"] for x in lag) == 1, "差出来的就是未标注年份的"


# ---------------------------------------------------------------------------
# ⑦ 第 33 期：阅读侧第二批序列逐条口径
# ---------------------------------------------------------------------------

def test_完成耗时按七档落桶且分位可手算(default_root, make_book):  # noqa: ARG001
    """分档边界照搬上游 7 档（0-7 / 8-30 / 31-90 / 91-180 / 181-365 / 366-730 / 731+），
    落桶前先 round。四本各顶一档后，三个分位都能手算出来（线性插值）：
    排序后是 0 / 20 / 90 / 1000 → P50 = 20+70×0.5 = 55、P75 = 90+910×0.25 = 317.5、
    P90 = 90+910×0.7 = 727。
    """
    for i in range(4):
        make_book(default_root, f"c{i}.epub", b"EPUB")
    _scan()
    bs = library.books()
    now = time.time()
    for b, d in zip(bs, (0, 20, 90, 1000)):
        db.set_status(b["id"], "finished", started_at=now - d * 86400, finished_at=now)

    lat = stats.overview()["completion_latency"]

    assert lat["total"] == 4
    assert {x["label"]: x["count"] for x in lat["buckets"]} == {
        "0-7d": 1, "8-30d": 1, "31-90d": 1,
        "91-180d": 0, "181-365d": 0, "366-730d": 0, "731d+": 1,
    }
    # 档位边界要如实带上（界面画坐标轴用），且必须与分档表逐条对齐
    assert [(x["min_days"], x["max_days"]) for x in lat["buckets"]] == [
        (0, 7), (8, 30), (31, 90), (91, 180), (181, 365), (366, 730), (731, None),
    ]
    assert sum(x["count"] for x in lat["buckets"]) == lat["total"], "分档必须不漏不重"
    assert (lat["median_days"], lat["p75_days"], lat["p90_days"]) == (55.0, 317.5, 727.0)
    # 分位与元数据分数分布**同一套插值口径**（复用 metascore.percentile，不另立一套）
    days = [0.0, 20.0, 90.0, 1000.0]
    assert lat["p75_days"] == metascore.percentile(days, 75)


def test_完成耗时跳过结束早于开始的脏数据(default_root, make_book):  # noqa: ARG001
    """详情页允许手工修正历史日期，于是能造出「读完早于开始读」的状态行。

    这种行必须**跳过**而不是记成负数 —— 负数会把 P50 拉到 0 附近、整张图失去意义；
    上游 where 里也有 ``endedOn >= startedOn`` 这层过滤。
    """
    make_book(default_root, "x.epub", b"EPUB")
    _scan()
    bid = library.books()[0]["id"]
    now = time.time()
    db.set_status(bid, "finished", started_at=now, finished_at=now - 3 * 86400)

    lat = stats.overview()["completion_latency"]

    assert lat["total"] == 0
    assert all(x["count"] == 0 for x in lat["buckets"])
    assert lat["median_days"] is None, "没数据给 null，不是 0"


def test_完成耗时空数据给null而不是零(default_root, make_book):  # noqa: ARG001
    """⚠️ 0 天会被读成「当天就读完」，与「没有数据」是两回事。

    上游这三个字段也是 ``number | null``（空时给 null）—— 界面据此显示「—」。
    顺带钉住「开始读的日期缺失就不算」：只有 ``finished_at``、没有 ``started_at``
    的行不进分布（旧库 / 手工改库造得出这种行 —— 该列的 schema 默认值就是 0）。
    """
    make_book(default_root, "a.epub", b"EPUB")
    make_book(default_root, "b.epub", b"EPUB")
    _scan()
    a, b = library.books()[0]["id"], library.books()[1]["id"]
    now = time.time()
    # 手工造一行旧形状：不给 started_at，落 schema 默认值 0
    c = db._connect()
    c.execute(
        "INSERT INTO reading_status(book_id, status, finished_at, updated_at) VALUES(?,?,?,?)",
        (a, "finished", now, now),
    )
    c.commit()
    lat = stats.overview()["completion_latency"]
    assert lat["total"] == 0, "缺开始日期就不是一段可测的完成耗时"

    # 真给一段：当天读完 → 落在第一档，分位是 0.0（真数据，不是 null）
    db.set_status(b, "finished", started_at=now, finished_at=now)
    lat = stats.overview()["completion_latency"]
    assert lat["total"] == 1
    assert lat["median_days"] == 0.0, "真是当天读完就是 0，与「没数据」的 null 区分开"
    assert {x["label"]: x["count"] for x in lat["buckets"]}["0-7d"] == 1


def test_题材阅读时长把一本书算进它的每个题材(default_root):  # noqa: ARG001
    """⚠️ **扇出**：一本书的整段时长计入它的每个题材（与上游内连接后 ``SUM`` 同义）。

    故各题材之和 ≥ 打题材那些书的实际总时长 —— 界面脚注要写明，否则会被当成
    「时长算重了」的 bug。同时钉住两件事：
    - 书内重复的题材先去重（一本书不该把自己的时长算两遍）；
    - **没打题材的书完全不进这张图**（题材是它唯一的维度），它那段时间不在图里。
    """
    _epub(default_root, "多.epub", title="多", meta={"tags": ["科幻", "短篇"]})
    _epub(default_root, "单.epub", title="单", meta={"tags": ["科幻", "科幻"]})
    _epub(default_root, "无.epub", title="无")
    _scan()
    idx = {b["title"]: b["id"] for b in library.books()}
    now = time.time()
    for title, sec in (("多", 600.0), ("单", 300.0), ("无", 900.0)):
        db.add_session(idx[title], sec, started_at=now - sec, ended_at=now)

    genre = stats.overview()["genre_reading"]

    assert genre == [{"genre": "科幻", "seconds": 900.0}, {"genre": "短篇", "seconds": 600.0}], \
        "按秒数降序，且重复题材只算一遍"
    assert sum(x["seconds"] for x in genre) == 1500.0 > 600.0 + 300.0, \
        "600 秒被科幻与短篇各记一次（扇出）"
    assert sum(x["seconds"] for x in genre) < 600.0 + 300.0 + 900.0, \
        "没打题材那本的 900 秒完全不进图"


def test_题材阅读时长只收一年内的会话(default_root, make_book):  # noqa: ARG001
    """窗口 365 天（上游 ``GENRE_READING_TIME_DEFAULT_DAYS``），与取数窗口（5 年）
    **不是一回事** —— 会话明细取 5 年是给会话时间轴用的，这里再按 365 天筛一遍。
    """
    _epub(default_root, "旧.epub", title="旧", meta={"tags": ["科幻"]})
    _scan()
    bid = library.books()[0]["id"]
    now = time.time()
    db.add_session(bid, 600.0, started_at=now - 400 * 86400, ended_at=now - 400 * 86400)

    assert stats.overview()["genre_reading"] == [], "400 天前的会话出了 365 天窗"

    db.add_session(bid, 300.0, started_at=now - 10 * 86400, ended_at=now - 10 * 86400)
    assert [x["seconds"] for x in stats.overview()["genre_reading"]] == [300.0]


def test_阅读速度按书聚合且不编造进度增量(default_root, make_book):  # noqa: ARG001
    """⚠️ 口径与上游**不同**（见模块头）：上游要 per-session 的 ``progressDelta``，
    本项目的 ``reading_sessions`` 没有那一列、历史会话也补不回来。与其编一个增量，
    这里换成「按书聚合」—— 累计时长 × 当前进度，形状同义、读数不同。

    故这条用例钉的是**本项目自己的口径**：同一本书的多次会话要**先合计再画一个点**，
    点里**不许出现 ``progressDelta``**（编出来的字段比没有更糟）。
    """
    for i in range(3):
        make_book(default_root, f"p{i}.epub", b"EPUB")
    _scan()
    bs = library.books()
    now = time.time()
    # 第一本两次会话合计 1800 秒、进度 40%
    db.add_session(bs[0]["id"], 600.0, started_at=now - 1800, ended_at=now - 1200)
    db.add_session(bs[0]["id"], 1200.0, started_at=now - 1200, ended_at=now)
    db.set_progress(bs[0]["id"], 0, 40.0)
    # 第二本只读了 60 秒但读完了 → 排在后面
    db.add_session(bs[1]["id"], 60.0, started_at=now - 60, ended_at=now)
    db.set_progress(bs[1]["id"], 0, 100.0)
    # 第三本有进度但没读过 → 不进点集（0 秒的点全挤在 y 轴左侧，没有读数意义）

    pace = stats.overview()["reading_pace"]

    assert [x["book_id"] for x in pace] == [bs[0]["id"], bs[1]["id"]], "按累计时长降序"
    assert pace[0] == {
        "book_id": bs[0]["id"], "title": "p0", "format": "EPUB",
        "seconds": 1800.0, "percent": 40.0,
    }, "同一本的两次会话要合计成一个点；字段固定，没有 progressDelta"


def test_会话时间轴按结束时间倒序并带书名格式(default_root):  # noqa: ARG001
    """只读周视图的数据面：新 → 旧，带书名 / 格式供 tooltip 用。

    ⚠️ 上游那张图是**能拖拽改会话时间的编辑器**（拖动写库），本期只做只读 ——
    这条用例顺带钉住「下发的字段里没有写接口要的东西」，免得有人以为已经能拖了。
    """
    _epub(default_root, "甲.epub", title="甲")
    _scan()
    bid = library.books()[0]["id"]
    now = time.time()
    db.add_session(bid, 100.0, started_at=now - 1000, ended_at=now - 900)
    db.add_session(bid, 200.0, started_at=now - 200, ended_at=now - 100)

    tl = stats.overview()["session_timeline"]

    assert [x["seconds"] for x in tl] == [200.0, 100.0], "按 ended_at 倒序（最近的在最前）"
    assert tl[0] == {
        "book_id": bid, "title": "甲", "format": "EPUB",
        "started_at": tl[0]["started_at"], "ended_at": tl[0]["ended_at"],
        "seconds": 200.0,
    }
    assert tl[0]["ended_at"] > tl[1]["ended_at"]


def test_会话形态只收五分钟以上且按开始时刻定档(default_root, make_book):  # noqa: ARG001
    """三条收敛（都照上游）：只收 ≥300 秒的会话、窗口 365 天、最多 2000 点。

    这里钉最容易错的两条：
    - **300 秒是「收」**，299 秒不收（边界照上游 ``durationSeconds >= 300``）；
    - 小时数与星期都按**开始时刻**算 —— 跨零点的会话按结束时刻算会被记成次日凌晨，
      整张「我几点读得多」的图就歪了。
    """
    make_book(default_root, "a.epub", b"EPUB")
    _scan()
    bid = library.books()[0]["id"]
    now = time.time()
    lt = time.localtime(now)
    # 昨天 23:50 开始、今天 00:10 结束（跨零点）
    cross = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - 1, 23, 50, 0, 0, 0, -1))
    db.add_session(bid, 1200.0, started_at=cross, ended_at=cross + 1200)
    db.add_session(bid, 299.0, started_at=now - 400, ended_at=now - 300)   # 差 1 秒 → 不收
    db.add_session(bid, 300.0, started_at=now - 200, ended_at=now - 100)   # 正好 5 分钟 → 收
    db.add_session(bid, 900.0, started_at=now - 400 * 86400, ended_at=now - 400 * 86400)

    arch = stats.overview()["session_archetypes"]

    assert sorted(x["minutes"] for x in arch) == [5.0, 20.0], "只有 300 秒 / 20 分钟两次进图"
    twenty = next(x for x in arch if x["minutes"] == 20.0)
    assert twenty["hour"] == 23.83, "小时按开始时刻算（23:50 → 23.83，不是次日的 0.17）"
    five = next(x for x in arch if x["minutes"] == 5.0)
    five_lt = time.localtime(now - 200)
    assert five["hour"] == round(five_lt.tm_hour + five_lt.tm_min / 60.0, 2), "小数小时"
    assert all(0 <= x["hour"] < 24 and 0 <= x["weekday"] <= 6 for x in arch)
    # 星期索引与 weekdays 序列**同一套**（0 = 周日）：同一个会话在两处的落点必须一致
    assert stats.overview()["weekdays"][five["weekday"]]["seconds"] >= 300.0
