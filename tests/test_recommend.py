"""第 35 期：相似书推荐的五路加权打分（`core/recommend.py`）。

打分口径：``0.5·余弦 + 0.1·同作者 + 0.25·题材Jaccard + 0.1·同系列 + 0.05·评分接近度``，
缺的那一路**不进分母**（没评分不该把好书压下去）。本文件钉四类边界：

1. **权重可加性**：五路全中 ⇒ 1.0；只有一路中 ⇒ 该路权重占**已生效权重**的比例；
2. **「实质重合」门**：只剩「同语言 + 同出版社」这种弱重合时不进候选
   （余弦能靠它冲到 0.3+，但那种推荐没有信息量）；
3. **题材用 Jaccard**：不再奖励「题材列得多」的书；
4. **上限与排序稳定**：上限 25（对齐上游）、同分按标题、得分为 0 不返回。

纯派生：不查库、不外呼，构造书目 dict 即可测。
"""
import pathlib

from novelforge.core import epub_builder, library, recommend


def _book(bid: str, title: str, **kw) -> dict:
    base = {"id": bid, "title": title, "author": "", "tags": [], "series": "",
            "series_index": "", "publisher": "", "language": "", "year": "",
            "rating": 0, "cover_url": "", "has_cover": False}
    base.update(kw)
    return base


def _score(me: dict, other: dict, limit: int = 6) -> "float | None":
    """跑一次推荐，返回 other 的分数；没进候选就返回 None。"""
    hit = next((x for x in recommend.similar_books(me["id"], [me, other], limit)
                if x["id"] == other["id"]), None)
    return hit["score"] if hit else None


# ---------------------------------------------------------------------------
# 权重可加性
# ---------------------------------------------------------------------------

def test_五路全中得满分(isolated):  # noqa: ARG001
    me = _book("a", "基地", author="阿西莫夫", tags=["科幻"], series="银河帝国",
               publisher="江苏文艺", language="zh", year="2012", rating=5)
    other = dict(me, id="b")
    got = recommend.similar_books("a", [me, other], 6)
    assert got and got[0]["score"] == 1.0, "每一项都是 1.0 ⇒ 加权和也是 1.0"


def test_只中同作者时分数为权重占比(isolated):  # noqa: ARG001
    """同作者 0.1 路满分、其余全 0 ⇒ 分数 = 0.1 / 已生效权重。"""
    me = _book("a", "甲", author="同一人", language="zh")
    other = _book("b", "乙", author="同一人")
    got = _score(me, other)
    assert got is not None
    # 余弦不是 0（同作者也在词元里）；这里断言的是「量级落在作者路附近且远小于满分」
    assert 0 < got < 0.35


def test_多中一路分数更高(isolated):  # noqa: ARG001
    me = _book("a", "基地", author="阿西莫夫", tags=["科幻"], language="zh")
    author_only = _book("b", "别的书", author="阿西莫夫", language="zh")
    author_and_tag = _book("c", "别的书", author="阿西莫夫", tags=["科幻"], language="zh")
    assert _score(me, author_and_tag) > _score(me, author_only)


def test_同系列也计入(isolated):  # noqa: ARG001
    me = _book("a", "基地", series="银河帝国", language="zh")
    series_only = _book("b", "基地与帝国", series="银河帝国", language="zh")
    assert _score(me, series_only) is not None


# ---------------------------------------------------------------------------
# 「实质重合」门：弱重合不进候选
# ---------------------------------------------------------------------------

def test_只剩同语言同出版社不进候选(isolated):  # noqa: ARG001
    """余弦能靠这两项冲到不低的值，但「同一个出版社出的中文书」没有任何推荐价值。"""
    me = _book("a", "基地", publisher="江苏文艺", language="zh")
    other = _book("b", "另一本无关的书", publisher="江苏文艺", language="zh")
    assert recommend.similar_books("a", [me, other], 6) == []


def test_毫无重合不返回(isolated):  # noqa: ARG001
    me = _book("a", "基地", author="阿西莫夫", tags=["科幻"])
    other = _book("b", "红楼梦", author="曹雪芹", tags=["古典"])
    assert recommend.similar_books("a", [me, other], 6) == []


def test_书目完全没有元数据不炸(isolated):  # noqa: ARG001
    me = _book("a", "无元数据")
    other = _book("b", "另一本无元数据")
    assert recommend.similar_books("a", [me, other], 6) == [], "空向量 ⇒ 余弦 0，且没有实质重合"
    assert recommend.similar_books("不存在", [me], 6) == []


# ---------------------------------------------------------------------------
# 题材用 Jaccard（不奖励「列得多」）
# ---------------------------------------------------------------------------

def test_题材重合用jaccard(isolated):  # noqa: ARG001
    me = _book("a", "基地", author="同一人", tags=["科幻"])
    tight = _book("b", "另一本", author="同一人", tags=["科幻"])
    loose = _book("c", "另一本", author="同一人",
                  tags=["科幻", "言情", "武侠", "历史", "悬疑"])
    assert _score(me, tight) > _score(me, loose), \
        "同样只中 1 个题材，Jaccard 该让「题材窄」的那本排前面"


