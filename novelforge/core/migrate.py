"""按格式把现有书迁移进各**类型库**（第 10 期 D8）。

为什么单独一个模块：迁移是**破坏性**操作（真移文件），必须有一处集中承载
「判据 + 幂等 + 冲突 + 回滚」四件事；散在 server / watcher 里迟早会写歪。

四条设计约束：

1. **判据只看格式**（ebook / comic / audiobook）：迁移要可解释、可复现。
   靠元数据关键词猜「这本奇幻该进哪个库」只用于**入库**归库（core/library_rules.py）。
2. **只挪库、不改名**：``name`` 是**库内相对路径**，换库根它不变，因此
   ``book_id``（basename 派生，见 library._book_id）不变 —— 进度 / 批注 / 评分
   不会断链。目标库已有同名文件时**拒绝覆盖**并给出建议名，改名与否由用户决定。
3. **manifest 先行**：每条 ``src → dst`` 在执行前落 ``library_migrations``（pending），
   执行后标 done/failed。于是：重复启动不会重复搬（幂等依据），回滚有据可依。
4. **逐条独立**：一条失败不影响其余；原因逐条入账，最后汇总返回。

门禁（第 10 期决策）：启动时**只出预览**，真正搬运要用户点一次确认；
答过「暂不迁移」后记进 ``app_state``，不再每次启动打扰；设置里可勾「以后自动执行」。
"""
import hashlib
import json
import pathlib
import shutil
import time

from .. import config
from . import activity_log, audio, db, library

#: 迁移门禁在 app_state 里的键（存 JSON：用户答过就不再打扰）
GATE_KEY = "library_migration_gate"

#: 类型库展示名（后端日志 / 预览文案共用一个来源，避免各处各写一套）
TYPE_LABELS = {"ebook": "电子书库", "comic": "漫画库", "audiobook": "有声书库",
               "mixed": "混合库"}

#: 向导用的默认命名与来源子目录名（**只是默认值**，用户可改）
SUGGEST = {
    "ebook": ("电子书库", "ebooks"),
    "comic": ("漫画库", "comics"),
    "audiobook": ("有声书库", "audiobooks"),
}

#: 迁移的目标类型；``mixed`` 不在列 —— 它本身就是「未归类」的容身之所
TARGET_TYPES = ("ebook", "comic", "audiobook")

_COMIC_FMT = {"CBZ", "CBR"}
_EBOOK_FMT = {"EPUB", "MOBI", "AZW3", "PDF", "TXT"}


# ---------------- 判据 ----------------

def _type_of_path(name: str) -> str:
    """扩展名兜底判定（目录形态的有声书由 ``format=AUDIO`` 覆盖，走不到这里）。"""
    ext = pathlib.PurePosixPath(str(name or "")).suffix.lower()
    if ext in library._exts_for_type("comic"):
        return "comic"
    if ext in audio.AUDIO_EXTS:
        return "audiobook"
    if ext in library._exts_for_type("ebook"):
        return "ebook"
    return ""


def target_type_of(book: dict) -> str:
    """书 → 目标库类型（先看 ``format``，缺失才回退扩展名）。"""
    fmt = str((book or {}).get("format") or "").upper()
    if fmt in _COMIC_FMT:
        return "comic"
    if fmt == "AUDIO":
        return "audiobook"
    if fmt in _EBOOK_FMT:
        return "ebook"
    return _type_of_path((book or {}).get("name") or "")


def libraries_of_type(ltype: str) -> list:
    """某类型的全部库（正常每类一个；多出来的会在预览里标为需指定目标）。"""
    t = str(ltype or "")
    return [l for l in library.libraries() if str(l.get("type") or "") == t]


def _suggest_name(root: pathlib.Path, name: str) -> str:
    """冲突时的建议名：``三体 (2).epub``（递增到不冲突为止）。

    ⚠️ 改名会换 ``book_id`` → 进度 / 批注断链，所以这里**只建议、不自动改**；
    真要改名应走「批量重命名」（它会把关联数据一起搬，见 db.remap_book_id）。
    """
    p = pathlib.PurePosixPath(str(name))
    stem, suffix, parent = p.stem, p.suffix, str(p.parent)
    for i in range(2, 100):
        cand = f"{stem} ({i}){suffix}"
        rel = cand if parent in ("", ".") else f"{parent}/{cand}"
        if not (root / rel).exists():
            return rel
    return str(name)


# ---------------- 门禁状态 ----------------

def gate_state() -> dict:
    """迁移门禁：用户是否已答过、设置里是否勾了「以后自动执行」。"""
    info: dict = {}
    try:
        raw = db.state_get(GATE_KEY, "")
        if raw:
            loaded = json.loads(raw)
            info = loaded if isinstance(loaded, dict) else {}
    except Exception:                      # 坏值不该让整个预览接口 500
        info = {}
    try:
        cfg = (config.load_config() or {}).get("libraries") or {}
    except Exception:
        cfg = {}
    return {
        "dismissed": bool(info.get("dismissed_at")),
        "dismissed_at": float(info.get("dismissed_at") or 0),
        "note": str(info.get("note") or ""),
        "auto_migrate": bool(cfg.get("auto_migrate")),
    }


