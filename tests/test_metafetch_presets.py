"""合并模式预设（第 52 期）→ 既有 fields 逐字段策略。

AUTO-FINALIZE 的「合并模式」在 Book Dock 页以预设呈现，落库时整体写成
metadata_fetch.fields 的逐字段策略；本测试钉住这层映射，确保 preset 名字变了
行为也不飘。
"""
from novelforge.core import metafetch

EXPECTED_KEYS = ["title", "author", "publisher", "year", "language",
                 "isbn", "description", "tags", "cover"]


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
