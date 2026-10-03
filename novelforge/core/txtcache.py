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

⚠️ **形态一经确定就锁定**（`state.json` 记**源文件指纹 + 分章规则版本**）：两条路线的
章节 index 都是 0 基、索引空间已对齐（派生 EPUB 用 ``nav=False`` 组装，spine 不含 nav
目录页），但**目录条目数仍可能因分章细节而不同**；为免「今天有 EPUB、清个缓存变原生」时
章节号漂移让既有批注跳错章，只在**源文件本身变化**（mtime/size 变）**或分章规则版本变化**
时才重建。后者是第 62 期补的：规则改了而源一个字没动时，光比源指纹会一直命中旧派生件，
**改了规则看不见效果**。

分章/编码/组装三处都不另写实现：`detect`（唯一分章真值源）、
`pipeline.decode_file`（唯一编码探测 + 读取；第 89 期起它**绝不静默丢字节**，
坏字节以 U+FFFD 呈现并计数上报，见 `decode_info`）、`epub_builder.build_epub`（唯一组装）。
"""
import json
import pathlib
import time

from .. import config
from . import detect, epub_builder, pipeline, preprocess, reading_list

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

#: 解码报告缓存（键 = 源路径 + 指纹 + 编码判据版本）。第 89 期加：章节接口每次都要问
#: 「这次用了什么编码、有几个字节解不出」（对用户可见，见 :func:`decode_info`），
#: 不能每次请求都重解一遍全文。只存报告（不含全文），体积可忽略。
_DECODE_CACHE: dict = {}

#: **分章规则版本**（跟随 `detect.CHAPTER_RULE_VERSION`）。第 62 期加：只比源指纹不够 ——
#: 规则改了而源文件一个字节没动时，旧派生 EPUB 的目录与新口径不一致，可缓存照样命中、
#: 原样返回，**用户改了规则却看不见效果**。版本号进指纹即触发重建。
RULE_VERSION = detect.CHAPTER_RULE_VERSION

#: **编码判据版本**（跟随 `pipeline.ENCODING_RULE_VERSION`）。第 72 期加：正文是从源文件
#: **解码**出来的，所以「判据改了、源文件一个字节没动」时，已缓存的正文（可能是乱码）
#: 必须失效 —— 光比源指纹会一直命中，**改了看不见效果**（与 `RULE_VERSION` 同一个道理）。
#: 它也进 `server._chapter_cached` 的 Redis 键（原生路线没有派生件指纹可用）。
ENC_RULE_VERSION = pipeline.ENCODING_RULE_VERSION

#: 规则升级导致重建时，活动日志里 `file` 一栏用的**固定主体**。见 :func:`_log_rule_rebuild`。
FILE_LABEL = "TXT 派生缓存"


def _cache_dir(book_id: str) -> pathlib.Path:
    return config.CACHE_DIR / CACHE_SUBDIR / str(book_id)


def _fingerprint(path: pathlib.Path) -> str:
    st = path.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _log_rule_rebuild(path: pathlib.Path) -> None:
    """分章规则升级引起的重建：记一条活动日志。

    ``file`` 传**固定标签**而不是书名 —— 活动日志的合并键是「动作 + 结果 + 主体」
    （见 `activity_log._merge_key`），主体固定才能把一次升级里逐本发生的重建并成
    **一条**（第 61 期合并，默认 10s 尾随窗口，每来一条窗口从头计时），界面上一行
    「已按新规则重建 ×N」。逐本各写一条会把活动日志刷屏，反而没人看得见。
    """
    try:
        from . import activity_log as al
        al.log(al.ACTION_CONVERT, FILE_LABEL, al.STATUS_OK,
               detail=f"分章规则 v{RULE_VERSION} 已生效：{path.name}", source="txtcache")
    except Exception:                                  # noqa: BLE001 —— 记日志失败不该影响阅读
        pass


def _log_unreadable(path: pathlib.Path, err: Exception) -> None:
    """正文读不出（编码判错 / 分章只剩空正文 / 组装失败）时留一条活动日志。

    第 72 期加：此前这条路是**静默**的 —— 只在 `state.json` 里记一个 ``failed``，
    阅读器照样渲染空章节，用户看到满屏乱码/空白却没有任何提示。写一条日志让它在
    「活动日志」页可见。

    主体用**源文件名**（不像 :func:`_log_rule_rebuild` 那样用固定标签）：出问题的
    通常是某一本书，用户要知道是**哪本**；不同书之间也不该互相合并。

    写日志失败不该影响阅读，故整段包住。
    """
    try:
        from . import activity_log as al
        al.log(al.ACTION_CONVERT, path.name, al.STATUS_FAIL,
               detail=f"正文读不出，已回落原生分章：{str(err)[:120]}", source="txtcache")
    except Exception:                                  # noqa: BLE001
        pass


def _read_state(cdir: pathlib.Path) -> dict:
    try:
        return json.loads((cdir / STATE_NAME).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_state(cdir: pathlib.Path, state: dict) -> None:
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        # ``enc_rule`` 在这里**统一**写入（而不是让每个调用方各写一遍）：编码判据版本
        # 是缓存有效性的一个分量，漏写就等于「判据改了但缓存照旧命中」。
        (cdir / STATE_NAME).write_text(
            json.dumps({**state, "enc_rule": ENC_RULE_VERSION, "at": time.time()},
                       ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        # 状态写不进去不是致命错：下次调用重新尝试（最坏是重复转换一次）
        pass


def _src_path(book: dict, path=None, root=None):
    if path is not None:
        return pathlib.Path(path)
    from . import library  # 延迟导入：library 顶层会 import 本模块的调用方链
    return (root or library.root_of(book)) / book["name"]


def _read(path: pathlib.Path) -> "tuple[str, dict]":
    """读全文并带回**解码报告**：编码探测 / 读取复用 `pipeline.decode_file`（唯一实现，禁第二处）。

    第 89 期：不再用 ``errors="ignore"`` —— 那条路会让解不出的字节**无声消失**，
    写进派生 EPUB 与章节缓存，读者拿到的是有洞且位置漂移的正文却不报错。
    `pipeline.decode_file` 会候选逐个严格试解、读不干净就如实计数。

    报告顺手留一份在 `_DECODE_CACHE`：正文读一次就够，但 :func:`decode_info`
    会被章节接口**每章问一次**，不能每次都重解全文。
    """
    text, info = pipeline.decode_file(path)
    try:
        key = (str(path), _fingerprint(path), ENC_RULE_VERSION)
        if len(_DECODE_CACHE) >= _SPLIT_CACHE_MAX:
            _DECODE_CACHE.clear()
        _DECODE_CACHE[key] = info
    except Exception:                                  # noqa: BLE001 —— 缓存失败不影响读
        pass
    return text, info


def decode_info(book: dict, *, path=None, root=None) -> dict:
    """这本书 TXT 源的**解码报告**（``{encoding, undecodable, positions}``）；非 TXT / 读不到回空 dict。

    第 89 期加，供章节接口把「本次用了什么编码、有几个字节解不出」如实带给前端与调用方
    （本仓纪律：**识别结果必须对用户可见**，不许静默猜测 / 静默丢弃）。命中派生件 state
    （里面记了编码与坏字节数）或 `_DECODE_CACHE` 时零成本；否则现读一次。
    """
    p = _src_path(book, path, root)
    if p.suffix.lower() != ".txt" or not p.is_file():
        return {}
    try:
        fp = _fingerprint(p)
    except Exception:                                  # noqa: BLE001
        return {}
    # ① 派生件 state：建派生 EPUB 时已把编码与坏字节数写进去（省一次全量解码）。
    bid = str(book.get("id") or "")
    if bid:
        state = _read_state(_cache_dir(bid))
        if (state.get("fingerprint") == fp and state.get("enc_rule") == ENC_RULE_VERSION
                and state.get("encoding")):
            return {"encoding": str(state.get("encoding") or ""),
                    "undecodable": int(state.get("undecodable") or 0),
                    "positions": []}
    # ② 内存缓存（原生分章路线没有派生件指纹可用）。
    hit = _DECODE_CACHE.get((str(p), fp, ENC_RULE_VERSION))
    if hit is not None:
        return hit
    # ③ 现读一次（会顺带把报告写进 `_DECODE_CACHE`）。
    try:
        _text, info = _read(p)
    except Exception:                                  # noqa: BLE001
        return {}
    return info


def _chapters(book: dict, path: pathlib.Path) -> list:
    """（带指纹缓存的）原生分章结果 —— 两条路线共用同一份切分。

    缓存键里必须带上 ``RULE_VERSION``：否则规则升级后即使派生件重建了，
    切分仍会从这份缓存里原样取出**旧规则的结果**（源指纹没变，键就一样）。
    ``ENC_RULE_VERSION`` 同理 —— 切分是在**解码后的文本**上做的，编码判据一变，
    同一份字节切出来的章也不同。
    """
    fp = f"{_fingerprint(path)}|v{RULE_VERSION}|e{ENC_RULE_VERSION}"
    key = (str(path), fp)
    hit = _SPLIT_CACHE.get(key)
    if hit is not None:
        return hit
    from .. import config as _cfg
    raw, _info = _read(path)
    chapters = detect.detect_chapters_cfg(raw, _cfg.load_config(), False) if raw.strip() else []
    if len(_SPLIT_CACHE) >= _SPLIT_CACHE_MAX:
        _SPLIT_CACHE.clear()
    _SPLIT_CACHE[key] = chapters
    return chapters


def derived_epub(book: dict, *, path=None, root=None):
    """TXT 书 → 派生 EPUB 路径；不可转 / 失败 ⇒ ``None``（调用方回落原生分章）。

    命中规则：源指纹没变**且编码判据版本没变**且上次成功 ⇒ 直接返回既有缓存（**不重复转换**）；
    源指纹没变、但上次失败 ⇒ 仍返回 ``None``（保持形态稳定，别一会儿 EPUB 一会儿原生）。
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
    # 三个分量缺一不可：源指纹（源变了）、分章规则（切法变了）、**编码判据**（解出来的
    # 文本变了）。老 state.json 没有 ``enc_rule`` ⇒ 这里不命中 ⇒ 重建一次；这正是
    # 「已缓存成 ok 的乱码派生件」唯一的失效通道。
    if (state.get("fingerprint") == fp and state.get("rule") == RULE_VERSION
            and state.get("enc_rule") == ENC_RULE_VERSION):
        if state.get("status") != "ok":
            return None
        epub = cdir / EPUB_NAME
        return epub if epub.exists() else None
    # 走到这里有两种可能：源变了，或**分章规则版本变了**（源指纹没动）。后者要留痕 ——
    # 否则用户升完级只看到目录变了，不知道是谁改的。
    if state.get("fingerprint") == fp:
        _log_rule_rebuild(p)

    if p.stat().st_size > SOURCE_MAX_BYTES:
        _write_state(cdir, {"status": "failed", "fingerprint": fp, "rule": RULE_VERSION,
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
        # 第 89 期：把「本次解码用的编码 + 有几个字节解不出」一并写进 state ——
        # ① 章节接口靠它把结果如实带给阅读器（`decode_info` 优先读这里，省一次全量解码）；
        # ② 缓存有效性判定也顺带把这两个值留下痕迹。
        info = decode_info(book, path=p)
        _write_state(cdir, {"status": "ok", "fingerprint": fp, "rule": RULE_VERSION,
                            "chapters": len(chapters),
                            "encoding": info.get("encoding", ""),
                            "undecodable": int(info.get("undecodable") or 0)})
        return final
    except Exception as e:
        _write_state(cdir, {"status": "failed", "fingerprint": fp, "rule": RULE_VERSION,
                            "reason": str(e)[:160]})
        # 只在**真正尝试过并失败**时记一条：状态落盘后，同一份源的下一次请求会走前面的
        # 命中分支直接 ``return None``，不会重复写日志（与 `_log_rule_rebuild` 同量级）。
        _log_unreadable(p, e)
        return None


def native_chapters(book: dict, *, path=None, root=None) -> list:
    """原生分章目录（与 `library._reading_list` **同形状**）：``[{volume, kind?, chapters}]``。

    索引 0 基、无 nav 占位 —— 与 :func:`native_chapter_html` 的 index 同一空间。

    ⚠️ **第 85 期起不再硬编码单个「正文」卷**：分章结果里 ``第X卷`` 这类卷首会被
    :func:`novelforge.core.reading_list.build_reading_list` 按**标题形态**认出来并分组
    （`detect` 的 ``vol`` 字段只标在卷首那一章身上，不能直接按值分组，得「遇卷首切一卷」）。
    此前 TXT 书**完全看不到卷**，正是因为这里把整本塞进一个「正文」卷。
    无名段的 ``volume`` 是空串（不再是「正文」）—— 显示层统一把无名段叫「正文」
    （见前端 `lib/chapterGroups.ts`），数据侧不留一个假卷名。
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
    entries: list = [
        {"title": (c.get("title") or f"第 {i + 1} 节"), "index": i, "depth": None}
        for i, c in enumerate(chapters)
    ]
    return reading_list.build_reading_list(entries)


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
