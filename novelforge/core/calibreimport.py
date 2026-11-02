"""外部书库的**只读登记**导入（第 228 期）。

## 范围（刻意很小）

上游（BookOrbit）有完整的「外部迁移」：把别的应用的书、用户、进度整套搬过来。
本项目**只做「只读登记」**：

- **只读**：读 Calibre 的 `metadata.db`（或一个书库目录），**不复制文件、不写源、
  不导其它应用的用户与进度**。
- **登记**：按行生成「书库来源目录登记」+ **元数据覆盖**（`meta_override`）——
  于是那些书**就地引用**被本项目扫到，书名 / 作者 / 系列按对方那一份显示。

为什么这个范围是对的：本项目的书库模型就是「**就地引用** + 来源根」
（见 `docs/user-guide.md` §2.1），所以登记一个外部目录 = 把那个目录挂成来源根，
**零拷贝**。整套迁移（用户映射 / 事务 / 回滚 / 进度搬运）是多人模型的东西，
本项目单用户（见 AGENTS.md 第 1 节）。

## 边界（如实留档）

- **只支持 Calibre 的 `metadata.db`**（SQLite，schema 见 `books` / `authors` /
  `series` / `tags` 四张表）。其它应用（Booklore / Audiobookshelf …）**不做** ——
  外部 schema 不可控，见 `docs/bookorbit/bookorbit-live-diff-2026-10.md` 的判断。
- **不装 Calibre 运行时**：不 `import calibre.*`、不写 `requirements.txt`。
  只是**读一个 SQLite 文件**。
- **文件格式只登记不判断**：Calibre 的书库里可能混着 `.epub` / `.pdf` / `.azw3` ——
  本项目扫到时按**自己的**白名单判能不能收；收不了的**如实报告**，不强行登记。
"""
from __future__ import annotations

import pathlib
import sqlite3

#: Calibre `metadata.db` �� `books` 表里我们关心的列。
#:
#: ⚠️ Calibre 的列名在 0.8 前后变过（`timestamp` / `pubdate` / `sort` …），
#: 所以这里**逐列探测**：表里有就用、没有就空 —— 而不是假定一套列名。
_BOOK_COLUMNS = ("id", "title", "sort", "author_sort", "series", "series_index",
                 "isbn", "pubdate", "publisher", "tags", "path", "format",
                 "timestamp", "lccn", "identifiers")


def _open_readonly(path: pathlib.Path) -> sqlite3.Connection:
    """**只读**打开 Calibre 的 `metadata.db`。

    ⚠️ 用 URI 的 `mode=ro` —— 绝不以可写方式打开对方的库（写坏了是**不可逆**的）。
    """
    uri = "file:%s?mode=ro" % str(path).replace("?", "%3f").replace("#", "%23")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> list:
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except sqlite3.Error:
        return []


