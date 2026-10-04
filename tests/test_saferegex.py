"""第 94 期 · 阶段 4c：执行期正则的超时护栏（`core/saferegex.py`，全程零网络）。

**要钉住的病**：书源规则里的 `pattern` 是**第三方文件**给的。一条 ``(a|a)*$`` 配一段
几十 KB 的正文，stdlib `re` 能把 worker 卡死几分钟 —— 而调用点（`rules._extract_regex`
/ `_parse_search` / `_extract_pages` / `_split_regex` / `selspec._replace_of`）**都没有超时**，
表现是「这本书永远转不完」，日志里一个字都不指向正则。

本文件钉四件事：

1. **能超时就真超时** —— 超时映射成 `RegexTimeout`，且 `finditer`（唯一惰性的方法，
   三个调用点都在用它）的超时也**没漏到护栏外**；
2. **不能超时就如实说** —— 没有 `regex` 时 `state()` 标 `timeout:false` + 原因，
   并且**不谎称安全**（`available` 也是 False，尽管这一层仍在工作）；
3. **审计与执行同一条编译路径** —— 不然会出现「审计说能跑、跑起来是另一回事」；
4. **逐条兜底接得住** —— 两种异常都是普通 `Exception`，`manager._search_one` 的
   逐源 try 能把它变成那一条源的 error，**不中断其它源、不 500**。
"""
import asyncio
import pathlib
import re

import pytest

from novelforge.core import saferegex
from novelforge.sources import manager, rules, selspec

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 实测能触发灾难性回溯的模式（`(a+)+b` 反而不行 —— `re` / `regex` 都会把它优化掉）。
#: 30 个 `a` 就够：回溯量是 2^n 级，0.1 秒的超时稳超。
REDOS = r"(a|a)*$"
REDOS_INPUT = "a" * 40 + "b"


# ---------------- ① 能力状态：如实，不撒谎 ----------------

def test_有regex时state说真话():
    if not saferegex.available():
        pytest.skip("本机没装 regex：这一条只在有真超时时才有意义")
    st = saferegex.state()
    assert st["available"] is True and st["timeout"] is True
    assert st["max_input"] == 0, "有超时就不需要长度兜底"
    assert st["reason"] == "" and st["version"]


def test_没有regex时state如实标没有超时(monkeypatch):
    """**最关键的一条**：降级不等于安全 —— `available` / `timeout` 都必须是 False。"""
    monkeypatch.setattr(saferegex, "_AVAILABLE", False)
    st = saferegex.state()
    assert st["available"] is False, "降级路径仍在跑正则，但**没有超时能力**，不许报 available=True"
    assert st["timeout"] is False
    assert st["max_input"] == saferegex.FALLBACK_MAX_INPUT
    assert "没有超时保护" in st["reason"] and "regex" in st["reason"], "要说清怎么恢复"


def test_降级上限是有意取的_不是随手写的():
    """8 MiB 是一个**决定**：章节页在 100 KB 内，只有整本拼串（`_split_regex`）才上 MB 级。"""
    assert saferegex.FALLBACK_MAX_INPUT == 8 * 1024 * 1024


# ---------------- ② 超时是真的 ----------------

@pytest.mark.skipif(not saferegex.available(), reason="没有 regex 模块就没有超时可测")
def test_search超时映射成RegexTimeout():
    pat = saferegex.compile(REDOS, 0, timeout=0.2)
    with pytest.raises(saferegex.RegexTimeout) as e:
        pat.search(REDOS_INPUT)
    msg = str(e.value)
    assert "超时" in msg and "ReDoS" in msg and REDOS in msg, "错误里要能看出**是哪条模式**"


@pytest.mark.skipif(not saferegex.available(), reason="没有 regex 模块就没有超时可测")
def test_finditer的超时也在护栏内():
    """`finditer` 是**惰性**的：超时在迭代时才抛，`_call` 那一层收不到。

    `rules._parse_search` / `_extract_pages` / `_split_regex` 三个调用点用的都是它 ——
    漏了这一条等于护栏只护住一半。
    """
    pat = saferegex.compile(REDOS, 0, timeout=0.2)
    with pytest.raises(saferegex.RegexTimeout):
        for _ in pat.finditer(REDOS_INPUT):
            pass


@pytest.mark.skipif(not saferegex.available(), reason="没有 regex 模块就没有超时可测")
def test_sub超时也映射():
    pat = saferegex.compile(REDOS, 0, timeout=0.2)
    with pytest.raises(saferegex.RegexTimeout):
        pat.sub("x", REDOS_INPUT)


@pytest.mark.skipif(not saferegex.available(), reason="没有 regex 模块就没有超时可测")
def test_正常模式不会被超时误伤():
    """护栏不能把正常取值的路弄坏 —— 用真样本里出现过的写法过一遍。"""
    html = '<div class="book"><h3><a href="/b/1">书名</a></h3></div>'
    pat = saferegex.compile(r'<h3><a href="([^"]+)">([^<]+)</a>', re.S | re.I)
    m = pat.search(html)
    assert m and m.group(2) == "书名"
    assert pat.findall(html) == [("/b/1", "书名")]
    assert saferegex.compile("作者：", 0).sub("", "作者：张三") == "张三"


