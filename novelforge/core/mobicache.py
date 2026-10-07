"""MOBI / AZW3 **直读解包缓存**（第 110 期）：不做转换，就地解出书自身的正文来读。

第 110 期的用户口径是「mobi 直接阅读，不进行转化」。`.mobi` / `.azw3`（以及 `.azw`）此前在
格式能力矩阵里的「阅读」一栏是 **❌ 需转换** —— 本仓整条阅读链路（`library._reading_list` /
`library.chapter_html` / `library.chapter_assets` / `epub_cfi`）都建立在「EPUB zip + spine」上，
而 MOBI 既不是 zip 也不长成 EPUB。本期的做法是**解包（unpack）**而不是转换：

- **KF8 / AZW3**（解包产出 `.epub`）⇒ 把解包出来的 EPUB 直接喂既有链路。目录 / 正文 / 插图 /
  书内样式 / **CFI 精确位置** / 批注**零新代码**复用。`mobi8/<base>.epub` 是书自身的 KF8
  内容由 KindleUnpack 抽取出来的结果，**我们这一侧没有转换器**。
- **纯 MOBI6**（解包只产出 `mobi7/book.html`）⇒ 复用既有分章真值源（`detect`）与段落渲染
  （`preprocess`），单章形状与 `txtcache.native_chapter_html` 逐字对齐。**如实降级**：这条路
  拿不到插图与书内样式（HTML 里的 `<img src>` 指向解包目录里的文件，不在 zip 里）。
- **Print Replica**（解包产出 `<base>.001.pdf`）⇒ 交回既有 PDF 阅读路线，本模块不处理。

「解包 ≠ 转换」的落点：产物落在 ``CACHE_DIR/mobi-unpack/<book_id>/``，**不进书库、不新增书目
条目、不写回源文件**（源文件全程只读），可随时重建、可随时整个删掉。这条与 `txtcache` 的
``txt-epub/`` 是同一个形态：派生缓存，不是第二本书。

⚠️ **形态一经确定即锁定**（`state.json` 记 **源指纹 + 本模块规则版本 + `mobi` 包版本**）。
三个分量缺一不可，理由与 `txtcache.RULE_VERSION` / `ENC_RULE_VERSION` 相同：源文件一个字节
没动、而「切法」或「抽取器」变了时必须重建，否则**改了看不见效果**（第 62 / 72 期的教训）。
包版本是本期特有的分量 —— 读到什么由 `mobi` 的抽取结果决定，换了版本得出的目录可能不同。

⚠️ **它不是硬依赖**：`mobi` 缺失时 :func:`state` 如实标 ``available: False``，读点据此回
「MOBI 直读需要 mobi（未安装）」，**绝不假装能读、也不 500** —— 与 `jssandbox.state()` /
`lxml_available()` / 缺 bsdtar 时 `.cbr` 报 503 是同一条纪律。
"""
import json
import os
import pathlib
import re
import shutil
import threading
import time

from .. import config
from . import detect, pipeline, preprocess, reading_list

#: 本模块认的扩展名。`.azw` 是未加密的 Mobipocket（Kindle 早期格式），与 `.mobi` 同一条解包
#: 路径 —— 它此前**不在任何白名单里**（第 110 期补进 `library.BOOK_EXTS` / `_EBOOK_EXTS`）。
EXTS = (".mobi", ".azw3", ".azw")

#: 缓存子目录名（小写 / 连字符，与 `txt-epub/`、`pdf/`、`authors/` 同风格）
CACHE_SUBDIR = "mobi-unpack"
STATE_NAME = "state.json"

#: **本模块的规则版本**：认产物的方式、HTML 路线的分章口径，凡影响「读到什么」的改动都 +1。
#: 它进 `state.json`，源文件没动而口径变了时触发重建（与 `txtcache.RULE_VERSION` 同理）。
RULE_VERSION = 1

