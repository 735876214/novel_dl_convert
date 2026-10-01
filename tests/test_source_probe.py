"""第 86 期第 4 步：单字探测 / 全部验证 / 目录来源探测（**零网络**，管理器全用桩）。

要钉住的四件事：

1. **「一条即有效」**：单字查询回 ≥1 条就算这条源现在能用，同时带上条数与耗时；
2. **「不支持」与「验证失败」是两种状态**：不可执行 / 已停用 / 未知 ⇒ **根本不出网**，
   台账 `verify_ok` 记 **`None`**（没测过）而不是 `False`（失败）—— 否则界面会把一个中性
   事实染成警示色；
3. **全部验证串行加间隔，且间隔只在两条之间**（最后一条后面不睡，不然每次全验白等）；
4. **目录来源探测不落库**：只读目录页，`store_toc` / `toc_map` / 台账一个字都不写。
"""
import asyncio
import json
import pathlib

import pytest

from novelforge import config
from novelforge.core import db
from novelforge.sources import base, probe as probe_mod, store, toc_sources
from novelforge.sources.manager import DownloadManager


@pytest.fixture(autouse=True)
def _sandbox(isolated):                                     # noqa: ARG001
    """清干净跨用例共享的目录 / REGISTRY / 台账（见 `test_source_ledger.py`）。"""
    d = pathlib.Path(config.SOURCES_DIR)
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob("*.json"):
        p.unlink()
    for row in db.source_ledger_all():
        db.source_ledger_delete(row["name"])
    before = set(base.REGISTRY)
    yield
    for name in set(base.REGISTRY) - before:
        base.REGISTRY.pop(name, None)


class _StubManager:
    """桩管理器：记录调用、按需返回 / 抛错（**永不联网**）。"""

    def __init__(self, *, items: int = 1, error: str = ""):
        self.calls: list = []
        self.items = items
        self.error = error

    async def test_source(self, cls, title: str):
        self.calls.append((getattr(cls, "name", str(cls)), title))
        if self.error:
            raise RuntimeError(self.error)
        return [{"title": f"命中 {i}", "url": f"https://x.com/{i}"} for i in range(self.items)]


def _rule(name: str, domain: str = "probe-demo.com") -> dict:
    return {
        "name": name, "display_name": name, "domains": [domain], "public": False,
        "search": {"url": f"https://{domain}/s?q={{title}}", "mode": "css", "container": ".i",
                   "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": "single", "content": {"mode": "css", "container": "#c"}},
    }


# ---------------- 四种状态 ----------------

def test_一条即有效并回写台账(isolated):                                    # noqa: ARG001
    store.add_rule(_rule("probe-ok"))
    mgr = _StubManager(items=1)
    res = asyncio.run(probe_mod.probe(mgr, "probe-ok"))
    assert res["state"] == "ok" and res["count"] == 1 and res["ms"] >= 0
    assert res["error"] == ""
    assert mgr.calls == [("probe-ok", "我")], "默认查询词就是单字「我」"
    row = db.source_ledger_get("probe-ok")
    assert row["verify_ok"] is True and row["verify_count"] == 1 and row["verified_at"]


def test_零条与网络错误都算验证失败但原因不同(isolated):                          # noqa: ARG001
    store.add_rule(_rule("probe-zero"))
    store.add_rule(_rule("probe-boom", "boom-demo.com"))
    zero = asyncio.run(probe_mod.probe(_StubManager(items=0), "probe-zero"))
    assert zero["state"] == "zero" and zero["count"] == 0 and "一条都没搜到" in zero["error"]
    assert db.source_ledger_get("probe-zero")["verify_ok"] is False

    boom = asyncio.run(probe_mod.probe(_StubManager(error="连接被拒绝"), "probe-boom"))
    assert boom["state"] == "error" and boom["count"] == 0
    assert boom["error"] == "连接被拒绝", "原因原文照回，供写规则的人排查"
    assert db.source_ledger_get("probe-boom")["verify_ok"] is False


