"""EPUB CFI（EPUB CFI / Canonical Fragment Identifier）生成与解析（第 54 期）。

目标：把阅读进度从「章序号 + 全书百分比」升级到「**章内字符偏移**」的精确坐标，
标准载体就是 CFI：``epubcfi(/6/{spine步}!/4/{元素步...}/{文本步}:{字符偏移})``。

三个入口（``core/epub_cfi`` 是**位置换算的唯一真值源**）：

- :func:`cfi_for_position` —— ``(spine 序号, 章内字符偏移)`` → CFI；
- :func:`position_from_cfi` —— CFI → ``(spine 序号, 章内字符偏移)``，解析不了 ⇒ ``None``；
- :func:`cfi_to_xpointer` / :func:`locator_from_cfi` —— 取 DocFragment 序号的兼容层，
  服务 KOReader 互通（见 koreader.py：**下发仍用章首 XPointer**，KOReader 的 kosync
  progress 只认 XPointer，真 CFI 下发会破坏它的解析 —— 章内精度由 ``percentage``
  兜底，这是相对原计划的**刻意保守**）。

实现口径：

- **字符偏移 = 渲染正文的 textContent 长度坐标**（前后端同尺度）：后端在解析出的
  DOM 上按文档序累计文本节点长度，前端用 ``contentRef.textContent.length`` 换算
  —— 两侧吃的是同一份正文（``chapter_html`` 只改写资源 URL，不动文本）。
- **解析用标准库 ``xml.etree``**：EPUB 内容文档本就要求良构 XML，不引新依赖。
  真世界的坏书（未转义实体 / DOCTYPE）做最小预处理后仍解析不了 ⇒ 返回空串 /
  ``None``，进度照旧走百分比 —— **宁可少个精确坐标，不许让保存进度失败**。
- spine 序号与 ``library._spine`` 同源（``chapter_html`` 的 index 就是它）；
  DOM 解析结果按 ``(文件, spine 序号, mtime)`` 缓存（进度保存是热路径的旁路，
  同一章反复读写不该反复解压）。
"""
import html as _html
import pathlib
import re
import zipfile
import xml.etree.ElementTree as ET

#: 完整 CFI 的外壳（``epubcfi( … )``）
_CFI_BODY = re.compile(r"^epubcfi\((.*)\)$", re.S)
#: spine 步（``/6/{2·(spine 序号+1)}!``）—— /6 = OPF 的 spine 元素（metadata /2、
#: manifest /4、spine /6 的标准排布），第 i 个 spine 项（0 起）= ``2·(i+1)``
_SPINE_STEP = re.compile(r"/6/(\d+)!")
#: 末尾的 ``:{字符偏移}``
_TAIL_OFFSET = re.compile(r":(-?\d+)\s*$")

#: DOM 解析缓存上限（条目数）。超出即整体清空 —— 进度路径只会命中最近那一章。
_CACHE_MAX = 32
_CACHE: dict = {}


def _local(tag: str) -> str:
    """剥掉 XML 命名空间：``{http://…}body`` → ``body``。"""
    return str(tag).rsplit("}", 1)[-1].lower()


def _dom_children(el) -> list:
    """把 ET 的 text/tail 模型还原成 DOM childNodes 序列。

    ET 把「标签之间的文本」挂在父元素的 .text / 子元素的 .tail 上，而 CFI 的步序
    数的是 DOM 的**孩子节点**（元素 = 偶数步，文本 = 奇数步）—— 两者必须对齐，
    否则生成的步序号在解析侧对不回去。
    """
    out = []
    if el.text:
        out.append(("t", el.text))
    for ch in list(el):
        out.append(("e", ch))
        if ch.tail:
            out.append(("t", ch.tail))
    return out


def _chunks(el, path=()):
    """按文档序产出文本块 ``(元素步元组, 文本步, 文本, 全局起点)``。"""
    counter = 0

    def walk(node, path):
        nonlocal counter
        for i, (kind, item) in enumerate(_dom_children(node)):
            if kind == "t":
                if item:
                    yield (path, 2 * i + 1, item, counter)
                    counter += len(item)
            else:
                yield from walk(item, path + (2 * (i + 1),))

    yield from walk(el, path)


