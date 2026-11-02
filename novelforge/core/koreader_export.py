"""把本项目的批注**导出成 KOReader 的批注文件**（第 234 期）。

## 为什么是「写文件」而不是「kosync 端点」

与 `koreader_anno.py` 的文件头同一套查证结论：官方 kosync **只有进度**，
没有批注端点（`plugins/kosync.koplugin/api.json` 4 个方法、服务端
`config/routes.lua` 同样只有进度）。KOReader 的批注跨设备同步走的是**文件** ——
关书时导出 `<书名>.annotations.lua`（需开 `annotations_export_on_closing`）。

⇒ 本期补的是**反向那一半**：把本项目里的批注写成那个文件，KOReader 下次打开
就能读到（它读文件的逻辑是 `pcall(dofile, file)`）。

## ⚠️ 这是「写用户设备上的文件」—— 三条纪律

1. **只写 KOReader 自己的导出位点**（`export_paths_for` 给的那两处），不新建目录、
   不写别处；
2. **不覆盖用户的文件而不说**：导出前先**读现有文件**，把本项目的批注**并进去**
   （按 `text` + 位置去重），而不是直接盖掉 —— 用户在设备上写的批注不能丢；
3. **默认只算不改**（`apply=False`）：界面上的「导出」按钮要先跑一次 dry-run
   让人看到「会写几个文件、几条批注」，再落盘。

## 格式

与 `koreader_anno.py` 的解析端**逐字对称**（同一份字段名、同一份转义规则）：

- 文件第一行是 ``-- <绝对路径>`` 行注释，第二行 ``return `` 起头（上游
  `util.writeToFile(..., lua_dofile_ready=true)` 的行为 ⇒ 它必须能被 `dofile`）；
- 表一律 ``[键] = 值,`` 逐行、4 空格缩进；
- 字符串走 **Lua 的** `%q` 转义（**不是 JSON 的**）—— 换行是「反斜杠 + 真换行」。

⚠️ **写出来的值必须能被 `koreader_anno.parse()` 读回去**（往返一致）——
否则就是「导出了一堆本项目自己都读不回来的东西」。
"""
from __future__ import annotations

import pathlib
import time

from .koreader_anno import SUFFIX, export_paths_for

#: 本项目的样式 → KOReader 的 ``drawer``（与 `DRAWER_TO_STYLE` 反向）。
#:
#: ⚠️ 只有**确有等价物**的才映射：`highlight` → `lighten`（在文字背景上做记号，
#: 与高亮同义）、`underline` → `underscore`、`strikethrough` → `strikeout`。
#: `note`（纯笔记）在 KOReader 里没有对应 drawer —— 它的笔记也是**有引文**的，
#: 所以纯笔记**导出成 `lighten` + 保留 note 文本**（引文为空时那条根本不导出）。
STYLE_TO_DRAWER = {
    "highlight": "lighten",
    "underline": "underscore",
    "strikethrough": "strikeout",
    "note": "lighten",
}

#: 本项目的颜色 → KOReader 的颜色（与 `COLOR_MAP` 反向）。
#:
#: ⚠️ 只映射**确有等价物**的：`teal` ↔ `cyan`（KOReader 的 cyan 就是青蓝）。
#: `pink` / `magenta` 在两边都有等价项，但**本项目的 `magenta` 与 KOReader 的
#: `magenta` 色相不同** ⇒ 不映射（回落到 `yellow`，宁可颜色不精确也别给错色相）。
COLOR_TO_KOREADER = {
    "yellow": "yellow", "orange": "orange", "red": "red",
    "purple": "purple", "blue": "blue", "green": "green", "gray": "gray",
    "teal": "cyan",
}

#: 回落色（与 `koreader_anno.DEFAULT_COLOR` 一致）
DEFAULT_KOREADER_COLOR = "yellow"

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def lua_quote(s: str) -> str:
    """Lua 的 ``string.format("%q", s)`` 转义（**不是 JSON 的**）。

    ⚠️ Lua 的 `%q` 规则：``"`` / ``\\`` / 换行 → 反斜杠 + 原字符（换行是「反斜杠后跟
    一个**真换行**」！），``\\r`` → 反斜杠 r，``\\0`` → 反斜杠 0，其余控制字符原样输出。

    抄这份规则是为了让导出文件**能被 `koreader_anno.parse()` 读回去** ——
    两边转义不一致 ⇒ 往返失败。
    """
    out = ['"']
    for ch in str(s):
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\0":
            out.append("\\0")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _lua_table(pairs: list, indent: int = 1) -> str:
    """Lua 的 ``dump`` 形态：``[键] = 值,`` 逐行、4 空格缩进。

    ⚠️ 键**总带方括号**（上游 `dump` 就是这样）—— 字符串键因此是 ``["annotations"]``。
    """
    if not pairs:
        return "{}"
    pad = "    " * indent
    lines = ["{"]
    for key, value in pairs:
        lines.append(f'{pad}[{key}] = {value},')
    lines.append("    " * (indent - 1) + "}")
    return "\n".join(lines)


