"""回收站台账与还原（第 81 期）。

回收站 = ``CACHE_DIR/recycle``（见 :func:`fileops.recycle_dir`）。本模块管两件事：

1. **台账**：``recycle_items`` 表记「哪个原路径被移进了回收站、落点名是什么、为什么」，
   由 :func:`db.recycle_note` 在每次移入时写入（三个调用方：``publish.recycle``、
   ``fileops.recycle_items``、``bookdock.remove``）。**还原据此把东西搬回原路径。**
2. **还原**：``GET /api/recycle`` 列出现状（台账 + 磁盘实况 + 无台账的孤儿），
   ``POST /api/recycle/restore`` 逐项搬回（后台任务、逐项进度）。

⚠️ 三条约束（改这个模块前先读）：

- **绝不覆盖**：目标已存在时退让命名（``name (2).ext``），并在回执里如实说明实际落点。
  退让思路与 :func:`publish.free_rel` 一致（那道判据服务于「成品出版」，这里服务于还原）。
- **幂等可续跑**：还原成功后**删掉那条台账行**；再次请求同一 id 只会如实报「不在台账里」。
- **孤儿还原必须显式给目标目录**：台账缺失（第 81 期之前的历史回收，或用户手工丢进去的东西）
  时无从知道原路径，只能由用户指定一个目录，按「剥时间戳前缀」后的名字落进去。
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import shutil

from . import activity_log, db, fileops

#: 回收落点名的前缀（由 :func:`fileops.recycled_name` 写入）：``YYYYMMDD-HHMMSS_[n_]原名``。
_STAMP_RE = re.compile(r"^(\d{8}-\d{6})_(?:(\d+)_)?(.+)$", re.S)


def strip_stamp(name: str) -> tuple[str, str, int]:
    """剥回收落点名的时间戳前缀，返回 ``(剥完的名字, stamp, 重名序号)``。

    没有前缀（用户自己丢进回收目录的东西）⇒ ``(原名, "", 0)``。
    """
    m = _STAMP_RE.match(str(name))
    if not m:
        return str(name), "", 0
    return m.group(3), m.group(1), (int(m.group(2)) if m.group(2) else 0)


def free_path(dst: pathlib.Path) -> pathlib.Path:
    """目标已存在时找一个不冲突的新名字（``name (2).ext``）。**绝不静默覆盖**。

    思路与 :func:`publish.free_rel` 一致 —— 回收目录里放着的可能是用户自己存进去的
    同名文件，还原时覆盖它属于数据丢失。
    """
    if not dst.exists():
        return dst
    stem, suf = dst.stem, dst.suffix
    for i in range(2, 100):
        cand = dst.with_name(f"{stem} ({i}){suf}")
        if not cand.exists():
            return cand
    tag = hashlib.sha1(str(dst).encode("utf-8")).hexdigest()[:8]
    return dst.with_name(f"{stem}~{tag}{suf}")


def restore_one(src, dst) -> dict:
    """把回收站里的一份搬回 ``dst``（**文件与目录都行**）。

    返回 ``{state, dst, error?}``：``restored``（落在请求的目标上）/ ``renamed``
    （目标已被占，退让到 ``name (2).ext``）/ ``missing``（源不在回收站）/ ``failed``。
    """
    s = pathlib.Path(str(src))
    target = pathlib.Path(str(dst))
    if not s.exists():
        return {"state": "missing", "dst": str(target)}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        final = free_path(target)
        shutil.move(str(s), str(final))
    except OSError as e:
        return {"state": "failed", "dst": str(target), "error": f"{type(e).__name__}: {e}"}
    return {"state": "renamed" if final != target else "restored", "dst": str(final)}


def _safe_name(name: str) -> bool:
    """回收站条目的名字必须是**纯文件名**（不含分隔符 / ``..``）—— 防路径穿越。"""
    n = str(name or "")
    return bool(n) and n not in (".", "..") and "/" not in n and "\\" not in n


def plan_restore(ids=None, names=None, target_dir: str = "", all_items: bool = False) -> dict:
    """把还原请求解析成逐项计划。**只读**：不建目录、不搬文件。

    - ``ids``：台账行 id（还原到各自 ``orig_path``）；``all_items=True`` 时取全部台账行。
    - ``names``：回收目录里的**文件名**（无台账的孤儿还原；``target_dir`` 必填）。
    - 解析不出来的条目进 ``errors``（如实回报，不静默丢）。

    返回 ``{items: [{ledger_id, name, src, dst, label}], errors: [...]}``。
    """
    d = fileops.recycle_dir()
    items: list = []
    errors: list = []
    if all_items:
        ids = [r["id"] for r in db.recycle_list()]
    for rid in (ids or []):
        row = db.recycle_get(rid)
        if not row:
            errors.append({"id": rid, "error": "台账里没有这条记录（可能已经还原过了）"})
            continue
        name = str(row["recycled_name"])
        orig = str(row["orig_path"] or "")
        if not orig:
            errors.append({"id": rid, "error": "这条台账没有原路径，无法还原"})
            continue
        items.append({"ledger_id": int(rid), "name": name, "src": str(d / name),
                      "dst": orig, "label": pathlib.Path(orig).name})
    tdir = str(target_dir or "").strip()
    for nm in (names or []):
        n = str(nm)
        if not _safe_name(n):
            errors.append({"name": n, "error": "条目名非法"})
            continue
        if not tdir:
            errors.append({"name": n, "error": "无台账条目必须指定还原目录"})
            continue
        stripped, _stamp, _seq = strip_stamp(n)
        items.append({"ledger_id": None, "name": n, "src": str(d / n),
                      "dst": str(pathlib.Path(tdir) / stripped), "label": stripped})
    return {"items": items, "errors": errors}


def restore_many(items: list, on_row=None) -> dict:
    """逐项还原（供后台任务调用）。``on_row(done, total, label)`` 是进度回调。

    返回逐项计数：``restored``（原样搬回）/ ``renamed``（退让改名后搬回）/
    ``missing``（回收站里已经没有）/ ``failed``。**每一份都独立** —— 一份失败不带走其余，
    与「删书三份逐份回收」同一条纪律。
    """
    total = len(items)
    counts = {"restored": 0, "renamed": 0, "missing": 0, "failed": 0}
    details: list = []
    for i, it in enumerate(items, 1):
        label = str(it.get("label") or it.get("name") or "")
        try:
            res = restore_one(it.get("src"), it.get("dst"))
        except Exception as e:                          # noqa: BLE001 —— 单项异常不该中断整批
            res = {"state": "failed", "dst": str(it.get("dst") or ""),
                   "error": f"{type(e).__name__}: {e}"}
        state = str(res["state"])
        counts[state] = counts.get(state, 0) + 1
        ledger_id = it.get("ledger_id")
        if ledger_id is not None and state in ("restored", "renamed"):
            db.recycle_delete(ledger_id)
        details.append({"name": str(it.get("name") or ""), "state": state,
                        "dst": res.get("dst") or "", "error": res.get("error") or ""})
        activity_log.log(
            activity_log.ACTION_RECYCLE, label,
            activity_log.STATUS_OK if state in ("restored", "renamed") else activity_log.STATUS_FAIL,
            output=res.get("dst") or "",
            detail=("回收站还原" + ("（目标已存在，退让改名）" if state == "renamed" else ""))
            if state in ("restored", "renamed") else (res.get("error") or state),
            source="api",
        )
        if on_row is not None:
            try:
                on_row(i, total, label)
            except Exception:                           # noqa: BLE001 —— 进度回调失败不该中断
                pass
    out = {"total": total, **counts}
    out["errors"] = [d for d in details if d["state"] == "failed"]
    out["details"] = details
    return out


def list_items(limit: int = 0) -> dict:
    """回收站现状：**台账条目**（带磁盘实况）+ **无台账孤儿**（磁盘上有、表里没有）。

    ``limit`` 只作用于返回的条目数量（页面首屏不必拉 2400 条），计数始终是全量。
    """
    d = fileops.recycle_dir()
    rows = db.recycle_list()
    items: list = []
    for r in rows:
        name = str(r["recycled_name"])
        p = d / name
        orig = str(r["orig_path"] or "")
        exists = p.exists()
        items.append({
            "id": int(r["id"]), "name": name, "orig_path": orig,
            "orig_dir": str(pathlib.Path(orig).parent) if orig else "",
            "why": str(r["why"] or ""), "size": int(r["size"] or 0),
            "created_at": float(r["created_at"] or 0),
            "exists": exists, "kind": "dir" if p.is_dir() else "file",
        })
    items.sort(key=lambda x: x["id"], reverse=True)
    known = {str(r["recycled_name"]) for r in rows}
    orphans: list = []
    try:
        entries = sorted(d.iterdir())
    except Exception:                                   # noqa: BLE001 —— 回收目录读不到就当作空
        entries = []
    for p in entries:
        if p.name in known:
            continue
        stripped, stamp, _seq = strip_stamp(p.name)
        orphans.append({
            "name": p.name, "stripped": stripped, "stamp": stamp,
            "kind": "dir" if p.is_dir() else "file",
            "size": fileops.size_of(p),
        })
    total = len(items)
    shown = items[:int(limit)] if limit and int(limit) > 0 else items
    return {"dir": str(d), "items": shown, "total": total,
            "orphans": orphans, "orphan_total": len(orphans)}
