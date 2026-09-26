"""语义向量（第 54 期）：相似书余弦一路的「真·向量」后端。

此前 ``recommend.py`` 的余弦输入是**元数据词元集合**（集合余弦 = |交| / 几何平均），
它只认词形重合：两本书都写太空歌剧，只要简介措辞不同，词元就完全不交。
本模块给出一条**离线、零下载、可插拔**的向量路线：

1. 默认 ``LSAEmbedder`` —— TF-IDF + 截断 SVD（latent semantic analysis 的教科书做法，
   纯 numpy）。SVD 把「经常一起出现的词」压进同一批潜概念维度，从而对「同义不同词」
   给出非零相似度 —— 这是词袋给不了的「语义」成分。
2. 可选 ``ModelEmbedder`` —— 用户自备本地 sentence-transformers 模型（放
   ``CACHE_DIR/embedding-model``，运行时**绝不联网**）；依赖或模型缺失时工厂自动
   回落 LSA，绝不因可选增强破坏可用性。

语料：每本书拼接 title / author / tags / series / publisher / language / year，
外加 description。简介此前被词袋余弦**刻意排除**（集合余弦会被「谁的字数多」带偏）；
TF-IDF + 行 L2 归一下这个偏差不存在了，简介里的内容词正是「语义」的主要来源 ——
但为让短而强的字段（题名 / 作者 / 题材）继续主导排序，简介词元按 ``DESC_WEIGHT`` 降权。

重算口径：**全量批式**（:func:`compute_embeddings`）。书目短文本 + 封顶词表下，
SVD 代价与库规模同阶（几千本书秒级）；批式让「新语料 / 新模型」天然一致，
不需要持久化投影基 —— 新书入库或元数据变更后重跑一次即全量刷新。
向量落 ``book_embeddings`` 表（float32 小端 BLOB），行带 ``model_tag``：
读端只认当前后端的 tag，换模型后旧行自然失效，不必清表。
"""
import math

import numpy as np

from .. import config
from .recommend import _text_tokens  # 词元判据唯一来源（CJK 二元组 / 拉丁 ≥2 字母词）

#: 潜概念维度。书目短文本下 128 足够容纳主要语义轴，再大只会放大噪音。
DIM = 128
#: 词表封顶（按文档频率取前 N）。不给 V 设上限，N 本书 × 大词表的稠密矩阵会吃内存。
VOCAB_CAP = 4096
#: 少于这个书数不产向量：两三本书的潜空间只有 1–2 个有效维度，余弦非 0 即 1，
#: 排序毫无信息量 ⇒ 直接回落词袋。
MIN_BOOKS = 3
#: 简介词元的降权系数（短强字段权重 1.0）。
DESC_WEIGHT = 0.25

#: LSA 后端的模型标识（写进 ``book_embeddings.model_tag``；改动口径必须换新 tag）
MODEL_TAG = f"lsa{DIM}-v1"


def corpus_of(book: dict) -> str:
    """书目 → 一段语料文本（字段拼装顺序固定，同输入同输出）。"""
    parts = [
        str(book.get("title") or ""),
        str(book.get("author") or ""),
        str(book.get("series") or ""),
        str(book.get("publisher") or ""),
        str(book.get("language") or ""),
        str(book.get("year") or ""),
    ]
    parts += [str(t) for t in (book.get("tags") or [])]
    return "\n".join(parts)


def _term_counts(book: dict) -> dict:
    """一本书的加权词频：短强字段 1.0 / 条，简介 ``DESC_WEIGHT`` / 条。"""
    counts: dict = {}
    for tok in _text_tokens(corpus_of(book)):
        counts[tok] = counts.get(tok, 0.0) + 1.0
    desc = str(book.get("description") or "")
    if desc:
        for tok in _text_tokens(desc):
            counts[tok] = counts.get(tok, 0.0) + DESC_WEIGHT
    return counts


