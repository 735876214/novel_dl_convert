"""第 86 期：书源台账 / 去重四级判据 / 冲突三选 / 覆盖可回滚 / 导出幂等（**零网络**）。

这一份测试要钉住的是**「绝不静默覆盖用户数据」**这条纪律，以及它带来的几个具体承诺：

1. **重复导入是幂等的**：同一份文件再导入一次 ⇒ 全部判 `duplicate`、一个文件都不重写；
2. **覆盖前必须有备份**：`更新` / `覆盖` 会把旧规则原文存进历史，`rollback` 能还原回去；
3. **撞名不硬来**：源名撞上手写源 ⇒ 判 `conflict` 交用户选，默认 `skip`（不是「帮你盖掉」）；
4. **同站点也要看得出来**：导入一个与**手写源同站点**的源 ⇒ 判 `conflict`（`conflict_with` 指到那条）；
5. **不可执行的条目也能被管理**：只记台账（含逐条原因）、**不落规则**，列表里看得到、删得掉。

⚠️ 一条容易写错的契约：导入源的名字是 `lg-<归一化站点>`，而归一化会**剥掉 `www.`**
（`legado.norm_site`）—— 所以 `https://www.example-novel.com` 造出来的名字是
`lg-example-novel.com`。这不是笔误：去重键与源名共用同一套归一，才不会出现
「同一个站点、两个名字」的书源。
"""
import json
import pathlib

import pytest

from novelforge import config
from novelforge.core import db
from novelforge.sources import base, ledger, legado, store

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "legado_sample.json"


@pytest.fixture(autouse=True)
def _sandbox(isolated):                                     # noqa: ARG001
    """本模块的**真隔离**：清空 `SOURCES_DIR` 的规则文件，并还原 `REGISTRY`。

    ⚠️ 实测踩过：`isolated` 只保证「不碰真实数据」，而 `SOURCES_DIR` 与会话级临时根共享、
    `REGISTRY` 更是**进程级全局** —— 上一个用例导入的书源会留在下一个用例里。
    于是「撞名」「导出内容串味」「文件存在性」这些断言全被污染成假失败。
    要测「导入 / 去重」这种跨用例敏感的语义，必须自己清干净（这是测试侧的事，不是产品缺陷）。
    """
    d = pathlib.Path(config.SOURCES_DIR)
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob("*.json"):
        p.unlink()
    for row in db.source_ledger_all():          # 台账/历史/导入记录同样会跨用例残留
        db.source_ledger_delete(row["name"])
    db.source_imports_clear()
    before = set(base.REGISTRY)
    yield
    for name in set(base.REGISTRY) - before:
        base.REGISTRY.pop(name, None)
    db.source_imports_clear()

#: 夹具里那条「纯 HTML 源」转成规则后的源名
NAME = "lg-example-novel.com"


def _legado_entry(name: str) -> dict:
    """夹具里那条「纯 HTML 源」（判 `yes`、能转成规则）。"""
    for e in json.loads(FIXTURE.read_text(encoding="utf-8")):
        if e.get("bookSourceName") == name:
            return e
    raise AssertionError(f"夹具里没有 {name}")


def _rule(name: str, domain: str = "www.example-novel.com") -> dict:
    """一条**手写**规则（各字段合法，能过 `rules.validate_rule`）。"""
    return {
        "name": name, "display_name": name, "domains": [domain], "public": False,
        "search": {"url": f"https://{domain}/search?q={{title}}", "mode": "css",
                   "container": ".item", "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": "toc", "toc": {"mode": "css", "container": ".list a"},
                 "content": {"mode": "css", "container": "#content", "text": True}},
    }


def _saved(name: str) -> pathlib.Path:
    return pathlib.Path(config.SOURCES_DIR) / f"{name}.json"


def _import(entries: list, origin: str = "a.json", **kw) -> dict:
    return ledger.apply(ledger.plan(entries, origin=origin), origin=origin, **kw)


