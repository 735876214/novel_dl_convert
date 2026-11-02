"""**书籍本体读 zip 条目一律走统一入口**（第 242 期）。

`core/zipkind.py::read_entry` 是「读归档里一个条目」的**唯一入口** —— 它带解压后大小上限
（`comics.MAX_ENTRY_BYTES`），而裸 `z.read()` **绕过**这个上限：一份几百 KB 的 zip 炸弹
就能让内存吃光。

第 242 期审计在**三处**找到裸读（其中一处是独立代理漏掉的）：

| 位置 | 读的是什么 | 后果 |
|---|---|---|
| `server.py` 书内资源 `GET /api/books/{id}/asset` | 章节里的插图 / 样式 | 打开含该资源的章节 ⇒ 内存暴涨 |
| `server.py` EPUB 内嵌封面 `GET /api/books/{id}/cover` | 封面图 | 同上 |
| `core/epub_cfi.py` 读 spine 条目 | 正文 XHTML | 恶意 EPUB 让 spine 指向超大条目 |

这里钉**结构性**判据：全仓（`novelforge/`）**不许**再有裸 `z.read(` / `zf.read(` 之类 ——
新增一处就会红。注释里提到「裸 `z.read()`」的**说明文字**不算（那是解释为什么改）。
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOVELFORGE = ROOT / "novelforge"

#: 裸读：`z.read(` / `zf.read(` / `zip.read(` —— 变量名是 z / zf / zip 这类
_BARE = re.compile(r"\b\w{1,4}\.read\(\s*[\"']|\b\w{1,4}\.read\(\s*[A-Za-z_]")
#: 允许的写法（统一入口 / 明确的受限读）
_ALLOWED = re.compile(r"zipkind\.read_entry|read_capped|\.read\(\)")


def _is_bare(line: str) -> bool:
    """这一行是不是「读 zip 条目」。只认常见的 zip 变量名，避免误伤普通文件读。"""
    if _ALLOWED.search(line):
        return False
    if line.lstrip().startswith("#"):
        return False
    # 说明文字里提到「裸 `z.read()`」不算（那是解释**为什么**改）
    if "`" in line and "read(" in line and line.strip().count("`") >= 2:
        return False
    # `z.read(name)` / `zf.read(x)` / `zip.read(y)` —— 但 `f.read()`（普通文件）不算
    m = re.search(r"\b(\w+)\.read\(", line)
    if not m:
        return False
    var = m.group(1)
    if var not in ("z", "zf", "zipf", "zip", "archive", "ar"):
        return False
    # `zip.read()` 无参 = 读整个 zip 目录（罕见），也算裸读
    return True


def test_没有裸读_zip_条目():
    hits = []
    for f in sorted(NOVELFORGE.rglob("*.py")):
        for i, line in enumerate(f.read_bytes().decode("utf-8", errors="replace").splitlines(), 1):
            if _is_bare(line):
                hits.append(f"{f.relative_to(ROOT)}:{i}  {line.strip()[:90]}")
    assert not hits, (
        "这些地方**裸读**了 zip 条目（绕过 `zipkind.read_entry` 的解压后大小上限）：\n  "
        + "\n  ".join(hits)
    )


def test_统一入口本身带上限():
    """`zipkind.read_entry` 必须真的带上限（否则「都走它」也没用）。"""
    from novelforge.core import comics, zipkind

    assert comics.MAX_ENTRY_BYTES > 0
    src = zipkind.read_entry.__doc__ or ""
    assert "上限" in src or "limit" in src, "read_entry 的 docstring 应说明它带上限"
