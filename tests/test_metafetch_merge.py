"""第 58 期：跨源字段级合并（`metafetch.merge_*`）契约。

## 这个文件真正在防什么

合并的**收益**是「字段更全」，**风险**是「把同名不同书的字段拼起来」—— 那会造出一个
真实存在过但从未出版过的组合，且**不可逆**（写进库后没人知道哪一半是错的）。所以：

1. **门槛必须真的挡住**：相对门槛（距最佳候选太远）与绝对门槛（压根不像同一本）各测一条；
   门槛挡住时**逐字回到旧行为**（只用最佳候选）—— 这是「可回退」的底线；
2. **择优规则必须可预期**：信任源插队（年份信 Open Library）与分数优先都要钉住；
   题材是**合并**（多源去重）而不是择优，这是它与其它字段不同的地方；
3. **合并只改「选值」，不改「写不写」**：字段策略 / 锁定 / 用户覆盖这三道闸在合并之后照旧。

盯的是 `plan()` 出参里**逐字段的 `source` 与 `merged_from`**，而不是屏幕上的字。
"""
from novelforge.core import metafetch


def cand(source, score, **kw):
    """一条候选（形状与 `metasources._entry` 一致，只填测试用得到的字段）。"""
    base = {"source": source, "title": "Dune", "author": "Frank Herbert", "publisher": "",
            "year": "", "language": "", "isbn": "", "description": "", "tags": [],
            "cover_url": "", "score": score}
    base.update(kw)
    return base


def _plan(monkeypatch, entries, merge=True, locked=(), overridden=(),
          book_extra=None, fields=None):
    book = {"id": "b1", "name": "dune.epub", "title": "Dune", "author": "Frank Herbert",
            "library_id": "", "format": "EPUB"}
    # `book_extra`：给书对象预置**已有值**（形状与 `library._apply_overlay` 并进去的一致），
    # 用来测 `fill_only` 那类「原值非空就不动」的分支。
    if book_extra:
        book.update(book_extra)
    monkeypatch.setattr(metafetch.library, "books", lambda *a, **k: [book])
    monkeypatch.setattr(metafetch.metasources, "search_by_isbn", lambda *a, **k: None)
    monkeypatch.setattr(metafetch.metasources, "search_all",
                        lambda *a, **k: {"entries": list(entries), "sources": {},
                                         "best": entries[0] if entries else None})
    monkeypatch.setattr(metafetch.db, "all_overrides",
                        lambda: {"b1": {f: "user" for f in overridden}})
    monkeypatch.setattr(metafetch.db, "all_locks", lambda: {"b1": set(locked)})
    cfg = {"metadata_fetch": {"enabled": True, "sources": ["openlibrary", "googlebooks"],
                              "threshold": 0.75, "merge_sources": merge,
                              "fields": dict(fields or {}), "genre_blocklist": []}}
    return metafetch.plan(names=["dune.epub"], cfg=cfg)["items"][0]


def _srcs(item):
    return {f: v["source"] for f, v in item["changes"].items()}


def test_信任表的键必须是合法字段名():
    """`FIELD_TRUST` 的键写成书对象里的名字（`year`）**不会报错、只会静默失效**。

    这条就是防这一类：查不到 ⇒ 退回按分数排 ⇒ 表面上「合并还在工作」，实际上信任表形同虚设。
    """
    valid = set(metafetch._VALUE_KEYS) | {"cover"}

    assert set(metafetch.FIELD_TRUST) <= valid, set(metafetch.FIELD_TRUST) - valid
    assert "date" in metafetch.FIELD_TRUST and "year" not in metafetch.FIELD_TRUST


def test_缺字段由次优源补上_逐字段记来源(isolated, monkeypatch):  # noqa: ARG001
    item = _plan(monkeypatch, [
        cand("openlibrary", 0.95, year="1965", language="en"),
        cand("googlebooks", 0.9, description="沙丘简介", cover_url="https://x/g.jpg"),
    ])

    assert item["merged_from"] == ["openlibrary", "googlebooks"]
    srcs = _srcs(item)
    assert srcs["date"] == "openlibrary" and srcs["language"] == "openlibrary"
    assert srcs["description"] == "googlebooks", "A 没有的字段必须从 B 补上"
    assert item["changes"]["description"]["score"] == 0.9, "来源分数要如实带出"
    assert item["cover"] and item["cover"]["source"] == "googlebooks"


