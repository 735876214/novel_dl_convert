"""命名规则占位符展开（第 17 期起，第 28 期合并为唯一实现）。

钉住四点：

1. **只加真实字段**：新增 token 全部取自 `library.books()` 里真实存在的键
   （year / publisher / language / series_index），取不到就**空串**，不编造。
2. **替换顺序先长后短**：`{series_index}` 必须排在 `{series}` / `{index}` 之前处理 ——
   `str.replace` 只看字面量，顺序错了会被短 token 抢先吃掉一半（最容易回归的点）。
3. **`{index}` 是系列卷号**（第 28 期统一）：与 `publish` 的落盘口径一致，
   **不是**「本次范围流水号」—— 流水号会让文件名每处理一次就变。
4. **占位符清单是前后端契约**：`fileops.PATTERN_FIELDS` 与前端 `RENAME_TOKENS`
   必须逐字一致（展开只有 `fileops.fill_pattern` 一份实现，清单一处失配就是
   「页面提示了却填不出值」）。

同批覆盖安全底线：规则里的路径分隔符在**接口层**被拒（预览 400），而不是靠
`sanitize_stem` 静默清掉 —— 配置项被悄悄改写比报错更难查。
"""
from __future__ import annotations

import pathlib
import re

import pytest

from novelforge.core import epub_builder, fileops, library

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIELDS_TS = ROOT / "frontend" / "src" / "data" / "settingsFields.ts"


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


def _rows(pattern: str) -> dict:
    """按规则展开**书目里的每本书**：`源文件名 → 新名（不含扩展名）`。"""
    return {b["name"]: fileops.fill_pattern(pattern, b) for b in library.books()}


def test_新token取到真实值(named_books):
    rows = _rows("{year}-{publisher}-{series}#{series_index}")

    assert rows["基地.epub"] == "2012-江苏文艺出版社-银河帝国#2"


def test_series_index不被短token抢先替换(named_books):
    """最容易回归的一处：`{series_index}` 必须先于 `{series}` / `{index}` 替换。"""
    rows = _rows("{series_index}")

    assert rows["基地.epub"] == "2"
    assert "index" not in rows["基地.epub"]


def test_index是系列卷号而非流水号(named_books):
    """第 28 期口径：`{index}` = 系列卷号（两位补零），没有卷号的回退 `01`。

    ⚠️ 这里**不能**退化成「按书列表顺序 01/02」——出版侧用的是系列卷号，
    两处语义一旦不同，预览就会与实际落盘的文件名对不上。
    """
    rows = _rows("{index}")

    assert rows["基地.epub"] == "02"           # series_index=2
    assert rows["无名.epub"] == "01"           # 无卷号 → 01


def test_缺字段时输出空串(named_books):
    rows = _rows("{year}{publisher}{language}")

    # 没有年份 / 出版社 → 只剩语言；不会出现 None 或占位文字
    assert rows["无名.epub"] == "zh"


def test_占位符清单与前端一致(named_books):  # noqa: ARG001 —— 仅借用隔离目录
    """`PATTERN_FIELDS` 是唯一真值源，前端提示表必须与它逐字一致。"""
    assert len(fileops.PATTERN_FIELDS) == 10  # 第 53 期新增 {narrators}
    for token in ("{series_index}", "{year}", "{publisher}", "{language}", "{narrators}"):
        assert token in fileops.PATTERN_FIELDS


def test_narrators多值用逗号连接(named_books):  # noqa: ARG001 —— 仅借用隔离目录
    """第 53 期：``{narrators}`` 多值列表用「, 」连接；空列表 → 空串（不残留字面量）。"""
    b = {"title": "x", "narrators": ["张三", "李四"], "author": "某",
         "series": "", "series_index": "", "index": "01", "year": "",
         "publisher": "", "language": "", "ext": "m4b"}
    assert fileops.fill_pattern("{narrators}", b) == "张三, 李四"
    assert fileops.fill_pattern("{narrators}", {**b, "narrators": []}) == ""
    assert fileops.fill_pattern("{narrators} - {title}", {**b, "narrators": ["A"]}) == "A - x"


    # ⚠️ 先切到 `= [` 再切 `]`：类型注解 `{ token: string; desc: string }[]` 里也有 `]`，
    # 直接按 `]` 切会切在注解上，抓出空清单（这个测试自身踩过一次）。
    text = FIELDS_TS.read_text(encoding="utf-8")
    block = (text.split("export const RENAME_TOKENS", 1)[1]
             .split("= [", 1)[1].split("]", 1)[0])
    frontend = re.findall(r"token:\s*'([^']+)'", block)
    assert frontend == list(fileops.PATTERN_FIELDS)


def test_规则里的路径分隔符被接口拒绝(client, auth_headers, named_books):
    r = client.post("/api/naming/preview", headers=auth_headers,
                    json={"pattern": "{series}/{title}"})

    assert r.status_code == 400, r.text
    assert "规则里不能含" in r.text


def test_草稿留空时回退到已保存的规则(client, auth_headers, named_books):
    """``pattern`` 留空 ≠ 没有规则：回退该库的**生效值**（配置默认 ``{author} - {title}``）。

    这条同时是「设置页保存的规则照旧直接生效」的回归位：别把缺省当成 400。
    """
    r = client.post("/api/naming/preview", headers=auth_headers, json={})

    assert r.status_code == 200, r.text
    assert r.json()["pattern"] == "{author} - {title}"