class LSAEmbedder:
    """默认后端：TF-IDF + 截断 SVD，纯 numpy、零下载、离线。"""

    tag = MODEL_TAG

    def fit(self, books: list) -> dict:
        """全量重算：``{book_id: (float32 小端 bytes, model_tag)}``。

        书数不足 ``MIN_BOOKS`` 或词表为空 ⇒ 返回 ``{}``（调用方别落库，
        读端自然整路回落词袋，而不是留一套只含噪音的向量）。
        """
        ids: list = []
        rows: list = []
        for b in books:
            tc = _term_counts(b)
            if tc:
                ids.append(b["id"])
                rows.append(tc)
        n = len(rows)
        if n < MIN_BOOKS:
            return {}

        df: dict = {}
        for tc in rows:
            for t in tc:
                df[t] = df.get(t, 0) + 1
        # 词表封顶：先按 df 降序再按词面定序 —— 不写死这个次序，SVD 的潜维度
        # 会随 dict 迭代序漂移，两次重算同一批书可能给出不同向量。
        vocab = sorted(df, key=lambda t: (-df[t], t))[:VOCAB_CAP]
        index = {t: j for j, t in enumerate(vocab)}

        # TF-IDF + 行 L2：TF 取 1+log(次) 压长简介，IDF 压「人人都有的词」。
        X = np.zeros((n, len(vocab)), dtype=np.float64)
        for i, tc in enumerate(rows):
            for t, c in tc.items():
                j = index.get(t)
                if j is None:
                    continue
                X[i, j] = (1.0 + math.log(c)) * (math.log((1 + n) / (1 + df[t])) + 1.0)
            row_norm = float(np.linalg.norm(X[i]))
            if row_norm:
                X[i] /= row_norm

        # X = U·S·Vt；书坐标取 U·S（潜概念空间）。行间余弦只依赖 U·S，
        # 与 SVD 的符号不确定性无关 —— 同一批书两次重算给出的两两余弦一致。
        u, s, _ = np.linalg.svd(X, full_matrices=False)
        d = min(DIM, int(s.shape[0]))
        emb = u[:, :d] * s[:d]

        out: dict = {}
        for i, bid in enumerate(ids):
            v = np.ascontiguousarray(emb[i], dtype="<f4")
            if float(np.linalg.norm(v)):  # 词表全不中 ⇒ 零向量不落库，读端按「无向量」回落
                out[str(bid)] = (v.tobytes(), self.tag)
        return out


class ModelEmbedder:
    """可选后端：本地 sentence-transformers 模型（依赖与模型文件都由用户自备）。

    只有当 ``CACHE_DIR/embedding-model`` 是个目录**且** ``sentence_transformers``
    可导入时，:func:`get_backend` 才会实例化本类 —— 缺一即回落 LSA。
    运行时不联网：编码是纯本地 CPU 推理。
    """

    def __init__(self, path):
        self.path = path
        self._model = None

    @property
    def tag(self):
        return "st:" + self.path.name

    def fit(self, books: list) -> dict:
        texts = [corpus_of(b) + "\n" + str(b.get("description") or "") for b in books]
        try:
            if self._model is None:
                from sentence_transformers import SentenceTransformer  # 可选依赖，延迟导入
                self._model = SentenceTransformer(str(self.path), device="cpu")
            mat = self._model.encode(texts, convert_to_numpy=True,
                                     normalize_embeddings=True)
        except Exception:
            # 模型半路起不来（文件残缺 / 版本不符）⇒ 本轮整体回落词袋。
            # 不落半套向量：读端按 tag 过滤，旧 tag 行自然失效，不会新旧混排。
            return {}
        out: dict = {}
        for b, row in zip(books, mat):
            v = np.ascontiguousarray(row, dtype="<f4")
            if float(np.linalg.norm(v)):
                out[str(b["id"])] = (v.tobytes(), self.tag)
        return out


def get_backend():
    """当前可用后端：本地 transformer 模型（用户自备）优先，缺依赖 / 缺模型回落 LSA。"""
    model_dir = config.CACHE_DIR / "embedding-model"
    if model_dir.is_dir():
        try:
            import sentence_transformers  # noqa: F401 — 可选依赖探测
            return ModelEmbedder(model_dir)
        except Exception:
            pass
    return LSAEmbedder()


def compute_embeddings(books: list) -> dict:
    """全量重算入口：``{book_id: (bytes, model_tag)}``，交给 ``db.set_embeddings`` 落库。"""
    return get_backend().fit(books)


def load_vectors() -> dict:
    """读出**当前后端 tag**的向量（解码为 float32 数组）：``{book_id: np.ndarray}``。

    旧 tag 的行（换过模型 / 语料口径）一律忽略 —— 宁可整路回落词袋，也不新旧混排。
    """
    from . import db
    tag = get_backend().tag
    out: dict = {}
    for bid, (raw, row_tag) in db.get_embeddings().items():
        if row_tag != tag:
            continue
        v = np.frombuffer(raw, dtype="<f4")
        if v.size and float(np.linalg.norm(v)):
            out[bid] = v
    return out


def vec_cosine(a, b) -> float:
    """稠密向量余弦；任一侧为零向量（未产向量不该进这里，兜底）⇒ 0。"""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def refresh(books: "list | None" = None) -> dict:
    """全量重算并落库，返回 ``{count, tag}``。

    ``books`` 缺省取 ``library.books()``（含 description，语料完整）。向量是纯派生
    缓存，重算 = 覆写同 tag 行；重算期间 /similar 照常用旧向量，不受影响。
    """
    if books is None:
        from . import library
        books = library.books()
    from . import db
    items = compute_embeddings(books)
    db.set_embeddings(items)
    return {"count": len(items), "tag": get_backend().tag}
