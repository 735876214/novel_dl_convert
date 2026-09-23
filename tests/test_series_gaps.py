"""第 43 期：系列缺册 —— 按 `series_index` 数字集合求 `[1..max]` 的补集。

钉住三条口径（唯一实现是 `library.series_gaps`，前端不再自己算）：
1. **中间空洞与尾部缺口都算**缺册；
2. **无序号**单独计数、**不并入**缺册 —— 否则每本没序号的书都会凭空造出一个「缺 1」；
3. **非数字序号**（如「特典」）同样不参与数字补集 —— 不硬猜它在第几册。
"""
from __future__ import annotations

import pathlib

from novelforge.core import epub_builder, fileops, library


def _epub(root, name: str, **meta) -> pathlib.Path:
    """造一本真 EPUB，并把给定字段写进 OPF（扫描才读得到）。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": meta.pop("title", path.stem), "author": "测试作者", "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    if meta:
        assert fileops.patch_epub_meta(path, meta), f"OPF 改写失败：{name}"
    return path


def test_中间空洞与尾部缺口都算缺册(isolated, default_root):  # noqa: ARG001
    for name, idx in (("一.epub", "1"), ("三.epub", "3"), ("四.epub", "4")):
        _epub(default_root, name, series="测试系列", series_index=idx)
    library.invalidate()

    g = library.series_gaps("测试系列")

    assert g["max_index"] == 4
    assert g["missing"] == [2]
    assert g["numbered"] == 3
    assert g["total"] == 3


def test_无序号不并入缺册而是单独计数(isolated, default_root):  # noqa: ARG001
    _epub(default_root, "一.epub", series="测试系列", series_index="1")
    _epub(default_root, "无序号.epub", series="测试系列")
    library.invalidate()

    g = library.series_gaps("测试系列")

    assert g["missing"] == [], "缺序号 ≠ 缺第 2 册"
    assert g["unnumbered"] == 1
    assert g["has_unnumbered"] is True
    assert g["max_index"] == 1


def test_非数字序号不参与数字补集(isolated, default_root):  # noqa: ARG001
    _epub(default_root, "一.epub", series="测试系列", series_index="1")
    _epub(default_root, "特典.epub", series="测试系列", series_index="特典")
    library.invalidate()

    g = library.series_gaps("测试系列")

    assert g["non_numeric"] == 1
    assert g["has_non_numeric"] is True
    assert g["missing"] == []
    assert g["max_index"] == 1


def test_空系列返回空缺口(isolated, default_root):  # noqa: ARG001
    library.invalidate()
    g = library.series_gaps("不存在的系列")
    assert g == {
        "missing": [], "max_index": 0, "numbered": 0, "unnumbered": 0,
        "has_unnumbered": False, "non_numeric": 0, "has_non_numeric": False, "total": 0,
    }


def test_接口把缺册注入系列详情(client, auth_headers, isolated, default_root):  # noqa: ARG001
    _epub(default_root, "一.epub", series="测试系列", series_index="1")
    _epub(default_root, "三.epub", series="测试系列", series_index="3")
    library.invalidate()

    r = client.get("/api/series/测试系列", headers=auth_headers)

    assert r.status_code == 200, r.text
    assert r.json()["gaps"]["missing"] == [2]
