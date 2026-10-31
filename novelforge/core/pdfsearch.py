"""PDF 大纲与文内搜索（第 195 期）—— PDF 读取判据的唯一实现。

用 pypdfium2（与 `core/pdfrender.py` 同一个依赖）；缺它时如实报「服务器缺少 PDF
解析能力」，不假装能搜。只读，不写任何文件。
"""
from __future__ import annotations

import re

#: 搜索结果上下文与上限
SNIPPET_BEFORE = 60
SNIPPET_AFTER = 100
MAX_RESULTS = 200
MAX_PAGE_CHARS = 2_000_000

_WS_RE = re.compile(r"\s+")


def _pdfium():
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415 —— 惰性导入：没这依赖时只有本功能不可用
        return pdfium
    except ImportError:
        raise ValueError("服务器缺少 PDF 解析能力（需 pypdfium2）") from None


def _snippet(text: str, pos: int, n: int) -> str:
    return text[max(0, pos - SNIPPET_BEFORE):min(len(text), pos + n + SNIPPET_AFTER)]


def outline(path) -> list:
    """PDF 大纲（书签树拍平）：`{title, page(1 基；0=没有页码目标), level}`。"""
    pdfium = _pdfium()
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception as e:  # noqa: BLE001 —— 坏 PDF / 加密，统一成可读中文
        raise ValueError(f"PDF 打不开：{e}") from None
    out: list = []
    try:
        try:
            toc = doc.get_toc()
        except Exception:  # noqa: BLE001 —— 没有大纲在 PDFium 里也可能抛
            toc = []
        for b in toc:
            page = 0
            try:
                page = int(b.get_dest().get_index()) + 1
            except Exception:  # noqa: BLE001 —— 非页目标（URI / 命名目标）没有页码
                page = 0
            try:
                title = str(b.get_title() or "").strip()
            except Exception:  # noqa: BLE001
                title = ""
            if title:
                out.append({"title": title, "page": page, "level": int(getattr(b, "level", 0) or 0)})
    finally:
        doc.close()
    return out


def search(path, query: str, limit: int = 100) -> dict:
    """PDF 文内搜索（按页返回第一条命中 + 上下文）。"""
    pdfium = _pdfium()
    q = str(query or "").strip()
    if not q:
        raise ValueError("搜索词不能为空")
    limit = max(1, min(int(limit or 100), MAX_RESULTS))
    needle = q.lower()
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"PDF 打不开：{e}") from None
    items: list = []
    truncated = False
    scanned = 0
    try:
        for i in range(len(doc)):
            page = doc.get_page(i)
            textpage = None
            try:
                textpage = page.get_textpage()
                text = str(textpage.get_text_range() or "")
            except Exception:  # noqa: BLE001 —— 扫描版 / 坏页：跳过，不编造文字
                text = ""
            finally:
                if textpage is not None:
                    try:
                        textpage.close()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
            scanned += 1
            text = _WS_RE.sub(" ", text[:MAX_PAGE_CHARS])
            pos = text.lower().find(needle)
            if pos < 0:
                continue
            items.append({
                "page": i + 1,
                "snippet": _snippet(text, pos, len(q)),
                "offset": pos,
                "match": text[pos:pos + len(q)],
            })
            if len(items) >= limit:
                truncated = True
                break
    finally:
        doc.close()
    return {"items": items, "total": len(items), "truncated": truncated,
            "scanned": scanned, "query": q}
