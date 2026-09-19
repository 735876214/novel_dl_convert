"""命名规则占位符扩展（第 17 期）。

钉住两点：

1. **只加真实字段**：新增 token 全部取自 `library.books()` 里真实存在的键
   （year / publisher / language / series_index），取不到就**空串**，不编造。
2. **替换顺序先长后短**：`{series_index}` 必须排在 `{series}` / `{index}` 之前处理 ——
   `str.replace` 只看字面量，顺序错了会被短 token 抢先吃掉一半（这是最容易回归的点）。

同时覆盖安全底线：扩展后仍然拒绝路径分隔符（规则会被当文件名用）。
"""
import pathlib

import pytest

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


@pytest.fixture
def named_books(isolated, default_root):  # noqa: ARG001 —— 依赖 isolated 切目录
    _epub(default_root, "基地.epub", series="银河帝国", series_index="2",
          date="2012", publisher="江苏文艺出版社")
    _epub(default_root, "无名.epub")           # 没有系列 / 年份 / 出版社
    library.invalidate()
    return default_root


def test_新token取到真实值(named_books):
    plan = fileops.plan_pattern_rename("all", "{year}-{publisher}-{series}#{series_index}")
    rows = {i["old"]: i["new"] for i in plan["items"]}

    assert rows["基地.epub"] == "2012-江苏文艺出版社-银河帝国#2.epub"


def test_series_index不被短token抢先替换(named_books):
    """最容易回归的一处：`{series_index}` 必须先于 `{series}` / `{index}` 替换。"""
    plan = fileops.plan_pattern_rename("all", "{series_index}")
    rows = {i["old"]: i["new"] for i in plan["items"]}

    assert rows["基地.epub"] == "2.epub"
    assert "index" not in rows["基地.epub"]


def test_缺字段时输出空串(named_books):
    plan = fileops.plan_pattern_rename("all", "{year}{publisher}{language}")
    rows = {i["old"]: i["new"] for i in plan["items"]}

    # 没有年份 / 出版社 → 只剩语言；不会出现 None 或占位文字
    assert rows["无名.epub"] == "zh.epub"


def test_fields清单与前端一致(named_books):
    """`fields` 是前端提示的来源，必须是 9 个且顺序与 `PATTERN_FIELDS` 一致。"""
    plan = fileops.plan_pattern_rename("all", "{title}")
    assert plan["fields"] == list(fileops.PATTERN_FIELDS)
    assert len(plan["fields"]) == 9
    for token in ("{series_index}", "{year}", "{publisher}", "{language}"):
        assert token in plan["fields"]


def test_扩展后仍拒绝路径分隔符(named_books):
    with pytest.raises(ValueError):
        fileops.plan_pattern_rename("all", "{series}/{title}")
