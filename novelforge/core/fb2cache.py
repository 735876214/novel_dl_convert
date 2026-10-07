"""FB2（FictionBook）**直读**（第 112 期）：解析后归一成一份**派生 EPUB**，再走整条 EPUB 链路。

FB2 是一种**单文件 XML** 电子书（`.fb2`）：自带章节（`<section>` + `<title>`）、插图（顶层
`<binary>` 里的 base64 图片，正文用 `<image l:href="#id"/>` 引用）、封面（`<coverpage>`）、
元数据（`<description><title-info>`）。它此前**不在任何白名单里**（`library.BOOK_EXTS`），
用户放进库里的 `.fb2` 连书架都上不去，更没有阅读入口。

做法与 `mobicache`（MOBI 解包）/ `txtcache`（TXT → EPUB）**同一形态**：把 FB2 解析成一份
真 EPUB，落到 ``CACHE_DIR/fb2-epub/<book_id>/derived.epub`` —— **不进书库、不新增书目条目、
不写回源文件**（源文件全程只读），可随时重建、可随时整个删掉。

于是整条既有 EPUB 链路**零新代码复用**：目录（`library._reading_list`）、单章正文
（`library.chapter_html`）、书内插图（`library.chapter_assets` + 资产接口）、书内样式、
**CFI 精确位置**与批注，全都跟真 EPUB 走同一套。

⚠️ **不引新依赖**：解析用标准库 ``xml.etree.ElementTree``（与 `core/epub_cfi.py` 同口径）。
它解析不了「轻微坏 XML」（未转义实体 / DOCTYPE），做最小预处理后仍解析不了时，**若 lxml 在**
（`requirements.txt` 里本就有）就用它的 ``XMLParser(recover=True)`` 兜一层；**两者都失败 ⇒ 422
（如实报错），绝不 500、绝不假装能读**。lxml 缺失只是少一层兜底，不影响本模块可用。

⚠️ **形态一经确定即锁定**（`state.json` 记 **源指纹 + 本模块规则版本 + `recover` 分量**）。
`recover` 分量是**自愈钩子**：先前因没有 lxml 而锁定失败的文件，装上 lxml 后即使源文件一个字节
没动也能重建（只比指纹会永远锁死）。这与 `mobicache` 用「解包器版本」当第三分量是同一个理由。
"""
import base64
import html as _html
import json
import os
import pathlib
import re
import shutil
import threading
import time
import xml.etree.ElementTree as ET

from .. import config
from . import epub_builder, pipeline

#: 本模块认的扩展名（单文件 FB2）。
EXTS = (".fb2",)

#: 派生缓存子目录名 / 产物名（小写连字符，与 `mobi-unpack/`、`txt-epub/` 同风格）
CACHE_SUBDIR = "fb2-epub"
EPUB_NAME = "derived.epub"
STATE_NAME = "state.json"

#: **本模块的规则版本**：解析口径 / 元素映射 / 分章规则，凡影响「读到什么」的改动都 +1。
#: 它进 `state.json`，源文件没动而口径变了时触发重建（与 `txtcache` / `mobicache` 同理）。
RULE_VERSION = 1

#: 超过这个大小不解析（整本 XML 会被读进内存）。
SOURCE_MAX_BYTES = 200 * 1024 * 1024

#: 头部扫描的字节数：只用于「这本 FB2 有没有内嵌封面」（`<coverpage>` 在 `<title-info>` 里，
#: 位于 `<body>` 之前）。刻意**不做整本解析** —— 扫描期开解析器会把「丢一本书进库」变成
#: 一次 XML 解析（NAS 上很贵），与 `library._probe_entry` 只做廉价探测的纪律相悖。
_HEAD_SCAN_BYTES = 256 * 1024

#: 活动日志里 `file` 一栏的固定主体（合并键要稳，理由见 `txtcache._log_rule_rebuild`）
FILE_LABEL = "FB2 派生 EPUB"

#: 解析是纯 CPU 且不碰全局状态，但整本 XML 进内存、且同一本书会被多个读点并发请求 ——
#: 串行化构建，避免同一本书被并发解析两遍（构建不常发生，不值得更细的锁）。
_BUILD_LOCK = threading.Lock()

