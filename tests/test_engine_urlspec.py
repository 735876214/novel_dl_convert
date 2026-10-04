"""第 94 期阶段 2b：**URL 请求选项**（`parse_url_spec`）—— 全程零网络。

## 这一版补的是什么能力

阅读把**请求选项**直接写在 URL 值后面，两代写法（都是实测出来的，不是想当然）：

- 3.x / 现代：`/search.php,{'method':'post','body':'searchkey={{key}}','charset':'gbk'}`
  —— 22 条真实样本里 6 条是这个形状（速读谷 / 就爱文学 / 武林中文网 / 69书吧 / 手机小说…）；
- 2.x / 竖线：`?searchkey={{key}}|char=gbk` —— 1537 条那份里 **775 条**，键只有 `char` 一个。

配这套写法要三件事**同时**做完，少一件都还是假可用：

1. **发请求**：`BrowserClient.get_text(method/body/headers)` 真的能 POST（以前只会 GET）；
2. **解码**：`charset` 真的按它解（走 `pipeline.decode_bytes` —— 与「上传文件」**同一份**判据，
   不在这里另写一份「先试 gbk 再试 utf-8」）；
3. **审计**：`_audit_url` 用**同一份解析结论**判「这条源能不能跑」，认不出的选项键如实拦下。

第 3 条是这一版最关键的地方：**执行**与**审计**读的是同一个 `parse_url_spec` —— 分成两处
就会出现最坏的一种组合：审计说能跑，跑起来却把整段 `,{'method':…}` 当地址发出去。
"""
import asyncio
import json
import pathlib

import pytest

from novelforge.sources import legado, rules

FIX_DIR = pathlib.Path(__file__).parent / "fixtures"
FIXTURE3 = FIX_DIR / "legado3_real.json"


# ---------------- 解析：两代写法、引号、大小写、坏输入 ----------------

@pytest.mark.parametrize("raw, url, opts", [
    # 3.x 的 `,{…}`（实测原文，单引号 Python repr 形式）
    ("/modules/article/search.php,{'charset':'gbk','body':'searchkey={title}&searchtype=all','method':'POST'}",
     "/modules/article/search.php",
     {"charset": "gbk", "body": "searchkey={title}&searchtype=all", "method": "post"}),
    # 双引号 JSON 形式（实测同一份文件里两种混着用）
    ('https://a.com/s,{"method":"post"}', "https://a.com/s", {"method": "post"}),
    # 逗号后的空格（实测有）
    ("https://a.com/s, {'method': 'POST','body': 'keyword={title}'}",
     "https://a.com/s", {"method": "post", "body": "keyword={title}"}),
    # 2.x 竖线：在末尾
    ("https://a.com/s?q={title}|char=gbk", "https://a.com/s?q={title}", {"charset": "gbk"}),
    # 2.x 竖线：在**中间**（实测 7 条这样写：选项后面还接着 `&参数`，那个 `&` 属于地址）
    ("http://m.shumil.com/search.php?searchkey={title}|char=gbk&page={page}",
     "http://m.shumil.com/search.php?searchkey={title}&page={page}", {"charset": "gbk"}),
    # 两种写法可以同时出现
    ("https://a.com/s?q={title}|char=gbk&x=2,{'method':'post'}",
     "https://a.com/s?q={title}&x=2", {"charset": "gbk", "method": "post"}),
    # 没有选项：一个字符都不许动（老规则的 URL 里可能有 `|` / `&` / 大括号）
    ("https://a.com/s?q={title}&x=1", "https://a.com/s?q={title}&x=1", {}),
    ("https://a.com/s?q={title}", "https://a.com/s?q={title}", {}),
])
def test_选项解析_认的写法都要解对(raw, url, opts):
    got = rules.parse_url_spec(raw)
    assert got.url == url
    assert got.opts == opts
    assert got.unknown == []


def test_取地址的字符不许被误摘():
    """地址里本来就有 `|`、`}`、`{}` 时**不许**当成选项 —— 误摘的后果是请求打到别处。"""
    for raw in ("https://a.com/s?q=a|b",
                "https://a.com/s?q={title}&tpl={a}",
                "https://a.com/s?q={title},x"):
        got = rules.parse_url_spec(raw)
        assert got.url == raw, raw
        assert got.opts == {} and got.unknown == []


