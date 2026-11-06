"""Komga 兼容面的**协议行为**（第 266 期审计后立的契约）。

审计手段是「起真实例、造真 CBZ/EPUB/PDF、用客户端的三种凭据打 49 条 `/api/v1/*`」，
下面每条都对应一次实测过的错误行为，不是想象。

## 七条

1. **搜索被静默忽略**：`POST /books/list` 完全不读 `fullTextSearch`（全仓 grep 零命中）
   ⇒ 客户端搜「三体」拿回**整个书库**，用户以为搜索坏了。
2. **条件值不是字典就 500**：`_ko_read_filter` 一律 `(cl[k] or {}).get(...)`
   ⇒ `{"condition": {"title": "球状"}}` 直接 `AttributeError` ⇒ 整页「加载失败」，
   与这个函数「陌生条件一律忽略、宁可多返回」的口径正好相反。
3. **分页参数越界 → 422**：`Query(le=500)` / `Query(ge=0)` 把**可夹**的输入变成硬失败，
   而客户端解析的是分页壳，422 的 `{"detail": [...]}` 它读不懂。
4. **`/file` 的 Content-Type 恒为 octet-stream**：DTO 说 comicbook+zip、下载说未知二进制。
5. **`users/me.sharedLibraries` 不按可见性/范围过滤**：只读凭据只许看 A 库时，
   `/libraries` 回 [A]、`/users/me` 却回 [default, A, B] ⇒ 客户端点进 B 是空的。
6. **阅读进度页码不夹上界**：`pagesCount=4` 时 `PUT {"page": 999}` 落库 `locator=998`、
   `percent=100`（永久「已读」且阅读器指向不存在的页）。
7. **列表是 O(全书库)**：先给全库造 DTO 再切片 ⇒ 300 本的库每翻一页 300 次进度查询、
   每本 EPUB 开一次 zip、每本 PDF 开一次文件。
"""
import base64
import io
import pathlib
import zipfile

import pytest

from novelforge import config
from novelforge.core import db, library


def _basic(user: str, pin: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pin}".encode()).decode()}


def _cbz(path: pathlib.Path, pages: int = 3) -> pathlib.Path:
    """真 CBZ（zip 里放真 PNG）—— 假字节解不出页，页数会恒 0，量不出真行为。"""
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(pages):
            b = io.BytesIO()
            Image.new("RGB", (40 + i, 50), (10 * i, 0, 0)).save(b, "PNG")
            z.writestr(f"{i + 1:03d}.png", b.getvalue())
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture
def komga_on():
    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        yield {"X-API-Key": "test-key"}
    finally:
        config.save_overrides({})


@pytest.fixture
def comic_lib(client, auth_headers, make_library, tmp_path):
    root = tmp_path / "lib"
    root.mkdir(parents=True, exist_ok=True)
    make_library("klib", "漫画库", "comic", root)
    for name in ("三体 第1卷", "球状闪电 第1卷", "超新星纪元 第1卷"):
        _cbz(root / name / f"{name}.cbz")
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    return root


def _names(resp) -> set:
    assert resp.status_code == 200, resp.text
    return {b["name"] for b in resp.json()["content"]}


def test_服务端搜索真的会筛(client, komga_on, comic_lib):        # noqa: ARG001
    """`fullTextSearch` 不是摆设：搜「三体」只该回三体。"""
    r = client.post("/api/v1/books/list", json={"fullTextSearch": "三体"}, headers=komga_on)
    assert _names(r) == {"三体 第1卷.cbz"}
    # 空词 = 不筛（不是「筛掉全部」）
    r = client.post("/api/v1/books/list", json={"fullTextSearch": ""}, headers=komga_on)
    assert len(_names(r)) == 3
    # 作者 / 系列也搜得到（判据与 OPDS 搜索框同源：`library.matches_text`）
    r = client.post("/api/v1/books/list", json={"fullTextSearch": "球状"}, headers=komga_on)
    assert _names(r) == {"球状闪电 第1卷.cbz"}


@pytest.mark.parametrize("payload", [
    {"condition": {"title": "球状"}},
    {"condition": {"title": {"contains": "超新"}}},
    {"condition": {"title": {"operator": "IS", "value": "三体 第1卷"}}},
    {"condition": {"tag": "科幻"}},
    {"condition": {"readStatus": "READ"}},
    {"condition": {"libraryId": "klib"}},
    {"condition": "根本不是字典"},
    {"condition": {"allOf": "也不是列表"}},
])
def test_条件形状再怪也不许_500(client, komga_on, comic_lib, payload):   # noqa: ARG001
    """**口径**：陌生条件一律忽略、宁可多返回 —— 绝不能让客户端整页失败。

    此前只要某个**认识**的键用了别的形状（裸字符串）就 `AttributeError` ⇒ 500。
    """
    r = client.post("/api/v1/books/list", json=payload, headers=komga_on)
    assert r.status_code == 200, f"{payload} → {r.status_code} {r.text}"


def test_条件里的标题照样能筛(client, komga_on, comic_lib):      # noqa: ARG001
    """「不 500」不等于「不筛」：形状认得的仍然要真的过滤。"""
    r = client.post("/api/v1/books/list", json={"condition": {"title": "球状"}}, headers=komga_on)
    assert _names(r) == {"球状闪电 第1卷.cbz"}
    r = client.post("/api/v1/books/list",
                    json={"condition": {"title": {"contains": "超新"}}}, headers=komga_on)
    assert _names(r) == {"超新星纪元 第1卷.cbz"}