#: `content-type` → 文件扩展名（写进派生 EPUB 的图片条目名）
_EXT_OF = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif",
           "image/webp": "webp", "image/svg+xml": "svg", "image/bmp": "bmp"}

#: 派生 EPUB 的内置样式（FB2 特有块级元素的排版）。刻意很小 —— 只为让 `chapter_assets`
#: 有一份声明样式表，正文排版交给前端主题。
_FB2_CSS = (
    "blockquote{margin:.8em 0 .8em 1.5em;font-style:italic}"
    ".poem{margin:.8em 0}"
    ".stanza{margin:0 0 .6em 1.5em;white-space:pre-wrap}"
    ".subtitle{font-weight:600;text-align:center;margin:1.2em 0 .6em}"
    ".text-author{text-align:right;font-style:italic}"
)

#: 行内元素 → HTML 标签（与 FB2 标准对齐；未列出的元素**透明**渲染子节点）
_INLINE = {
    "p": "p", "emphasis": "em", "strong": "strong", "strikethrough": "s",
    "sub": "sub", "sup": "sup", "code": "code", "style": "span",
    "text-author": "p", "subtitle": "p",
}
#: 需要附加 class 的两个 p（便于内置样式命中）
_CLASS_OF = {"subtitle": "subtitle", "text-author": "text-author"}

#: `<coverpage` 出现在头部即认为有内嵌封面（**廉价近似**：二进制坏了封面接口会 404，
#: 前端回落渐变占位，与既有口径一致）
_COVER_RE = re.compile(rb"<coverpage[\s>/]", re.I)

_XLINK = "{http://www.w3.org/1999/xlink}href"


# ---------------- 依赖可用性（如实报）----------------

def _recover_available() -> bool:
    """lxml 的「宽容解析」兜底在不在。**唯一判据**（`state()` 与构建都问它）。"""
    try:
        from lxml import etree  # noqa: F401
        return True
    except Exception:                                  # noqa: BLE001 —— 没装 = 常态，不是异常
        return False


def state() -> dict:
    """`{"available", "version", "recover", "reason"}`。

    解析器是标准库，**恒可用**（`available` 永远真，理由如实写明）；`recover` 只是
    「轻微坏 XML 有没有 lxml 兜底」。读点据此在**解析彻底失败**时回 422 + 原因，不 500。
    """
    return {"available": True, "version": "",
            "recover": _recover_available(),
            "reason": "FB2 解析器为标准库 xml.etree，始终可用"}


# ---------------- 路径 / 指纹 / 状态 ----------------

def _cache_dir(book_id: str) -> pathlib.Path:
    return config.CACHE_DIR / CACHE_SUBDIR / str(book_id)


def _fingerprint(path: pathlib.Path) -> str:
    st = path.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _src_path(book: dict, path=None, root=None) -> pathlib.Path:
    if path is not None:
        return pathlib.Path(path)
    from . import library  # 延迟导入：library.book_detail 会 import 本模块
    return (root or library.root_of(book)) / book["name"]


def _read_state(cdir: pathlib.Path) -> dict:
    try:
        return json.loads((cdir / STATE_NAME).read_text(encoding="utf-8")) or {}
    except Exception:                                  # noqa: BLE001
        return {}


