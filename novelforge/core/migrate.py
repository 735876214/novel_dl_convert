"""把书在**书库之间**搬运（第 10 期自动归库；第 36 期起另有用户点选的跨库移动）。

为什么单独一个模块：迁移是**破坏性**操作（真移文件），必须有一处集中承载
「判据 + 幂等 + 冲突 + 回滚」四件事；散在 server / watcher 里迟早会写歪。

两条入口、同一台机器：

- **自动归库**（``preview`` / ``plan``，``direction="move"``）：按**格式**把散落在
  默认库里的书归进各类型库。第 10 期口径，行为不再改动。
- **跨库移动**（``move_preview`` / ``move_plan``，``direction="bookmove"``）：用户勾书、
  指定目标库。多两道闸门 —— **类型相容**（白名单决定扫描认不认，见 :func:`compat_reason`）
  与**副本随书搬**（口径③，见 :func:`copy_plan`）。

四条设计约束（两条入口都遵守）：

1. **判据只看格式**（ebook / comic / audiobook）：迁移要可解释、可复现。
   靠元数据关键词猜「这本奇幻该进哪个库」只用于**入库**归库（core/library_rules.py）。
2. **只挪库、不改名**：``name`` 是**库内相对路径**，换库根它不变；但第 17 期起
   ``book_id`` 是「库$哈希」，换库会让 id 的**库前缀**变化 —— 所以执行时用
   ``db.remap_book_id`` 把进度 / 批注 / 评分一起搬到新 id，数据不断链。**回滚必须反向
   搬一次**，否则文件回来了、数据留在废 id 上（第 36 期修的）。
   目标库已有同名文件时**拒绝覆盖**并给出建议名，改名与否由用户决定。
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
from . import activity_log, audio, db, fileops, lib_settings, library, publish

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


def _src_library_id_of(src: pathlib.Path) -> str:
    """由源文件绝对路径反查它所属的书库 id（搬库前它在哪个库）。"""
    try:
        want = src.resolve()
    except Exception:
        return library.DEFAULT_LIBRARY_ID
    for l in library.libraries():
        try:
            root = pathlib.Path(l.get("root_path") or "").resolve()
        except Exception:
            continue
        if root and str(want).startswith(str(root)):
            return str(l.get("id") or library.DEFAULT_LIBRARY_ID)
    return library.DEFAULT_LIBRARY_ID


def _suggest_name(root: pathlib.Path, name: str) -> str:
    """冲突时的建议名：``三体 (2).epub``（递增到不冲突为止）。

    ⚠️ 改名会换 ``book_id`` → 进度 / 批注断链，所以这里**只建议、不自动改**；
    真要改名应走「工具 → 书库管理 → 跨库同名冲突」的一键修复
    （``fileops.apply_conflict_rename``，它会把关联数据一起搬，见 db.remap_book_id）。
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


# ---------------- 用户发起的跨库移动（第 36 期）----------------
# 与上面「按格式自动归库」共用同一台机器（manifest 批次 / 逐条独立 / remap / 回滚），
# 差别只有三处：**谁选源集合**（用户点选 vs 全库扫描）、**谁定目标库**（显式指定 vs 按
# 格式推导）、**副本怎么处理**（随书搬 vs 不动）。所以不另开模块 —— 另开就得把
# 「逐条独立 / 幂等 / 回滚口径」再抄一遍，两处迟早会写歪。
#
# ⚠️ 自动归库那条路（``preview`` / ``plan`` / ``direction="move"``）**行为一字不改**：
# 它仍然不动副本、不改台账 —— 这是本期**有意**留下的边界（存量批次可能正躺在 pending
# 里等执行），不是漏做。要改它得单独一期。

#: ``library_migrations.direction`` 的取值，如实记录迁移是**谁发起的**。
#: ⚠️ 自动归库落库时写的就是字面量 ``"move"``，**不能改** ——
#: ``migration_last_batch("move")`` 与既有回滚入口都按它取批次。
DIR_AUTO = "move"
DIR_BOOKMOVE = "bookmove"


def _fmt_exts(exts) -> str:
    """扩展名清单 → 「EPUB / MOBI / PDF」（给人看的写法）。"""
    return " / ".join(e.lstrip(".").upper() for e in exts)


