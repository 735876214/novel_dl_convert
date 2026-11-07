"""Komga 持续审计第 2 轮（第 274 期）：读不出来的书要报 `ERROR`。

这一轮扫了三个角度，两个零发现（**别重查**）：

- **排序 / 筛选 / 分页的组合**：`sort` 的七个变体（空 / `name,asc` / 大写 / 带空格的
  ` booksCount,desc ` / 不认识的字段 / `metadata.titleSort,desc` / `,asc`）都回 200 且
  顺序合理；同键重复请求**顺序稳定**；`condition.allOf` + `fullTextSearch` +
  `sort=metadata.numberSort,desc` + `page` **一起用**也正确（total=3、第 0 页给 #3#2、
  第 1 页给 #1）。
- **并发（系列标记已读 vs 单本续写）**：40 本的系列边标已读、边有一个线程持续写某本书的
  进度 ⇒ 结束时是**最后写入者胜**（locator=8 / 90%），没有被批量写吞掉。
- **软删除与「文件已被删但没重扫」**：软删除后视图立刻少一本（3 本）、系列计数 3→2、
  单本详情 / 文件 / 封面全 404；直接从磁盘删文件（不重扫）视图也立刻少一本、
  `/file` `/thumbnail` `/pages` 全 404 —— 索引读路径**本来就会过滤掉不存在的条目**。

一条发现：

**坏掉的书在客户端里报 `READY`**（`media.status`）。`status` 此前只由**格式**决定
（`READY` = 客户端有阅读器 / `UNSUPPORTED` = 没有），而「这本书读不读得出来」是**另一件事**：
一个解不开的 `.cbz` 早已被扫描记进索引（`issues=["unparsable"]`），DTO 却报
`READY` + `DIVINA` + `pagesCount=0` ⇒ 客户端显示「阅读」按钮，点进去 `/pages` 回 400 /
0 页 ⇒ 用户看到「加载失败」，以为是客户端或网络坏了。
Komga 的 `Media.Status` 本来就有 `ERROR` 这一档；判据**不需要开文件**（扫描期已记在索引里）。
"""
import io
import zipfile

import pytest

from novelforge import config
from novelforge.core import library


@pytest.fixture
def komga_on():
    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        yield {"X-API-Key": "test-key"}
    finally:
        config.save_overrides({})


def _cbz(path, pages: int = 2):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(pages):
            b = io.BytesIO()
            Image.new("RGB", (20, 30), (i * 20, 0, 0)).save(b, "PNG")
            z.writestr(f"{i + 1:03d}.png", b.getvalue())
    path.write_bytes(buf.getvalue())


@pytest.fixture
def good_and_broken(client, auth_headers, make_library, tmp_path):
    root = tmp_path / "L"
    root.mkdir(parents=True, exist_ok=True)
    make_library("L", "库", "mixed", root)     # mixed：`.txt` 也收得进来（要验 UNSUPPORTED）
    _cbz(root / "好" / "好 #1.cbz")
    bad = root / "坏" / "坏 #1.cbz"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"PK\x03\x04" + b"\x00" * 64)          # 解不开的 zip
    (root / "文.txt").write_text("第一章 开头\n正文\n", encoding="utf-8")
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    return root


def test_坏书报_ERROR_好书报_READY(client, komga_on, good_and_broken):   # noqa: ARG001
    got = {b["name"]: b["media"] for b in
           client.get("/api/v1/books?size=20", headers=komga_on).json()["content"]}
    print("\n" + str({k: v["status"] for k, v in got.items()}))
    bad = next(v for k, v in got.items() if k.startswith("坏"))
    assert bad["status"] == "ERROR", f"坏书的 status 是 {bad['status']}（客户端会显示「阅读」按钮）"
    good = next(v for k, v in got.items() if k.startswith("好"))
    assert good["status"] == "READY" and good["pagesCount"] == 2


def test_没有阅读器的格式仍是_UNSUPPORTED(client, komga_on, good_and_broken):  # noqa: ARG001
    """`ERROR` 只盖「客户端有阅读器、但这本书读不出来」那一档，不许波及 UNSUPPORTED。"""
    got = {b["name"]: b["media"] for b in
           client.get("/api/v1/books?size=20", headers=komga_on).json()["content"]}
    txt = next(v for k, v in got.items() if k.endswith(".txt"))
    assert txt["status"] == "UNSUPPORTED", txt["status"]
    assert txt["mediaProfile"] is None


def test_判据来自索引_不开文件(client, komga_on, good_and_broken, monkeypatch):  # noqa: ARG001
    """`issues` 是扫描期就记好的 ⇒ 列表端点**不该为此打开任何文件**。

    第 266 期刚把「列表 O(全书库)」收掉（每本开一次 zip）；为了这条状态又去开文件
    就把那笔账还回去了。这里用「把 `comics.pages` 打成会抛」来钉住它。
    """
    from novelforge.core import comics

    def boom(*a, **kw):
        raise AssertionError("列表端点不该为了状态去解归档")
    monkeypatch.setattr(comics, "pages", boom)
    r = client.get("/api/v1/books?size=20", headers=komga_on)
    assert r.status_code == 200
    assert {b["media"]["status"] for b in r.json()["content"]} <= {"READY", "ERROR", "UNSUPPORTED"}