# ---------------- 台账 CRUD ----------------

def test_台账CRUD往返(isolated):                                    # noqa: ARG001
    assert db.source_ledger_get("x") is None
    row = db.source_ledger_upsert("x", origin="a.json", dedup_key="demo.com",
                                  unsupported=[{"field": "f", "why": "w", "instead": "i"}],
                                  notes=["n"], imported=True)
    assert row["name"] == "x" and row["dedup_key"] == "demo.com"
    assert row["enabled"] is True and row["imported"] is True
    assert row["unsupported"][0]["instead"] == "i" and row["notes"] == ["n"]

    # 部分更新：只动给到的键，别的保持
    db.source_ledger_upsert("x", supported="partial")
    got = db.source_ledger_get("x")
    assert got["supported"] == "partial" and got["dedup_key"] == "demo.com"

    assert [r["name"] for r in db.source_ledger_all()] == ["x"]
    assert db.source_ledger_set_enabled("x", False)["enabled"] is False
    assert db.source_ledger_delete("x") is True and db.source_ledger_all() == []


def test_书源变量_内部可取值_对外只给是否存在(isolated):                    # noqa: ARG001
    db.source_vars_set("fanqie-toc", "密钥", "SECRET-KEY")
    db.source_vars_set("fanqie-toc", "mode", "3")
    assert db.source_vars_get("fanqie-toc") == {"密钥": "SECRET-KEY", "mode": "3"}
    # 给界面的那份**只有布尔**（值等同凭据，绝不回显）
    keys = db.source_vars_keys("fanqie-toc")
    assert keys == {"密钥": True, "mode": True}
    assert "SECRET-KEY" not in json.dumps(keys, ensure_ascii=False)
    # 空值 = 清除该键（界面上「填了又清空」要能真的清掉）
    assert db.source_vars_set("fanqie-toc", "mode", "") == {"密钥": True}
    assert db.source_vars_clear("fanqie-toc") == 1 and db.source_vars_keys("fanqie-toc") == {}


# ---------------- 差异表（四级判据）----------------

def test_差异表_新条目(isolated):                                    # noqa: ARG001
    rows = ledger.plan([_legado_entry("示例HTML源")], origin="a.json")
    assert len(rows) == 1
    r = rows[0]
    assert r["name"] == NAME and r["verdict"] == "new"
    assert r["supported"] == "yes" and r["changed_fields"] == []
    # 纯计算：不该落任何东西
    assert not _saved(r["name"]).exists() and db.source_ledger_all() == []


def test_差异表_重复与更新(isolated):                                # noqa: ARG001
    ent = _legado_entry("示例HTML源")
    _import([ent], "first.json")
    assert ledger.plan([ent], origin="again.json")[0]["verdict"] == "duplicate", \
        "同一份文件再导入一次必须是重复（幂等）"

    # 规则本体变了（搜索地址）⇒ 判「有更新」并给出变化的字段
    changed = json.loads(json.dumps(ent))
    changed["searchUrl"] = "/search2?q={{key}}"
    rows = ledger.plan([changed], origin="v2.json")
    assert rows[0]["verdict"] == "update" and rows[0]["conflict_with"] == NAME
    assert rows[0]["changed_fields"] == ["search.url"]

    # 只在簿记块里变了（weight）⇒ 下钻一层报出来，而不是笼统地报「legado 变了」；
    # `legado.rule_hash` 永远不进这份清单（内容一变它必变，报出来是噪音）
    heavier = json.loads(json.dumps(ent))
    heavier["weight"] = 99
    assert ledger.plan([heavier], origin="v3.json")[0]["changed_fields"] == ["legado.weight"]