def compat_reason(book: dict, dst_lib: dict) -> str:
    """这本书能不能进那个库：能则返回 ``""``，不能则返回一句给人看的理由。

    判据**只有** :func:`library._exts_for_type` —— 库扫描白名单的唯一真值源，不新写
    第二处相容表（写了就一定会跟扫描漂移，然后「预览说能搬、搬完扫不到」）。
    为什么不留「先搬过去试试」的口子：白名单决定扫描认不认这个文件，
    **不相容不是「半可见」，是根本不出现在那个库的书目里**（``library.books()`` 扫不到），
    它的行当场变成孤儿。所以这是数据完整性闸门，不是 UX 偏好 —— 后端必须自己再拦一次，
    不能只靠前端把按钮置灰。
    """
    dst_type = str((dst_lib or {}).get("type") or "")
    label = str((dst_lib or {}).get("name") or "") or "目标库"
    allowed = library._exts_for_type(dst_type)
    if publish.is_dir_entry(book):
        # 目录型条目（有声书一章一文件）只在白名单含音频扩展名时才被算作一本书
        # —— 与 ``library._iter_book_entries`` 的 ``allow_audio_dir`` 同一判据。
        if set(audio.AUDIO_EXTS) & set(allowed):
            return ""
        return f"「{label}」只收 {_fmt_exts(allowed)}，认不出「一章一文件」的有声书目录"
    ext = pathlib.PurePosixPath(str(book.get("name") or "")).suffix.lower()
    if ext in allowed:
        return ""
    return (f"「{label}」只收 {_fmt_exts(allowed)}，这本是 "
            f"{ext.lstrip('.').upper() or '没有扩展名的文件'}")


def _lib_id_of_path(path) -> str:
    """由绝对路径反查所属库 —— **取路径最长（最具体）的那个库根**。

    与 :func:`_src_library_id_of` 只差一处：嵌套库根时（``库A/子目录`` 又被登记成一个库）
    取最长匹配，而不是「谁先遍历到算谁」。用户点名的源路径必须判准 —— 判错会算出错的
    旧 id（数据搬到不存在的 id 上），副本也会落到错的成品目录。``_src_library_id_of``
    的历史行为**不动**（自动归库路径照旧）。
    """
    try:
        want = str(pathlib.Path(str(path)).resolve())
    except Exception:                          # pragma: no cover —— 只有畸形路径才走到
        return library.DEFAULT_LIBRARY_ID
    best, best_len = library.DEFAULT_LIBRARY_ID, -1
    for l in library.libraries():
        raw = str(l.get("root_path") or "")
        if not raw:
            continue                           # 空根会 resolve 成 cwd，误匹配一大片
        try:
            root = str(pathlib.Path(raw).resolve())
        except Exception:                      # pragma: no cover
            continue
        if want.startswith(root) and len(root) > best_len:
            best, best_len = str(l.get("id") or library.DEFAULT_LIBRARY_ID), len(root)
    return best


def _rel_of(path, library_id: str) -> str:
    """绝对路径 → **库内相对路径**（``name`` 的口径）。取不到就退化成 basename。"""
    try:
        return pathlib.Path(str(path)).relative_to(library.root_of(library_id)).as_posix()
    except Exception:
        return pathlib.PurePosixPath(str(path)).name


def _copy_rel(book: dict, name: str, library_id: str) -> str:
    """副本在**该书库成品目录**下的相对落点（命名规则取该库的生效值）。

    ⚠️ 必须带上 ``book`` 的**全部**元数据（title / series / series_index …）只换 ``name``
    与 ``library_id``：命名规则里那些占位符就是靠它们填的，只传 ``{"name": ...}``
    会让 ``{series}`` 之类的模式算出不一样的名字 —— 于是预览与落盘各说各话。
    """
    b = dict(book)
    b["name"], b["library_id"] = str(name), str(library_id)
    return publish.relpath_for(b, lib_settings.config_for(library_id))


def copy_plan(book: dict, dst_library_id: str, final_name: str,
              ledger_id: str = None) -> dict:
    """副本（成品目录里那份）**随书搬**的计划。**预览与执行共用这一份算法**。

    ``ledger_id``：台账行**此刻**挂在哪个 id 上（默认就是这本书的 id）—— 正向移动在旧
    id、回滚在新 id，传错会读不到 ``link_rel`` 从而误判成「这本书没有副本」，静默漏搬。

    返回 ``{action, old_copy, new_copy, rel, reason}``，``action`` 取值：

    - ``none``：这本书没有副本（没刮削过，或台账记的副本已不在磁盘上）
    - ``left``：目标库没配成品目录 ⇒ 副本**留在原库**（口径③的边界，如实记账不静默）
    - ``same``：两个库共用同一成品目录、落点也一样 ⇒ 原地不动
    - ``reuse``：目标落点已经是**同一个 inode**（同一份数据的另一个硬链接）⇒ 回收旧链接
    - ``move``：搬过去（落点被外来文件占着时**退让改名**，绝不覆盖）
    """
    lib_id = str(book.get("library_id") or library.DEFAULT_LIBRARY_ID)
    out = {"action": "none", "old_copy": "", "new_copy": "", "rel": "", "reason": ""}
    led = db.scrape_get(ledger_id if ledger_id is not None else book.get("id")) or {}
    old_rel = str(led.get("link_rel") or "")
    old_pdir = publish.publish_dir(lib_id)
    if not old_rel or old_pdir is None:
        out["reason"] = "这本书还没有副本"
        return out
    old_copy = pathlib.Path(old_pdir / old_rel)
    out["old_copy"] = str(old_copy)
    if not old_copy.exists():
        out["reason"] = "台账记的副本已不在磁盘上"
        return out
    new_pdir = publish.publish_dir(dst_library_id)
    if new_pdir is None:
        out.update(action="left", old_copy=str(old_copy),
                   reason=f"目标库未配置成品目录，副本留在原库：{old_copy}")
        return out
    rel = _copy_rel(book, final_name, dst_library_id)
    new_copy = pathlib.Path(new_pdir / rel)
    if new_copy == old_copy:
        out.update(action="same", new_copy=str(new_copy), rel=rel,
                   reason="两个库共用同一成品目录，落点也一样")
        return out
    # 判据与出版共用一份：同 inode → 复用；别人的文件占着 → 退让改名（绝不覆盖）。
    verdict = publish.rel_verdict(new_pdir, rel, old_copy, "")
    if verdict == publish.REL_REUSE and new_copy.exists():
        out.update(action="reuse", new_copy=str(new_copy), rel=rel,
                   reason="目标落点已是同一份副本（同源硬链接）")
        return out
    if verdict == publish.REL_DECLINE:
        rel = publish.free_rel(new_pdir, rel)
        new_copy = pathlib.Path(new_pdir / rel)
        out["reason"] = "目标落点被外来文件占用，副本退让改名"
    out.update(action="move", new_copy=str(new_copy), rel=rel)
    return out


