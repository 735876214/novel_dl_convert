"""第 94 期：**格式轴**（`novelforge/sources/formats/`）的契约 —— 全程零网络。

格式轴与执行轴（`sources/base.py` 的 `SourceAdapter` + `REGISTRY`）是**两条正交的轴**：
执行轴回答「一条 native 规则怎么跑」，格式轴回答「一段输入是什么格式、怎么读成条目」。
本文件钉的就是后半句：嗅探分数、解析、条目级分派、序列化，以及**每个适配器的产物
必须过引擎自己的校验与诚实闸**（不许由适配器自称可用）。
"""
import json
import pathlib

import pytest

from novelforge.sources import formats, intake, legado, rules

FIX_DIR = pathlib.Path(__file__).parent / "fixtures"
LEGADO3 = FIX_DIR / "legado3_real.json"          # XIU2 合集里裁的 8 条现代 3.x 源
LEGADO2 = FIX_DIR / "legado2_real.json"          # 202003.txt 里裁的 5 条 2.x 旧方言源
LEGADO_SAMPLE = FIX_DIR / "legado_sample.json"   # 第 86 期就在的事实夹具

#: 格式轴**必须**有的 5 个适配器（本期口径：没样本的格式不做，也不留空壳）
EXPECTED_IDS = ("nf-native", "nf-export", "legado-3", "legado-2", "legado-jsonl")


