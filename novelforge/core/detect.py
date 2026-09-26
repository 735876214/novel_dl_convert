"""分章判据的**唯一真值源**（第 55 期起明确）。

「正文 → 章节列表」只有这一处实现：转换管线（`core/pipeline.py`）、书源
（`sources/*`）、AI 兜底（`core/ai_detect.py` 复用本模块的 bounds/split）与
原生 TXT 阅读器全部经此。改这里 = 同时改出版成品目录与阅读器章节流，
所以契约由 `tests/test_detect_chapters.py` 钉住，别在别处再写第二份切分。
"""
import re

# 多正则：覆盖常见章节标记（中文数字/阿拉伯/No./Chapter/序章番外等）
CHAPTER_PATTERNS = [
    re.compile(r"第\s*[零一二三四五六七八九十百千万亿0-9]+\s*[卷部]\s*[：:]*\s*第\s*[零一二三四五六七八九十百千万亿0-9]+\s*[章节回话集幕篇]"),
    re.compile(r"第\s*[零一二三四五六七八九十百千万亿0-9]+\s*[章节回话集幕篇]"),
    re.compile(r"^\s*No[、.．]\s*\d+\s*.+", re.M),
    re.compile(r"^\s*Chapter\s+\d+", re.M | re.I),
    re.compile(r"^\s*(序章|楔子|引子|前言|后记|番外)", re.M),
    re.compile(r"^\s*[0-9]+\s*[\.、]\s*.+", re.M),
    re.compile(r"^\s*[一二三四五六七八九十]+\s*[\.、]\s*.+", re.M),
]
MIN_CHARS, MAX_CHARS = 80, 50_000
# 仅当章节正文短于此值时才并入上一章（避免吞掉真实短章），默认不合并由调用方控制
MERGE_MIN_LEN = 20


def regex_bounds(text: str) -> list[tuple[int, str]]:
    """返回正则命中的 (字符偏移, 标题) 列表，已按偏移排序去重。"""
    return sorted(
        {(m.start(), m.group(0).strip()) for p in CHAPTER_PATTERNS for m in p.finditer(text)}
    )


def _is_volume(title: str) -> bool:
    return bool(re.match(r"第.+[卷部]", title))


def split_by_offsets(text: str, bounds: list[tuple[int, str]], merge: bool = False) -> list[dict]:
    """按 (偏移, 标题) 切分正文为章节；带卷/章层级。

    边界 (pos_i, title_i) 表示 title_i 在文本中的位置；title_i 的正文是
    [pos_i, pos_{i+1})，末章正文为 [pos_n, 文末)。

    ⚠️ **首个边界之前的内容（书名 / 作者行）会被丢弃**，不并入首章 ——
    这是实现的实际行为（首章 body 在下一轮循环里被 [pos_0, pos_1) 覆写）；
    此前注释写「作为前言并入首章正文」，与实现不符，第 55 期按实际行为订正。
    契约由 `tests/test_detect_chapters.py` 钉住（改它是改出版成品，别顺手改）。

    merge=True 时按 MERGE_MIN_LEN 合并极小碎片章。
    """
    chaps, start = [], 0
    for i, (pos, title) in enumerate(bounds):
        vol = title if _is_volume(title) else "正文"
        if i == 0:
            # 首个章节标题之前的内容（书名/作者等）作为首章前置，不单独成章
            chaps.append({"title": title, "body": text[:pos].strip(), "vol": vol})
        else:
            # 上一章（chaps[-1]）的正文 = 上一章标题位置到本章标题位置
            chaps[-1]["body"] = text[start:pos].strip()
            chaps.append({"title": title, "body": "", "vol": vol})
        start = pos
    # 末章正文 = 最后一个标题位置到文本末尾
    if chaps:
        chaps[-1]["body"] = text[start:].strip()
    return _merge_small(chaps) if merge else chaps


def detect_chapters(text: str, merge: bool = False) -> list[dict]:
    """章节识别：正则优先，命中率不足时退化为缩进切分。"""
    bounds = regex_bounds(text)
    if bounds and len(bounds) * 2000 >= len(text):  # 正则有效
        return split_by_offsets(text, bounds, merge)
    return _split_by_indent(text)  # 缩进降级


def detect_chapters_cfg(text: str, cfg: dict | None = None, merge: bool | None = None) -> list[dict]:
    """带配置的入口：hybrid/ai 且配置了 llm 时交由 AI 检测器，否则走正则。

    merge 控制是否合并极小碎片章；为 None 时默认不合并（由 CLI --merge 显式开启）。
    """
    cfg = cfg or {}
    cd = cfg.get("chapter_detection", {}) or {}
    mode = cd.get("mode", "hybrid")
    llm = cfg.get("llm", {}) or {}
    do_merge = bool(merge)
    if mode in ("ai", "hybrid") and llm.get("api_key"):
        from .ai_detect import HybridChapterDetector, _run_in_thread

        detector = HybridChapterDetector(cfg)
        # 在独立线程跑新事件循环，兼容 CLI（同步）与 Web 服务（已有运行中的 loop）；
        # 直接 asyncio.run 在事件中 loop 的线程会抛 RuntimeError，导致 AI 兜底静默失效。
        try:
            return _run_in_thread(detector.detect(text))
        except Exception:
            if cd.get("fallback", "regex") == "regex":
                return detect_chapters(text, do_merge)
            raise
    return detect_chapters(text, do_merge)


def _split_by_indent(text: str) -> list[dict]:
    chaps, cur = [], None
    for ln in text.splitlines():
        if ln[:1] in (" ", "\t") or not ln.strip():
            if cur is not None:
                cur["body"] += "\n" + ln
        else:
            if cur:
                chaps.append(cur)
            cur = {"title": ln.strip(), "body": "", "vol": "正文"}
    if cur:
        chaps.append(cur)
    for c in chaps:
        c["body"] = c["body"].strip()
    return chaps


def _merge_small(chaps: list[dict]) -> list[dict]:
    out = []
    for c in chaps:
        if out and len(c["body"]) < MERGE_MIN_LEN:
            out[-1]["body"] += "\n" + c["title"] + "\n" + c["body"]
        else:
            out.append(c)
    return out
