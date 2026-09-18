"""元数据完整度评分（Confidence Score / Metadata Score）。

给每本书算一个 **0–100 的完整度分**，再聚合出**分布直方图与分位数（P50 / P90）**，
用于回答「我的书库元数据整体有多完整、哪些书最该补」。

模型
----
字段 → 权重（满分占比，加总 100），分 5 组（与上游 Confidence Score 页一致）::

    Core           title 14 · author 14 · has_cover 12            = 40
    Publishing     language 6 · publisher 7 · year 6 · pages 4    = 23
    Classification description 12 · tags 8                        = 20
    Provider IDs   isbn 10                                        = 10
    Enrichment     series 4 · series_index 3                      =  7
    ------------------------------------------------------------------
    合计                                                          = 100

计分口径
--------
- **字段存在** = 该字段有非空值（``tags`` 非空列表、``pages`` > 0、``has_cover`` 为真）。
- **分母按适用权重归一**：``has_cover`` / ``pages`` 只有 EPUB 才有意义，非 EPUB（PDF/MOBI…）
  不计入分母 —— 否则一本外部 PDF 会被平白扣掉 16 分。故::

      得分 = 命中字段权重和 / 该格式适用权重和 × 100

- 数据面来自 ``library.books()``（EPUB 解析 OPF + 文件名推断 + 可选元数据抓取）。

与上游的差异（刻意且已标注）
----------------------------
- 上游是 **24 个计分字段**（含大量 Provider 专有字段）；本项目只列**元数据管线真正能填**的
  12 个 —— 凑成 24 只会得到一排永远 0 分、无法行动的行。
- 上游把 **Series name / Series index 列为不计分**；本项目**计入 Enrichment**，
  因为系列信息决定 Komga 布局（见 core/komga.py）。页面上明确标注这条差异。
"""
from __future__ import annotations

from . import library

#: 5 个权重分组：(key, 英文名, 中文名)
GROUPS = (
    ("core", "Core", "核心标识"),
    ("publishing", "Publishing", "出版信息"),
    ("classification", "Classification", "分类与简介"),
    ("provider_ids", "Provider IDs", "外部标识"),
    ("enrichment", "Enrichment", "系列增强"),
)

#: 计分字段 → (分组, 权重, 中文名)。权重加总 = 100（见模块 docstring）
FIELDS = {
    "title":        ("core", 14.0, "书名"),
    "author":       ("core", 14.0, "作者"),
    "has_cover":    ("core", 12.0, "封面"),
    "language":     ("publishing", 6.0, "语言"),
    "publisher":    ("publishing", 7.0, "出版社"),
    "year":         ("publishing", 6.0, "出版年"),
    "pages":        ("publishing", 4.0, "页数"),
    "description":  ("classification", 12.0, "简介"),
    "tags":         ("classification", 8.0, "题材"),
    "isbn":         ("provider_ids", 10.0, "ISBN"),
    "series":       ("enrichment", 4.0, "系列"),
    "series_index": ("enrichment", 3.0, "系列序号"),
}

#: 只有 EPUB 才有意义的字段：非 EPUB 不计入分母
_EPUB_ONLY = {"has_cover", "pages"}

#: 分布直方图分档（与上游页面一致：<50 / 50-69 / 70-89 / 90+）
_BUCKETS = (
    ("lt50", "< 50", lambda s: s < 50),
    ("50_69", "50–69", lambda s: 50 <= s < 70),
    ("70_89", "70–89", lambda s: 70 <= s < 90),
    ("gte90", "90+", lambda s: s >= 90),
)

#: 明确不参与计分的项（页面上单独列出，避免「为什么它没算」的疑问）
NOT_SCORED = (
    {"key": "subtitle", "label": "副标题", "why": "本项目元数据面没有这个字段"},
    {"key": "custom_fields", "label": "自定义元数据", "why": "用户自定义键值，不参与完整度"},
    {"key": "pages_source", "label": "页数来源", "why": "只是来源标记（estimate/…），不是内容"},
)

