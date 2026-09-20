"""阅读 / 书库统计聚合：把 library（书目）与 db（进度、批注）合成统计视图。

口径说明：
- 「已读完」＝ 阅读进度 ≥ 99.5%（阅读器按整章推进，末章末尾即 100%）。
- 「入库节奏」＝ 按成品文件 mtime 落在最近 N 天内的数量（与阅读无关）。
- 「最近在读」＝ progress 表里按 updated_at 倒序的书。

时间窗口（days）与 Top 榜长度（top）参数化：dashboard 用默认 28/8，
统计页可传 7/28/90 天与更长榜单。历史字段名 added_28d / reading_28d 保留
（dashboard 契约不变），实际长度跟随 days，响应里的 window 是权威口径。

第 30 期补的按库筛选（``library_id``）：

- **空串 = 全部书库**，输出与加该参数之前**逐字节一致**（既有测试与 8 个仪表盘
  部件零影响）；给了库 id 就只统计该库（未知库 = 空库，不 404 —— 与
  ``library.books()`` 及 ``/api/duplicates`` 等既有接口同待遇）。
- 书目派生的一切（规模/格式/作者/系列/出版社/题材/年份/体检/体积榜/入库节奏/
  阅读状态/最近在读/平均进度/批注数）随库收窄。
- **阅读会话没有库维度**（``reading_sessions`` 只有 book_id），故「某库的阅读时长」
  靠「这本书属于哪个库」判定 —— 由这里算出该书库的书 id 集合，传给 db 侧过滤。
  口径写在响应里（``library_id`` 回显），界面据此标注。

第 29 期补的两件（都是**增补**，不删既有键）：
- ``integrity`` 在原有 5 个计数键之外增补百分比口径（``total_books`` / ``present`` /
  ``primary`` / ``metadata`` 三项覆盖率 + ``score``），对齐上游 ``LibraryIntegrityGauge``；
- 新增 ``largest``（按体积降序的 Top 50，对齐上游 ``LargestBookItem``）。
"""
import time

from . import db, library, metascore

#: 体积榜固定长度（上游该榜名为「Top 50 Largest Books」）。
#: 刻意**不**跟随 `top` 参数：那个参数管的是作者/系列/出版社/题材四个计数器榜。
_LARGEST_N = 50


def _top(counter: dict, n: int = 8) -> list:
    return [
        {"name": k, "count": v}
        for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    ]


def overview(days: int = 28, top: int = 8, library_id: str = "") -> dict:
    # 越界值收敛到安全范围，而不是 400 —— 统计是展示型接口，宁可得体降级
    try:
        days = max(7, min(int(days), 365))
    except (TypeError, ValueError):
        days = 28
    try:
        top = max(1, min(int(top), 50))
    except (TypeError, ValueError):
        top = 8

    lid = (library_id or "").strip()
    bs = library.books(lid or None)
    # 按库筛选时的书 id 集合（None = 不按书过滤）；供「阅读会话→库」的归属判定用
    ids = {b["id"] for b in bs} if lid else None
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
        # 三项「文件侧」计数一律读 issues —— 与「缺失资源」页 / 库分面同一口径
        # （library 已经把「无封面只对 EPUB 有意义」「音频目录不算 0 字节」
        # 「服务端有封面就撤掉 no-cover」这些判定做在 issues 上了，这里再各判一遍必然走岔）。
        # ⚠️ 原先 unparsable 读的是 b["unparsable"]，而书目字典**没有这个键**
        # （library._scan_once 只下发 issues）⇒ 该计数恒为 0。
        iss = b.get("issues") or []
        if "no-cover" in iss:
            integrity["no_cover"] += 1
        if "zero-bytes" in iss:
            integrity["zero_size"] += 1
        if "unparsable" in iss:
            integrity["unparsable"] += 1

    # ---- 书库体检的百分比口径（第 29 期，对齐上游 LibraryIntegrityGauge 的四值）----
    # 口径差异要写明：本项目书目**由扫描文件得来**，不存在「库里登记了、文件却不在」的书，
    # 上游的 Present（文件在磁盘上）在本项目恒为 100%、是个恒真项。故这里把
    #   Present 落在「文件有实体内容（非 0 字节）」、Primary 落在「主文件能被解析」上。
    # 元数据侧取 metascore 的达标本数（阈值 = 已公示的分档边界 70）。
    scores = [metascore.audit(b)["score"] for b in bs]
    metadata_ok = sum(1 for s in scores if s >= metascore.METADATA_OK)

    def _pct(n: int) -> float:
        return round(n / total * 100, 1) if total else 0.0

    present = total - integrity["zero_size"]
    primary = total - integrity["unparsable"]
    integrity.update({
        "total_books": total,
        "present": present,
        "present_percent": _pct(present),
        "primary": primary,
        "primary_percent": _pct(primary),
        "metadata": metadata_ok,
        "metadata_percent": _pct(metadata_ok),
        # 综合分 = 三项覆盖率的算术平均（不发明权重：三项各占三分之一）
        "score": round((_pct(present) + _pct(primary) + _pct(metadata_ok)) / 3, 1),
    })

    # ---- Top 50 最大书（上游 LargestBookItem）----
    # 固定 50 条：上游该榜就叫 Top 50 Largest Books，故不与 `top`（计数器榜长度）混用 ——
    # 混用会让统计页一加载就把作者/系列/出版社/题材四个榜一起撑到 50 行。
    # 0 字节书**不排除**：它是一种真实信号（配合上面的 zero_size 计数看）。
    largest = sorted(
        (
            {
                "id": b["id"],
                "title": b["title"],
                "size_bytes": int(b.get("size") or 0),
                "format": b.get("format") or "",
            }
            for b in bs
        ),
        key=lambda x: (-x["size_bytes"], x["title"]),
    )[:_LARGEST_N]

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

    tot = db.reading_totals(ids)
    read_daily = db.daily_seconds(days, ids)
    hours = db.hour_histogram(ids)
    active = db.active_days(ids)
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
        # 元数据完整度分布（Average / P50 / P90 + 分档直方图），模型见 core/metascore.py
        "metadata_score": metascore.summary(scores=scores),
        # 体积榜：固定最多 50 条，与 `top` 无关（见上方注释）
        "largest": largest,
        "reading": {
            "unread": unread,
            "reading": reading,
            "finished": finished,
            # 按库筛选时必须按 bs 取（annos 是全部书的批注计数）；全库时两者相等
            "annotations": sum(annos.get(b["id"], 0) for b in bs),
            "seconds": tot["seconds"],
            "sessions": tot["sessions"],
            "avg_seconds": (tot["seconds"] / tot["sessions"]) if tot["sessions"] else 0.0,
            "streak": streak,
            "days": len(active),
        },
        # 历史字段名保留；长度跟随 days，window 是权威口径
        "window": days,
        # 统计范围回显：空串 = 全部书库（第 30 期按库筛选；界面据此标注口径）
        "library_id": lid,
        "added_28d": buckets,
        "added_month": added_month,
        "hours": hours,
        "reading_28d": read_daily,
        "recent": recent[:12],
    }
