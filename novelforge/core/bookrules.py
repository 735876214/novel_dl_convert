"""书目规则引擎（智能书架 / 规则筛选）—— **规则的唯一判定实现**。

第 218 期把求值从前端搬到服务端，理由有两个：

1. **同一判据只许一处实现**：此前字段 / 操作白名单在 `server.py`、判定语义在
   `frontend/src/lib/smartScope.ts`，加一个字段要两边同改，漏一边就静默错。
2. **客户端不必先拿到全量书目才能算规则**：规则书架现在由服务端求值，前端只管展示。

字段按**书目卡片**（`GET /api/books` 的条目，已合并进度 / 状态 / 批注 / 收藏夹）
声明；每字段声明允许的操作，校验与求值共用这一份规格（:data:`FIELDS`）。

语义口径（与改造前的 TS 实现逐条对齐，避免老规则行为漂移）：

- 空值规则恒真（用户还没填完，先不排除书）；
- 文本比较**大小写不敏感**、去首尾空白；
- 多值字段（题材 / 演播者 / 收藏夹 / 问题）任一值命中即算包含；
- `status` **真实状态优先**，没有状态行才按进度 + 阅读阈值兜底；
- 数值字段遇到无法解析的书值 ⇒ **不命中**（没标年份的书不参与年份比较，
  不能被当成 0 归进「至多」）；
- `all` = 全部规则满足，`any` = 满足其一。
"""
from __future__ import annotations

import time

# ---- 字段规格（唯一真值源：校验、求值、前端表单都从这里派生）----

TEXT_OPS = ("contains", "not_contains", "equals", "not_equals",
            "starts_with", "ends_with", "is_empty", "is_not_empty")
LIST_OPS = ("contains", "not_contains", "equals", "not_equals",
            "is_empty", "is_not_empty")
ENUM_OPS = ("equals", "not_equals", "is_empty", "is_not_empty")
NUM_OPS = ("equals", "not_equals", "at_least", "at_most")

#: 操作 → 中文（前端表单直接取这份，不在客户端再抄一遍）。
OPS = {
    "contains": {"label": "包含", "needs_value": True},
    "not_contains": {"label": "不包含", "needs_value": True},
    "equals": {"label": "等于", "needs_value": True},
    "not_equals": {"label": "不等于", "needs_value": True},
    "starts_with": {"label": "开头是", "needs_value": True},
    "ends_with": {"label": "结尾是", "needs_value": True},
    "is_empty": {"label": "为空", "needs_value": False},
    "is_not_empty": {"label": "不为空", "needs_value": False},
    "at_least": {"label": "至少", "needs_value": True},
    "at_most": {"label": "至多", "needs_value": True},
}

_STATUS_VALUES = [
    {"value": "unread", "label": "未读"},
    {"value": "want_to_read", "label": "想读"},
    {"value": "reading", "label": "在读"},
    {"value": "rereading", "label": "重读"},
    {"value": "finished", "label": "已读完"},
    {"value": "skimmed", "label": "略读"},
    {"value": "paused", "label": "搁置"},
    {"value": "abandoned", "label": "弃读"},
]
_YES_NO = [{"value": "yes", "label": "是"}, {"value": "no", "label": "否"}]
_LIBRARY_TYPES = [
    {"value": "ebook", "label": "电子书"},
    {"value": "comic", "label": "漫画"},
    {"value": "audiobook", "label": "有声书"},
    {"value": "mixed", "label": "混合"},
]
_PAGES_SOURCES = [
    {"value": "estimate", "label": "估算"},
    {"value": "archive", "label": "归档"},
]

