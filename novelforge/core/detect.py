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


def regex_bounds(text: str) -> list[tuple[int, str]]:
    """返回正则命中的 (字符偏移, 标题) 列表，已按偏移排序去重。"""
    return sorted(
        {(m.start(), m.group(0).strip()) for p in CHAPTER_PATTERNS for m in p.finditer(text)}
    )


def _is_volume(title: str) -> bool:
    return bool(re.match(r"第.+[卷部]", title))


def split_by_offsets(text: str, bounds: list[tuple[int, str]]) -> list[dict]:
    """按 (偏移, 标题) 切分正文为章节；带卷/章层级。"""
    chaps, prev = [], 0
    for pos, title in bounds:
        body = text[prev:pos].strip()
        prev = pos
        if len(body) >= MIN_CHARS or not chaps:
            vol = title if _is_volume(title) else "正文"
            chaps.append({"title": title, "body": body, "vol": vol})
    return _merge_small(chaps)


def detect_chapters(text: str) -> list[dict]:
    """章节识别：正则优先，命中率不足时退化为缩进切分。"""
    bounds = regex_bounds(text)
    if bounds and len(bounds) * 2000 >= len(text):  # 正则有效
        return split_by_offsets(text, bounds)
    return _split_by_indent(text)  # 缩进降级


def detect_chapters_cfg(text: str, cfg: dict | None = None) -> list[dict]:
    """带配置的入口：hybrid/ai 且配置了 llm 时交由 AI 检测器，否则走正则。"""
    cfg = cfg or {}
    cd = cfg.get("chapter_detection", {}) or {}
    mode = cd.get("mode", "hybrid")
    llm = cfg.get("llm", {}) or {}
    if mode in ("ai", "hybrid") and llm.get("api_key"):
        from .ai_detect import HybridChapterDetector

        detector = HybridChapterDetector(cfg)
        # 同步包装：AI 检测为 async，但转换管线多为同步调用，这里用简易事件循环
        try:
            import asyncio

            return asyncio.run(detector.detect(text))
        except Exception:
            if cd.get("fallback", "regex") == "regex":
                return detect_chapters(text)
            raise
    return detect_chapters(text)


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
        if out and len(c["body"]) < MIN_CHARS:
            out[-1]["body"] += "\n" + c["title"] + "\n" + c["body"]
        else:
            out.append(c)
    return out