def _anno_pairs(anno: dict) -> list:
    """一条批注 → Lua 字面量的键值对列表（字段名与上游 `buildAnnotation` 对齐）。"""
    pairs = []
    text = str(anno.get("text") or "")
    if text:
        pairs.append(('"datetime"', lua_quote(str(anno.get("datetime") or ""))))
        pairs.append(('"text"', lua_quote(text)))
        pairs.append(('"drawer"', lua_quote(str(anno.get("drawer") or ""))))
        pairs.append(('"color"', lua_quote(str(anno.get("color") or ""))))
        pairs.append(('"chapter"', lua_quote(str(anno.get("chapter") or ""))))
        pairs.append(('"page"', lua_quote(str(anno.get("page") or ""))))
        pairs.append(('"pos0"', lua_quote(str(anno.get("pos0") or ""))))
        pairs.append(('"pos1"', lua_quote(str(anno.get("pos1") or ""))))
    note = str(anno.get("note") or "")
    if note:
        pairs.append(('"note"', lua_quote(note)))
    return pairs


def build_lua(annos: list, device_id: str = "novelforge",
              paging: bool = False, path: str = "") -> str:
    """拼出 KOReader 的批注文件内容（**含** ``-- <路径>`` 行注释与 ``return ``）。

    形状与上游 `onExportAnnotations` + `util.writeToFile` 一致：
    第一行是 ``-- <绝对路径>``，第二行以 ``return `` 起头（`dofile` 才吃得下）。
    """
    ts = time.strftime(_TS_FORMAT, time.localtime())
    top = [
        ('"device_id"', lua_quote(str(device_id or "novelforge"))),
        ('"datetime"', lua_quote(ts)),
        ('"paging"', "true" if paging else "false"),
    ]
    if annos:
        # `annotations` 是**数组** ⇒ 键是数字下标（上游 `dump` 对数组也用 `[1] = …`）
        # ⚠️ 它必须**内嵌在顶层表里**（上游 `dump` 就是这样）—— 另起一块的话
        # 顶层表会被提前闭合，解析器读到 `}` 就结束、`annotations` 根本读不到。
        # ⚠️ 数组的键是**数字下标**（上游 `dump` 对数组也用 `[1] = …`）——
        # 写成光秃秃的 `{ {...}, {...} }` 的话，解析器读表时**先要 `[`**，
        # 没有键就会在第二个元素处报「期望 '['」。
        # ⚠️ 每条批注**自己就是一张表**（`[1] = { ["text"] = … }`）——
        # 多套一层 `{ { … } }` 的话，解析器会把外层那个当批注表，读不到字段。
        # ⇒ 这里**手写**这一行，不走 `_lua_table`（它会给值再包一层 `{}`）。
        inner = "\n".join(
            "    [" + str(i + 1) + "] = "
            + _lua_table(_anno_pairs(a), indent=2) + ","
            for i, a in enumerate(annos)
        )
        top.append(('"annotations"', "{\n" + inner + "\n    }"))
    body = _lua_table(top, indent=1)
    head = f"-- {path}\n" if path else ""
    return head + "return " + body + "\n"


def _anno_key(a: dict) -> str:
    """去重键：引文 + 位置（KOReader 的注释没有稳定 id）。"""
    return "|".join([str(a.get("text") or ""), str(a.get("page") or ""),
                     str(a.get("pos0") or ""), str(a.get("pos1") or "")])