#: 超过这个大小不解包（KindleUnpack 会把整书正文读进内存）
SOURCE_MAX_BYTES = 200 * 1024 * 1024

#: 抽取器所在的发行包名 —— 只用来**问版本**（进 state 做缓存分量），不 import 它本身。
PKG_NAME = "mobi"

#: 活动日志里 `file` 一栏的固定主体（合并键要稳，理由见 `txtcache._log_rule_rebuild`）
FILE_LABEL = "MOBI 直读解包"

#: 解包是秒级且吃内存的操作，而 `kindleunpack` 有一批**进程级全局**
#: （`DUMP` / `WRITE_RAW_DATA` / `SPLIT_COMBO_MOBIS`，见其 `unpackBook` 开头）。所以并发解包
#: **整体串行化**：不同的书也排队，免得两个线程的抽取相互干扰（解包不常发生，不值得更细的锁）。
_BUILD_LOCK = threading.Lock()

#: HTML 路线的分章缓存（键 = 产物路径 + 指纹 + 规则版本）：详情接口与逐章接口都会调
_SPLIT_CACHE: dict = {}
_SPLIT_CACHE_MAX = 8


# ---------------- 依赖可用性（如实报）----------------

def state() -> dict:
    """`mobi` 抽取器的可用性：``{"available", "version", "reason"}``。

    **本函数是唯一的「能不能直读 MOBI」判据**（读点、测试、文案都问它）。缺包或包坏了都
    如实报出来，不假装能读 —— 见模块文档末尾那条纪律。
    """
    try:
        from importlib.metadata import version as _pkg_version
        ver = str(_pkg_version(PKG_NAME) or "")
    except Exception:                                  # noqa: BLE001 —— 没装 = 常态，不是异常
        return {"available": False, "version": "",
                "reason": f"MOBI 直读需要 {PKG_NAME}（未安装）"}
    try:
        # 只探测能不能 import：真解包时再 import 一次（模块级缓存，第二次是字典查找）
        from mobi.kindleunpack import unpackBook  # noqa: F401
    except Exception as e:                             # noqa: BLE001
        return {"available": False, "version": ver,
                "reason": f"MOBI 直读需要 {PKG_NAME}（不可用：{str(e)[:80]}）"}
    return {"available": True, "version": ver, "reason": ""}


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
        # 状态写不进去不是致命错：下次调用重新尝试（最坏是多解包一次）
        pass


# ---------------- 活动日志 ----------------

def _log_failed(path: pathlib.Path, err) -> None:
    """解不开 / 装不了时留一条活动日志。

    主体用**源文件名**（不像规则升级那样用固定标签）：出问题的是某一本书，用户要知道是哪本。
    写日志失败不该影响阅读，故整段包住（与 `txtcache._log_unreadable` 同款）。
    """
    try:
        from . import activity_log as al
        al.log(al.ACTION_CONVERT, path.name, al.STATUS_FAIL,
               detail=f"MOBI 直读解包失败：{str(err)[:120]}", source="mobicache")
    except Exception:                                  # noqa: BLE001
        pass


def _log_rule_rebuild(path: pathlib.Path, why: str) -> None:
    """抽取器/规则变了引起的重建：记一条活动日志（主体固定，便于同一次升级合并成一行）。"""
    try:
        from . import activity_log as al
        al.log(al.ACTION_CONVERT, FILE_LABEL, al.STATUS_OK,
               detail=f"{why} 已生效：{path.name}", source="mobicache")
    except Exception:                                  # noqa: BLE001
        pass


# ---------------- 产物识别 ----------------

