"""第 86 期：书源导入 / 导出 / 台账 / 启停 / 回滚 / 批量 的**接口契约**（零网络）。

接口层是薄包装，所以这份测试盯的是**包装有没有把内核的承诺弄丢**：

- `dry_run` 默认不写盘（连一个字节都不写）；
- 差异表**不回**整条规则本体（一份文件几百条源，回本体能把响应撑到几 MB）；
- `resolutions` 里的非法取值**当没给**（退回默认动作），而不是悄悄当成覆盖；
- 停用的源仍出现在 `/api/sources` 里（否则界面上「停用」等于「消失」）；
- 内置源启停**如实 400**；批量操作逐条回报而不是整批失败。
"""
import json
import pathlib

import pytest

from novelforge import config
from novelforge.core import db
from novelforge.sources import base, ledger, store

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "legado_sample.json"


@pytest.fixture(autouse=True)
def _sandbox(isolated):                                     # noqa: ARG001
    """清干净跨用例共享的三样东西：`SOURCES_DIR` / `REGISTRY` / 台账（见 `test_source_ledger.py`）。"""
    d = pathlib.Path(config.SOURCES_DIR)
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob("*.json"):
        p.unlink()
    for row in db.source_ledger_all():
        db.source_ledger_delete(row["name"])
    db.source_imports_clear()
    before = set(base.REGISTRY)
    yield
    for name in set(base.REGISTRY) - before:
        base.REGISTRY.pop(name, None)


def _html_entry() -> dict:
    return next(e for e in json.loads(FIXTURE.read_text(encoding="utf-8"))
                if e.get("bookSourceName") == "示例HTML源")


def _hand_rule(name: str, domain: str = "other.com") -> dict:
    return {
        "name": name, "display_name": "手写的", "domains": [domain], "public": False,
        "search": {"url": f"https://{domain}/s?q={{title}}", "mode": "css", "container": ".i",
                   "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": "toc", "toc": {"mode": "css", "container": ".l a"},
                 "content": {"mode": "css", "container": "#c", "text": True}},
    }


def _import(client, h, entries, **kw):
    body = {"payload": entries, "origin": "test.json", **kw}
    return client.post("/api/sources/import", headers=h, json=body)


def _by_name(client, h) -> dict:
    return {s["name"]: s for s in client.get("/api/sources", headers=h).json()["sources"]}


def test_dry_run默认不落盘且不回规则本体(client, auth_headers):
    r = _import(client, auth_headers, [_html_entry()])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["dry_run"] is True and len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["verdict"] == "new" and row["name"] == "lg-example-novel.com"
    assert "converted_rule" not in row and "raw" not in row, "差异表不回整条规则本体"
    assert "supported" in row and "unsupported_fields" in row and "changed_fields" in row
    # 一个字节都不该写
    assert not list(pathlib.Path(config.SOURCES_DIR).glob("*.json"))
    assert db.source_ledger_all() == []
    assert db.source_imports() == []


def test_真导入后列表能看出是导入来的(client, auth_headers):
    assert _import(client, auth_headers, [_html_entry()], dry_run=False).status_code == 200
    s = _by_name(client, auth_headers)["lg-example-novel.com"]
    assert s["imported"] is True and s["enabled"] is True and s["user"] is True
    assert s["domains"] == ["www.example-novel.com"]

    hist = client.get("/api/sources/imports", headers=auth_headers).json()["items"]
    assert hist and hist[0]["counts"]["new"] == 1 and hist[0]["origin"] == "test.json"

    led = {r["name"]: r for r in client.get("/api/sources/ledger", headers=auth_headers).json()["items"]}
    assert led["lg-example-novel.com"]["imported"] is True
    assert "raw_json" not in led["lg-example-novel.com"], "列表不该背着原文副本"


def test_非法的冲突处理取值当没给不静默覆盖(client, auth_headers):
    name = "lg-example-novel.com"
    # ⚠️ 手写源直接用 `store.add_rule` 建（**校验不过会当场抛**）：走 `/api/sources` 时
    #    200 也可能是「一条都没加进去」，那样这条用例会变成一个永远绿的假断言。
    store.add_rule(_hand_rule(name, "other.com"))
    r = _import(client, auth_headers, [_html_entry()], dry_run=False,
                resolutions={name: "overwrite!!"})        # 拼错一个词
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["action"] == "skip", "非法取值必须退回默认动作"
    saved = json.loads((pathlib.Path(config.SOURCES_DIR) / f"{name}.json").read_text(encoding="utf-8"))
    assert saved["domains"] == ["other.com"], "拼错一个词就把用户的书源盖了 —— 不能接受"


def test_两条并存不会越导越多(client, auth_headers):
    """并存之后**再导入同一份**不该继续生出 `-3` / `-4`：默认动作是跳过。

    ⚠️ 这一条刻意用「同站点、不同名」的手写源：若手写源与导入目标**同名**，
    那么它的判定就是「撞名冲突」而不是「更新 / 重复」——两条用例的语义不同，别混着测。
    """
    name = "lg-example-novel.com"
    store.add_rule(_hand_rule("my-example", "www.example-novel.com"))
    r = _import(client, auth_headers, [_html_entry()], dry_run=False,
                resolutions={name: "keep_both"})
    assert r.status_code == 200 and r.json()["items"][0]["ok"] is True
    names = set(_by_name(client, auth_headers))
    # 并存 = 新条目**改名落地**（`lg-example-novel.com-2`）+ 原来那条一字不动；
    # 所以列表里没有叫 `lg-example-novel.com` 的源，这不是丢件。
    assert {f"{name}-2", "my-example"} <= names, "两条并存必须两条都在，且不碰原来那条"
    assert _by_name(client, auth_headers)["my-example"]["public"] is False

    again = _import(client, auth_headers, [_html_entry()], dry_run=False)
    assert [i["verdict"] for i in again.json()["items"]] == ["conflict"], \
        "同一个站点上还站着 my-example，所以再导入仍是「同站点冲突」"
    assert again.json()["counts"]["skipped"] == 1, "默认动作必须是跳过，不是无限改名"
    assert not (pathlib.Path(config.SOURCES_DIR) / f"{name}-3.json").exists()