def dismiss(note: str = "") -> dict:
    """记下「暂不迁移」（在设置里重新开启前不再打扰）。"""
    db.state_set(GATE_KEY, json.dumps({"dismissed_at": time.time(), "note": str(note or "")}))
    return gate_state()


def reset_gate() -> dict:
    """清掉门禁状态 → 下次启动重新提示（设置页「已迁移/继续迁移」用）。"""
    db.state_delete(GATE_KEY)
    return gate_state()


# ---------------- 预览 ----------------

def _pick_dst(ltype: str, targets: dict):
    """选定目标库：显式指定优先 → 唯一同类库 → 否则 ``None``（缺失或需指定）。"""
    dsts = libraries_of_type(ltype)
    want = str((targets or {}).get(ltype) or "")
    if want:
        return next((l for l in dsts if str(l.get("id")) == want), None)
    return dsts[0] if len(dsts) == 1 else None


def preview(targets: dict = None) -> dict:
    """待迁移概览（**只读**：不建库、不写台账）。

    ``targets``：``{类型: 库 id}``，用于「同类库有多个」时指定目标。
    """
    items: list = []
    missing: set = set()
    for b in library.books():
        t = target_type_of(b)
        if not t:
            continue                          # 不认识的格式：不动它（宁可漏迁，不可乱迁）
        cur_id = str(b.get("library_id") or library.DEFAULT_LIBRARY_ID)
        dsts = libraries_of_type(t)
        if any(str(l.get("id")) == cur_id for l in dsts):
            continue                          # 已在同类型库里 → 无需迁移
        dst = _pick_dst(t, targets)
        it = {
            "name": b["name"], "book_id": b["id"], "title": b.get("title") or "",
            "format": str(b.get("format") or "").upper(), "target_type": t,
            "target_label": TYPE_LABELS.get(t, t),
            "library_id": cur_id,
            "library_name": str((library.get_library(cur_id) or {}).get("name") or ""),
            "src": str(library.root_of(b) / b["name"]),
            "dst_library_id": "", "dst_library_name": "", "dst": "",
            "status": "", "reason": "", "suggest": "",
        }
        if not dsts:
            missing.add(t)
            it["status"] = "no_library"
            it["reason"] = f"还没有「{TYPE_LABELS.get(t, t)}」—— 先建库再迁移"
        elif dst is None:
            it["status"] = "ambiguous"
            it["reason"] = "存在多个同类库，需要指定目标库"
        else:
            root = pathlib.Path(dst.get("root_path") or config.OUTPUT_DIR)
            it["dst_library_id"] = str(dst.get("id") or "")
            it["dst_library_name"] = str(dst.get("name") or "")
            it["dst"] = str(root / b["name"])
            if (root / b["name"]).exists():
                it["status"] = "conflict"
                it["reason"] = "目标库已有同名文件（拒绝覆盖）"
                it["suggest"] = _suggest_name(root, b["name"])
            else:
                it["status"] = "ready"
        items.append(it)

    counts = {k: sum(1 for i in items if i["status"] == k)
              for k in ("ready", "conflict", "no_library", "ambiguous")}
    gate = gate_state()
    return {
        "items": items, "total": len(items), **counts,
        "movable": counts["ready"],
        "blocked": counts["conflict"] + counts["ambiguous"],
        "missing_types": sorted(missing),
        "missing_labels": [TYPE_LABELS[t] for t in sorted(missing)],
        "suggest_specs": suggest_specs(),
        "gate": gate,
        # 有东西可搬、且用户没答过「暂不迁移」、且没勾自动执行 → 前端应阻塞式确认一次
        "needs_confirm": counts["ready"] > 0 and not gate["dismissed"] and not gate["auto_migrate"],
    }


def suggest_specs() -> list:
    """向导用：为**缺失**的类型库给出两套位置方案（就地引用 / 独立存储）。

    只给默认值，不落库；用户选定后由调用方建库（见 server 的书库 CRUD）。

    ⚠️ 库里只存**来源子目录名**（相对 ``LIBRARY_SOURCE_DIR``），不存来源的绝对路径 ——
    挂载点换了之后绝对路径会失效，相对子目录不会。``import`` 模式另有自己的存储根
    （``DATA_DIR/libraries/<id>``，与配置同卷、随备份）。
    """
    out = []
    for t in TARGET_TYPES:
        if libraries_of_type(t):
            continue
        name, sub = SUGGEST[t]
        out.append({
            "id": t, "type": t, "name": name, "source_subdir": sub,
            "inplace": {"mode": "inplace", "root_path": str(config.LIBRARY_SOURCE_DIR / sub)},
            "import": {"mode": "import", "root_path": str(config.DATA_DIR / "libraries" / t)},
        })
    return out


