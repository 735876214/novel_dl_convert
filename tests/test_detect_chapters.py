"""第 55 期：分章判据的**唯一真值源**契约（`core/detect.py`）。

转换管线（`core/pipeline.py`）、书源（`sources/rules.py`、`sources/manager.py`）、
AI 兜底（`core/ai_detect.py` 复用其 bounds/split）、以及**原生 TXT 阅读器**都吃
这一份「正文 → 章节列表」的实现。这里钉住它的**对外契约**，免得日后有人
「顺手优化」切分口径 —— 那会同时改掉出版成品的目录与阅读器的章节流。

钉住的口径（全部为**实测**，不是从注释抄的）：

1. 出参形状 `[{title, body, vol}]`；`title` 只到标记本身（如 `第一章`），
   标题行的文字留在 `body` 里；
2. **首个边界之前的内容（书名 / 作者行）会被丢弃** —— 注释曾写「并入首章正文」，
   与实现不符，第 55 期已把注释改成实际行为（不改正则，因为改它就是改出版成品）；
3. 正则置信判据：命中数 × 2000 ≥ 文本长度才算「正则有效」，否则退化**缩进切分**；
4. 缩进降级：顶格行 = 章标题，其下的缩进行 = 该章正文；
5. `merge=True` 把正文 < `MERGE_MIN_LEN` 的碎片章并入上一章；
6. `detect_chapters_cfg` 在**没有 llm.api_key** 时分毫不差地等于 `detect_chapters`
   （即没有 AI 兜底时不产生任何额外行为）。

**第 62 期改了两条口径**（见 `detect.CHAPTER_RULE_VERSION`），本文件的用例随之
重写/新增，理由逐条写在用例里：

7. **行首锚定**：标记必须落在行首（允许行首空白，不跨行）。正文段落中间提到
   「第 3 章」不再算边界 —— 这是第 55 期**刻意钉住的旧口径**，现按计划反转；
8. 卷 / 括号 / 序章类新形态见下方用例。
"""
from novelforge.core import detect


def test_两章切分_标题只到标记_正文含标题行():
    text = "第一章 起风\n" + "风" * 100 + "\n第二章 落雨\n" + "雨" * 100

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == ["第一章", "第二章"]
    assert chaps[0]["body"].startswith("第一章 起风")
    assert chaps[1]["body"].startswith("第二章 落雨")
    assert all(c["vol"] == "正文" for c in chaps)


def test_首个边界之前的内容会被丢弃():
    """书名 / 作者行不在首章正文里 —— 这是**现状**（注释此前写反了，已订正）。"""
    text = "书名：测试\n第一章 起\n" + "正" * 100

    chaps = detect.detect_chapters(text)

    assert len(chaps) == 1
    assert chaps[0]["body"].startswith("第一章 起")
    assert "书名：测试" not in chaps[0]["body"]


def test_英文与特殊章标记():
    text = "Chapter 1 Start\n" + "a" * 120 + "\nChapter 2 End\n" + "b" * 120

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == ["Chapter 1", "Chapter 2"]


def test_正则命中太少则退化为缩进切分():
    """「命中数 × 2000 ≥ 长度」是置信判据：命中太少 ⇒ 缩进降级。"""
    text = "顶格行一\n    缩进正文一\n顶格行二\n    缩进正文二\n顶格行三"

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == ["顶格行一", "顶格行二", "顶格行三"]
    assert chaps[0]["body"] == "缩进正文一"
    assert chaps[1]["body"] == "缩进正文二"
    assert chaps[2]["body"] == ""


def test_merge_把碎片章并入上一章():
    text = ("第一章 起\n短\n第二章 落\n更短\n第三章 长\n" + "长" * 100)

    loose = detect.detect_chapters(text)
    merged = detect.detect_chapters(text, merge=True)

    assert [c["title"] for c in loose] == ["第一章", "第二章", "第三章"]
    assert [c["title"] for c in merged] == ["第一章", "第三章"]
    # 被并入的章标题会作为普通文本留在上一章正文里（不丢字）
    assert "第二章" in merged[0]["body"] and "更短" in merged[0]["body"]
    assert "短" in merged[0]["body"]


def test_cfg_无_api_key_时等于纯正则():
    """没有 AI 兜底（未配 llm.api_key）时，两个入口必须逐字一致 —— 否则
    「配置了 hybrid 但没填 key」会悄悄改变出版结果的目录。"""
    text = "第一章 甲\n" + "甲" * 100 + "\n第二章 乙\n" + "乙" * 100

    assert detect.detect_chapters_cfg(text, {}) == detect.detect_chapters(text)
    assert detect.detect_chapters_cfg(text, {"chapter_detection": {"mode": "hybrid"}}) == \
        detect.detect_chapters(text)