# ---------------------------------------------------------------------------
# 评分接近度
# ---------------------------------------------------------------------------

def test_评分接近提升分数(isolated):  # noqa: ARG001
    me = _book("a", "基地", author="同一人", tags=["科幻"], rating=5)
    close = _book("b", "另一本", author="同一人", tags=["科幻"], rating=5)
    far = _book("c", "另一本", author="同一人", tags=["科幻"], rating=1)
    assert _score(me, close) > _score(me, far)


def test_未评分不进分母(isolated):  # noqa: ARG001
    """双方都没评分 ⇒ 其余四路全中时仍然是满分（不能因为「没打分」扣它 5%）。"""
    me = _book("a", "基地", author="同一人", tags=["科幻"], series="银河帝国")
    other = _book("b", "基地", author="同一人", tags=["科幻"], series="银河帝国")
    assert _score(me, other) == 1.0


def test_理由里有评分接近(isolated):  # noqa: ARG001
    me = _book("a", "基地", author="同一人", rating=5)
    other = _book("b", "另一本", author="同一人", rating=5)
    hit = recommend.similar_books("a", [me, other], 6)[0]
    assert "同作者" in hit["reasons"] and "评分接近" in hit["reasons"]


def test_理由文案去重且可解释(isolated):  # noqa: ARG001
    me = _book("a", "基地", author="阿西莫夫", tags=["科幻"], series="银河帝国")
    other = dict(me, id="b")
    hit = recommend.similar_books("a", [me, other], 6)[0]
    assert hit["reasons"][:3] == ["同作者", "题材：科幻", "同系列"]
    assert len(hit["reasons"]) == len(set(hit["reasons"]))
    assert any(r.startswith("元数据重合") for r in hit["reasons"]), "完全同构时应给出重合度"


# ---------------------------------------------------------------------------
# 中文书名（二元组）
# ---------------------------------------------------------------------------

def test_中文书名靠二元组拉近(isolated):  # noqa: ARG001
    me = _book("a", "基地", author="同一人")
    near = _book("b", "基地与帝国", author="同一人")
    far = _book("c", "完全不相干的名字", author="同一人")
    n, f = _score(me, near), _score(me, far)
    assert n is not None and f is not None and n > f


# ---------------------------------------------------------------------------
# 上限与排序
# ---------------------------------------------------------------------------

def test_上限25与默认条数(isolated):  # noqa: ARG001
    assert recommend.MAX_LIMIT == 25 and recommend.DEFAULT_LIMIT == 6
    me = _book("me", "基地", author="同一人")
    others = [_book(f"b{i}", f"另一本{i}", author="同一人") for i in range(40)]
    assert len(recommend.similar_books("me", [me, *others], 99)) == 25, "上限封在 25"
    # 0 / None = 「没给条数」⇒ 默认 6（HTTP 层的 ge=1 已经把 0 挡在门外）
    assert len(recommend.similar_books("me", [me, *others], 0)) == 6
    assert len(recommend.similar_books("me", [me, *others], None)) == 6
    assert len(recommend.similar_books("me", [me, *others], -3)) == 1, "负数夹到 1"


def test_顺序完全确定(isolated):  # noqa: ARG001
    me = _book("me", "基地", author="同一人")
    # 同分 + 同名（同一本书的两个版本）⇒ 只靠标题分不开，必须靠末级 id 定序
    a = _book("a", "一样的名字", author="同一人")
    b = _book("b", "一样的名字", author="同一人")
    fwd = [x["id"] for x in recommend.similar_books("me", [me, a, b], 6)]
    rev = [x["id"] for x in recommend.similar_books("me", [me, b, a], 6)]
    assert fwd == rev == ["a", "b"], "换输入顺序不该换结果（否则推荐列表会随扫描顺序跳）"
    scores = [x["score"] for x in recommend.similar_books("me", [me, a, b], 6)]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 接口边界
# ---------------------------------------------------------------------------

def _real_epub(root, name: str, title: str, author: str, tags=None) -> pathlib.Path:
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"title": title, "author": author, "language": "zh"}
    if tags:
        meta["tags"] = tags
    epub_builder.build_epub(meta, [{"title": "第一章", "body_html": "<p>正文</p>"}], str(path))
    return path


def test_接口上限25(client, auth_headers, default_root):  # noqa: ARG001
    _real_epub(default_root, "推荐.epub", "推荐", "同一人", ["科幻"])
    library.invalidate()
    b = client.get("/api/books", headers=auth_headers).json()["items"][0]

    assert client.get(f"/api/books/{b['id']}/similar", headers=auth_headers).status_code == 200
    assert client.get(f"/api/books/{b['id']}/similar?limit=25",
                      headers=auth_headers).status_code == 200
    assert client.get(f"/api/books/{b['id']}/similar?limit=26",
                      headers=auth_headers).status_code == 422, "上限对齐上游 25"
    assert client.get(f"/api/books/{b['id']}/similar?limit=0",
                      headers=auth_headers).status_code == 422


def test_接口未登录401(client):  # noqa: ARG001
    assert client.get("/api/books/x/similar").status_code == 401