@pytest.mark.parametrize("raw, key", [
    ("https://a.com/s,{'method':'PUT'}", "method=PUT"),          # 认不出的方法
    ("https://a.com/s,{'webView':True}", "webView"),             # 认不出的选项键
    ("https://a.com/s?q={title}|method=post", "method"),         # 竖线写法只认编码
    ("https://a.com/s,{'method':'post','headers':'不是字典'}", "headers"),
])
def test_认不出的选项如实报出来_不静默忽略(raw, key):
    got = rules.parse_url_spec(raw)
    assert key in got.unknown, got.unknown
    assert "method" not in got.opts or key == "headers"


def test_选项字典读不出来时不留半截():
    """JS 写法的 `true` / 拼错的引号 ⇒ 整段读不出 ⇒ **地址也不许被截断**。

    截断的后果比「不认识」严重得多：地址看着正常，请求打到一个不存在的路径上，
    现象只是「搜不到」——完全看不出是选项那一段的问题。
    """
    raw = "https://a.com/s,{'method':'get','webView':true}"
    got = rules.parse_url_spec(raw)
    assert got.url == raw and got.opts == {}
    assert rules._OPTS_UNPARSED in got.unknown


def test_方法的空值不当成选项():
    assert rules.parse_url_spec("https://a.com/s,{'method':''}").unknown == ["method="]


def test_字面量字典解析只有一处():
    """`header` 字段与 URL 选项字典**共用** `parse_dict_literal`（各写一份的下场：
    一处只认单引号、另一处只认双引号，而两边都不报错，字段静默为空）。"""
    for text in ("{'a': '1'}", '{"a": "1"}'):
        assert rules.parse_dict_literal(text) == {"a": "1"}, text
    assert rules.parse_dict_literal("不是字典") is None
    assert rules.parse_dict_literal("['列表']") is None
    assert rules.parse_dict_literal(None) is None
    # 真实书源的 header 是 Python repr 形式（见夹具）
    ent = json.loads(FIXTURE3.read_text(encoding="utf-8"))[0]
    assert "User-Agent" in legado._headers({**ent, "header": "{'User-Agent': 'UA'}"})


# ---------------- 执行：选项真的落到请求上 ----------------

class _OptClient:
    """记下**每一次请求的完整参数**的桩 client（本文件零网络）。"""

    html = '<a href="/b/1">三体</a>'

    def __init__(self):
        self.calls: list = []

    async def get_text(self, url: str, **kw) -> str:
        self.calls.append((url, kw))
        return self.html


def _src(url_tpl: str) -> type:
    return rules.make_rule_class({
        "name": "opt-src", "display_name": "选项源", "domains": ["e.com"], "public": True,
        "search": {"url": url_tpl, "mode": "regex",
                   "pattern": '<a href="(?P<url>[^"]+)">(?P<title>[^<]+)</a>'},
        "book": {"mode": "single", "content": {"mode": "css", "container": "#c", "text": True}},
        "chapter": {"mode": "auto"},
    })


def test_不带选项的规则_请求参数一个都不多传():
    """**兼容红线**：老规则走的是 `get_text(url)` 那条路，多传一个 kwarg 就有桩客户端会炸
    （真实世界里也有只实现 `get_text(url)` 的适配器）。"""
    client = _OptClient()
    asyncio.run(_src("https://e.com/s?q={title}")().search(client, "三体"))
    assert client.calls == [("https://e.com/s?q=%E4%B8%89%E4%BD%93", {})]


def test_POST选项真的落到请求上():
    client = _OptClient()
    src = _src("https://e.com/s.php,{'method':'post','body':'searchkey={title}&type=all',"
               "'charset':'gbk','headers':{'Referer':'https://e.com/'}}")()
    asyncio.run(src.search(client, "三体"))
    url, kw = client.calls[0]
    # 地址里**不许**残留选项那一段（残留的后果：请求打到一个带 `,{...}` 的路径上）
    assert url == "https://e.com/s.php"
    assert kw["method"] == "POST"
    assert kw["body"] == "searchkey=%E4%B8%89%E4%BD%93&type=all", "body 里的 {title} 也要替换"
    assert kw["charset"] == "gbk"
    assert kw["headers"] == {"Referer": "https://e.com/"}


def test_竖线编码选项也落到请求上():
    client = _OptClient()
    asyncio.run(_src("https://e.com/s?q={title}|char=gbk&p=1")().search(client, "三体"))
    url, kw = client.calls[0]
    assert url == "https://e.com/s?q=%E4%B8%89%E4%BD%93&p=1"
    assert kw == {"charset": "gbk"}