def _product_of(stage: pathlib.Path, stem: str) -> "tuple[str, str]":
    """stage 目录里认产物，返回 ``(相对 stage 的路径, kind)``；认不出回 ``("", "")``。

    kind ∈ ``"epub"`` / ``"html"`` / ``"pdf"``，与 `mobi.extract` 的候选顺序**逐条对齐**
    （EPUB → HTML → PDF，见其 `extract.py:30-38`）；`mobi8/*.epub` 的 glob 是兜底：万一
    抽取器对文件名做了归一，按 `<stem>.epub` 找不到时仍能认出那本就是它。
    """
    ep = stage / "mobi8" / f"{stem}.epub"
    if ep.is_file():
        return ep.relative_to(stage).as_posix(), "epub"
    ht = stage / "mobi7" / "book.html"
    if ht.is_file():
        return ht.relative_to(stage).as_posix(), "html"
    k8 = stage / "mobi8"
    if k8.is_dir():
        for cand in sorted(k8.glob("*.epub")):
            if cand.is_file():
                return cand.relative_to(stage).as_posix(), "epub"
    for cand in sorted(stage.glob(f"{stem}.*.pdf")):
        if cand.is_file():
            return cand.relative_to(stage).as_posix(), "pdf"
    return "", ""


def _sweep(parent: pathlib.Path, bid: str) -> None:
    """清掉上一次崩溃留下的 stage / old 目录（**只清本模块自己造的那些名字**）。"""
    for pat in (f".stage-{bid}-*", f"{bid}.old-*"):
        for stale in parent.glob(pat):
            shutil.rmtree(stale, ignore_errors=True)


def _swap_in(stage: pathlib.Path, final: pathlib.Path) -> None:
    """把 stage 换成 final —— **原子换入**：旧目录先挪走、再 replace、最后删旧的。

    直接往 final 里写是**不行**的：解包中途失败会留下半个目录，而 `state.json` 一旦在
    那里写成 ok，读者拿到的是缺文件的正文。所以一律**先在同卷的临时目录里解完**再换入
    （源不可变 + 临时文件 + `Path.replace` 的既有纪律）。
    """
    old = None
    if final.exists():
        old = final.with_name(f"{final.name}.old-{os.getpid()}-{int(time.time() * 1000)}")
        shutil.rmtree(old, ignore_errors=True)
        final.replace(old)
    try:
        stage.replace(final)
    except OSError:
        # 换入失败就把旧目录放回去：否则这本书的缓存目录整个消失（下次会重解，但没必要）
        if old is not None and old.exists() and not final.exists():
            try:
                old.replace(final)
            except OSError:                            # noqa: BLE001
                pass
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


# ---------------- 缓存判定 / 解包 ----------------

def _lookup(cdir: pathlib.Path, fp: str, src: pathlib.Path):
    """缓存判定，返回 ``("hit", 产物路径, kind)`` / ``("locked", None, "")`` / ``("miss", None, "")``。

    ``locked`` 是**刻意**的：源文件没变、上次就是解不开 ⇒ 不每次请求都重试一遍（解包是秒级
    操作，坏书会被反复触发）。这与 `txtcache` 的「形态锁定，别一会儿 EPUB 一会儿原生」同一
    条纪律 —— 源一改（mtime/size 变）指纹就变，自然解除。
    """
    st = _read_state(cdir)
    if not st or st.get("fingerprint") != fp or st.get("rule") != RULE_VERSION:
        return "miss", None, ""
    if st.get("status") != "ok" or not st.get("rel"):
        return "locked", None, ""
    target = cdir / str(st["rel"])
    if not target.is_file():
        # 产物被人手工删了 / 只删掉了其中几个文件：视同未命中，重新解包（**不是**错误）
        return "miss", None, ""
    pkg = state().get("version")
    if pkg and str(st.get("pkg") or "") != pkg:
        # 换了抽取器版本 ⇒ 旧产物作废重建（目录/分卷可能不同，光比源指纹会一直命中旧的）。
        # ⚠️ 只在**问得到版本**时比：包没了但产物还在盘上时，读它并不需要包。
        _log_rule_rebuild(src, f"解包器 {PKG_NAME} {pkg}")
        return "miss", None, ""
    return "hit", target, str(st.get("kind") or "")