def test_差异表_撞上手写源的名字是冲突不是更新(isolated):                    # noqa: ARG001
    store.add_rule(_rule(NAME, "other.com"))
    rows = ledger.plan([_legado_entry("示例HTML源")], origin="a.json")
    assert rows[0]["verdict"] == "conflict" and rows[0]["conflict_with"] == NAME
    # 默认动作是最保守的跳过；`apply` 不带 resolutions 时绝不能动那条手写源
    out = ledger.apply(rows, origin="a.json")
    assert out["counts"]["skipped"] == 1
    assert json.loads(_saved(NAME).read_text(encoding="utf-8"))["domains"] == ["other.com"], \
        "手写源被覆盖了 —— 这正是本期明令禁止的"


def test_差异表_与手写源同站点也判冲突(isolated):                          # noqa: ARG001
    store.add_rule(_rule("my-example", "www.example-novel.com"))
    rows = ledger.plan([_legado_entry("示例HTML源")], origin="a.json")
    assert rows[0]["verdict"] == "conflict" and rows[0]["conflict_with"] == "my-example"
    assert rows[0]["dedup_key"] == "example-novel.com"


def test_差异表_不可执行的条目(isolated):                              # noqa: ARG001
    ent = next(e for e in json.loads(FIXTURE.read_text(encoding="utf-8"))
               if e.get("bookSourceName", "").startswith("🍅"))
    rows = ledger.plan([ent], origin="b.json")
    assert rows[0]["verdict"] == "unsupported" and rows[0]["supported"] == "no"
    assert any(u["field"] == "bookSourceUrl" for u in rows[0]["unsupported_fields"])


# ---------------- 落盘 / 冲突三选 / 回滚 ----------------

def test_不可执行条目只记台账不落规则(isolated):                            # noqa: ARG001
    ent = next(e for e in json.loads(FIXTURE.read_text(encoding="utf-8"))
               if e.get("bookSourceName", "").startswith("🍅"))
    out = _import([ent], "b.json")
    assert out["counts"]["unsupported"] == 1
    # 列表里看得到、原因看得到、但**一个规则文件都不该有**
    assert not list(pathlib.Path(config.SOURCES_DIR).glob("*.json"))
    row = db.source_ledger_get(out["items"][0]["name"])
    assert row["supported"] == "no" and row["enabled"] is False
    assert row["unsupported"][0]["instead"], "不可执行必须给替代做法"


def test_导入落盘并尊重源文件的enabled(isolated):                          # noqa: ARG001
    ent = _legado_entry("示例HTML源")
    off = json.loads(json.dumps(ent))
    off["bookSourceName"] = "停用的源"
    off["bookSourceUrl"] = "https://off.example.com"
    off["enabled"] = False
    out = _import([ent, off], "a.json")
    assert out["counts"]["new"] == 2

    on_name, off_name = NAME, "lg-off.example.com"
    assert _saved(on_name).is_file() and _saved(off_name).is_file()
    assert db.source_ledger_get(on_name)["enabled"] is True
    assert db.source_ledger_get(off_name)["enabled"] is False
    # 源文件里标了 enabled: false ⇒ **导进来就是停用**：文件在，但没注册
    assert on_name in base.REGISTRY and off_name not in base.REGISTRY


def test_冲突三选_跳过(isolated):                                    # noqa: ARG001
    store.add_rule(_rule("my-example", "www.example-novel.com"))
    out = _import([_legado_entry("示例HTML源")], "a.json", resolutions={NAME: "skip"})
    assert out["counts"]["skipped"] == 1 and out["items"][0]["action"] == "skip"
    assert not _saved(NAME).exists() and NAME not in base.REGISTRY


def test_冲突三选_两条并存自动改名(isolated):                              # noqa: ARG001
    store.add_rule(_rule("my-example", "www.example-novel.com"))
    out = _import([_legado_entry("示例HTML源")], "a.json", resolutions={NAME: "keep_both"})
    assert out["items"][0]["ok"] is True and "改名" in out["items"][0]["note"]
    assert _saved(f"{NAME}-2").is_file() and f"{NAME}-2" in base.REGISTRY
    assert _saved("my-example").is_file(), "并存不许动原来那条"


