"""第 60 期：**按书籍语种自动重排来源顺序**的契约。

要钉住的四件事（每一条都对应一个「做错了会静默出错」的点）：

1. **稳定分档**：专精本语种 (0) → 多语种通吃 (1) → 专精别的语种 (2)；**档内保持用户设的顺序**
   （`sorted` 稳定）—— 否则「重排」会变成「覆盖用户配置」；
2. **只排序、不筛源**：任何启用的家都不会因为语种被丢掉（专精别的语种的家只是排后面）；
3. **不猜**：语种未知 / 空 / 开关关闭 ⇒ **原样返回**；
4. **三处口径一致**：`plan`（逐本）、`online_candidate`（单本）、`series`（成员书投票）。

`LANG_AFFINITY` / `LANG_BROAD` 是**人工判断表**，所以还钉一条「完整性」契约：
每家源必须显式表态（专精某些语种，或通吃），新增源不能默默漏过。
"""
import copy

import pytest

import novelforge.core.metasources as m


def _cfg(**mf):
    """测试用配置：**深拷贝** DEFAULTS 再改 —— 直接改 `config.DEFAULTS` 会污染别的用例。"""
    from novelforge import config

    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["metadata_fetch"].update(mf)
    return cfg


# ---------------- 亲和表本身 ----------------

def test_每家源都显式表过态():
    """`LANG_AFFINITY ∪ LANG_BROAD == SOURCES` 且不相交：新增一家源必须想清楚它的语种定位。"""
    affinity, broad = set(m.LANG_AFFINITY), set(m.LANG_BROAD)
    assert affinity & broad == set(), affinity & broad
    assert affinity | broad == set(m.SOURCES), set(m.SOURCES) ^ (affinity | broad)


def test_亲和表的语种码是归一后的短码():
    for sid, langs in m.LANG_AFFINITY.items():
        assert sid in m.SOURCES, sid
        for code in langs:
            assert code == m._lang_of(code) and len(code) == 2, (sid, code)


# ---------------- 分档与排序 ----------------

@pytest.mark.parametrize("source,lang,tier", [
    ("aladin", "ko", 0), ("aladin", "zh", 2), ("lubimyczytac", "pl", 0),
    ("ranobedb", "ja", 0), ("audible", "en", 0), ("audible", "zh", 2),
    ("googlebooks", "zh", 1), ("openlibrary", "ja", 1), ("kobo", "ko", 1),
])
def test_分档(source, lang, tier):
    assert m.language_tier(source, lang) == tier


def test_按语种稳定重排_档内保持用户顺序():
    # 用户设的顺序故意「反着来」：通吃在前、专精韩语在后
    order = ["googlebooks", "openlibrary", "aladin", "lubimyczytac", "ranobedb"]

    ko = m.reorder_for_language(order, "ko")
    assert ko == ["aladin", "googlebooks", "openlibrary", "lubimyczytac", "ranobedb"]
    # 通吃档内保持原顺序（googlebooks 在 openlibrary 前）✓；韩语专精进第 0 档 ✓

    # 波兰语：lubimyczytac 进第 0 档，其余不变
    assert m.reorder_for_language(order, "pl") == [
        "lubimyczytac", "googlebooks", "openlibrary", "aladin", "ranobedb"]

    # 中文：没有专精中文的家（第 0 档空）→ 通吃在前，全部「专精别的语种」按原顺序排后面
    assert m.reorder_for_language(order, "zh") == [
        "googlebooks", "openlibrary", "aladin", "lubimyczytac", "ranobedb"]

    # 英语：英语专精的家（这里没有）与通吃都在前三档，日/韩/波专精排最后
    assert m.reorder_for_language(order, "en") == [
        "googlebooks", "openlibrary", "aladin", "lubimyczytac", "ranobedb"]


def test_只排序不筛源():
    order = ["aladin", "audible", "comicvine", "googlebooks", "ranobedb"]
    out = m.reorder_for_language(order, "zh")
    assert sorted(out) == sorted(order), "重排不能丢掉任何一家（只是顺序变了）"
    assert len(out) == len(order)


def test_语种未知或开关关闭时原样返回():
    order = ["googlebooks", "aladin", "ranobedb"]
    # 语种未知 / 空 / 无法归一 → 不动（不猜）
    for lang in ("", None, "  ", "未知", "???"):
        assert m.reorder_for_language(order, lang) == order, lang
    # 开关关闭 → 严格按用户顺序
    assert m.reorder_for_language(order, "ko", enabled=False) == order
    # 少于两家没什么好排的
    assert m.reorder_for_language(["ranobedb"], "ko") == ["ranobedb"]


def test_语种码会先归一():
    # "zh-CN" / "chi" / "Chinese" 都该归一成 zh；"ja" 与 "Japanese" 同档
    assert m.reorder_for_language(["aladin", "googlebooks"], "zh-CN") == \
        ["googlebooks", "aladin"]
    assert m.reorder_for_language(["aladin", "googlebooks"], "Chinese") == \
        ["googlebooks", "aladin"]
    assert m.reorder_for_language(["googlebooks", "ranobedb"], "Japanese") == \
        ["ranobedb", "googlebooks"]
    # 陌生但合法的语种码不会炸，只按「通吃优先」排
    assert m.reorder_for_language(["aladin", "googlebooks"], "xx") == ["googlebooks", "aladin"]


def test_系列用成员书投票():
    members = [{"language": "ja"}, {"language": "ja"}, {"language": "zh"}, {"language": ""}, {}]
    assert m.dominant_language(members) == "ja"
    # 平票取**先出现**的：保证同一批数据每次结果一致（否则重排不可复现）
    assert m.dominant_language([{"language": "zh"}, {"language": "ko"}]) == "zh"
    assert m.dominant_language([{"language": ""}, {}]) == ""
    assert m.dominant_language([]) == ""