def _clean_new_name(raw, book: dict, dst_lib: dict) -> str:
    """校验用户给的**新名字**（库内相对路径），可疑输入抛 ``ValueError``。

    借 :func:`fileops.safe_path` 做空名 / 层级 / 路径穿越那道闸门（与改名、回收同一道），
    再自己补两条它管不着的：**形态不许变**（目录型有声书与带扩展名的文件不能互换）、
    **扩展名不许换**（``.epub`` 改 ``.txt`` 是换格式，该走转换而不是借移动偷偷改）。
    """
    name = str(raw or "").strip().replace("\\", "/")
    lib_id = str(dst_lib.get("id") or "")
    fileops.safe_path(name, lib_id)            # 空名 / 层级过深 / 穿越：这里就抛了
    if publish.is_dir_entry({"name": name}) != publish.is_dir_entry(book):
        raise ValueError("新名字的形态必须与原书一致（有声书目录不能改成带扩展名的文件，反之亦然）")
    old_ext = pathlib.PurePosixPath(str(book.get("name") or "")).suffix
    new_ext = pathlib.PurePosixPath(name).suffix
    if new_ext != old_ext:
        raise ValueError(f"扩展名不能改（{old_ext or '无'} → {new_ext or '无'}）")
    return name


def _move_items(book_ids, dst_library_id: str, decisions) -> tuple:
    """选择集 → 逐条预检（相容 / 冲突 / 副本计划）。**只读**：不建目录、不写库、不动文件。

    ``decisions``：``[{"id": book_id, "action": "move"|"rename"|"skip", "new_name": ...}]``
    —— 用户对冲突条目的处置。不传 = 全部按 ``move`` 处理（冲突即 ``conflict``）。

    返回 ``(dst_lib, items)``。``status`` 取值：``ready`` 可搬 / ``conflict`` 目标同名待用户
    决定 / ``blocked`` 搬不了（不相容、源已不在、已在目标库）/ ``skip`` 用户主动跳过。
    """
    dst_lib = library.get_library(dst_library_id) if dst_library_id else None
    if not dst_lib:
        raise ValueError("目标书库不存在")
    dst_lib_id = str(dst_lib.get("id") or "")
    dst_root = pathlib.Path(dst_lib.get("root_path") or config.OUTPUT_DIR)
    dec = {}
    for d in (decisions or []):
        if isinstance(d, dict) and d.get("id"):
            dec[str(d["id"])] = d

    items: list = []
    for bid in (book_ids or []):
        bid = str(bid)
        it = {
            "name": "", "book_id": bid, "title": "", "format": "",
            "target_type": str(dst_lib.get("type") or ""),
            "target_label": TYPE_LABELS.get(str(dst_lib.get("type") or ""), ""),
            "library_id": "", "library_name": "",
            "src": "", "is_dir": False,
            "dst_library_id": dst_lib_id, "dst_library_name": str(dst_lib.get("name") or ""),
            "dst": "", "status": "", "reason": "", "suggest": "",
            "copy": {"action": "none", "old_copy": "", "new_copy": "", "rel": "",
                     "reason": ""},
        }
        try:
            b = library.by_id(bid)
        except library.BookIdConflict as e:
            b = None
            it.update(status="blocked", reason=str(e))
        if b is None and not it["status"]:
            it.update(status="blocked", reason="这本书已不在库里（可能刚被移动或删除）")
        if it["status"]:
            items.append(it)
            continue

        src_lib = str(b.get("library_id") or library.DEFAULT_LIBRARY_ID)
        src = pathlib.Path(library.root_of(b)) / str(b.get("name") or "")
        it.update(name=str(b.get("name") or ""), title=str(b.get("title") or ""),
                  format=str(b.get("format") or "").upper(), library_id=src_lib,
                  library_name=str((library.get_library(src_lib) or {}).get("name") or ""),
                  src=str(src), is_dir=publish.is_dir_entry(b))
        if src_lib == dst_lib_id:
            it.update(status="blocked", reason="这本书已经在目标库里")
        elif not src.exists():
            it.update(status="blocked", reason="源已不在磁盘上（可能被移动或删除了）")
        else:
            why = compat_reason(b, dst_lib)
            if why:
                it.update(status="blocked", reason=why)
        if it["status"]:
            items.append(it)
            continue

        # 落点：默认「库内相对路径不变」（移动只换库，不改名）—— 与自动归库同一口径
        name = str(b.get("name") or "")
        action = str((dec.get(bid) or {}).get("action") or "").strip().lower()
        if action == "skip":
            it.update(status="skip", reason="按你的选择跳过")
            items.append(it)
            continue
        if action == "rename":
            try:
                name = _clean_new_name((dec.get(bid) or {}).get("new_name"), b, dst_lib)
            except ValueError as e:
                it.update(status="blocked", reason=str(e))
                items.append(it)
                continue
        dst = dst_root / name
        it["dst"] = str(dst)
        clash = library.id_conflict_with(name, dst_lib_id)
        if dst.exists():
            hit = clash["name"] if clash else ""
            if action == "rename":
                it.update(status="blocked",
                          suggest=library.suggest_name(name, dst_lib_id, dst_root),
                          reason=f"「{name}」在目标库里也被占着"
                                 + (f"（与「{hit}」撞同一 id）" if hit else ""))
            else:
                it.update(status="conflict", reason="目标库已有同名文件（拒绝覆盖）",
                          suggest=library.suggest_name(name, dst_lib_id, dst_root))
            items.append(it)
            continue
        if clash is not None:
            # 目标目录里没有这个名字，却已经有一本**别的路径**的书撞同一个 id：
            # 搬过去就会让 ``library.by_id`` 抛 BookIdConflict（该库的读点全挂）
            it.update(status="conflict",
                      reason=f"目标库里已有一本同名不同路径的书（「{clash['name']}」，会撞 id）",
                      suggest=library.suggest_name(name, dst_lib_id, dst_root))
            items.append(it)
            continue
        it["status"] = "ready"
        it["copy"] = copy_plan(b, dst_lib_id, name)
        items.append(it)
    return dst_lib, items


