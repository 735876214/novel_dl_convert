"""在线阅读：把**用户自己的书源**接到阅读器上（第 93 期）。

## 这一层解决什么

阅读器的本地链路是「书 → 库里的文件 → 单章 XHTML」。本模块补的是另一条：
**书 → 书源上的一页 → 单章正文**（`online_bind` 记的就是那「一页」在哪）。
用户的要求原话是「在线阅读接我给的书源」「切换客户端进度同步」「允许缓存章节，
以方便无网络或网络差的时候还可以继续阅读」—— 三条各对应本模块的一段：

· **接书源**：`index_of()` / `chapter_of()`，取数全部走 `rules` 那份唯一实现
  （`chapter_links` / `chapter_body`），本模块不解析任何页面；
· **跨客户端**：什么都不存在前端 —— 目录、正文、位置（`online_bind.pos`）都在服务端；
· **能离线读**：`CACHE_DIR/online/<书>/`（`index_of` 与 `chapter_of` 一律**缓存优先**），
  抓取失败时回落缓存并如实标 `stale`。

## 三条硬边界

1. **只写缓存目录**。本模块的写盘点**全部**在 :func:`cache_root` 之下，绝不碰书库 /
   收书目录 / 回收站，也**从不 `unlink`** 任何别的路径（有静态契约钉住，见
   `tests/test_online_read.py`）。清缓存只清缓存目录。
2. **第三方标记永不进 `v-html`**。源站正文先经 :func:`html_to_text` 压成纯文本，
   再由 `core.reading_list.text_to_xhtml`（**唯一实现**，与追更共用）逐行 `escape`
   包 `<p>`。所以能进阅读器的字符串**只能**由服务端这两步产出。
3. **URL 只在服务端**。客户端按 `index` 取章，永远不传 URL —— 没有 SSRF 面
   （绑定那一页由用户在详情页显式选择，存在 `online_bind` 里）。

## 缓存形态与上限

```
CACHE_DIR/online/<sanitized-book-id~hash>/
    toc.json       {"entries": [{"title", "url"}...], "single": bool, "fetched_at": float}
    <index>.txt    toc 模式：单章正文（**源站原文**，剥标记在读取时做）
    full.json      single 模式：整本一次取回的全部章节正文
```

上限：总量 200 MB、单本 500 章（`toc` 模式）。超了按**最久没碰过的先删**（真 LRU，
用文件的 mtime）。缓存只是缓存 —— 删掉任何一份都不影响正确性，只影响下一次要多跑一趟网络。

⚠️ `single` 模式的源**没法只取一章**：它的缓存一旦被清掉，下一次读要重取整本。
这是源站形态决定的代价（`book.mode != "toc"` 的规则只有整页全文），如实写在
`online_support` 那条链的说明里，不假装它和 `toc` 模式一样廉价。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path

from .. import config
from ..core.reading_list import text_to_xhtml
from .base import REGISTRY

logger = logging.getLogger(__name__)

#: 缓存目录名（`CACHE_DIR/online/`）。清缓存 / 统计 / 静态契约都以它为唯一入口。
SUBDIR = "online"

#: 总量上限（字节）。用户口径是「允许落盘，方便断网时继续读」——
#: 上限存在的意义是「别把 NAS 的盘吃满」，不是「尽量多缓存」。
MAX_BYTES = 200 * 1024 * 1024
#: 单本上限（`toc` 模式的章节文件数）。500 章 ≈ 一本中等长度的网络小说。
MAX_CHAPTERS = 500

#: 索引缓存文件与整本缓存文件的名字（读点只有这两个常量决定，不散落字符串）。
_INDEX_FILE = "toc.json"
_FULL_FILE = "full.json"


# ---------------- 路径与统计 ----------------

def cache_root() -> Path:
    """在线缓存的根目录（**本模块唯一允许写入的位置**）。"""
    return Path(config.CACHE_DIR) / SUBDIR


def book_dir(book_id) -> Path:
    """某本书的缓存目录。

    ⚠️ 目录名不直接用 `book_id`：它由**文件名**派生（可能带 `$`、空格、中文），
    直接拼进路径在 Windows 上会遇到非法字符或过长名。所以清洗 + 附一段哈希保唯一。
    """
    safe = re.sub(r"[^0-9A-Za-z_.\-]", "_", str(book_id))[:48]
    h = hashlib.sha1(str(book_id or "").encode("utf-8")).hexdigest()[:10]
    return cache_root() / f"{safe}~{h}"


def _index_path(book_id) -> Path:
    return book_dir(book_id) / _INDEX_FILE


def _full_path(book_id) -> Path:
    return book_dir(book_id) / _FULL_FILE


def _chapter_path(book_id, index: int) -> Path:
    return book_dir(book_id) / f"{int(index)}.txt"


def _iter_cache_files():
    """遍历缓存下的所有文件 → ``[(mtime, size, path), ...]``（不存在的目录当空）。"""
    out: list = []
    root = cache_root()
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        try:
            if not p.is_file():
                continue
            st = p.stat()
        except OSError:
            continue
        out.append((st.st_mtime, st.st_size, p))
    return out


def cache_stats() -> dict:
    """在线缓存的占用（维护页与在线阅读卡共用这一份统计，不各算一遍）。"""
    files = _iter_cache_files()
    root = cache_root()
    books = 0
    try:
        books = sum(1 for d in root.iterdir() if d.is_dir())
    except OSError:
        books = 0
    chapters = sum(1 for _, _, p in files if p.suffix == ".txt")
    return {"books": books, "chapters": chapters, "files": len(files),
            "bytes": sum(size for _, size, _ in files), "path": str(root),
            "max_bytes": MAX_BYTES, "max_chapters": MAX_CHAPTERS}


#: 章节文件名（`<index>.txt`）—— 统计与遍历都按它认，避免把 `toc.json` 数成章节。
_CHAPTER_NAME = re.compile(r"^\d+$")


def book_cache_stats(book_id, *, source: str = "", url: str = "") -> dict:
    """某本书**本机缓存**的现状（**不触网**：只读已落盘的目录与章节文件）。

    详情页的在线读卡要如实告诉用户「本机存了几章 / 共几章」，而这件事不该为了
    显示一行字去外呼源站 —— 磁盘上有多少就报多少，没有就是 0。

    给了 `source` / `url` 时会核对缓存是**不是这一页**的（用户刚把绑定换到另一个源 /
    另一页时，旧缓存还躺在盘上）—— 不核对的话界面上会报出上一页的章数，
    看起来像「还没读就缓存好了」。
    """
    d = book_dir(book_id)
    data = _read_json(_index_path(book_id)) or {}
    if (source or url) and not _same_page(data, source, url):
        return {"total": 0, "cached": 0, "single": False, "fetched_at": 0.0}
    entries = data.get("entries") or []
    if data.get("single"):
        blob = _read_json(_full_path(book_id)) or {}
        cached = len(blob.get("bodies") or [])
    else:
        try:
            cached = sum(1 for p in d.glob("*.txt") if _CHAPTER_NAME.match(p.stem))
        except OSError:
            cached = 0
    return {"total": len(entries), "cached": cached, "single": bool(data.get("single")),
            "fetched_at": float(data.get("fetched_at") or 0)}


def has_body(book_id, index) -> bool:
    """这一章**本机缓存里已经有了**吗（预取据此决定要不要多跑一趟网络）。"""
    data = _read_json(_index_path(book_id)) or {}
    try:
        return _read_body(book_id, data, int(index))[0] is not None
    except (TypeError, ValueError):
        return False


def purge_cache() -> dict:
    """清空**在线缓存**（只删缓存目录里的东西；书库 / 收书目录 / 回收站一个都不碰）。

    与 ``/api/cache/clear``（清整个 CACHE_DIR）分开：用户常常只想腾掉在线阅读那份，
    不想顺手把 AI 分章缓存也清掉 —— 那会让下一本书的分章重跑一遍。
    """
    import shutil
    root = cache_root()
    before = cache_stats()
    try:
        for d in list(root.iterdir()):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
            else:
                try:
                    d.unlink()
                except OSError:
                    pass
    except OSError:
        pass
    return {"ok": True, "removed_books": before["books"], "removed_bytes": before["bytes"]}


def trim() -> int:
    """按上限回收缓存（**最久没碰过的先删**），返回删掉的文件数。

    两级：先按「单本 500 章」删该书最旧的章节文件，再按「总量 200 MB」删全局最旧的。
    每次写缓存后调一次 —— 缓存文件数在这个量级（几百到几千），
    一遍 `rglob` 比「维护一个元数据库」简单得多，也不会出现「元数据与磁盘对不上」。
    """
    removed = 0
    root = cache_root()
    if not root.is_dir():
        return 0
    # ① 单本上限
    try:
        dirs = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return 0
    for d in dirs:
        try:
            chaps = sorted(((p.stat().st_mtime, p) for p in d.glob("*.txt")
                            if p.is_file()), key=lambda t: t[0])
        except OSError:
            continue
        for _, p in chaps[:max(0, len(chaps) - MAX_CHAPTERS)]:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    # ② 总量上限
    files = sorted(_iter_cache_files(), key=lambda t: t[0])
    total = sum(size for _, size, _ in files)
    for _, size, p in files:
        if total <= MAX_BYTES:
            break
        try:
            p.unlink()
            total -= size
            removed += 1
        except OSError:
            pass
    # 空目录顺手收掉（否则统计里的「书数」会一直涨）
    for d in dirs:
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass
    return removed


def _write_text(path: Path, text: str) -> None:
    """原子写缓存文件（临时文件 + `replace`）。

    ⚠️ 缓存也要原子写：半截的正文会被当成「已缓存」，读者看到的是断在中间的一章，
    而且此后**永远命中**那份坏缓存（没有任何东西会去修它）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_json(path: Path, data: dict) -> None:
    _write_text(path, json.dumps(data, ensure_ascii=False))


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001 —— 坏了当没有
        return None


