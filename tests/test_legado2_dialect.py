"""第 94 期：阅读 **2.x 旧方言**（`ruleSearchUrl` / `ruleBookContent` 那一代）的归一。

夹具 `tests/fixtures/legado2_real.json` 是从真实样本 `202003.txt`（用户给的
`cdn.jsdelivr.net/gh/yeyulingfeng01/yuedu.github.io@1.1/202003.txt`，3,345,858 字节、
**1537 条**书源）里裁出来的 9 条 —— 名字、键名、取值**一字未改**，只在条数上做了裁剪。

## 这一版修的是什么

第 94 期之前这 1537 条是**全灭**：`legado.analyze` 只认 3.x 键名，一个键都读不到，
于是每条都被判「可判定的字段不足以拼出本项目规则」—— 而用户看到的是「源不能用」，
看不出「其实是方言不认识」。现在 2.x 的键名、以及**裸词搜索占位符**，都在
:func:`legado.normalize_legacy` 这一处归一到 3.x，然后走同一条转换路（**没有第二套 convert**）。

阶段 2c 又补了两处 2.x 独有写法（**由实测驱动，不是猜的**）：单个 `#` 也是替换分隔符
（`斗书阁` / `小说旗` 那两条），以及 `@children` 步的渲染往返（`看看书™九天之狼`）。
这三条就是新加进夹具的回归钉子。
"""
import json
import pathlib

import pytest

from novelforge.sources import formats, intake, legado, rules, selspec

FIX_DIR = pathlib.Path(__file__).parent / "fixtures"
FIXTURE2 = FIX_DIR / "legado2_real.json"
FIXTURE3 = FIX_DIR / "legado3_real.json"