def _build(book: dict, src: pathlib.Path, bid: str, cdir: pathlib.Path, fp: str):
    """真去解包（调用方已在 `_BUILD_LOCK` 里，且已双检过）。"""
    st = state()
    if not st.get("available"):
        _log_failed(src, str(st.get("reason") or "解包器不可用"))
        return None, ""
    try:
        size = src.stat().st_size
    except OSError as e:
        _log_failed(src, e)
        return None, ""
    if size > SOURCE_MAX_BYTES:
        _write_state(cdir, {"status": "failed", "fingerprint": fp, "rule": RULE_VERSION,
                            "pkg": st.get("version"),
                            "reason": f"source > {SOURCE_MAX_BYTES} bytes"})
        return None, ""

    parent = cdir.parent
    parent.mkdir(parents=True, exist_ok=True)
    _sweep(parent, bid)
    stage = parent / f".stage-{bid}-{os.getpid()}-{int(time.time() * 1000)}"
    try:
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        # ⚠️ 刻意**不用** `mobi.extract()`：它把临时目录建在**系统 TEMP**
        # （`tempfile.mkdtemp(prefix="mobiex")`）—— 于是产物要跨卷复制进缓存目录、解包还
        # 依赖 `/tmp` 的容量（NAS 容器上常很小）。这里直接喂它下面那一层的 `unpackBook`，
        # 把自己的 stage 目录给它：**同卷**、可原子换入、不碰任何全局状态。
        # 产物位置与 `extract()` 的三个候选逐条一致（见 `_product_of`）。
        from mobi.kindleunpack import unpackBook
        unpackBook(str(src), str(stage), epubver="A")
        rel, kind = _product_of(stage, src.stem)
        if not rel:
            raise ValueError("解包产物里没有 EPUB / HTML / PDF")
        _write_state(stage, {"status": "ok", "fingerprint": fp, "rule": RULE_VERSION,
                             "pkg": st.get("version"), "rel": rel, "kind": kind})
        _swap_in(stage, cdir)
        return cdir / rel, kind
    except Exception as e:                             # noqa: BLE001 —— 坏书不能把接口打成 500
        shutil.rmtree(stage, ignore_errors=True)
        _write_state(cdir, {"status": "failed", "fingerprint": fp, "rule": RULE_VERSION,
                            "pkg": st.get("version"), "reason": str(e)[:160]})
        _log_failed(src, e)
        return None, ""


