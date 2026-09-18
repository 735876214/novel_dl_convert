"""库类型 → 能力矩阵（`core/features.py`）。

这张表的判据是**现有实现真实支持的范围**，不是「理论上可以」——
例如元数据抓取只写 EPUB 的 OPF，所以漫画库不该显示那些设置页。
把边界钉住，是为了防止以后有人顺手把能力加宽，让用户点进一个用不了的入口。
"""
from novelforge.core import features, library

#: 与格式无关的通用能力（三类库都有）
COMMON = {"rename", "duplicates", "entity", "missing", "logs", "output"}


def test_漫画库能力集():
    assert set(features.features_for("comic")) == COMMON | {"comic", "opds_sources", "komga"}


def test_有声书库能力集():
    assert set(features.features_for("audiobook")) == COMMON | {"audio"}


def test_电子书库能力集():
    got = set(features.features_for("ebook"))
    assert {"ebook", "pdf", "annotations", "metadata", "authors",
            "convert", "sources", "opds_sources", "komga"} <= got
    assert "comic" not in got and "audio" not in got


def test_元数据抓取能力只在电子书库():
    # 判据：元数据抓取只改写 EPUB 的 OPF（见 metafetch.plan 的非 EPUB 跳过说明）
    assert "metadata" in features.features_for("ebook")
    assert "metadata" not in features.features_for("comic")
    assert "metadata" not in features.features_for("audiobook")


def test_全部书库与混合库返回全部能力():
    # 「全部书库」是默认态，**不做裁剪** —— 否则用户一进来就发现功能少了
    assert features.features_for("") == features.ALL_FEATURES
    assert features.features_for("mixed") == features.ALL_FEATURES
    assert features.features_for(None, None) == features.ALL_FEATURES


def test_未知类型保守返回全部能力():
    # 宁可多显示几个入口，也不要把功能藏起来让人找不到（与前端 hasFeature 同一原则）
    assert features.features_for("weird-type") == features.ALL_FEATURES


def test_按库id取能力(isolated, tmp_path, make_library):  # noqa: ARG001
    make_library("comic", "漫画库", "comic", tmp_path / "libs" / "comics")
    assert set(features.features_for(library_id="comic")) == set(features.features_for("comic"))
    # 库里查不到的 id → 退回「不裁剪」
    assert features.features_for(library_id="不存在的库") == features.ALL_FEATURES


def test_visible判定():
    assert features.visible("comic", "comic") is True
    assert features.visible("comic", "convert") is False
    assert features.visible("mixed", "convert") is True


def test_能力矩阵与中文标签():
    m = features.matrix()
    assert set(m["types"]) >= {"ebook", "comic", "audiobook", "mixed"}
    assert m["all"] == list(features.ALL_FEATURES)
    # 每个能力都要有中文名：书库管理页直接展示这份标签
    assert set(m["labels"]) == set(features.ALL_FEATURES)
    assert features.labels()["convert"] == "本地转换（TXT → EPUB）"


def test_默认库是混合库所以不裁剪(isolated):  # noqa: ARG001
    default = library.default_library()
    assert default["type"] == "mixed"
    assert features.features_for(default["type"]) == features.ALL_FEATURES
