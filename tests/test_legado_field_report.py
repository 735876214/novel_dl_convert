"""第 94 期 · 阶段 5：`legado.analyze` 的**全字段**报告。

**要钉住的病**：`analyze` 原先只看 5 个字段（`searchUrl` / `ruleSearch.bookList` /
`ruleToc.chapterList` / `ruleToc.chapterUrl` / `ruleContent.content`），其余十几项
**一声不响地消失** —— 用户的源里明明白白写着「详情页作者规则」「登录地址」「变量表」，
导入后那部分没了，界面上一个字都不提。这与用户报的「导入没反应」是同一族的病：
**不报错、不生效、还给出错误的结论**。

本文件分四截：

① **覆盖**：这条源里**出现过**的每一个字段都要在报告里有一行（2.x 的先归一到 3.x 键名）；
② **三档**：`executable` / `ported` / `unsupported` 各有着落，且**表外的键走兜底**
   （照样报「本项目不使用这个字段」—— 不猜含义，但见了就要说）；
③ **不越权**：全字段报告**不许**改变 `supported` 判定。「发现页不支持」进报告但**不进**
   `unsupported_fields` —— 混在一起会把 1321 条本来能用的源判成 `no`（把「如实说」做成「误杀」）；
④ **接线**：报告要真的送到 dry-run 差异表那一行（只在库里存在、界面看不到 = 没做）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from novelforge.sources import formats, intake, ledger, legado

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAMPLE3 = ROOT / "tests" / "fixtures" / "legado_sample.json"

#: 2.x 的一条最小样本 —— 键名全部来自 `202003.txt` 的实测频次表（不猜）。
LEGACY_2X = {
    "bookSourceName": "旧方言源",
    "bookSourceUrl": "https://old.example.com",
    "enable": True,
    "httpUserAgent": "Mozilla/5.0 (测试)",
    "ruleSearchUrl": "https://old.example.com/search.php?keyword=searchKey&page=searchPage",
    "ruleSearchList": ".result .item",
    "ruleSearchName": ".title@text",
    "ruleSearchNoteUrl": "a@href",
    "ruleChapterList": "#list dd",
    "ruleChapterName": "a@text",
    "ruleContentUrl": "a@href",
    "ruleBookContent": "#content@html",
    "ruleChapterUrlNext": "下一页@href",
    "ruleIntroduce": "#intro@text",
    "ruleFindUrl": "发现::https://old.example.com/find",
}

VALID_STATUS = {"executable", "ported", "unsupported"}

#: 3.x 形态的一条完整样本：主链 + 各续页 + 替换。**不是** `LEGACY_2X | {...}` 拼出来的 ——
#: 那样写会把 2.x 的 `ruleToc` / `ruleContent` 整个替换掉（字典合并是**覆盖**不是深合并），
#: 于是「主链可执行」这一组会拿到一个**没有 chapterList** 的条目。
FULL_3X = {
    "bookSourceName": "现代方言源",
    "bookSourceUrl": "https://new.example.com",
    "bookSourceType": 0,
    "enabled": True,
    "header": {"User-Agent": "Mozilla/5.0 (测试)"},
    "searchUrl": "https://new.example.com/search?q={{key}}",
    "ruleSearch": {"bookList": ".result .item", "name": ".title@text",
                   "author": ".author@text", "bookUrl": "a@href"},
    "ruleBookInfo": {"tocUrl": "/toc"},
    "ruleToc": {"chapterList": "#list dd", "chapterName": "a@text",
                "chapterUrl": "a@href", "nextTocUrl": "下一页@href"},
    "ruleContent": {"content": "#content@html", "nextContentUrl": "下一页@href",
                    "replaceRegex": "##x##y"},
}


def _ent3() -> dict:
    data = json.loads(SAMPLE3.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data, "样本夹具没了"
    return data[0]


def _report(entry: dict) -> list:
    return legado.field_report(entry)


def _by_field(entry: dict) -> dict:
    return {r["field"]: r for r in _report(entry)}


# ---------------- ① 覆盖：出现过的每个字段都要有一行 ----------------

def test_3x样本里出现过的字段一个不漏():
    ent = _ent3()
    got = _by_field(ent)
    for key, val in ent.items():
        if isinstance(val, dict):
            for sub, sv in val.items():
                if sv in (None, "", [], {}):
                    continue
                assert f"{key}.{sub}" in got, f"{key}.{sub} 没进全字段报告"
            continue
        if val in (None, "", [], {}):
            continue
        assert key in got, f"{key} 没进全字段报告"


def test_2x键名先归一_报告里出现的是3x键名():
    """报告只认 3.x 键名 —— 归一只在 `normalize_legacy` 一处（第二份必然漂）。"""
    got = _by_field(LEGACY_2X)
    assert "ruleSearch.name" in got, "2.x 的 ruleSearchName 没归一到 ruleSearch.name"
    assert "ruleSearch.bookList" in got
    assert "ruleToc.chapterUrl" in got
    assert "ruleContent.content" in got
    # 归一前的旧名字**不许**出现在报告里（出现即说明有人在别处又认了一遍方言）
    assert not [f for f in got if f.startswith("ruleSearchList") or f == "ruleSearchUrl"]
    assert "searchUrl" in got


def test_2x的UA进了请求头():
    """`httpUserAgent` → `header` 是**值级**归一（改名表表达不了），报告里要看得见。"""
    assert "header" in _by_field(LEGACY_2X)


def test_空值字段不占篇幅():
    """`""` / 空表在阅读的导出里到处都是；每一行都报一遍会把报告淹掉。"""
    got = _by_field({"name": "x", "domains": ["a.com"], "search": {},
                     "bookSourceName": "", "ruleSearch": {"kind": ""}})
    assert "bookSourceName" not in got and "ruleSearch.kind" not in got


# ---------------- ② 三档：主链可执行、老功能如实说、表外键兜底 ----------------

@pytest.mark.parametrize("field", [
    "searchUrl", "ruleSearch.bookList", "ruleSearch.name", "ruleSearch.bookUrl",
    "ruleToc.chapterList", "ruleToc.chapterUrl", "ruleContent.content",
    "ruleBookInfo.tocUrl", "ruleToc.nextTocUrl", "ruleContent.nextContentUrl",
    "ruleContent.replaceRegex", "bookSourceName", "bookSourceUrl", "header",
])
def test_主链上的字段判为可直接执行(field):
    got = _by_field(FULL_3X)
    assert got[field]["status"] == "executable", got[field]


def test_换了形态的字段判为ported():
    """`weight` / `concurrentRate` 确实被用上了，但**不是照原样**（存台账 / 换算并发）。"""
    got = _by_field({"weight": 3, "concurrentRate": "3000", "bookSourceName": "x"})
    assert got["weight"]["status"] == "ported"
    assert got["concurrentRate"]["status"] == "ported"


@pytest.mark.parametrize("field", [
    "loginUrl", "loginUi", "loginCheckJs", "variable", "jsLib", "enabledCookieJar",
    "customOrder", "serialNumber", "lastUpdateTime",
    "ruleBookInfo.name", "ruleBookInfo.intro", "ruleContent.webJs",
    "ruleContent.sourceRegex", "ruleToc.isVip",
])
def test_本项目没有的功能逐条如实说(field):
    got = _by_field({"bookSourceName": "x", "searchUrl": "https://a/",
                     "loginUrl": "u", "loginUi": "ui", "loginCheckJs": "js",
                     "variable": "v", "jsLib": "l", "enabledCookieJar": True,
                     "customOrder": 1, "serialNumber": 2, "lastUpdateTime": 3,
                     "ruleBookInfo": {"name": "n", "intro": "i"},
                     "ruleContent": {"webJs": "w", "sourceRegex": "r"},
                     "ruleToc": {"isVip": "v"}})
    row = got[field]
    assert row["status"] == "unsupported", row
    assert row["why"], f"{field} 说了不支持却没说为什么"


@pytest.mark.parametrize("key", ["exploreUrl", "enabledExplore", "ruleFindUrl", "ruleFindList"])
def test_发现页两代名字都如实说(key):
    """2.x 的 `ruleFind*` 与 3.x 的 `exploreUrl` —— 本项目**没有发现页功能**。"""
    row = _by_field({key: "发现::https://a/find"})[key]
    assert row["status"] == "unsupported"
    assert "发现页" in row["why"]


def test_表外的键走兜底而不是静默丢():
    """没见过的键**不许猜含义**，但**见了就要说** —— 这是本次「全字段」的全部意义。"""
    row = _by_field({"someFutureField": "x", "bookSourceName": "n"})["someFutureField"]
    assert row["status"] == "unsupported"
    assert "本项目不使用这个字段" in row["why"]
    assert row["instead"], "兜底也要给出路（告诉用户去哪儿手写等价规则）"


def test_报告每一行都是四件套():
    for r in _report(_ent3()):
        assert set(r) == {"field", "status", "why", "instead"}, r
        assert r["status"] in VALID_STATUS, r
        assert r["status"] != "unsupported" or r["why"], r


def test_报告表里没有非法状态也没有空原因():
    """表是数据，数据也会有笔误（写错一个状态字，界面就出现一种没人认识的说法）。"""
    for key, row in legado._FIELD_TABLE.items():
        assert row[0] in VALID_STATUS, f"{key} 的状态写错了：{row[0]}"
        assert row[1], f"{key} 没有任何说明"
        assert len(row) == 3, f"{key} 的元组形状不对"


# ---------------- ③ 不越权：报告不许改变 supported 判定 ----------------

def test_发现页只进报告_不进判定依据():
    """⚠️ 这条是**误杀防护**：把「发现页不支持」塞进 `unsupported_fields`，
    `verdict` 立刻变 `no` —— 实测 2.x 样本里 1321 条带发现页的源会**全部**被判死。"""
    an = legado.analyze(LEGACY_2X)
    assert an["supported"] in ("yes", "partial"), an["unsupported_fields"]
    fields = {u["field"] for u in an["unsupported_fields"]}
    assert not (fields & {"ruleFindUrl", "ruleFindList", "exploreUrl", "enabledExplore"}), fields
    report = {r["field"]: r["status"] for r in an["field_report"]}
    assert report["ruleFindUrl"] == "unsupported", "报告里必须说清它被忽略了"
    assert any("发现页" in n for n in an["notes"]), "人话说明还要在 notes 里"


def test_analyze把报告带出来了():
    an = legado.analyze(_ent3())
    assert isinstance(an["field_report"], list) and an["field_report"]


# ---------------- ④ 接线：报告要真的到得了差异表与前端 ----------------

def test_差异表行里带全字段报告(isolated):  # noqa: ARG001 —— 差异表要读库判冲突
    got = intake.rows_from_payload(json.dumps([_ent3()], ensure_ascii=False))
    row = got["rows"][0]
    assert row["field_report"], "差异表行里没有全字段报告 ⇒ 界面上看不到"
    assert {r["field"] for r in row["field_report"]} >= {"bookSourceName", "searchUrl"}


def test_原生格式的行也有这个键_界面不必判空(isolated):  # noqa: ARG001
    """native 走的是另一条审计（`validate_rule` + `audit_native_rule`），没有全字段清单；
    但**键必须在**（缺键的话前端 `r.field_report.length` 会炸）。"""
    native = {"name": "n1", "domains": ["a.com"],
              "search": {"url": "https://a.com/s?q={title}", "mode": "css",
                         "container": ".item", "fields": {"title": ".t"}},
              "book": {"mode": "toc", "toc": {"mode": "css", "container": "#l a"},
                       "content": {"mode": "css", "container": "#c"}}}
    row = ledger.plan([native])[0]
    assert row["field_report"] == [], "native 行也要有键（空列表），否则前端要到处判空"


def test_接口的dry_run响应里能拿到明细(client, auth_headers):
    """**端到端**：界面上「字段明细」按钮读的就是这个响应。"""
    r = client.post("/api/sources/import", headers=auth_headers,
                    json={"payload": json.dumps([_ent3()], ensure_ascii=False), "dry_run": True})
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0]
    assert row["field_report"], row
    assert all(x["status"] in VALID_STATUS for x in row["field_report"])


def test_适配器的map产物带报告():
    """格式轴只做**包装** —— 报告必须能从 `formats.map_entry` 出来，
    否则说明有人把 `analyze` 的结果在中途截断了。"""
    an = formats.map_entry(_ent3())
    assert an["field_report"], an