@pytest.fixture(scope="module")
def legado3() -> list:
    return json.loads(LEGADO3.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def legado2() -> list:
    return json.loads(LEGADO2.read_text(encoding="utf-8"))


# ---------------- 注册表 ----------------

def test_注册表就是这五个():
    ids = [a.format_id for a in formats.FORMATS]
    assert set(ids) == set(EXPECTED_IDS), "格式标识的声明只在 formats/base.py 一处，别处不许再记一份"
    assert len(set(ids)) == len(ids), "同一个格式不许注册两次"
    for a in formats.FORMATS:
        assert a.display_name, f"{a.format_id} 没有展示名 —— 界面上「无法识别格式：…」要靠它列出来"


def test_注册即刻生效_且能按标识取到同一个():
    for a in formats.FORMATS:
        assert formats.adapter_for(a.format_id) is a
    assert formats.adapter_for("不存在的格式") is None


def test_装饰器注册类_表里放的是实例():
    """`@register_format` 用在类上时必须**返回类本身**（否则装饰器把类名变成实例）。

    表里放的又必须是**实例** —— 放类的话 `sniff_format` 内部调用 `a.sniff(payload)`
    会缺 self 抛 TypeError，而 `sniff_format` 的兜底 `except` 会把它吞成「0 分」⇒
    表现为「一份好文件被判成无法识别格式」，最难查的一类静默失败。
    """
    class _Probe(formats.FormatAdapter):
        format_id = "_probe-test"
        display_name = "测试用"

        def map(self, entry) -> dict:
            return {"supported": "no", "unsupported_fields": [], "converted_rule": None,
                    "notes": [], "source_type": "text"}

    got = formats.register_format(_Probe)
    try:
        assert got is _Probe, "装饰器要返回原对象，否则 `class X` 的名字会被换掉"
        assert isinstance(formats.FORMATS[-1], formats.FormatAdapter)
        assert formats.FORMATS[-1].format_id == "_probe-test"
    finally:
        formats.FORMATS.pop()


# ---------------- 嗅探 ----------------

def test_三种真实输入各归各家(legado3, legado2):
    assert intake.detect(json.dumps(legado3, ensure_ascii=False)) == formats.FORMAT_LEGADO3
    assert intake.detect(json.dumps(legado2, ensure_ascii=False)) == formats.FORMAT_LEGADO2
    assert intake.detect(LEGADO_SAMPLE.read_text(encoding="utf-8")) == formats.FORMAT_LEGADO3


def test_导出信封被信封适配器认领():
    env = {"nf_export": 1, "exported_at": 1.0,
           "entries": [{"name": "手写源", "domains": ["a.com"],
                        "search": {"url": "https://a.com/s?q={title}", "container": ".x",
                                   "fields": {"title": ".t", "url": "a::attr(href)"}},
                        "book": {"mode": "single", "content": {"mode": "css", "container": ".c",
                                                               "text": True}}}]}
    adapter, score = formats.sniff_format(json.dumps(env, ensure_ascii=False))
    assert adapter.format_id == formats.FORMAT_EXPORT
    # 信封必须**赢过**所有按条目认的适配器（0.8 / 0.9），否则信封会被当成一份普通 JSON 数组
    assert score > max(a.sniff(json.dumps(env)) for a in formats.FORMATS
                       if a.format_id != formats.FORMAT_EXPORT)
    assert [e["name"] for e in adapter.parse(json.dumps(env))] == ["手写源"]


def test_JSONL_与单行JSON不打架():
    text = '{"bookSourceName": "甲"}\n{"bookSourceName": "乙"}'
    assert intake.detect(text) == formats.FORMAT_JSONL
    # ⚠️ 一行 JSON 不是 JSONL：它应该由按条目认的适配器接管（JSONL 的分数更低）
    one = '{"name": "x", "domains": ["a.com"]}'
    assert intake.detect(one) == formats.FORMAT_NATIVE
    assert intake.detect('{"bookSourceName": "x", "bookSourceUrl": "https://a.com"}') \
        == formats.FORMAT_LEGADO3


def test_认不出回零分_绝不抛异常():
    for bad in ("这不是 JSON", "", "   ", "[]", "null", None, 12345, {"随便": 1}):
        assert intake.detect(bad) == ""

    class _Boom(formats.FormatAdapter):
        format_id = "_boom-test"
        display_name = "会炸的"

        def sniff(self, payload) -> float:
            raise RuntimeError("适配器自己炸了")

    class _BoomDuck:                                  # 连 FormatAdapter 都不是
        format_id = "_boom-duck"
        display_name = "鸭子"
        sniff = _Boom.sniff

    formats.register_format(_BoomDuck())
    try:
        # 一个坏适配器不许把整条导入链带崩（分数按 0 处理，其余适配器照常打分）
        assert formats.sniff_format('{"name": "x", "domains": ["a.com"]}')[0].format_id \
            == formats.FORMAT_NATIVE
    finally:
        formats.FORMATS.pop()


def test_方言分数_2x赢过3x_3x对2x让位(legado2, legado3):
    """2.x 与 3.x 都是 Legado JSON（3.x 的特征 2.x 也有一半），差别只在「有没有旧键名」。

    用**分数**表达「2.x 更具体」，不在调用方写 if：整份都是旧键名时 3.x 直接让位（0 分），
    2.x 拿 0.9；反过来 3.x 的源里一个旧键名都没有，2.x 也就不会来抢。
    """
    two = json.dumps(legado2, ensure_ascii=False)
    assert formats.adapter_for(formats.FORMAT_LEGADO2).sniff(two) == 0.9
    assert formats.adapter_for(formats.FORMAT_LEGADO3).sniff(two) == 0.0, "2.x 的源要让 3.x 主动让位"

    three = json.dumps(legado3, ensure_ascii=False)
    assert formats.adapter_for(formats.FORMAT_LEGADO3).sniff(three) == 0.8
    assert formats.adapter_for(formats.FORMAT_LEGADO2).sniff(three) == 0.0


# ---------------- 解析 ----------------

def test_解析_三种输入都出同构条目(legado3, legado2):
    for text, fid in ((json.dumps(legado3, ensure_ascii=False), formats.FORMAT_LEGADO3),
                      (json.dumps(legado2, ensure_ascii=False), formats.FORMAT_LEGADO2),
                      (LEGADO_SAMPLE.read_text(encoding="utf-8"), formats.FORMAT_LEGADO3)):
        entries = formats.adapter_for(fid).parse(text)
        assert entries and all(isinstance(e, dict) and e for e in entries)
        assert all("bookSourceName" in e or "bookSourceUrl" in e for e in entries)


def test_坏输入仍是人话(legado2):
    """解析的坏输入措辞只有一份（`legado.parse_sources`），适配器**包装**它而不是自己写一份。"""
    with pytest.raises(ValueError, match="没有解析出任何书源条目"):
        formats.adapter_for(formats.FORMAT_NATIVE).parse("[1, 2, 3]")
    with pytest.raises(ValueError, match="内容为空"):
        formats.adapter_for(formats.FORMAT_LEGADO3).parse("   ")


# ---------------- 条目级分派（唯一一处） ----------------

def test_逐条分派只看条目自己(legado3, legado2):
    an = formats.map_entry(legado3[0])
    assert set(an) >= {"supported", "unsupported_fields", "converted_rule", "notes", "source_type"}
    assert formats.map_entry(legado2[0])["supported"] in ("yes", "partial", "no")
    native = {"name": "手写", "domains": ["a.com"], "search": {"url": "https://a.com/s?q={title}"},
              "book": {"mode": "single"}}
    assert formats.map_entry(native)["converted_rule"]["name"] == "手写"


def test_分派产物形状对任何格式都一样(legado3, legado2):
    """`ledger.plan` 只认这一套键 —— 任何一个适配器漏一个键，差异表里就会凭空少一列。"""
    entries = list(legado3) + list(legado2) + [{"name": "x", "domains": ["a.com"],
                                                "search": {}, "book": {}}]
    for ent in entries:
        an = formats.map_entry(ent)
        assert an["supported"] in ("yes", "partial", "no")
        assert isinstance(an["unsupported_fields"], list) and isinstance(an["notes"], list)
        assert isinstance(an["source_type"], str)
        # 判「不能跑」就必须**给出理由**（界面上不许出现「不能用但不告诉我为什么」）
        if an["supported"] == "no":
            assert an["unsupported_fields"], ent.get("bookSourceName") or ent.get("name")


# ---------------- 序列化 ----------------

def test_序列化_native是恒等():
    src = {"name": "手写", "domains": ["a.com"], "search": {"url": "https://a.com"}, "book": {}}
    assert formats.serialize_native(src) == src
    assert formats.serialize_native(src) is not src, "不许把内部字典的引用交出去"


def test_格式展示名():
    assert all(formats.format_label(a.format_id) == a.display_name for a in formats.FORMATS)
    assert formats.format_label("不存在") == "不存在"


# ---------------- 与引擎的耦合：产物必须过引擎自己的关 ----------------

def test_每个适配器的产物都过引擎校验与诚实闸(legado3, legado2):
    """**红线**：格式轴只负责读，能不能跑由引擎说了算（`validate_rule` + `audit_native_rule`）。

    判 `yes` / `partial` 的产物必须：① 过 `validate_rule`；② 过诚实闸（空列表）。
    判 `no` 的产物要么是 None，要么也带着理由 —— 不许出现「说能用、其实跑不动」。
    """
    checked = 0
    for ent in list(legado3) + list(legado2):
        an = formats.map_entry(ent)
        rule = an["converted_rule"]
        if an["supported"] == "no":
            continue
        assert rule is not None, f"{ent.get('bookSourceName')} 判可用却没有产物"
        assert rules.validate_rule(rule) == [], f"{ent.get('bookSourceName')} 产物过不了 validate_rule"
        if an["supported"] == "yes":
            assert rules.audit_native_rule(rule) == [], \
                f"{ent.get('bookSourceName')} 判 yes 但引擎跑不动（假可用）"
        checked += 1
    assert checked >= 3, "夹具里连一条能用的都没有 ⇒ 这条断言等于没测"
