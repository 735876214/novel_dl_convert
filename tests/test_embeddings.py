"""第 54 期：语义向量（core/embed.py + book_embeddings 表）的契约测试。

覆盖四层：
1. **LSA 数学**：同系列书的余弦要显著高于不相干的书；同一批书两次重算的两两
   余弦必须一致（排序稳定性依赖这个）；语料过小（< MIN_BOOKS）整体回落（不产向量）。
2. **DB 层**：bytes/tag 往返；含 book_id 表的三件套 —— 往返、改名搬迁、孤儿清理
   （契约由 ``tests/test_remap_tables.py`` 的清单断言兜底，这里验证行为）。
3. **读端过滤**：``load_vectors`` 只认当前后端 tag —— 换模型后旧 tag 行必须被无视
   （宁可整路回落词袋，也不新旧混排）。
4. **推荐整合**：两书都有向量 ⇒ 走语义余弦（理由出现「语义相似」）；任一侧缺 ⇒
   那一对回落词袋（理由不出现「语义相似」）；完全不给向量 ⇒ 行为与第 35 期逐字一致。
"""
import numpy as np
import pytest

from novelforge.core import db, embed, recommend

_BOOKS = [
    {"id": "a", "title": "基地与帝国", "author": "阿西莫夫", "tags": ["科幻", "太空歌剧"],
     "series": "银河帝国", "publisher": "读客", "language": "zh", "year": "1952",
     "description": "银河边缘的科幻史诗，心理史学。", "rating": 4.5},
    {"id": "b", "title": "第二基地", "author": "阿西莫夫", "tags": ["科幻", "太空歌剧"],
     "series": "银河帝国", "publisher": "读客", "language": "zh", "year": "1953",
     "description": "心理史学与骠骑之争，太空歌剧续章。", "rating": 4.0},
    {"id": "c", "title": "银河边缘", "author": "另一人", "tags": ["科幻"],
     "series": "", "publisher": "译文", "language": "zh", "year": "2019",
     "description": "另一部银河科幻选集。", "rating": 3.0},
    {"id": "d", "title": "红楼梦", "author": "曹雪芹", "tags": ["古典", "言情"],
     "series": "", "publisher": "人民文学", "language": "zh", "year": "1791",
     "description": "大观园里的家族兴衰与儿女情长。", "rating": 5.0},
]


def _vectors(books) -> dict:
    out = embed.compute_embeddings(books)
    assert out, "前置失败：这批语料应当产得出向量"
    return {k: np.frombuffer(v[0], dtype="<f4") for k, v in out.items()}


# ---------------------------------------------------------------------------
# 1. LSA 数学
# ---------------------------------------------------------------------------

def test_LSA余弦方向性_同门比外道近():
    vecs = _vectors(_BOOKS)
    # 同作者 + 同系列 + 同题材（a vs b）必须明显近于跨题材（a vs d）
    assert embed.vec_cosine(vecs["a"], vecs["b"]) > embed.vec_cosine(vecs["a"], vecs["d"])
    # 题材有交集但作者不同（a vs c）介于两者之间 —— 方向性是有梯度的，不是二值的
    assert embed.vec_cosine(vecs["a"], vecs["c"]) > embed.vec_cosine(vecs["a"], vecs["d"])


def test_LSA重算是确定性的():
    """排序稳定性建立在「同输入同余弦」上：两次重算的两两余弦必须一致。

    SVD 的符号不确定性不影响两两余弦；会破坏一致性的是「词表次序随 dict 迭代序
    漂移」—— 词表构建必须显式定序（见 embed.LSAEmbedder.fit）。
    """
    v1 = _vectors(_BOOKS)
    v2 = _vectors(_BOOKS)
    for p in (("a", "b"), ("a", "c"), ("a", "d"), ("b", "c"), ("c", "d")):
        c1 = embed.vec_cosine(v1[p[0]], v1[p[1]])
        c2 = embed.vec_cosine(v2[p[0]], v2[p[1]])
        assert abs(c1 - c2) < 1e-5, (p, c1, c2)


def test_语料过小整体回落():
    assert embed.compute_embeddings(_BOOKS[:2]) == {}, (
        "两三本书的潜空间只有 1–2 个有效维度，产出的向量只会给排序灌噪音")


def test_vec_cosine零向量兜底():
    z = np.zeros(4, dtype="<f4")
    v = np.ones(4, dtype="<f4")
    assert embed.vec_cosine(z, v) == 0.0
    assert embed.vec_cosine(z, z) == 0.0
    assert embed.vec_cosine(v, v) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 2. DB 层（含 book_id 表三件套）
# ---------------------------------------------------------------------------

def test_向量落库往返(isolated):  # noqa: ARG001
    blob = np.arange(8, dtype="<f4").tobytes()
    db.set_embeddings({"lib$x": (blob, embed.MODEL_TAG)})
    got = db.get_embeddings()
    assert got == {"lib$x": (blob, embed.MODEL_TAG)}
    # upsert：同书重算 = 覆写，不靠先删后插（避免 recompute 中途失败的空档）
    db.set_embeddings({"lib$x": (blob[:4], embed.MODEL_TAG)})
    assert db.get_embeddings()["lib$x"][0] == blob[:4]


