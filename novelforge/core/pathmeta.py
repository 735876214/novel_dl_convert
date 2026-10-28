"""按正则从文件名 / 相对路径提取元数据（第 165 期）—— 「正则导入」的唯一判据源。

## 它是什么 / 不是什么

用户手里常有一批**文件名本身就带元数据**的书（`[作者] 书名 (2021).epub`、
`系列/第03卷 - 书名.epub`）。这里让用户写一条正则（**命名分组 = 元数据字段名**），
先预览「哪几本匹配、每条字段会变成什么」，确认后才写成**服务端覆盖**
（`meta_override`）—— 与单书编辑是同一条写入路径，**书文件一字节不动**。

**不是常驻规则**：不落库、不参与扫描。规则只活在这一次请求里 ——
否则又会多出一套「扫描时自动应用」的第二判据，与 `metadata.from_filename`
的默认解析打架。

## 三条硬口径

1. **字段名只认 `fileops.METADATA_FIELDS`**：正则里的命名分组必须是其中的字段，
   否则整条正则**直接拒绝**并列出不认识的组名（拼错一个字段名却静默无效果，
   比报错难查得多）。未命名分组允许存在（`(?:…)` 之类），只是不参与映射。
2. **空匹配值 = 这个字段不写**：能匹配到书、但某个分组是空串时，该字段保持原值 ——
   绝不把「没提取到」写成清空。清空只能逐本在编辑器里做。
3. **应用不信任预览条目**：与实体改名同一条纪律 —— 调用方只能传 `book_ids`
   **收窄范围**，要改哪些书、改成什么由服务端用同一个 `preview()` 重新算。

正则本身走 `core.saferegex`（带超时 / 降级护栏）：这是用户输入的执行期正则，
一条灾难性回溯的模式就能把请求线程卡死。
"""
from __future__ import annotations

import pathlib
import re

from . import activity_log, db, fileops, library, metastore, saferegex

#: 可匹配的文本口径。**唯一一份**：前端下拉与后端校验都从这里取。
TARGETS: dict = {
    "stem": "文件名（不含扩展名）",
    "filename": "文件名（含扩展名）",
    "path": "相对库根的路径",
}

#: 每本书参与映射的字段：命名分组只认这些。
ALLOWED_FIELDS = tuple(fileops.METADATA_FIELDS)

#: 与 `db._parse_tags` 同源的**多值字段**（题材 / 演播者）。
_LIST_FIELDS = ("tags", "narrators")

#: 预览最多返回多少条（计数仍然覆盖全量）：几千本一次性回给前端是纯浪费。
PREVIEW_LIMIT = 200

#: 规则长度上限：正常正则几十个字符，超过这个量级多半是贴错东西了。
MAX_PATTERN_LEN = 500


def _text_of(book: dict, target: str) -> str:
    """取这本书用于匹配的文本（`target` 已校验）。"""
    name = str(book.get("name") or "").replace("\\", "/")
    p = pathlib.PurePosixPath(name)
    if target == "path":
        return name
    if target == "filename":
        return p.name
    return p.stem                                     # 默认 / "stem"


def compile_rule(pattern: str, target: str = "stem") -> tuple:
    """校验并编译规则 → `(编译后的正则, 参与映射的字段元组, target)`。

    失败一律抛 :class:`ValueError`（接口层转 400，消息直接给用户看）。
    """
    pat = str(pattern or "").strip()
    if not pat:
        raise ValueError("正则不能为空")
    if len(pat) > MAX_PATTERN_LEN:
        raise ValueError(f"正则过长（上限 {MAX_PATTERN_LEN} 字符）")
    tgt = str(target or "stem")
    if tgt not in TARGETS:
        raise ValueError(f"匹配范围只能是 {' / '.join(TARGETS)}")
    try:
        rx = saferegex.compile(pat)
    except re.error as e:
        raise ValueError(f"正则无法编译：{e}") from None

    names = sorted(set(getattr(rx, "groupindex", {}) or {}))
    unknown = [n for n in names if n not in ALLOWED_FIELDS]
    if unknown:
        raise ValueError(
            "这些命名分组不是可写的元数据字段：" + "、".join(unknown)
            + "（可用字段见编辑元数据页；拼写需完全一致）")
    if not names:
        raise ValueError("正则里没有任何命名分组 —— 用 (?P<字段名>…) 指定要提取的字段")
    return rx, tuple(names), tgt


def _normalize(field: str, raw) -> object:
    """分组值 → 要写入的值；空串返回 `None`（= 这个字段不写）。"""
    v = str(raw or "").strip()
    if not v:
        return None
    if field in _LIST_FIELDS:
        # 与 `db._meta_out` / `metastore` 同一份解析：顿号 / 逗号 / 分号 / 竖线都当分隔符
        return db._parse_tags(v)
    return v