# ---------------- 取数（唯一的两个入口：目录 / 单章）----------------

def support_reason(source: str) -> str:
    """这个书源能不能逐章在线阅读（空串 = 能，非空 = **可直接展示**的原因）。"""
    cls = REGISTRY.get(str(source or ""))
    if not cls:
        return f"未知书源：{source or '(空)'}"
    try:
        # ⚠️ 必须在**实例**上问：`online_support` 是实例方法，规则源要读自己的
        # `self._RULE` 才知道有没有 `book.content`。在类上问会得到
        # 「missing 1 required positional argument: 'self'」—— 而那句报错会
        # 原样显示给用户当「不支持的原因」，看起来像源坏了。
        return str(cls().online_support() or "")
    except Exception as e:                              # noqa: BLE001 —— 适配器没实现也要如实说
        return f"这个书源不支持逐章在线阅读（{e}）"


def _source_class(source: str):
    cls = REGISTRY.get(str(source or ""))
    if not cls:
        raise ValueError(f"未知书源：{source or '(空)'}")
    return cls


def _may_be_html(source: str) -> bool:
    """这个源取回的正文可能是 HTML 吗（决定要不要过 HTML 解析器，见 `render_body`）。"""
    try:
        return bool(_source_class(source)().content_may_be_html())
    except Exception:                                   # noqa: BLE001 —— 拿不准就按「可能是」处理
        return True


