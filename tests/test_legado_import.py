"""第 86 期：Legado 书源解析 / 四档能力判定 / 转换 / 登录声明抽取（**全程零网络**）。

夹具 `tests/fixtures/legado_sample.json` 是从用户的两份真实书源里裁出来的代表性片段：

- `shuyuan.json`（多源合集）→ `示例HTML源`（HTML + CSS + 模板那一类的**最小化样本**）、
  `起点中文`（`loginUrl` 是网址 + `searchUrl`/`ruleToc.chapterUrl` 是含 `java.*` 的 JS）、
  `酷我小说`（JSON 接口 + `$.data` 路径 + `{{$.book_id}}` 跨条目拼 URL）、
  `番茄小说2`（`loginUi` 表单 + 密钥变量 + `loginUrl` 是 JS + 正文 `<js>` 含 `java.*`）；
- `1790850039.json`（单条巨型聚合源）→ `🍅大灰狼聚合5.9.30(vip完全版)`：**`bookSourceUrl`
  是「大灰狼融合VIP5.0」，不是网址**（真实文件即如此），整条不可用。

另加两条**我们自己造的**样本（不改真实文件的事实，只覆盖判定的边界）：
`可移植JS源`（正文是纯字符串/正则 JS ⇒ 应判 partial）与用于去重/哈希的构造。
裁剪范围：只保留与本期判定有关的字段，长 JS 只留关键片段。
"""
import json
import pathlib

import pytest

from novelforge.sources import legado, rules

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "legado_sample.json"


@pytest.fixture(scope="module")
def samples() -> list:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _by_name(samples: list, name: str) -> dict:
    for s in samples:
        if s.get("bookSourceName") == name:
            return s
    raise AssertionError(f"夹具里没有 {name}")


# ---------------- 格式嗅探与解析 ----------------

def test_嗅探三种输入(samples):
    assert legado.detect_format(samples) == "legado"
    assert legado.detect_format(json.dumps(samples)) == "legado"
    assert legado.detect_format('{"name": "x", "domains": ["a.com"]}') == "ours"
    assert legado.detect_format('{"bookSourceName": "x"}\n{"bookSourceName": "y"}') == "jsonl"
    assert legado.detect_format("这不是 JSON") == ""
    assert legado.detect_format("") == ""


def test_解析数组_单对象_JSONL(samples):
    assert len(legado.parse_sources(samples)) == len(samples)
    one = legado.parse_sources('{"bookSourceName": "单条", "bookSourceUrl": "https://a.com"}')
    assert len(one) == 1 and one[0]["bookSourceName"] == "单条"
    two = legado.parse_sources('{"bookSourceName": "甲"}\n{"bookSourceName": "乙"}')
    assert [e["bookSourceName"] for e in two] == ["甲", "乙"]


def test_坏输入给可读错误():
    with pytest.raises(ValueError, match="内容为空"):
        legado.parse_sources("   ")
    with pytest.raises(ValueError, match="第 2 行不是合法 JSON"):
        legado.parse_sources('{"bookSourceName": "甲"}\n{坏行')
    with pytest.raises(ValueError, match="没有解析出任何书源条目"):
        legado.parse_sources("[1, 2, 3]")


# ---------------- 四档判定 ----------------

def test_HTML源可转_且产物能过校验(samples):
    got = legado.analyze(_by_name(samples, "示例HTML源"))
    assert got["supported"] == "yes" and got["unsupported_fields"] == []
    assert got["source_type"] == "text" and got["source_type_label"] == "文本"

    r = got["converted_rule"]
    assert r["name"].startswith("lg-") and r["display_name"] == "示例HTML源"
    assert r["domains"] == ["www.example-novel.com"]
    # ⚠️ 最强的一条：转出来的东西必须真能当书源用（过 validate_rule）
    assert rules.validate_rule(r) == []
    assert r["search"]["url"] == "https://www.example-novel.com/search?q={title}&page={page}"
    assert r["search"]["container"] == ".book-item"
    assert r["search"]["fields"]["url"] == "a::attr(href)"
    assert r["search"]["fields"]["title"] == ".title a"
    # 目录容器要补上链接层，否则一条章节都取不到
    assert r["book"]["toc"]["container"] == "#chapter-list li a"
    # Legado 的 @html 要带上，不然正文被压成纯文本
    assert r["book"]["content"] == {"mode": "css", "container": "#content", "html": True}
    # header 是 Python repr 形式的字典（真实文件就这样），要能解析
    assert r["headers"]["User-Agent"].startswith("Mozilla/5.0")


def test_起点不可转_原因指到具体字段(samples):
    got = legado.analyze(_by_name(samples, "起点中文"))
    assert got["supported"] == "no"
    fields = {u["field"] for u in got["unsupported_fields"]}
    assert "searchUrl" in fields and "ruleToc.chapterUrl" in fields
    # 每条都要给替代做法，不能只报「不支持」
    assert all(u["why"] and u["instead"] for u in got["unsupported_fields"])
    assert any("java." in u["why"] for u in got["unsupported_fields"])


def test_酷我不可转_跨条目拼URL是原因(samples):
    got = legado.analyze(_by_name(samples, "酷我小说"))
    assert got["supported"] == "no"
    assert any("每条目录项" in u["why"] for u in got["unsupported_fields"])


