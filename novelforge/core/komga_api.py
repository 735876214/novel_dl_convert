"""Komga v1 兼容 API 的协议层：DTO / 分页壳 / 认证 / 阅读进度映射。

**目标**：让第三方 Komga 客户端（Mihon/Tachiyomi、Panels、Komga 官方 App 等）
把服务器地址填成本应用，就能浏览书库、读漫画/EPUB/PDF、推拉阅读进度 ——
用户不需要装 Komga，也不需要开发任何客户端。

## 与 `core/komga.py` 的区别（别搞混）
- `komga.py`：**输出侧布局** —— 让产物落成 Komga 能扫成系列的结构（本应用是「生产方」）
- 本模块：**冒充 Komga 服务端** —— 对外提供 v1 API（本应用是「服务方」）

## 协议要点（逐条对齐官方文档与 gotson/komga 源码索引）
- 前缀 `/api/v1`；认证三选一：**HTTP Basic** / **`X-API-Key` 头** / 会话 cookie
- 客户端第一步都是 `GET /api/v1/libraries`
- 列表返回 **Spring Data 分页壳**（`content/totalElements/totalPages/size/number/first/last/empty`），
  不是裸数组 —— 客户端解析的就是这个结构
- 分页参数 `page` **从 0 起**、`size`；排序 `sort=field,asc`
- ⚠️ `GET /api/v1/series` 与 `GET /api/v1/books` 在 Komga 1.19.0 已弃用（改用 `POST .../list`），
  但**老客户端仍在用**（Mihon 就是），所以两套都得提供
- 阅读进度：`PUT /api/v1/books/{id}/read-progress` → **204**（`completed: true` 时忽略页码）

## 映射（本项目 → Komga）
- **库**：只有 OUTPUT_DIR 一个库，id 固定 —— 客户端只透传它
- **系列**：按 `books()` 的 `series` 字段分组；没有系列的书**各自成为单本系列**
  （Komga 里每本书都必须属于某个系列，用书名当系列名最自然）
- **书**：`bookId` 直接复用本项目的 id（sha1(basename)[:12]）—— 不做二次映射，
  这样客户端拿到的 id 能直接用于本应用既有的 `/api/books/{bid}/...` 接口，少一层转换
- **进度**：漫画/PDF 用页码，EPUB 用 locator（href + progression），见 :func:`apply_read_progress`
"""
import datetime
import hashlib
import hmac
import os
import pathlib
from urllib.parse import unquote

from .. import config          # ⚠️ config 在上一级（novelforge/），不在 core/ 里
from . import auth as auth_mod
from . import db, library
from .library import norm_key

#: 库 id / 名字的**兜底**常量：多书库后真实值来自 ``libraries`` 表，
#: 只在拿不到库实体时使用（例如库表为空的老部署）。
LIBRARY_ID = "novelforge"
LIBRARY_NAME = "NovelForge"
#: 会话 cookie（Komga 官方 Web 用这个；第三方 App 多数直接用 Basic）
SESSION_COOKIE = "KOMGA-SESSION"
#: 会话签名密钥：复用部署时已有的 AUTH_SECRET，不新增配置项
_SESSION_SECRET = (os.getenv("AUTH_SECRET") or "novelforge-komga").encode()

#: 格式 → Komga 客户端要的媒体类型
MEDIA_TYPES = {
    "EPUB": "application/epub+zip", "PDF": "application/pdf",
    "CBZ": "application/vnd.comicbook+zip", "MOBI": "application/x-mobipocket-ebook",
    "AZW3": "application/x-mobipocket-ebook", "TXT": "text/plain",
}
#: Komga 用 mediaProfile 决定阅读器：漫画类走 DIVINA，EPUB 走 EPUB，PDF 走 PDF
_PROFILES = {"EPUB": "EPUB", "PDF": "PDF", "CBZ": "DIVINA"}


class KomgaAuthError(Exception):
    """凭据无效（调用方转成 401 + WWW-Authenticate）。"""


def _fmt() -> str:
    return "%Y-%m-%dT%H:%M:%SZ"


def iso(ts) -> str:
    """Komga 全是 ISO-8601 UTC 时间串（客户端直接展示，不做本地化）。"""
    try:
        return datetime.datetime.fromtimestamp(
            float(ts or 0), datetime.timezone.utc).strftime(_fmt())
    except (TypeError, ValueError, OSError):
        return datetime.datetime.now(datetime.timezone.utc).strftime(_fmt())


