"""PDF 页面渲染（给 Komga 客户端用）。

Komga 客户端读 PDF 是**逐页取图**（`/books/{id}/pages/{n}`），而不是下载 PDF 文件本身，
所以服务端得把页渲染成图片。用 pypdfium2（PDFium 的 Python 绑定，pip 装、**无需系统库**）。

实测（600×900 的 PDF、`scale=2`）：单页渲染约 **15ms** —— 已经够快，但仍做**磁盘缓存**：
逐页翻的时候没必要重复渲染，而且高倍率（retina）下开销才会真正显现。

缓存落在 ``CACHE_DIR/pdf/<book_id>/<page>_<scale>.jpg``：

- 文件名带倍率 → 改了配置不会读到旧图
- 随 `CACHE_DIR` 一起被维护页清理，不额外引入一套清理逻辑
"""
import io
import pathlib

from .. import config          # ⚠️ config 在上一级（novelforge/），不在 core/ 里

#: 默认 2× 渲染：高分屏上才不糊（1× 在手机上明显发虚）
DEFAULT_SCALE = 2.0
JPEG_QUALITY = 82
_CACHE_SUBDIR = "pdf"


def _cache_path(bid: str, index: int, scale: float) -> pathlib.Path:
    safe_scale = str(round(float(scale), 2)).replace(".", "_")
    return config.CACHE_DIR / _CACHE_SUBDIR / str(bid) / f"{int(index)}_{safe_scale}.jpg"


def page_count(path) -> int:
    """页数。Komga 的 `pagesCount` 用它 —— 本项目扫描书目时不解析 PDF 页数，故按需算。"""
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception:
        return 0
    try:
        return len(doc)
    finally:
        doc.close()


def render_page(path, index: int, bid: str, scale: float = DEFAULT_SCALE) -> tuple:
    """渲染指定页 → ``(jpeg 字节, (width, height))``；越界或损坏返回 ``(None, None)``。"""
    try:
        index = int(index)
    except (TypeError, ValueError):
        return (None, None)
    if index < 0:
        return (None, None)

    cache = _cache_path(bid, index, scale)
    if cache.is_file():
        try:
            from PIL import Image
            with Image.open(cache) as im:
                return (cache.read_bytes(), im.size)
        except Exception:
            pass                      # 缓存坏了就当没有，重渲染

    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception:
        return (None, None)
    try:
        if index >= len(doc):
            return (None, None)
        bitmap = doc[index].render(scale=float(scale))
        img = bitmap.to_pil()
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_QUALITY)
        data, size = buf.getvalue(), img.size
    except Exception:
        return (None, None)
    finally:
        try:
            doc.close()
        except Exception:
            pass

    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    except Exception:
        pass                          # 缓存写不了不影响本次返回
    return (data, size)


def page_sizes(path, count: int, scale: float = DEFAULT_SCALE) -> list:
    """各页渲染后的像素尺寸（DTO 里的 `width` / `height`）。

    `get_size()` 只读页面框、**不渲染**，所以一次算完整份清单很便宜。
    """
    import pypdfium2 as pdfium
    out: list = []
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception:
        return [(0, 0)] * max(0, int(count))
    try:
        for i in range(min(int(count), len(doc))):
            try:
                w, h = doc[i].get_size()
                out.append((int(w * scale), int(h * scale)))
            except Exception:
                out.append((0, 0))
    finally:
        doc.close()
    while len(out) < int(count):
        out.append((0, 0))
    return out
