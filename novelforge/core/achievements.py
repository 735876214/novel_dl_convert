"""成就体系（单用户口径）。

三个设计取舍，都是为了「目录可以随便改，机制不用动」：

1. **目录是数据**：每条成就只声明 `metric` + `target`，判定逻辑集中在 :func:`_metrics`。
   新增成就 = 加一行，不写新代码。
2. **进度实时算、不落库**：`user_achievements` 只记解锁时间。进度若落库，
   删掉几本书之后库里就留着过期进度，界面会自相矛盾。
3. **只解锁、不回退**：书删了、批注删了，已解锁的成就不会消失 ——
   那是对「曾经做到过」的记录，不是一个当前状态的投影。

⚠️ 下方的 :data:`ACHIEVEMENTS` 是**起步集**，目的是把
   「目录 → 判定 → 解锁 → 接口 → 页面」这条链路先打通并验证；
   具体条目名 / 阈值 / 分组待确认后再定，改这一份列表即可。
"""
from __future__ import annotations

import time

from .. import config
from . import db, stats

# ---- 分组（按能力面，不按难度）----
GROUP_LIBRARY = "LIBRARY"        # 书库规模
GROUP_READING = "READING"        # 阅读行为
GROUP_ANNOTATION = "ANNOTATION"  # 批注

# ---- 目录（起步集）----
# metric 必须存在于 _metrics()；target 为达成阈值（含等于）。
ACHIEVEMENTS: list = [
    # 书库规模
    {"key": "first_book", "group": GROUP_LIBRARY, "metric": "books", "target": 1,
     "name": "第一本书", "desc": "书库里有了第一本书"},
    {"key": "books_10", "group": GROUP_LIBRARY, "metric": "books", "target": 10,
     "name": "十本", "desc": "书库达到 10 本"},
    {"key": "books_100", "group": GROUP_LIBRARY, "metric": "books", "target": 100,
     "name": "百本", "desc": "书库达到 100 本"},
    {"key": "books_500", "group": GROUP_LIBRARY, "metric": "books", "target": 500,
     "name": "五百本", "desc": "书库达到 500 本"},
    {"key": "authors_10", "group": GROUP_LIBRARY, "metric": "authors", "target": 10,
     "name": "十位作者", "desc": "收录了 10 位不同作者"},
    {"key": "series_5", "group": GROUP_LIBRARY, "metric": "series", "target": 5,
     "name": "五个系列", "desc": "收录了 5 个不同系列"},
    {"key": "languages_3", "group": GROUP_LIBRARY, "metric": "languages", "target": 3,
     "name": "多语言书库", "desc": "书库覆盖 3 种及以上语言"},
    {"key": "size_1gb", "group": GROUP_LIBRARY, "metric": "size_gb", "target": 1,
     "name": "一个 G", "desc": "书库总体积达到 1 GB"},

    # 阅读行为
    {"key": "first_session", "group": GROUP_READING, "metric": "sessions", "target": 1,
     "name": "开始阅读", "desc": "完成第一次阅读会话"},
    {"key": "hours_1", "group": GROUP_READING, "metric": "hours", "target": 1,
     "name": "阅读一小时", "desc": "累计阅读 1 小时"},
    {"key": "hours_10", "group": GROUP_READING, "metric": "hours", "target": 10,
     "name": "阅读十小时", "desc": "累计阅读 10 小时"},
    {"key": "hours_100", "group": GROUP_READING, "metric": "hours", "target": 100,
     "name": "阅读一百小时", "desc": "累计阅读 100 小时"},
    {"key": "finished_1", "group": GROUP_READING, "metric": "finished", "target": 1,
     "name": "读完第一本", "desc": "读完第一本书（进度 ≥ 99.5%）"},
    {"key": "finished_10", "group": GROUP_READING, "metric": "finished", "target": 10,
     "name": "读完十本", "desc": "读完 10 本书"},
    {"key": "streak_3", "group": GROUP_READING, "metric": "streak", "target": 3,
     "name": "连读三天", "desc": "连续 3 天有阅读记录"},
    {"key": "streak_30", "group": GROUP_READING, "metric": "streak", "target": 30,
     "name": "连读三十天", "desc": "连续 30 天有阅读记录"},
    {"key": "active_days_30", "group": GROUP_READING, "metric": "days", "target": 30,
     "name": "活跃三十天", "desc": "累计 30 天有阅读记录（无需连续）"},

    # 批注
    {"key": "first_note", "group": GROUP_ANNOTATION, "metric": "annotations", "target": 1,
     "name": "第一条批注", "desc": "记下第一条批注"},
    {"key": "notes_50", "group": GROUP_ANNOTATION, "metric": "annotations", "target": 50,
     "name": "五十条批注", "desc": "累计 50 条批注"},
]


