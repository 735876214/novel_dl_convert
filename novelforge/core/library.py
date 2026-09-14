"""书目库：扫描导出目录并聚合出工具页需要的真实数据。

后端没有「图书库」实体 —— 唯一的真实「书」就是 ``OUTPUT_DIR`` 里的成品文件。
所以这里以「扫目录 + 读元数据」的方式聚合出**书目 / 作者 / 系列**，并在此之上
做**重复分组**与**缺失检测**，供工具页的四个工具消费：

- 实体管理     → :func:`entities`
- 重复书籍     → :func:`duplicate_groups`
- 缺失资源     → :func:`missing_items`
- 批量重命名   → 只读 :func:`books`，改名逻辑在 ``fileops``

EPUB 解析是 IO 密集（要解开 zip 读 OPF），因此扫描结果做进程内短期缓存：
TTL + 目录指纹（文件数 + 最新 mtime）双重判定；任何写操作后调用
:func:`invalidate` 立即失效，保证下一个请求读到新状态。
"""
from __future__ import annotations

import pathlib
import re
import threading
import time
import zipfile

from .. import config
from . import metadata

# 只把这些扩展名当成「书」；与 /api/files 的全量列表不同，这里是有意收窄的
BOOK_EXTS = (".epub", ".mobi", ".azw3", ".pdf", ".txt")

_CACHE_TTL = 5.0

_lock = threading.RLock()
_cache = {"at": 0.0, "sig": None, "books": []}

# 文件名噪声：括号里的版本说明 + 空白/连字符
_NOISE_RE = re.compile(r"[（(][^）)]*(?:校对|全本|完结|精校|未删减|典藏|合集)[^）)]*[）)]|[\s\-_·]+")
# 标点：归一化时全部去掉，避免《书名》与 书名 被判成两本
_PUNCT_RE = re.compile(r"[《》【】\[\]()（）:：·,，.。!！?？'\"“”‘’]")


# ---------------- 归一化 ----------------

def norm_key(text: str) -> str:
    """归一化书名 / 作者，用于重复判定（大小写、标点、版本后缀都不影响结果）。"""
    t = (text or "").lower()
    t = _NOISE_RE.sub("", t)
    t = _PUNCT_RE.sub("", t)
    return t.strip()


# ---------------- EPUB 探测 ----------------

def _tag_text(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S | re.I)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def _series_of(opf: str) -> str:
    """系列名：兼容 calibre 与 EPUB3 的两种写法。"""
    for pat in (
        r'<meta[^>]+name="calibre:series"[^>]+content="([^"]*)"',
        r'<meta[^>]+content="([^"]*)"[^>]+name="calibre:series"',
        r'<meta[^>]+property="belongs-to-collection"[^>]*>(.*?)</meta>',
    ):
        m = re.search(pat, opf, re.S | re.I)
        if m:
            v = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if v:
                return v
    return ""


def _has_cover(opf: str, z: zipfile.ZipFile) -> bool:
    if re.search(r'properties="[^"]*cover-image', opf, re.I):
        return True
    if re.search(r'name="cover"', opf, re.I):
        return True
    return any("cover" in n.lower() for n in z.namelist())


def probe_epub(path: pathlib.Path) -> dict:
    """读 EPUB 容器内的 OPF，取书名 / 作者 / 系列，并判断有没有封面。

    任何失败都**不抛异常**，而是折算成 ``issues`` 里的 ``unparsable`` ——
    这个函数同时是「缺失资源」工具的判定依据，必须容错。
    """
    out = {"title": "", "author": "", "series": "", "has_cover": False, "unparsable": False}
    try:
        with zipfile.ZipFile(path) as z:
            opf_path = ""
            try:
                container = z.read("META-INF/container.xml").decode("utf-8", "ignore")
                m = re.search(r'full-path="([^"]+)"', container)
                if m:
                    opf_path = m.group(1)
            except Exception:
                opf_path = ""
            if not opf_path:
                names = [n for n in z.namelist() if n.lower().endswith(".opf")]
                if not names:
                    out["unparsable"] = True
                    return out
                opf_path = names[0]
            opf = z.read(opf_path).decode("utf-8", "ignore")
            out["title"] = _tag_text(opf, "dc:title")
            out["author"] = _tag_text(opf, "dc:creator")
            out["series"] = _series_of(opf)
            out["has_cover"] = _has_cover(opf, z)
    except Exception:
        out["unparsable"] = True
    return out


