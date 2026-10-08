"""第 102 期：**元数据来源声明是唯一真值源**的契约。

第 102 期把一家源的信息从 `core/metasources.py` 的 **7 张手工扁平表**收口到
`core/sources/registry.py` 的一份声明（`Provider`），7 张表全部改为**派生**。

本文件钉住三件事，每一件都对应一个**真实的、发生过的**静默失败：

1. **声明自洽**（`registry.validate()`）—— 尤其「`needs_config=True` 却不声明 secret
   配置项」：界面会显示「需要设置」却**没有任何输入框**，而体检又因读不到密钥判
   `missing_key` —— 一家永远用不了、且看不出为什么的源。
2. **派生表 == 声明**：漏一张表就回到「改一处、别处不一致」。第 60 期正是因为
   `LANG_AFFINITY` 漏项不报错，才补了「每家在语种表里必须表态」的断言 ——
   现在由 `Provider.langs` 空元组显式表达「通吃」，**不再有漏的可能**。
3. **派生读取器的签名与返回形状不变**：`SOURCES` 仍是 `dict[str, dict]`
   （`SOURCES[id]["label"]` 这种取法在 server / metafetch / metascore / 前端契约里
   到处在用），`provider_catalog()` 的条目仍带齐前端吃的所有键。

⚠️ 与 `tests/test_sources_registry.py` **不是一回事**：那个文件管的是**书源引擎**
（`novelforge/sources/` 的 `REGISTRY`，Legado 规则那套）；本文件管的是**元数据来源**
（`novelforge/core/metasources.py`）。两者是同一段中文名下的两个不同子系统。
"""
import pytest

from novelforge.core import metasources
from novelforge.core.sources import kinds, registry


# ---------------------------------------------------------------- 1. 声明自洽

def test_声明表自洽():
    """id 唯一 / kind 合法 / group 合法 / needs_config 必有 secret 项（见模块 docstring）。"""
    registry.validate()


def test_每家都选了领域轴():
    """第 102 期新增 `kind`：**每家必须显式表态**，不能默默漏过。

    拼错 kind 的后果是静默的 —— `kinds.fields_of()` 对未知 kind 返回空集，
    界面会显示「这家什么都不提供」而不是报错。
    """
    for p in registry.DECLARED:
        assert p.kind in kinds.KINDS, f"{p.id} 的 kind 非法：{p.kind!r}"
        assert kinds.fields_of(p.kind), f"{p.id} 的 kind 没有字段白名单：{p.kind!r}"


def test_领域轴的取值就是四档():
    assert kinds.KINDS == ("ebook", "comic", "anime", "audiobook")
    # 中文名必须齐（界面直接用这一份，别在两端各写一套说法）
    assert set(kinds.KIND_LABELS) == set(kinds.KINDS)


def test_每家在语种表里都表了态():
    """`LANG_AFFINITY | LANG_BROAD == SOURCES` 且两者不相交（第 60 期定的契约）。

    第 102 期起这不是「手工表要记得加」，而是**由声明派生**：`langs` 空 = 通吃。
    断言保留，因为它防的是「派生逻辑写错」，与第 60 期防的是同一件事。
    """
    assert set(metasources.LANG_AFFINITY) | set(metasources.LANG_BROAD) == set(metasources.SOURCES)
    assert not (set(metasources.LANG_AFFINITY) & set(metasources.LANG_BROAD))
    # 派生来源必须与声明逐家对上
    for p in registry.DECLARED:
        if p.langs:
            assert metasources.LANG_AFFINITY[p.id] == tuple(p.langs), p.id
        else:
            assert p.id in metasources.LANG_BROAD, p.id


# ---------------------------------------------------------------- 2. 派生表 == 声明

def test_派生表与声明逐项一致():
    """7 张派生表全部由声明算出 —— 这里逐项验算，防「派生逻辑漏了一家」。"""
    declared = {p.id: p for p in registry.DECLARED}

    # ① SOURCES 键集合与顺序 = 声明顺序
    assert list(metasources.SOURCES) == [p.id for p in registry.DECLARED]
    # ② IMPLEMENTED = 真有 fetch 的家
    assert set(metasources.IMPLEMENTED) == {p.id for p in registry.DECLARED if p.fetch_name}
    # ③ _FETCHERS 键集合 = 声明里声明了 fetch 的家
    assert set(metasources._FETCHERS) == {p.id for p in registry.DECLARED if p.fetch_name}
    # ④ _ISBN_FETCHERS 键集合 = 声明了 isbn 的家
    assert set(metasources._ISBN_FETCHERS) == {p.id for p in registry.DECLARED if p.isbn_name}
    # ⑤ SOURCE_ID_FIELD = 声明了 id_field 的家
    assert metasources.SOURCE_ID_FIELD == {p.id: p.id_field
                                          for p in registry.DECLARED if p.id_field}
    # ⑥ HEALTH_SAMPLES 键集合 = 全部家（没声明样本的用通用样本）
    assert set(metasources.HEALTH_SAMPLES) == set(declared)
    # ⑦ IMPLEMENTED 与 _FETCHERS 逐字一致（第 57 期定的老契约，继续钉）
    assert set(metasources.IMPLEMENTED) == set(metasources._FETCHERS)


