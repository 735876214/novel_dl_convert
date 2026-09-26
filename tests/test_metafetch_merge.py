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


def _plan(monkeypatch, entries, merge=True, locked=(), overridden=()):
    book = {"id": "b1", "name": "dune.epub", "title": "Dune", "author": "Frank Herbert",
            "library_id": "", "format": "EPUB"}
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
                              "fields": {}, "genre_blocklist": []}}
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
