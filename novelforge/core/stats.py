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

第 32 期再补 8 条**图表序列**（同样全是新键，既有键一个不删），供统计页照搬上游的
图表用 —— 上游是「一张图一个 composable 一次请求」，本项目是**单接口共享一份
overview**，故这里把序列一次算齐：

书库侧：``by_language``（语言分布）、``by_format_size``（按格式体积）、
``pages_by_format``（按格式的页数五数概括，箱线图用）、``added_monthly``（全时段
按月入库）、``publication_yearly``（逐年出版，带该年样例书名）。

阅读侧：``progress_funnel``（进度分档）、``completion_monthly``（按月读完）、
``weekdays``（周几读多久，与 ``hours`` 同族）。

第 33 期再补 5 条（书库侧第二批图表，同样全是新键）：

``metadata_fields``（按字段的元数据覆盖率）、``library_metadata``（按 库 × 字段 的覆盖率，
heatmap 用）、``genre_cooccurrence``（题材两两共现，弦图用）、``format_share_monthly``
（格式 × 月份 的入库交叉序列）、``acquisition_lag``（出版年 → 入库的滞后年数点集）。
分数分布要用的 P25 / P75 由 ``metascore`` 侧补（``metadata_score`` 增补两键，既有键不动）。

四条口径约定（写在这里免得以后各算各的）：

- 一律**跟随 ``library_id``**：书库侧从 ``bs`` 算，阅读侧靠 ``ids`` 过滤
  （阅读会话没有库维度，见上）。新增序列不得绕过这条。
- **唯一的例外是 ``library_metadata``**：它要回答的是「哪个库的元数据更完整」——
  对比才是它的用途，跟随 ``library_id`` 就退化成一行、图本身没了意义。故它**始终覆盖
  全部书库**，并在每条里带 ``library_id`` / ``library_name``，界面据此标注口径。
  看接口的人要知道：这一条不随统计范围收窄，其余都收窄。
- ``pages`` 的 0 是「不知道」不是「0 页」（EPUB 为估算值、漫画为归档实际值、
  其余格式恒 0），故不进分布 —— 否则 PDF / 有声书会压出一根假底线。
- ``progress_funnel`` **走进度、不走真实状态**：漏斗要求各档单调包含，而真实状态
  允许把 20% 的书标成 finished，那会造出「后档比前档多」的畸形图。
