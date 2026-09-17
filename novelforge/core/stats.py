"""阅读 / 书库统计聚合：把 library（书目）与 db（进度、批注）合成统计视图。

口径说明：
- 「已读完」＝ 阅读进度 ≥ 99.5%（阅读器按整章推进，末章末尾即 100%）。
- 「入库节奏」＝ 按成品文件 mtime 落在最近 N 天内的数量（与阅读无关）。
- 「最近在读」＝ progress 表里按 updated_at 倒序的书。

时间窗口（days）与 Top 榜长度（top）参数化：dashboard 用默认 28/8，
统计页可传 7/28/90 天与更长榜单。历史字段名 added_28d / reading_28d 保留
（dashboard 契约不变），实际长度跟随 days，响应里的 window 是权威口径。
"""
import time

from . import db, library


def _top(counter: dict, n: int = 8) -> list:
    return [
        {"name": k, "count": v}
        for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    ]


def overview(days: int = 28, top: int = 8) -> dict:
    # 越界值收敛到安全范围，而不是 400 —— 统计是展示型接口，宁可得体降级
    try:
        days = max(7, min(int(days), 365))
    except (TypeError, ValueError):
        days = 28
    try:
        top = max(1, min(int(top), 50))
    except (TypeError, ValueError):
        top = 8

    bs = library.books()
    total = len(bs)
    size = sum(b.get("size") or 0 for b in bs)

    by_format: dict = {}
    authors: dict = {}
    series: dict = {}
    publishers: dict = {}
    genres: dict = {}
    decades: dict = {}
    # 书库体检：不指望一个人去逐本检查，缺元数据 / 无封面这类问题聚合成计数
    integrity = {
        "missing_author": 0,
        "missing_language": 0,
        "no_cover": 0,
        "zero_size": 0,
        "unparsable": 0,
    }
    for b in bs:
        f = b.get("format") or "?"
        by_format[f] = by_format.get(f, 0) + 1
        a = (b.get("author") or "").strip()
        if a:
            authors[a] = authors.get(a, 0) + 1
        else:
            integrity["missing_author"] += 1
        s = (b.get("series") or "").strip()
        if s:
            series[s] = series.get(s, 0) + 1
        pub = (b.get("publisher") or "").strip()
        if pub:
            publishers[pub] = publishers.get(pub, 0) + 1
        for g in b.get("tags") or []:
            g = str(g).strip()
            if g:
                genres[g] = genres.get(g, 0) + 1
        y = str(b.get("year") or "").strip()
        if y.isdigit() and 1000 <= int(y) <= 2100:
            d = int(y) // 10 * 10
            decades[d] = decades.get(d, 0) + 1
        if not (b.get("language") or "").strip():
            integrity["missing_language"] += 1
        # 无封面只对 EPUB 有意义（mobi/pdf/txt 本来就不解析封面）
        if (b.get("format") or "").upper() == "EPUB" and not b.get("has_cover"):
            integrity["no_cover"] += 1
        if not (b.get("size") or 0):
            integrity["zero_size"] += 1
        if b.get("unparsable"):
            integrity["unparsable"] += 1

    prog = db.all_progress()
    annos = db.annotation_counts()

    unread = reading = finished = 0
    recent: list = []
    statuses = db.all_statuses()
    psum = 0.0
    for b in bs:
        p = prog.get(b["id"])
        pct = float(p["percent"]) if p else 0.0
        psum += pct
        # 真实状态优先；没有状态行的书才按进度兜底推导（与 stats 口径一致）。
        # paused/abandoned 归入在读：它们都「翻过」，和未读不是一回事。
        raw = (statuses.get(b["id"]) or {}).get("status")
        if raw == "finished":
            finished += 1
        elif raw == "unread":
            unread += 1
        elif raw in ("reading", "paused", "abandoned"):
            reading += 1
        elif pct <= 0:
            unread += 1
        elif pct >= 99.5:
            finished += 1
        else:
            reading += 1
        if p:
            recent.append({
                "id": b["id"],
                "title": b["title"],
                "author": b["author"],
                "percent": pct,
                "updated_at": p["updated_at"],
            })
    recent.sort(key=lambda r: r["updated_at"], reverse=True)

    # 近 N 天入库节奏（按文件 mtime；buckets[0] = N 天前，buckets[-1] = 今天）
    now = time.time()
    buckets = [0] * days
    for b in bs:
        d = int((now - (b.get("mtime") or 0)) // 86400)
        if 0 <= d < days:
            buckets[days - 1 - d] += 1

    tot = db.reading_totals()
    read_daily = db.daily_seconds(days)
    hours = db.hour_histogram()
    active = db.active_days()
    day_set = set(active)

    # 连续阅读天数：今天有阅读就从今天算起，否则从昨天算起
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    yesterday = time.strftime("%Y-%m-%d", time.localtime(now - 86400))
    streak = 0
    if today in day_set or yesterday in day_set:
        i = 0 if today in day_set else 1
        while time.strftime("%Y-%m-%d", time.localtime(now - i * 86400)) in day_set:
            streak += 1
            i += 1

    # 本月入库（按文件 mtime 的日历月）
    now_lt = time.localtime(now)
    added_month = 0
    for b in bs:
        lt = time.localtime(b.get("mtime") or 0)
        if lt.tm_year == now_lt.tm_year and lt.tm_mon == now_lt.tm_mon:
            added_month += 1

    languages = len({
        (b.get("language") or "").strip() for b in bs if (b.get("language") or "").strip()
    })

    return {
        "books": {
            "total": total,
            "size": size,
            "by_format": by_format,
            "languages": languages,
        },
        "authors": {"total": len(authors), "top": _top(authors, top)},
        "series": {"total": len(series), "top": _top(series, top)},
        "publishers": {"total": len(publishers), "top": _top(publishers, top)},
        "genres": {"total": len(genres), "top": _top(genres, top)},
        # 年份按十年聚合：逐年的柱子噪声太大，十年一档才看得出藏书面貌
        "years": {
            "known": sum(decades.values()),
            "unknown": total - sum(decades.values()),
            "decades": [{"decade": d, "count": c} for d, c in sorted(decades.items())],
        },
        "avg_progress": round(psum / total, 1) if total else 0.0,
        "integrity": integrity,
        "reading": {
            "unread": unread,
            "reading": reading,
            "finished": finished,
            "annotations": sum(annos.values()),
            "seconds": tot["seconds"],
            "sessions": tot["sessions"],
            "avg_seconds": (tot["seconds"] / tot["sessions"]) if tot["sessions"] else 0.0,
            "streak": streak,
            "days": len(active),
        },
        # 历史字段名保留；长度跟随 days，window 是权威口径
        "window": days,
        "added_28d": buckets,
        "added_month": added_month,
        "hours": hours,
        "reading_28d": read_daily,
        "recent": recent[:12],
    }
