"""演播者（narrator）实体模块（第 53 期）。

与 ``authors`` **同源同构**，但**刻意精简**：能力矩阵 ``hasPhoto=—``，故无 bio/photo；
本项目作者侧亦未实现真·软删，故不引入 ``deleted_at``。只保留排序名两列
（``sort_name`` 派生 / ``sort_name_local`` 覆盖），与 ``authors`` 的排序键逻辑**逐字复用**。

排序名两列语义、回退规则、以及「回填只写 sort_name 绝不动 sort_name_local」的铁律，
对齐 ``core/authors.py``，避免双标。
"""
from __future__ import annotations

import novelforge.core.authors as authors
import novelforge.core.db as db
import novelforge.core.library as library


def derive_sort_name(display_name: str) -> str:
    """从显示名派生排序键（直接复用 authors 的同名函数，规则一致）。"""
    return authors.derive_sort_name(display_name)


def backfill_sort_names() -> dict:
    """为**还没有派生排序键**的演播者补一个 ``sort_name``（第 53 期一次性回填）。

    只写 ``sort_name``（派生态列），**绝不动** ``sort_name_local``（用户覆盖）：
    写后者等于冒充用户改过、界面会误显示「已覆盖」；已有 ``sort_name`` 的跳过；
    派生结果与显示名相同的（CJK 等）也跳过（填了等于没填）。
    返回 ``{total, filled, skipped, details:[{name, sort_name}]}``。
    """
    rows = db.all_narrators()
    total = filled = 0
    details: list = []
    for n in library.narrators_list():
        name = str(n.get("name") or "").strip()
        if not name:
            continue
        total += 1
        row = rows.get(name) or {}
        if str(row.get("sort_name") or "").strip():
            continue
        derived = derive_sort_name(name)
        if not derived or derived == name:
            continue
        db.set_narrator_sort_name(name, derived)
        filled += 1
        details.append({"name": name, "sort_name": derived})
    return {"total": total, "filled": filled, "skipped": total - filled, "details": details}


def sort_name_of(row: dict) -> str:
    """从 ``narrators`` 表行里取**生效**排序名（本地覆盖 > 在线），都没有则空串。

    **刻意不回退到 name**：「没设排序名」与「把排序名设成和显示名一样」是两件事；
    回退到显示名是排序时的事，由取值方 ``or name`` 决定。
    """
    r = row or {}
    return str(r.get("sort_name_local") or "").strip() or str(r.get("sort_name") or "")


def effective(name: str) -> dict:
    """演播者生效信息：排序名（本地覆盖 > 在线）、覆盖标记。"""
    row = db.get_narrator(name) or {}
    sort_local = str(row.get("sort_name_local") or "").strip()
    return {
        "name": name,
        "sort_name": sort_name_of(row),
        "sort_name_overridden": bool(sort_local),
    }


def set_sort_name(name: str, value: str) -> dict:
    """设置/清除演播者排序名的本地覆盖（空串 = 撤销覆盖，排序回退到在线排序名 / 显示名）。"""
    db.set_narrator_sort_name_local(name, value)
    return effective(name)
