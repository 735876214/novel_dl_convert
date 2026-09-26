"""TXT 书的**派生 EPUB 缓存**（第 55 期）：让 TXT 也能走 EPUB 阅读全链路。

TXT 直接阅读缺的不止是渲染 —— 目录、批注、CFI 精确位置与资源代理整条链路都建立在
「EPUB zip + spine」上（`library.chapter_html` / `library._reading_list` / `epub_cfi`）。
所以策略是**先转后用**：

- 转得动 ⇒ 用同一个分章真值源（`core/detect.py`）切章、拼一本**最小 EPUB**，落进
  ``CACHE_DIR/txt-epub/<book_id>/``。它是**派生缓存**：可随时重建、不进书库
  （不会凭空多出第二个书目条目）、不碰成品目录纪律（「成品目录禁与库根重叠」）；
  阅读器读到的是真 EPUB ⇒ 目录 / 批注 / CFI / 进度全部免费复用。
- 转不动（空文本 / 编码坏到读出空串 / 超大文件 / 构建失败）⇒ 记一条**失败标记**并
  返回 ``None``，由调用方回落**原生 TXT 分章**（:func:`native_chapters` /
  :func:`native_chapter_html`）。

⚠️ **形态一经确定就锁定**（`state.json` 记源文件指纹）：两条路线的章节 index 都是
0 基、索引空间已对齐（派生 EPUB 用 ``nav=False`` 组装，spine 不含 nav 目录页），
但**目录条目数仍可能因分章细节而不同**；为免「今天有 EPUB、清个缓存变原生」时
章节号漂移让既有批注跳错章，只在**源文件本身变化**（mtime/size 变）时才可能换形态。

分章/编码/组装三处都不另写实现：`detect`（唯一分章真值源）、
`pipeline._detect_encoding`（唯一编码探测）、`epub_builder.build_epub`（唯一组装）。
"""
import json
import pathlib
import time

from .. import config
from . import detect, epub_builder, preprocess

#: 缓存子目录名（小写 / 连字符，与 `pdf/`、`authors/` 同风格）
CACHE_SUBDIR = "txt-epub"
#: 超过这个大小的 TXT 不转（组装与解包都吃内存）⇒ 直接走原生分章兜底
SOURCE_MAX_BYTES = 20 * 1024 * 1024
#: 缓存文件名（固定名，state.json 里不再记文件名 —— 少了半套「名字变了找不到」的分支）
EPUB_NAME = "derived.epub"
STATE_NAME = "state.json"

#: 分章结果缓存（键 = 源路径 + 指纹）：详情接口与逐章接口都会调，别每章重切一遍
_SPLIT_CACHE: dict = {}
_SPLIT_CACHE_MAX = 8


def _cache_dir(book_id: str) -> pathlib.Path:
    return config.CACHE_DIR / CACHE_SUBDIR / str(book_id)