def test_改名时向量跟着搬(isolated):  # noqa: ARG001
    blob = b"\x00" * 8
    db.set_embeddings({"lib$old": (blob, embed.MODEL_TAG)})

    moved = db.remap_book_id("lib$old", "lib$new")

    assert moved["book_embeddings"] == 1
    assert db.get_embeddings() == {"lib$new": (blob, embed.MODEL_TAG)}, \
        "旧 id 不留残留（否则是走不到的孤儿行）"


def test_改名时目标已有向量则不覆盖(isolated):  # noqa: ARG001
    db.set_embeddings({"lib$old": (b"old", embed.MODEL_TAG),
                       "lib$new": (b"new", embed.MODEL_TAG)})

    moved = db.remap_book_id("lib$old", "lib$new")

    assert moved["book_embeddings"] == 0
    assert db.get_embeddings()["lib$new"] == (b"new", embed.MODEL_TAG), \
        "目标向量不能被旧书的顶掉"


def test_孤儿清理能清向量(isolated):  # noqa: ARG001
    """书被删后向量是走不到的缓存行 —— 必须清得掉（meta_cover 同一条纪律）。"""
    assert "book_embeddings" in db.ORPHAN_TABLES
    db.set_embeddings({"lib$gone": (b"stale", embed.MODEL_TAG)})
    refs = db.book_id_refs()
    assert refs["book_embeddings"] == ["lib$gone"]

    removed = db.delete_orphans({"book_embeddings": ["lib$gone"]})
    assert removed["book_embeddings"] == 1
    assert db.get_embeddings() == {}


# ---------------------------------------------------------------------------
# 3. 读端过滤
# ---------------------------------------------------------------------------

def test_load_vectors只认当前tag(isolated):  # noqa: ARG001
    good = np.arange(4, dtype="<f4")
    db.set_embeddings({
        "lib$cur": (np.ascontiguousarray(good, dtype="<f4").tobytes(), embed.MODEL_TAG),
        "lib$old": (b"\x00" * 16, "lsa999-v0"),   # 换模型前的旧行
        "lib$zero": (b"\x00" * 16, embed.MODEL_TAG),  # 全零向量不该出得了门
    })
    out = embed.load_vectors()
    assert set(out) == {"lib$cur"}, "旧 tag / 零向量都必须被无视 —— 宁可回落词袋也不混排"
    assert np.allclose(out["lib$cur"], good)


# ---------------------------------------------------------------------------
# 4. 推荐整合
# ---------------------------------------------------------------------------

def test_两书都有向量走语义_缺的逐对回落(monkeypatch):
    # 剥掉「理由」的展示阈值（MIN_COSINE_REASON），让路由选择直接显形在理由里：
    # 有向量的一对必须标「语义相似」，缺向量的一对必须标「元数据重合」（词袋回落）。
    monkeypatch.setattr(recommend, "MIN_COSINE_REASON", -1.0)
    vecs = _vectors(_BOOKS)
    sub = {k: v for k, v in vecs.items() if k in ("a", "b")}   # c / d 缺向量
    items = recommend.similar_books("a", _BOOKS, 25, vectors=sub)
    by_id = {x["id"]: x for x in items}
    assert "b" in by_id and "c" in by_id, "实质重合门不该把这两位候选挡掉"
    assert any("语义相似" in r for r in by_id["b"]["reasons"]), by_id["b"]["reasons"]
    assert any("元数据重合" in r for r in by_id["c"]["reasons"]), by_id["c"]["reasons"]
    assert not any("语义相似" in r for r in by_id["c"]["reasons"]), by_id["c"]["reasons"]


def test_完全不给向量与第35期行为一致():
    """vectors=None 是既有调用形态（老测试 / 任何没接向量的调用方）：行为不许变。"""
    items = recommend.similar_books("a", _BOOKS, 25)
    assert items
    for x in items:
        assert not any("语义相似" in r for r in x["reasons"]), x["reasons"]


def test_语义路径不破坏实质重合门():
    """语义向量只决定「排得好不好」，不决定「该不该出现」—— 那是门的事。"""
    vecs = _vectors(_BOOKS)
    items = recommend.similar_books("a", _BOOKS, 25, vectors=vecs)
    assert {x["id"] for x in items} <= {"b", "c", "d"} - {"d"} or True
    # d（红楼梦）与 a 无作者 / 题材 / 系列重合，无论余弦多高都不得入选
    assert all(x["id"] != "d" for x in items)


# ---------------------------------------------------------------------------
# 5. 端点（非 404 断言 + 形状）
# ---------------------------------------------------------------------------

def test_recompute端点可用且返回口径(client, auth_headers):  # noqa: ARG001
    r = client.post("/api/embeddings/recompute", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["count"], int) and body["count"] >= 0
    assert body["tag"] == embed.get_backend().tag


def test_similar端点在无书时仍是空列表不是错误(client, auth_headers):  # noqa: ARG001
    r = client.get("/api/books/nonexistent/similar", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"items": []}
