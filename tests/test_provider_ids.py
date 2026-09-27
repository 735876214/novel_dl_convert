"""第 63 期：副标题与 9 个**提供商 ID**（对齐上游 Book Orbit 的 CATALOG 组）。

## 这个文件真正在防什么

「让抓取真填 ID」这件事有**两种失败方式**，且都不报错：

1. **填错**：把一个 URL、或者**别家**的 ID 记进 ``*_id`` 字段。用户看到的是一个格式
   合法的字符串，没有任何迹象表明它是错的 —— 比留空糟得多。所以有一条**反造假**
   判据：候选只认自己那一家的标识（``metafetch._cand_value``）。
2. **填不上**：fetcher 里取了 ``provider_id``，但**上游返回里根本没请求那个字段**
   （Hardcover 的 GraphQL 选择集就是这样，漏了 ``id`` 只会永远拿到 ``None``）。
   这类靠「**选择集字面量**」的断言钉住，光测解析函数的输入输出是测不到的。

另一半是**评分的账**：``metascore.FIELDS`` 加字段就必须仍合 100，否则统计页上
「完整度分」整个失真 —— 而且失真是静默的（一个 91 分的书看着挺正常）。

## 边界（刻意，不是漏）

只有 9 家源有 ID 字段。另外 4 家（comicvine / ranobedb / librofm / lubimyczytac）
抓到的只是**页面 URL**，本项目没给它们开字段 —— ``_entry`` 会把它们的 ``provider_id``
清空（见 ``test_没有对应字段的源_它的标识不会漏进别的字段``）。
"""
import pytest

from novelforge.core import fileops, metafetch, metascore, metasources, metastore

#: 元数据面的 9 个提供商 ID 字段（顺序即 fileops 里的声明顺序）
IDS = list(fileops.PROVIDER_ID_FIELDS)


# ---------------------------------------------------------------------------
# ① 字段表本身
# ---------------------------------------------------------------------------

def test_九个提供商id都进了可编辑字段集():
    assert len(IDS) == 9
    assert set(IDS) <= set(fileops.METADATA_FIELDS)
    assert "subtitle" in fileops.METADATA_FIELDS


def test_提供商id与副标题都进了抓取引擎的字段表():
    """没进 `_VALUE_KEYS` ⇒ 抓到了也**不会被算进 changes**（静默丢弃）。"""
    for f in [*IDS, "subtitle"]:
        assert f in metafetch._VALUE_KEYS, f
        assert f in metafetch._FINALIZE_FIELDS, f


def test_每个有id字段的源都映射到唯一一个字段():
    """`SOURCE_ID_FIELD` 的**值**必须落在真实字段上；且 audnexus 与 audible 共用
    同一个 ASIN 字段（两家是同一份数据的两个入口，没有区分的意义）。"""
    assert set(metasources.SOURCE_ID_FIELD.values()) == set(IDS)
    assert metasources.SOURCE_ID_FIELD["audnexus"] == metasources.SOURCE_ID_FIELD["audible"]
    assert metasources.SOURCE_ID_FIELD["amazon"] == "amazon_id"


def test_没有对应字段的源_它的标识不会漏进别的字段():
    """comicvine / ranobedb / librofm / lubimyczytac 只抓到页面 URL，本项目没给它们
    开字段。`_entry` 必须把它们的 `provider_id` **清空** —— 否则这个值会挂在候选上，
    等着哪天有人给它随便挑一个字段塞进去。"""
    for src in ("comicvine", "ranobedb", "librofm", "lubimyczytac"):
        e = metasources._entry(src, title="书", provider_id="https://example.com/x/1")
        assert e["provider_field"] == "", src
        assert e["provider_id"] == "", src


# ---------------------------------------------------------------------------
# ② 各家 fetcher 真的填了（含「上游有没有返回这个字段」）
# ---------------------------------------------------------------------------

def test_hardcover_的_graphql_选择集真的请求了_id():
    """⚠️ 这条不是形式主义：``_hardcover_entry`` 读 ``b.get("id")``，而 Hardcover
    是 GraphQL —— **选择集里没写的字段不会返回**。漏了它只会永远拿到 ``None``，
    表现为「Hardcover 抓得到书名作者，就是没有 ID」，没有任何报错。
    """
    q = metasources._HARDCOVER_Q
    body = q.split("{", 1)[1]
    assert " id" in body.split("contributions")[0], "books 选择集里没有 id"


def test_hardcover_条目取数字id而不是slug():
    e = metasources._hardcover_entry({"id": 4321, "title": "Dune", "slug": "dune"})
    assert e["provider_field"] == "hardcover_id"
    assert e["provider_id"] == "4321"
    assert e["raw_id"] == "dune"          # slug 仍是定位串，只是不冒充 ID