def _fingerprint(path: pathlib.Path) -> str:
    st = path.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _read_state(cdir: pathlib.Path) -> dict:
    try:
        return json.loads((cdir / STATE_NAME).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_state(cdir: pathlib.Path, state: dict) -> None:
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / STATE_NAME).write_text(
            json.dumps({**state, "at": time.time()}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        # 状态写不进去不是致命错：下次调用重新尝试（最坏是重复转换一次）
        pass


def _src_path(book: dict, path=None, root=None):
    if path is not None:
        return pathlib.Path(path)
    from . import library  # 延迟导入：library 顶层会 import 本模块的调用方链
    return (root or library.root_of(book)) / book["name"]


def _read_text(path: pathlib.Path) -> "tuple[str, str]":
    """读全文：编码探测复用 `pipeline._detect_encoding`（唯一实现，禁第二处）。"""
    from .pipeline import _detect_encoding
    enc = _detect_encoding(path)
    return path.read_text(encoding=enc, errors="ignore"), enc


def _chapters(book: dict, path: pathlib.Path) -> list:
    """（带指纹缓存的）原生分章结果 —— 两条路线共用同一份切分。"""
    fp = _fingerprint(path)
    key = (str(path), fp)
    hit = _SPLIT_CACHE.get(key)
    if hit is not None:
        return hit
    from .. import config as _cfg
    raw, _enc = _read_text(path)
    chapters = detect.detect_chapters_cfg(raw, _cfg.load_config(), False) if raw.strip() else []
    if len(_SPLIT_CACHE) >= _SPLIT_CACHE_MAX:
        _SPLIT_CACHE.clear()
    _SPLIT_CACHE[key] = chapters
    return chapters


def derived_epub(book: dict, *, path=None, root=None):
    """TXT 书 → 派生 EPUB 路径；不可转 / 失败 ⇒ ``None``（调用方回落原生分章）。

    命中规则：源指纹没变且上次成功 ⇒ 直接返回既有缓存（**不重复转换**）；
    源指纹没变但上次失败 ⇒ 仍返回 ``None``（保持形态稳定，别一会儿 EPUB 一会儿原生）。
    """
    p = _src_path(book, path, root)
    if p.suffix.lower() != ".txt" or not p.is_file():
        return None
    bid = str(book.get("id") or "")
    if not bid:
        return None
    try:
        fp = _fingerprint(p)
    except Exception:
        return None

    cdir = _cache_dir(bid)
    state = _read_state(cdir)
    if state.get("fingerprint") == fp:
        if state.get("status") != "ok":
            return None
        epub = cdir / EPUB_NAME
        return epub if epub.exists() else None

    if p.stat().st_size > SOURCE_MAX_BYTES:
        _write_state(cdir, {"status": "failed", "fingerprint": fp,
                            "reason": f"source > {SOURCE_MAX_BYTES} bytes"})
        return None

    try:
        chapters = _chapters(book, p)
        if not chapters or not any((c.get("body") or "").strip() for c in chapters):
            raise ValueError("文本读不出可读内容（空文本或编码全坏）")
        for ch in chapters:
            ch["body_html"] = preprocess.paragraphs_to_html(ch["body"])
        meta = {
            "title": str(book.get("title") or p.stem),
            "author": str(book.get("author") or ""),
            "language": str(book.get("language") or "zh") or "zh",
        }
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = cdir / (EPUB_NAME + ".tmp")
        if tmp.exists():
            tmp.unlink()
        # nav=False：spine 不含 nav 目录页 ⇒ 章节 index 0 基，与原生分章**索引空间对齐**
        # （两条路线的 index 语义一致，形态切换不会让章节号整体挪位）
        epub_builder.build_epub(meta, chapters, str(tmp), nav=False)
        final = cdir / EPUB_NAME
        tmp.replace(final)          # 原子落盘：半成品绝不留在最终路径上
        _write_state(cdir, {"status": "ok", "fingerprint": fp, "chapters": len(chapters)})
        return final
    except Exception as e:
        _write_state(cdir, {"status": "failed", "fingerprint": fp,
                            "reason": str(e)[:160]})
        return None


def native_chapters(book: dict, *, path=None, root=None) -> list:
    """原生分章目录（与 `library._reading_list` **同形状**）：``[{volume, chapters}]``。

    索引 0 基、无 nav 占位 —— 与 :func:`native_chapter_html` 的 index 同一空间。
    """
    p = _src_path(book, path, root)
    if p.suffix.lower() != ".txt" or not p.is_file():
        return []
    try:
        chapters = _chapters(book, p)
    except Exception:
        return []
    if not chapters:
        return []
    return [{
        "volume": "正文",
        "chapters": [
            {"num": i + 1, "title": (c.get("title") or f"第 {i + 1} 节"), "index": i}
            for i, c in enumerate(chapters)
        ],
    }]


def native_chapter_html(book: dict, index: int, *, path=None, root=None) -> dict:
    """原生兜底的单章内容：``{index, total, title, html}``（与 `library.chapter_html` 同形）。

    越界抛 ``IndexError``（调用方转 404），与 EPUB 路径的约定一致。
    """
    p = _src_path(book, path, root)
    chapters = _chapters(book, p)
    i = int(index)
    if i < 0 or i >= len(chapters):
        raise IndexError("章节不存在")
    ch = chapters[i]
    return {
        "index": i,
        "total": len(chapters),
        "title": ch.get("title") or f"第 {i + 1} 节",
        # 原生路线没有 z3 标题元素（epub_builder 会给章节加 <h2>），这里把标题也放进正文，
        # 让两条形态读起来一致
        "html": f"<h2>{ch.get('title') or ''}</h2>" + preprocess.paragraphs_to_html(ch.get("body") or ""),
    }