def _same_page(data: dict, source: str, url: str) -> bool:
    """缓存里那份目录记的是**这一页**吗。

    缓存只按 `book_id` 分目录，而绑定可以换源 / 换页（用户改主意、上一个源挂了、
    手动粘错了地址）—— 不核对的话，换了页之后读到的仍是旧站点的目录与正文，
    而且**没有任何报错**：用户会以为「这个源就只有这些章」。
    目录里记着它是哪一页的，就在这里对一次。
    """
    if not data or not (data.get("entries") or []):
        return False
    return ((data.get("source") or "") == (source or "")
            and (data.get("url") or "") == (url or ""))


def _same_or_extended(prev: list, new: list) -> bool:
    """新目录是不是**旧目录的延伸**（旧目录的每一条都还在原位）。

    延伸（源站只是在末尾加了新章 —— 正是追更那种情形）⇒ 旧缓存仍然有效，别清；
    否则（改版 / 重排 / 变短）⇒ 旧的正文缓存必须清掉：它对应的是另一份目录，
    留着会让「第 12 章」显示成另一章的内容，而且**没有任何报错**。
    """
    if not prev:
        return True
    if len(new) < len(prev):
        return False
    for a, b in zip(prev, new):
        if (a.get("title") or "") != (b.get("title") or "") or \
                (a.get("url") or "") != (b.get("url") or ""):
            return False
    return True