def _day(value) -> str:
    """出版日期：Komga 要 ``YYYY-MM-DD``；只有年份时补成 ``YYYY-01-01``。"""
    s = str(value or "").strip()
    if not s:
        return ""
    if len(s) == 4 and s.isdigit():
        return f"{s}-01-01"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            return datetime.datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s[:10] if len(s) >= 10 else ""


# ---------------- 认证 ----------------

def session_token(user: str) -> str:
    """会话 token = 对用户名的 HMAC（无状态：服务端不存会话表）。"""
    return hmac.new(_SESSION_SECRET, user.encode(), hashlib.sha256).hexdigest()


def _session_user(token: str) -> str:
    cfg = (config.load_config().get("komga") or {})
    user = str(cfg.get("username") or "admin")
    return user if token and hmac.compare_digest(token, session_token(user)) else ""


def verify(request) -> str:
    """校验凭据，返回身份标识；失败抛 :class:`KomgaAuthError`。

    三种方式（与 Komga 一致），任何一种通过即可：

    1. ``X-API-Key`` 头 —— 需在设置页填写 API Key 才有
    2. ``HTTP Basic`` —— 用**应用账号**（用户名 + 登录 PIN），与 OPDS 同一套凭据
    3. ``KOMGA-SESSION`` cookie —— 供官方 Web 那类会走登录流程的客户端
    """
    cfg = (config.load_config().get("komga") or {})
    if not cfg.get("enabled"):
        # 未启用 → 调用方应回 404（401 会让客户端反复重试并弹密码框）
        raise KomgaAuthError("disabled")

    key = (request.headers.get("x-api-key") or "").strip()
    expected = str(cfg.get("api_key") or "").strip()
    if key and expected and hmac.compare_digest(key, expected):
        return "apikey"

    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("basic "):
        import base64
        try:
            raw = base64.b64decode(auth[6:].strip()).decode("utf-8", "replace")
            user, _, pin = raw.partition(":")
        except Exception:
            user, pin = "", ""
        want_user = str(cfg.get("username") or "admin")
        if user == want_user and pin and auth_mod.verify_pin(user, pin):
            return user

    tok = request.cookies.get(SESSION_COOKIE) or ""
    user = _session_user(tok)
    if user:
        return user
    raise KomgaAuthError("invalid")


# ---------------- 库 / 系列 / 书 的 DTO ----------------

def library_dto(lib: dict = None) -> dict:
    """LibraryDto（**每库一份**）。

    多书库后 id / name / root 都来自库实体；不传则用默认库（兼容既有单库调用方）。
    客户端多数只读 id/name，但字段缺失会让某些实现直接崩 —— 一律给全。
    """
    lib = lib or library.default_library()
    root = str(lib.get("root_path") or library.root_of(lib.get("id")))
    return {
        "id": lib.get("id") or LIBRARY_ID, "name": lib.get("name") or LIBRARY_NAME, "root": root,
        "importComicInfoBook": False, "importComicInfoSeries": False,
        "importComicInfoCollection": False, "importComicInfoReadList": False,
        "importComicInfoSeriesAppendVolume": False,
        "importEpubBook": False, "importEpubSeries": False,
        "importMylarSeries": False, "importLocalArtwork": False,
        "importBarcodeIsbn": False, "scanForceModifiedTime": False,
        "scanInterval": "DISABLED", "scanOnStartup": False, "scanCbx": True,
        "scanPdf": True, "scanEpub": True, "scanDirectoryExclusions": [],
        "repairExtensions": False, "convertToCbz": False,
        "emptyTrashAfterScan": False, "seriesCover": "FIRST",
        "hashFiles": False, "hashPages": False, "hashKoreader": False,
        "oneshotsDirectory": "", "unavailable": False,
    }


def book_library_id(b: dict) -> str:
    """书归属的**真实**库 id —— 必须与 ``/api/v1/libraries`` 返回的 id 一致。

    书目自带 ``library_id``（扫描时写入，见 core/library.py）。缺失时回退**默认库 id**
    而非 :data:`LIBRARY_ID` 常量：后者只用于兜底展示，若拿它当归属，客户端点进任一库
    都会得到空列表（id 对不上）。
    """
    return str((b or {}).get("library_id") or library.DEFAULT_LIBRARY_ID)


def series_name_of(b: dict) -> str:
    """书归属的系列名：没有系列就**用书名**（Komga 里每本书都属于某个系列）。"""
    s = str(b.get("series") or "").strip()
    return s or str(b.get("title") or pathlib.PurePosixPath(str(b.get("name") or "")).stem or "未命名")


def series_id(name: str) -> str:
    """系列 id：系列名的稳定哈希（客户端只透传；反查靠遍历书库，量小）。"""
    return "s" + hashlib.sha1(norm_key(name).encode("utf-8")).hexdigest()[:15]