def test_覆盖前备份且可回滚(isolated):                                 # noqa: ARG001
    ent = _legado_entry("示例HTML源")
    _import([ent], "v1.json")
    assert json.loads(_saved(NAME).read_text(encoding="utf-8"))["display_name"] == "示例HTML源"

    changed = json.loads(json.dumps(ent))
    changed["bookSourceName"] = "示例HTML源（改版）"
    out = _import([changed], "v2.json")
    assert out["counts"]["update"] == 1
    assert json.loads(_saved(NAME).read_text(encoding="utf-8"))["display_name"] == "示例HTML源（改版）"

    hist = db.ledger_history_list(NAME)
    assert len(hist) == 1 and hist[0]["kind"] == "rule", "覆盖前必须留一份旧规则原文"
    ledger.rollback(NAME, hist[0]["id"])
    assert json.loads(_saved(NAME).read_text(encoding="utf-8"))["display_name"] == "示例HTML源", \
        "回滚要真的把旧规则写回去"


def test_导出往返是幂等的(isolated):                                   # noqa: ARG001
    ent = _legado_entry("示例HTML源")
    _import([ent], "a.json")
    payload = ledger.export_payload()
    assert payload["nf_export"] == 1 and payload["entries"] == [ent], \
        "导出条目里不许夹带附加字段（那会改变哈希，让「导出再导入」变成「有更新」）"

    rows = ledger.plan(ledger.entries_of(payload), origin="roundtrip.json")
    assert [r["verdict"] for r in rows] == ["duplicate"], "导出→导入必须幂等"
    assert ledger.apply(rows, origin="roundtrip.json")["counts"]["duplicate"] == 1
    assert db.ledger_history_list(NAME) == [], "重复导入不该产生备份"


def test_导入历史留痕(isolated):                                     # noqa: ARG001
    ledger.apply(ledger.plan([_legado_entry("示例HTML源")], origin="a.json"), origin="a.json",
                 actor="tester")
    rows = db.source_imports()
    assert len(rows) == 1
    assert rows[0]["origin"] == "a.json" and rows[0]["actor"] == "tester"
    assert rows[0]["counts"]["new"] == 1 and rows[0]["detail"][0]["verdict"] == "new"


# ---------------- 启停 ----------------

def test_启停_用户源可开关且文件不动(isolated):                            # noqa: ARG001
    _import([_legado_entry("示例HTML源")], "a.json")
    ok, why = store.set_enabled(NAME, False)
    assert ok and why == "" and NAME not in base.REGISTRY
    assert _saved(NAME).is_file(), "停用只是不注册，不许动文件"
    assert db.source_ledger_get(NAME)["enabled"] is False
    store.load_user_sources()          # 重启也不该把它注册回来
    assert NAME not in base.REGISTRY

    ok, _ = store.set_enabled(NAME, True)
    assert ok and NAME in base.REGISTRY


def test_启停_内置源如实拒绝(isolated):                                  # noqa: ARG001
    name = next(n for n in base.REGISTRY if not _saved(n).exists())
    ok, why = store.set_enabled(name, False)
    assert ok is False and "内置源" in why, "内置源没有规则文件 —— 不许假装停用了"


# ---------------- 与 legado 的契约 ----------------

def test_手写规则再导入判重复(isolated):                                  # noqa: ARG001
    """导出的条目也可能是**本项目规则**（手写源的形态）——它也要能再导入且判重复。"""
    store.add_rule(_rule("hand-made"))
    assert legado.detect_format(_rule("hand-made")) == "ours"
    rows = ledger.plan([_rule("hand-made")], origin="hand.json")
    assert rows[0]["name"] == "hand-made" and rows[0]["verdict"] == "duplicate", \
        "内容一字不差的手写源，再导入必须判重复（不能判成撞名冲突）"
    assert ledger.apply(rows, origin="hand.json")["counts"]["duplicate"] == 1
    # 重复之后它仍是「手写的」，没有被标成导入的
    assert db.source_ledger_get("hand-made")["imported"] is False
