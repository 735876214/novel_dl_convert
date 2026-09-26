"""第 57 期：元数据提供商注册表与「提供商」页契约。

这块的核心风险不是功能，而是**诚实性**：注册表列的是上游那 14 家的目录，本项目真正
实现的只有 2 家。所以契约要钉住三件事：

1. **注册表 ↔ 实现一致**：`IMPLEMENTED` 必须与 `_FETCHERS` 的键**完全相等** ——
   否则会出现「标着已实现、抓取时`源不可用`」或反之的错位；
2. **未实现的源不发外呼**：`/api/metadata/probe` 对它如实回报「未实现」而不是打一次
   注定失败的网络请求（也不该让用户以为是自己网络坏了）；
3. **端点形状**：分组、`已启用 N/总数`、`needs_setup`（「需要设置」过滤器的数据源）。
"""
from novelforge.core import metasources


def test_注册表覆盖上游十四家且分四组():
    items = metasources.provider_catalog()

    assert len(items) == 14, [i["id"] for i in items]
    assert len({i["id"] for i in items}) == 14, "id 不能重复"
    groups = {i["group"] for i in items}
    assert groups == set(metasources.GROUPS), groups
    for meta in items:
        assert meta["label"] and meta["home"] and meta["note"], meta
        assert isinstance(meta.get("implemented"), bool), meta


def test_已实现清单与fetcher逐字一致():
    """`IMPLEMENTED` 是给注册表/前端看的，`_FETCHERS` 是真正能跑的 —— 两者必须相等。"""
    assert set(metasources.IMPLEMENTED) == set(metasources._FETCHERS)
    assert set(metasources.is_implemented(s) for s in metasources.SOURCES) == \
        {True, False}, "注册表里应当同时有已实现与未实现的家（诚实目录）"
    for sid in metasources.IMPLEMENTED:
        assert metasources.SOURCES[sid]["implemented"] is True, sid


def test_默认启用顺序只含已实现的源():
    for sid in metasources.DEFAULT_ORDER:
        assert metasources.is_implemented(sid), f"{sid} 没实现却在默认顺序里"


def test_目录按分组顺序排列():
    items = metasources.provider_catalog()
    order = [metasources.GROUPS.index(i["group"]) for i in items]
    assert order == sorted(order), "分组必须按 GROUPS 的顺序连续出现"


def test_未实现的源检索返回不可用而不抛():
    r = metasources.search("amazon", "三体", "刘慈欣")

    assert r["ok"] is False and r["entries"] == []
    assert "不可用" in r["error"], r


def test_providers_端点给出分组与计数(client, auth_headers):
    r = client.get("/api/metadata/providers", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total"] == 14
    assert body["implemented_count"] == 2
    assert body["active_count"] == 2, "默认启用 openlibrary + googlebooks"
    assert [g["name"] for g in body["groups"]] == list(metasources.GROUPS)

    by_id = {i["id"]: i for i in body["items"]}
    assert by_id["openlibrary"]["active"] is True
    assert by_id["openlibrary"]["order"] == 1
    assert by_id["googlebooks"]["order"] == 2
    assert by_id["amazon"]["implemented"] is False
    assert by_id["amazon"]["active"] is False
    # 「需要设置」= 要 Key 且还没填（前端过滤器的唯一数据源）
    assert by_id["hardcover"]["needs_setup"] is True
    assert by_id["openlibrary"]["needs_setup"] is False
    assert by_id["amazon"]["needs_setup"] is False, "不需要配置 ≠ 需要设置"


def test_连通性探测跳过未实现的源(client, auth_headers, monkeypatch):
    """未实现的家**一次外呼都不该发**：如实回报即可。"""
    called: list = []
    real_probe = metasources.probe

    def spy(sid, opts=None):
        called.append(sid)
        return real_probe(sid, opts)

    monkeypatch.setattr(metasources, "probe", spy)

    r = client.post("/api/metadata/probe", headers=auth_headers,
                    json={"sources": ["amazon", "hardcover"]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]

    assert called == [], f"未实现的源不该被探测：{called}"
    assert items["amazon"]["ok"] is False and "未实现" in items["amazon"]["message"]


def test_配置里混入未实现源不会让抓取计划炸(isolated, monkeypatch):  # noqa: ARG001
    """用户可以手改配置（或插件卸载后残留 id）—— 计划侧必须稳。"""
    from novelforge.core import metafetch

    cfg = {"metadata_fetch": {"enabled": True, "sources": ["amazon", "openlibrary"]}}
    out = metafetch.plan(cfg=cfg)

    assert isinstance(out, dict) and out.get("enabled") is True
    assert isinstance(out.get("items"), list)