def _clear_chapters(book_id) -> int:
    """丢掉某本书的**正文**缓存（目录缓存另外写）。目录变了才调它。"""
    d = book_dir(book_id)
    n = 0
    if not d.is_dir():
        return 0
    for p in list(d.glob("*.txt")) + [_full_path(book_id)]:
        try:
            if p.is_file():
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


async def _fetch_index(manager, source: str, url: str) -> dict:
    """真的去源站取一次目录（触网）。返回 ``_write_index`` 要写的那份数据。"""
    src = _source_class(source)()
    reason = src.online_support() if hasattr(src, "online_support") else ""
    if reason:
        raise ValueError(reason)
    mode = src.online_mode() or "toc"
    if mode == "toc":
        async with manager._client(src) as c:
            links = await src.chapter_links(c, url)
        if not links:
            raise ValueError("这个书页里没解析出章节 —— 规则大概过期了，"
                             "可以在「书源管理」里改好规则再试（或改用「手动填书页地址」）")
        return {"entries": [{"title": c.get("title") or "", "url": c.get("url") or ""}
                            for c in links],
                "single": False, "fetched_at": time.time(),
                "source": source, "url": url}
    # single：源站只有整本一页 ⇒ 目录与正文一起取回来
    chapters = await _fetch_all(manager, src, url)
    if not chapters:
        raise ValueError("这个书页里没解析出章节 —— 规则大概过期了，"
                         "可以在「书源管理」里改好规则再试")
    return {"entries": [{"title": c.get("title") or "", "url": ""} for c in chapters],
            "single": True, "fetched_at": time.time(), "source": source, "url": url,
            "_bodies": [c.get("body") or "" for c in chapters]}


async def _fetch_all(manager, src, url: str) -> list[dict]:
    """整本取回（`single` 模式的唯一取法）：按既有分章规则切成章节。"""
    async with manager._client(src) as c:
        return await src.fetch_book_chapters(c, {"url": url}) or []


async def index_of(manager, book_id, source: str, url: str, *, refresh: bool = False) -> dict:
    """这本书在这个源上的章节清单（**缓存优先**）。

    返回 ``{"entries", "single", "fetched_at", "origin": "cache"|"network",
    "stale": bool, "error": str}``。``stale=True`` 的含义很具体：
    **这次想去刷新但没成功，给的是上次缓存的那份**（断网时的正常路径，不是错误）。
    """
    cached = _read_json(_index_path(book_id))
    if cached and not _same_page(cached, source, url):
        # 绑定换到了别的源 / 别的书页 ⇒ 这份缓存是**另一页**的：正文也要清
        #（否则「第 1 章」会在新目录下取到旧站点的正文）。见 `_same_page`。
        _clear_chapters(book_id)
        cached = None
    if cached and cached.get("entries") and not refresh:
        return {**cached, "origin": "cache", "stale": False, "error": ""}
    try:
        fresh = await _fetch_index(manager, source, url)
    except Exception as e:                              # noqa: BLE001 —— 原因原文交给上层
        if cached and cached.get("entries"):
            return {**cached, "origin": "cache", "stale": True, "error": f"{e}"}
        raise
    bodies = fresh.pop("_bodies", None)
    if cached and not _same_or_extended(cached.get("entries") or [], fresh["entries"]):
        _clear_chapters(book_id)
    _write_json(_index_path(book_id), fresh)
    if bodies is not None:                              # single 模式：正文顺手落缓存
        _write_json(_full_path(book_id), {"fetched_at": fresh["fetched_at"], "bodies": bodies})
    trim()
    return {**fresh, "origin": "network", "stale": False, "error": ""}


