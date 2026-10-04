"""书源台账：导入 / 去重 / 冲突处理 / 导出（第 86 期）。

## 这个模块的职责边界（先定死，避免长出两套定义）

- **规则本体**只由 `sources/store.py` 写进 `SOURCES_DIR/<name>.json` —— 本模块**只调** `store.add_rule()`；
- **台账**只放元数据（导入来源 / 去重键 / 档位 / 原始原文 / 启停 / 验证与追更记录），在 `core/db.py`；
- 能力判定与转换全在 `sources/legado.py`（纯函数）—— 本模块不重复实现。

## 去重四级判据（逐条给结论，**绝不静默覆盖**）

| 结论 | 判据 | 默认动作 |
|---|---|---|
| `duplicate` | 同一个**源名** + 同一个 `rule_hash` | 跳过（重复导入幂等） |
| `update` | 同一个源名 + 哈希变了 | 备份旧规则后覆盖（用户点了一下才动的） |
| `conflict` | 站点相同的**另一条**，或撞上**手写源**的源名 | **交用户选**：跳过 / 覆盖 / 两条并存 |
| `new` | 都没有 | 直接落 |
| `unsupported` | 能力报告判 `no`（Legado 走 `analyze`，native 走 `validate_rule` + `audit_native_rule`） | 只记台账（含逐条原因），**不落规则** |

⚠️ 去重范围含**内置源、手写源、已导入源**三类 —— 只比「本次导入的条目之间」会放进一个
与内置源重复的源，用户列表里就会出现两条同站点的书源。
"""
from __future__ import annotations

import json
import pathlib
import time

from ..core import db
from . import formats, legado, store

#: 冲突处理方式（界面逐条让用户选）
RESOLUTIONS = ("skip", "overwrite", "keep_both")

#: 更新类默认动作：`update` 是「同一个源的新版本」，用户勾了就该更新；
#: `conflict` 是「两条不同的东西撞在一起」，默认必须是最保守的跳过。
_DEFAULT_RESOLUTION = {"update": "overwrite", "conflict": "skip", "new": "overwrite"}

#: 「书源管理 → 手动表单 → 保存」用的动作表（第 94 期）。
#: 手写表单是**一次显式的 upsert**（用户自己填了名字、自己点了保存），所以撞名冲突按覆盖处理
#: —— 覆盖前照旧把旧规则原文备份进历史（`apply` 里那一段），可回滚。
#: ⚠️ 只有 `conflict` 与默认表不同：`duplicate` / `unsupported` 在 `apply` 里**先于**动作判定，
#:    改这里影响不到它们；`new` / `update` 本来就是覆盖。
SAVE_RESOLUTION = {**_DEFAULT_RESOLUTION, "conflict": "overwrite"}


def entries_of(payload) -> list:
    """吃下各种输入：本项目的导出文件、Legado 数组 / 单对象 / JSONL、或已是 list。

    ⚠️ 第 94 期起**委托** `intake.unpack_entries`（信封判据、坏输入措辞都只有那一份）——
    本模块不再自己认格式，否则「同一种输入两条路两种结论」的老毛病会原样长回来。
    """
    from . import intake                                     # 局部导入：intake 需要 plan，模块级导入成环

    return intake.unpack_entries(payload)


def _rule_path(name: str) -> pathlib.Path:
    return store._sources_dir() / f"{name}.json"


def existing_sources() -> list:
    """现有书源（内置 + 手写 + 已导入），带上台账里能拿到的去重键。

    ⚠️ 手写源没有台账行，它的站点要从 `domains[0]` 现算 —— 否则「导入一个与手写源
    同站点的源」根本不会判出冲突（那正是最该拦的一种）。
    """
    ledger = {r["name"]: r for r in db.source_ledger_all()}
    out = []
    for s in store.list_sources():
        row = ledger.get(s["name"]) or {}
        doms = list(s.get("domains") or [])
        key = row.get("dedup_key") or legado.norm_site(doms[0] if doms else "")
        out.append({"name": s["name"], "user": bool(s.get("user")), "domains": doms,
                    "dedup_key": key, "rule_hash": row.get("rule_hash") or "",
                    "imported": bool(row.get("imported")), "has_ledger": bool(row)})
    return out


def changed_fields(old: "dict | None", new: dict) -> list:
    """两份规则里取值变了的键（给「有更新」的差异表用）。

    ⚠️ `legado` 是我们自己的**簿记块**（去重键 / 分组 / weight / concurrent_rate）：
    它变了往往就意味着「源里某个字段变了」，所以下钻一层报成 ``legado.weight`` ——
    笼统地报「legado 变了」对用户毫无信息量。
    """
    old, new = old or {}, new or {}
    out = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        if a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            # ⚠️ `legado.rule_hash` 是整条源的哈希：**内容一变它必变**，报出来纯属噪音
            #    （用户会看到「有更新」，但真正变了的是什么仍然要靠别的字段说清）。
            out.extend(f"{k}.{s}" for s in sorted(set(a) | set(b))
                       if a.get(s) != b.get(s) and s != "rule_hash")
        else:
            out.append(k)
    return out