def test_空文本与无边界文本不炸():
    assert detect.detect_chapters("") == []
    # 单行长文本没有正则边界 ⇒ 缩进降级出 1 章（顶格行即标题）
    chaps = detect.detect_chapters("一整段没有章节标记的文本" * 20)
    assert len(chaps) == 1


def test_正文中间提到的章号不再被当边界():
    """⚠️ **第 62 期反转了第 55 期刻意钉住的口径**。

    旧口径：章节正则**非锚定**，正文里提一句「他看到第 3 章的标题」就被当成边界，
    段落被拦腰截断、目录凭空多出一条「第 3 章」。第 55 期不改正则，是因为这条判据
    同时决定出版成品的目录（`core/pipeline.py` 走同一实现），改它 = 存量 EPUB
    重出版后目录会变 —— 要改得单独评估、出版与阅读器一起改。本期即按该条件改：
    规则改动由 `detect.CHAPTER_RULE_VERSION` 记版本，`txtcache` 据此重建派生缓存。
    """
    text = ("第一章 起\n" + "正文。" * 40
            + "\n他看到第 3 章的标题。\n" + "续写。" * 40)

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == ["第一章"]
    assert "他看到第 3 章的标题" in chaps[0]["body"], "那句话是正文，不许丢"


def test_行首的章号仍旧算边界():
    """锚定的是**行首**，不是「整行只有标记」—— 行首带标题（`第 3 章 他真的讲过`）
    与行首缩进（全角空格）都照旧成立，否则真目录会被砍掉一大截。"""
    text = ("第一章 起\n" + "正文。" * 40
            + "\n第 3 章 他真的讲过\n" + "续写。" * 40
            + "\n　　第 4 章 缩进的标题\n" + "再续。" * 40)

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == ["第一章", "第 3 章", "第 4 章"]


def test_卷单独成行与卷一写法():
    """计划点名的两种卷形态：`第一卷` 单独成行、`卷一 起风`（数字在「卷」之后）。"""
    text = ("第一卷\n" + "甲" * 200
            + "\n第一章 起\n" + "乙" * 200
            + "\n卷二 落雨\n" + "丙" * 200)

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == ["第一卷", "第一章", "卷二 落雨"]
    assert [c["vol"] for c in chaps] == ["第一卷", "正文", "卷二 落雨"], \
        "卷首要把 vol 带上（阅读器/成品据此做卷分组）"


def test_卷首不能吃掉正文句子():
    """「一部分……」「第二部的内容……」这类**普通句子**不许被判成卷首 ——
    「数字 + 卷/部」后面必须跟真分隔符（分隔号或空格）才认标题。"""
    for line in ("一部分内容他已经看过了，剩下的部分明天再读。",
                 "第二部的内容其实并不复杂，读起来很快。"):
        text = line + "\n" + "正文。" * 200
        chaps = detect.detect_chapters(text)
        assert [c["title"] for c in chaps] != [line[:20]], f"{line!r} 被误判成卷首"


def test_括号与全角句点章标记():
    """计划点名的其余形态：`【第1章】`、`（一）`、`1．风`（全角句点 U+FF0E）。

    `（1）`（阿拉伯数字的括号形式）**刻意不认** —— 它在正文里更像列表项 / 脚注编号，
    误判的代价比漏切大；真按「（1）」分章的文本多半另有可切的章标记。
    """
    assert [c["title"] for c in detect.detect_chapters(
        "【第1章】风起\n" + "甲" * 200 + "\n【第2章】雨落\n" + "乙" * 200)] \
        == ["【第1章】", "【第2章】"]
    assert [c["title"] for c in detect.detect_chapters(
        "（一）\n" + "甲" * 200 + "\n（二）\n" + "乙" * 200)] == ["（一）", "（二）"]
    assert [c["title"] for c in detect.detect_chapters(
        "1．风\n" + "甲" * 200 + "\n2．雨\n" + "乙" * 200)] == ["1．风", "2．雨"]


def test_序章类捕获整行而不是只捕获标记():
    """`番外一 开始` 此前只切出「番外」，「一 开始」被丢在正文里 —— 现在整行都是标题。"""
    text = "序章\n" + "甲" * 200 + "\n番外一 开始\n" + "乙" * 200

    chaps = detect.detect_chapters(text)

    assert [c["title"] for c in chaps] == ["序章", "番外一 开始"]


def test_同一位置被多条模式命中只留一个边界():
    """`第二卷 第三章 风起` 既被「卷+章」命中、又被「卷单独成行」整行命中。
    留下两个同偏移的边界会切出一个正文为空的假章（`text[pos:pos]`）。"""
    text = "第二卷 第三章 风起\n" + "甲" * 200

    bounds = detect.regex_bounds(text)

    assert len(bounds) == 1 and len(bounds[0]) == 2
    chaps = detect.detect_chapters(text)
    assert len(chaps) == 1 and chaps[0]["body"].strip()