def test_请求基准地址不含选项段():
    """`_parse_search` 拿请求地址当相对链接的基准 ⇒ 基准得是**摘掉选项**的地址。

    基准里带 `,{'method':…}` 时，`urljoin` 补出来的每条结果链接都拖着一截废串，
    而现象只是「详情页打不开」——离真正的原因很远。
    """
    html = '<div class="i"><a href="/b/1">三体</a></div>'
    sp = {"mode": "css", "container": ".i", "fields": {"url": "a::attr(href)"}}
    assert rules._parse_search(html, sp, "https://e.com/s.php")[0]["url"] == "https://e.com/b/1"


# ---------------- 与转换器接上：真夹具里的选项要**原样**带过去 ----------------

def test_转换产物原样带着选项_且引擎认它():
    """转换器**不翻译也不丢**选项：它只补绝对地址，选项由引擎解析（`parse_url_spec`）。

    在这里翻译（把 `charset` 落到别的字段上）就等于转换器自己声明了一遍「哪些选项能跑」——
    而那正是本项目最深的那个病（转换器既当运动员又当裁判）。
    """
    entries = json.loads(FIXTURE3.read_text(encoding="utf-8"))
    ent = next(e for e in entries if e.get("bookSourceName") == "速读谷")
    got = legado.analyze(ent)
    url = got["converted_rule"]["search"]["url"]
    assert url.startswith("https://") and "," in url, url
    spec = rules.parse_url_spec(url)
    assert spec.opts["method"] == "post" and "{title}" in spec.opts["body"]
    assert spec.unknown == []
    assert rules.audit_native_rule(got["converted_rule"]) == []


def test_2x真源里的竖线编码_转换后仍然生效():
    """2.x 那份 1537 条里 **775 条**靠 `|char=gbk` —— 转换丢了它 = 整页乱码（搜不到）。

    夹具里没有带竖线选项的条目（`legado2_real.json` 是从真文件里裁的代表性片段），
    所以这里在**真实 2.x 条目**上补一个 `|char=gbk`（形状与真文件逐字一致，
    见 `.codebuddy/memory` 里 202003.txt 的实测：`…searchkey=searchKey|char=gbk`）。
    """
    entries = json.loads((FIX_DIR / "legado2_real.json").read_text(encoding="utf-8"))
    ent = next(e for e in entries if str(e.get("ruleSearchUrl") or "").startswith("http"))
    ent = {**ent, "ruleSearchUrl": str(ent["ruleSearchUrl"]) + "|char=gbk"}
    got = legado.analyze(ent)
    assert got["supported"] != "no", got["unsupported_fields"]
    spec = rules.parse_url_spec(got["converted_rule"]["search"]["url"])
    assert spec.opts.get("charset") == "gbk", "编码选项在转换中丢了"
    assert rules.url_kwargs(spec) == {"charset": "gbk"}
    assert rules.audit_native_rule(got["converted_rule"]) == []


# ---------------- 解码：一份判据，两个入口 ----------------

def test_按规则给的编码解码():
    from novelforge.core import pipeline
    data = "第 1 章 三体".encode("gbk")
    text, info = pipeline.decode_bytes(data, encoding="gbk")
    assert text == "第 1 章 三体" and info["encoding"] == "gbk"
    # 编码名不认（阅读的 `char=escape` 那种）⇒ **落回自动探测并如实说明**，不抛异常
    text2, info2 = pipeline.decode_bytes(data, encoding="escape")
    assert info2.get("fallback") is True and info2.get("requested") == "escape"
    assert text2


def test_decode_bytes与decode_file是同一份判据(tmp_path):
    """同一份内容走**文件入口**与**内存入口**必须解出同一个结果（否则抓取与上传会打架）。"""
    from novelforge.core import pipeline
    for text, enc in (("第 1 章 中文标题", "gbk"), ("chapter one", "utf-8"),
                      ("繁體中文測試", "big5")):
        p = tmp_path / f"{enc}.txt"
        p.write_bytes(text.encode(enc, errors="replace"))
        from_file, info_f = pipeline.decode_file(p)
        from_bytes, info_b = pipeline.decode_bytes(p.read_bytes())
        assert from_file == from_bytes
        assert info_f["encoding"] == info_b["encoding"]