def test_分页参数越界要夹住而不是_422(client, komga_on, comic_lib):   # noqa: ARG001
    """客户端解析的是分页壳 —— 422 的 `{"detail": [...]}` 它读不懂，只会显示「加载失败」。"""
    for query, want_size in (("size=501", 500), ("size=1000", 500), ("size=0", 1)):
        r = client.get(f"/api/v1/books?{query}", headers=komga_on)
        assert r.status_code == 200, f"{query} → {r.status_code} {r.text}"
        assert r.json()["size"] == want_size
    r = client.get("/api/v1/books?page=-1", headers=komga_on)
    assert r.status_code == 200, f"page=-1 → {r.status_code} {r.text}"
    assert r.json()["number"] == 0, "负页码夹到第 0 页"
    # 非数字页码是**真的坏输入**（Spring 也回 400），只要不是 500 / 不是 200 里假装成功
    assert client.get("/api/v1/books?page=abc", headers=komga_on).status_code < 500


def test_下载的_Content_Type_与_DTO_一致(client, komga_on, comic_lib):   # noqa: ARG001
    """同一本书两处说法必须一致：DTO 说 comicbook+zip，下载就不能说未知二进制。"""
    b = client.get("/api/v1/books?size=1", headers=komga_on).json()["content"][0]
    assert b["media"]["mediaType"] == "application/vnd.comicbook+zip"
    r = client.get(f"/api/v1/books/{b['id']}/file", headers=komga_on)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.comicbook+zip")


def test_users_me_的库列表与_libraries_同源(client, komga_on, comic_lib):   # noqa: ARG001
    """`sharedLibraries` 是客户端画库列表的依据 —— 它必须与 `/libraries` 逐字一致。"""
    me = client.get("/api/v1/users/me", headers=komga_on).json()
    libs = client.get("/api/v1/libraries", headers=komga_on).json()
    assert [x["libraryId"] for x in me["sharedLibraries"]] == [x["id"] for x in libs]


def test_只读凭据的范围也管_users_me(client, auth_headers, make_library, tmp_path, komga_on):
    """只读凭据只许看 A 库 ⇒ `/libraries` 与 `/users/me` 都只能出现 A。"""
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)
    make_library("klib-a", "A 库", "comic", a)
    make_library("klib-b", "B 库", "comic", b)
    _cbz(a / "甲" / "甲 第1卷.cbz")
    _cbz(b / "乙" / "乙 第1卷.cbz")
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    r = client.post("/api/opds/credentials", headers=auth_headers,
                    json={"username": "reader1", "pin": "1234", "library_ids": ["klib-a"]})
    assert r.status_code == 200, r.text
    h = dict(_basic("reader1", "1234"))
    libs = {x["id"] for x in client.get("/api/v1/libraries", headers=h).json()}
    shared = {x["libraryId"] for x in
              client.get("/api/v1/users/me", headers=h).json()["sharedLibraries"]}
    assert libs == {"klib-a"}
    assert shared == libs, f"users/me 漏出了范围外的库：{shared - libs}"


def test_阅读进度页码不越界(client, komga_on, comic_lib):        # noqa: ARG001
    """越界页码不许落成「locator=998 / 已读」—— 那会让这本书永久显示读完，
    而本应用自己的阅读器打开会指向不存在的页。"""
    b = client.get("/api/v1/books?size=1", headers=komga_on).json()["content"][0]
    total = b["media"]["pagesCount"]
    assert total >= 3
    r = client.put(f"/api/v1/books/{b['id']}/read-progress", json={"page": 9999},
                   headers=komga_on)
    assert r.status_code == 204
    raw = db.get_progress(b["id"]) or {}
    assert int(raw.get("locator") or 0) <= total - 1, f"locator 越界：{raw}"
    assert float(raw.get("percent") or 0) <= 100.0
    # 正常页码照旧
    client.put(f"/api/v1/books/{b['id']}/read-progress", json={"page": 1}, headers=komga_on)
    assert int((db.get_progress(b["id"]) or {}).get("locator", -1)) == 0


def test_列表只给当前页造_DTO(client, auth_headers, make_library, tmp_path,
                             komga_on, monkeypatch):
    """回归点：一页 20 条却给全库 300 本造 DTO —— 每本一次进度查询、每本 EPUB 开一次 zip。"""
    root = tmp_path / "big"
    root.mkdir(parents=True, exist_ok=True)
    make_library("big", "大库", "comic", root)
    for i in range(120):
        _cbz(root / f"系列{i // 10}" / f"系列{i // 10} #{i % 10 + 1}.cbz", pages=1)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()

    calls = {"n": 0}
    real = db.get_progress

    def counted(bid, *a, **kw):
        calls["n"] += 1
        return real(bid, *a, **kw)
    monkeypatch.setattr(db, "get_progress", counted)

    r = client.get("/api/v1/books?size=20", headers=komga_on)
    assert r.status_code == 200
    assert r.json()["totalElements"] == 120, "总数仍是全量（客户端要拿它算页数）"
    assert len(r.json()["content"]) == 20
    # 逐本查库必须只发生在**这一页**上（`all_progress` 一次取全量，故这里是 0）
    assert calls["n"] == 0, f"列表端点又逐本查进度了（{calls['n']} 次）"

    r = client.get("/api/v1/series?size=20", headers=komga_on)
    assert r.status_code == 200
    assert calls["n"] == 0, f"系列列表又逐本查进度了（{calls['n']} 次）"