def move_preview(book_ids, dst_library_id: str, decisions=None) -> dict:
    """跨库移动的预检（**只读**）。

    「预览==落盘」是靠**共用** :func:`copy_plan` / :func:`library.suggest_name` /
    ``publish.rel_verdict`` 保证的，不是靠两边各写一遍 —— 所以这里算出来的 ``dst`` /
    ``copy.new_copy`` **就是**执行时用的那一个。
    """
    dst_lib, items = _move_items(book_ids, dst_library_id, decisions)
    counts = {k: sum(1 for i in items if i["status"] == k)
              for k in ("ready", "conflict", "blocked", "skip")}
    copies = {k: sum(1 for i in items if i["copy"]["action"] == k)
              for k in ("none", "left", "same", "reuse", "move")}
    return {
        "items": items, "total": len(items), **counts, "movable": counts["ready"],
        "dst_library_id": str(dst_lib.get("id") or ""),
        "dst_library_name": str(dst_lib.get("name") or ""),
        "copy_counts": copies,
        # 真会动磁盘的数量（前端照着写「将移动 N 本、其中 M 本副本随迁」）
        "will_move_files": counts["ready"],
        "will_move_copies": copies["move"] + copies["reuse"],
    }


def move_plan(book_ids, dst_library_id: str, decisions=None) -> dict:
    """把 ``ready`` 的条目落成 manifest（pending），返回批次。

    幂等口径与 :func:`plan` 逐字一致：``batch_id`` 由「条目集合 + 目标库」**确定性**派生，
    同一批重复点「移动」得到同一批次、不会重复落行；改了目标库或加/减了书 → 自然得到
    新批次。
    """
    pv = move_preview(book_ids, dst_library_id, decisions)
    movable = [i for i in pv["items"] if i["status"] == "ready"]
    if not movable:
        return {"batch_id": "", "created": 0, "reused": False, "items": [], "preview": pv,
                "message": "没有可移动的条目（都还在冲突 / 不相容 / 已跳过）"}
    sig = "\n".join(sorted(f"{i['src']}|{i['dst']}" for i in movable))
    batch_id = "bookmove-" + hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]
    reused = bool(db.migration_batch(batch_id))
    if not reused:
        for i in movable:
            db.migration_add(batch_id, DIR_BOOKMOVE, i["dst_library_id"], i["src"], i["dst"])
    return {"batch_id": batch_id, "created": len(movable), "reused": reused,
            "items": movable, "preview": pv, "message": ""}