def grouped() -> dict:
    """``{系列名: [书…]}``，系列内按卷号/书名排序。"""
    out: dict = {}
    for b in library.books():
        out.setdefault(series_name_of(b), []).append(b)
    for name, items in out.items():
        def key(b, _n=name):
            try:
                return (float(str(b.get("series_index") or "").strip() or 1e9), str(b.get("title") or ""))
            except ValueError:
                return (1e9, str(b.get("title") or ""))
        items.sort(key=key)
    return out


def find_series(name: str):
    """按 id 或名字找系列 → ``(名字, [书…])``；找不到返回 ``None``。"""
    for sname, items in grouped().items():
        if sname == name or series_id(sname) == name:
            return (sname, items)
    return None


def series_dto(name: str, items: list) -> dict:
    """SeriesDto。读完/在读计数客户端会显示，所以要认真算（按 percent 判定）。"""
    progs = {b["id"]: (db.get_progress(b["id"]) or {}) for b in items}
    read = sum(1 for p in progs.values() if float(p.get("percent") or 0) >= 99.5)
    inprog = sum(1 for p in progs.values() if 0 < float(p.get("percent") or 0) < 99.5)
    latest = max([b.get("mtime") or 0 for b in items] or [0])
    first = items[0] if items else {}
    return {
        # 系列按名字跨库聚合，若同名系列的书分散在多库，归属取**第一本**所在库
        # （Komga 的 SeriesDto 只允许一个 libraryId；给空会让客户端整页失败）
        "id": series_id(name), "libraryId": book_library_id(first), "name": name,
        "url": "", "created": iso(latest), "lastModified": iso(latest),
        "fileLastModified": iso(latest),
        "booksCount": len(items), "booksReadCount": read,
        "booksUnreadCount": len(items) - read - inprog, "booksInProgressCount": inprog,
        "metadata": {
            "title": name, "titleLock": False, "summary": "", "summaryLock": False,
            "publisher": str(first.get("publisher") or ""), "publisherLock": False,
            "readingDirection": "LEFT_TO_RIGHT", "readingDirectionLock": False,
            "ageRating": None, "ageRatingLock": False,
            "language": str(first.get("language") or ""), "languageLock": False,
            "genres": list({t for b in items for t in (b.get("tags") or [])})[:10],
            "genresLock": False, "tags": [], "tagsLock": False,
            "totalBookCount": len(items), "totalBookCountLock": False,
            "sharingLabels": [], "sharingLabelsLock": False,
            "links": [], "linksLock": False,
        },
        "booksMetadata": {"authors": [], "tags": [], "releaseDate": None,
                          "summary": "", "summaryNumber": ""},
        "deleted": False, "oneshot": len(items) == 1,
    }


def book_dto(b: dict, series_name: str = "") -> dict:
    """BookDto —— 客户端依赖最多的结构，字段名必须逐字对齐。"""
    fmt = str(b.get("format") or "").upper()
    prog = db.get_progress(b["id"]) or {}
    pages = int(b.get("pages") or 0)
    if not pages and fmt == "PDF":
        # 本项目扫描书目时**不解析 PDF 页数**（避免扫描期就打开每个 PDF）；
        # 而 Komga 客户端要靠 pagesCount 渲染阅读器，所以在这里单本实时算。
        try:
            from . import pdfrender
            pages = pdfrender.page_count(library.root_of(b) / str(b.get("name") or ""))
        except Exception:
            pages = 0
    sname = series_name or series_name_of(b)
    try:
        number = int(str(b.get("series_index") or "").strip() or 1)
    except ValueError:
        number = 1
    return {
        "id": b["id"], "seriesId": series_id(sname), "seriesTitle": sname,
        "libraryId": book_library_id(b),
        "name": pathlib.PurePosixPath(str(b.get("name") or "")).name,
        "url": "", "number": number,
        "created": iso(b.get("mtime")), "lastModified": iso(b.get("mtime")),
        "fileLastModified": iso(b.get("mtime")), "sizeBytes": int(b.get("size") or 0),
        "media": {
            "status": "READY", "mediaType": MEDIA_TYPES.get(fmt, "application/octet-stream"),
            "pagesCount": pages, "comment": "",
            "mediaProfile": _PROFILES.get(fmt, "DIVINA"),
            "epubDivinaCompatible": fmt == "EPUB",
            "epubIsKepub": False, "kepubDivinaCompatible": False,
        },
        "metadata": {
            "title": str(b.get("title") or ""), "titleLock": False,
            "summary": str(b.get("description") or ""), "summaryLock": False,
            "number": str(number), "numberLock": False,
            "numberSort": float(number), "numberSortLock": False,
            "releaseDate": _day(b.get("year")) or None, "releaseDateLock": False,
            "authors": ([{"name": str(b["author"]), "role": "writer"}] if b.get("author") else []),
            "authorsLock": False,
            "tags": list(b.get("tags") or []), "tagsLock": False,
            "isbn": str(b.get("isbn") or ""), "isbnLock": False,
            "links": [], "linksLock": False,
        },
        "readProgress": read_progress_dto(b, prog),
        "deleted": False,
        "fileHash": "", "oneshot": False,
    }