NOTES = (
    "上游把 Series name / Series index 列为不计分；本项目计入 Enrichment —— 系列信息决定 Komga 布局。",
    "非 EPUB（PDF / MOBI…）不计封面与页数的权重，避免格式不同造成的不公平扣分。",
)


def _present(b: dict, key: str) -> bool:
    """字段是否有实质取值。"""
    v = b.get(key)
    if key == "has_cover":
        return bool(v)
    if key == "pages":
        try:
            return int(v or 0) > 0
        except (TypeError, ValueError):
            return False
    if key == "tags":
        return any(str(t).strip() for t in (v or []))
    return bool(str(v if v is not None else "").strip())


def _applicable(b: dict) -> float:
    """该格式下的适用权重和（分母）。"""
    is_epub = (b.get("format") or "").upper() == "EPUB"
    return sum(
        w for k, (_g, w, _l) in FIELDS.items() if not (k in _EPUB_ONLY and not is_epub)
    )


def audit(b: dict) -> dict:
    """单本评分：得分 + 已命中 / 缺失字段（缺的按权重从高到低排，便于按优先级补）。"""
    earned = 0.0
    present: list = []
    missing: list = []
    for key, (_g, w, label) in FIELDS.items():
        if _present(b, key):
            earned += w
            present.append(key)
        else:
            missing.append({"key": key, "label": label, "weight": w})
    missing.sort(key=lambda m: -m["weight"])
    denom = _applicable(b) or 1.0
    return {
        "id": b.get("id") or "",
        "name": b.get("name") or "",
        "title": b.get("title") or "",
        "author": b.get("author") or "",
        "format": b.get("format") or "",
        "score": round(earned / denom * 100, 1),
        "present": present,
        "missing": missing,
    }


def percentile(values, p: float) -> float:
    """线性插值分位数（与 numpy 默认口径一致），索引 0-based。"""
    vals = sorted(float(v) for v in values)
    if not vals:
        return 0.0
    if len(vals) == 1:
        return round(vals[0], 1)
    k = (len(vals) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


def _summarize(scores: list) -> dict:
    total = len(scores)
    buckets = []
    for key, label, test in _BUCKETS:
        n = sum(1 for s in scores if test(s))
        buckets.append({
            "key": key, "label": label, "count": n,
            "percent": round(n / total * 100, 1) if total else 0.0,
        })
    return {
        "total": total,
        "avg": round(sum(scores) / total, 1) if total else 0.0,
        "p50": percentile(scores, 50),
        "p90": percentile(scores, 90),
        "min": round(min(scores), 1) if scores else 0.0,
        "max": round(max(scores), 1) if scores else 0.0,
        "buckets": buckets,
    }


def summary(books=None) -> dict:
    """紧凑摘要（供统计页 / dashboard 直接内嵌）：分位 + 分档直方图。"""
    bs = library.books() if books is None else books
    return _summarize([audit(b)["score"] for b in bs])


def payload(books=None, lowest: int = 12) -> dict:
    """完整载荷：摘要 + 权重模型（含字段覆盖率）+ 最低分书目 + 不计分说明。"""
    bs = library.books() if books is None else books
    audits = [audit(b) for b in bs]
    n = len(bs)

    groups = []
    for gkey, glabel, gzh in GROUPS:
        fields = []
        gweight = 0.0
        for key, (gk, w, label) in FIELDS.items():
            if gk != gkey:
                continue
            gweight += w
            coverage = round(sum(1 for b in bs if _present(b, key)) / n * 100, 1) if n else 0.0
            fields.append({"key": key, "label": label, "weight": w, "coverage": coverage})
        groups.append({
            "key": gkey, "label": glabel, "zh": gzh,
            "weight": round(gweight, 1),
            "coverage": round(sum(f["coverage"] for f in fields) / len(fields), 1) if fields else 0.0,
            "fields": fields,
        })

    lowest_n = max(1, int(lowest))
    order = sorted(audits, key=lambda a: (a["score"], a["name"]))
    return {
        **_summarize([a["score"] for a in audits]),
        "groups": groups,
        "lowest": order[:lowest_n],
        "not_scored": list(NOT_SCORED),
        "notes": list(NOTES),
    }