# ---------------- 扫描 ----------------

def _dir_signature(d: pathlib.Path) -> tuple:
    """目录指纹：文件数 + 最新 mtime。任一变化即让缓存失效。"""
    n, newest = 0, 0.0
    try:
        for f in d.iterdir():
            if not f.is_file():
                continue
            n += 1
            try:
                m = f.stat().st_mtime
                if m > newest:
                    newest = m
            except OSError:
                pass
    except Exception:
        return (0, 0.0)
    return (n, round(newest, 3))


def _scan_once() -> list:
    d = config.OUTPUT_DIR
    books = []
    try:
        entries = sorted(d.iterdir())
    except Exception:
        return books

    for f in entries:
        if not f.is_file() or f.suffix.lower() not in BOOK_EXTS:
            continue
        try:
            st = f.stat()
        except OSError:
            continue

        name_meta = metadata.from_filename(f.name)
        info = {"title": "", "author": "", "series": "", "has_cover": False, "unparsable": False}
        if f.suffix.lower() == ".epub":
            info = probe_epub(f)

        issues = []
        if st.st_size == 0:
            issues.append("zero-bytes")
        if info["unparsable"]:
            issues.append("unparsable")
        elif not info["has_cover"] and f.suffix.lower() == ".epub":
            issues.append("no-cover")
        elif f.suffix.lower() != ".epub":
            # 非 EPUB（mobi/pdf/txt）本项目不会去解析封面，不计为缺失
            pass

        books.append({
            "name": f.name,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "format": f.suffix.lstrip(".").upper(),
            "title": info["title"] or name_meta["title"],
            "author": info["author"] or name_meta["author"],
            "series": info["series"],
            "has_cover": info["has_cover"],
            "issues": issues,
        })
    return books


def books(force: bool = False) -> list:
    """导出目录里的书目列表（带短期缓存）。"""
    d = config.OUTPUT_DIR
    sig = _dir_signature(d)
    with _lock:
        fresh = _cache["sig"] == sig and (time.time() - _cache["at"]) < _CACHE_TTL
        if fresh and not force:
            return _cache["books"]

    result = _scan_once()
    with _lock:
        _cache.update({"at": time.time(), "sig": sig, "books": result})
    return result


def invalidate() -> None:
    """让缓存立即失效（任何改文件的操作之后都要调）。"""
    with _lock:
        _cache.update({"at": 0.0, "sig": None, "books": []})


def find(name: str) -> dict | None:
    for b in books():
        if b["name"] == name:
            return b
    return None


# ---------------- 聚合 ----------------

def entities(kind: str) -> dict:
    """按作者或系列聚合：``{type, items: [{name, count, books}]}``。"""
    field = "author" if kind == "author" else "series"
    bucket: dict = {}
    for b in books():
        key = (b.get(field) or "").strip()
        if not key:
            continue
        bucket.setdefault(key, []).append(b["name"])
    items = [
        {"name": k, "count": len(v), "books": v}
        for k, v in sorted(bucket.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    return {"type": kind, "items": items, "total": len(books())}


def duplicate_groups() -> dict:
    """按「归一化书名 + 归一化作者」分组，返回 2 个及以上的组。"""
    bucket: dict = {}
    for b in books():
        key = f"{norm_key(b['title'])}|{norm_key(b['author'])}"
        if not key.strip("|"):
            continue
        bucket.setdefault(key, []).append(b)

    groups = []
    for key, items in bucket.items():
        if len(items) < 2:
            continue
        groups.append({
            "key": key,
            "reason": "归一化后的书名与作者相同",
            "title": items[0]["title"],
            "author": items[0]["author"],
            "items": [
                {"name": i["name"], "size": i["size"], "mtime": i["mtime"], "format": i["format"]}
                for i in items
            ],
        })
    groups.sort(key=lambda g: -len(g["items"]))
    return {"groups": groups, "total": len(books())}


def missing_items() -> dict:
    """有问题的条目：零字节 / 无法解析 / 缺封面。"""
    items = [
        {"name": b["name"], "size": b["size"], "mtime": b["mtime"], "issues": b["issues"]}
        for b in books() if b["issues"]
    ]
    return {"items": items, "total": len(books())}
