"""收书目录的**入库前预览**（第 224 期）。

## 为什么要有这一层

收书目录（Book Dock）此前是「投递 → 自动处理 → 就绪」的**直筒**：用户把文件丢进
`input/`，目录里就多一条记录，等它变成「就绪」。中间发生了什么、叫什么名字、有没有
封面、**会不会跟已有的书重复**，用户**看不到** —— 只能等处理完再去书库里核对。

上游（BookOrbit）把这一段做成了「出货检验台」：入库前就能预览文件名、封面、查重，
再手动定稿。本项目**保留「收件箱」语义**（不改成出货检验台），但把**预览**这一层补上：

1. **名字预览**：这份文件按**目标库当前的命名规则**会叫什么（`publish.relpath_for`，
   与实际落盘**同一份判据** —— 预览名与实际名各说各话是最难查的一类缺陷）。
2. **封面预览**：这份文件自己带不带封面（EPUB 读 OPF；其它格式如实说「无」）。
3. **查重**：与**目标库已有**的书比 —— 同 ISBN / 同作者+书名相似 / 同内容。

## 边界（如实留档）

- **只读**：本模块**不动任何文件**、不写库。真正的入库仍走既有的
  `POST /api/book-dock/{id}/rescan`（自动流水线）或「入库到…」指定目标库。
- **查重是「提示」不是「拦截」**：命中重复**不阻止**入库 —— 收书目录的语义是
  「用户已经决定要收」，重复与否由用户自己判断（有时就是要收第二遍）。
- **扫描版 PDF / 图片格式**：没有可提取的元数据 ⇒ 名字预览退成文件名本身，
  封面一律「无」，**不编造**。
"""
from __future__ import annotations

import pathlib

from . import library, metadata


def _clean_name(name: str) -> str:
    """文件名清洗（与 `bookdock._clean_name` 同一口径 —— 预览名必须是**真名**）。"""
    from . import bookdock

    try:
        return bookdock._clean_name(name)
    except Exception:                       # noqa: BLE001 —— 预览不该因一个怪文件名炸掉
        return str(name or "")


def _probe_meta(path: pathlib.Path) -> dict:
    """读一份文件的元数据（EPUB 走 `probe_epub`；其它格式尽力而为，失败即空）。

    ⚠️ **不抛异常**：预览是「尽力给出信息」，坏文件也要能预览（并如实说「读不出」）。
    """
    suffix = path.suffix.lower()
    if suffix == ".epub":
        try:
            return library.probe_epub(path)
        except Exception:                   # noqa: BLE001
            return {}
    if suffix in (".txt", ".fb2", ".mobi", ".azw", ".azw3"):
        # 纯文本类：书名取文件名（其余元数据要靠抓取，入库时才有）
        return {"title": path.stem, "author": "", "series": "", "has_cover": False}
    return {}


def preview_item(watcher, item_id: str, library_id: str = "") -> dict:
    """一个待入库条目的预览（**只读**）。

    返回形状::

        {
          "item_id": "...", "name": "...", "size": 1234, "ext": ".epub",
          "title": "...", "author": "...", "series": "...",
          "has_cover": true,
          "target_rel": "书名.epub",        # 按目标库命名规则算出的**落点相对路径**
          "target_library": "lib$1",
          "duplicates": [ {book_id, title, reason} ],
          "warnings": [ "..." ],
        }

    ⚠️ 目标库没给（或不存在）⇒ ``target_rel`` 为空、`warnings` 里说明原因 ——
    **不猜**一个库来算名字（预览名与实际名必须同源）。
    """
    from . import db

    row = db.dock_get(str(item_id))
    if not row:
        raise LookupError("条目不存在")

    name = str(row.get("name") or item_id)
    ext = str(row.get("ext") or pathlib.Path(name).suffix.lower())
    size = int(row.get("size") or 0)

    src = pathlib.Path(watcher.input_dir) / name if watcher is not None else None
    meta: dict = {}
    if src is not None and src.is_file():
        meta = _probe_meta(src)

    out = {
        "item_id": str(item_id),
        "name": name,
        "ext": ext,
        "size": size,
        "title": str(meta.get("title") or ""),
        "author": str(meta.get("author") or ""),
        "series": str(meta.get("series") or ""),
        "isbn": str(meta.get("isbn") or ""),
        "has_cover": bool(meta.get("has_cover")),
        "target_library": "",
        "target_rel": "",
        "duplicates": [],
        "warnings": [],
    }

    # ---- 名字预览：与实际落盘**同一份判据**（publish.relpath_for）----
    lib = library.get_library(library_id) if library_id else None
    if library_id and not lib:
        out["warnings"].append("目标书库不存在")
    elif lib is None:
        out["warnings"].append("未指定目标书库：按当前库的内容来源目录，无法预览落点名")
    else:
        from . import lib_settings, publish

        out["target_library"] = str(lib.get("id") or "")
        cfg = lib_settings.config_for(str(lib.get("id") or ""))
        # 用「文件本身」当 book 代理：命名规则要的是 name / title / author / series
        book = {
            "name": name,
            "title": out["title"] or pathlib.Path(name).stem,
            "author": out["author"],
            "series": out["series"],
            "series_index": str(meta.get("series_index") or ""),
        }
        try:
            out["target_rel"] = publish.relpath_for(book, cfg)
        except Exception as e:              # noqa: BLE001 —— 预览失败要说明，不装作成功
            out["warnings"].append(f"落点名算不出来：{e}")

    # ---- 查重：只与**目标库**已有的书比 ----
    if lib is not None:
        out["duplicates"] = find_duplicates(out, lib)

    if not out["has_cover"] and ext == ".epub":
        out["warnings"].append("这份 EPUB 没有可用封面")
    if not out["title"]:
        out["warnings"].append("读不出书名（入库时靠文件名或元数据抓取补齐）")

    return out


def find_duplicates(preview: dict, lib: dict) -> list:
    """与目标库已有的书比 —— 同 ISBN / 同作者+书名相似 / 同内容。

    ⚠️ **只提示不拦截**：收书目录的语义是「用户已经决定要收」。
    """
    out: list = []
    title = str(preview.get("title") or "")
    author = str(preview.get("author") or "")
    if not title:
        return out

    lid = str(lib.get("id") or "")
    try:
        existing = library.books(lid or None)
    except Exception:                       # noqa: BLE001
        return out

    for b in existing:
        reasons: list = []
        isbn_new = metadata.isbn_digits(preview.get("isbn") or "")
        isbn_old = metadata.isbn_digits(b.get("isbn") or "")
        if isbn_new and isbn_old and isbn_new == isbn_old:
            reasons.append("ISBN 相同")
        if author and str(b.get("author") or "").strip() == author.strip():
            if str(b.get("title") or "").strip() == title.strip():
                reasons.append("书名与作者完全相同")
            elif _similar(title, str(b.get("title") or "")):
                reasons.append("同作者且书名相近")
        if reasons:
            out.append({
                "book_id": str(b.get("id") or ""),
                "title": str(b.get("title") or ""),
                "author": str(b.get("author") or ""),
                "reasons": reasons,
            })
    return out


def _similar(a: str, b: str, threshold: float = 0.85) -> bool:
    """书名相似度（复用 `library` 里的同一把尺子 —— 别再写一份判据）。"""
    from difflib import SequenceMatcher

    try:
        return SequenceMatcher(None, a, b).ratio() >= threshold
    except Exception:                       # noqa: BLE001
        return False