def read_target(book: dict, *, path=None, root=None):
    """这本书的**读目标**：``(路径, kind)``，kind ∈ ``"epub"`` / ``"html"`` / ``"pdf"`` / ``""``。

    **四个读点都必须问这里**（详情页的目录表 / 单章正文 / 书内资源与样式 / 进度的 CFI）：
    「这本书的正文其实在哪个文件里」只允许有一处答案 —— 第 87 期那四条不一致
    （抓取封面永远 404、OPDS 给出必然 404 的下载链…）就是同一个判据在四处各写一遍造成的。

    非 MOBI 扩展名 / 文件不在 / 无 book_id ⇒ ``(None, "")``（调用方各自回落既有行为）。
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
        # 双检：等锁期间别人可能已经解好了（解包是秒级操作，这里省掉重复的一遍）
        verdict, target, kind = _lookup(cdir, fp, p)
        if verdict == "hit":
            return target, kind
        if verdict == "locked":
            return None, ""
        return _build(book, p, bid, cdir, fp)


def unreadable_reason(book: dict, *, path=None, root=None) -> str:
    """读不了时的**如实**说明（读点报错文案的唯一来源）。"""
    st = state()
    if not st.get("available"):
        return str(st.get("reason") or f"MOBI 直读需要 {PKG_NAME}（未安装）")
    bid = str(book.get("id") or "")
    if bid:
        s = _read_state(_cache_dir(bid))
        if s.get("status") == "failed" and s.get("reason"):
            return f"这本书解不开：{s['reason']}"
    return "这本书解不开（解包没有产出可读内容）"


# ---------------- 目录 / 单章 ----------------

def chapters(book: dict, *, path=None, root=None) -> list:
    """这本书的**本地目录**（形状与 `library._reading_list` 一致：``[{volume, chapters}]``）。

    `epub` 路线直接复用 `library._reading_list`（解包出的 EPUB 与真 EPUB 在它眼里没有区别）；
    `html` 路线走既有分章器；`pdf` 交回既有 PDF 路线（本模块不认它的目录）。
    """
    target, kind = read_target(book, path=path, root=root)
    if target is None:
        return []
    if kind == "epub":
        from . import library      # 延迟导入：library.book_detail 里会 import 本模块
        return library._reading_list(target)
    if kind == "html":
        return _html_list(target)
    return []


def _html_text(target: pathlib.Path) -> str:
    """解包出的 HTML → 纯文本（块级元素间以换行分隔）。

    编码走 `pipeline.decode_file`（**唯一**的编码探测 + 读取实现）：KindleUnpack 写出的
    `mobi7/book.html` 用的是书上声明的编码，不是想当然的 UTF-8。
    取不到正文（XML 坏到 bs4 也认不出）时原样返回，交给 `detect` 自己去分。
    """
    raw, _info = pipeline.decode_file(target)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text("\n")
    except Exception:                                  # noqa: BLE001 —— 坏 HTML 也要能读
        return re.sub(r"<[^>]+>", "\n", raw)


def _split_html(target: pathlib.Path) -> list:
    """HTML 路线的分章结果（带指纹 + 规则版本的缓存）：``detect`` 的原生形状。"""
    fp = f"{_fingerprint(target)}|v{RULE_VERSION}"
    key = (str(target), fp)
    hit = _SPLIT_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        text = _html_text(target)
    except Exception:                                  # noqa: BLE001
        return []
    chapters = detect.detect_chapters_cfg(text, config.load_config(), False) if text.strip() else []
    if len(_SPLIT_CACHE) >= _SPLIT_CACHE_MAX:
        _SPLIT_CACHE.clear()
    _SPLIT_CACHE[key] = chapters
    return chapters


def _html_list(target: pathlib.Path) -> list:
    """HTML 路线的**目录表**，形状与 `library._reading_list` 一致（``[{volume, chapters}]``）。"""
    chapters = _split_html(target)
    if not chapters:
        return []
    entries = [{"title": (c.get("title") or f"第 {i + 1} 节"), "index": i, "depth": None}
               for i, c in enumerate(chapters)]
    return reading_list.build_reading_list(entries)


def chapter_html(book: dict, index: int, *, path=None, root=None) -> dict:
    """HTML 路线（纯 MOBI6）的单章正文：``{index, total, title, html}``。

    形状与 `txtcache.native_chapter_html` **逐字对齐**（两条"没有 EPUB"的路线读起来要一致）：
    标题也放进正文（EPUB 路线的 `epub_builder` 会给章节加 `<h2>`），越界抛 `IndexError`
    （调用方 `_chapter_read` 翻成 404，与 EPUB 路径同一约定）。

    KF8 路线不走这里 —— 那条由 server 直接把解包出的 EPUB 喂 `library.chapter_html`。
    """
    target, kind = read_target(book, path=path, root=root)
    if kind != "html":
        raise ValueError(f"不是 HTML 路线的 MOBI（kind={kind or '空'}）")
    chapters = _split_html(target)
    i = int(index)
    if i < 0 or i >= len(chapters):
        raise IndexError("章节不存在")
    ch = chapters[i]
    title = ch.get("title") or f"第 {i + 1} 节"
    return {
        "index": i,
        "total": len(chapters),
        "title": title,
        "html": f"<h2>{title}</h2>" + preprocess.paragraphs_to_html(ch.get("body") or ""),
    }
