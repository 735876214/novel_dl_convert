"""元数据完整度权重可配 + 版本标注（第 204 期）。"""
from __future__ import annotations

from novelforge.core import metascore


def test_权重覆盖与版本():
    cfg = {"metadata_score": {"weights": {"title": 0, "author": 30, "nope": 99,
                                         "language": "bad", "publisher": 500},
                              "version": 7}}
    w = metascore._weights(cfg)
    assert w["title"] == 0 and w["author"] == 30
    assert w["language"] == 6.0 and w["publisher"] == 7.0   # 坏值 / 越界忽略
    assert "nope" not in w
    assert metascore._weight_version(cfg) == 7
    assert metascore._weight_version(None) == 1


def test_载荷带生效权重与版本():
    book = {"id": "b1", "name": "a.epub", "format": "EPUB", "title": "书", "author": "",
            "has_cover": False, "language": "", "publisher": "", "year": "",
            "pages": 0, "description": "", "tags": [], "isbn": "", "series": "",
            "series_index": ""}
    cfg = {"metadata_score": {"weights": {"title": 0, "author": 40}, "version": 3}}
    out = metascore.payload([book], cfg=cfg)
    assert out["weight_version"] == 3
    assert out["weights"]["title"] == 0 and out["weights"]["author"] == 40
    core = next(g for g in out["groups"] if g["key"] == "core")
    weights = {f["key"]: f["weight"] for f in core["fields"]}
    assert weights["title"] == 0 and weights["author"] == 40
    # 只有标题有值、标题权重 0 ⇒ 0 分（分母仍是其它字段的默认权重）
    assert out["lowest"][0]["score"] == 0.0