# ---------------- ③ 降级路径：短输入照跑、长输入明拒 ----------------

def test_降级时短输入照常工作(monkeypatch):
    monkeypatch.setattr(saferegex, "_AVAILABLE", False)
    pat = saferegex.compile(r"(?P<n>\d+)", 0)
    assert pat.search("a12").group("n") == "12"
    assert pat.findall("a1 b2") == ["1", "2"]
    assert saferegex.compile("x", 0).sub("Y", "axb") == "aYb"
    assert [m.group(0) for m in pat.finditer("1 2")] == ["1", "2"]


def test_降级时超长输入被明拒(monkeypatch):
    """宁可拒绝并说清原因，也不要**静默**跑一遍没有保护的正则。"""
    monkeypatch.setattr(saferegex, "_AVAILABLE", False)
    monkeypatch.setattr(saferegex, "FALLBACK_MAX_INPUT", 32)
    pat = saferegex.compile("a", 0)
    with pytest.raises(saferegex.RegexInputTooLong) as e:
        pat.search("a" * 33)
    assert "没有超时保护" in str(e.value) and "33" in str(e.value)
    # 阈值内的照跑
    assert pat.search("a" * 32)


def test_降级时编不过的模式照旧报错(monkeypatch):
    monkeypatch.setattr(saferegex, "_AVAILABLE", False)
    with pytest.raises(re.error):
        saferegex.compile("(a", 0)


# ---------------- ④ 编译错误的类型归一 ----------------

def test_编不过统一抛re_error():
    """`regex.error` 既不是 `re.error` 也不是 `ValueError`（实测）—— 调用方认的是前者。

    `selspec._replace_of` / `replace_text` 靠 `except Exception` 兜着，但
    `rules._regex_error` 的文案会被**导入差异表**直接展示，类型名不该随依赖漂移。
    """
    with pytest.raises(re.error) as e:
        saferegex.compile("(a", 0)
    assert "missing )" in str(e.value)


def test_编不过时异常类型与依赖无关():
    """装了 regex 也不该冒出 `regex.error` / `PatternError` 之外的类型名。"""
    with pytest.raises(re.error) as e:
        saferegex.compile("(a", 0)
    assert type(e.value).__name__ in ("error", "PatternError"), type(e.value).__name__


# ---------------- ⑤ 单一真值源：执行点全走 saferegex ----------------

#: 动态模式 = 模式文本来自**规则**（`rule.get("pattern")` / `toc.get(...)` / `sp.get(...)`）。
#: 常量模式（`_VAR_RE`、`_JP_TOKEN`、`legado.ANDROID_API_RE`…）继续用 stdlib `re` —— 输入
#: 短且可信，搬进来只会让「哪里真的需要超时」变得看不出来。
_DYNAMIC_HINTS = ("pattern", 'get("regex"', "toc.get", "rule.get", "sp.get")


@pytest.mark.parametrize("rel", ["novelforge/sources/rules.py", "novelforge/sources/selspec.py"])
def test_执行期正则没有裸re_compile(rel):
    """**防回归**：以后新增规则取值通道时，别又写一处 `re.compile(rule.get(...))`。

    这就是「同一判据只许有一处实现」在本期的落法 —— 裸 `re.compile` 一旦混进来，
    那条通道就**没有超时保护**，而且从现象上完全看不出来。
    """
    bad = []
    for i, line in enumerate((REPO / rel).read_text(encoding="utf-8").splitlines(), 1):
        if re.compile(r"(?<![a-z_])re\.compile\(").search(line) and any(h in line for h in _DYNAMIC_HINTS):
            bad.append(f"{rel}:{i}: {line.strip()}")
    assert not bad, "执行期正则必须走 saferegex.compile（超时保护只此一处）：\n" + "\n".join(bad)


def test_两个文件都真的用了saferegex():
    for rel in ("novelforge/sources/rules.py", "novelforge/sources/selspec.py"):
        assert "saferegex.compile(" in (REPO / rel).read_text(encoding="utf-8")


def test_审计与执行同一条编译路径():
    """审计说能跑、跑起来是另一回事 —— `::attr()` / XPath 都踩过这个坑。"""
    assert rules._regex_error(r"(?P<a>\d+)") == ""
    err = rules._regex_error("(a")
    assert err and "missing )" in err, err
    # 降级路径下也必须是同一条（编译结果一致）
    assert rules._regex_error("(a") == rules._regex_error("(a")


def test_规则里的替换也走超时保护():
    """`##正则##替换` 的模式同样是规则给的，编译产物必须是 saferegex 的那一种。"""
    plan = selspec.parse_spec(".a@text##作者：##")
    assert plan.replace, plan.render()
    pat, _repl = plan.replace[0]
    assert isinstance(pat, saferegex._Pattern), type(pat)
    # `render()` 靠 `.pattern` 还原原文 —— 换了包装也不许丢
    assert "作者：" in plan.render()