def test_番茄不可转_但登录声明完整(samples):
    got = legado.analyze(_by_name(samples, "番茄小说2"))
    assert got["supported"] == "no"

    spec = legado.login_spec(_by_name(samples, "番茄小说2"))
    assert spec["needs_cookie"] is False          # enabledCookieJar: false
    key = next(v for v in spec["vars"] if v["label"] == "密钥")
    assert key["type"] == "text" and key["secret"] is True and key["required"] is True
    mode = next(v for v in spec["vars"] if v["type"] == "choice")
    assert [o["value"] for o in mode["options"]] == [0, 1, 2, 3, 4, 5, 6]
    assert [o["label"] for o in mode["options"]][0] == "取消听书"
    # 作者写的使用方法要原样带出来（不改写）
    assert spec["instructions"].startswith("// 首次使用时")
    # 跑不了的步骤要逐条说清「哪一项 / 为什么 / 替代做法」
    whats = " ".join(u["what"] for u in spec["unsupported"])
    assert "内置浏览器" in whats and "书源密钥" in whats
    assert all(u["instead"] for u in spec["unsupported"])


def test_聚合源不可转_直指bookSourceUrl不是网址(samples):
    ent = _by_name(samples, "🍅大灰狼聚合5.9.30(vip完全版)")
    got = legado.analyze(ent)
    assert got["supported"] == "no"
    assert any(u["field"] == "bookSourceUrl" and "不是 http" in u["why"]
               for u in got["unsupported_fields"])
    assert legado.dedup_key(ent) == ""            # 没有可用站点，也就没有去重键


def test_可移植JS判partial_并落到js通道(samples):
    got = legado.analyze(_by_name(samples, "可移植JS源"))
    assert got["supported"] == "partial", got
    assert any("JS" in n for n in got["notes"])
    r = got["converted_rule"]
    assert r["book"]["content"]["mode"] == "js"
    assert "result.replace" in r["book"]["content"]["script"]
    assert rules.validate_rule(r) == []


def test_起点登录声明_要Cookie并给出该打开的地址(samples):
    """起点是最顺的一类：`loginUrl` 就是网址 ⇒ 我们只需告诉用户「去这个地址过一次」。"""
    spec = legado.login_spec(_by_name(samples, "起点中文"))
    assert spec["needs_cookie"] is True
    assert spec["open_url"] == "https://www.qidian.com/all/"
    assert spec["vars"] == []
    assert spec["unsupported"] == [], "登录这一步本项目真能做到（开地址 + 粘 Cookie），不该报「做不到」"
    assert "Cookie" in spec["instructions"], "作者说明要带出来，用户才知道为什么要这么做"


def test_无需登录的源_登录声明为空(samples):
    spec = legado.login_spec(_by_name(samples, "示例HTML源"))
    assert spec["needs_cookie"] is True and spec["vars"] == [] and spec["unsupported"] == []
    assert spec["instructions"]                      # 夹具里写了说明；真实世界里可能为空


# ---------------- 去重键 / 哈希 / 类型 / JS 移植 ----------------

def test_去重键归一化():
    a = {"bookSourceUrl": "https://www.Qidian.com/"}
    b = {"bookSourceUrl": "http://qidian.com"}
    assert legado.dedup_key(a) == legado.dedup_key(b) == "qidian.com"
    assert legado.norm_site("HTTPS://WWW.Example.com/Path/") == "example.com/path"


def test_哈希与键序无关():
    a = {"bookSourceName": "甲", "bookSourceUrl": "https://a.com", "ruleContent": {"content": "x"}}
    b = {"ruleContent": {"content": "x"}, "bookSourceUrl": "https://a.com", "bookSourceName": "甲"}
    assert legado.rule_hash(a) == legado.rule_hash(b)
    assert legado.rule_hash(a) != legado.rule_hash({**a, "bookSourceName": "乙"})


def test_书源类型():
    assert legado.source_type({"bookSourceType": 0}) == "text"
    assert legado.source_type({"bookSourceType": 1}) == "audio"
    assert legado.source_type({"bookSourceType": 2}) == "image"
    assert legado.source_type({"bookSourceType": 99}) == "unknown"
    assert legado.source_type({}) == "text"


def test_JS可移植性判定():
    assert legado.js_port("<js>result.replace(/\\s+/g, ' ')</js>")["ok"] is True
    bad = legado.js_port("<js>java.ajax(book.bookUrl)</js>")
    assert bad["ok"] is False and bad["missing"] == ["java.ajax"]
    multi = legado.js_port("<js>java.put('a', 1); source.getVariable();</js>")
    assert multi["ok"] is False and set(multi["missing"]) == {"java.put", "source.getVariable"}
    assert legado.js_port("")["ok"] is False


def test_选择器转换_非零索引如实拒绝():
    assert legado._sel_to_css("class.book-item")["css"] == ".book-item"
    assert legado._sel_to_css("id.chapter-list.0@tag.li")["css"] == "#chapter-list li"
    assert legado._sel_to_css("a[data-bid]")["css"] == "a[data-bid]"
    bad = legado._sel_to_css("class.item.1@text")
    assert bad["index_ok"] is False and "非 0 索引" in bad["note"]
    assert legado._sel_to_css("$.data && $.list")["index_ok"] is False
