"""第 55 期：分章判据的**唯一真值源**契约（`core/detect.py`）。

转换管线（`core/pipeline.py`）、书源（`sources/rules.py`、`sources/manager.py`）、
AI 兜底（`core/ai_detect.py` 复用其 bounds/split）、以及本期新增的**原生 TXT
阅读器**都吃这一份「正文 → 章节列表」的实现。这里钉住它的**对外契约**，
免得日后有人「顺手优化」切分口径 —— 那会同时改掉出版成品的目录与阅读器的章节流。

钉住的口径（全部为**实测**，不是从注释抄的）：

1. 出参形状 `[{title, body, vol}]`；`title` 只到标记本身（如 `第一章`），
   标题行的文字留在 `body` 里；
2. **首个边界之前的内容（书名 / 作者行）会被丢弃** —— 注释曾写「并入首章正文」，
   与实现不符，本期已把注释改成实际行为（不改正则，因为改它就是改出版成品）；
3. 正则置信判据：命中数 × 2000 ≥ 文本长度才算「正则有效」，否则退化**缩进切分**；
4. 缩进降级：顶格行 = 章标题，其下的缩进行 = 该章正文；
5. `merge=True` 把正文 < `MERGE_MIN_LEN` 的碎片章并入上一章；
6. `detect_chapters_cfg` 在**没有 llm.api_key** 时分毫不差地等于 `detect_chapters`
   （即没有 AI 兜底时不产生任何额外行为）。
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


def test_正文里出现章标记也会被当边界_与出版链路同口径():
    """⚠️ **现状口径**（不是理想行为）：章节正则是**非锚定**的，「第 N 章」出现在
    正文里照样算边界 —— 于是正文提到「第 3 章」的那一段会被切成新章。

    钉住它的原因：这条判据同时决定**出版成品的目录**（`core/pipeline.py` 走同一
    实现），改它 = 存量 EPUB 重出版后目录会变。要改必须作为独立一期评估，
    并且与出版、阅读器两处一起改。
    """
    text = ("第一章 起\n" + "正文。" * 40
            + "\n他看到第 3 章的标题。\n" + "续写。" * 40)

    chaps = detect.detect_chapters(text)

    # 正文里的「第 3 章」被当作边界 ⇒ 多切出一章（标题只到标记本身）
    assert len(chaps) == 2
    assert chaps[1]["title"] == "第 3 章"