# ---------------- 三处调用点 ----------------

def _spy_search(monkeypatch, seen: list):
    """记录 `search_all` / `search_by_isbn` 收到的来源顺序，并回一个空结果。"""
    def fake_all(sources, title, author, limit=5, options=None):
        seen.append(list(sources))
        return {"entries": [], "sources": {}, "best": None}

    def fake_isbn(isbn, sources, limit=5, options=None):
        seen.append(list(sources))
        return None

    monkeypatch.setattr(m, "search_all", fake_all)
    monkeypatch.setattr(m, "search_by_isbn", fake_isbn)


def test_plan按每本书自己的语种重排(isolated, monkeypatch):  # noqa: ARG001
    """同一批书混着中日文时，每本书的顺序必须各算各的（用一个顺序显然不合理）。"""
    from novelforge.core import library, metafetch

    books = [
        {"name": "韩书.epub", "title": "채식주의자", "language": "ko"},
        {"name": "日书.epub", "title": "狼と香辛料", "language": "ja"},
    ]
    monkeypatch.setattr(library, "books", lambda *a, **k: [
        {**b, "id": b["name"], "format": "EPUB", "has_cover": False, "locked": []}
        for b in books])
    seen: list = []
    _spy_search(monkeypatch, seen)

    cfg = _cfg(enabled=True, sources=["googlebooks", "openlibrary", "aladin",
                                      "ranobedb", "lubimyczytac"])
    out = metafetch.plan(cfg=cfg)

    assert out["auto_order_by_language"] is True
    assert out["sources"] == ["googlebooks", "openlibrary", "aladin", "ranobedb", "lubimyczytac"]
    orders = {i["name"]: i["sources_order"] for i in out["items"]}
    assert orders["韩书.epub"][0] == "aladin", orders
    assert orders["日书.epub"][0] == "ranobedb", orders
    # 只排序不筛源：每本都还是那 5 家
    assert sorted(orders["韩书.epub"]) == sorted(out["sources"])


def test_关掉开关后严格按配置顺序(isolated, monkeypatch):  # noqa: ARG001
    from novelforge.core import library, metafetch

    monkeypatch.setattr(library, "books", lambda *a, **k: [
        {"id": "b", "name": "b.epub", "title": "t", "language": "ko", "format": "EPUB",
         "has_cover": False, "locked": []}])
    seen: list = []
    _spy_search(monkeypatch, seen)
    cfg = _cfg(enabled=True, auto_order_by_language=False, sources=["googlebooks", "aladin"])

    out = metafetch.plan(cfg=cfg)

    assert out["auto_order_by_language"] is False
    assert out["items"][0]["sources_order"] == ["googlebooks", "aladin"]
    assert seen and seen[0] == ["googlebooks", "aladin"]


def test_online_candidate按书语种重排(isolated, monkeypatch):  # noqa: ARG001
    from novelforge.core import metafetch

    seen: list = []
    _spy_search(monkeypatch, seen)
    cfg = _cfg(enabled=True, sources=["googlebooks", "lubimyczytac"])

    # 语种已知 → 波兰语专精排最前
    assert metafetch.online_candidate({"title": "Wiedźmin", "language": "pl"}, cfg=cfg) is None
    assert seen[-1][0] == "lubimyczytac", seen

    # 语种未知 → 原样
    assert metafetch.online_candidate({"title": "x", "language": ""}, cfg=cfg) is None
    assert seen[-1] == ["googlebooks", "lubimyczytac"], seen


def test_系列抓取用成员书语种(isolated, monkeypatch):  # noqa: ARG001
    from novelforge.core import library, series_meta

    monkeypatch.setattr(library, "series_books", lambda name: [
        {"name": "a", "title": "a", "language": "ja"},
        {"name": "b", "title": "b", "language": "ja"}])
    seen: list = []

    def fake_series(name, members, sources=None, limit=5, options=None):
        seen.append(list(sources))
        return {"entries": [], "sources": {}, "best": None}

    monkeypatch.setattr(m, "search_series", fake_series)
    cfg = _cfg(enabled=True, sources=["googlebooks", "ranobedb"])

    res = series_meta.fetch_one("系列", cfg=cfg)

    assert not res["ok"]
    assert seen and seen[0][0] == "ranobedb", seen


# ---------------- 配置面向 ----------------

def test_配置键可写且默认开启(client, auth_headers):  # noqa: ARG001
    cfg = client.get("/api/config", headers=auth_headers).json()["config"]["metadata_fetch"]
    assert cfg["auto_order_by_language"] is True

    r = client.put("/api/config", headers=auth_headers,
                   json={"metadata_fetch": {"auto_order_by_language": False}})
    assert r.status_code == 200, r.text
    after = client.get("/api/config", headers=auth_headers).json()["config"]["metadata_fetch"]
    assert after["auto_order_by_language"] is False, "该开关必须可写（否则界面点了没用）"
    assert after["sources"] == cfg["sources"], "只改开关不该动别的键"


def test_提供商目录回传语种亲和(client, auth_headers):  # noqa: ARG001
    items = {i["id"]: i for i in client.get("/api/metadata/providers",
                                            headers=auth_headers).json()["items"]}

    assert items["aladin"]["langs"] == ["ko"] and items["aladin"]["lang_broad"] is False
    assert items["ranobedb"]["langs"] == ["ja"]
    assert items["googlebooks"]["langs"] == [] and items["googlebooks"]["lang_broad"] is True