def test_判为不可执行的源根本不出网(isolated):                                  # noqa: ARG001
    store.add_rule(_rule("probe-js"))
    db.source_ledger_upsert("probe-js", supported="no")
    mgr = _StubManager()
    res = asyncio.run(probe_mod.probe(mgr, "probe-js"))
    assert res["state"] == "unsupported" and mgr.calls == [], "不可执行就别去挨风控"
    row = db.source_ledger_get("probe-js")
    assert row["verify_ok"] is None, "没测过就记 None —— 记 False 会把「不支持」显示成「失败」"
    assert row["verified_at"] is not None, "但「什么时候看过一眼」仍要如实记下来"


def test_停用的源不出网且措辞说清原因(isolated):                                # noqa: ARG001
    store.add_rule(_rule("probe-off"))
    store.set_enabled("probe-off", False)
    mgr = _StubManager()
    res = asyncio.run(probe_mod.probe(mgr, "probe-off"))
    assert res["state"] == "unsupported" and mgr.calls == []
    assert "已停用" in res["error"] and db.source_ledger_get("probe-off")["verify_ok"] is None


def test_未知书源不留幽灵台账(isolated):                                    # noqa: ARG001
    res = asyncio.run(probe_mod.probe(_StubManager(), "根本没有这个源"))
    assert res["state"] == "unsupported" and "未知书源" in res["error"]
    assert db.source_ledger_get("根本没有这个源") is None, "探测未知名字不许凭空造一条台账"


# ---------------- 全部验证 ----------------

def test_全部验证串行且只在两条之间间隔(isolated, monkeypatch):                  # noqa: ARG001
    for n, d in (("p1", "p1.com"), ("p2", "p2.com"), ("p3", "p3.com")):
        store.add_rule(_rule(n, d))
    sleeps: list = []

    async def _fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(probe_mod.asyncio, "sleep", _fake_sleep)
    mgr = _StubManager(items=2)
    out = asyncio.run(probe_mod.probe_many(mgr, ["p1", "p2", "p3"], interval=1.5))
    assert [i["name"] for i in out["items"]] == ["p1", "p2", "p3"], "顺序按给定名单（串行）"
    assert [c[0] for c in mgr.calls] == ["p1", "p2", "p3"], "真的是一条一条跑的，没有并发"
    assert sleeps == [1.5, 1.5], "只在两条之间睡：最后一条后面不该再等"
    assert out["counts"] == {"ok": 3} and out["queried"] == 3


def test_全部验证把不可执行的算进去但不出网(isolated, monkeypatch):                # noqa: ARG001
    store.add_rule(_rule("p-ok"))
    db.source_ledger_upsert("p-js", supported="no")
    sleeps: list = []

    async def _fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(probe_mod.asyncio, "sleep", _fake_sleep)
    mgr = _StubManager(items=1)
    out = asyncio.run(probe_mod.probe_many(mgr, ["p-ok", "p-js", "p-none"], interval=0))
    states = {i["name"]: i["state"] for i in out["items"]}
    assert states == {"p-ok": "ok", "p-js": "unsupported", "p-none": "unsupported"}
    assert mgr.calls == [("p-ok", "我")], "整轮只有一条真的出了网"
    assert out["counts"] == {"ok": 1, "unsupported": 2}


# ---------------- 目录来源（不落库）----------------

def _toc_entity(*, with_rule: bool = True) -> dict:
    for s in toc_sources.SOURCES:
        if with_rule and s.get("rule") and s.get("status") != toc_sources.UNSUPPORTED:
            return s
        if not with_rule and s.get("status") == toc_sources.UNSUPPORTED:
            return s
    raise AssertionError("注册表里没有符合条件的那类来源")