def read_calibre(db_path: pathlib.Path, limit: int = 5000) -> dict:
    """读 Calibre 的 `metadata.db` → ``{"books": [...], "warnings": [...]}``。

    每一本给出：书名 / 作者 / 系列 / 系列序号 / ISBN / 出版社 / 年份 / 题材 /
    **库内路径**（相对 Calibre 书库根，用 `/` 分隔）。

    ⚠️ **读不出来就如实说**（`warnings`），不返回空列表冒充「没有书」。
    """
    out: dict = {"books": [], "warnings": [], "total": 0}
    p = pathlib.Path(db_path)
    if not p.is_file():
        out["warnings"].append(f"找不到 {p}")
        return out
    try:
        conn = _open_readonly(p)
    except sqlite3.Error as e:
        out["warnings"].append(f"打不开 {p.name}（不是可读的 SQLite？）：{e}")
        return out
    try:
        bcols = _columns(conn, "books")
        if not bcols:
            out["warnings"].append(f"{p.name} 里没有 books 表 —— 这不像 Calibre 的 metadata.db")
            return out
        # 作者 / 系列 / 题材都在各自的表里，且是**多对多**（逗号分隔的 id 列表）
        authors = _author_map(conn)
        series = _series_map(conn)
        tags = _tag_map(conn)

        rows = conn.execute(
            "SELECT * FROM books ORDER BY id LIMIT ?", (int(limit),)
        ).fetchall()
        for r in rows:
            b = {c: r[c] for c in _BOOK_COLUMNS if c in bcols}
            aid = _first_id(b.get("author_sort") or "")
            # Calibre 的 `author_sort` 存的是**作者 id 列表**（逗号分隔）
            names = authors.get(aid) or (b.get("author_sort") or "")
            sid = _first_id(b.get("series") or "")
            book = {
                "calibre_id": b.get("id"),
                "title": str(b.get("title") or ""),
                "author": names,
                "series": series.get(sid, ""),
                # ⚠️ Calibre 的 `series_index` 是 **REAL**（1.0）⇒ 直接写进覆盖层
                # 会让界面显示「第 1.0 册」。这里归一成整数形态（`1`），空值仍是空。
                "series_index": _index_text(b.get("series_index")),
                "isbn": str(b.get("isbn") or ""),
                "publisher": str(b.get("publisher") or ""),
                "year": _year_of(b.get("pubdate") or ""),
                "tags": tags.get(_first_id(b.get("tags") or ""), ""),
                "path": str(b.get("path") or "").replace("\\", "/"),
                "format": str(b.get("format") or ""),
            }
            if not book["path"]:
                out["warnings"].append(f"「{book['title']}」没有路径字段 —— 登记不了")
                continue
            out["books"].append(book)
        try:
            out["total"] = int(conn.execute("SELECT COUNT(*) FROM books").fetchone()[0])
        except sqlite3.Error:
            out["total"] = len(out["books"])
        if out["total"] > len(out["books"]):
            out["warnings"].append(
                f"共 {out['total']} 本，本次只读了前 {len(out['books'])} 本"
            )
    except sqlite3.Error as e:
        out["warnings"].append(f"读 {p.name} 失败：{e}")
    finally:
        try:
            conn.close()
        except Exception:                   # noqa: BLE001
            pass
    return out


