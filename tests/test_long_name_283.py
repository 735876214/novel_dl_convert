"""由**元数据生成**的路径片段必须压进文件系统的字节上限（第 283 期）。

审计发现：副本名来自书名 / 作者 / 系列（书名本身允许 200 **字符**），而文件系统按
**UTF-8 字节**限制单段名（ext4 / xfs / btrfs / APFS / NTFS 常见 255 ⇒ 中文约 85 字）。
实测（`publish.relpath_for`，120 汉字书名）：

```
修前：生成名 = 超长书名×30.epub       字节数 = 365   ← 在 Linux 上必然 ENAMETOOLONG
修后：生成名 = 超长书名×20-98c00a9d.epub  字节数 = 254
```

修前 `publish()` 把这句 OS 错误原样当 `error` 返回（`[Errno 36] File name too long`），
出版 / 入库 / 改名都失败，而命名预览照常显示那个写不出来的名字。判据常量
`NAME_MAX_BYTES`（`core/filename.py`）早就有，但只用在**进来的**路径上。

截断规则：保留前 `limit-9` 字节（按 UTF-8 边界切）+ `-<sha1 前 8 位>` —— 确定且不撞名。
"""
import pathlib

from novelforge.core import db, epub_builder, filename, komga, library, publish


def _bytes(s: str) -> int:
    return len(s.encode("utf-8"))


def test_fit_segment_截断到字节上限且有稳定后缀():
    assert filename.fit_segment("短名字") == "短名字"
    long_zh = "书" * 120                      # 360 字节
    got = filename.fit_segment(long_zh)
    assert _bytes(got) <= filename.NAME_MAX_BYTES
    assert got != long_zh and got.endswith(got[-9:]) and got[-9] == "-"
    assert got == filename.fit_segment(long_zh), "必须确定（同一输入同一结果）"
    assert got.encode("utf-8").decode("utf-8") == got, "不许切出半个 UTF-8 字"
    other = filename.fit_segment("书" * 119 + "名")
    assert other != got, "不同长名截断后不许撞成同一个"


def test_平铺布局的名字不超单段():
    rel = komga.relpath_for("书" * 120, "epub", "", "", "flat")
    assert _bytes(rel) <= filename.NAME_MAX_BYTES, _bytes(rel)
    assert rel.endswith(".epub")
    assert rel.startswith("书书"), "应保留开头的书名"


def test_komga布局的系列目录与文件名都不超单段():
    rel = komga.relpath_for("书" * 120, "epub", "系" * 120, "1", "komga")
    seg, name = rel.split("/")
    assert _bytes(seg) <= filename.NAME_MAX_BYTES
    assert _bytes(name) <= filename.NAME_MAX_BYTES
    assert name.endswith(" #1.epub")
    assert name.startswith(seg), "目录名必须是文件名的前缀（Komga 靠它解析系列）"


def test_目录型条目的名字不超单段():
    rel = komga.relpath_for_dir("书" * 120, "系" * 120, "2", "komga")
    seg, name = rel.split("/")
    assert _bytes(seg) <= filename.NAME_MAX_BYTES
    assert _bytes(name) <= filename.NAME_MAX_BYTES
    assert name.endswith(" #2")
    assert name.startswith(seg)


def test_超长书名的书真的出版得出来(isolated, make_library, tmp_path):
    root = tmp_path / "lib"
    out = tmp_path / "out"
    p = root / "长名书.epub"
    p.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": "超长书名" * 30, "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>x</p>"}], str(p))
    make_library("L", "库", "ebook", root)
    db.update_library("L", publish_path=str(out))
    library.invalidate()

    book = library.books("L")[0]
    cfg = {"naming": {"pattern": "{title}", "scope": "all"},
           "output": {"layout": "flat"}}
    rel = publish.relpath_for(book, cfg)
    assert _bytes(rel) <= filename.NAME_MAX_BYTES

    res = publish.publish(book, cfg=cfg)
    assert res["ok"] is True, res["error"]
    dst = pathlib.Path(res["path"])
    assert dst.is_file()
    assert _bytes(dst.name) <= filename.NAME_MAX_BYTES