def _metrics() -> dict:
    """当前可用的度量值。**成就判定只认这张表** —— 新增 metric 在这里加一行。"""
    ov = stats.overview()
    r = ov["reading"]
    return {
        "books": float(ov["books"]["total"]),
        "authors": float(ov["authors"]["total"]),
        "series": float(ov["series"]["total"]),
        "languages": float(ov["books"]["languages"]),
        "size_gb": float(ov["books"]["size"]) / (1024 ** 3),
        "sessions": float(r["sessions"]),
        "hours": float(r["seconds"]) / 3600.0,
        "finished": float(r["finished"]),
        "streak": float(r["streak"]),
        "days": float(r["days"]),
        "annotations": float(r["annotations"]),
    }


def enabled() -> bool:
    """成就是否启用（``achievements.enabled``，存 config.yaml / settings.json 覆盖层）。

    关闭时**既不判定也不解锁** —— 上游语义是「不统计、不显示成就相关界面」。
    这里刻意连解锁都不做：否则用户关掉开关、过段时间再打开，
    会看到一批「趁关着的时候偷偷解锁」的成就，与「关闭期间不统计」相矛盾。
    """
    try:
        val = (config.load_config().get("achievements") or {}).get("enabled", True)
    except Exception:
        val = True          # 配置读不出来时按启用处理，不因为读配置失败而静默关掉功能
    return bool(val)


def _disabled() -> dict:
    """关闭状态下的空结果（形状与启用时一致，调用方不必分支判空）。"""
    return {
        "enabled": False,
        "items": [],
        "groups": [],
        "total": 0,
        "unlocked": 0,
        "newly_unlocked": [],
        "metrics": {},
    }


def sync_catalog() -> int:
    """把代码里的目录同步进库表（幂等，可反复调用）。返回条目数。"""
    for i, a in enumerate(ACHIEVEMENTS):
        db.upsert_achievement(
            a["key"], a["name"], a.get("desc", ""), a.get("group", ""),
            a.get("metric", ""), a.get("target", 1), i,
        )
    return len(ACHIEVEMENTS)


def evaluate(auto_unlock: bool = True) -> dict:
    """算出每条成就的进度，并（默认）把达标项解锁。返回完整概览。"""
    if not enabled():
        return _disabled()

    sync_catalog()
    m = _metrics()
    unlocked = db.unlocked_map()
    newly: list = []
    items: list = []

    for row in db.list_achievements():
        key = row["key"]
        metric = row["metric"]
        try:
            target = float(row["target"]) or 1.0
        except (TypeError, ValueError):
            target = 1.0

        raw = m.get(metric)
        known = raw is not None          # metric 打错字时能看出来，而不是静默算成 0
        cur = float(raw or 0.0)
        is_unlocked = key in unlocked

        if auto_unlock and not is_unlocked and known and cur >= target:
            if db.unlock_achievement(key):
                unlocked[key] = time.time()
                is_unlocked = True
                newly.append(key)

        items.append({
            "key": key,
            "name": row["name"],
            "desc": row["desc"],
            "group": row["group_name"],
            "metric": metric,
            "target": target,
            "progress": min(cur, target),
            "percent": round(min(cur / target, 1.0) * 100, 1) if target else 0.0,
            "unlocked": is_unlocked,
            "unlocked_at": float(unlocked.get(key, 0.0)),
            "known_metric": known,
        })

    bucket: dict = {}
    for it in items:
        g = bucket.setdefault(it["group"], {"group": it["group"], "total": 0, "unlocked": 0})
        g["total"] += 1
        if it["unlocked"]:
            g["unlocked"] += 1

    return {
        "enabled": True,
        "items": items,
        "groups": sorted(bucket.values(), key=lambda g: g["group"]),
        "total": len(items),
        "unlocked": sum(1 for it in items if it["unlocked"]),
        "newly_unlocked": newly,
        "metrics": m,
    }


def backfill() -> dict:
    """重算：清空解锁记录后按当前数据重新判定解锁。

    对应上游 Maintenance 页的 ``Backfill achievements``。
    注意它会**重置解锁时间**（重新判定即视为此刻解锁）—— 这是「重算」的应有语义。
    """
    if not enabled():
        res = _disabled()
        res["backfilled"] = False
        return res
    db.clear_unlocked()
    res = evaluate(auto_unlock=True)
    res["backfilled"] = True
    return res
