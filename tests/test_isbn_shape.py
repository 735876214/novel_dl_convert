"""第 34 期：ISBN 形状判定 —— 唯一真值源 `metadata.isbn_digits`。

**为什么会有这个文件**：`tests/test_stats_integrity.py::test_分位数增补p25与p75且既有两键不动`
长期偶发失败（本机 8 轮全量里挂 2 轮）。逐层打印后看到漂移的是「薄.epub 的得分 32 → 42」
（差 10 分 = ISBN 那一档），再往前追是：

    `library._isbn_of` 与 `fileops._set_isbn` 各自写了一遍 `[\\dxX-]{10,17}` 的**子串**判据，
    而 EPUB 里最常见的 `dc:identifier` 就是一枚随机 **UUID**
    （`ec365410-6538-43b9-93e2-9f8cdd3c0c72` —— 中间一段数字加连字符正好落进那个形状）
    ⇒ 约 1/3 的随机 UUID 会被当成 ISBN。

后果不只是测试偶发：界面上会冒出一个**假 ISBN**、元数据完整度白送 10 分，
而 `_set_isbn` 更狠 —— 它会把书**自己的标识符覆盖掉**。

所以这里钉两件事：① 形状判据本身（单元）；
② 判定只有一处（`grep` 断言全仓不再有第二份 `[\\dxX-]{10,17}`）。
"""
import pathlib
import re

import pytest

from novelforge.core import epub_builder, fileops, library, metadata

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 真实撞过的那枚 UUID（本仓实测会命中旧判据）
_UUID = "ec365410-6538-43b9-93e2-9f8cdd3c0c72"


# ---------------------------------------------------------------------------
# ① 形状判据
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    # 正常 ISBN-13 / ISBN-10（含分隔符与前缀）
    ("9787539941123", "9787539941123"),
    ("978-7-5399-4112-3", "9787539941123"),
    ("978 7 5399 4112 3", "9787539941123"),
    ("urn:isbn:9787539941123", "9787539941123"),
    ("URN:ISBN:978-7-5399-4112-3", "9787539941123"),
    ("7539941127", "7539941127"),
    ("080442957X", "080442957X"),
    ("0-8044-2957-x", "080442957X"),
    # 不是 ISBN：UUID / 任意串 / 糊状字符串
    (_UUID, ""),
    ("urn:uuid:" + _UUID, ""),
    ("", ""),
    ("   ", ""),
    ("未知", ""),
    ("https://example.com/book/9787539941123", ""),   # URL 不是标识符本身
    ("123456789012", ""),                              # 12 位：既不是 10 也不是 13
    ("12345678901234", ""),                            # 14 位
    ("978753994112", ""),                              # 13 位数字里混了 12 位 + 字母？
    ("abcdefghij", ""),
])
def test_isbn形状判定(raw, want):
    assert metadata.isbn_digits(raw) == want


def test_十位校验位可以是x():
    assert metadata.isbn_digits("080442957x") == "080442957X", "小写 x 要规整成大写"


# ---------------------------------------------------------------------------
# ② 端到端：随机 UUID 的标识符**不得**被当成 ISBN（把偶发变成必然）
# ---------------------------------------------------------------------------

def test_只有uuid标识符的epub读不出isbn():
    """这一条就是那条 flaky 的钉子：UUID 是随机的，所以必须**多造几本**才有说服力。

    旧判据下约 1/3 命中 ⇒ 30 本全不命中的概率 < 1e-5（(2/3)^30）。所以它不是「抽一次看看」，
    而是「抽到就红」。
    """
    for i in range(30):
        opf = (
            '<?xml version="1.0"?><package><metadata>'
            f'<dc:identifier id="id">{"%08x-%04x-%04x-%04x-%012x" % (i * 7919, i, i, i, i * 104729)}</dc:identifier>'
            "</metadata></package>"
        )
        assert library._isbn_of(opf) == "", f"第 {i} 个 UUID 被当成了 ISBN：{opf}"


def test_uuid与isbn并存时取isbn():
    opf = ('<metadata><dc:identifier id="id">urn:uuid:' + _UUID + "</dc:identifier>"
           '<dc:identifier id="isbn">978-7-5399-4112-3</dc:identifier></metadata>')
    assert library._isbn_of(opf) == "978-7-5399-4112-3", "返回的是**原始写法**，但必须挑对那一条"


def test_写isbn不会覆盖书自己的uuid(tmp_path: pathlib.Path):
    """`_set_isbn` 的旧判据会命中 UUID ⇒ 直接把它替换掉，书丢了唯一标识符。"""
    path = tmp_path / "书.epub"
    epub_builder.build_epub({"title": "书", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(path))
    _opf_path, opf, _blob = fileops._read_epub(path)
    uuid_before = library._tag_all(opf, "dc:identifier")[0]
    assert "uuid" in uuid_before.lower() or len(uuid_before) == 36, uuid_before

    # patch_epub_meta 返回**实际改动的字段列表**（不是布尔）
    assert fileops.patch_epub_meta(path, {"isbn": "9787539941123"}) == ["isbn"]

    _p, opf2, _b = fileops._read_epub(path)
    ids = library._tag_all(opf2, "dc:identifier")
    assert uuid_before in ids, f"书自己的标识符被覆盖了：{ids}"
    assert library._isbn_of(opf2) == "9787539941123"
    assert len(ids) == 2, f"应当在保留原标识符的前提下**新增**一条 ISBN：{ids}"


def test_已有真isbn时是替换而不是追加(tmp_path: pathlib.Path):
    path = tmp_path / "书.epub"
    epub_builder.build_epub({"title": "书", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(path))
    assert fileops.patch_epub_meta(path, {"isbn": "9787539941123"}) == ["isbn"]
    assert fileops.patch_epub_meta(path, {"isbn": "9780306406157"}) == ["isbn"]

    _p, opf, _b = fileops._read_epub(path)
    ids = library._tag_all(opf, "dc:identifier")
    assert len(ids) == 2, f"第二次改 ISBN 不该再追加一条：{ids}"
    assert library._isbn_of(opf) == "9780306406157"


# ---------------------------------------------------------------------------
# ③ 判定只有一处（不许再长出第二份）
# ---------------------------------------------------------------------------

def test_全仓只有一处isbn形状判据():
    """这条宽松判据正是本 bug 的形态 —— 复制一份就是把 bug 复制一份。

    ⚠️ 先剥掉 `#` 注释再扫：`metadata.py` 的说明里必须**引用**这条旧判据（讲清它错在哪），
    那是文档不是代码（第 32/34 期「期望写得比事实严会得到假警报」的同类教训）。
    """
    hits = []
    for p in (ROOT / "novelforge").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if "[\\dxX-]{10,17}" in code or r"[\dxX-]{10,17}" in code:
                hits.append(f"{p.relative_to(ROOT)}:{i}")
    assert not hits, f"还有别处用着那条宽松的 ISBN 判据（应当统一走 metadata.isbn_digits）：{hits}"


def test_元数据读取确实走了唯一真值源():
    src = (ROOT / "novelforge" / "core" / "library.py").read_text(encoding="utf-8")
    assert re.search(r"def _isbn_of[\s\S]{0,400}metadata\.isbn_digits", src), \
        "library._isbn_of 没走 metadata.isbn_digits"
    src = (ROOT / "novelforge" / "core" / "fileops.py").read_text(encoding="utf-8")
    assert re.search(r"def _set_isbn[\s\S]{0,600}metadata\.isbn_digits", src), \
        "fileops._set_isbn 没走 metadata.isbn_digits"
