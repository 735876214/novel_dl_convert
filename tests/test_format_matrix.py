"""格式 × 能力矩阵的**契约测试**（第 87 期第②步）。

判据与成文口径见 `docs/format-capability-matrix.md`。本文件的唯一职责是：

· **通用能力**（与格式无关）必须在**四类库**里都有；
· 任何「只给部分库」的能力键**必须**在下面的 `EXCLUSIVE` 表里登记**理由** ——
  否则本文件会红。

⚠️ 这条闸门是第 86 期那个真 bug 逼出来的：`sources` 漏给了漫画/有声书库，
而注释里还留着一条**过期的事实**（「书源下载产出 EPUB → 仅 ebook」）——
结果**选中漫画库时「工具 → 书源管理」标签整个消失**（用户报「书源找不到在哪」）。
能力键的判据是「**现有实现真实支持的范围**」，实现扩了而能力键没扩，
界面就会藏起用户真正需要的入口。以后再加一个「只给某类库」的能力键，
就必须在这里写明为什么 —— 写理由的过程本身会暴露漏配。
"""
from novelforge.core import features

#: 只给部分库类型的能力键 → 理由（**必须**与 `docs/format-capability-matrix.md` 一致）
EXCLUSIVE = {
    "ebook": "EPUB 文字阅读器（专有形态）",
    "pdf": "PDF 阅读器（专有形态）",
    "comic": "漫画阅读器（专有形态）",
    "audio": "有声书播放器（专有形态）",
    "annotations": "批注长在文字阅读器里；漫画/PDF/有声书是另外的渲染器",
    "bookmarks": "同 annotations",
    "authors": "与作者检索绑定，目前只有 ebook 走那条检索路",
    "convert": "手动投递入库 —— 门槛沿用旧口径刻意没放宽（独立一期评估）",
    "komga": "Komga 布局针对系列化目录；有声书库不进（协议无音频模型）",
}

_TYPES = ("ebook", "comic", "audiobook", "mixed")


def test_通用能力四类库都必须有():
    """`_COMMON` 是与格式无关的那一批 —— 少一个库就是「某类库看不见一个通用功能」。"""
    for key in features._COMMON:                      # noqa: SLF001 —— 同仓同源，刻意直取
        for t in _TYPES:
            assert key in features.FEATURES_BY_TYPE[t], f"{t} 库缺通用能力 {key}"


def test_只给部分库的能力键都必须写明理由():
    for key in features.ALL_FEATURES:
        types = {t for t in _TYPES if key in features.FEATURES_BY_TYPE[t]}
        if types == set(_TYPES):
            continue
        assert key in EXCLUSIVE, (
            f"能力键 {key} 只给了 {sorted(types)} —— 要么补全四类库，"
            f"要么在 tests/test_format_matrix.py 的 EXCLUSIVE 里写明理由"
            f"（并同步 docs/format-capability-matrix.md）")
        assert types, f"{key} 一个库都没给，那它不该出现在能力表里"


def test_混合库与全部书库含全部能力():
    """`mixed` 是「什么都收」的兜底类型 ⇒ 能力集必须是全集（否则兜底库反而少功能）。"""
    assert set(features.FEATURES_BY_TYPE["mixed"]) == set(features.ALL_FEATURES)
    assert features.features_for("") == features.ALL_FEATURES


def test_每条能力键都有中文名():
    """能力键要出现在界面上，缺中文名就是给用户看一个英文 key。"""
    for key in features.ALL_FEATURES:
        assert features.FEATURE_LABELS.get(key), f"{key} 缺中文名"
    for key in features.FEATURE_LABELS:
        assert key in features.ALL_FEATURES, f"{key} 有中文名但不在任何库的能力集里"


def test_书源能力三类库都有():
    """第 86 期那个 bug 的定点回归：文本/漫画/有声书都能用书源下载。

    三类库的产出形态不同（EPUB / CBZ / 目录树），但**能力键是同一个** ——
    此前只给了 ebook/mixed，漫画库下整个「书源管理」标签会消失。
    """
    for t in ("ebook", "comic", "audiobook"):
        assert "sources" in features.FEATURES_BY_TYPE[t]


def test_设置覆盖项声明的能力键都真实存在():
    """`SETTING_CAPS` 里写错一个键名 ⇒ 那个覆盖项会在所有库上被悄悄剔除（静默失效）。"""
    for path, cap in features.SETTING_CAPS.items():
        assert cap in features.ALL_FEATURES, f"{path} 声明了不存在的能力键 {cap}"