def test_声明的可见字段逐字进了注册表():
    """`SOURCES` 的可见字段必须来自声明 —— 这是「只改一处」的实际含义。"""
    for p in registry.DECLARED:
        meta = metasources.SOURCES[p.id]
        assert meta["label"] == p.label, p.id
        assert meta["group"] == p.group, p.id
        assert meta["home"] == p.home, p.id
        assert meta["note"] == p.note, p.id
        assert meta["fragile"] == p.fragile, p.id
        assert meta["needs_config"] == p.needs_config, p.id
        assert meta["config_hint"] == p.config_hint, p.id
        assert meta["kind"] == p.kind, p.id


def test_抓取函数全部绑定成功():
    """声明里写了 `fetch_name` 却找不到同名函数 ⇒ `_bind_declared()` **抛错**，不静默忽略。

    「静默忽略」正是第 102 期要消灭的那类失败：源出现在声明里、界面给开关、
    点下去却抓不了。
    """
    missing = [p.id for p in registry.DECLARED
               if p.fetch_name and p.id not in metasources._FETCHERS]
    assert missing == [], f"这些家声明了抓取函数却没绑上：{missing}"
    # 绑上的确实是函数（不是 None / 不是字符串）
    for sid, fn in metasources._FETCHERS.items():
        assert callable(fn), sid


# ---------------------------------------------------------------- 3. 兼容边界

def test_SOURCES仍是dict_of_dict():
    """第 102 期**刻意不动**的兼容边界：`SOURCES[id]["label"]` 这类取法全仓库在用。"""
    assert isinstance(metasources.SOURCES, dict)
    for sid, meta in metasources.SOURCES.items():
        assert isinstance(meta, dict), sid
        assert isinstance(meta["label"], str), sid
        # 取值方式照旧可用（不是 dataclass / 不是 attrdict）
        assert meta["label"] == meta.get("label"), sid


def test_provider_catalog条目带齐前端要的键():
    """前端「元数据来源」页直接吃 `provider_catalog()` —— 键少了页面会渲染成空白。"""
    items = metasources.provider_catalog()
    assert len(items) == 13
    need = {"id", "label", "group", "home", "note", "implemented", "fragile",
            "needs_config", "config_hint", "config_fields", "key_field", "key_label",
            "key_placeholder", "langs", "lang_broad", "kind"}
    for item in items:
        missing = need - set(item)
        assert not missing, f"{item['id']} 缺键：{missing}"


def test_派生读取器签名与返回值不变():
    """这些是别处（server / metafetch / metascore / 前端契约）依赖的公开形状。"""
    # is_implemented / needs_key 返回 bool
    for sid in metasources.SOURCES:
        assert isinstance(metasources.is_implemented(sid), bool), sid
        assert isinstance(metasources.needs_key(sid), bool), sid
    # 未知源不抛，如实回 False / 空
    assert metasources.is_implemented("不存在的源") is False
    assert metasources.needs_key("不存在的源") is False
    assert metasources.config_fields_of("不存在的源") == []
    assert metasources.key_field_of("不存在的源") == ""
    # secret_fields 是 tuple，且每项都不重复
    sec = metasources.secret_fields()
    assert isinstance(sec, tuple) and sec
    assert len(set(sec)) == len(sec), "secret 键名不能重复"
    # options_for 形状：{源: {opt: 值}}
    opts = metasources.options_for({"amazon_cookie": "abc"}, ["amazon"])
    assert opts == {"amazon": {"cookie": "abc"}}
    assert metasources.options_for({}, ["amazon"]) == {}


def test_新增的领域轴与限流字段进了注册表():
    """第 102 期给注册表加的三项（`kind` / `rate_limit` / `cache_ttl`）要能被读到。"""
    for p in registry.DECLARED:
        meta = metasources.SOURCES[p.id]
        assert meta["kind"] == p.kind
        assert meta["rate_limit"] == list(p.rate_limit)
        assert isinstance(meta["cache_ttl"], int) and meta["cache_ttl"] >= 0
    # 实测需要限流的家（官方文档给的额度）
    assert metasources.SOURCES["comicvine"]["rate_limit"] == [1, 18.0]   # 200 次/小时
    assert metasources.SOURCES["ranobedb"]["rate_limit"] == [1, 1.0]     # ≤60 次/分钟
    assert metasources.SOURCES["openlibrary"]["rate_limit"] == []        # 未声明 = 不限


@pytest.mark.parametrize("kind", kinds.KINDS)
def test_字段白名单是METADATA_FIELDS的子集(kind):
    """`kinds.FIELDS_OF_KIND` 描述的是「元数据字段」——不该出现不存在的字段名。

    `fileops.METADATA_FIELDS` 是写回 EPUB 的字段全集；白名单里写错一个名字
    （如把 `narrators` 写成 `narrator`）会让界面把它当有效字段显示。
    """
    from novelforge.core import fileops
    allowed = set(fileops.METADATA_FIELDS)
    bad = kinds.fields_of(kind) - allowed
    assert not bad, f"{kind} 的字段白名单含未知字段：{sorted(bad)}"