# ---------------- 移动的落盘细节 ----------------

def _book_of(bid) -> "dict | None":
    """按 id 取书；id 撞车（同库同名不同路径）时返回 ``None`` 而不是抛。

    撞车不是这里能解决的（要用户改名，见 ``library.id_conflicts``）—— 移动照搬正本，
    副本与台账留一句实话就够，不该让整条搬运卡死。
    """
    try:
        return library.by_id(bid)
    except library.BookIdConflict:
        return None


def _move_ids(src: pathlib.Path, dst: pathlib.Path, dst_library_id: str) -> dict:
    """一条 manifest 行两侧的 id 与库内相对路径。**正向与回滚共用**。

    ``src`` / ``dst`` 始终指**正向**的「从哪来 / 到哪去」；回滚把结果掉个头用即可
    （数据此刻在 ``new_id`` 上，要搬回 ``old_id``）。
    """
    src_lib = _lib_id_of_path(src)
    dst_lib = str(dst_library_id)
    src_rel, dst_rel = _rel_of(src, src_lib), _rel_of(dst, dst_lib)
    return {"src_lib": src_lib, "src_rel": src_rel,
            "dst_lib": dst_lib, "dst_rel": dst_rel,
            "old_id": library.book_id(src_rel, src_lib),
            "new_id": library.book_id(dst_rel, dst_lib)}


def _bookmove_ctx(src: pathlib.Path, r: dict) -> dict:
    """搬之前把要用的东西一次取齐 —— 搬完再取就取不到了（扫描树已经变了）。

    ``book`` 取的是**扫描结果**（含生效元数据）：副本落点要用它的 title / series /
    series_index 去填命名规则，少一个都会算出不一样的名字。
    """
    ctx = _move_ids(src, pathlib.Path(str(r["dst"])), str(r["library_id"]))
    ctx["book"] = _book_of(ctx["old_id"])
    return ctx