def test_低于相对门槛的候选不参与(isolated, monkeypatch):  # noqa: ARG001
    """最佳 0.95 ⇒ 门槛 = max(0.7, 0.9×0.95=0.855)；0.8 的那条不够格。"""
    item = _plan(monkeypatch, [
        cand("openlibrary", 0.95, year="1965"),
        cand("googlebooks", 0.8, description="别人的简介", cover_url="https://x/x.jpg"),
    ])

    assert item["merged_from"] == [], "不能把明显不够像的候选混进来"
    assert "description" not in item["changes"]
    assert _srcs(item)["date"] == "openlibrary"
    assert item["cover"] is None


def test_最佳候选自己都低于绝对门槛则不合并(isolated, monkeypatch):  # noqa: ARG001
    item = _plan(monkeypatch, [
        cand("openlibrary", 0.6, year="1965"),
        cand("googlebooks", 0.59, description="简介"),
    ])

    assert item["merged_from"] == []
    assert _srcs(item)["date"] == "openlibrary"


def test_题材多源合并去重且过黑名单(isolated, monkeypatch):  # noqa: ARG001
    item = _plan(monkeypatch, [
        cand("openlibrary", 0.95, tags=["科幻", "太空歌剧", "小说"]),
        cand("googlebooks", 0.92, tags=["科幻", "冒险", "小说"]),
    ])
    book = {"tags": [], "genre_blocklist": []}

    assert item["merged_from"] == ["openlibrary", "googlebooks"]
    # 去重保序 + 上限；黑名单（「小说」在默认黑名单里）在本用例的 cfg 未开黑名单，
    # 所以这里只验「去重保序」，黑名单过滤由 _candidate_values 的老用例覆盖。
    assert item["changes"]["tags"]["to"] == ["科幻", "太空歌剧", "小说", "冒险"]


def test_演播者只取一家不跨源拼(isolated, monkeypatch):  # noqa: ARG001
    """第 103 期：演播者是**版本属性**，与题材相反 —— **只取一家**。

    两个源报的常常是两次不同录音（甚至不同语言版本）的阵容；拼起来会造出一份
    **从未存在过**的名单，而且写进库后没人能看出哪一半是错的（与「同名不同书」
    的污染同一类风险）。所以这里断言的是：结果**恰好等于**某一个源的名单。
    """
    item = _plan(monkeypatch, [
        cand("audible", 0.95, narrators=["Scott Brick", "Euan Morton"]),
        cand("audnexus", 0.93, narrators=["Simon Vance"]),
    ])

    assert item["merged_from"] == ["audible", "audnexus"], "两家都够格参与合并"
    assert item["changes"]["narrators"]["to"] == ["Scott Brick", "Euan Morton"], "取一家，不拼"
    assert item["changes"]["narrators"]["source"] == "audible"


def test_演播者首位源为空则顺延到下一家(isolated, monkeypatch):  # noqa: ARG001
    item = _plan(monkeypatch, [
        cand("audible", 0.95),
        cand("audnexus", 0.93, narrators=["Simon Vance"]),
    ])

    assert item["changes"]["narrators"]["to"] == ["Simon Vance"]


def test_关掉开关逐字回到旧行为(isolated, monkeypatch):  # noqa: ARG001
    item = _plan(monkeypatch, [
        cand("openlibrary", 0.95, year="1965"),
        cand("googlebooks", 0.94, description="简介", cover_url="https://x/g.jpg"),
    ], merge=False)

    assert item["merged_from"] == []
    assert "description" not in item["changes"], "关掉后不能再用次优源补字段"
    assert _srcs(item)["date"] == "openlibrary"


