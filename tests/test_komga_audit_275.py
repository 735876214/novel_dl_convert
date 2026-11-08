"""Komga 持续审计第 3 轮（第 275 期）：HEAD 只补了两条 / 跨端点 DTO 一致性。

这一轮扫了三个角度，两个零发现（**别重查**）：

- **同一本书在四个端点**（`/books/{id}` · `/books` · `/series/{id}/books` · `/books/list`）
  的 DTO **逐字段一致**：41 个叶子字段，0 处不同。
- **CBR/RAR 的读取面**：一个解不开的 `.cbr` 扫描期就记进 `issues=["unparsable"]` ⇒
  DTO `status=ERROR`（第 274 期那条修法**覆盖 rar 分支**，不是只管 zip）。

一条发现：**HEAD 只补了一半**。第 268 期给 `/file` 与 `/pages/{n}` 补了 HEAD（FastAPI 的
`@app.get` 不自动加），但**三条缩略图仍然是 404** —— 客户端「先 HEAD 看看有没有封面」会
被判成「没有封面」，列表里一片占位色。判据是「**能返回字节的出口都要能被 HEAD 探一下**」，
所以这次把 books / series / collections 三条缩略图补齐，并抽成 `_ko_head_like()`：
HEAD **直接调用 GET 的处理函数**再丢掉正文 ⇒ 状态码（200/404/413/503）与
`Content-Type` / `Content-Length` 天然与 GET 一致，不会分成两条会漂的路。
"""
import io
import json
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


def _cbz(path, pages: int = 3):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(pages):
            b = io.BytesIO()
            Image.new("RGB", (40, 60), (i * 20, 0, 0)).save(b, "PNG")
            z.writestr(f"{i + 1:03d}.png", b.getvalue())
    path.write_bytes(buf.getvalue())


@pytest.fixture
def one_lib(client, auth_headers, make_library, tmp_path):
    root = tmp_path / "L"
    root.mkdir(parents=True, exist_ok=True)
    make_library("L", "库", "comic", root)
    _cbz(root / "系列" / "系列 #1.cbz", pages=3)
    (root / "坏.cbr").write_bytes(b"Rar!\x1a\x07\x00" + bytes(64))     # 解不开的 RAR
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    return root


# ---------------------------------------------------------------- 1. HEAD 全覆盖

def test_三条缩略图的_HEAD_与_GET_同源(client, auth_headers, komga_on, one_lib):
    from novelforge.core import db

    bid = next(b["id"] for b in library.books() if b["name"].startswith("系列"))
    s = next(x for x in client.get("/api/v1/series?size=9", headers=komga_on).json()["content"]
             if x["name"] == "系列")
    cid = db.create_collection("夹")
    db.add_books_to_collection(cid, [bid])

    for ep in (f"/api/v1/books/{bid}/thumbnail",
               f"/api/v1/series/{s['id']}/thumbnail",
               f"/api/v1/collections/{cid}/thumbnail"):
        g = client.get(ep, headers=komga_on)
        h = client.head(ep, headers=komga_on)
        assert g.status_code == 200, ep
        assert h.status_code == 200, f"{ep} 的 HEAD 还是 {h.status_code}"
        assert h.headers.get("content-type") == g.headers.get("content-type")
        assert h.headers.get("content-length") == str(len(g.content)), ep


def test_没有封面时_HEAD_与_GET_一起_404(client, auth_headers, make_library,
                                  tmp_path, komga_on):
    """HEAD 不是「永远 200」——它必须和 GET 一起说「没有」。"""
    root = tmp_path / "T"
    root.mkdir(parents=True, exist_ok=True)
    make_library("T", "库", "ebook", root)
    p = root / "无封面.epub"
    from novelforge.core import epub_builder
    epub_builder.build_epub({"title": "无封面", "author": "a", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>x</p>"}], str(p))
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    bid = library.books()[0]["id"]
    g = client.get(f"/api/v1/books/{bid}/thumbnail", headers=komga_on)
    h = client.head(f"/api/v1/books/{bid}/thumbnail", headers=komga_on)
    assert g.status_code == h.status_code == 404, (g.status_code, h.status_code)


# ---------------------------------------------------------------- 2. 跨端点一致

def _flat(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        key = prefix + k
        if isinstance(v, dict):
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


def test_同一本书在四个端点的_DTO_逐字段一致(client, auth_headers, komga_on, one_lib):
    books = client.get("/api/v1/books?size=20", headers=komga_on).json()["content"]
    good = next(b for b in books if b["name"].startswith("系列"))
    bid = good["id"]
    s = next(x for x in client.get("/api/v1/series?size=9", headers=komga_on).json()["content"]
             if x["id"] == good["seriesId"])
    one = client.get(f"/api/v1/books/{bid}", headers=komga_on).json()
    via_series = next(b for b in client.get(
        f"/api/v1/series/{s['id']}/books?size=10", headers=komga_on).json()["content"]
        if b["id"] == bid)
    via_list = next(b for b in client.post("/api/v1/books/list", json={},
                                           headers=komga_on).json()["content"]
                    if b["id"] == bid)

    flats = {"单本": _flat(one), "全库": _flat(good),
             "系列书": _flat(via_series), "list": _flat(via_list)}
    keys = set().union(*(set(f) for f in flats.values()))
    assert len(keys) > 30, f"字段太少（{len(keys)}），比对没意义"
    diff = {}
    for k in keys:
        vals = {n: f.get(k, "<缺>") for n, f in flats.items()}
        if len({json.dumps(v, ensure_ascii=False) for v in vals.values()}) > 1:
            diff[k] = vals
    assert not diff, "同一本书在四个端点不一致：" + json.dumps(diff, ensure_ascii=False)[:400]


def test_坏RAR也报_ERROR(client, auth_headers, komga_on, one_lib):
    """第 274 期那条修法必须覆盖 rar 分支（判据在扫描期，与后端无关）。"""
    bad = next(b for b in client.get("/api/v1/books?size=20",
                                     headers=komga_on).json()["content"]
               if b["name"].endswith(".cbr"))
    assert bad["media"]["status"] == "ERROR", bad["media"]
    assert bad["media"]["pagesCount"] == 0