def _same_rule(name: str, converted: dict) -> bool:
    """磁盘上那条规则与待导入的**内容一字不差**？（手写源没有台账哈希，只能比文件）"""
    return _read_rule(name) == converted


def plan(entries: list, *, origin: str = "", existing: "list | None" = None) -> list:
    """逐条判定 → 差异表（**纯计算，不落盘、不出网**）。"""
    known = existing if existing is not None else existing_sources()
    by_name = {k["name"]: k for k in known}
    rows = []
    for ent in entries:
        ent = dict(ent or {})
        # 条目级分派**只在格式轴里**（`formats.map_entry` → 某个适配器的 `map`）：
        # 这里原来是内联判据 `"name" in ent and "domains" in ent`，与 native 适配器的
        # sniff 是同一件事的两份实现 ⇒ 已删。`an` 的形状对任何格式都一样（见 formats/base.py）。
        an = formats.map_entry(ent)
        converted = an.get("converted_rule")
        if converted is None:
            # 不可执行也要有个稳定的名字，才能在列表里看到它、删掉它
            converted = {"name": legado.rule_name(ent), "display_name": "",
                         "domains": [], "legado": {}}
        name = converted["name"]
        rhash = legado.rule_hash(ent)
        dkey = legado.dedup_key(ent) or (converted.get("legado") or {}).get("dedup_key") or ""
        if not dkey and converted.get("domains"):
            dkey = legado.norm_site(converted["domains"][0])

        verdict, conflict_with, changes = "new", "", []
        cur = by_name.get(name)
        # ⚠️ 只有「**真的有东西**」的已知源才算撞名候选：REGISTRY 里可能残留着没有文件、
        #    也没有台账行的条目（测试里尤其常见）—— 拿它当「手写源」会凭空判出一堆冲突。
        real = cur is not None and (cur["user"] or cur["has_ledger"])
        if real and cur["rule_hash"]:
            # 台账里有哈希 ⇒ 能判「同一个源的新旧版本」
            if cur["rule_hash"] == rhash:
                verdict = "duplicate"
            else:
                verdict = "update"
                conflict_with = name
                changes = changed_fields(_read_rule(name), converted)
        elif real:
            # 手写源没有台账哈希：内容一字不差也算重复，否则才是「撞名冲突」——
            # **不覆盖别人的东西**（覆盖与否由用户在差异表里逐条选）。
            if _same_rule(name, converted):
                verdict = "duplicate"
            else:
                verdict, conflict_with = "conflict", name
        elif dkey:
            hit = next((k for k in known if k["dedup_key"] == dkey and k["name"] != name), None)
            if hit:
                verdict, conflict_with = "conflict", hit["name"]
        if an.get("supported") == "no" or converted.get("domains") == []:
            verdict = "unsupported"

        rows.append({
            "name": name,
            "display_name": converted.get("display_name") or name,
            "group": (converted.get("legado") or {}).get("group", ""),
            "source_type": an.get("source_type", "text"),
            "supported": an.get("supported", "yes"),
            "verdict": verdict,
            "unsupported_fields": an.get("unsupported_fields", []),
            "notes": an.get("notes", []),
            "dedup_key": dkey, "rule_hash": rhash, "conflict_with": conflict_with,
            "changed_fields": changes, "converted_rule": converted, "raw": ent,
            "origin": origin,
        })
    return rows


def _read_rule(name: str) -> "dict | None":
    p = _rule_path(name)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001 —— 坏文件当没有
        return None


def _free_name(name: str, taken: set) -> str:
    """「两条并存」用的新名字：``name-2`` / ``name-3`` …（撞到空位为止）。"""
    n = 2
    while f"{name}-{n}" in taken:
        n += 1
    return f"{name}-{n}"