def test_信任源在同分时插队(isolated, monkeypatch):  # noqa: ARG001
    """年份信 Open Library —— 即使 Google Books 排在前面（源顺序）且分数相同。"""
    item = _plan(monkeypatch, [
        cand("googlebooks", 0.9, year="1965"),
        cand("openlibrary", 0.9, year="1965"),
    ])

    assert item["merged_from"] == ["googlebooks", "openlibrary"]
    assert _srcs(item)["date"] == "openlibrary"


def test_合并只改选值_策略与锁定照旧(isolated, monkeypatch):  # noqa: ARG001
    """锁定 / 用户改过是**写不写**的闸，压在合并的选值之上。"""
    item = _plan(monkeypatch, [
        cand("openlibrary", 0.95, year="1965"),
        cand("googlebooks", 0.94, description="简介", publisher="Ace"),
    ], locked=("description",), overridden=("publisher",))

    srcs = _srcs(item)
    assert "description" not in srcs, "锁定的字段不产生改动（不管候选多好）"
    assert "publisher" not in srcs, "用户改过的字段不覆盖"
    assert srcs["date"] == "openlibrary"
    assert "description" in item["locked"]


def test_online_candidate_与plan同一套规则(isolated, monkeypatch):  # noqa: ARG001
    """详情页的「在线建议」必须与抓取预览口径一致（否则同一数据两种答案）。"""
    book = {"id": "b1", "name": "dune.epub", "title": "Dune", "author": "Frank Herbert",
            "library_id": ""}
    entries = [cand("openlibrary", 0.95, year="1965"),
               cand("googlebooks", 0.9, description="沙丘简介")]
    monkeypatch.setattr(metafetch.metasources, "search_by_isbn", lambda *a, **k: None)
    monkeypatch.setattr(metafetch.metasources, "search_all",
                        lambda *a, **k: {"entries": entries, "sources": {},
                                         "best": entries[0]})
    cfg = {"metadata_fetch": {"enabled": True, "sources": ["openlibrary", "googlebooks"],
                              "merge_sources": True}}

    out = metafetch.online_candidate(book, cfg=cfg)

    assert out["values"]["date"] == "1965" and out["values"]["description"] == "沙丘简介"
    assert out["merged_from"] == ["openlibrary", "googlebooks"]
    assert out["field_sources"]["description"] == "googlebooks"
    assert out["field_sources"]["date"] == "openlibrary"


# ---------------- 副标题（第 113 期：Audible 顶层 `subtitle` 接线）----------------

def test_副标题只在空着的书上补(isolated, monkeypatch):  # noqa: ARG001
    """候选里带 `subtitle` ⇒ 默认策略（fill_only）下，没副标题的书会被补上。"""
    item = _plan(monkeypatch, [cand("audible", 0.95, subtitle="Book 1 of the Dune Saga")],
                 fields={"subtitle": "fill_only"})

    assert item["changes"]["subtitle"]["to"] == "Book 1 of the Dune Saga"
    assert item["changes"]["subtitle"]["source"] == "audible", "来源要如实带出"


def test_副标题已有值时不覆盖(isolated, monkeypatch):  # noqa: ARG001
    """书**已经有**副标题 ⇒ fill_only 跳过；同一份候选换 overwrite 就会换掉。

    钉的是**两条策略的差异**：`fill_only` 曾经是空转（没有任何源填过 subtitle），
    接线之后它才真正意味着「只在没有副标题的书上补」。已有值可能是用户手工改的、
    也可能是上一次抓来的 —— 两者都会经 `library._apply_overlay` 并进书对象。
    """
    cands = [cand("audible", 0.95, subtitle="Book 1 of the Dune Saga")]
    have = {"subtitle": "沙漠星球"}

    kept = _plan(monkeypatch, cands, book_extra=have, fields={"subtitle": "fill_only"})
    assert "subtitle" not in kept["changes"], "原值非空 ⇒ 默认不动"

    changed = _plan(monkeypatch, cands, book_extra=have, fields={"subtitle": "overwrite"})
    assert changed["changes"]["subtitle"]["from"] == "沙漠星球"
    assert changed["changes"]["subtitle"]["to"] == "Book 1 of the Dune Saga"
