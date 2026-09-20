"""阅读活动聚合：贡献热力图 + 时间轴（第 31 期新增）。

数据基础：
- ``reading_sessions``（按 ``started_at`` 的本地日聚合分钟数 → 热力图），对齐上游
  ``reading-session.ts`` 的 ``dailySummary{day,totalMinutes}[]``；
- ``annotations``（批注）+ ``user_achievements``（成就解锁）合并为时间轴。

按库过滤复用 ``library.books(lid)`` 取书 id 集合，与 ``core/stats.py`` 同一范式：
阅读会话本身没有库维度，靠 book_id 归属判定。``reading_sessions`` 无 ``source`` 列，
故无分设备热力图（上游有 ``READING_SESSION_SOURCES`` 分桶），属刻意分流。
"""
from __future__ import annotations

from . import db, library


def _book_ids(library_id: str):
    """按库取书 id 集合；空串/None = 全库（返回 None，调用方不按书过滤）。"""
    lid = (library_id or "").strip()
    if not lid:
        return None
    return {b["id"] for b in library.books(lid)}


def heatmap(library_id: str = "", year: int | None = None) -> dict:
    """按日阅读分钟贡献热力图。

    返回 ``{library_id, year, days[], total_minutes, active_days}``；
    ``days`` 为 ``[{date, minutes, sessions}]``，空库时为空列表（不补假数据）。
    """
    lid = (library_id or "").strip()
    ids = _book_ids(lid)
    rows = db.reading_day_minutes(ids)
    days = [
        {"date": d, "minutes": m, "sessions": s}
        for d, m, s in rows
        if year is None or d.startswith(str(year))
    ]
    return {
        "library_id": lid,
        "year": year,
        "days": days,
        "total_minutes": round(sum(d["minutes"] for d in days), 1),
        "active_days": len(days),
    }


def timeline(library_id: str = "", limit: int = 120) -> dict:
    """合并阅读会话 / 批注 / 成就解锁为时间轴 feed（新 → 旧）。

    返回 ``{library_id, events[], total}``；``events`` 为统一形状：
      - session:     ``{type, ts, book_id, title, seconds}``
      - annotation:  ``{type, ts, book_id, title, note, quote}``
      - achievement: ``{type, ts, key, name}``
    空库时 events 为空列表（不补假数据）。
    """
    lid = (library_id or "").strip()
    ids = _book_ids(lid)
    books = library.books(lid or None)
    titles = {b["id"]: (b.get("title") or b.get("name") or "") for b in books}

    events: list = []

    for r in db.session_feed(ids):
        events.append({
            "type": "session",
            "ts": float(r["ended_at"]),
            "book_id": r["book_id"],
            "title": titles.get(r["book_id"], ""),
            "seconds": float(r["seconds"]),
        })

    for r in db.annotation_feed(ids):
        events.append({
            "type": "annotation",
            "ts": float(r["created_at"]),
            "book_id": r["book_id"],
            "title": titles.get(r["book_id"], ""),
            "note": (r.get("note") or "").strip(),
            "quote": (r.get("quote") or "").strip(),
        })

    ach_names = {a["key"]: a["name"] for a in db.list_achievements()}
    for k, ts in db.unlocked_map().items():
        events.append({
            "type": "achievement",
            "ts": float(ts),
            "key": k,
            "name": ach_names.get(k, k),
        })

    events.sort(key=lambda e: e["ts"], reverse=True)
    return {
        "library_id": lid,
        "events": events[: max(1, int(limit))],
        "total": len(events),
    }


def reading_activity(library_id: str = "", year: int | None = None, limit: int = 120) -> dict:
    """一次性返回热力图 + 时间轴（前端一请求拿全）。"""
    return {
        "heatmap": heatmap(library_id, year),
        "timeline": timeline(library_id, limit),
    }
