"""合并模式预设（第 52 期）→ 既有 fields 逐字段策略。

AUTO-FINALIZE 的「合并模式」在 Book Dock 页以预设呈现，落库时整体写成
metadata_fetch.fields 的逐字段策略；本测试钉住这层映射，确保 preset 名字变了
行为也不飘。
"""
from novelforge import config
from novelforge.core import fileops, metafetch

#: 逐字列出，**不用** `set(metafetch._FINALIZE_FIELDS)` 生成 —— 那等于拿被测对象
#: 断言它自己。这里要的是「加字段必须有意改一次这张表」。
#: ⚠️ 出版年写 **`date`**（字段名）。第 63 期之前这里（以及 `_FINALIZE_FIELDS` /
#: `config` 默认值）写的是 `year` —— 那是**书对象**里的名字，`metafetch.plan` 是按
#: 字段名查策略的，于是预设里「出版年」那一档**从来没生效过**（查不到 ⇒ 回落默认），
#: 而设置页的逐字段下拉写的是 `date`、一直是对的。两套键空间并存了整整若干期。
EXPECTED_KEYS = ["title", "author", "publisher", "date", "language",
                 "isbn", "description", "tags", "series", "series_index", "cover",
                 "subtitle", *fileops.PROVIDER_ID_FIELDS]


def test_每个策略键都必须是引擎真的会去查的字段名():
    """策略表的键**必须**是 `metafetch._VALUE_KEYS` 的键（= `plan` 查策略用的名字），
    外加封面那个独立键 `cover`。

    写成书对象里的名字（`year` 而不是 `date`）不会报错、只会**静默失效**：
    `plan` 查不到 ⇒ 回落 `DEFAULT_POLICY` ⇒ 用户设的那一档等于没设。
    这条就是当年 `year`/`date` 两套键空间并存若干期的护栏。
    """
    valid = set(metafetch._VALUE_KEYS) | {"cover"}
    assert set(metafetch._FINALIZE_FIELDS) <= valid, \
        set(metafetch._FINALIZE_FIELDS) - valid
    assert "date" in metafetch._FINALIZE_FIELDS and "year" not in metafetch._FINALIZE_FIELDS


def test_预设对出版年真的生效():
    """端到端复述上一条的**行为面**：预设说「不修改」，`plan` 就必须真的不动出版年。

    只看键名对不对是不够的（键对了但 `plan` 读别处，照样失效）。
    """
    f = metafetch.preset_to_fields("embedded_only")
    assert metafetch._field_policy(f, "date") == "skip"


def test_引擎侧与配置侧的字段表必须同集合():
    """两张手抄的表：`metafetch._FINALIZE_FIELDS`（引擎读策略）与
    `config.DEFAULTS.metadata_fetch.fields`（新装用户的默认配置）。

    漏一边的表现都是**静默的**：只加引擎侧 ⇒ 新字段没有默认策略（靠
    `_field_policy` 兜底）；只加配置侧 ⇒ 那个键在 preset 展开时被丢掉。
    """
    assert set(metafetch._FINALIZE_FIELDS) == set(EXPECTED_KEYS)
    assert set(config.DEFAULTS["metadata_fetch"]["fields"]) == set(EXPECTED_KEYS)


def test_preset_overwrite_全字段覆盖():
    f = metafetch.preset_to_fields("overwrite")
    assert set(f) == set(EXPECTED_KEYS)
    assert all(v == "overwrite" for v in f.values())


def test_preset_fill_only_与_safe_merge_等价():
    # 安全合并 = 仅补空值，等价于 fill_only
    for preset in ("fill_only", "safe_merge"):
        f = metafetch.preset_to_fields(preset)
        assert set(f) == set(EXPECTED_KEYS)
        assert all(v == "fill_only" for v in f.values())


def test_preset_embedded_only_全字段跳过():
    # 仅用内嵌：不下载在线封面 / 远程字段 → 全部 skip
    f = metafetch.preset_to_fields("embedded_only")
    assert set(f) == set(EXPECTED_KEYS)
    assert all(v == "skip" for v in f.values())


def test_preset_未知回落_overwrite_不丢配置():
    # 未知预设不能静默变成空字典或异常，回落 overwrite 最安全
    f = metafetch.preset_to_fields("__bogus__")
    assert set(f) == set(EXPECTED_KEYS)
    assert all(v == "overwrite" for v in f.values())


def test_presets_声明齐全():
    assert set(metafetch.FINALIZE_PRESETS) >= {"overwrite", "fill_only", "embedded_only"}


def test_系列两项的默认策略是fill_only():
    """系列 / 卷号的**默认**策略是 fill_only（与整表其它项的 overwrite 不同，故意的）。

    理由写在 `config.DEFAULTS` 那段注释里，核心是一条：系列会参与**命名规则**
    （`{series}` / `{series_index}`）与系列视图 —— 默认覆盖会静默改掉用户已有的系列
    分组与文件名（重命名读的是生效值）。抓取的收益主要在**没有**系列的书上。

    这条钉的是默认值本身：谁把这两项「顺手统一成 overwrite」，用户可见行为就变了。
    """
    f = config.DEFAULTS["metadata_fetch"]["fields"]
    assert f["series"] == "fill_only" and f["series_index"] == "fill_only"
    others = {k: v for k, v in f.items() if k not in ("series", "series_index")}
    assert set(others.values()) == {"overwrite"}, "别因为这两项把整表改档"