@pytest.mark.parametrize("href,want", [
    ("/book/show/12345", "12345"),
    ("/book/show/12345.Dune", "12345"),
    ("/book/show/Dune", ""),          # 老式路径没有数字 → 留空，不拿路径充数
    ("", ""),
])
def test_goodreads_从书目路径抠数字id(href, want):
    assert metasources._goodreads_id(href) == want


@pytest.mark.parametrize("d,want", [
    ({"slug": "dune"}, "dune"),
    ({"url": "https://www.kobo.com/us/en/ebook/dune-1"}, "dune-1"),
    ({"href": "https://www.kobo.com/us/en/audiobook/dune"}, "dune"),
    ({"url": "https://www.kobo.com/us/en/browse"}, ""),   # 不是书目页 → 留空
    ({}, ""),
])
def test_kobo_取详情页末段作标识(d, want):
    """Kobo 不对外给数字 ID（它用 URL 里的 slug 定位）。取不到就留空。"""
    assert metasources._kobo_id(d) == want


def test_条目的标识只属于它自己那个字段():
    e = metasources._entry("googlebooks", title="三体", provider_id="zyTCAlFPjgYC")
    assert e["provider_field"] == "google_books_id"
    assert e["provider_id"] == "zyTCAlFPjgYC"


# ---------------------------------------------------------------------------
# ③ 反造假：别家的 ID 不许填进来
# ---------------------------------------------------------------------------

def cand(source, score, **kw):
    """一条候选（形状与 `metasources._entry` 一致）。"""
    base = {"source": source, "title": "Dune", "author": "Frank Herbert", "publisher": "",
            "year": "", "language": "", "isbn": "", "description": "", "tags": [],
            "cover_url": "", "raw_id": "", "provider_field": "", "provider_id": "",
            "score": score}
    base.update(kw)
    return base


def test_取候选值时_提供商id只认它自己那一项():
    """`_cand_value` 的判据。Google Books 的候选带着自己的卷 ID，
    它**不**该给出一个 `goodreads_id` —— 哪怕候选对象上恰好有个同名字段。"""
    gb = cand("googlebooks", 0.9, provider_field="google_books_id", provider_id="zyTCAlFPjgYC")

    assert metafetch._cand_value(gb, "google_books_id", "google_books_id") == "zyTCAlFPjgYC"
    assert metafetch._cand_value(gb, "goodreads_id", "goodreads_id") == ""
    # 普通字段照旧走 key（不受影响）
    assert metafetch._cand_value(gb, "title", "title") == "Dune"


def test_别家的候选不会污染_id字段(isolated, monkeypatch):  # noqa: ARG001
    """端到端复述上一条：只问到了 Google Books，`changes` 里就**只有**
    `google_books_id`，不许凭空多出 8 个空改动（空改动会被写成「清空」语义）。"""
    item = _plan(monkeypatch, [
        cand("googlebooks", 0.95, provider_field="google_books_id", provider_id="zyTCAlFPjgYC"),
    ])
    assert item["changes"]["google_books_id"]["to"] == "zyTCAlFPjgYC"
    for other in IDS:
        if other != "google_books_id":
            assert other not in item["changes"], other


def _plan(monkeypatch, entries, fields=None, **over):
    book = {"id": "b1", "name": "dune.epub", "title": "Dune", "author": "Frank Herbert",
            "library_id": "", "format": "EPUB", "isbn": ""}
    monkeypatch.setattr(metafetch.library, "books", lambda *a, **k: [book])
    monkeypatch.setattr(metafetch.metasources, "search_by_isbn", lambda *a, **k: None)
    monkeypatch.setattr(metafetch.metasources, "search_all",
                        lambda *a, **k: {"entries": list(entries), "sources": {},
                                         "best": entries[0] if entries else None})
    monkeypatch.setattr(metafetch.db, "all_overrides", lambda: {})
    monkeypatch.setattr(metafetch.db, "all_locks", lambda: {})
    cfg = {"metadata_fetch": {"enabled": True, "sources": ["googlebooks"],
                              "threshold": 0.75, "merge_sources": False,
                              "fields": fields if fields is not None else {},
                              "genre_blocklist": []}}
    cfg["metadata_fetch"].update(over)
    return metafetch.plan(names=["dune.epub"], cfg=cfg)["items"][0]


# ---------------------------------------------------------------------------
# ④ 写策略：老配置里没有新字段的键时，别把预设静默作废
# ---------------------------------------------------------------------------

def test_老配置缺新字段的键时_整表同档就按那个档走():
    """`config.load_config` 对 `fields` 是**整体替换**。第 63 期之前存过
    「仅用内嵌（不下载远程字段）」的用户，他配置里只有当时那 9 个键 ——
    新字段若一律按 `DEFAULT_POLICY`(overwrite) 处理，那个预设就**静默作废**了
    （明明选了不下载远程字段，却仍然写回 9 个在线 ID）。
    """
    old = {k: "skip" for k in ["title", "author", "publisher", "year",
                               "language", "isbn", "description", "tags", "cover"]}
    for f in [*IDS, "subtitle"]:
        assert metafetch._field_policy(old, f) == "skip", f