# ---------------- 分页壳 ----------------

def paginate(items: list, page=0, size=20) -> dict:
    """Spring Data 风格分页壳 —— 客户端解析的是这个结构，**不是裸数组**。"""
    try:
        page = max(0, int(page))
    except (TypeError, ValueError):
        page = 0
    try:
        size = max(1, min(int(size), 500))
    except (TypeError, ValueError):
        size = 20
    total = len(items)
    pages = max(1, (total + size - 1) // size)
    page = min(page, pages - 1)
    chunk = items[page * size:(page + 1) * size]
    return {
        "content": chunk, "totalElements": total, "totalPages": pages,
        "size": size, "number": page, "numberOfElements": len(chunk),
        "first": page == 0, "last": page >= pages - 1, "empty": not chunk,
        "pageable": {
            "pageNumber": page, "pageSize": size, "offset": page * size,
            "paged": True, "unpaged": False,
            "sort": {"sorted": False, "unsorted": True, "empty": True},
        },
    }


# ---------------- 阅读进度（双向映射）----------------
# 本项目：progress(book_id, locator, percent)，其中
#   · 漫画 / PDF：locator = 页码 - 1（0 起）
#   · EPUB：locator = 章节 index（0 起）
# Komga：漫画/PDF 用 `page`（**1 起**），EPUB 用 `locator{href, locations.progression}`。

def _is_paged(b: dict) -> bool:
    return str(b.get("format") or "").upper() in ("CBZ", "PDF")


def read_progress_dto(b: dict, prog: dict) -> dict:
    """本项目进度 → Komga 的 readProgress（客户端据此显示「读到第几页/百分之多少」）。"""
    percent = float((prog or {}).get("percent") or 0)
    locator = int((prog or {}).get("locator") or 0)
    updated = (prog or {}).get("updated_at") or 0
    out = {
        "completed": percent >= 99.5,
        "readDate": iso(updated) if updated else None,
        "lastModified": iso(updated) if updated else None,
    }
    if _is_paged(b):
        out["page"] = locator + 1          # Komga 的页码从 1 起
    else:
        href = _spine_href(b, locator)
        out["locator"] = {
            "href": href, "type": "application/xhtml+xml",
            "locations": {"progression": round(min(max(percent, 0), 100) / 100.0, 6)},
            "koboSpan": "",
        }
        # 有些客户端（老版）只读 `page`：EPUB 也给一个「近似页码」，避免显示空白
        out["page"] = locator + 1
    return out


def _spine_href(b: dict, index: int) -> str:
    """章节 index → EPUB 里真实的 spine 路径（读不到就退回一个可用的占位）。"""
    try:
        path = library.root_of(b) / str(b.get("name") or "")
        spine = library._spine(path)
        if 0 <= index < len(spine):
            return unquote(spine[index])
    except Exception:
        pass
    return f"chapter_{index}.xhtml"


def apply_read_progress(b: dict, payload: dict = None) -> tuple:
    """Komga 的进度 → 本项目的 ``(locator, percent)``。

    - ``completed: true`` → ``percent = 100``（页码忽略，与 Komga 语义一致）
    - 漫画/PDF：``page``（1 起）→ ``locator = page - 1``
    - EPUB：``locator.locations.progression`` → percent；
      ``locator.href`` 若能对上 spine 的某一章 → 同时更新 locator（对不上就只更新 percent）
    """
    p = payload or {}
    if p.get("completed"):
        return (int((db.get_progress(b["id"]) or {}).get("locator") or 0), 100.0)

    if _is_paged(b):
        try:
            page = int(p.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
        percent = 0.0
        total = int(b.get("pages") or 0)
        if total > 0 and page > 0:
            percent = min(100.0, round(page / total * 100.0, 4))
        return (max(0, page - 1), percent)

    loc = p.get("locator") or {}
    prog = (((loc.get("locations") or {}).get("progression")) if isinstance(loc, dict) else None)
    try:
        percent = min(100.0, max(0.0, float(prog) * 100.0))
    except (TypeError, ValueError):
        percent = 0.0
    locator = 0
    href = unquote(str((loc or {}).get("href") or "")) if isinstance(loc, dict) else ""
    if href:
        try:
            spine = library._spine(library.root_of(b) / str(b.get("name") or ""))
            if href in spine:
                locator = spine.index(href)
        except Exception:
            locator = 0
    if not locator:
        locator = int((db.get_progress(b["id"]) or {}).get("locator") or 0)
    return (locator, percent)


# ---------------- 页面流（客户端阅读的核心）----------------
# 漫画 / PDF 走**逐页取图**；EPUB 不走页面流（客户端下载文件、或读 manifest）。
# 两个格式的取图差异被这两个函数包住，路由层不必再判断格式。

def pages_for(b: dict) -> list:
    """页清单（Komga 的 `PageDto[]`）。**number 从 1 起** —— 与客户端取图的编号一致。"""
    import mimetypes
    from . import comics

    fmt = str(b.get("format") or "").upper()
    path = library.root_of(b) / str(b.get("name") or "")
    if fmt in ("CBZ", "CBR"):
        info = comics.pages(path)
        out = []
        for i, p in enumerate(info.get("pages") or []):
            name = str(p.get("name") or f"page{i + 1}")
            out.append({
                "number": i + 1, "fileName": pathlib.PurePosixPath(name).name,
                # 页的真实类型从文件名推（zip 里可能是 png/webp，不该一律报 jpeg）
                "mediaType": mimetypes.guess_type(name)[0] or "image/jpeg",
                "width": 0, "height": 0, "sizeBytes": int(p.get("size") or 0),
            })
        return out
    if fmt == "PDF":
        from . import pdfrender
        n = pdfrender.page_count(path)
        sizes = pdfrender.page_sizes(path, n)
        return [{"number": i + 1, "fileName": f"page{i + 1}.jpg",
                 "mediaType": "image/jpeg", "width": sizes[i][0], "height": sizes[i][1],
                 "sizeBytes": 0} for i in range(n)]
    return []


def page_image(b: dict, number, convert: str = "") -> tuple:
    """取第 `number` 页（**1 起**）→ ``(bytes, media_type)``；取不到返回 ``(None, "")``。

    `convert='jpeg'`（Komga 的查询参数）对 CBZ 也转码：客户端偶尔会用它统一格式，
    但转码有成本 —— 只有确实不是 jpeg 且客户端要求时才转。
    """
    from . import comics

    try:
        idx = int(number) - 1
    except (TypeError, ValueError):
        return (None, "")
    if idx < 0:
        return (None, "")

    fmt = str(b.get("format") or "").upper()
    path = library.root_of(b) / str(b.get("name") or "")
    if fmt in ("CBZ", "CBR"):
        data, media = comics.page_bytes(path, idx)
        if not data:
            return (None, "")
        if (convert or "").lower() in ("jpeg", "jpg") and "jpeg" not in media:
            try:
                import io

                from PIL import Image
                buf = io.BytesIO()
                with Image.open(io.BytesIO(data)) as im:
                    im.convert("RGB").save(buf, "JPEG", quality=88)
                return (buf.getvalue(), "image/jpeg")
            except Exception:
                return (data, media)          # 转码失败就用原图，别让客户端拿不到
        return (data, media)
    if fmt == "PDF":
        from . import pdfrender
        data, _ = pdfrender.render_page(path, idx, b["id"])
        return (data, "image/jpeg") if data else (None, "")
    return (None, "")


def manifest_for(b: dict) -> dict:
    """WebPub manifest（EPUB 在线阅读用）：把 spine 章节列成 readingOrder。

    第三方 App 对 EPUB 多数是**下载后本地读**，manifest 主要给 Komga 官方的 Web 阅读器；
    但生成成本很低，给全了免得客户端在某些流程上撞 404。
    """
    path = library.root_of(b) / str(b.get("name") or "")
    try:
        spine = library._spine(path)
    except Exception:
        spine = []
    prog = db.get_progress(b["id"]) or {}
    return {
        "metadata": {
            "title": str(b.get("title") or ""),
            "author": str(b.get("author") or ""),
            "publisher": str(b.get("publisher") or ""),
            "language": str(b.get("language") or ""),
            "modified": iso(b.get("mtime")),
        },
        "readingOrder": [
            {"href": unquote(h), "type": "application/xhtml+xml",
             "title": pathlib.PurePosixPath(h).name} for h in spine
        ],
        "resources": [], "toc": [],
        "readingProgression": "ltr",
        "startProgression": round(float(prog.get("percent") or 0) / 100.0, 6),
    }