def _plan_for_book(book: dict, rx, fields: tuple, target: str) -> "dict | None":
    """单本书的匹配结果；没匹配上返回 `None`。"""
    text = _text_of(book, target)
    m = rx.search(text)
    if not m:
        return None
    current = metastore.effective(book)
    values: dict = {}
    changes: list = []
    for f in fields:
        try:
            raw = m.group(f)
        except (IndexError, KeyError):                # 理论上不会发生（fields 来自 groupindex）
            continue
        val = _normalize(f, raw)
        if val is None:
            continue
        values[f] = val
        before = current.get(f)
        if isinstance(val, list):
            if list(before or []) != val:
                changes.append({"field": f, "from": before, "to": val})
        elif str(before or "").strip() != val:
            changes.append({"field": f, "from": before, "to": val})
    return {
        "book_id": str(book.get("id") or ""),
        "name": str(book.get("name") or ""),
        "title": str(book.get("title") or "") or str(book.get("name") or ""),
        "library_id": book.get("library_id"),
        "matched": True,
        "values": values,
        "changes": changes,
    }


def preview(pattern: str, target: str = "stem", library_id=None) -> dict:
    """只读预览：匹配多少本、哪些字段会变。**不写任何东西。**"""
    rx, fields, tgt = compile_rule(pattern, target)
    bs = library.books(str(library_id)) if library_id else library.books()
    matched: list = []
    for b in bs:
        hit = _plan_for_book(b, rx, fields, tgt)
        if hit:
            matched.append(hit)
    changed_books = sum(1 for it in matched if it["changes"])
    return {
        "target": tgt,
        "fields": list(fields),
        # 计数覆盖全量；条目只回前 PREVIEW_LIMIT 条（前端提示「仅显示前 N 条」）
        "items": matched[:PREVIEW_LIMIT],
        "total": len(bs),
        "matched": len(matched),
        "unmatched": len(bs) - len(matched),
        "changed": changed_books,
        "truncated": len(matched) > PREVIEW_LIMIT,
        "limit": PREVIEW_LIMIT,
    }


def apply(pattern: str, target: str = "stem", library_id=None, book_ids=None) -> dict:
    """把规则写成服务端覆盖。**重新算**（不信任预览条目），`book_ids` 只作收窄。

    ⚠️ 写入是**一条事务**（第 171 期）：先把每一行算齐，最后 `db.set_overrides` 一次提交。
    逐行 `db.set_override` 时每行一次 `commit()`（实测 2.26 ms/行，fsync 主导），
    「整库匹配上规则」的典型用法（2,000 本 × 2 字段）≈ **9.5 s**，已顶到前端 15 s 超时。
    代价：写入期间的 DB 级异常会整批失败（此前是逐本隔离）—— 但这里的写入是同一张表、
    同一条语句，失败必然是系统性原因（磁盘 / 连接），逐本重试没有意义。
    """
    rx, fields, tgt = compile_rule(pattern, target)
    narrow = {str(x) for x in (book_ids or []) if str(x or "").strip()}
    bs = library.books(str(library_id)) if library_id else library.books()
    planned, rows = [], []
    for b in bs:
        bid = str(b.get("id") or "")
        if not bid or (narrow and bid not in narrow):
            continue
        hit = _plan_for_book(b, rx, fields, tgt)
        if not hit:
            continue
        write: dict = {}
        for ch in hit["changes"]:
            f = ch["field"]
            val = hit["values"][f]
            write[f] = val
        if not write:
            continue
        for f, val in write.items():
            # 多值字段按 `str(list)` 落库（与单书编辑同一种形态，读侧统一解析）
            rows.append((bid, f, str(val) if isinstance(val, list) else val,
                         str(ch_of(hit, f, "from") or "")))
        planned.append({"book_id": bid, "name": hit["name"],
                        "library_id": hit["library_id"], "fields": sorted(write)})
    done, errors = [], []
    if planned:
        try:
            db.set_overrides(rows)
        except Exception as e:                        # noqa: BLE001 —— 整批失败如实回执
            errors.append({"book_id": "", "name": "",
                           "error": f"写入失败（{len(planned)} 本未写入）：{e}"})
        else:
            done = planned
    library.invalidate()
    if done:
        activity_log.log(activity_log.ACTION_METADATA, "正则提取元数据",
                         activity_log.STATUS_OK,
                         detail=(f"{len(done)} 本；字段：" + "、".join(sorted(set(fields))))[:300],
                         source="api")
    return {"count": len(done), "items": done, "errors": errors,
            "fields": sorted(set(fields))}


def ch_of(hit: dict, field: str, key: str):
    """从 `changes` 里取某字段的 `from` / `to`（没有该字段时返回空串）。"""
    for ch in hit.get("changes") or []:
        if ch.get("field") == field:
            return ch.get(key) or ""
    return ""