def _apply_copy(cp: dict) -> None:
    """按 :func:`copy_plan` 的结论动副本（真搬移 / 回收旧链接 / 什么都不做）。"""
    act = cp["action"]
    if act == "reuse":
        # 目标落点已是同一份数据 ⇒ 旧链接只是个多余的名字；回收（可恢复，不 unlink）
        publish.recycle(cp["old_copy"], why="跨库移动：副本已在目标库")
        return
    if act != "move":
        return
    dst = pathlib.Path(cp["new_copy"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(cp["old_copy"], cp["new_copy"])   # 跨卷时自动退化为「复制 + 删除」


def _ledger_after_copy(src, copy_path, is_dir: bool) -> dict:
    """副本落地后，台账里那几个**关系列**按磁盘实况重量一遍。

    不沿用旧值：``link_mode`` / ``link_shared`` 说的是「这份副本与那个源是不是共享数据块」，
    而源刚换过 inode（跨卷移动必然换）。照抄旧值就是照着旧关系说话 —— 硬链接跨卷会退化成
    真复制，复制模式的副本换到同一卷上也可能仍不共享。所以问磁盘，不问台账。
    """
    p = pathlib.Path(str(copy_path))
    try:
        shared = (publish.tree_shared(src, p) if is_dir else publish.same_file(src, p))
    except OSError:                            # pragma: no cover —— 副本刚搬好，读不到极罕见
        shared = False
    out = {"link_mode": publish.LINK_HARD if shared else publish.LINK_COPY,
           "link_shared": 1 if shared else 0}
    try:
        sig = publish.source_sig(src)
        out.update(src_size=sig[0], src_mtime=sig[1])
    except OSError:                            # 量不到就只更新关系列，不写假数字
        pass
    return out


def _after_bookmove(r: dict, dst: pathlib.Path, ctx: dict, watcher) -> dict:
    """一本搬完之后的收尾：remap 关联数据 → 副本随书搬 → 台账改挂 → 通知 watcher。

    顺序有讲究：**先 remap、再动副本、最后写台账** —— 台账那一行要按「副本最终落在哪」
    写，写早了还得再改一次；而 remap 与副本无关，先做完它，副本那步即使失败，
    用户的进度 / 批注也已经在正确的位置上了。

    返回 ``{"copy": action, "note": "给人看的一句话"}``。
    """
    old_id, new_id, dst_lib = ctx["old_id"], ctx["new_id"], ctx["dst_lib"]
    if old_id != new_id:
        db.remap_book_id(old_id, new_id)

    note = ""
    book = ctx["book"]
    cp = (copy_plan(book, dst_lib, ctx["dst_rel"], ledger_id=old_id) if book else
          {"action": "none", "old_copy": "", "new_copy": "", "rel": "", "reason":
           f"扫描缓存里找不到这本书（{ctx['src_rel']}），副本未随书搬 —— 重扫后可再搬一次"})
    fields = {"library_id": dst_lib, "source_rel": ctx["dst_rel"]}
    if cp["action"] == "left":
        # 目标库没配成品目录：副本留在原库。台账如实标成「跳过」并写清副本在哪 ——
        # 留着 link_rel 指旧库成品目录就是一句假话（这行已经属于新库了），
        # 而清掉它又必须让人知道「磁盘上还有一份」，所以两者都做。
        fields.update(status="skipped", link_rel="", link_mode="", link_shared=0,
                      error=f"副本未随迁：{cp['old_copy']}")
        note = "副本留在原库（目标库未配置成品目录）"
    elif cp["action"] in ("move", "reuse", "same"):
        try:
            _apply_copy(cp)
        except Exception as e:                 # noqa: BLE001 —— 正本已经搬好，别把它判成失败
            fields["error"] = f"副本随迁失败：{e}"
            note = f"副本未随迁（{e}）"
        else:
            fields["link_rel"] = str(cp["rel"])
            fields.update(_ledger_after_copy(dst, cp["new_copy"],
                                            bool(book and publish.is_dir_entry(book))))
            note = cp["reason"]

    n = db.scrape_remap_item(old_id, new_id, **fields)
    if not n and (db.scrape_get(old_id) or {}).get("book_id"):
        note = _join_note(note, "台账未改挂（目标 id 上已有台账行）")

    if watcher is not None:
        # 去重键是「相对 input_dir 的路径 + (size, mtime)」——**移进来的文件在它眼里是一个
        # 全新路径**，不登记就会被当成新投递再入库一次（正本会被复制回来）。
        try:
            watcher.mark_processed(dst)
        except Exception as e:                 # noqa: BLE001 —— 登记失败不该让已经搬好的书变失败
            note = _join_note(note, f"watcher 登记失败（{e}），可能被重复入库")
    return {"copy": cp["action"], "note": note}


def _copy_back(book, src_lib: str, dst_lib: str, src_rel: str, dst_rel: str,
               ledger_id: str) -> tuple:
    """回滚时把副本从目标库成品目录搬回原库。返回 ``(回滚后的 link_rel, 是否真的动了)``。

    与正向同一口径：落点被占时**退让改名**，绝不覆盖（回滚也不许动别人的文件）。
    没有副本、或任一侧没配成品目录 → 原样返回 ``link_rel`` 且 ``moved=False``。
    """
    rel_now = str((db.scrape_get(ledger_id) or {}).get("link_rel") or "")
    from_pdir, to_pdir = publish.publish_dir(dst_lib), publish.publish_dir(src_lib)
    if not rel_now or from_pdir is None or to_pdir is None:
        return rel_now, False
    cur = pathlib.Path(from_pdir / rel_now)
    if not cur.exists():
        return rel_now, False
    want = (_copy_rel(book, src_rel, src_lib) if book
            else pathlib.PurePosixPath(str(src_rel)).name)
    back = pathlib.Path(to_pdir / want)
    back.parent.mkdir(parents=True, exist_ok=True)
    if back.exists():
        if publish.same_file(cur, back):
            publish.recycle(str(cur), why="跨库移动回滚：副本已在原位")
            return want, True
        want = publish.free_rel(to_pdir, want)
        back = pathlib.Path(to_pdir / want)
    shutil.move(str(cur), str(back))
    return want, True


def _after_bookmove_back(r: dict, src: pathlib.Path, dst: pathlib.Path, ctx: dict,
                         book, watcher) -> str:
    """回滚一本搬回去之后的收尾：反向 remap → 副本带回原库 → 台账改挂回原库 → 通知 watcher。

    与 :func:`_after_bookmove` 是同一件事的**镜像**，但刻意不复用它：那边的每一步方向都是
    反的，参数化到「一个函数两个方向」只会让两边都读不懂。真正该共用的是**判据**
    （落点退让、link_mode 重量、台账改挂），那几处本来就是共用函数。
    """
    old_id, new_id = ctx["old_id"], ctx["new_id"]
    src_lib, dst_lib = ctx["src_lib"], ctx["dst_lib"]
    if old_id != new_id:
        db.remap_book_id(new_id, old_id)          # 与 execute 的 remap 成对
    was = db.scrape_get(new_id) or {}
    rel, moved = _copy_back(book, src_lib, dst_lib, ctx["src_rel"], ctx["dst_rel"], new_id)
    fields = {"library_id": src_lib, "source_rel": ctx["src_rel"]}
    note = ""
    pdir_src = publish.publish_dir(src_lib)
    copy = pathlib.Path(pdir_src / rel) if (pdir_src is not None and rel) else None
    if copy is not None and copy.exists():
        fields["link_rel"] = rel
        if moved:
            fields.update(_ledger_after_copy(src, copy,
                                             bool(book and publish.is_dir_entry(book))))
        if str(was.get("error") or "").startswith(("副本未随迁", "副本随迁失败")):
            # **只撤回我们自己写下的那句**（正向那一步的失败标记）——别的 error 是别的
            # 流程留下的，回滚没资格替它抹掉。
            fields["error"] = ""
            if str(was.get("status") or "") == "skipped":
                # 正向因为「目标库没配成品目录」把状态降成了 skipped；现在副本就在原库
                # 原处、源也回来了 —— 那正是「已出版」的定义。只在**副本确实在**时才改：
                # 没有副本就不该自称已出版（宁可少认，不可错认）。
                fields["status"] = "ok"
        if not moved:
            note = "副本本来就在原库原位"
    else:
        fields.update(link_rel="", link_mode="", link_shared=0)
        note = "副本未随回滚" if rel else ""
    n = db.scrape_remap_item(new_id, old_id, **fields)
    if not n and (db.scrape_get(new_id) or {}).get("book_id"):
        note = _join_note(note, "台账未改挂（原 id 上已有台账行）")
    if watcher is not None:
        try:
            watcher.mark_processed(src)
        except Exception as e:                 # noqa: BLE001 —— 登记失败不该让回滚变失败
            note = _join_note(note, f"watcher 登记失败（{e}）")
    return note


def _join_note(note: str, extra: str) -> str:
    return f"{note}；{extra}" if note else extra


def _notify(on_row, done: int, total: int, dst) -> None:
    """进度回调：``on_row(已完成条数, 总条数, 书名)`` —— 数的是**真值**，不编造百分比。"""
    if on_row is None:
        return
    try:
        on_row(done, total, pathlib.PurePosixPath(str(dst)).name)
    except Exception:                          # noqa: BLE001 —— 回调是调用方的事，别带崩搬运
        pass


# ---------------- 执行 / 回滚 ----------------

def execute(batch_id: str, *, on_row=None, watcher=None) -> dict:
    """执行批次：逐条移动，**一条失败不影响其余**。已处理过的条目跳过（幂等）。

    按 manifest 行的 ``direction`` 分两条路（同一批次只可能是其中一种）：

    - ``move``（自动归库）：只搬正本、remap 关联数据 —— 第 10 期口径，本期**一字不改**。
    - ``bookmove``（用户点选的跨库移动）：正本 + **副本随书搬** + 台账改挂 + 通知 watcher。

    ``on_row``：``fn(done, total, name)``，每条**走到终态后**回调一次（成功 / 失败 / 早已
    处理过的都会调，所以进度条最后一定停在 ``total/total``）。
    ``watcher``：入库侧监听器，**按参数注入**（与 ``bookdock.reload(watcher, ...)`` 同一口径），
    不设模块级全局 —— 全局变量会让「谁在哪一刻注入了哪个 watcher」变得不可追踪。
    """
    rows = db.migration_batch(batch_id)
    if not rows:
        raise ValueError("迁移批次不存在")

    moved = failed = skipped = copies = 0
    errors: list = []
    notes: list = []
    total = len(rows)
    done = 0
    for r in rows:
        if r["status"] != "pending":
            skipped += 1
            done += 1
            _notify(on_row, done, total, r["dst"])
            continue
        src = pathlib.Path(str(r["src"]))
        dst = pathlib.Path(str(r["dst"]))
        is_bookmove = str(r.get("direction") or "") == DIR_BOOKMOVE
        try:
            if not src.exists():
                raise ValueError("源文件已不存在")
            if dst.exists():
                raise ValueError("目标已存在同名文件")
            dst.parent.mkdir(parents=True, exist_ok=True)
            # 要用的东西必须在**搬之前**取齐：搬完扫描树就变了，书名 / 元数据 / 旧 id
            # 都取不到（``_bookmove_ctx`` 里有详述）
            ctx = _bookmove_ctx(src, r) if is_bookmove else None
            shutil.move(str(src), str(dst))       # 跨卷时自动退化为「复制 + 删除」
        except Exception as e:                    # noqa: BLE001 —— 逐条兜底，继续搬其它
            reason = str(e) or e.__class__.__name__
            db.migration_mark(r["id"], "failed", reason)
            errors.append({"src": str(src), "dst": str(dst), "error": reason})
            failed += 1
            done += 1
            _notify(on_row, done, total, dst)
            continue
        if is_bookmove:
            res = _after_bookmove(r, dst, ctx, watcher)
            if res["copy"] in ("move", "reuse"):
                copies += 1
            if res["note"]:
                notes.append({"src": str(src), "note": res["note"]})
        else:
            # 库维度 id：搬库后 basename 不变但库前缀变了 → 关联数据搬到新 id，避免断链
            src_lib = _src_library_id_of(src)
            old_id = library.book_id(str(src), src_lib)
            new_id = library.book_id(str(dst), r["library_id"])
            if old_id != new_id:
                db.remap_book_id(old_id, new_id)
        if watcher is not None and not is_bookmove:
            # 自动归库这条路**只**补登记、不改其它行为（副本 / 台账照旧不动）
            try:
                watcher.mark_processed(dst)
            except Exception as e:                # noqa: BLE001
                notes.append({"src": str(src), "note": f"watcher 登记失败（{e}）"})
        db.migration_mark(r["id"], "done")
        moved += 1
        done += 1
        _notify(on_row, done, total, dst)

    library.invalidate()
    extra = f"、副本随迁 {copies} 本" if copies else ""
    activity_log.log(
        activity_log.ACTION_LAYOUT, f"书库迁移 {batch_id}",
        activity_log.STATUS_OK if not failed else activity_log.STATUS_FAIL,
        detail=f"迁移 {moved} 本、失败 {failed} 本、跳过 {skipped} 本{extra}", source="api",
    )
    return {"ok": not failed, "batch_id": batch_id, "moved": moved, "failed": failed,
            "skipped": skipped, "copies": copies, "errors": errors[:20], "notes": notes[:20],
            "items": db.migration_batch(batch_id)}


def rollback(batch_id: str, *, watcher=None) -> dict:
    """一键回滚：把该批次**已搬走**的文件移回原位（仅限 status=done 的条目）。

    ``bookmove`` 批次还要把**副本一起带回来**并把台账改挂回原库 —— 只搬正本的话，
    原库的架上少一本、新库多一本不在那儿的书，等于把移动做了一半。
    """
    rows = [r for r in db.migration_batch(batch_id) if r["status"] == "done"]
    if not rows:
        raise ValueError("该批次没有可回滚的条目")

    back = failed = 0
    errors: list = []
    notes: list = []
    for r in rows:
        src = pathlib.Path(str(r["src"]))
        dst = pathlib.Path(str(r["dst"]))
        is_bookmove = str(r.get("direction") or "") == DIR_BOOKMOVE
        try:
            if not dst.exists():
                raise ValueError("文件已不在目标位置")
            if src.exists():
                raise ValueError("原位置已有同名文件")
            src.parent.mkdir(parents=True, exist_ok=True)
            # 与 execute 同理：**搬之前**取齐 —— 副本要按书目的元数据算原落点，而文件
            # 一搬回去，扫描树里就查不到这本书了（``_book_of`` 会返回 None）。
            ctx = _move_ids(src, dst, str(r["library_id"])) if is_bookmove else None
            book = _book_of(ctx["new_id"]) if is_bookmove else None
            shutil.move(str(dst), str(src))
        except Exception as e:                    # noqa: BLE001
            reason = str(e) or e.__class__.__name__
            db.migration_mark(r["id"], "rollback_failed", reason)
            errors.append({"src": str(src), "dst": str(dst), "error": reason})
            failed += 1
            continue
        # 反向 remap：与 execute 的搬过去**必须成对**。缺了这一半，回滚就是
        # 「文件回来了、进度 / 批注 / 元数据留在废 id 上」—— 用户看到的是书回到了原处
        # 却「干干净净」，读点还都不报错，与本期 T1 修的静默断链同一个病。
        # 两侧 id 都用 id 的**定义式**重算（``库$basename 哈希``），不猜、不存快照：
        # 这样即使 manifest 行是上一版写下、或文件被手工挪过，算出来的也是当下真值。
        if is_bookmove:
            note = _after_bookmove_back(r, src, dst, ctx, book, watcher)
            if note:
                notes.append({"src": str(src), "note": note})
        else:
            # 自动归库：只反向搬关联数据（它本来就没动副本与台账，见模块头「有意留下的边界」）
            src_lib = _src_library_id_of(src)
            old_id = library.book_id(str(src), src_lib)
            new_id = library.book_id(str(dst), r["library_id"])
            if old_id != new_id:
                db.remap_book_id(new_id, old_id)
        db.migration_mark(r["id"], "rolled_back")
        back += 1

    library.invalidate()
    activity_log.log(
        activity_log.ACTION_LAYOUT, f"书库迁移回滚 {batch_id}",
        activity_log.STATUS_OK if not failed else activity_log.STATUS_FAIL,
        detail=f"回滚 {back} 本、失败 {failed} 本", source="api",
    )
    return {"ok": not failed, "batch_id": batch_id, "restored": back, "failed": failed,
            "errors": errors[:20], "notes": notes[:20], "items": db.migration_batch(batch_id)}


def last_batch(direction: str = "move") -> str:
    """最近一个批次 id（回滚入口默认取最近一次迁移批次）。"""
    return db.migration_last_batch(direction)