def _write_state(cdir: pathlib.Path, state_dict: dict) -> None:
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / STATE_NAME).write_text(
            json.dumps({**state_dict, "at": time.time()}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:                                  # noqa: BLE001
        # 状态写不进去不是致命错：下次调用重新尝试（最坏是多解析一次）
        pass


# ---------------- 活动日志 ----------------

def _log_failed(path: pathlib.Path, err) -> None:
    """解析不了时留一条活动日志（主体用**源文件名**：用户要知道是哪本）。"""
    try:
        from . import activity_log as al
        al.log(al.ACTION_CONVERT, path.name, al.STATUS_FAIL,
               detail=f"FB2 直读失败：{str(err)[:120]}", source="fb2cache")
    except Exception:                                  # noqa: BLE001
        pass


def _log_rule_rebuild(path: pathlib.Path, why: str) -> None:
    """规则 / 兜底层变了引起的重建：记一条活动日志（主体固定，便于同一次升级合并成一行）。"""
    try:
        from . import activity_log as al
        al.log(al.ACTION_CONVERT, FILE_LABEL, al.STATUS_OK,
               detail=f"{why} 已生效：{path.name}", source="fb2cache")
    except Exception:                                  # noqa: BLE001
        pass


# ---------------- 原子换入（与 mobicache 同款）----------------

def _sweep(parent: pathlib.Path, bid: str) -> None:
    """清掉上一次崩溃留下的 stage / old 目录（**只清本模块自己造的那些名字**）。"""
    for pat in (f".stage-{bid}-*", f"{bid}.old-*"):
        for stale in parent.glob(pat):
            shutil.rmtree(stale, ignore_errors=True)


def _swap_in(stage: pathlib.Path, final: pathlib.Path) -> None:
    """把 stage 换成 final —— **原子换入**：旧目录先挪走、再 replace、最后删旧的。

    直接往 final 里写是不行的：中途失败会留下半个目录，而 `state.json` 一旦写成 ok，
    读者拿到的就是缺文件的正文。一律先在同卷临时目录里建完再换入（源不可变 + 临时文件 +
    `Path.replace` 的既有纪律）。
    """
    old = None
    if final.exists():
        old = final.with_name(f"{final.name}.old-{os.getpid()}-{int(time.time() * 1000)}")
        shutil.rmtree(old, ignore_errors=True)
        final.replace(old)
    try:
        stage.replace(final)
    except OSError:
        if old is not None and old.exists() and not final.exists():
            try:
                old.replace(final)
            except OSError:                            # noqa: BLE001
                pass
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


# ---------------- FB2 解析（元素 → HTML）----------------

def _local(tag) -> str:
    """剥掉 XML 命名空间：``{http://…}body`` → ``body``（FB2 带不带命名空间都能过）。"""
    return str(tag).rsplit("}", 1)[-1].lower()


def _children(el, name: str) -> list:
    return [c for c in list(el) if _local(c.tag) == name]


def _child(el, name: str):
    for c in list(el):
        if _local(c.tag) == name:
            return c
    return None


def _text_of(el) -> str:
    return "".join(el.itertext()).strip()


def _href(el) -> str:
    return str(el.get(_XLINK) or el.get("href") or "")


def _esc(s: str) -> str:
    return _html.escape(s or "", quote=False)


def _attr_escape(s: str) -> str:
    return _html.escape(s or "", quote=True)


def _ent(m: re.Match) -> str:
    """HTML5 具名实体 → 数字引用（FB2 里裸 ``&nbsp;`` / ``&mdash;`` 很常见）。"""
    name = m.group(1) + ";"
    cp = _html.entities.html5.get(name)
    if cp is None:
        return m.group(0)
    return "&#" + str(ord(cp)) + ";"


def _clean_xml(text: str) -> str:
    """去掉 XML 声明与 DOCTYPE，并把 HTML5 具名实体转成数字引用（复用 `epub_cfi._parse` 的配方）。"""
    text = re.sub(r"<\?xml[^>]*\?>", "", text, count=1, flags=re.I)
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.I | re.S)
    return re.sub(r"&([a-zA-Z][a-zA-Z0-9]+);", _ent, text)


def _parse(text: str):
    """解析 FB2 XML；stdlib 失败时若 lxml 在就用它的 recover 模式兜一层。失败 ⇒ None。"""
    cleaned = _clean_xml(text)
    try:
        return ET.fromstring(cleaned)
    except ET.ParseError:
        pass
    except Exception:                                  # noqa: BLE001
        return None
    if not _recover_available():
        return None
    try:
        from lxml import etree
        return etree.fromstring(cleaned.encode("utf-8"), etree.XMLParser(recover=True))
    except Exception:                                  # noqa: BLE001
        return None


def _collect_images(root) -> "tuple[list, dict]":
    """顶层 ``<binary>`` → ``([{name, media_type, data}], {"#id": name})``；坏 base64 跳过。"""
    imgs: list = []
    src_map: dict = {}
    for b in root.iter():
        if _local(b.tag) != "binary":
            continue
        bid = str(b.get("id") or "").strip()
        ct = str(b.get("content-type") or "image/jpeg").strip().lower()
        raw = (b.text or "").strip()
        if not bid or not raw:
            continue
        try:
            data = base64.b64decode(raw, validate=False)
        except Exception:                              # noqa: BLE001 —— 坏 base64 跳过
            continue
        if not data:
            continue
        name = f"images/b{len(imgs):04d}.{_EXT_OF.get(ct, 'jpg')}"
        imgs.append({"name": name, "media_type": ct or "image/jpeg", "data": data})
        src_map["#" + bid] = name
    return imgs, src_map


def _render(el, src_map: dict) -> str:
    """把一个 FB2 元素渲染成 HTML 片段（**含它自己的 tail**）。未知元素透明（只渲染子节点）。"""
    name = _local(el.tag)
    if name == "image":
        src = src_map.get(_href(el))
        return (f'<img src="{_attr_escape(src)}"/>' if src else "") + _esc(el.tail)
    if name == "empty-line":
        return "<br/>" + _esc(el.tail)
    if name == "a":
        href = _href(el)
        inner = _render_inner(el, src_map)
        if not href or href.startswith("#"):
            # 锚指向脚注（本期不展开 notes body）⇒ 退成纯文本，避免悬空链接
            return inner + _esc(el.tail)
        return f'<a href="{_attr_escape(href)}">{inner}</a>' + _esc(el.tail)
    if name in ("epigraph", "cite"):
        return f"<blockquote>{_render_inner(el, src_map)}</blockquote>" + _esc(el.tail)
    if name == "poem":
        return f'<div class="poem">{_render_inner(el, src_map)}</div>' + _esc(el.tail)
    if name == "stanza":
        return f'<div class="stanza">{_render_inner(el, src_map)}</div>' + _esc(el.tail)
    if name == "v":
        return f"<p>{_render_inner(el, src_map)}</p>" + _esc(el.tail)
    if name in ("table", "tr", "td", "th"):
        return f"<{name}>{_render_inner(el, src_map)}</{name}>" + _esc(el.tail)
    tag = _INLINE.get(name)
    if tag:
        cls = f' class="{_CLASS_OF[name]}"' if name in _CLASS_OF else ""
        return f"<{tag}{cls}>{_render_inner(el, src_map)}</{tag}>" + _esc(el.tail)
    # 未知元素 / 结构元素（section / title 等）：透明渲染子节点，保留文本与 tail
    return _render_inner(el, src_map) + _esc(el.tail)


def _render_inner(el, src_map: dict) -> str:
    out = [_esc(el.text) if el.text else ""]
    for ch in list(el):
        out.append(_render(ch, src_map))
    return "".join(out)


def _split_chapters(root, src_map: dict) -> list:
    """把 ``<body>`` 切成章：带 ``<title>`` 的 ``<section>`` = 一章，其余内容并入当前章。

    规则：无 title 的 section 递归展开（其内容进入当前章）；收尾后**丢掉没有可见内容的章**
    （"第一部"这类纯容器），再给无标题章补 ``第 N 章``（过滤**之后**编号 ⇒ 0 基连续）。
    脚注 body（``<body name="notes">``）本期**跳过**（如实记在「没做」）。
    """
    bodies = [b for b in _children(root, "body")
              if str(b.get("name") or "").strip().lower() not in ("notes",)]
    chapters: list = []
    cur = {"title": "", "parts": []}

    def switch(title: str) -> None:
        nonlocal cur
        chapters.append(cur)
        cur = {"title": title, "parts": []}

    def walk(node) -> None:
        for ch in list(node):
            name = _local(ch.tag)
            if name == "section":
                t = _child(ch, "title")
                if t is not None:
                    switch(_text_of(t))
                walk(ch)
            elif name == "title":
                continue                # title 已用作章题，不重复渲染
            else:
                frag = _render(ch, src_map)
                if frag:
                    cur["parts"].append(frag)

    for b in bodies:
        walk(b)
    chapters.append(cur)

    def has_content(parts: list) -> bool:
        joined = "".join(parts)
        return bool(re.search(r"<img\b", joined)) or bool(re.sub(r"<[^>]+>", "", joined).strip())

    kept = [c for c in chapters if has_content(c["parts"])]
    return [{"title": c["title"] or f"第 {i + 1} 章", "html": "".join(c["parts"])}
            for i, c in enumerate(kept)]


def _meta_of(root, src: pathlib.Path) -> dict:
    """``<description><title-info>`` → ``build_epub`` 的 meta（缺项回落文件名 / 中文）。"""
    title, author, lang, annotation = "", "", "", ""
    for desc in root.iter():
        if _local(desc.tag) != "description":
            continue
        ti = _child(desc, "title-info")
        if ti is None:
            continue
        bt = _child(ti, "book-title")
        if bt is not None:
            title = _text_of(bt)
        names = []
        for au in _children(ti, "author"):
            parts = [_text_of(x) for x in list(au)
                     if _local(x.tag) in ("first-name", "middle-name", "last-name", "nickname")]
            nm = " ".join(p for p in parts if p).strip()
            if nm:
                names.append(nm)
        author = ", ".join(names)
        lg = _child(ti, "lang")
        if lg is not None:
            lang = _text_of(lg)
        an = _child(ti, "annotation")
        if an is not None:
            annotation = _text_of(an)
        break
    return {"title": title or src.stem, "author": author or "未知",
            "language": lang or "zh", "description": annotation}


def _cover_rel(root, src_map: dict) -> str:
    """``<coverpage><image l:href="#id">`` → 派生 EPUB 里那个图片条目名；没有回空串。"""
    for cp in root.iter():
        if _local(cp.tag) != "coverpage":
            continue
        for im in cp.iter():
            if _local(im.tag) == "image":
                rel = src_map.get(_href(im))
                if rel:
                    return rel
    return ""


# ---------------- 缓存判定 / 构建 ----------------

def _lookup(cdir: pathlib.Path, fp: str, src: pathlib.Path):
    """``("hit", 产物路径, "epub")`` / ``("locked", None, "")`` / ``("miss", None, "")``。"""
    st = _read_state(cdir)
    recover = _recover_available()
    if (not st or st.get("fingerprint") != fp or st.get("rule") != RULE_VERSION
            or bool(st.get("recover")) != recover):
        return "miss", None, ""
    if st.get("status") != "ok" or not st.get("rel"):
        return "locked", None, ""
    target = cdir / str(st["rel"])
    if not target.is_file():
        # 产物被人手工删了：视同未命中，重新构建（**不是**错误）
        return "miss", None, ""
    return "hit", target, "epub"


def _build(book: dict, src: pathlib.Path, bid: str, cdir: pathlib.Path, fp: str):
    """真去解析 + 组装（调用方已在 `_BUILD_LOCK` 里，且已双检过）。"""
    try:
        size = src.stat().st_size
    except OSError as e:
        _log_failed(src, e)
        return None, ""
    if size > SOURCE_MAX_BYTES:
        _write_state(cdir, {"status": "failed", "fingerprint": fp, "rule": RULE_VERSION,
                            "recover": _recover_available(),
                            "reason": f"source > {SOURCE_MAX_BYTES} bytes"})
        return None, ""

    parent = cdir.parent
    parent.mkdir(parents=True, exist_ok=True)
    _sweep(parent, bid)
    stage = parent / f".stage-{bid}-{os.getpid()}-{int(time.time() * 1000)}"
    try:
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        text, info = pipeline.decode_file(src)         # 唯一的编码探测 + 读取实现
        root = _parse(text)
        if root is None or _local(root.tag) != "fictionbook" or not _children(root, "body"):
            raise ValueError("不是可解析的 FB2（缺少 FictionBook 根或 body）")
        imgs, src_map = _collect_images(root)
        chapters = _split_chapters(root, src_map)
        if not chapters:
            raise ValueError("FB2 正文为空")
        meta = _meta_of(root, src)
        cover_rel = _cover_rel(root, src_map)
        cover_path = None
        if cover_rel:
            data = next((im["data"] for im in imgs if im["name"] == cover_rel), None)
            if data:
                cover_path = stage / "cover.jpg"
                cover_path.write_bytes(data)
        epub_builder.build_epub(
            meta,
            [{"title": c["title"], "body_html": c["html"]} for c in chapters],
            str(stage / EPUB_NAME),
            css=_FB2_CSS, cover=str(cover_path) if cover_path else None,
            nav=False, images=imgs)
        _write_state(stage, {"status": "ok", "fingerprint": fp, "rule": RULE_VERSION,
                             "recover": _recover_available(), "rel": EPUB_NAME, "kind": "epub",
                             "encoding": info.get("encoding"), "undecodable": info.get("undecodable"),
                             "chapters": len(chapters)})
        _swap_in(stage, cdir)
        return cdir / EPUB_NAME, "epub"
    except Exception as e:                             # noqa: BLE001 —— 坏书不能把接口打成 500
        shutil.rmtree(stage, ignore_errors=True)
        _write_state(cdir, {"status": "failed", "fingerprint": fp, "rule": RULE_VERSION,
                            "recover": _recover_available(), "reason": str(e)[:160]})
        _log_failed(src, e)
        return None, ""


def read_target(book: dict, *, path=None, root=None):
    """这本书的**读目标**：``(派生 EPUB 路径, "epub")`` 或 ``(None, "")``。

    **五个读点都必须问这里**（详情页目录表 / 单章正文 / 书内资源 / 书内样式 / 进度的 CFI）：
    「这本书的正文其实在哪个文件里」只允许有一处答案 —— 判据写两处迟早对不上
    （`mobicache.read_target` 那一段说透了这件事）。

    非 `.fb2` / 文件不在 / 无 book_id ⇒ ``(None, "")``（调用方各自回落既有行为）。
    """
    p = _src_path(book, path, root)
    if p.suffix.lower() not in EXTS or not p.is_file():
        return None, ""
    bid = str(book.get("id") or "")
    if not bid:
        return None, ""
    try:
        fp = _fingerprint(p)
    except OSError:
        return None, ""
    cdir = _cache_dir(bid)

    verdict, target, kind = _lookup(cdir, fp, p)
    if verdict == "hit":
        return target, kind
    if verdict == "locked":
        return None, ""

    with _BUILD_LOCK:
        verdict, target, kind = _lookup(cdir, fp, p)
        if verdict == "hit":
            return target, kind
        if verdict == "locked":
            return None, ""
        return _build(book, p, bid, cdir, fp)


def unreadable_reason(book: dict, *, path=None, root=None) -> str:
    """读不了时的**如实**说明（读点报错文案的唯一来源）。"""
    bid = str(book.get("id") or "")
    if bid:
        s = _read_state(_cache_dir(bid))
        if s.get("status") == "failed" and s.get("reason"):
            return f"这本书读不了：{s['reason']}"
    return "这本书读不了（FB2 解析没有产出可读内容）"


def has_embedded_cover(path) -> bool:
    """这本 `.fb2` 有没有内嵌封面（**廉价头部扫描**，不做整本解析）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(_HEAD_SCAN_BYTES)
    except OSError:
        return False
    return bool(_COVER_RE.search(head))


# ---------------- 目录 ----------------

def chapters(book: dict, *, path=None, root=None) -> list:
    """这本书的**本地目录**（形状与 `library._reading_list` 一致：``[{volume, chapters}]``）。

    派生 EPUB 与真 EPUB 在这一层没有区别 ⇒ 直接复用 `library._reading_list`（index = spine
    下标，与阅读进度 / 批注 / 书签的坐标系一致）。
    """
    target, _kind = read_target(book, path=path, root=root)
    if target is None:
        return []
    from . import library      # 延迟导入：library.book_detail 里会 import 本模块
    return library._reading_list(target)