@pytest.fixture(scope="module")
def entries2() -> list:
    return json.loads(FIXTURE2.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def entries3() -> list:
    return json.loads(FIXTURE3.read_text(encoding="utf-8"))


def _by_name(entries: list, name: str) -> dict:
    for e in entries:
        if e.get("bookSourceName") == name:
            return e
    raise AssertionError(f"夹具里没有 {name}")


# ---------------- 方言判定 ----------------

def test_整份夹具都是2x(entries2):
    assert all(legado.dialect(e) == "legado-2" for e in entries2)
    assert all(legado.legacy_keys(e) for e in entries2)


def test_3x的源一条旧键都认不出来(entries3):
    assert all(legado.legacy_keys(e) == [] for e in entries3), \
        "3.x 的源里出现 2.x 键名 ⇒ 别名表收宽了（会把 3.x 源误判成 2.x）"


def test_方言跟到接口(entries2, entries3):
    assert intake.detect(json.dumps(entries2, ensure_ascii=False)) == formats.FORMAT_LEGADO2
    assert intake.detect(json.dumps(entries3, ensure_ascii=False)) == formats.FORMAT_LEGADO3


def test_别名表只收实测出现过的键():
    """别名表收宽了会让 2.x 判定误伤 —— 每个键都要在真实样本里出现过。

    本文件不联网，所以只钉「表里的键都指向 3.x 的真实键名」这一半（另一半由
    `legado2_real.json` 与 `test_整份夹具都是2x` 反向钉住：表里没写的旧键不会被当成 2.x）。
    """
    from novelforge.sources.model import LEGACY_ALIASES
    known3 = {"searchUrl", "ruleSearch", "ruleToc", "ruleContent", "ruleBookInfo", "enabled",
              "header", "bookSourceUrl", "bookSourceName", "bookSourceType", "bookSourceGroup"}
    for old, path in LEGACY_ALIASES.items():
        assert old != path
        assert path.split(".")[0] in known3 or path == "enabled", f"{old} → {path} 不是 3.x 键名"


# ---------------- normalize_legacy：纯函数、幂等、只动该动的 ----------------

def test_归一不改入参_且幂等(entries2):
    for e in entries2:
        before = json.dumps(e, sort_keys=True, ensure_ascii=False)
        once = legado.normalize_legacy(e)
        assert json.dumps(e, sort_keys=True, ensure_ascii=False) == before, "归一改了入参"
        assert legado.normalize_legacy(once) == once, "归一不幂等"
        assert legado.dialect(once) == "legado-3", "归一之后不该再有旧键名"


def test_键名搬到3x的位置(entries2):
    got = legado.normalize_legacy(_by_name(entries2, "看大书网"))
    # 原条目里是 `plus/search.php?q=searchKey&…`（相对地址，真实文件就这样）
    assert got["searchUrl"] == "plus/search.php?q={{key}}&searchtype=articlename"
    assert got["ruleSearch"]["bookList"] == "id.nr"
    assert got["ruleSearch"]["name"] == "tag.a.0@text"
    assert got["ruleSearch"]["bookUrl"] == "tag.a.0@href"
    assert got["ruleToc"]["chapterList"] == "id.list@dl@dd"
    assert got["ruleToc"]["chapterUrl"] == "a@href"
    assert got["ruleContent"]["content"] == "id.content@textNodes"
    assert got["ruleBookInfo"]["intro"] == "id.intro@text"
    assert got["ruleBookInfo"]["coverUrl"] == "id.fmimg@a@img@src"
    assert got["enabled"] is True and "enable" not in got


def test_3x没有的键原样留着(entries2):
    """`raw_json` 要能无损往返 —— 归一**只搬**认识的键，不认识的键一个都不许丢。"""
    ent = _by_name(entries2, "看大书网")
    got = legado.normalize_legacy(ent)
    for k in ("serialNumber", "weight", "bookSourceGroup", "bookSourceType", "lastUpdateTime"):
        if k in ent:
            assert got.get(k) == ent[k]
    assert len(got) >= len(ent) - len(legado.legacy_keys(ent))


def test_已有3x键时不被旧键覆盖():
    ent = {"bookSourceName": "混血", "ruleSearchList": "旧",
           "ruleSearch": {"bookList": "新"}, "searchUrl": "先", "ruleSearchUrl": "后"}
    got = legado.normalize_legacy(ent)
    assert got["ruleSearch"]["bookList"] == "新"
    assert got["searchUrl"] == "先"


def test_裸词占位符归一到模板(entries2):
    """实测 1537 条里 1412 条写 `=searchKey`、389 条写 `=searchPage` —— 3.x 才写 `{{key}}`。

    不归一的话地址里会原样留下 `searchKey`：**搜什么都搜同一个词，且一个错都不报**。
    """
    for e in entries2:
        got = legado.normalize_legacy(e)["searchUrl"]
        assert "searchKey" not in got and "searchPage" not in got, got
    got = legado.normalize_legacy({"bookSourceName": "甲", "ruleSearchList": "a",
                                   "ruleSearchUrl": "https://x/s?kw=searchKey&page=searchPage"})
    # 归一到 `{{key}}`，再由 `_tpl` 换成本项目模板（同一份 `_tpl`，没有第二个渲染器）
    assert got["searchUrl"] == "https://x/s?kw={{key}}&page={{page}}"


def test_小写searchkey是参数名_不许被换掉():
    """样本里小写 `searchkey=` 是**参数名**（479 条），驼峰 `searchKey` 才是值。

    用 re.I 做替换会把参数名一起换掉（`?{{key}}=searchKey`）—— 这个用例就是钉这个。
    """
    got = legado.normalize_legacy({"bookSourceName": "甲", "ruleSearchList": "a",
                                   "ruleSearchUrl": "https://x/s?searchkey=searchKey"})
    assert got["searchUrl"] == "https://x/s?searchkey={{key}}"


def test_2x的UA变成请求头(entries2):
    """2.x 的 `httpUserAgent` 是**一个字符串**，3.x 的 `header` 是字典（实测 166 条带 UA）。"""
    ent = _by_name(entries2, "QQ音乐")
    assert ent["httpUserAgent"].startswith("Mozilla/5.0")
    got = legado.normalize_legacy(ent)
    assert got["header"]["User-Agent"] == ent["httpUserAgent"]
    # 转出来的规则要真的带上这个头（不是归一完就丢了）
    assert formats.map_entry(ent)["converted_rule"]["headers"]["User-Agent"] == ent["httpUserAgent"]
    # 有显式 header 时以它为准（不合并、不猜）：UA 不许被塞进去
    explicit = {"X-A": "1"}
    assert legado.normalize_legacy({**ent, "header": dict(explicit)})["header"] == explicit


def test_空的UA不产生空请求头(entries2):
    """实测里 `httpUserAgent` 大量是空串 —— 空串不许变成一个空的 User-Agent。"""
    ent = _by_name(entries2, "[MUSIC]A8音乐™")
    assert not str(ent.get("httpUserAgent") or "").strip()
    assert "header" not in legado.normalize_legacy(ent)


# ---------------- bookSourceType：2.x 写字符串 ----------------

def test_书源类型_字符串与整数都认():
    assert legado.source_type({"bookSourceType": ""}) == "text"        # 实测：2.x 大量是空串
    assert legado.source_type({"bookSourceType": "TEXT"}) == "text"
    assert legado.source_type({"bookSourceType": "AUDIO"}) == "audio"
    assert legado.source_type({"bookSourceType": "漫画"}) == "image"
    assert legado.source_type({"bookSourceType": 0}) == "text"
    assert legado.source_type({"bookSourceType": 1}) == "audio"
    assert legado.source_type({"bookSourceType": 2}) == "image"
    assert legado.source_type({"bookSourceType": 99}) == "unknown"
    assert legado.source_type({}) == "text"
    # 2.x 夹具里 `bookSourceType: ""` 的那几条要判成文本，不是 unknown
    assert legado.source_type(_by_name(json.loads(FIXTURE2.read_text(encoding="utf-8")),
                                      "看大书网")) == "text"


# ---------------- 整条链：2.x 现在真能转出规则 ----------------

def test_2x的源现在转得出规则(entries2):
    """**这就是本期修的东西**：同一个源，以前一个键都读不到 ⇒ 判 no。

    现在它要转出一条**过得了引擎校验**的规则，地址里的占位符换成本项目的模板。
    """
    got = formats.map_entry(_by_name(entries2, "看大书网"))
    assert got["supported"] == "yes", got["unsupported_fields"]
    rule = got["converted_rule"]
    assert rule["name"] == "lg-kandshu.com" and rule["domains"] == ["www.kandshu.com"]
    assert rules.validate_rule(rule) == []
    assert rule["search"]["url"] == "http://www.kandshu.com/plus/search.php?q={title}&searchtype=articlename"
    assert "{title}" in rule["search"]["url"] and "searchKey" not in rule["search"]["url"]
    assert rule["search"]["container"] == "#nr"
    assert rule["search"]["fields"]["url"] == "a::attr(href)"
    assert rule["book"]["toc"]["container"] == "#list dl dd a"
    assert rule["book"]["content"]["mode"] == "css"


def test_2x条目判no时也给逐条理由(entries2):
    """整份夹具里**每一条**都要说清为什么（判 `no` 的必须有逐条理由，不许只丢一句「不可用」）。"""
    for e in entries2:
        got = formats.map_entry(e)
        assert got["supported"] in ("yes", "partial", "no")
        if got["supported"] != "no":
            assert rules.audit_native_rule(got["converted_rule"]) == []
        else:
            assert got["unsupported_fields"]
            assert all(u["why"] and u["instead"] for u in got["unsupported_fields"])


def test_2x整份导入不再全灭(entries2):
    """本期验收的**下限**：一份真实 2.x 文件不许再 0 条可用。"""
    got = [formats.map_entry(e) for e in entries2]
    usable = [g for g in got if g["supported"] != "no"]
    assert usable, "2.x 的源一条都没转出来 ⇒ 方言归一回退了"
    assert any(g["supported"] == "yes" for g in got)


def test_整份走一遍导入路由(entries2, isolated):
    """端到端（**零网络、零落盘**）：`intake.rows_from_payload` 出差异表行。"""
    res = intake.rows_from_payload(json.dumps(entries2, ensure_ascii=False), origin="测试")
    assert res["format"] == formats.FORMAT_LEGADO2
    assert len(res["rows"]) == len(entries2)
    by_name = {r["name"]: r for r in res["rows"]}
    row = by_name["lg-kandshu.com"]
    assert row["supported"] == "yes" and row["verdict"] in ("new", "conflict", "duplicate")
    assert row["converted_rule"]["search"]["url"].startswith(
        "http://www.kandshu.com/plus/search.php")
    for r in res["rows"]:
        if r["verdict"] == "unsupported":
            assert r["unsupported_fields"], f"{r['name']} 判不可用却没给理由"


# ---------------- 阶段 2c：单个 `#` 替换 / `@children`（都是实测真源写法） ----------------

def test_单井号替换照旧当替换(entries2):
    r"""2.x 里**单个** `#` 也是替换分隔符 —— 从前被当成「把 `##` 写错了」整条判死。

    实测（`202003.txt`）单 `#` 出现在 1745 个取值里，其中 **206 条**整条只卡这一处。
    证据是成对出现的：`.mlist@html##^\s*##<br>` 与 `.brief_text@html#^#<br>` 并存。
    """
    rule = formats.map_entry(_by_name(entries2, "小说旗"))["converted_rule"]
    # ⚠️ 归一成项目自己的两个 `#`（引擎只认一份实现），语义不变
    assert rule["book"]["content"]["container"] == \
        "#content##一秒记住【小说旗 www.xs7.la】，热门小说免费阅读！"
    assert rule["search"]["fields"]["author"] == "span##作者："
    # 容器与字段都要**真的能跑**（不是只过闸门）
    soup = rules._soup("<div id='content'>一秒记住【小说旗 www.xs7.la】，"
                       "热门小说免费阅读！正文开始</div>")
    assert rules._field_value(soup, rule["book"]["content"]["container"]) == "正文开始"


def test_单井号在容器上也是替换(entries2):
    """`斗书阁` 的正文容器 `id.content@html#…` —— 单 `#` 在**容器**位置同样当替换。"""
    got = formats.map_entry(_by_name(entries2, "斗书阁"))
    assert got["supported"] == "yes", got["unsupported_fields"]
    rule = got["converted_rule"]
    assert rule["book"]["content"]["container"].startswith("#content@html##")
    assert "@@" not in json.dumps(got, ensure_ascii=False)


def test_children步不再渲染成两个井号(entries2):
    """`class.chaptercontent@children` 曾渲染成 `.chaptercontent@@children` ⇒ 解析报「空的 `@` 段」。

    （实测原始语料里 `@@` 出现 **0 次** —— 那些 `@@children` 全是本项目自己的渲染 bug。）
    """
    got = formats.map_entry(_by_name(entries2, "看看书™九天之狼"))
    assert got["supported"] == "yes", got["unsupported_fields"]
    container = got["converted_rule"]["book"]["content"]["container"]
    assert container == ".chaptercontent@children", container
    assert not selspec.spec_error(selspec.parse_spec(container))
    assert "@@" not in json.dumps(got, ensure_ascii=False)
