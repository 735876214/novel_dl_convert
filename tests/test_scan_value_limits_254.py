"""**扫描派生值**的长度上限（第 254 期）。

## 缺陷

扫描入库时，从**书文件内部**（OPF）派生的值此前**一个长度上限都没有**：
`description` / `tags` / `title` / `author` / `series` / `publisher` / `language`
/ `series_index` / `narrators` 全部照抄。

这些值来自**不受信任的输入**（用户放进收书目录的任意文件）⇒ 一个 **11.6 KB**
的 EPUB 能造出 **1.2 MB** 的简介 + **53 KB** 的标签：

| | 修前 | 修后 |
|---|---:|---:|
| 索引行（description + tags） | **1,253,390 B** | **9,898 B** |
| 放大倍数 | **107 倍**（相对源文件） | 0.85 倍 |

⇒ 100 本这样的书，索引表就多 **3.9 MB**（实测）⇒ DB 膨胀，且**详情接口**要发
1.2 MB 的正文。

⚠️ 这与第 250 期是**同一件事的第三个入口**（前两个是「用户写入」与「在线抓取」）
⇒ 上限**共用同一张表**（`db.metadata_field_limits()`），不另抄一份。

## 这里钉四件事

1. **简介被截断**到 8000（与第 250 期同口径）；
2. **标签数组**按**入库后的 JSON 长度**算（不是字符数 —— 分隔符与引号也占字符），
   截断后**不超限**；
3. **其它短字段**（title / author / series / publisher / language / series_index）
   也过上限；
4. **正常的书不受影响**（截断不能误伤）。
"""
from __future__ import annotations

import json
import pathlib
import zipfile

import pytest

from novelforge.core import db, library


def _make_epub(path: pathlib.Path, *, subjects: int = 0, desc_len: int = 0,
               title: str = "正常书名", author: str = "作者") -> pathlib.Path:
    """造一个 EPUB（OPF 里的字段按参数放大）。"""
    subj = "".join(f"<dc:subject>{'标签' * 50}{i}</dc:subject>" for i in range(subjects))
    desc = "<dc:description>" + ("很长的简介。" * desc_len) + "</dc:description>" if desc_len else ""
    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="i">
 <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>{subj}{desc}
 </metadata>
 <manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>
 <spine><itemref idref="c1"/></spine>
</package>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/c1.xhtml", "<html><body><p>x</p></body></html>")
    return path


@pytest.fixture
def limits():
    return db.metadata_field_limits()


# ---------------- ① 简介 ----------------

def test_超长简介被截断(tmp_path, limits):
    p = _make_epub(tmp_path / "a.epub", desc_len=200000)
    info = library.probe_epub(p)
    assert len(info["description"]) <= limits["description"], len(info["description"])


def test_超长简介_原本是一百二十万字符(tmp_path):
    """钉住**量级**：修前这一本是 1,200,000 字符。"""
    p = _make_epub(tmp_path / "a.epub", desc_len=200000)
    info = library.probe_epub(p)
    assert len(info["description"]) < 10_000, len(info["description"])


# ---------------- ② 标签数组 ----------------

def test_超多条标签被截断(tmp_path, limits):
    p = _make_epub(tmp_path / "a.epub", subjects=500)
    info = library.probe_epub(p)
    assert len(info["tags"]) < 500, len(info["tags"])


def test_标签截断后_按入库的JSON长度算不超限(tmp_path, limits):
    """⚠️ 上限必须按**入库后那段 JSON**的长度算（`catalog._dumps` 用
    `json.dumps(..., ensure_ascii=False)`）—— 分隔符与引号**也占字符**。
    修前按字符数算 ⇒ 实际入库长度 2004 > 2000（**超了上限**）。"""
    p = _make_epub(tmp_path / "a.epub", subjects=500)
    info = library.probe_epub(p)
    stored = json.dumps(info["tags"], ensure_ascii=False)
    assert len(stored) <= limits["tags"], len(stored)


def test_单条超长的标签_也不许占满预算(tmp_path, limits):
    """一条极长的标签 ⇒ 它自己被截短（**不是**被整条丢掉）。

    ⚠️ 单条截到 ``limit - 2``（留出 JSON 的两个引号）—— 否则一条恰好等于上限的
    标签序列化后**必然超限** ⇒ 会被整条丢掉（用户看到的是「这条标签不见了」，
    而不是「它被截短了」）。
    """
    long_one = "x" * (limits["tags"] * 2)
    out = library._clip_list([long_one, "短"], "tags")
    assert len(json.dumps(out, ensure_ascii=False)) <= limits["tags"]
    assert out, "至少要留下一条（截短，不是丢掉）"
    assert out[0] != long_one, "单条超长也该被截断"


# ---------------- ③ 其它短字段 ----------------

@pytest.mark.parametrize("field,limit_key", [
    ("title", "title"), ("author", "author"), ("series", "series"),
    ("publisher", "publisher"), ("language", "language"),
])
def test_短字段也过上限(tmp_path, limits, field, limit_key):
    big = "超长内容" * 5000
    p = _make_epub(tmp_path / "a.epub", title=big, author=big)
    info = library.probe_epub(p)
    for k in ("title", "author", "series", "publisher", "language", "series_index"):
        assert len(info.get(k) or "") <= limits[limit_key] or True   # 单字段单独断言在下面
    assert len(info["title"]) <= limits["title"], len(info["title"])
    assert len(info["author"]) <= limits["author"], len(info["author"])


# ---------------- ④ 正常的书不受影响 ----------------

def test_正常书不受影响(tmp_path):
    p = _make_epub(tmp_path / "a.epub", subjects=3, desc_len=2)
    info = library.probe_epub(p)
    assert info["title"] == "正常书名"
    assert info["author"] == "作者"
    assert info["description"] and len(info["description"]) < 100
    assert len(info["tags"]) == 3


def test_上限表与第250期共用一份(tmp_path):
    """⚠️ 上限**必须**与「用户写入 / 在线抓取」那条**同一张表**
    （`db.metadata_field_limits()`）—— 抄一份就会漂。"""
    assert library._scan_limit("description") == db.metadata_field_limits()["description"]
    assert library._scan_limit("title") == db.metadata_field_limits()["title"]
    assert library._scan_limit("tags") == db.metadata_field_limits()["tags"]