def _body_of_doc(path, spine_index: int):
    """读 spine 第 ``index`` 个文档并解析出 body 元素（带缓存）；失败 ⇒ None。"""
    p = pathlib.Path(path)
    try:
        mtime = p.stat().st_mtime
        from . import library  # 延迟导入：library 链着 db / config，别在 import 期拉
        spine = library._spine(p)
        if not (0 <= int(spine_index) < len(spine)):
            return None
        key = (str(p), int(spine_index), mtime)
        cached = _CACHE.get(key)
        if cached is not None:
            # None 也缓存（坏书反复读不反复解析）；Element 的真值判断已弃用，
            # 必须用 ``is not None`` 判缓存命中
            return cached if cached is not None else None
        with zipfile.ZipFile(p) as z:
            raw = z.read(spine[int(spine_index)]).decode("utf-8", "ignore")
        root = _parse(raw)
        body = None
        if root is not None:
            if _local(root.tag) == "body":
                body = root
            else:
                body = next((c for c in root.iter() if _local(c.tag) == "body"), None)
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        # None 也缓存（坏书反复读不反复解析），读的时候 ``or None`` 还原
        _CACHE[key] = body
        return body
    except Exception:
        return None


def _parse(raw: str):
    """宽容解析：剥 DOCTYPE、把 HTML 命名实体转成数字引用。失败 ⇒ None。"""
    try:
        raw = re.sub(r"<!DOCTYPE[^>]*>", "", raw, flags=re.I | re.S)

        def _ent(m):
            name = m.group(1) + ";"
            cp = _html.entities.html5.get(name)
            if cp is None:
                return m.group(0)
            return "&#" + str(ord(cp)) + ";"

        raw = re.sub(r"&([a-zA-Z][a-zA-Z0-9]+);", _ent, raw)
        return ET.fromstring(raw)
    except Exception:
        return None


def cfi_for_position(path, spine_index: int, char_offset: int) -> str:
    """(spine 序号, 章内字符偏移) → CFI；文档解析不了 / 偏移越界 ⇒ ``''``。"""
    body = _body_of_doc(path, int(spine_index))
    if body is None:
        return ""
    chunks = list(_chunks(body))
    if not chunks:
        return ""
    off = max(0, int(char_offset))
    last = chunks[-1]
    off = min(off, last[3] + len(last[2]))          # 恰好读到末尾 ⇒ 锚最后一块
    chunk = next((c for c in chunks if c[3] <= off < c[3] + len(c[2])), last)
    path_steps, text_step, _, gstart = chunk
    inner = "".join("/%d" % s for s in path_steps)
    return "epubcfi(/6/%d!/4%s/%d:%d)" % (
        2 * (int(spine_index) + 1), inner, text_step, off - gstart)


def position_from_cfi(path, cfi) -> "tuple[int, int] | None":
    """CFI → (spine 序号, 章内字符偏移)。形状不对 / spine 越界 / 步序走不到 ⇒ ``None``。"""
    m = _CFI_BODY.match(str(cfi or "").strip())
    if not m:
        return None
    expr = m.group(1)
    sp = _SPINE_STEP.match(expr.lstrip())
    if not sp:
        return None
    s = int(sp.group(1))
    if s < 2 or s % 2:
        return None
    spine_index = s // 2 - 1
    body = _body_of_doc(path, spine_index)
    if body is None:
        return None
    rest = expr[sp.end():]
    mo = _TAIL_OFFSET.search(rest)
    if not mo:
        return None
    local = int(mo.group(1))
    steps = [int(x) for x in re.findall(r"/(\d+)", rest[:mo.start()])]
    if len(steps) < 2 or steps[0] != 4:             # 必须从 body（/4）开始
        return None
    text_step = steps[-1]
    if text_step % 2 == 0:
        return None
    # 直接在**整章 body** 的文本块表上按 (父元素路径, 文本步) 匹配 ——
    # gstart 是全文 textContent 坐标系的起点，绝不能下钻后局部重算
    # （那是偏移「变小了」的坐标空间，往返就回不去了）。
    want = tuple(steps[1:-1])
    for path_steps, ts, text, gstart in _chunks(body):
        if path_steps == want and ts == text_step:
            return (spine_index, max(0, gstart + max(0, min(local, len(text)))))
    return None


def locator_from_cfi(cfi) -> int:
    """CFI → spine 序号（0 起）；解析不出 ⇒ -1。纯字符串操作，不碰文件。"""
    m = _SPINE_STEP.search(str(cfi or ""))
    if not m:
        return -1
    s = int(m.group(1))
    if s < 2 or s % 2:
        return -1
    return s // 2 - 1


def cfi_to_xpointer(cfi) -> str:
    """CFI → 章首 XPointer（KOReader 兼容层）：只取 DocFragment 序号，与
    ``koreader.make_xpointer`` 同一形状；章内精度由 ``percentage`` 兜底。"""
    loc = locator_from_cfi(cfi)
    if loc < 0:
        return ""
    return "/body/DocFragment[%d]/text().0" % (loc + 1)