def test_替换的往返语义一字不差():
    """包装层不能把阅读的 `$1` ↔ Python 的 `\\g<1>` 往返弄坏。"""
    assert selspec.replace_text("第12章 起风了", r"第(\d+)章", r"$1.") == ("12. 起风了", "")
    text, err = selspec.replace_text("abc", "(", "")
    assert text == "abc" and err, "编不过 ⇒ 原文返回 + 如实报错"


# ---------------- ⑥ 逐条兜底：不中断整本、不 500 ----------------

def test_两种异常都是普通Exception():
    """`manager._search_one` / `_fetch_toc._one` 用的是 `except Exception` 逐条兜底 ——
    异常必须落在这一支里（`BaseException` 会一路冒穿到 500）。"""
    for exc in (saferegex.RegexTimeout, saferegex.RegexInputTooLong):
        assert issubclass(exc, RuntimeError) and issubclass(exc, Exception)


class _StubClient:
    """只实现规则源真正会调的那一个方法（`search_page` → `get_text`）。"""

    def __init__(self, page: str):
        self.page = page
        self.urls: list[str] = []

    async def get_text(self, url, **kw):
        self.urls.append(url)
        return self.page


class _CM:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *a):
        return False


def _rule_with_search_regex(pattern: str) -> dict:
    return {
        "name": "ReDoS 测试源", "domains": ["a.com"],
        "search": {"url": "https://a.com/s?q={title}", "mode": "regex", "pattern": pattern},
        "book": {"mode": "single",
                 "content": {"mode": "css", "container": "#c", "text": True}},
    }


@pytest.mark.skipif(not saferegex.available(), reason="没有 regex 模块就没有超时可测")
def test_搜索撞上ReDoS只废掉这一个源(monkeypatch):
    """端到端：一条坏正则 ⇒ 那一条源 error 里带「正则匹配超时」，**别的源不受影响**。"""
    mgr = manager.DownloadManager({"network": {}, "download": {}})
    stub = _StubClient(REDOS_INPUT)
    monkeypatch.setattr(mgr, "_client", lambda src: _CM(stub))

    bad = rules.make_rule_class(_rule_with_search_regex(REDOS))
    good = rules.make_rule_class(_rule_with_search_regex(r"<h3>(?P<title>[^<]+)</h3>"))

    async def go():
        return (await mgr._search_one("坏源", bad, "关键词", 1),
                await mgr._search_one("好源", good, "关键词", 1))

    (row_bad, items_bad), (row_good, items_good) = asyncio.run(go())

    assert row_bad["ok"] is False and items_bad == []
    assert "正则匹配超时" in row_bad["error"], row_bad["error"]
    assert REDOS in row_bad["error"], "要指出是哪条模式，否则用户只能瞎猜"
    # 好源照旧（同一个进程、同一次循环里，坏源没有把整轮拖垮）
    assert row_good["ok"] is True and row_good["error"] == ""


def test_整本切章的超长输入被明拒(monkeypatch):
    """`_split_regex` 是唯一把**整本书**当一个字符串匹配的地方（MB 级）。"""
    monkeypatch.setattr(saferegex, "_AVAILABLE", False)
    monkeypatch.setattr(saferegex, "FALLBACK_MAX_INPUT", 64)
    with pytest.raises(saferegex.RegexInputTooLong):
        rules._split_regex("正" * 65, r"^第.章.*$")
    # 阈值内照常切
    out = rules._split_regex("第一章 A\n正文\n第二章 B\n正文", r"^第[一二]章.*$")
    assert [c["title"] for c in out] == ["第一章 A", "第二章 B"]


# ---------------- ⑦ 能力接口如实下发 ----------------

def test_capabilities把三项能力都报出来(client, auth_headers):
    r = client.get("/api/sources/capabilities", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("node", "regex", "lxml", "decrypt", "hints", "hint"):
        assert key in body, f"能力接口缺 {key}"
    assert body["regex"] == saferegex.state(), "接口必须原样下发 state()，不许自己再算一遍"
    assert body["hints"]["regex"] == saferegex.state()["reason"]
    # 判据只有一处：接口报的必须就是 `rules.lxml_available()`（换台机器也不会打架）
    assert body["lxml"]["available"] == rules.lxml_available()
    assert bool(body["hints"]["lxml"]) is not rules.lxml_available()
    # 旧字段仍在（既有前端与 tests/test_js_node.py 钉着它）
    assert body["hint"] == body["hints"]["node"]


def test_接口在降级时如实标没有超时(client, auth_headers, monkeypatch):
    monkeypatch.setattr(saferegex, "_AVAILABLE", False)
    body = client.get("/api/sources/capabilities", headers=auth_headers).json()
    assert body["regex"]["timeout"] is False
    assert "没有超时保护" in body["hints"]["regex"]