#: 字段规格。键的顺序 = 前端下拉里的顺序（先常用文本字段，再数值 / 状态）。
FIELDS: dict = {
    "title": {"label": "书名", "kind": "text", "ops": TEXT_OPS},
    "author": {"label": "作者", "kind": "text", "ops": TEXT_OPS},
    "series": {"label": "系列", "kind": "text", "ops": TEXT_OPS},
    "publisher": {"label": "出版社", "kind": "text", "ops": TEXT_OPS},
    "language": {"label": "语言", "kind": "text", "ops": TEXT_OPS},
    "isbn": {"label": "ISBN", "kind": "text", "ops": TEXT_OPS},
    "name": {"label": "文件名", "kind": "text", "ops": TEXT_OPS},
    "series_index": {"label": "系列序号", "kind": "text", "ops": TEXT_OPS},
    "library": {"label": "书库", "kind": "text", "ops": TEXT_OPS},
    "tag": {"label": "题材", "kind": "list", "ops": LIST_OPS},
    "narrator": {"label": "演播者", "kind": "list", "ops": LIST_OPS},
    "collection": {"label": "收藏夹", "kind": "list", "ops": LIST_OPS},
    "issue": {"label": "文件问题", "kind": "list", "ops": LIST_OPS},
    "format": {"label": "格式", "kind": "enum", "ops": ENUM_OPS},
    "status": {"label": "阅读状态", "kind": "enum", "ops": ENUM_OPS,
               "values": _STATUS_VALUES},
    "library_type": {"label": "书库类型", "kind": "enum", "ops": ENUM_OPS,
                     "values": _LIBRARY_TYPES},
    "pages_source": {"label": "页数来源", "kind": "enum", "ops": ENUM_OPS,
                     "values": _PAGES_SOURCES},
    "has_cover": {"label": "有封面", "kind": "enum", "ops": ENUM_OPS, "values": _YES_NO},
    "has_description": {"label": "有简介", "kind": "enum", "ops": ENUM_OPS, "values": _YES_NO},
    "fixed_layout": {"label": "固定版式", "kind": "enum", "ops": ENUM_OPS, "values": _YES_NO},
    "stars": {"label": "评分", "kind": "number", "ops": NUM_OPS},
    "year": {"label": "出版年", "kind": "number", "ops": NUM_OPS},
    "annotations": {"label": "批注数", "kind": "number", "ops": NUM_OPS},
    "added": {"label": "入库天数", "kind": "number", "ops": NUM_OPS},
    "percent": {"label": "阅读进度（%）", "kind": "number", "ops": NUM_OPS},
    "size_mb": {"label": "大小（MB）", "kind": "number", "ops": NUM_OPS},
    "pages": {"label": "页数", "kind": "number", "ops": NUM_OPS},
    "tracks": {"label": "音轨数", "kind": "number", "ops": NUM_OPS},
    "collection_count": {"label": "收藏夹数量", "kind": "number", "ops": NUM_OPS},
}

ALLOWED = frozenset(FIELDS)


def schema() -> dict:
    """给前端的字段 / 操作清单（**前端不静态抄一份**，加字段只改这里）。"""
    fields = []
    for key, spec in FIELDS.items():
        item = {"key": key, "label": spec["label"], "kind": spec["kind"],
                "ops": list(spec["ops"])}
        if spec.get("values"):
            item["values"] = [dict(v) for v in spec["values"]]
        fields.append(item)
    return {
        "fields": fields,
        "ops": [{"key": k, "label": v["label"], "needs_value": v["needs_value"]}
                for k, v in OPS.items()],
    }


def validate(rules, match: str = "all") -> tuple:
    """结构校验 → ``(干净的三元组列表, match)``；不合法抛 ``ValueError``（消息可直接展示）。

    刻意**不信任客户端**：多传的键一律丢掉（前端求值只看 field/op/value，多余的键
    是隐性配置）；数值字段的值必须是数字 —— 否则规则存进去也永远不命中，用户只会
    看到「保存成功但书架是空的」。
    """
    if match not in ("all", "any"):
        raise ValueError("匹配方式必须是 all 或 any")
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules 必须为非空数组")
    out = []
    for r in rules:
        if not isinstance(r, dict):
            raise ValueError("规则必须是对象")
        field, op = r.get("field"), r.get("op")
        value = str(r.get("value") if r.get("value") is not None else "")
        spec = FIELDS.get(field)
        if spec is None:
            raise ValueError(f"未知规则字段：{field}")
        if op not in spec["ops"]:
            raise ValueError(f"字段 {field} 不支持操作 {op}")
        if OPS[op]["needs_value"] and spec["kind"] == "number" and value.strip():
            try:
                float(value)
            except ValueError:
                raise ValueError(f"字段 {field} 的值必须是数字：{value}") from None
        out.append({"field": field, "op": op, "value": value})
    return out, match


def _norm(v) -> str:
    return str(v if v is not None else "").strip().lower()


def _num(v) -> "float | None":
    """数值化；**空值 / 无法解析返回 None**（调用方据此判「不参与比较」）。"""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None          # NaN 也当没有


def _text_hit(hay, op: str, needle: str) -> bool:
    h, n = _norm(hay), _norm(needle)
    if op == "is_empty":
        return not h
    if op == "is_not_empty":
        return bool(h)
    if not n:
        return True                       # 值还没填：恒真（见模块文档）
    if op == "equals":
        return h == n
    if op == "not_equals":
        return h != n
    if op == "not_contains":
        return n not in h
    if op == "starts_with":
        return h.startswith(n)
    if op == "ends_with":
        return h.endswith(n)
    return n in h                         # contains


def _list_hit(values, op: str, needle: str) -> bool:
    vals = [_norm(v) for v in (values or []) if _norm(v)]
    n = _norm(needle)
    if op == "is_empty":
        return not vals
    if op == "is_not_empty":
        return bool(vals)
    if not n:
        return True
    if op == "equals":
        return n in vals
    if op == "not_equals":
        return n not in vals
    if op == "not_contains":
        return not any(n in v for v in vals)
    return any(n in v for v in vals)