def _to_koreader_anno(row: dict, chapter_title: str) -> "dict | None":
    """本项目的一条批注 → KOReader 的注释（**没有引文就不导** —— 见文件头）。"""
    quote = str(row.get("quote") or "").strip()
    if not quote:
        return None
    style = str(row.get("style") or "highlight")
    drawer = STYLE_TO_DRAWER.get(style, "lighten")
    color = COLOR_TO_KOREADER.get(str(row.get("color") or ""), DEFAULT_KOREADER_COLOR)
    created = float(row.get("created_at") or 0) or time.time()
    ts = time.strftime(_TS_FORMAT, time.localtime(created))
    # 位置：KOReader 的可重排版注释用 `page` 存 **XPointer 串**（上游注释：
    # 「pos0 ... xPointer (== page)」）⇒ 本项目的 `anchor` 正好是那个东西。
    # ⚠️ **空锚导不出去**：KOReader 的解析端把没有位置的条目当书签丢掉
    # （`to_items` 的 `no_position`），而本项目的锚对**自己写的**批注也是空的
    # （本项目用「章内字符偏移」，不是 XPointer）⇒ 那种批注**导不出位置**，
    # 但**引文与笔记仍在**（KOReader 能显示，只是不能精确跳回原位）。
    anchor = str(row.get("anchor") or "")
    return {
        "datetime": ts,
        "text": quote,
        "note": str(row.get("note") or ""),
        "drawer": drawer,
        "color": color,
        "chapter": chapter_title,
        "page": anchor,
        "pos0": "",
        "pos1": "",
    }


def plan_export(book_file: pathlib.Path, rows: list, chapter_titles=None) -> dict:
    """算一份导出计划（**只算不改**）。

    ``rows`` = 这本书的批注行（`db.list_annotations` 的形状）。
    返回 ``{"path", "existing", "add", "total", "skipped", "preview"}``：
    ``preview`` 是将要写出的文件内容（给人看 / 核对）。
    """
    titles = chapter_titles or {}
    out = []
    skipped = 0
    for r in rows or []:
        a = _to_koreader_anno(r, str(titles.get(r.get("chapter"), "") or ""))
        if a is None:
            skipped += 1
            continue
        out.append(a)
    # 已有文件里的批注也要保留（不能盖掉用户在设备上写的）
    existing = []
    target = None
    for cand in export_paths_for(book_file):
        if cand.is_file():
            target = cand
            try:
                from .koreader_anno import parse
                parsed = parse(cand.read_text(encoding="utf-8", errors="replace"))
                from .koreader_anno import to_items
                items, _sk, _st = to_items(parsed)
                for it in items:
                    # `to_items` 的键是**本项目侧**的（`quote` / `style`），
                    # 这里要写回 KOReader 侧的键（`text` / `drawer`）。
                    existing.append({
                        "datetime": str(it.get("created_at") and
                                        time.strftime(_TS_FORMAT,
                                                      time.localtime(it["created_at"])) or ""),
                        "text": str(it.get("quote") or ""),
                        "note": str(it.get("note") or ""),
                        "drawer": STYLE_TO_DRAWER.get(str(it.get("style") or ""), "lighten"),
                        "color": COLOR_TO_KOREADER.get(str(it.get("color") or ""),
                                                    DEFAULT_KOREADER_COLOR),
                        "chapter": "",
                        "page": str(it.get("anchor") or ""),
                        "pos0": "",
                        "pos1": "",
                    })
            except Exception:
                existing = []                # 读不懂就不合并（但**不删**那个文件）
            break
    if target is None:
        target = export_paths_for(book_file)[0]
    seen = {_anno_key(a) for a in existing}
    merged = list(existing)
    added = 0
    for a in out:
        k = _anno_key(a)
        if k in seen:
            continue
        seen.add(k)
        merged.append(a)
        added += 1
    return {
        "path": str(target),
        "existing": len(existing),
        "add": added,
        "total": len(merged),
        "skipped": skipped,
        "preview": build_lua(merged, path=str(target)),
    }


def apply_export(book_file: pathlib.Path, rows: list, chapter_titles=None) -> dict:
    """把导出计划**落盘**（写 KOReader 的导出位点）。

    ⚠️ 只写 `export_paths_for` 给出的位点；不新建目录（sidecar 目录不存在时
    只写「书的旁边」那一个）。
    """
    plan = plan_export(book_file, rows, chapter_titles)
    target = pathlib.Path(plan["path"])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(plan["preview"], encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"写 {target.name} 失败：{e}", **{
            k: plan[k] for k in ("path", "existing", "add", "total", "skipped")}}
    return {"ok": True, **plan}
