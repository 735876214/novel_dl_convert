"""第 94 期：**转换诚实闸**（`rules.audit_native_rule`）—— 全程零网络。

## 这一版修的是什么

`legado.convert` 把 Legado 源转成 native 规则后，**由转换器自己声明** `supported`。
转换器既当运动员又当裁判 ⇒ 真实样本（XIU2 `shuyuan`，22 条）实测「9 条判可用」里有
**7 条**一搜就炸 —— 不是「结果不准」，是 `soup.select_one("#author tbody tr!0")`
**直接抛 SelectorSyntaxError**（下面 `test_索引语法真的会抛异常` 就是这条的铁证）。

修法：把「引擎能跑什么」这一判断**收进引擎自己**（`rules.audit_native_rule`，唯一真值源），
`legado.analyze` 的 `supported` 由它的结论反推；**任何格式的适配器产物**都过这一关
（手写 native 规则、本项目导出文件也一样 —— 没有例外通道）。

⚠️ 如实标注：加了这道闸，**被判「可用」的源会变少**。实测 22 条（XIU2 `shuyuan`）：
旧的转换器自称可用 **9** 条，其中 **7** 条的选择器在裸 bs4 下**编译不过**
（=当年一搜就抛 `SelectorSyntaxError`）；加闸后落到 `yes 0 / partial 2 / no 20`，假可用 0。
少掉的是「本来一搜就抛异常」的那些，是修正不是退化。
闸门会**单调变短**：阶段 2/3 每补一项能力就摘掉 `_UNSUPPORTED_CONSTRUCTS` 里的一条并补用例。
实测分布（**假可用恒为 0**，这是本文件的验收点）：

| 样本 | 加闸前（自称可用 / 其中真能跑） | 阶段 2b | 阶段 2c（现在） |
|---|---|---|---|
| `shuyuan`（22 条，3.x） | 9 / 3 | `yes 1 · partial 6 · no 15` | **`yes 2 · partial 6 · no 14`** |
| `202003.txt`（1537 条，2.x） | 0 / 0 | `yes 398 · partial 403 · no 736` | **`yes 685 · partial 357 · no 495`** |

还差的那些见 `_UNSUPPORTED_CONSTRUCTS` 现存条目（阶段 2c 又摘掉 XPath 这一条：
1537 条里 **120 条**源用了 XPath ⇒ 可用 993 → **1042**）。
"""
import json
import pathlib

import pytest

from novelforge.sources import formats, intake, legado, rules

FIX_DIR = pathlib.Path(__file__).parent / "fixtures"
FIXTURE3 = FIX_DIR / "legado3_real.json"
FIXTURE2 = FIX_DIR / "legado2_real.json"

#: 闸门自己生成的构造标识（不是 `_UNSUPPORTED_CONSTRUCTS` 里那几条）
#: `replace_regex` 是阶段 2a 新增的：`##正则##替换` 现在真的会跑，但**编译不过**的那一段
#: 会被丢掉（取值会带着该去掉的原文）—— 静默变差也要报出来。
#: 阶段 2b 又加四条：URL 选项**认不出的键** / **编码解不了** / **选项字典读不出来** /
#: **地址不是 http(s)** —— 前三条以前一律挤在 `url_option_dict` / `url_option_pipe`
#: 里笼统报「整段字典会当着地址发出去」，现在引擎真的会发 POST / 真的会按 `charset` 解码，
#: 那两条必须撤；剩下这三种情况仍要拦，且要说清是哪一种。
GENERATED = ("android_bridge", "selector_syntax", "regex_syntax", "jsonpath_syntax",
             "unknown_mode", "no_url_field", "not_object", "replace_regex",
             "url_option_unknown", "url_option_charset", "url_option_broken", "url_not_http")