def _num_hit(value, op: str, needle: str) -> bool:
    if not str(needle if needle is not None else "").strip():
        return True                       # 值还没填：恒真
    want = _num(needle)
    if want is None:
        return False                      # 非法值（老数据）不命中，别当成「全部」
    cur = _num(value)
    if cur is None:
        return False                      # 书没有这个值 ⇒ 不参与比较
    if op == "equals":
        return cur == want
    if op == "not_equals":
        return cur != want
    if op == "at_most":
        return cur <= want
    return cur >= want                    # at_least


def _status_of(book: dict, ctx: dict) -> str:
    """真实状态优先；没有状态行时按进度 + 阈值兜底（与 `stats._classify_status` 同口径）。

    阈值**按书所属库**取（`thresholds_by_library`），没有该库的数据才回落全局值 ——
    智能书架的计数与书目列表必须用同一把尺子，否则「侧栏 5、点进去 4」。
    """
    raw = book.get("status")
    if raw:
        return str(raw)
    by_lib = ctx.get("thresholds_by_library") or {}
    started, finished = by_lib.get(str(book.get("library_id") or ""),
                                   ctx.get("thresholds") or (0.0, 99.5))
    pct = _num(book.get("percent")) or 0.0
    if pct >= finished:
        return "finished"
    return "reading" if pct > started else "unread"


def _field_value(book: dict, field: str, ctx: dict):
    if field == "tag":
        return book.get("tags") or []
    if field == "narrator":
        return book.get("narrators") or []
    if field == "issue":
        return book.get("issues") or []
    if field == "collection":
        names = ctx.get("collection_names") or {}
        return [names.get(int(c), "") for c in (book.get("collection_ids") or [])]
    if field == "collection_count":
        return len(book.get("collection_ids") or [])
    if field == "library":
        return (ctx.get("library_names") or {}).get(str(book.get("library_id") or ""),
                                                    str(book.get("library_id") or ""))
    if field == "status":
        return _status_of(book, ctx)
    if field == "has_cover":
        return "yes" if book.get("has_cover") else "no"
    if field == "has_description":
        return "yes" if book.get("has_description") else "no"
    if field == "fixed_layout":
        return "yes" if book.get("fixed_layout") else "no"
    if field == "year":
        digits = "".join(ch for ch in str(book.get("year") or "") if ch.isdigit())
        return digits or None
    if field == "added":
        ts = _num(book.get("added_at")) or _num(book.get("mtime")) or 0.0
        return (time.time() - ts) / 86400 if ts > 0 else None
    if field == "size_mb":
        return float(book.get("size") or 0) / (1024 * 1024)
    if field == "percent":
        return _num(book.get("percent")) or 0.0
    if field == "stars":
        return _num(book.get("stars")) or 0.0
    if field == "annotations":
        return int(book.get("annotation_count") or 0)
    if field == "pages":
        return int(book.get("pages") or 0)
    if field == "tracks":
        return int(book.get("tracks") or 0)
    return book.get(field)


def rule_hit(book: dict, rule: dict, ctx: dict = None) -> bool:
    """单条规则对一本书的判定（接口与 UI 共用这一份语义）。"""
    ctx = ctx or {}
    spec = FIELDS.get(rule.get("field"))
    if spec is None:
        return True                       # 未知字段：不排除书（老规则 / 未来字段的降级）
    value = _field_value(book, rule["field"], ctx)
    op = str(rule.get("op") or "")
    needle = str(rule.get("value") if rule.get("value") is not None else "")
    kind = spec["kind"]
    if kind == "list":
        return _list_hit(value, op, needle)
    if kind == "number":
        return _num_hit(value, op, needle)
    # enum 也走文本比较（统一大小写处理）
    return _text_hit(value, op, needle)


def evaluate(books: list, rules: list, match: str = "all", *,
             thresholds: tuple = (0.0, 99.5),
             thresholds_by_library: dict = None,
             library_names: dict = None, collection_names: dict = None) -> list:
    """按规则组筛书。``all`` = 且，``any`` = 或；空规则 = 全部。"""
    rs = [r for r in (rules or []) if isinstance(r, dict)]
    if not rs:
        return list(books)
    ctx = {"thresholds": thresholds,
           "thresholds_by_library": thresholds_by_library or {},
           "library_names": library_names or {},
           "collection_names": collection_names or {}}
    if match == "any":
        return [b for b in books if any(rule_hit(b, r, ctx) for r in rs)]
    return [b for b in books if all(rule_hit(b, r, ctx) for r in rs)]