def test_导出往返幂等(client, auth_headers):
    _import(client, auth_headers, [_html_entry()], dry_run=False)
    payload = client.get("/api/sources/export", headers=auth_headers).json()
    assert payload["nf_export"] == 1 and payload["entries"] == [_html_entry()]
    rows = _import(client, auth_headers, payload, dry_run=False).json()
    assert [i["verdict"] for i in rows["items"]] == ["duplicate"]


def test_停用的源仍在列表里且可再打开(client, auth_headers):
    name = "lg-example-novel.com"
    _import(client, auth_headers, [_html_entry()], dry_run=False)
    r = client.post(f"/api/sources/{name}/enabled", headers=auth_headers, json={"enabled": False})
    assert r.status_code == 200
    s = _by_name(client, auth_headers)[name]
    assert s["enabled"] is False and s["user"] is True, "停用后必须还在列表里（否则用户点不回来）"
    assert s["display_name"], "不在 REGISTRY 的源也要从文件里补齐展示名"
    assert name not in base.REGISTRY, "停用 = 不注册"

    assert client.post(f"/api/sources/{name}/enabled", headers=auth_headers,
                       json={"enabled": True}).status_code == 200
    assert name in base.REGISTRY


def test_内置源启停如实拒绝(client, auth_headers):
    name = next(n for n in base.REGISTRY
                if not (pathlib.Path(config.SOURCES_DIR) / f"{n}.json").exists())
    r = client.post(f"/api/sources/{name}/enabled", headers=auth_headers, json={"enabled": False})
    assert r.status_code == 400 and "内置源" in r.json()["detail"]


def test_覆盖后可从历史回滚(client, auth_headers):
    name = "lg-example-novel.com"
    _import(client, auth_headers, [_html_entry()], dry_run=False)
    changed = json.loads(json.dumps(_html_entry()))
    changed["bookSourceName"] = "示例HTML源（改版）"
    _import(client, auth_headers, [changed], dry_run=False)

    items = client.get(f"/api/sources/{name}/history", headers=auth_headers).json()["items"]
    assert len(items) == 1 and "payload" not in items[0], "历史列表不该回旧规则原文"
    r = client.post(f"/api/sources/{name}/rollback", headers=auth_headers,
                    json={"history_id": items[0]["id"]})
    assert r.status_code == 200
    saved = json.loads((pathlib.Path(config.SOURCES_DIR) / f"{name}.json").read_text(encoding="utf-8"))
    assert saved["display_name"] == "示例HTML源"


def test_重新分析区分导入源与手写源(client, auth_headers):
    _import(client, auth_headers, [_html_entry()], dry_run=False)
    r = client.post("/api/sources/lg-example-novel.com/reanalyze", headers=auth_headers)
    assert r.status_code == 200 and r.json()["supported"] == "yes"

    store.add_rule(_hand_rule("mine"))
    r2 = client.post("/api/sources/mine/reanalyze", headers=auth_headers)
    assert r2.status_code == 400 and "手写源" in r2.json()["detail"], "手写源要如实说清，不假装分析过"
    assert client.post("/api/sources/根本没这源/reanalyze", headers=auth_headers).status_code == 404


def test_批量操作逐条回报(client, auth_headers):
    _import(client, auth_headers, [_html_entry()], dry_run=False)
    builtin = next(n for n in base.REGISTRY
                   if not (pathlib.Path(config.SOURCES_DIR) / f"{n}.json").exists())
    r = client.post("/api/sources/bulk", headers=auth_headers,
                    json={"action": "disable", "names": ["lg-example-novel.com", builtin, "不存在"]})
    assert r.status_code == 200, r.text
    items = {i["name"]: i for i in r.json()["items"]}
    assert items["lg-example-novel.com"]["ok"] is True
    assert items[builtin]["ok"] is False and "内置源" in items[builtin]["note"]
    assert items["不存在"]["ok"] is False, "混选里必然有杂项：逐条回报，不整批失败"

    r2 = client.post("/api/sources/bulk", headers=auth_headers,
                     json={"action": "炸了", "names": ["x"]})
    assert r2.status_code == 400 and "action" in r2.json()["detail"]


def test_导入相关接口都要鉴权(client):
    assert client.post("/api/sources/import", json={"payload": []}).status_code in (401, 403)
    assert client.get("/api/sources/export").status_code in (401, 403)
    assert client.get("/api/sources/ledger").status_code in (401, 403)


def test_台账删除后不留幽灵(client, auth_headers):
    """删源要连台账一起删：留下孤立台账行会让「导入来源 / 档位」出现在一个不存在的源上。"""
    name = "lg-example-novel.com"
    _import(client, auth_headers, [_html_entry()], dry_run=False)
    assert client.delete(f"/api/sources/{name}", headers=auth_headers).status_code == 200
    assert db.source_ledger_get(name) is None
    assert ledger.plan([_html_entry()])[0]["verdict"] == "new"
