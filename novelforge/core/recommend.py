"""相似书推荐：纯派生计算，不落库。

书库里没有协同过滤的信号（单用户、无行为积累），能可靠算出的只有
**内容重合度**：同作者 / 题材重合 / 同系列。三者的可信度依次递减，
权重也依次递减 —— 同作者最可能被再次拿起，题材重合次之。
"""

# 权重集中在一个常量里，调参时不用翻实现
W_AUTHOR = 3.0
W_TAG = 2.0    # 每个重合题材 2 分
W_SERIES = 2.0


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def similar_books(book_id: str, books: list, limit: int = 6) -> list:
    """返回与 book_id 最相似的若干本（不含自身）。

    ``books`` 传 /api/books 同构的书目（含 author/tags/series）。
    得分为 0 的书**不返回** —— 「毫无关系」的推荐只会消耗界面信任。
    """
    me = next((b for b in books if b["id"] == book_id), None)
    if me is None:
        return []
    my_tags = {_norm(t) for t in (me.get("tags") or [])}
    my_author = _norm(me.get("author"))
    my_series = _norm(me.get("series"))

    out = []
    for b in books:
        if b["id"] == book_id:
            continue
        score = 0.0
        reasons = []
        if my_author and _norm(b.get("author")) == my_author:
            score += W_AUTHOR
            reasons.append("同作者")
        shared = my_tags & {_norm(t) for t in (b.get("tags") or [])}
        if shared:
            score += W_TAG * len(shared)
            reasons.append("题材：" + "、".join(sorted(shared)))
        if my_series and _norm(b.get("series")) == my_series:
            score += W_SERIES
            reasons.append("同系列")
        if score <= 0:
            continue
        out.append({
            "id": b["id"],
            "title": b.get("title"),
            "author": b.get("author"),
            "series": b.get("series"),
            "series_index": b.get("series_index"),
            "cover_url": b.get("cover_url"),
            "has_cover": b.get("has_cover", False),
            "score": score,
            # 去重的理由文案（同系列 + 同作者时不要说两遍）
            "reasons": list(dict.fromkeys(reasons)),
        })
    out.sort(key=lambda x: (-x["score"], x.get("title") or ""))
    return out[: max(1, int(limit))]
