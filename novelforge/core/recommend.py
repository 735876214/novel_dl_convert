"""相似书推荐：纯派生计算，不落库。

第 35 期起打分口径对齐上游（BookOrbit `recommendation.service`）的**五路加权**：

    总分 = 0.5·余弦 + 0.1·同作者 + 0.25·题材重合(Jaccard) + 0.1·同系列 + 0.05·评分接近度

每一路都先归一化到 0–1，缺的那一路（如双方都没评分）**不进分母** —— 不能因为「没打分」
就平白把一本好书压下去。

两处与上游的**刻意差异**（都写在这里，免得下一个人以为是漏做）：

1. **特征向量不用语义 embedding，也用不上简介**。上游那套向量是元数据特征（不是语义
   模型），本项目就按「手上真有的短字段」建**词元集合**：作者 / 题材 / 系列 / 出版社 /
   语言 / 出版年十年段 / 书名词元（中文取二元组，英文取 ≥2 字母的词）。
   **简介刻意不进向量**：它是抓来的自由文本，同一本书在不同源的简介几乎不重合，
   塞进去只会让余弦被「谁的字数多」带偏。
   用集合而非词频（TF）也是同一个理由：书目的元数据太短，词频只会放大
   「同一句写了两遍」这种噪音。
2. **保留一道「实质重合」门**：余弦能靠「同语言 + 同出版社」这种弱重合冲到 0.3–0.4，
   那种推荐没有信息量（原有注释那句话仍然成立：**「毫无关系」的推荐只会消耗界面信任**）。
   所以候选必须**至少有作者 / 题材 / 系列之一重合**，在这批候选里再按五路加权排序 ——
   上游的权重决定**排得好不好**，这道门决定**该不该出现**。

复杂度：O(N·tokens)，词元只构建一次（同一本书不会在每轮比较里重建），纯派生、不查库。
"""
import re

#: 五路权重（加总 1.0；缺路时按剩余权重归一）
W_COSINE = 0.5
W_AUTHOR = 0.1
W_TAG = 0.25
W_SERIES = 0.1
W_RATING = 0.05

#: 上限对齐上游（25）；默认值沿用本项目的 6（详情页先显示 6 条，可展开看全部）
MAX_LIMIT = 25
DEFAULT_LIMIT = 6

#: 余弦到达这个值才在理由里写一条（不然每本书都顶着「元数据重合 3%」很吵）
MIN_COSINE_REASON = 0.5

#: 评分满分（五档）
_RATING_MAX = 5.0

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_WORD = re.compile(r"[a-z0-9]{2,}")


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _text_tokens(text) -> set:
    """一段文本 → 词元集合。

    中文没有空格，按词切需要词典（本仓不引第三方依赖），所以走**二元组**：
    「基地与帝国」给出 基/地/基地/地与/与帝/帝国… 足以把《基地》与《基地与帝国》
    拉近，又不会把《第二基地》错当成同一本。英文按 ≥2 字母的词切。
    """
    t = str(text or "").lower()
    out = set(_ASCII_WORD.findall(t))
    for han in _CJK.findall(t):
        if len(han) == 1:
            out.add(han)
        out.update(han[i:i + 2] for i in range(len(han) - 1))
    return out


def _vector(b: dict) -> set:
    """一本书的**元数据词元集合**（余弦的输入）。

    短字段直接取整值做一个词元（作者/系列/出版社/语言各一个，避免「张三」与「张三丰」
    因为共享「张三」而被判相似）；书名才分词；出版年按**十年段**归并（1999 与 2001 同段）。
    """
    out: set = set()
    for tag, raw in (("a", b.get("author")), ("s", b.get("series")),
                     ("p", b.get("publisher")), ("l", b.get("language"))):
        v = _norm(raw)
        if v:
            out.add(f"{tag}:{v}")
    year = str(b.get("year") or "").strip()[:4]
    if year.isdigit():
        out.add(f"y:{int(year) // 10 * 10}s")
    for w in _text_tokens(b.get("title")):
        out.add("t:" + w)
    for g in (b.get("tags") or []):
        v = _norm(g)
        if v:
            out.add("g:" + v)
    return out


def _cosine(a: set, b: set) -> float:
    """集合余弦（= |交| / sqrt(|A|·|B|)）。任一侧为空 ⇒ 0（不参与相似）。"""
    if not a or not b:
        return 0.0
    return len(a & b) / ((len(a) ** 0.5) * (len(b) ** 0.5))


