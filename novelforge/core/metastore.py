"""元数据分层解析：override（用户编辑）> online（在线抓取）> opf（文件本体）。

本模块服务「详情 / 编辑」这类单书的生效值查询。第 17 期 T3 起，``library.books()``
的**批量热路径**也会按同一优先级合并服务端元数据（``db.get_effective_meta`` 一次批量
取全，靠扫描缓存摊销），使列表 / 卡片 / 搜索 / OPDS 与详情页一致 —— 元数据只存服务端，
不再改写 EPUB 文件。两处**优先级必须保持一致**（override > online > opf）。

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
            # 翻掉「显式无值」哨兵（清空系列序号这类）—— 取到的是空串，
            # 而不是把哨兵本身当成值显示出去。
            out[f] = db._meta_out(f, ov[f])
        elif on.get(f) and str((on[f].get("value") or "")).strip():
            out[f] = on[f]["value"]
        else:
            out[f] = _opf_value(book, f)
    return out


def state(book: dict) -> dict:
    """编辑器的逐字段明细：生效值 / 在线建议值 / OPF 原值 / 是否已覆盖 / 是否已锁定。

    供 ``GET /api/books/{bid}/metadata`` 一次性下发，前端据此渲染
    "已本地修改" 徽标与"恢复为在线值"按钮，无需额外往返。

    第 35 期起多下发 ``locked``（字段级锁定，只挡抓取、不挡手动编辑）。它**不是**
    ``overridden`` 的别名：两者可以任意组合 —— 没改过但锁上（抓取别动）、
    改过但没锁（抓取之后可以再接管）都成立。
    """
    bid = book.get("id")
    ov = db.get_overrides(bid) if bid else {}
    on = db.get_online(bid) if bid else {}
    locks = db.get_locks(bid) if bid else set()
    out = {}
    for f in fileops.METADATA_FIELDS:
        opf = _opf_value(book, f)
        online = (on.get(f) or {}).get("value") or ""
        online = str(online).strip()
        overridden = bool(ov.get(f) and str(ov[f]).strip())
        # 被覆盖时取「对外形态」：哨兵 → 空串（用户显式清空）。overridden 仍为真，
        # 编辑器据此显示「已本地修改」并提供「恢复为在线值」——语义没变，只是值空了。
        out[f] = {
            "value": db._meta_out(f, ov[f]) if overridden else (online or opf),
            "online": online,
            "opf": opf,
            "overridden": overridden,
            "locked": f in locks,
        }
    return out


def locked_fields(book: dict) -> list:
    """该书被锁的字段（含 ``cover``，按 :data:`fileops.METADATA_FIELDS` 的次序 + 封面）。

    供详情页/抓取预览标注用：只返回**该书确实存在的锁**，不补空位。
    """
    bid = (book or {}).get("id")
    if not bid:
        return []
    locks = db.get_locks(bid)
    out = [f for f in fileops.METADATA_FIELDS if f in locks]
    if db.LOCK_COVER in locks:
        out.append(db.LOCK_COVER)
    return out