# ---------------- 计划（落 manifest）----------------

def plan(targets: dict = None) -> dict:
    """把预览里 ``ready`` 的条目落成 manifest（pending），返回批次。

    ``batch_id`` 由「条目集合」**确定性**派生：同一批文件重复 plan 得到同一批次，
    因此不会重复落行（幂等）。要换目标库时条目集合会变 → 自然得到新批次。
    """
    pv = preview(targets)
    movable = [i for i in pv["items"] if i["status"] == "ready"]
    if not movable:
        return {"batch_id": "", "created": 0, "reused": False, "items": [], "preview": pv,
                "message": "没有可自动迁移的条目" if pv["total"] else "没有需要迁移的书"}

    sig = "\n".join(sorted(f"{i['src']}|{i['dst']}" for i in movable))
    batch_id = "auto-" + hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]
    reused = bool(db.migration_batch(batch_id))
    if not reused:
        for i in movable:
            db.migration_add(batch_id, "move", i["dst_library_id"], i["src"], i["dst"])
    return {"batch_id": batch_id, "created": len(movable), "reused": reused,
            "items": movable, "preview": pv, "message": ""}


def pending_batches() -> list:
    """全部批次概览（含进度计数），供「书库管理」页展示。"""
    out = []
    for b in db.migration_batches(50):
        rows = db.migration_batch(b["batch_id"])
        out.append({
            **b,
            "pending": sum(1 for r in rows if r["status"] == "pending"),
            "done": sum(1 for r in rows if r["status"] == "done"),
            "failed": sum(1 for r in rows if r["status"] == "failed"),
            "rolled_back": sum(1 for r in rows if r["status"] == "rolled_back"),
        })
    return out


# ---------------- 执行 / 回滚 ----------------

def execute(batch_id: str) -> dict:
    """执行批次：逐条移动，**一条失败不影响其余**。已处理过的条目跳过（幂等）。"""
    rows = db.migration_batch(batch_id)
    if not rows:
        raise ValueError("迁移批次不存在")

    moved = failed = skipped = 0
    errors: list = []
    for r in rows:
        if r["status"] != "pending":
            skipped += 1
            continue
        src = pathlib.Path(str(r["src"]))
        dst = pathlib.Path(str(r["dst"]))
        try:
            if not src.exists():
                raise ValueError("源文件已不存在")
            if dst.exists():
                raise ValueError("目标已存在同名文件")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))       # 跨卷时自动退化为「复制 + 删除」
        except Exception as e:                    # noqa: BLE001 —— 逐条兜底，继续搬其它
            reason = str(e) or e.__class__.__name__
            db.migration_mark(r["id"], "failed", reason)
            errors.append({"src": str(src), "dst": str(dst), "error": reason})
            failed += 1
            continue
        db.migration_mark(r["id"], "done")
        moved += 1

    library.invalidate()
    activity_log.log(
        activity_log.ACTION_LAYOUT, f"书库迁移 {batch_id}",
        activity_log.STATUS_OK if not failed else activity_log.STATUS_FAIL,
        detail=f"迁移 {moved} 本、失败 {failed} 本、跳过 {skipped} 本", source="api",
    )
    return {"ok": not failed, "batch_id": batch_id, "moved": moved, "failed": failed,
            "skipped": skipped, "errors": errors[:20], "items": db.migration_batch(batch_id)}


def rollback(batch_id: str) -> dict:
    """一键回滚：把该批次**已搬走**的文件移回原位（仅限 status=done 的条目）。"""
    rows = [r for r in db.migration_batch(batch_id) if r["status"] == "done"]
    if not rows:
        raise ValueError("该批次没有可回滚的条目")

    back = failed = 0
    errors: list = []
    for r in rows:
        src = pathlib.Path(str(r["src"]))
        dst = pathlib.Path(str(r["dst"]))
        try:
            if not dst.exists():
                raise ValueError("文件已不在目标位置")
            if src.exists():
                raise ValueError("原位置已有同名文件")
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
        except Exception as e:                    # noqa: BLE001
            reason = str(e) or e.__class__.__name__
            db.migration_mark(r["id"], "rollback_failed", reason)
            errors.append({"src": str(src), "dst": str(dst), "error": reason})
            failed += 1
            continue
        db.migration_mark(r["id"], "rolled_back")
        back += 1

    library.invalidate()
    activity_log.log(
        activity_log.ACTION_LAYOUT, f"书库迁移回滚 {batch_id}",
        activity_log.STATUS_OK if not failed else activity_log.STATUS_FAIL,
        detail=f"回滚 {back} 本、失败 {failed} 本", source="api",
    )
    return {"ok": not failed, "batch_id": batch_id, "restored": back, "failed": failed,
            "errors": errors[:20], "items": db.migration_batch(batch_id)}


def last_batch(direction: str = "move") -> str:
    """最近一个批次 id（回滚入口默认取最近一次迁移批次）。"""
    return db.migration_last_batch(direction)
