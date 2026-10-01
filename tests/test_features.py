"""库类型 → 能力矩阵（`core/features.py`）。

这张表的判据是**现有实现真实支持的范围**，不是「理论上可以」——
例如元数据抓取只写 EPUB 的 OPF，所以漫画库不该显示那些设置页。
把边界钉住，是为了防止以后有人顺手把能力加宽，让用户点进一个用不了的入口。
"""
from novelforge.core import features

#: 与格式无关的通用能力（三类库都有）
COMMON = {"rename", "duplicates", "entity", "missing", "logs", "output", "opds"}


def test_漫画库能力集():
    # ⚠️ 第 86 期起 `sources` **也归漫画库**：书源下载现在三类产物都有（文本 EPUB /
    #    漫画 CBZ / 有声书目录树），漫画源本来就是主要来源之一。
    #    这条以前写作「仅 ebook」—— 那是第 86 期之前的事实；能力键没跟上时的实测后果是
    #    **选中漫画库时「工具 → 书源管理」整个标签消失**（用户报「书源找不到在哪」）。
    assert set(features.features_for("comic")) == COMMON | {"comic", "metadata", "komga", "sources"}


def test_有声书库能力集():
    assert set(features.features_for("audiobook")) == COMMON | {"audio", "metadata", "sources"}


def test_电子书库能力集():
    got = set(features.features_for("ebook"))
    assert {"ebook", "pdf", "annotations", "bookmarks", "metadata", "authors",
            "convert", "sources", "komga"} <= got
    assert "comic" not in got and "audio" not in got


def test_书签与批注同档只给文字阅读器的库():
    # 书签长在文字阅读器里：漫画（ComicReader）/ 有声书（播放器）没有这个入口
    assert "bookmarks" in features.features_for("ebook")
    assert "bookmarks" in features.features_for("mixed")
    assert "bookmarks" not in features.features_for("comic")
    assert "bookmarks" not in features.features_for("audiobook")


def test_元数据抓取能力覆盖电子书漫画与有声书():
    # 判据：抓取结果只存服务端 DB、与文件格式无关（**手动编辑**仍限 EPUB，那是另一条路径）
    assert "metadata" in features.features_for("ebook")
    assert "metadata" in features.features_for("comic")
    assert "metadata" in features.features_for("audiobook")
    # 作者元数据仍只给电子书 / 混合库（与作者检索绑定）
    assert "authors" not in features.features_for("comic")


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
    # 第 62 期改标签（键名不变，含义收敛为「手动投递入库」）：TXT 已「只入库不转换」，
    # 这个页面不再产出转换件 —— 标签必须跟着实际行为走，否则是明着骗用户。
    assert features.labels()["convert"] == "本地导入（手动投递）"


def test_混合库不裁剪任何能力(isolated):  # noqa: ARG001
    """`mixed` 库的能力集 = 全部。

    第 37 期前这条测的是「合成出来的默认库是 mixed」；默认库没了，但**判据本身**
    （mixed ⇒ 全量白名单）仍要钉住 —— 它是「新建库时选 mixed 就等于不裁剪」的契约。
    """
    assert features.features_for("mixed") == features.ALL_FEATURES