def test_目录来源探测不落库(isolated, monkeypatch):                              # noqa: ARG001
    ent = _toc_entity(with_rule=True)
    calls: list = []

    async def _fake_fetch(manager, source_id, *, book, url="", query=""):
        calls.append((source_id, book.get("title"), query))
        return {"ok": True, "entries": [{"title": "第一章", "depth": None}], "note": ""}

    monkeypatch.setattr(toc_sources, "fetch_toc", _fake_fetch)
    res = asyncio.run(probe_mod.probe_toc(None, ent["id"]))
    assert res["state"] == "ok" and res["count"] == 1
    assert calls == [(ent["id"], "我", "我")], "探测用单字当书名，只读目录页"
    assert db.source_ledger_all() == [] and db.source_imports() == [], "探测不落台账"
    # 目录结果**一个字都没写**（`store_toc_get` 对任何书都应为空表）
    assert db.store_toc_get("随便一本书") == []


def test_只登记没规则的来源如实判不支持(isolated, monkeypatch):                     # noqa: ARG001
    ent = _toc_entity(with_rule=False)
    calls: list = []

    async def _fake_fetch(*a, **kw):
        calls.append(1)
        return {"ok": True, "entries": [], "note": ""}

    monkeypatch.setattr(toc_sources, "fetch_toc", _fake_fetch)
    res = asyncio.run(probe_mod.probe_toc(None, ent["id"]))
    assert res["state"] == "unsupported" and calls == []
    assert res["supported"] == "no" and res["error"], "不支持也要说清为什么"
    assert asyncio.run(probe_mod.probe_toc(None, "没有这个来源"))["state"] == "unsupported"


# ---------------- 路由 ----------------

def test_接口_单条与全部验证(client, auth_headers, monkeypatch):
    store.add_rule(_rule("probe-api"))

    async def _stub(self, cls, title):
        return [{"title": "命中", "url": "https://probe-demo.com/1"}]

    monkeypatch.setattr(DownloadManager, "test_source", _stub)
    r = client.post("/api/sources/probe-api/probe", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ok" and r.json()["count"] == 1
    assert db.source_ledger_get("probe-api")["verify_ok"] is True

    r2 = client.post("/api/sources/probe-all", headers=auth_headers,
                     json={"names": ["probe-api", "根本没有这个源"], "interval": 0})
    assert r2.status_code == 200, r2.text
    items = {i["name"]: i for i in r2.json()["items"]}
    assert items["probe-api"]["state"] == "ok"
    assert items["根本没有这个源"]["state"] == "unsupported"
    assert r2.json()["counts"] == {"ok": 1, "unsupported": 1}


def test_接口_目录来源探测就是只读一眼(client, auth_headers, monkeypatch):
    ent = _toc_entity(with_rule=True)
    async def _fake_fetch(manager, source_id, *, book, url="", query=""):
        return {"ok": True, "entries": [{"title": "第一章", "depth": None},
                                        {"title": "第二章", "depth": None}], "note": ""}
    monkeypatch.setattr(toc_sources, "fetch_toc", _fake_fetch)
    r = client.post("/api/toc/probe", headers=auth_headers,
                    json={"source_id": ent["id"], "query": "我"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ok" and r.json()["count"] == 2
    assert db.source_ledger_all() == [], "目录来源探测不写台账，也不写 store_toc"


def test_探测接口要鉴权(client):
    assert client.post("/api/sources/x/probe", json={}).status_code in (401, 403)
    assert client.post("/api/sources/probe-all", json={"interval": 0}).status_code in (401, 403)
    assert client.post("/api/toc/probe", json={"source_id": "fanqie"}).status_code in (401, 403)


def test_台账把探测结果并进列表(client, auth_headers):
    """列表要能直接显示「最近验证 / 有效条数 / 耗时」——否则界面还得再发一轮请求。"""
    store.add_rule(_rule("probe-list"))
    db.source_ledger_upsert("probe-list", verified_at=1.0, verify_ok=True,
                            verify_count=7, verify_ms=123, verify_error="")
    led = {r["name"]: r for r in
           client.get("/api/sources/ledger", headers=auth_headers).json()["items"]}
    assert led["probe-list"]["verify_count"] == 7 and led["probe-list"]["verify_ms"] == 123
    assert led["probe-list"]["verify_ok"] is True