def _first_id(raw) -> str:
    """Calibre 把多对多关系存成逗号分隔的 id 串 ⇒ 取第一个。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    # 形如 "1,2,3" 或 "{1,2,3}"
    s = s.strip("{}")
    return s.split(",")[0].strip()


def _name_map(conn: sqlite3.Connection, table: str, id_col: str = "id") -> dict:
    """`{id: name}`（作者 / 系列 / 题材三张表同构）。"""
    cols = _columns(conn, table)
    if not cols or id_col not in cols:
        return {}
    name_col = "name" if "name" in cols else ("title" if "title" in cols else "")
    if not name_col:
        return {}
    try:
        rows = conn.execute(f"SELECT {id_col}, {name_col} FROM {table}").fetchall()
    except sqlite3.Error:
        return {}
    return {str(r[0]): str(r[1] or "") for r in rows}


def _author_map(conn: sqlite3.Connection) -> dict:
    return _name_map(conn, "authors")


def _series_map(conn: sqlite3.Connection) -> dict:
    return _name_map(conn, "series")


def _tag_map(conn: sqlite3.Connection) -> dict:
    """题材：Calibre 的 `tags` 列存的是**逗号分隔的题材名**（不是 id）——
    但也有版本用 `tags` 表 ⇒ 两种都认，认不出就原样返回。"""
    cols = _columns(conn, "tags")
    if cols and "name" in cols:
        m = _name_map(conn, "tags")
        if m:
            return m
    return {}


def _index_text(raw) -> str:
    """系列序号 → 文本（`1.0` → `1`；`1.5` → `1.5`；空 → 空）。

    Calibre 的 `series_index` 是 REAL ⇒ 整数册号会带 `.0`。直接写进覆盖层会让
    界面显示「第 1.0 册」—— 那不是用户数据里的样子。
    """
    s = str(raw if raw is not None else "").strip()
    if not s:
        return ""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s
    if f == int(f):
        return str(int(f))
    return s


def _year_of(raw) -> str:
    """从 Calibre 的日期串里取年份（`pubdate` 形如 `2011-03-05 00:00:00`）。"""
    import re

    m = re.search(r"(\d{4})", str(raw or ""))
    return m.group(1) if m else ""


def plan_registration(root: pathlib.Path, books: list, allowed_exts=None) -> dict:
    """把 Calibre 的书单 → 本项目的「登记计划」（**只算不改**）。

    每一本给出：源路径（Calibre 书库根下的相对路径）、书名 / 作者 / 系列等**元数据覆盖**、
    以及**能不能收**（扩展名是否在本项目认的格式里）。

    ⚠️ **不碰磁盘**：这一层只算，真登记由调用方按本项目的库模型写。
    """
    out: dict = {"items": [], "skipped": [], "warnings": []}
    root = pathlib.Path(root)
    for b in books:
        rel = str(b.get("path") or "")
        if not rel:
            continue
        src = root / rel
        if not src.is_file():
            out["skipped"].append({"title": b.get("title") or rel, "path": rel,
                                   "reason": "文件不在 Calibre 书库根下"})
            continue
        ext = src.suffix.lower()
        if allowed_exts is not None and ext not in allowed_exts:
            out["skipped"].append({"title": b.get("title") or rel, "path": rel,
                                   "reason": f"本项目的书库不收 {ext or '这个格式'}"})
            continue
        out["items"].append({
            "path": rel,
            "title": b.get("title") or "",
            "author": b.get("author") or "",
            "series": b.get("series") or "",
            "series_index": b.get("series_index") or "",
            "isbn": b.get("isbn") or "",
            "publisher": b.get("publisher") or "",
            "year": b.get("year") or "",
            "tags": b.get("tags") or "",
        })
    if out["skipped"]:
        out["warnings"].append(f"{len(out['skipped'])} 本登记不了（见 skipped）")
    return out


def apply_registration(library_id: str, plan: dict) -> dict:
    """把登记计划落到本项目（**只写元数据覆盖**，不碰文件）。

    流程：① 那个目录已经被登记成书库的**来源根**（由调用方 / 建库向导完成）⇒
    ② 本项目扫到那些文件 ⇒ ③ 按**文件路径**找到对应的书，把 Calibre 的元数据
    写成 `meta_override`（书名 / 作者 / 系列 / 序号 / ISBN / 出版社 / 年份 / 题材）。

    ⚠️ **不复制文件、不移动、不删除**：那些书是**就地引用**被本项目扫到的
    （本项目的书库模型就是「就地引用 + 来源根」，见 `docs/user-guide.md` §2.1）。

    返回 ``{"ok", "matched", "written", "skipped", "warnings"}``。
    """
    from . import db, library

    out: dict = {"ok": True, "matched": 0, "written": 0, "skipped": 0, "warnings": []}
    items = plan.get("items") or []
    if not items:
        return out

    # 按**相对路径**索引本项目已扫到的书（登记的对象是「那个目录里的这些文件」）
    index: dict = {}
    for b in library.books(library_id):
        rel = str(b.get("name") or "")
        if rel:
            index[rel.replace("\\", "/")] = b

    writes: list = []
    for it in items:
        rel = str(it.get("path") or "").replace("\\", "/")
        b = index.get(rel)
        if not b:
            out["skipped"] += 1
            continue
        out["matched"] += 1
        bid = str(b.get("id") or "")
        for field, key in (("title", "title"), ("author", "author"),
                          ("series", "series"), ("series_index", "series_index"),
                          ("isbn", "isbn"), ("publisher", "publisher"),
                          ("year", "year"), ("tags", "tags")):
            val = str(it.get(key) or "").strip()
            if val:
                # `db.set_overrides` 的行是 4 元组 `(book_id, field, value, orig)`；
                # `orig` 留空 ⇒ 记「用户覆盖前的样子」为空（不影响写入）。
                writes.append((bid, field, val, ""))
    if writes:
        out["written"] = db.set_overrides(writes)
    if out["skipped"]:
        out["warnings"].append(
            f"{out['skipped']} 本没在本项目的书目里找到 —— 先扫描那个来源目录再登记"
        )
    return out