def _jaccard(a: set, b: set) -> float:
    """题材重合度：交 / 并（比「重合个数×2」更公平 —— 后者奖励题材列得多的书）。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _rating(b: dict) -> "float | None":
    """书目里的评分（0–5）；未评分（缺字段 / 0 / 非法）返回 None。"""
    try:
        v = float(b.get("rating") or 0)
    except (TypeError, ValueError):
        return None
    return v if 0 < v <= _RATING_MAX else None


def _rating_closeness(a: "float | None", b: "float | None") -> "float | None":
    """评分接近度：``1 - |差| / 5``（5 分制）。任一方未评分 ⇒ None（该路不计入）。"""
    if a is None or b is None:
        return None
    return max(0.0, 1.0 - abs(a - b) / _RATING_MAX)


def similar_books(book_id: str, books: list, limit: int = DEFAULT_LIMIT) -> list:
    """返回与 ``book_id`` 最相似的若干本（不含自身）。

    ``books`` 传 /api/books 同构的书目（含 author/tags/series/publisher/language/year/rating）。
    只返回**至少一条实质重合**（同作者 / 共同题材 / 同系列）的书 ——
    「毫无关系」的推荐只会消耗界面信任。

    出参每项：``{id, title, author, series, series_index, cover_url, has_cover, score, reasons}``。
    ``score`` 是 **0–1 的加权总分**（第 35 期起；此前是 3.0/2.0 这样的裸分值），
    ``reasons`` 仍是给人看的「为什么相似」。
    """
    me = next((b for b in books if b["id"] == book_id), None)
    if me is None:
        return []
    # 0 / None = 「没给条数」⇒ 用默认；给了就夹在 1..MAX_LIMIT 之间（负数也算没给够）
    limit = max(1, min(int(limit) if limit else DEFAULT_LIMIT, MAX_LIMIT))

    my_vec = _vector(me)
    my_tags = {_norm(t) for t in (me.get("tags") or []) if _norm(t)}
    my_author = _norm(me.get("author"))
    my_series = _norm(me.get("series"))
    my_rating = _rating(me)

    out = []
    for b in books:
        if b["id"] == book_id:
            continue
        their_tags = {_norm(t) for t in (b.get("tags") or []) if _norm(t)}
        shared = my_tags & their_tags
        same_author = bool(my_author) and _norm(b.get("author")) == my_author
        same_series = bool(my_series) and _norm(b.get("series")) == my_series
        # 「实质重合」门：三条可解释的轴里至少中一条，余弦不参与这道门
        if not (same_author or shared or same_series):
            continue

        cos = _cosine(my_vec, _vector(b))
        tag_sim = _jaccard(my_tags, their_tags)
        rating_sim = _rating_closeness(my_rating, _rating(b))
        parts = [(W_COSINE, cos), (W_AUTHOR, 1.0 if same_author else 0.0),
                 (W_TAG, tag_sim), (W_SERIES, 1.0 if same_series else 0.0)]
        if rating_sim is not None:
            parts.append((W_RATING, rating_sim))
        total_w = sum(w for w, _ in parts)
        score = sum(w * v for w, v in parts) / total_w if total_w else 0.0

        reasons = []
        if same_author:
            reasons.append("同作者")
        if shared:
            reasons.append("题材：" + "、".join(sorted(shared)))
        if same_series:
            reasons.append("同系列")
        if cos >= MIN_COSINE_REASON:
            reasons.append(f"元数据重合 {round(cos * 100)}%")
        if rating_sim is not None and rating_sim >= 0.8:
            reasons.append("评分接近")

        out.append({
            "id": b["id"],
            "title": b.get("title"),
            "author": b.get("author"),
            "series": b.get("series"),
            "series_index": b.get("series_index"),
            "cover_url": b.get("cover_url"),
            "has_cover": b.get("has_cover", False),
            # 0–1 的加权总分（前端只用 title 与 reasons，但接口口径要写清楚）
            "score": round(score, 4),
            # 去重的理由文案（同系列 + 同作者时不要说两遍）
            "reasons": list(dict.fromkeys(reasons)),
        })
    # 排序键要能**完全定序**：同分再同标题的书（同书不同版本）只靠标题分不开，
    # 而 Python 的排序是稳定的 ⇒ 顺序会跟着输入顺序变（扫描顺序一变，推荐列表就跳）。
    # 所以补一个 id（库内稳定、内容派生）作为最后一级。
    out.sort(key=lambda x: (-x["score"], x.get("title") or "", x["id"]))
    return out[:limit]
