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


def detect_chapters(text: str) -> list:
    """章节识别：正则优先，命中率不足时退化为缩进切分。"""
    hits = sorted(
        {(m.start(), m.group(0).strip())
         for p in CHAPTER_PATTERNS for m in p.finditer(text)}
    )
    if hits and len(hits) * 2000 >= len(text):  # 正则有效
        chaps, prev = [], 0
        for pos, title in hits:
            body = text[prev:pos].strip()
            prev = pos
            if len(body) >= MIN_CHARS or not chaps:
                vol = title if re.match(r"第.+[卷部]", title) else "正文"
                chaps.append({"title": title, "body": body, "vol": vol})
        return _merge_small(chaps)
    return _split_by_indent(text)  # 缩进降级


def _split_by_indent(text: str) -> list:
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


def _merge_small(chaps: list) -> list:
    out = []
    for c in chaps:
        if out and len(c["body"]) < MIN_CHARS:
            out[-1]["body"] += "\n" + c["title"] + "\n" + c["body"]
        else:
            out.append(c)
    return out
