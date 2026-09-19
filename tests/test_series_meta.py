"""系列级元数据（第 12 期 C3）：聚合、分层、抓取阈值、重排册号不变量。

为什么这个文件必须用**真 EPUB**：系列名与系列序号只存在于 EPUB 内部的 OPF
（`calibre:series` / `calibre:series_index`），假 `b"EPUB"` 占位解析不出系列。
构造器见 `_epub_with_series`（用 `fileops.patch_epub_meta` 造出「文件里带系列」的
真实样本 —— 该函数已退出生产路径，现在是**测试夹具**）。

⚠️ 第 18 期口径变更：**重排册号不再改写 OPF**，改为写服务端覆盖
（`meta_override.series_index`）；因此本文件对「重排」的断言从
「回读 OPF 确认」变成「**文件字节分毫未动** + 生效值（override > online > opf）正确」。

离线约定：抓取相关用例一律用 `monkeypatch` 顶掉 `metasources.search_all`，
断言的是**我们自己的打分/阈值/落库逻辑**，不是外部源是否可达（本机无外网）。
"""
import hashlib
import json
import pathlib

import pytest

from novelforge.core import db, epub_builder, fileops, library, metasources, series_meta


def _epub_with_series(root, name: str, *, title: str, series: str, index: str = "",
                      publisher: str = "", year: str = "", tags: list = None) -> pathlib.Path:
    """造一本**带系列信息**的真 EPUB（先建标准 EPUB，再改写 OPF 元数据）。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": "测试作者", "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    fields = {"series": series}
    if index:
        fields["series_index"] = index
    if publisher:
        fields["publisher"] = publisher
    if year:
        fields["date"] = year
    if tags:
        fields["tags"] = tags
    assert fileops.patch_epub_meta(path, fields), f"OPF 改写失败：{name}"
    return path


@pytest.fixture
def series_fixture(isolated, default_root):  # noqa: ARG001 —— 依赖 isolated 切目录
    """一个三册系列：出版社 2:1 多数派、年份跨 2012–2015、题材有交集与独有项。"""
    _epub_with_series(default_root, "基地.epub", title="基地", series="银河帝国", index="1",
                      publisher="江苏文艺出版社", year="2012", tags=["科幻", "经典"])
    _epub_with_series(default_root, "基地与帝国.epub", title="基地与帝国", series="银河帝国",
                      index="2", publisher="江苏文艺出版社", year="2013", tags=["科幻"])
    _epub_with_series(default_root, "第二基地.epub", title="第二基地", series="银河帝国",
                      index="3", publisher="读客文化", year="2015", tags=["科幻", "太空"])
    library.invalidate()
    return "银河帝国"


def _fake_search(entries: list):
    """替掉外呼：返回固定候选（`search_all` 的形状）。"""
    return lambda *a, **k: {
        "entries": entries,
        "sources": {"openlibrary": {"ok": True, "count": len(entries), "error": ""}},
        "best": None,
    }


def _cand(title: str, **kw) -> dict:
    base = {"source": "openlibrary", "title": title, "author": "测试作者", "description": "",
            "publisher": "", "year": "", "tags": [], "isbn": "", "score": 0.0}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# 聚合（本地事实，零猜测）
# ---------------------------------------------------------------------------

def test_聚合取成员书事实(series_fixture):
    eff = series_meta.effective(series_fixture)
    assert eff["owned_count"] == 3, "册数必须是实际拥有数"
    assert eff["publisher"] == "江苏文艺出版社", "出版社取出现最多的那个（2:1）"
    assert eff["first_year"] == "2012", "首发年取最早"
    assert eff["tags"] == ["科幻", "经典", "太空"], "题材取并集且保序"
    assert eff["description"] == "", "系列简介本地无从推断，聚合阶段应为空"
    assert eff["declared_count"] == 0 and eff["source"] == ""


def test_轻量分层不做聚合(series_fixture):
    """列表页专用：不能有 owned_count（它必须来自聚合，不能瞎猜）。"""
    light = series_meta.effective_light(series_fixture)
    assert "owned_count" not in light
    assert light["description"] == "" and light["tags"] == []


def test_题材归一化():
    assert series_meta._as_tags(None) == []
    assert series_meta._as_tags("科幻，经典、科幻") == ["科幻", "经典"]
    assert series_meta._as_tags('["a", "b", "a"]') == ["a", "b"]


# ---------------------------------------------------------------------------
# 分层：本地覆盖 > 聚合 > 在线补空
# ---------------------------------------------------------------------------

def test_本地覆盖优先于聚合(series_fixture):
    series_meta.set_local(series_fixture, description="我写的简介")
    eff = series_meta.effective(series_fixture)
    assert eff["description"] == "我写的简介"
    assert eff["overridden"]["description"] is True
    # 未覆盖的字段仍取聚合值
    assert eff["publisher"] == "江苏文艺出版社" and eff["overridden"]["publisher"] is False


def test_在线值只补空不覆盖聚合(series_fixture):
    db.upsert_series_meta(series_fixture, description="在线简介", publisher="在线出版社",
                          first_year="1999", tags=json.dumps(["在线题材"]),
                          declared_count=7, source="openlibrary", score=0.9)
    eff = series_meta.effective(series_fixture)
    assert eff["description"] == "在线简介", "简介本地算不出 → 用在线值补"
    assert eff["publisher"] == "江苏文艺出版社", "聚合已有出版社 → 在线值不得覆盖"
    assert eff["first_year"] == "2012", "聚合已有首发年 → 在线值不得覆盖"
    assert eff["tags"] == ["科幻", "经典", "太空"], "聚合已有题材 → 在线值不得覆盖"
    # 两个「册数」语义不同，必须并存而不是互相覆盖
    assert eff["owned_count"] == 3 and eff["declared_count"] == 7
    assert eff["source"] == "openlibrary"


def test_清除覆盖后回落(series_fixture):
    series_meta.set_local(series_fixture, description="临时的")
    assert series_meta.effective(series_fixture)["description"] == "临时的"
    series_meta.set_local(series_fixture, description="")
    assert series_meta.effective(series_fixture)["description"] == ""
    assert series_meta.effective(series_fixture)["overridden"]["description"] is False


def test_编辑不支持的字段被拒绝(series_fixture):
    """只认 FIELDS 白名单 —— 不校验就等于放任任意列名流进库里。"""
    assert series_meta.set_local(series_fixture, owned_count="999")[
        "owned_count"] == 3
    with pytest.raises(ValueError):
        series_meta.set_local("", description="x")


def test_题材覆盖的写入读取往返(series_fixture):
    """配对契约：`set_local(tags=...)` 以 JSON 落库，`effective` 再解析回来 —— 必须同源。

    列表形态最容易在这里走样（写成 Python repr 就解析不回来），所以两端都要断言：
    写入的列表 == 读出的列表，且覆盖标记为真；清除后落回聚合值。
    """
    series_meta.set_local(series_fixture, tags=["甲", "乙", "甲"])
    eff = series_meta.effective(series_fixture)
    assert eff["tags"] == ["甲", "乙"], "写入的列表必须能原样读回（顺带去重保序）"
    assert eff["overridden"]["tags"] is True

    series_meta.set_local(series_fixture, tags=[])
    eff2 = series_meta.effective(series_fixture)
    assert eff2["tags"] == ["科幻", "经典", "太空"], "清空覆盖后应回落到成员书聚合值"
    assert eff2["overridden"]["tags"] is False


def test_state给出逐字段明细(series_fixture):
    db.upsert_series_meta(series_fixture, description="在线简介", source="openlibrary", score=0.8)
    st = series_meta.state(series_fixture)["description"]
    assert st["value"] == "在线简介" and st["online"] == "在线简介"
    assert st["aggregated"] == "" and st["overridden"] is False


# ---------------------------------------------------------------------------
# 在线抓取：一致性打分与「如实未找到」
# ---------------------------------------------------------------------------

def test_抓取命中成员书(series_fixture, monkeypatch):
    monkeypatch.setattr(metasources, "search_all", _fake_search([
        _cand("完全无关的书", author="某某", description="无关"),
        _cand("基地", description="系列第一部", publisher="江苏文艺出版社", year="2012"),
    ]))
    res = series_meta.fetch_one(series_fixture, cfg={"metadata_fetch": {"enabled": True,
                                                                       "sources": ["openlibrary"]}})
    assert res["ok"] is True
    assert res["matched_title"] == "基地", "应挑与成员书一致的那条，而不是列表第一条"
    assert res["score"] == 1.0
    assert db.get_series_meta(series_fixture)["description"] == "系列第一部"


def test_低于阈值如实未找到且不写库(series_fixture, monkeypatch):
    monkeypatch.setattr(metasources, "search_all",
                        _fake_search([_cand("毫不相干", author="谁", description="无关简介")]))
    res = series_meta.fetch_one(series_fixture, cfg={"metadata_fetch": {"enabled": True}})
    assert res["ok"] is False
    assert "未找到" in res["error"]
    assert res["score"] < series_meta.MIN_MATCH
    assert (db.get_series_meta(series_fixture) or {}).get("description") != "无关简介", \
        "低于阈值时**不得**把不相关候选写进库"


def test_抓取不冲掉本地覆盖(series_fixture, monkeypatch):
    series_meta.set_local(series_fixture, description="我自己写的")
    monkeypatch.setattr(metasources, "search_all", _fake_search([
        _cand("基地", description="在线简介"),
    ]))
    assert series_meta.fetch_one(series_fixture,
                                 cfg={"metadata_fetch": {"enabled": True}})["ok"] is True
    eff = series_meta.effective(series_fixture)
    assert eff["description"] == "我自己写的", "用户改过的不能被再次抓取冲掉"


def test_抓取边界不抛异常(series_fixture):
    """抓取是旁路增强：任何情况都只回错误，不向上抛（否则系列页会整页挂掉）。"""
    assert series_meta.fetch_one("")["ok"] is False
    assert series_meta.fetch_one("不存在的系列")["ok"] is False
    assert series_meta.fetch_one(series_fixture, cfg={"metadata_fetch": {"enabled": False}})[
        "ok"] is False
    # 抓取未启用时**不应**触发外呼：真跑一遍也不会抛
    assert series_meta.fetch_all(limit=1, cfg={"metadata_fetch": {}})["failed"] >= 0


def test_批量抓取分批并回remaining(series_fixture, monkeypatch):
    monkeypatch.setattr(metasources, "search_all", _fake_search([_cand("基地")]))
    res = series_meta.fetch_all(limit=1, cfg={"metadata_fetch": {"enabled": True}})
    assert res["total"] == 1 and res["ok"] == 1 and res["remaining"] == 0
    res2 = series_meta.fetch_all(names=[series_fixture], cfg={"metadata_fetch": {"enabled": True}})
    assert res2["total"] == 1


# ---------------------------------------------------------------------------
# 重排册号：只写服务端覆盖，不动文件名、更不动文件内容
# ---------------------------------------------------------------------------

def _sha_of(root) -> dict:
    """库根下每个文件的 sha256（用来钉死「文件分毫未动」）。"""
    out = {}
    for p in sorted(pathlib.Path(root).rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out

def test_重排计划按当前序号升序(series_fixture, default_root):  # noqa: ARG001
    _epub_with_series(default_root, "无序.epub", title="无序册", series=series_fixture)
    library.invalidate()
    plan = series_meta.renumber_plan(series_fixture)
    assert [i["title"] for i in plan["items"]] == ["基地", "基地与帝国", "第二基地", "无序册"], \
        "缺序号的必须排最后，而不是被当成第一册"
    assert [i["new_index"] for i in plan["items"]] == ["1", "2", "3", "4"]
    assert plan["total"] == 4 and plan["changing"] == 1


def test_重排只写服务端不动文件名与文件字节(series_fixture, default_root):
    """核心不变量（第 18 期加严）：

    1. 文件名不动 → book_id 不变 → 阅读进度/批注/评分/收藏不断链；
    2. **文件字节一个都不变** → 元数据只存服务端（`meta_override`），原书可随时还原；
    3. 生效值（override > online > opf）确实是新序号。
    """
    before = {b["name"]: b["id"] for b in library.series_books(series_fixture)}
    files_before = _sha_of(default_root)
    plan = series_meta.renumber_plan(series_fixture, order=list(reversed(list(before))))
    res = series_meta.renumber_apply(series_fixture, [
        {"name": i["name"], "new_index": i["new_index"]} for i in plan["items"]])

    assert res["renumbered"] == 3 and res["skipped"] == [] and res["mismatched"] == []
    after = {b["name"]: b["id"] for b in library.series_books(series_fixture)}
    assert after == before, "文件名与 book_id 都不能变"
    assert _sha_of(default_root) == files_before, "EPUB 文件字节不能被改写"
    # 序号落在服务端覆盖上，且**生效值**回读到的是新序号
    assert db.get_overrides(next(iter(after.values()))).get("series_index")
    assert res["verified"] == {i["name"]: i["new_index"] for i in plan["items"]}


def test_重排幂等(series_fixture):
    plan = series_meta.renumber_plan(series_fixture)
    items = [{"name": i["name"], "new_index": i["new_index"]} for i in plan["items"]]
    series_meta.renumber_apply(series_fixture, items)
    assert series_meta.renumber_plan(series_fixture)["changing"] == 0, "已排好再排一次应无变化"
    assert series_meta.renumber_apply(series_fixture, items)["mismatched"] == []


def test_重排可完整回滚(series_fixture, default_root):  # noqa: ARG001
    """按 old_index 再写一次即可还原 —— 含「原本没有序号」→ 清除这一种。"""
    _epub_with_series(default_root, "无序.epub", title="无序册", series=series_fixture)
    library.invalidate()
    before = {b["name"]: str(b.get("series_index") or "") for b in library.series_books(series_fixture)}
    plan = series_meta.renumber_plan(series_fixture)
    series_meta.renumber_apply(series_fixture, [
        {"name": i["name"], "new_index": i["new_index"]} for i in plan["items"]])
    assert {b["name"]: str(b.get("series_index") or "")
            for b in library.series_books(series_fixture)} != before
    series_meta.renumber_apply(series_fixture, [
        {"name": i["name"], "new_index": i["old_index"]} for i in plan["items"]])
    assert {b["name"]: str(b.get("series_index") or "")
            for b in library.series_books(series_fixture)} == before


def test_重排拒绝越界与非法条目(series_fixture, default_root):  # noqa: ARG001
    _epub_with_series(default_root, "x.epub", title="x", series="别的系列", index="9")
    library.invalidate()
    # 不属于该系列 → 拒绝（不允许顺手改到别的系列的书）
    assert series_meta.renumber_apply(series_fixture, [
        {"name": "x.epub", "new_index": "1"}])["skipped"][0]["error"] == "不属于该系列"
    # 缺 new_index 键 → 拒绝（给空串才是「清除序号」）
    assert series_meta.renumber_apply(series_fixture, [
        {"name": "基地.epub"}])["skipped"][0]["error"] == "缺少 new_index"
    # 路径穿越 → 同样落到「不属于该系列」，碰不到库外文件
    assert series_meta.renumber_apply(series_fixture, [
        {"name": "../escape.epub", "new_index": "1"}])["skipped"]
    with pytest.raises(ValueError):
        series_meta.renumber_plan("不存在的系列")
    with pytest.raises(ValueError):
        series_meta.renumber_apply(series_fixture, [])


def test_重排支持清除序号(series_fixture, default_root):
    """清空序号 = 写「显式无值」哨兵。

    覆盖值是**列**，存不了空串（空串在 `set_override` 里表示撤销覆盖），
    所以清空必须走哨兵；否则该册会退回**文件原值**（这里是 1），
    「把序号去掉」这个能力就丢了。
    """
    files_before = _sha_of(default_root)
    res = series_meta.renumber_apply(series_fixture, [
        {"name": "基地.epub", "new_index": ""}])
    assert res["renumbered"] == 1 and res["mismatched"] == []
    assert [c["name"] for c in res["cleared"]] == ["基地.epub"]
    idx = {b["name"]: str(b.get("series_index") or "")
           for b in library.series_books(series_fixture)}
    assert idx["基地.epub"] == ""
    assert _sha_of(default_root) == files_before, "清空只写服务端，文件字节不能变"
    # 哨兵只当值用，不该泄漏到读取端
    assert db.META_CLEAR not in [idx[k] for k in idx]
