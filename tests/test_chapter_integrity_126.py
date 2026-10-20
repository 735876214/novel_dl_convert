"""第 126 期：分章「正文完整性」回归 —— 缩进降级不许把正文吃掉。

两条缺陷（都是**缩进降级**这一条路的，正则那条路 72 期已经堵过一半）：

1. **全顶格且一个章标记都没有**的文本（随笔 / 诗歌 / 一话一行的网文导出）被切成
   「一行一章、正文全空」—— 阅读器里满屏的 ``<h2>``，正文一个字都没有。
   72 期只在「正则**有**边界」时回退正则边界；一个边界都没有时没有可回退的东西。
2. **整本书都用全角空格缩进**（中文排版常态）又没有章标记时，第一个顶格行之前的
   缩进正文被 `cur is None` 直接跳过 —— 极端情况（全书缩进）切出 **0 章**，整本书读不了。

修法都落在 `detect.detect_chapters` 这一个入口（`:func:`detect.absorb_orphan_titles`
与 `_split_by_indent` 的前置章），所以 txt 阅读、派生 EPUB、mobi 缓存、CLI 转换同批受益。
"""
from novelforge.core import detect


def test_全顶格无标记文本退化成一章全文():
    """没有章标记、也没有缩进 ⇒ 整本书就是一章，正文一行不丢。"""
    text = "他来了。\n她走了。\n于是街上又空了。\n"

    chaps = detect.detect_chapters(text)

    assert len(chaps) == 1, f"该退化成一章，却切出 {len(chaps)} 章"
    assert chaps[0]["title"] == detect.FULLTEXT_TITLE
    assert all(ln in chaps[0]["body"] for ln in ("他来了。", "她走了。", "于是街上又空了。"))


def test_整本全角缩进无标记文本不再切出零章():
    """**这本书以前一个字都读不到**：`cur is None` 把首个顶格行之前的正文全跳过。"""
    text = "　　他来了。\n　　她走了。\n　　于是街上又空了。\n"

    chaps = detect.detect_chapters(text)

    assert len(chaps) == 1
    assert chaps[0]["title"] == detect.FULLTEXT_TITLE
    assert "他来了。" in chaps[0]["body"]
    assert "于是街上又空了。" in chaps[0]["body"]


def test_首行缩进的前置正文成前置章且行序不变():
    """前置缩进正文与后面的顶格行**都在**，且先出现的先读。"""
    text = "　　缩进一。\n　　缩进二。\n他插了一句。\n　　缩进三。\n"

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == [detect.FULLTEXT_TITLE, "他插了一句。"]
    assert chaps[0]["body"].startswith("缩进一。")
    assert chaps[1]["body"] == "缩进三。"


def test_空正文的尾章并进上一章而不是单独成章():
    """「顶格行 + 脚下没有缩进行」= 普通正文行，不是章标题（旧口径留了个空章）。"""
    text = "顶格一\n    正文一\n顶格二\n    正文二\n尾巴一行\n"

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == ["顶格一", "顶格二"]
    assert chaps[1]["body"] == "正文二\n尾巴一行"
    assert all(c["body"].strip() for c in chaps), "不许再有空正文的章"


def test_空行开头的全缩进文本也不丢字():
    text = "\n\n　　第一段。\n　　第二段。\n"

    chaps = detect.detect_chapters(text)

    assert len(chaps) == 1
    assert "第一段。" in chaps[0]["body"] and "第二段。" in chaps[0]["body"]


def test_无标记文本逐行核对一行都不少():
    """不变量：走缩进降级的文本，每一行非空输入都必须在某章的标题或正文里。"""
    samples = [
        "甲。\n乙。\n",
        "　　甲。\n乙。\n　　丙。\n",
        "短行\n    长一点的正文一行。\n短行二\n",
        "　　一\n　　二\n　　三\n",
        "正文一句。\n" * 40,
    ]
    for text in samples:
        assert not detect.regex_bounds(text), "本用例只覆盖缩进降级这条路"
        chaps = detect.detect_chapters(text)
        seen = "".join((c.get("title") or "") + "\n" + (c.get("body") or "") for c in chaps)
        for line in text.splitlines():
            line = line.strip()
            if line:
                assert line in seen, f"{line!r} 没进任何一章：{text!r}"


def test_真章节文本不受影响():
    text = "第一章 起\n" + "风" * 120 + "\n第二章 落\n" + "雨" * 120

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == ["第一章", "第二章"]
    assert chaps[0]["body"].startswith("第一章 起")
    assert all(c["vol"] == "正文" for c in chaps)


def test_空文本仍是零章():
    assert detect.detect_chapters("") == []
    assert detect.detect_chapters("\n \n\t\n") == []


def test_分章规则版本已随口径升级():
    """改了切分口径却不升版本 ⇒ 存量 TXT 的派生 EPUB 命中原缓存，**改了看不见**。"""
    assert detect.CHAPTER_RULE_VERSION >= 4