@pytest.fixture(scope="module")
def entries3() -> list:
    return json.loads(FIXTURE3.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def entries2() -> list:
    return json.loads(FIXTURE2.read_text(encoding="utf-8"))


def _rule(container=".book", fields=None, url="https://a.com/s?q={title}", **extra) -> dict:
    """一份**最小可跑**的 native 规则（改一处就能测出一条构造）。"""
    search = {"url": url, "mode": "css", "container": container,
              "fields": fields if fields is not None else {"title": ".t", "url": "a::attr(href)"}}
    search.update(extra.pop("search", {}))
    rule = {"name": "测试源", "domains": ["a.com"], "search": search,
            "book": {"mode": "single", "content": {"mode": "css", "container": "#c", "text": True}}}
    rule.update(extra)
    return rule


def _constructs(rule) -> set:
    return {f["construct"] for f in rules.audit_native_rule(rule)}


def _by_name(entries: list, name: str) -> dict:
    for e in entries:
        if e.get("bookSourceName") == name:
            return e
    raise AssertionError(f"夹具里没有 {name}")


# ---------------- 干净规则必须一分不扣（否则闸门会误杀能用的源） ----------------

def test_能跑的规则审计为空():
    assert rules.audit_native_rule(_rule()) == []
    assert rules.audit_native_rule(_rule(container=".book",
                                        fields={"title": ".t", "url": "a::attr(href)"})) == []
    # regex 通道 + json 通道
    assert rules.audit_native_rule(_rule(search={"mode": "regex", "pattern": r"<a href='(.*?)'"},
                                         container=None, fields=None)) == []
    assert rules.audit_native_rule(_rule(search={"mode": "json", "container": "$.data[*]",
                                                 "path": "$.data[*]",
                                                 "fields": {"title": "$.name", "url": "$.url"}},
                                         container=None, fields=None)) == []
    # 正文用 js 通道（正则路径）是合法的
    r = _rule()
    r["book"]["content"] = {"mode": "js", "script": "result.replace(/x/g, '')"}
    assert rules.audit_native_rule(r) == []


# ---------------- 逐条构造：id 要对，理由要能给用户照做 ----------------

@pytest.mark.parametrize("mutate, expect", [
    # 阶段 2b：`{'method':'post'}` 与 `|char=gbk` 现在**真的会按它发请求** ⇒ 不再拦
    # （用例见 `tests/test_engine_urlspec.py`）。**仍要拦**的是下面这四种。
    (lambda r: r["search"].update({"url": "https://a.com/s?q={title},{'method':'PUT'}"}),
     "url_option_unknown"),
    (lambda r: r["search"].update({"url": "https://a.com/s?q={title}|char=escape"}),
     "url_option_charset"),
    (lambda r: r["search"].update({"url": "https://a.com/s?q={title},{'method':'get','webView':true}"}),
     "url_option_broken"),
    (lambda r: r["search"].update({"url": "/s?q={title}"}), "url_not_http"),
    (lambda r: r["search"].update({"url": "https://a.com/s?q=searchKey"}), "legacy_placeholder"),
    (lambda r: r["search"].update({"url": "https://a.com/s?q={title}&p={{page}}"}), "tpl_leftover"),
    (lambda r: r["search"].update({"container": "//div[@id='x']/p"}), "xpath"),
    (lambda r: r["search"].update({"container": "(((//div"}), "xpath"),
    (lambda r: r["search"].update({"container": "@@bad"}), "selector_syntax"),
    # 实测真源里的写法（天天看小说）：`@children[0]` 不是合法选择器 —— 仍如实拦下
    (lambda r: r["search"].update({"container": "class.x@children[0]@tag.a"}), "selector_syntax"),
    (lambda r: r["search"]["fields"].update({"author": "$.a['b']"}), "jsonpath_in_css"),
    (lambda r: r["search"]["fields"].update({"author": "JSon:$.title"}), "jsonpath_in_css"),
    # 阶段 2c：`xpath` 已经是**合法** mode ⇒ 这一条改用真正不认识的值（口径不变：不许静默当 css）
    (lambda r: r["search"].update({"mode": "yaml"}), "unknown_mode"),
    (lambda r: r["search"].pop("fields"), "no_url_field"),
    (lambda r: r["book"]["content"].update(
        {"mode": "js", "script": "java.ajax(book.bookUrl)"}), "android_bridge"),
    # `##` 的**正则**编译不过（Java 写法 `<a href="(.*)">` 里的 `$1` 组名差异、括号不配对…）
    # ⇒ 那一段替换会被丢掉，取值带着该去掉的原文（静默变差），必须报
    (lambda r: r["search"]["fields"].update({"author": ".a##(未闭合"}), "replace_regex"),
])
def test_每一条构造都拦得住_且理由可照做(mutate, expect):
    rule = _rule()
    mutate(rule)
    bad = rules.audit_native_rule(rule)
    assert expect in {b["construct"] for b in bad}, f"{expect} 没拦下：{bad}"
    for b in bad:
        assert b["field"] and b["why"] and b["instead"], b
        # 理由里要能看到**原文的一段** —— 只说「有问题」不说「哪一段」等于让人自己找
        assert b["field"] != "?" and len(b["why"]) > 8


@pytest.mark.parametrize("mutate, expect", [
    # json 通道：只看 `$.a.b` / `$.a[0]` / `$.a[*]` / `$..k` 这一子集（`_jp_tokens` 的实现）
    (lambda r: r["search"].update({"path": "$.data['list'][*]"}), "jsonpath_ext"),
    (lambda r: r["search"].update({"path": "$.data[1:2]"}), "jsonpath_ext"),
    (lambda r: r["search"].update({"path": "$.data[?(@.k=='v')]"}), "jsonpath_ext"),
    (lambda r: r["search"]["fields"].update({"title": "$.list[0,1]"}), "jsonpath_ext"),
    # 选项字典本身能读（阶段 2b），但这个「地址」是条 JSON 路径，发不出去
    (lambda r: r["search"].update({"url": "$.items[*],{'method':'post'}"}), "url_not_http"),
])
def test_JSON通道的越界写法也拦得住(mutate, expect):
    rule = _rule(search={"mode": "json", "container": "$.data[*]", "path": "$.data[*]",
                         "fields": {"title": "$.name", "url": "$.url"}})
    mutate(rule)
    bad = rules.audit_native_rule(rule)
    assert expect in {b["construct"] for b in bad}, f"{expect} 没拦下：{bad}"
    assert all(b["why"] and b["instead"] for b in bad)


def test_子集内的JSON路径一分不扣():
    for path in ("$.data", "$.data.list", "$.data[0]", "$.data[*]", "$..title"):
        r = _rule(search={"mode": "json", "container": path, "path": path,
                          "fields": {"title": "$.name", "url": "$.url"}})
        assert rules.audit_native_rule(r) == [], path


def test_闸门声明表是自洽的():
    """`_UNSUPPORTED_CONSTRUCTS` 是**给界面看的**：每条都得四要素齐全（界面直接渲染）。"""
    declared = {c["id"] for c in rules._UNSUPPORTED_CONSTRUCTS}
    assert declared <= set(rules.MODES) | set(GENERATED) | declared
    assert len(declared) == len(rules._UNSUPPORTED_CONSTRUCTS) == len(
        {c["id"] for c in rules._UNSUPPORTED_CONSTRUCTS})
    # 每条声明都要有 4 个字段齐全的说明（界面直接展示）
    for c in rules._UNSUPPORTED_CONSTRUCTS:
        assert c["id"] and c["what"] and c["why"] and c["instead"] and c["kinds"]
        #: 阶段 2c 起多了 `xpath` 这一档：`tpl_leftover` 在 XPath 通道里同样拦得住
        #: （`{{page}}` 在 XPath 里也会原样拼出去）—— 声明表要跟着通道数走。
        assert c["kinds"] and set(c["kinds"]) <= {"url", "selector", "regex", "jsonpath", "xpath"}


def test_未知mode不会被当成css静默跑():
    """**口径变化**（CHANGELOG 有记）：未知 mode 以前会静默落回 css 通道。

    ⚠️ 阶段 2c 起 `xpath` **是**已知通道（用例见 `tests/test_engine_xpath.py`）——
    这条钉的是「**不认识**的值不许被当成 css 跑」，不是「值必须少」。
    """
    r = _rule(search={"mode": "yaml"})
    assert "unknown_mode" in _constructs(r)
    # 正文允许 js，搜索不允许
    assert rules.audit_native_rule(_rule(search={"mode": "js", "script": "1"})) != []
    assert "unknown_mode" in _constructs({"name": "x", "domains": ["a.com"],
                                         "search": {"url": "https://a/s?q={title}"},
                                         "book": {"mode": "图"}})
    assert "unknown_mode" in _constructs({**_rule(), "chapter": {"mode": "猜"}})
    # 合法值一个都不报（含阶段 2c 新增的 xpath）
    assert "unknown_mode" not in _constructs({
        **_rule(), "book": {"mode": "toc", "toc": {"mode": "css", "container": "li a"},
                            "content": {"mode": "regex", "pattern": "x"}}})
    assert "unknown_mode" not in _constructs({
        **_rule(search={"mode": "xpath", "container": '//ul/li',
                        "fields": {"title": "//a/text()", "url": "//a/@href"}}),
        "book": {"mode": "single",
                 "content": {"mode": "xpath", "container": '//*[@id="c"]'}}})


def test_拼不出请求地址的规则要单独说():
    """`{}` 走结构检查会答成「没有详情页地址」——那是答非所问，必须单独一条。"""
    for bad in ({}, None, [], "字符串", 3):
        got = rules.audit_native_rule(bad)
        assert len(got) == 1 and got[0]["construct"] == "not_object"


def test_审计绝不抛异常():
    """脏输入（真实世界里什么都有）只许如实报理由，不许把整次导入带崩。"""
    for junk in ({}, {"search": "不是字典"}, {"search": {"fields": "不是字典"}},
                 {"book": None}, {"search": {"url": None, "container": 3, "fields": {"a": 4}}},
                 {"search": {"mode": None}}, {"legado": {"x": object()}},
                 {"search": {"fields": {"u": "\x00\ud800"}}}):
        assert isinstance(rules.audit_native_rule(junk), list)


def test_选择器编译是问编译器不是猜():
    """`soupsieve`（bs4 的依赖）真的编译一次 —— 正则猜不出来 `children[0]` 不合法。"""
    assert rules._css_error(".book-item") == ""
    assert rules._css_error("a::attr(href)") == "", "本项目自己的取值后缀要先摘掉再编译"
    assert rules._css_error(".full_chapters children[0] a") != ""
    assert rules._css_error("@@bad") != ""
    assert rules._css_error("") == "" and rules._css_error(".") == ""
    assert rules._regex_error("(未闭合") != "" and rules._regex_error("^a+$") == ""


def test_索引语法真的会抛异常_但引擎不再把它交给选择器():
    """这条既是**闸门存在的理由**，也是**阶段 2a 的验收点**。

    原生 `soup.select_one("#author tbody tr!0")` 直接抛 `SelectorSyntaxError`
    （搜索与目录的调用点**没有 try 保护** ⇒ 一条判「可用」的规则会让整次搜索 500）。
    阶段 2a 起这类写法**不再直接进选择器**：`selspec` 先把索引摘下来、按「匹配列表第 n 个」
    执行，写坏了的落成空值 + 人话 error（用例在 `tests/test_engine_selspec.py`）。
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup("<html><body><a>x</a></body></html>", "html.parser")
    for sel in ("#author tbody tr!0", ".odd.0", "a.0"):
        with pytest.raises(Exception):                       # noqa: B017 —— 抛什么都行，重点是**会抛**
            soup.select_one(sel)
    # 引擎里同一条写法：不再抛，而且**真的取到值**（`a.0` = 第一个 a 的文本）
    assert rules._field_value(soup, "a.0") == "x"
    assert "legado_index" not in _constructs(_rule(search={"container": "#author tbody tr!0"}))


# ---------------- 闸门接在转换器上：真实样本 ----------------

def test_analyze的结论由引擎反推(entries3, entries2):
    """`supported` 不再由转换器自称：判可用 ⇒ 产物必须过审计。"""
    for ent in list(entries3) + list(entries2):
        got = legado.analyze(ent)
        rule = got["converted_rule"]
        if got["supported"] == "no":
            continue
        assert rule is not None
        assert rules.audit_native_rule(rule) == [], \
            f"{ent.get('bookSourceName')} 自称 {got['supported']} 但引擎跑不动"


def test_假可用实证_现在全拦下(entries3):
    """真样本里逐条对上「以前判可用、其实一搜就炸」（**这几条在 22 条真源整份跑时都判「可用」**）。

    理由必须**指到具体字段**：阶段 2a 之前这几条会退化成一个笼统的「（整体）拼不出规则」
    （转换器提前 `return None`，闸门就看不到是哪一项不行）—— 那正是「答非所问」。

    ⚠️ 这份名单**只会变短**（闸门单调变诚实），每摘掉一条都要有「它现在真的跑得动」的用例兜着：
    - 阶段 2a 摘掉 `legado_index` / `hash_hash_replace` / `legado_sel_syntax`
      （见 `tests/test_engine_selspec.py`）；
    - 阶段 2b 摘掉 `url_option_dict` / `url_option_pipe` —— 速读谷 / 武林中文网 退出本表
      （见 `test_阶段2b放进来的条目_选项不再是拦点`）；
    - 阶段 2c 摘掉 XPath —— **手机小说**（目录容器是 `//…`）退出本表，见
      `test_阶段2c放进来的条目_XPath不再是拦点`。

    夹具是 22 条真源里裁的 8 条；留下的这条卡在阅读的选择器方言上（`class.full_chapters
    @children[0]@tag.a` 里的 `children[0]` 不是合法 CSS，`@tag.a` 也不是 CSS 的写法）。
    """
    cases = {
        "天天看小说": {"selector_syntax"},                        # `class.full_chapters@children[0]@tag.a`
    }
    for name, expect in cases.items():
        got = formats.map_entry(_by_name(entries3, name))
        assert got["supported"] == "no", f"{name} 还是「可用」——假可用没堵住"
        assert expect <= {u["construct"] for u in got["unsupported_fields"]}, \
            f"{name} 的理由不对：{got['unsupported_fields']}"
        for u in got["unsupported_fields"]:
            assert u["field"] != "（整体）", f"{name} 又退化成了笼统理由：{u}"
        assert not ({"url_option_dict", "url_option_pipe", "url_option_broken"}
                    & {u["construct"] for u in got["unsupported_fields"]}), \
            f"{name} 还在按选项字典拦 —— 引擎已经会按选项发请求了"
    # 那两类构造**已从声明表里撤掉**（撤表与「引擎真会做」必须同批，否则界面还在吓人）
    declared = {c["id"] for c in rules._UNSUPPORTED_CONSTRUCTS}
    assert not ({"url_option_dict", "url_option_pipe"} & declared), declared


def test_阶段2b放进来的条目_选项不再是拦点(entries3):
    """摘掉 `url_option_dict` / `url_option_pipe` 的**实证**：夹具里**三条**带选项字典。

    `searchUrl` 形如 `/search.php,{'method':'post','body':'searchkey={{key}}…'}`（速读谷 / 武林中文网）
    或 `,{'charset':'gbk',…}`（手机小说）。当年判「可用」是**假可用** —— 整段字典被当成地址的
    一部分发出去；阶段 1 拦下，阶段 2b 把能力补进引擎（`parse_url_spec` +
    `BrowserClient.get_text(method/body/charset)`）之后**才**真的能用。

    ⚠️ 阶段 2c 起这三条**都走到头了**：手机小说当时另有一处卡点（目录容器是 XPath），
    2c 把 XPath 补成正式通道之后它也整体可用 —— 选项类构造在三条里**一条都不剩**
    （手机小说的「现在能用」另有用例：`test_阶段2c放进来的条目_XPath不再是拦点`）。
    """
    seen = 0
    for name, want in (("速读谷", {"method": "post"}),
                       ("武林中文网", {"method": "post"}),
                       ("手机小说", {"charset": "gbk", "method": "post"})):
        got = formats.map_entry(_by_name(entries3, name))
        rule = got["converted_rule"]
        assert rule is not None, f"{name} 连产物都没有：{got['unsupported_fields']}"
        spec = rules.parse_url_spec(str(rule["search"]["url"]))
        assert spec.opts and not spec.unknown, f"{name} 的选项没解析出来：{spec}"
        for k, v in want.items():
            assert spec.opts.get(k) == v, f"{name} 的 {k} 选项丢了：{spec.opts}"
        # 引擎自己的结论：产物过审计 —— 选项这一块**一律**不许再成为拦点
        bad = {u["construct"] for u in rules.audit_native_rule(rule)}
        assert not ({"url_option_dict", "url_option_pipe", "url_option_unknown",
                     "url_option_charset", "url_option_broken", "url_not_http"} & bad), \
            f"{name} 的选项部分仍不可执行：{bad}"
        assert got["supported"] != "no", f"{name} 仍被判死：{got['unsupported_fields']}"
        assert rules.audit_native_rule(rule) == []
        assert rules.validate_rule(rule) == []
        seen += 1
    assert seen == 3


def test_阶段2a放进来的两条_以前拦着现在能用(entries3):
    """摘掉构造的**实证**：`铅笔小说`（正文 `##…##`）与 `武林中文网`（`!-1` 索引）。

    这两条当年判「可用」是**假可用**（`##` 原样进正文、`!-1` 一搜就抛异常），阶段 1 先把
    它们拦下（判 `no`），阶段 2a 把能力补进引擎之后**才**真的能用 —— 拦下与放开都不是拍脑袋。
    """
    got = formats.map_entry(_by_name(entries3, "铅笔小说"))
    assert got["supported"] == "partial", got["unsupported_fields"]
    assert "hash_hash_replace" not in {u["construct"] for u in got["unsupported_fields"]}
    assert "##" in got["converted_rule"]["book"]["content"]["container"]
    assert rules.audit_native_rule(got["converted_rule"]) == []


def test_阶段2c放进来的条目_XPath不再是拦点(entries3):
    """摘掉 XPath 阻塞的**实证**：`手机小说` 的目录容器是 `//*[@id="chapterlist"]…` 一类的 XPath。

    它当年判「可用」是**假可用**（XPath 被当成 CSS 编译 ⇒ 一取目录就空/炸），阶段 1 因此判它 `no`，
    阶段 2c 把 XPath 补成**正式通道**（`mode:"xpath"`，唯一执行处 `rules._xpath_nodes`）之后才真的能用 ——
    放开与当初拦下是**同一个判据**（`audit_native_rule`）给出的两个结论，不是拍脑袋翻案。

    另：它的搜索地址还带着 `,{'charset':'gbk','method':'post'}` 选项字典（见上一个用例），
    这条源因此是「阶段 2b + 2c 两处能力叠起来才活」的那一类。
    """
    got = formats.map_entry(_by_name(entries3, "手机小说"))
    assert got["supported"] != "no", got["unsupported_fields"]
    rule = got["converted_rule"]
    assert rules.audit_native_rule(rule) == [] and rules.validate_rule(rule) == []
    assert rule["book"]["toc"]["mode"] == "xpath", rule["book"]["toc"]
    assert rule["book"]["toc"]["container"].startswith("//")
    # 「XPath 通道写选择器」这条错配**没有**落到它身上：卡点是被支持，不是被绕过
    assert "xpath" not in {u["construct"] for u in got["unsupported_fields"]}


def test_转换不出来时的理由指到具体字段(entries3):
    """酷我小说是「跨条目拼 URL」那一类：理由要指到 `ruleToc.chapterUrl` 而不是笼统说不行。"""
    got = formats.map_entry(_by_name(entries3, "酷我小说"))
    assert got["supported"] == "no"
    hit = [u for u in got["unsupported_fields"] if u["field"] == "ruleToc.chapterUrl"]
    assert hit and "每条目录项" in hit[0]["why"] and hit[0]["instead"], got["unsupported_fields"]


def test_拼不出规则时给的是整体理由():
    """逐字段看着都能转、却拼不出完整规则时，必须有一条「（整体）」的理由。"""
    got = formats.map_entry({"bookSourceName": "半成品", "bookSourceUrl": "https://a.com",
                             "ruleSearchList": "class.item@tag.a",
                             "ruleSearchUrl": "/s?q=searchKey", "ruleContent": {"content": ""}})
    assert got["supported"] == "no"
    assert any(u["field"] == "（整体）" and u["why"] and u["instead"]
               for u in got["unsupported_fields"]), got["unsupported_fields"]


def test_不是所有源都被判死(entries3):
    """闸门要**准**：真实样本里确实能跑的必须留下，否则就成了「一刀切判 no」蒙混过关。"""
    keep = {n: formats.map_entry(_by_name(entries3, n))["supported"]
            for n in ("得奇小说网", "快书网")}
    assert all(v == "partial" for v in keep.values()), keep
    for name in keep:
        rule = formats.map_entry(_by_name(entries3, name))["converted_rule"]
        assert rules.validate_rule(rule) == [] and rules.audit_native_rule(rule) == []


def test_一份真实文件里没有假可用(entries3, entries2):
    """**本期验收的核心断言**：整份文件里，凡是判「可用」的，引擎真的能跑。"""
    for entries in (entries3, entries2):
        claimed = [e for e in entries if formats.map_entry(e)["supported"] != "no"]
        assert claimed, "整份文件全判 no ⇒ 这不是诚实，是一刀切"
        for e in entries:
            got = formats.map_entry(e)
            if got["supported"] == "no":
                assert got["unsupported_fields"], e.get("bookSourceName")
            else:
                assert rules.audit_native_rule(got["converted_rule"]) == [], \
                    f"{e.get('bookSourceName')} 是假可用"


def test_判no的条目也留在差异表里_且带原因(entries3, isolated):
    """不可执行的条目要能看到、能删、能看到「为什么不能用」—— 不许悄悄丢掉。"""
    res = intake.rows_from_payload(json.dumps(entries3, ensure_ascii=False), origin="测试")
    rows = {r["name"]: r for r in res["rows"]}
    assert len(rows) == len(entries3)
    for row in rows.values():
        if row["supported"] == "no":
            assert row["verdict"] == "unsupported"
            assert row["unsupported_fields"], row["name"]
            assert all(u["why"] and u["instead"] for u in row["unsupported_fields"])
        else:
            assert row["converted_rule"] is not None


# ---------------- 没有例外通道：native / 导出文件一样要过闸门 ----------------

def test_手写native规则也要过闸门():
    """以前 native 条目是「自带可用声明」的例外通道（`ledger.plan` 直接写 `supported:"yes"`）。"""
    bad = _rule(search={"container": "//div[@id='x']/p"})
    got = formats.map_entry(bad)
    assert got["supported"] == "no"
    assert "xpath" in {u["construct"] for u in got["unsupported_fields"]}

    good = _rule()
    got = formats.map_entry(good)
    assert got["supported"] == "yes" and got["unsupported_fields"] == []
    assert got["converted_rule"] == good


def test_缺必填项的native规则给的是必填理由():
    got = formats.map_entry({"name": "缺东西"})
    assert got["supported"] == "no"
    assert any(u["construct"] == "required" for u in got["unsupported_fields"])
    assert all(u["why"] for u in got["unsupported_fields"])


def test_导出文件里的坏规则也被拦下(isolated):
    env = {"nf_export": 1, "exported_at": 1.0,
           "entries": [_rule(search={"container": "//x"}),
                       _rule(url="https://a.com/s?q={title},{'method':'PUT'}")]}
    res = intake.rows_from_payload(json.dumps(env, ensure_ascii=False), origin="导出")
    assert res["format"] == formats.FORMAT_EXPORT
    assert all(r["verdict"] == "unsupported" for r in res["rows"]), res["rows"]
    for r in res["rows"]:
        assert r["unsupported_fields"], r["name"]