"""
import time

from . import db, library, metascore

#: 体积榜固定长度（上游该榜名为「Top 50 Largest Books」）。
#: 刻意**不**跟随 `top` 参数：那个参数管的是作者/系列/出版社/题材四个计数器榜。
_LARGEST_N = 50

#: 题材共现弦图的节点上限（第 33 期）：弦图靠弧长与弦的粗细读数，节点一多弦就糊成
#: 一团、什么都读不出来。收敛到计数最高的 12 个题材，且**只统计两端都在节点集里的
#: 边** —— 否则会出现指向不存在节点的弦（ECharts 会把它们悄悄丢掉或画到原点）。
_CHORD_NODES = 12


def _top(counter: dict, n: int = 8) -> list:
    return [
        {"name": k, "count": v}
        for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    ]


def _five_number(values: list) -> dict:
    """五数概括（min / Q1 / median / Q3 / max），分位数走线性插值。

    与常见统计库的默认口径一致；``values`` 必须非空（调用方已过滤）。
    """
    v = sorted(values)
    n = len(v)

    def q(p: float) -> float:
        if n == 1:
            return float(v[0])
        pos = p * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (pos - lo), 1)

    return {"min": v[0], "q1": q(0.25), "median": q(0.5), "q3": q(0.75), "max": v[-1]}


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
    by_format_size: dict = {}
    by_language: dict = {}
    pages_by_format: dict = {}
    page_sources: dict = {}
    monthly: dict = {}
    yearly: dict = {}
    year_titles: dict = {}
    authors: dict = {}
    series: dict = {}
    publishers: dict = {}
    genres: dict = {}
    decades: dict = {}
    # 第 33 期：格式 × 月份 的入库交叉、出版→入库滞后、题材两两共现
    fmt_monthly: dict = {}
    lag: dict = {}
    genre_pairs: dict = {}
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
        by_format_size[f] = by_format_size.get(f, 0) + int(b.get("size") or 0)
        # 未知语言归到 "?"（照 by_format 的既成惯例，不新造一个 null 维度）
        lg = (b.get("language") or "").strip()
        by_language[lg or "?"] = by_language.get(lg or "?", 0) + 1
        # 页数只对有值的书有意义：EPUB 是估算值（pages_source=estimate）、漫画是归档
        # 实际值（archive），其余格式恒 0 —— 0 是「不知道」不是「0 页」，不进分布，
        # 否则 PDF / 有声书会在箱线图上压出一根假底线。来源构成一并带上，界面如实标注。
        pnum = int(b.get("pages") or 0)
        if pnum > 0:
            pages_by_format.setdefault(f, []).append(pnum)
            src = (b.get("pages_source") or "").strip() or "unknown"
            page_sources.setdefault(f, {})
            page_sources[f][src] = page_sources[f].get(src, 0) + 1
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
        # 一本书的题材先去重：tags 里可能有重复项，不去重会让「这本书」在共现对里
        # 被数两次（自己和自己配一对），也会把单本计数抬高。
        bg: list = []
        for g in b.get("tags") or []:
            g = str(g).strip()
            if not g:
                continue
            genres[g] = genres.get(g, 0) + 1
            if g not in bg:
                bg.append(g)
        for i in range(len(bg)):
            for j in range(i + 1, len(bg)):
                # 无序对：统一按字典序排，否则 (A,B) 与 (B,A) 会各记一份、共现数减半
                p = (bg[i], bg[j]) if bg[i] <= bg[j] else (bg[j], bg[i])
                genre_pairs[p] = genre_pairs.get(p, 0) + 1
        y = str(b.get("year") or "").strip()
        pub_year = 0
        if y.isdigit() and 1000 <= int(y) <= 2100:
            yi = int(y)
            pub_year = yi
            decades[yi // 10 * 10] = decades.get(yi // 10 * 10, 0) + 1
            yearly[yi] = yearly.get(yi, 0) + 1
            year_titles.setdefault(yi, []).append(b["title"])
        # 入库月份（按文件 mtime）。mtime<=0 是「没有时间戳」的异常文件：time.localtime(0)
        # 是 1970-01，放进去会在时间轴最左端造出一根假柱子，故直接不进序列。
        mt = b.get("mtime") or 0
        if mt > 0:
            lt_m = time.localtime(mt)
            mk = (lt_m.tm_year, lt_m.tm_mon)
            monthly[mk] = monthly.get(mk, 0) + 1
            fk = (lt_m.tm_year, lt_m.tm_mon, f)
            fmt_monthly[fk] = fmt_monthly.get(fk, 0) + 1
            # 入库滞后只在出版年已知时才有意义（不知道出版年 ≠ 滞后 0 年）；
            # 为负 = 文件时间戳早于出版年（重新入库、时间戳被改动等），照实记为负数，
            # 不 clamp —— 掩盖掉反而会让「未标注年份」和「倒挂」两种异常混作一谈。
            if pub_year:
                lk = (lt_m.tm_year, lt_m.tm_year - pub_year)
                lag[lk] = lag.get(lk, 0) + 1
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
    # audit 的返回值这里要**用全**：既取 score（下面算达标率），也取 present（下面算
    # 逐字段覆盖率）—— 第 33 期之前只取 score，等于把已经算好的字段命中信息扔了。
    audits = [metascore.audit(b) for b in bs]
    scores = [a["score"] for a in audits]
    metadata_ok = sum(1 for s in scores if s >= metascore.METADATA_OK)

    def _pct(n: int) -> float:
        return round(n / total * 100, 1) if total else 0.0

    # ---- 逐字段的元数据覆盖率（第 33 期，对齐上游 MetadataCompletenessItem）----
    # 分母是**全部在册书**，与元数据页 metascore.payload() 里的字段覆盖率同口径
    # （那里也是除以 n）。封面 / 页数只对 EPUB 有意义，但这里刻意**不**做格式归一：
    # 与已公示的元数据页保持一致，比多一个更精确的分母更重要 —— 页面已用脚注说明
    # 「这两项只对 EPUB 有意义」，两处口径不同才是真正的坑。
    field_hits: dict = {}
    for a in audits:
        for k in a["present"]:
            field_hits[k] = field_hits.get(k, 0) + 1
    metadata_fields = [
        {
            "key": k, "label": label,
            "present": field_hits.get(k, 0),
            "total": total,
            "percent": _pct(field_hits.get(k, 0)),
        }
        for k, (_g, _w, label) in metascore.FIELDS.items()
    ]

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
    # 进度漏斗（对齐上游 ProgressFunnel 的五档）：**走进度，不走真实状态** ——
    # 漏斗要求各档单调包含（开始 ⊇ 25% ⊇ 50% ⊇ 75% ⊇ 读完），而真实状态允许把
    # 一本 20% 的书手动标成 finished，那会让漏斗出现「后档比前档多」的畸形。
    # 「读完」阈值沿用本模块既有口径 99.5%（见文件头）。
    funnel = {"started": 0, "reached25": 0, "reached50": 0, "reached75": 0, "completed": 0}
    for b in bs:
        p = prog.get(b["id"])
        pct = float(p["percent"]) if p else 0.0
        psum += pct
        if pct > 0:
            funnel["started"] += 1
        if pct >= 25:
            funnel["reached25"] += 1
        if pct >= 50:
            funnel["reached50"] += 1
        if pct >= 75:
            funnel["reached75"] += 1
        if pct >= 99.5:
            funnel["completed"] += 1
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
    weekdays = db.weekday_histogram(ids)
    completions = db.completion_months(ids)
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

    # ---- 第 32 期：把上面累加的字典整理成有序列表（图表直接吃）----
    pages_list = [
        {"format": f, "count": len(v), **_five_number(v), "sources": page_sources.get(f, {})}
        for f, v in sorted(pages_by_format.items())
    ]
    added_list = [
        {"year": y, "month": m, "count": n} for (y, m), n in sorted(monthly.items())
    ]
    yearly_list = [
        {
            "year": y,
            "count": n,
            # 该年的几本样例书名（上游 PublicationYearTimeline 的 topTitles 同义，
            # 只进 tooltip）；排序取稳定口径，避免每次刷新 tooltip 里换一批书
            "top_titles": sorted(year_titles.get(y, []))[:3],
        }
        for y, n in sorted(yearly.items())
    ]

    # ---- 第 33 期：书库侧第二批图表序列 ----
    # 格式 × 月份：只给计数、占比留给前端算 —— 占比的分母是「当月入库总数」，
    # 后端先算成百分比，前端就没法在 tooltip 里同时给出「本数」了。
    fmt_share = [
        {"year": y, "month": m, "format": f, "count": n}
        for (y, m, f), n in sorted(fmt_monthly.items())
    ]
    # 出版年 → 入库滞后：只含**出版年已知**的书（不知道 ≠ 滞后 0 年），
    # 未标注年份的本数由界面用 `books.total - Σcount` 反推，不再多给一个键。
    lag_list = [
        {"added_year": ay, "lag_years": lg, "count": n}
        for (ay, lg), n in sorted(lag.items())
    ]
    # 题材共现：节点先收敛到 top N，再只留两端都在节点集里的边（见 _CHORD_NODES）
    top_genres = _top(genres, _CHORD_NODES)
    node_set = {x["name"] for x in top_genres}
    genre_chord = {
        "nodes": [{"name": x["name"], "count": x["count"]} for x in top_genres],
        "links": [
            {"source": a, "target": b, "value": n}
            for (a, b), n in sorted(genre_pairs.items())
            if a in node_set and b in node_set
        ],
    }

    # ---- 按 库 × 字段 的覆盖率（heatmap）----
    # **刻意不跟随 library_id**（见文件头第 2 条）：切库时另取全库书目做横向对比，
    # 全库时直接复用上面那一份（同一次扫描结果，不重扫盘）。
    scope = bs if not lid else library.books()
    scope_audits = audits if not lid else [metascore.audit(b) for b in scope]
    lib_hits: dict = {}
    lib_n: dict = {}
    for b, a in zip(scope, scope_audits):
        k = str(b.get("library_id") or "")
        lib_n[k] = lib_n.get(k, 0) + 1
        hits = lib_hits.setdefault(k, {})
        for fk in a["present"]:
            hits[fk] = hits.get(fk, 0) + 1
    # 行按 libraries() 的顺序（= 书库管理的排序）、列按 metascore.FIELDS 的顺序，
    # 都由后端定死 —— 前端照单渲染，否则每次刷新可能排出一个不一样的热图。
    # 0 本书的库**照样出行**（percent 全 0）：它是一条真实状态，藏掉会让人以为库不存在；
    # tooltip 里的 present/total 会显示成 0/0，不至于被误读为「字段全缺」。
    library_metadata = []
    for lib in library.libraries():
        k = str(lib.get("id") or "")
        n = lib_n.get(k, 0)
        hits = lib_hits.get(k, {})
        for fkey, (_g, _w, label) in metascore.FIELDS.items():
            c = hits.get(fkey, 0)
            library_metadata.append({
                "library_id": k,
                "library_name": lib.get("name") or k,
                "key": fkey,
                "label": label,
                "present": c,
                "total": n,
                "percent": round(c / n * 100, 1) if n else 0.0,
            })

    return {
        "books": {
            "total": total,
            "size": size,
            "by_format": by_format,
            "languages": languages,
        },
        # ---- 第 32 期图表序列（书库侧）：全部是新键，既有键一个不动 ----
        "by_language": by_language,
        "by_format_size": by_format_size,
        "pages_by_format": pages_list,
        "added_monthly": added_list,
        "publication_yearly": yearly_list,
        # ---- 第 33 期图表序列（书库侧）：同样是新键，既有键一个不动 ----
        "metadata_fields": metadata_fields,
        "library_metadata": library_metadata,
        "genre_cooccurrence": genre_chord,
        "format_share_monthly": fmt_share,
        "acquisition_lag": lag_list,
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
        # 元数据完整度分布（Average / P25 / P50 / P75 / P90 + 分档直方图），模型见 core/metascore.py
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
        # ---- 第 32 期图表序列（阅读侧）：weekdays 与 hours 同族（时段分布）----
        "weekdays": weekdays,
        "progress_funnel": funnel,
        "completion_monthly": completions,
        "reading_28d": read_daily,
        "recent": recent[:12],
    }