def apply(rows: list, *, origin: str = "", resolutions: "dict | None" = None,
          actor: str = "") -> dict:
    """按差异表落盘。`resolutions` = ``{源名: "skip"|"overwrite"|"keep_both"}``。

    返回 ``{"counts": {...}, "items": [...]}``；每次导入都会留一条**导入历史**。
    """
    res = dict(resolutions or {})
    counts = {"new": 0, "update": 0, "duplicate": 0, "conflict": 0, "unsupported": 0,
              "skipped": 0}
    items = []
    taken = {s["name"] for s in existing_sources()}
    for row in rows:
        name, verdict = row["name"], row["verdict"]
        action = res.get(name) or _DEFAULT_RESOLUTION.get(verdict, "skip")
        counts[verdict] = counts.get(verdict, 0) + 1
        rec = {"name": name, "verdict": verdict, "action": action, "ok": True, "note": ""}
        try:
            if verdict == "unsupported":
                # 只记台账：列表里能看到、能删、能看到「为什么不能用」，但**不落规则**
                db.source_ledger_upsert(
                    name, origin=origin, dedup_key=row["dedup_key"], rule_hash=row["rule_hash"],
                    supported="no", source_type=row["source_type"], group_name=row["group"],
                    raw_json=json.dumps(row["raw"], ensure_ascii=False),
                    unsupported=row["unsupported_fields"], notes=row["notes"],
                    enabled=False, imported=True)
                rec["note"] = "不可执行：已记入台账，可查看原因"
            elif verdict == "duplicate":
                # 只补哈希，**不改 `imported`**：手写源被判重复之后不该被标成「导入的」
                # （那会让下一次它被当成「我们自己的源」而走进覆盖分支）。
                db.source_ledger_upsert(name, origin=origin, rule_hash=row["rule_hash"])
                rec["note"] = "内容相同，未做任何改动"
            elif action == "skip":
                counts["skipped"] += 1
                rec["note"] = "按你的选择跳过"
            else:
                new_name = name
                rule = dict(row["converted_rule"])
                if action == "keep_both" and verdict == "conflict":
                    new_name = _free_name(name, taken)
                    rule["name"] = new_name
                    rec["note"] = f"两条并存：新条目改名为 {new_name}"
                else:
                    old = _rule_path(name)
                    if old.is_file():
                        # ⚠️ 覆盖前**必须**备份旧规则原文 —— 「可回滚」靠的就是这一行
                        db.ledger_history_add(
                            name, old.read_text(encoding="utf-8"),
                            rule_hash=(db.source_ledger_get(name) or {}).get("rule_hash", ""),
                            note=f"被 {origin or '导入'} 覆盖")
                        db.ledger_history_prune(name)
                store.add_rule(rule)
                taken.add(new_name)
                enabled = _raw_enabled(row["raw"])
                db.source_ledger_upsert(
                    new_name, origin=origin, dedup_key=row["dedup_key"], rule_hash=row["rule_hash"],
                    supported=row["supported"], source_type=row["source_type"],
                    group_name=row["group"], raw_json=json.dumps(row["raw"], ensure_ascii=False),
                    unsupported=row["unsupported_fields"], notes=row["notes"],
                    imported=True, enabled=enabled)
                # 源文件里 `enabled: false` 的条目**导进来就是停用**：台账刚写完，
                # 让 store 按它同步一次注册状态（否则它已经注册进 REGISTRY，界面上却是停用）
                store.set_enabled(new_name, enabled)
                rec["note"] = rec["note"] or f"已{'更新' if verdict == 'update' else '导入'}"
        except Exception as e:                               # noqa: BLE001 —— 逐条报，不整批失败
            rec["ok"] = False
            rec["note"] = str(e)
        items.append(rec)
    db.source_import_add(origin, counts, items, actor=actor)
    return {"counts": counts, "items": items}


def _raw_enabled(raw: dict) -> bool:
    """导入时**尊重源文件里的 ``enabled``**（Legado 里标 false 的条目导进来就是停用）。"""
    if not isinstance(raw, dict) or "enabled" not in raw:
        return True
    return bool(raw.get("enabled"))


def export_payload() -> dict:
    """导出为一份可再导入的文件：**原文优先**（导入过的存原始条目，手写的存规则本身）。

    ⚠️ 不带任何附加字段：附加键会改变 `rule_hash`，于是「导出的文件再导入一次」会被判成
    「有更新」而不是「重复」—— 那样导出→导入就不再幂等了（本轮点名的验收点之一）。
    """
    ledger = {r["name"]: r for r in db.source_ledger_all()}
    entries = []
    for s in store.list_sources():
        if not s["user"]:
            continue
        row = ledger.get(s["name"]) or {}
        raw = row.get("raw_json") or ""
        obj = None
        if raw:
            try:
                obj = json.loads(raw)
            except Exception:                                # noqa: BLE001
                obj = None
        # 没有原文（手写源 / 台账行丢了）就导出**规则本体** —— 走格式轴的序列化入口，
        # 调用方不必知道 native 的序列化是恒等（将来加别的格式就换适配器，不改这里）。
        fallback = formats.serialize_native(_read_rule(s["name"]) or {"name": s["name"]})
        entries.append(obj if isinstance(obj, dict) else fallback)
    return {"nf_export": 1, "exported_at": time.time(), "entries": entries}


def rollback(name: str, history_id: str) -> dict:
    """把某条历史里的旧规则还原回 `SOURCES_DIR`（「覆盖前已备份，可回滚」的落点）。"""
    h = db.ledger_history_one(history_id)
    if not h or h.get("name") != name:
        raise ValueError("找不到这条历史（可能已被清理）")
    rule = json.loads(h.get("payload") or "{}")
    store.add_rule(rule)
    db.source_ledger_upsert(name, rule_hash=h.get("rule_hash") or legado.rule_hash(rule),
                            supported="yes")
    return {"name": name, "restored": h["id"], "created_at": h.get("created_at")}
