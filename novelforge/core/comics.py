"""漫画（CBZ）：页清单 / 单页取图 / 封面探测。

**只支持 CBZ**（CBZ 就是普通 zip，标准库直接解）。**刻意不支持 CBR / RAR** ——
RAR 需要额外的二进制依赖（unrar / rarfile），为单一格式引入一个系统级依赖不划算。
因此 `.cbr` 不进 `library.BOOK_EXTS`：宁可不显示，也不放一本永远打不开的书进书架。

两个必须处理的现实问题：
- macOS 压缩会塞进 `__MACOSX/` 与 `.DS_Store`，不过滤的话漫画里会混进垃圾「页」；
- 页序必须**自然排序**（page2 < page10），字典序会把 page10 排到 page2 前面。
"""
import pathlib
import re
import zipfile

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif"}
_JUNK_PARTS = ("__MACOSX/", ".DS_Store", "Thumbs.db", ".thumbnails/")


def is_cbz(path) -> bool:
    return pathlib.PurePath(str(path)).suffix.lower() == ".cbz"


def _natural_key(name: str) -> list:
    """把文件名切成「文字段 / 数字段」再比较，使 page2 < page10。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _entries(z: zipfile.ZipFile) -> list:
    """zip 内的图片条目名（过滤垃圾、目录项与非图片），自然排序。"""
    out = []
    for info in z.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if any(j in name for j in _JUNK_PARTS):
            continue
        if pathlib.PurePath(name).name.startswith("."):
            continue
        if pathlib.PurePath(name).suffix.lower() not in IMAGE_EXTS:
            continue
        out.append(name)
    out.sort(key=_natural_key)
    return out


def _open(path):
    return zipfile.ZipFile(path)


def probe(path) -> dict:
    """书目扫描用：页数 / 是否有封面 / 封面条目。坏包折算成 unparsable（与 EPUB 同口径）。"""
    out = {"has_cover": False, "cover": "", "pages": 0, "pages_source": "archive", "unparsable": False}
    try:
        with _open(path) as z:
            names = _entries(z)
            out["pages"] = len(names)
            if names:
                out["has_cover"] = True
                out["cover"] = names[0]
    except Exception:
        out["unparsable"] = True
        out["pages_source"] = ""
    return out


def pages(path) -> dict:
    """页清单。index 是**序号**（0 起），不是 zip 内的名字 —— 前端按序号取图。"""
    try:
        with _open(path) as z:
            infos = {i.filename: i for i in z.infolist()}
            names = _entries(z)
    except Exception:
        return {"pages": [], "total": 0}
    return {
        "pages": [
            {"index": i, "name": n, "size": infos[n].file_size if n in infos else 0}
            for i, n in enumerate(names)
        ],
        "total": len(names),
    }


def page_bytes(path, index: int):
    """取第 index 页的原始字节 + media type；越界 / 坏包返回 (None, "")。"""
    import mimetypes

    try:
        with _open(path) as z:
            names = _entries(z)
            if not (0 <= index < len(names)):
                return (None, "")
            name = names[index]
            data = z.read(name)
    except Exception:
        return (None, "")
    media = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return (data, media)


def cover_entry(path) -> str:
    """第一页的条目名（封面用它）；没有图片返回空串。"""
    try:
        with _open(path) as z:
            names = _entries(z)
            return names[0] if names else ""
    except Exception:
        return ""
