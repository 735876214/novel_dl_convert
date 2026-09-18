"""元数据分层解析：override（用户编辑）> online（在线抓取）> opf（文件本体）。

只服务「详情 / 编辑」这类需要展示生效值的接口；`library.books()` 的批量热路径
保持只读 OPF，不引入额外 DB 查询（控制爆炸半径，参见第 8 期 plan 的防回归说明）。

分层语义对应"在线优先、本地兜底、可编辑"：
- **override**：用户通过本工具显式改过的字段，最高优先、且抓取时受保护不被覆盖；
- **online**：最近一次在线抓取到的值，仅在无 override 时生效，并供"恢复在线"回退；
- **opf**：EPUB 内嵌原值，作为最终兜底。
"""
from . import db, fileops


def _opf_value(book: dict, field: str):
    """从 library 的书对象读 OPF 原值。字段名对齐 ``fileops.METADATA_FIELDS``
    （注意 ``date`` 在书目里叫 ``year``）。"""
    if field == "tags":
        return list(book.get("tags") or [])
    if field == "date":
        return str(book.get("year") or "").strip()
    return str(book.get(field) or "").strip()


def effective(book: dict) -> dict:
    """返回该书每个可编辑字段的生效值（override > online > opf）。"""
    bid = book.get("id")
    ov = db.get_overrides(bid) if bid else {}
    on = db.get_online(bid) if bid else {}
    out = {}
    for f in fileops.METADATA_FIELDS:
        if ov.get(f) and str(ov[f]).strip():
            out[f] = ov[f]
        elif on.get(f) and str((on[f].get("value") or "")).strip():
            out[f] = on[f]["value"]
        else:
            out[f] = _opf_value(book, f)
    return out


def state(book: dict) -> dict:
    """编辑器的逐字段明细：生效值 / 在线建议值 / OPF 原值 / 是否已被用户覆盖。

    供 ``GET /api/books/{bid}/metadata`` 一次性下发，前端据此渲染
    "已本地修改" 徽标与"恢复为在线值"按钮，无需额外往返。
    """
    bid = book.get("id")
    ov = db.get_overrides(bid) if bid else {}
    on = db.get_online(bid) if bid else {}
    out = {}
    for f in fileops.METADATA_FIELDS:
        opf = _opf_value(book, f)
        online = (on.get(f) or {}).get("value") or ""
        online = str(online).strip()
        overridden = bool(ov.get(f) and str(ov[f]).strip())
        out[f] = {
            "value": ov[f] if overridden else (online or opf),
            "online": online,
            "opf": opf,
            "overridden": overridden,
        }
    return out
