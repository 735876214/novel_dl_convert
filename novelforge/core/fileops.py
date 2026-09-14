"""成品文件操作：批量重命名与回收目录。

对应工具页里的三个「会改磁盘」的工具（实体管理 / 批量重命名 / 重复书籍）。

安全约定（三条硬约束，改这个模块前先读）：

1. **路径不越界**：所有文件名入参都过 :func:`safe_path` —— 不允许路径分隔符、
   ``..``、绝对路径、非法字符；解析后的父目录必须**恰好**是 ``OUTPUT_DIR``。
2. **一律「先预览、再应用」**：``plan_*`` 只算不改；``apply_rename`` 只接受前端
   回传的 ``{old, new}`` 条目并**再校验一遍**，不接受自由规则 ——
   避免同一套规则在前后端解释不一致时改错文件。
3. **删除即回收**：清理动作走 :func:`recycle_items`，把文件 move 进
   ``CACHE_DIR/recycle``（带时间戳前缀，重名自动加序号），**从不 unlink**。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import time

from .. import config
from . import activity_log, library, metadata

RECYCLE_DIRNAME = "recycle"

# 跨平台都不安全的文件名字符（含控制字符）
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# 其它非法字符（路径分隔符、Windows 保留结尾的点和空格）
_BAD_TAIL = re.compile(r"[. ]+$")

#: 批量重命名规则里可用的占位符，前端据此给出提示
PATTERN_FIELDS = ("{title}", "{author}", "{series}", "{index}", "{ext}")


def output_dir() -> pathlib.Path:
    return config.OUTPUT_DIR


def recycle_dir() -> pathlib.Path:
    d = config.CACHE_DIR / RECYCLE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------- 校验 ----------------

def safe_path(name: str) -> pathlib.Path:
    """把「文件名」解析成 ``OUTPUT_DIR`` 下的真实路径，任何可疑输入都抛 ValueError。"""
    raw = (name or "").strip()
    if not raw:
        raise ValueError("文件名为空")
    if raw in (".", "..") or pathlib.PurePath(raw).name != raw:
        raise ValueError(f"非法文件名：{name}")
    if _BAD_CHARS.search(raw):
        raise ValueError(f"文件名含非法字符：{name}")
    base = output_dir().resolve()
    p = (base / raw).resolve()
    if p.parent != base:
        raise ValueError(f"路径不在导出目录内：{name}")
    return p


def sanitize_stem(stem: str) -> str:
    """把用户输入的「新名（不含扩展名）」清洗成安全文件名。"""
    s = _BAD_CHARS.sub("", (stem or "").strip())
    s = _BAD_TAIL.sub("", s)
    return s.strip()


# ---------------- 预览 ----------------

def _mk_item(old: str, new: str) -> dict:
    return {"old": old, "new": new, "conflict": False, "reason": ""}


def _mark_conflicts(items: list) -> list:
    """标出冲突：新名与原名相同、两条目撞名、目标已存在、新名非法。"""
    olds = {it["old"] for it in items}
    taken: dict = {}
    for it in items:
        new = it["new"]
        if new == it["old"]:
            it["conflict"], it["reason"] = True, "新名与原名相同"
        if new in taken:
            it["conflict"] = True
            it["reason"] = f"与「{taken[new]}」的目标名重复"
        else:
            taken[new] = it["old"]
        try:
            tgt = safe_path(new)
        except ValueError as e:
            it["conflict"], it["reason"] = True, str(e)
            continue
        if tgt.exists() and new not in olds:
            it["conflict"], it["reason"] = True, "目标文件已存在"
    return items


def plan_entity_rename(kind: str, frm: str, to: str) -> dict:
    """把某作者 / 系列名批量改成另一个名字 —— **基于文件名**。

    作者名按本项目约定写在文件名里（``《书名》作者：某某.epub``），所以改名即改
    文件名，改完 ``metadata.from_filename`` 解析出的作者也随之变化。
    系列名通常只存在于 EPUB 内部元数据、文件名里没有，因此**只替换文件名中
    确实出现过的部分**，不凭空编造文件名（改不出条目时前端会给出解释）。
    """
    frm, to = (frm or "").strip(), (to or "").strip()
    if not frm or not to:
        raise ValueError("原名称与新名称都不能为空")
    if not sanitize_stem(to):
        raise ValueError("新名称含非法字符")
    field = "author" if kind == "author" else "series"

    items = []
    for b in library.books():
        cur = (b.get(field) or "").strip()
        if cur != frm:
            continue
        p = pathlib.Path(b["name"])
        stem, suffix = p.stem, p.suffix
        if frm in stem:
            new_stem = stem.replace(frm, to, 1)
        elif field == "author":
            # 作者名没写在文件名里：按本项目命名约定重建，结果可预期
            new_stem = f"《{b['title']}》作者：{to}"
        else:
            continue
        new_stem = sanitize_stem(new_stem)
        if not new_stem:
            continue
        items.append(_mk_item(b["name"], f"{new_stem}{suffix}"))

    return {"type": kind, "from": frm, "to": to, "items": _mark_conflicts(items)}


def plan_merge(kind: str, source: str, target: str) -> dict:
    """合并实体 = 把 ``source`` 名下所有书改挂到 ``target``，即一次改名预览。"""
    return plan_entity_rename(kind, source, target)


def plan_pattern_rename(scope: str, pattern: str) -> dict:
    """按规则生成「旧名 → 新名」预览。

    规则里可用 ``{title}`` / ``{author}`` / ``{series}`` / ``{index}`` / ``{ext}``。
    ``scope`` 传扩展名（如 ``epub``，不带点）可只处理该格式；留空或 ``all`` 表示全部。
    """
    pat = (pattern or "").strip()
    if not pat:
        raise ValueError("重命名规则不能为空")
    if _BAD_CHARS.search(pat):
        raise ValueError("规则里不能含 \\ / : * ? \" < > | 这些字符")

    want = (scope or "").strip().lstrip(".").lower()
    items = []
    idx = 0
    for b in library.books():
        suffix = pathlib.Path(b["name"]).suffix
        if want and want != "all" and suffix.lstrip(".").lower() != want:
            continue
        idx += 1
        stem = pathlib.Path(b["name"]).stem
        filled = (
            pat.replace("{title}", b["title"] or stem)
            .replace("{author}", b["author"] or "未知")
            .replace("{series}", b["series"] or "无系列")
            .replace("{index}", f"{idx:02d}")
            .replace("{ext}", suffix.lstrip("."))
        )
        new_stem = sanitize_stem(filled)
        if not new_stem:
            continue
        items.append(_mk_item(b["name"], f"{new_stem}{suffix}"))

    return {
        "scope": want or "all",
        "pattern": pat,
        "fields": list(PATTERN_FIELDS),
        "items": _mark_conflicts(items),
    }


# ---------------- 应用 ----------------

def apply_rename(items: list) -> dict:
    """执行改名。只认 ``{old, new}``；冲突项与非法项一律跳过并记失败日志。"""
    if not isinstance(items, list) or not items:
        raise ValueError("没有可应用的条目")

    renamed, errors = [], []
    for it in items:
        it = it if isinstance(it, dict) else {}
        old = str(it.get("old") or "").strip()
        new = str(it.get("new") or "").strip()
        if it.get("conflict"):
            errors.append({"old": old, "error": "存在冲突，已跳过"})
            continue
        try:
            src, dst = safe_path(old), safe_path(new)
            if not src.is_file():
                raise ValueError("源文件不存在")
            if dst.exists():
                raise ValueError("目标文件已存在")
            src.rename(dst)
        except Exception as e:
            errors.append({"old": old, "error": str(e)})
            activity_log.log(activity_log.ACTION_RENAME, old, activity_log.STATUS_FAIL,
                             detail=str(e), source="api")
            continue
        renamed.append({"old": old, "new": new})
        activity_log.log(activity_log.ACTION_RENAME, old, activity_log.STATUS_OK,
                         output=new, source="api")

    library.invalidate()
    return {"renamed": renamed, "errors": errors, "count": len(renamed)}


def recycle_items(names: list, reason: str = "") -> dict:
    """把若干成品文件移入回收目录（**不是删除**），返回回收目录路径。"""
    if not isinstance(names, list) or not names:
        raise ValueError("没有要清理的条目")

    dest_dir = recycle_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved, errors = [], []
    for name in names:
        label = str(name or "").strip()
        try:
            src = safe_path(label)
            if not src.is_file():
                raise ValueError("文件不存在")
            dst = dest_dir / f"{stamp}_{src.name}"
            n = 1
            while dst.exists():
                dst = dest_dir / f"{stamp}_{n}_{src.name}"
                n += 1
            shutil.move(str(src), str(dst))
        except Exception as e:
            errors.append({"name": label, "error": str(e)})
            activity_log.log(activity_log.ACTION_RECYCLE, label, activity_log.STATUS_FAIL,
                             detail=str(e), source="api")
            continue
        moved.append({"name": label, "moved_to": dst.name})
        activity_log.log(activity_log.ACTION_RECYCLE, label, activity_log.STATUS_OK,
                         output=dst.name, detail=reason or "移入回收目录", source="api")

    library.invalidate()
    return {"moved": moved, "errors": errors, "recycle_dir": str(dest_dir)}


def resolve_duplicates(keep: str, remove: list) -> dict:
    """重复书籍处理：``remove`` 里的文件移入回收目录，``keep`` 仅用于日志备注。"""
    keep = (keep or "").strip()
    result = recycle_items(remove, reason=f"保留重复项：{keep}" if keep else "重复书籍清理")
    result["keep"] = keep
    return result