def test_逐字段调过的表_缺失键回落默认():
    """表里值不一致 ⇒ 还原不出预设意图 ⇒ 不猜，按 DEFAULT_POLICY。"""
    mixed = {"title": "skip", "author": "overwrite"}
    assert metafetch._field_policy(mixed, "google_books_id") == metafetch.DEFAULT_POLICY
    # 表里写了就以表为准
    assert metafetch._field_policy(mixed, "title") == "skip"


def test_逐字段策略对提供商id照旧生效(isolated, monkeypatch):  # noqa: ARG001
    """三道闸里的「字段策略」这一道对 ID 同样成立 —— 不是新字段就绕过去了。"""
    # 书名给一个与书本现值**不同**的值：`plan` 会丢掉「值没变」的改动，
    # 拿书名当对照就必须让它真的有变化，否则测的是「没差异」而不是「策略生效」
    entries = [cand("googlebooks", 0.95, title="Dune (Deluxe)",
                    provider_field="google_books_id", provider_id="zyTCAlFPjgYC")]
    item = _plan(monkeypatch, entries,
                 fields={"google_books_id": "skip", "title": "overwrite"})
    assert "google_books_id" not in item["changes"]
    assert item["changes"]["title"]["to"] == "Dune (Deluxe)"


# ---------------------------------------------------------------------------
# ⑤ 落库：ID 没有 OPF 原值，这条要有据可依
# ---------------------------------------------------------------------------

def test_提供商id存进覆盖后_编辑器的分层状态正确(isolated, default_root):  # noqa: ARG001
    """`metastore.state` 对每个字段都给 `value / online / opf / overridden`。

    提供商 ID **没有 OPF 对应物**（`fileops.patch_opf_meta` 只认它那串 if/elif），
    所以 `opf` 必须是空串 —— 「恢复在线」对它们就等于「回落到在线值、没有就为空」。
    这条同时钉住三处同集合：字段若没进 `db._META_FIELDS`，覆盖根本读不回来。
    """
    from novelforge.core import db, epub_builder
    p = default_root / "三体.epub"
    epub_builder.build_epub({"title": "三体", "author": "刘慈欣", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(p))
    bid = "lib$test"
    db.set_override(bid, "google_books_id", "zyTCAlFPjgYC")

    st = metastore.state({"id": bid, "name": "三体.epub"})
    assert st["google_books_id"]["value"] == "zyTCAlFPjgYC"
    assert st["google_books_id"]["overridden"] is True
    assert st["google_books_id"]["opf"] == ""


# ---------------------------------------------------------------------------
# ⑥ 评分的账：加字段之后权重仍合 100，且 ID 真的参与计分
# ---------------------------------------------------------------------------

def test_权重仍然是100且各组与文档一致():
    assert round(sum(w for _g, w, _l in metascore.FIELDS.values()), 6) == 100.0
    group = round(sum(w for g, w, _l in metascore.FIELDS.values() if g == "provider_ids"), 6)
    assert group == 10.0
    # 9 个来源 ID 都在计分表里（漏一个就是「页面上一排永远 0 分的行」的反面：
    # 填了也不涨分，用户会以为抓取没生效）
    assert set(IDS) <= set(metascore.FIELDS)


def test_填一个来源id会涨分且ISBN比它值钱():
    """判据力的**正例**：只测「权重合 100」是恒真的（把 9 个字段全设成 0 分也合 100）。
    必须有「填了就涨分」和「ISBN 更值钱」两条，权重表才不是一纸空文。"""
    base = {"id": "b1", "name": "x.epub", "title": "书", "author": "作者", "format": "EPUB"}
    s0 = metascore.audit(dict(base))["score"]
    s_id = metascore.audit({**base, "google_books_id": "zyTCAlFPjgYC"})["score"]
    s_isbn = metascore.audit({**base, "isbn": "9787536692930"})["score"]

    assert s_id > s0
    assert s_isbn > s_id, "ISBN 必须比单个来源 ID 值钱（见 metascore 的权重说明）"
    # 一个 ISBN(5.5) 比「9 个来源 ID 全填满」(4.5) 还多 —— 这正是想要的读法
    all_ids = metascore.audit({**base, **{f: "x" for f in IDS}})["score"]
    assert s_isbn > all_ids


def test_副标题不计分且理由已改口径():
    """第 63 期之前这条写的是「本项目元数据面没有这个字段」—— 现在**已经有**了，
    那句话变成了假话。不计分的理由换成如实的那条。"""
    keys = {n["key"] for n in metascore.NOT_SCORED}
    assert "subtitle" in keys
    why = next(n["why"] for n in metascore.NOT_SCORED if n["key"] == "subtitle")
    assert "没有这个字段" not in why
