"""EPUB 书内全文搜索（第 189 期）—— 搜索判据的唯一实现。

输入是书文件（只读），输出是「哪一章、第几个字符起、上下文」。
不做索引、不落库：单本书的章节数在几百量级，需求又是用户显式点搜索；
为它建一套全文索引等于引入第二个真值源（索引与书文件不同步时搜不到新正文）。
"""
from __future__ import annotations

import html as _html
import pathlib
import re
import zipfile

from . import library

#: 单个章节最多读这么多字节（超过的畸形章节跳过，不把一次搜索拖成分钟级）。
MAX_CHAPTER_BYTES = 4 * 1024 * 1024
#: 命中上下文：前后各留这些字符
SNIPPET_BEFORE = 60
SNIPPET_AFTER = 100
MAX_RESULTS = 200

_TAG_RE = re.compile(r"<(script|style)\b.*?</\1\s*>|<[^>]+>", re.S | re.I)
_WS_RE = re.compile(r"\s+")


def plain_text(raw_html: str) -> str:
    """HTML → 纯文本（去掉 script / style / 标签与实体，折叠空白）。"""
    text = _TAG_RE.sub(" ", raw_html or "")
    text = _html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _titles(path: pathlib.Path) -> dict:
    out = {}
    for group in library._reading_list(path):
        for ch in group.get("chapters") or []:
            out[int(ch.get("index", -1))] = str(ch.get("title") or "")
    return out


def search_epub(path, query: str, limit: int = 50) -> dict:
    """在一本 EPUB 里搜 substring（大小写不敏感），返回命中章节 + 上下文。

    `limit` 控制**命中条数**；每章只返回第一条命中（同一章反复命中对定位没有增益）。
    """
    p = pathlib.Path(path)
    q = str(query or "").strip()
    if not q:
        raise ValueError("搜索词不能为空")
    if p.suffix.lower() != ".epub":
        raise ValueError("书内搜索目前只支持 EPUB")
    limit = max(1, min(int(limit or 50), MAX_RESULTS))
    needle = q.lower()
    spine = library._spine(p)
    titles = _titles(p)
    items: list = []
    truncated = False
    scanned = 0
    try:
        z = zipfile.ZipFile(p)
    except (OSError, zipfile.BadZipFile):
        raise ValueError("不是有效的 EPUB（zip）") from None
    with z:
        names = set(z.namelist())
        for i, href in enumerate(spine):
            if href not in names:
                continue
            try:
                info = z.getinfo(href)
                if info.file_size > MAX_CHAPTER_BYTES:
                    continue
                text = plain_text(z.read(href).decode("utf-8", "ignore"))
            except (KeyError, OSError, zipfile.BadZipFile):
                continue
            scanned += 1
            pos = text.lower().find(needle)
            if pos < 0:
                continue
            start = max(0, pos - SNIPPET_BEFORE)
            end = min(len(text), pos + len(q) + SNIPPET_AFTER)
            items.append({
                "chapter_index": i,
                "title": titles.get(i, ""),
                "snippet": text[start:end],
                "offset": pos,
                "match": text[pos:pos + len(q)],
            })
            if len(items) >= limit:
                truncated = True
                break
    return {
        "items": items,
        "total": len(items),
        "truncated": truncated,
        "scanned": scanned,
        "query": q,
    }