async def _fetch_one_body(manager, source: str, url: str) -> str:
    """取回**一章**的原文（`toc` 模式的按需路径）。"""
    cls = _source_class(source)
    src = cls()
    async with manager._client(src) as c:
        return await src.chapter_body(c, url)


async def chapter_of(manager, book_id, source: str, url: str, index,
                     *, force: bool = False) -> dict:
    """取单章（**缓存优先**：读过的章不再外呼）。

    返回 ``{"index", "total", "title", "html", "origin", "stale", "cached_at", "raw_len"}``，
    其中 ``html`` 已经是可以直接进阅读器的那份（见模块注释第 2 条）。
    `origin` 如实说这一章**是哪儿来的**（`"cache"` / `"network"`）——
    界面那条来源横幅读它，不许拿「有没有网」去猜。
    """
    data = await index_of(manager, book_id, source, url)
    entries = data.get("entries") or []
    total = len(entries)
    try:
        i = int(index)
    except (TypeError, ValueError):
        raise ValueError("章节号必须是整数")
    if i < 0 or i >= total:
        raise IndexError("章节不存在")
    entry = entries[i]
    may_html = _may_be_html(source)

    raw = None
    cached_at = 0.0
    origin = "cache"
    if not force:
        raw, cached_at = _read_body(book_id, data, i)
    if raw is None:
        origin = "network"
        try:
            if data.get("single"):
                raw, cached_at, entries, total = await _load_single(
                    manager, book_id, source, url, data, i, entries, total)
            else:
                raw = await _fetch_one_body(manager, source, entry.get("url") or "")
                raw = raw if raw is not None else ""
                _write_text(_chapter_path(book_id, i), raw)
                cached_at = time.time()
                trim()
        except Exception as e:                      # noqa: BLE001
            # 降级：缓存里有旧的（`force` 刷新失败时）就用旧的，并如实标 `stale`
            fallback, fallback_at = _read_body(book_id, data, i)
            if fallback is not None:
                return _chapter_out(i, total, entry, fallback, may_be_html=may_html,
                                    origin="cache", stale=True, cached_at=fallback_at,
                                    error=f"{e}")
            raise
    return _chapter_out(i, total, entry, raw or "", may_be_html=may_html, origin=origin,
                        stale=bool(data.get("stale")), cached_at=cached_at, error="")


async def _load_single(manager, book_id, source: str, url: str, data: dict,
                       index: int, entries: list, total: int) -> tuple:
    """`single` 模式取一章：**整本取回**后落到 `full.json`，再从里面取这一章。

    顺带对齐目录：源站加了章 / 改了版时章节数与缓存那份不同 ⇒ 按新的重写目录
    （下一步 `_same_or_extended` 会在下一次刷新时清掉不再对应的正文）。
    返回 ``(正文, 时间戳, 目录, 总数)``。
    """
    chapters = await _fetch_all(manager, _source_class(source)(), url)
    now = time.time()
    _write_json(_full_path(book_id),
                {"fetched_at": now, "bodies": [c.get("body") or "" for c in chapters]})
    if entries and len(chapters) != total:
        logger.info("在线读 %s：源站章节数 %s → %s，重写目录", book_id, total, len(chapters))
        fresh = {"entries": [{"title": c.get("title") or "", "url": ""} for c in chapters],
                 "single": True, "fetched_at": now, "source": source, "url": url}
        _write_json(_index_path(book_id), fresh)
        entries, total = fresh["entries"], len(fresh["entries"])
    trim()
    raw, at = _read_body(book_id, data, index)
    return (raw or ""), (at or now), entries, total


def _read_body(book_id, data: dict, index: int):
    """读缓存里的正文 → ``(正文 | None, 写入时间)``。"""
    if data.get("single"):
        blob = _read_json(_full_path(book_id))
        if not blob:
            return None, 0.0
        bodies = blob.get("bodies") or []
        if index >= len(bodies):
            return None, 0.0
        return str(bodies[index] if bodies[index] is not None else ""), float(blob.get("fetched_at") or 0)
    p = _chapter_path(book_id, index)
    try:
        if p.is_file():
            return p.read_text(encoding="utf-8"), p.stat().st_mtime
    except OSError:
        pass
    return None, 0.0


def _chapter_out(index: int, total: int, entry: dict, raw: str, *, origin: str,
                 stale: bool, cached_at: float, error: str = "",
                 may_be_html: bool = True) -> dict:
    """组一章的响应（**形状与 `/api/books/{bid}/chapter/{i}` 一致** —— 同一个阅读器要吃它）。"""
    html = render_body(raw, may_be_html=may_be_html)
    return {"index": index, "total": total, "title": entry.get("title") or "",
            "html": html, "origin": origin, "stale": bool(stale),
            "cached_at": float(cached_at or 0), "error": error,
            "raw_len": len(raw or "")}


# ---------------- 正文清洗（第三方标记到这里为止）----------------

def html_to_text(raw: str) -> str:
    """把源站给的 HTML 正文压成**纯文本**（保留段落切分）。

    ⚠️ 这是「第三方标记永不进 `v-html`」那道闸门的前半截：`script` / `style`
    **连内容一起丢掉**（否则页面里的 JS 会变成一堆乱码正文），其余标签只当**分段信号**，
    文本一律交给 :func:`render_body` 里的 `escape`。所以本模块**从不**把源站
    HTML 直接交给前端，无论规则怎么写。
    """
    text = str(raw or "")
    if "<" not in text:                     # 纯文本（css 默认 / json 通道）⇒ 不必过解析器
        return text
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "html.parser")
        for bad in soup(["script", "style"]):
            bad.decompose()
        return soup.get_text("\n", strip=True)
    except Exception:                       # noqa: BLE001 —— 解析器炸了也不能放过标记
        logger.warning("在线正文压纯文本失败，改用去标记兜底")
        return re.sub(r"<[^>]*>", "\n", text)


def render_body(raw: str, *, may_be_html: bool = True) -> str:
    """源站正文 → 阅读器 XHTML（**本模块唯一产出正文的地方**）。

    `may_be_html=False`（规则的正文提取本来就给纯文本）时只做转义分段，不过 HTML 解析器 ——
    正文里合法的 `<`（如「他笑了 <3」）不该被解析器吃掉一段。
    """
    text = html_to_text(raw) if may_be_html else str(raw or "")
    return text_to_xhtml(text)


# ---------------- 预取（读第 p 章时顺手把 p+1 拿回来）----------------

async def prefetch(manager, book_id, source: str, url: str, index) -> bool:
    """把第 ``index`` 章（通常是下一章）先缓存好 —— **尽力而为**，失败静默。

    为什么值得做：滚动模式读到章末要立刻接上下一章，等一次网络往返就是「卡一下」。
    为什么失败要静默：预取是**锦上添花**，它的失败不该让用户看到任何东西
    （真正要读那一章时会重新取一次，并在这时报出真原因）。
    """
    try:
        await chapter_of(manager, book_id, source, url, index)
        return True
    except Exception:                        # noqa: BLE001 —— 见 docstring
        logger.debug("在线读预取第 %s 章失败（忽略）", index, exc_info=True)
        return False
