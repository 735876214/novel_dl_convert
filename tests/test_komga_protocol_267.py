"""Komga 兼容面**第二轮**审计的契约（第 267 期）。

第一轮（第 266 期）修的是「看起来实现了其实没做」；这一轮换角度，专查
**跨字段一致性 / 单位 / 缓存 / 写开销**。下面每条都对应一次实测：

1. **同一份 DTO 里两个互相矛盾的百分比**：EPUB 的 `readProgress.page` 是**章节序号**，
   而 `media.pagesCount` 是**估算的文本页数**。20 章、pagesCount=883 的书读到第 10 章
   ⇒ `page=11`，客户端按 page/pagesCount 画进度条是 **1.2%**，而 `locator.progression`
   说 **50%**。
2. **卷号被压成整数 / 无卷号冒充第 1 卷**：`1.5` 卷与真正的第 1 卷撞号（原始书目里明明
   存着 `"1.5"`，`library._series_index_of` 特意保留了它）；3 本未编号的书全报 `number=1`。
3. **manifest 的 href 取不到**：给的是 `EPUB/c0000.xhtml`，服务端却没有对应路由 ⇒
   「advertise 了但服务不了」。
4. **认证过的媒体资源回了 `Cache-Control: public`** ⇒ 共享缓存可以把封面 / 漫画页
   交给没登录的人。
5. **系列级「标记已读」逐本写**：200 本 460 ms，2000 章到秒级（客户端超时会重试重写）。
6. **`oneshot` 用「成员数 == 1」判** ⇒ 真实的单本系列也被标成 one-shot。
7. **错误体不是 Komga 的形状**：客户端读 `error.message` 时是空白。
"""
import io
import pathlib
import zipfile

import pytest

from novelforge import config
from novelforge.core import db, epub_builder, fileops, library


@pytest.fixture
def komga_on():
    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        yield {"X-API-Key": "test-key"}
    finally:
        config.save_overrides({})


def _epub(path: pathlib.Path, title: str, body: str = "<p>正文</p>",
          series: str = "", index: str = "") -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": title, "author": "作者", "language": "zh"},
                            [{"title": f"第{i + 1}章", "body_html": body} for i in range(20)],
                            str(path))
    if series:
        assert fileops.patch_epub_meta(path, {"series": series, "series_index": index})
    return path


def _cbz(path: pathlib.Path, pages: int = 2) -> pathlib.Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(pages):
            b = io.BytesIO()
            Image.new("RGB", (40, 50), (i * 20, 0, 0)).save(b, "PNG")
            z.writestr(f"{i + 1:03d}.png", b.getvalue())
    path.write_bytes(buf.getvalue())
    return path


def _scan(client, auth_headers):
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()


# ---------------------------------------------------------------- 1. 单位一致

def test_epub的page与pagesCount是同一把尺子(client, auth_headers, make_library,
                                        tmp_path, komga_on):
    """读到 50% 就该是「半本书」，不能是「1.2%」。"""
    root = tmp_path / "E"
    big = "<p>" + "正文内容。" * 6000 + "</p>"
    _epub(root / "长书.epub", "长书", big)
    make_library("E", "书库", "ebook", root)
    _scan(client, auth_headers)

    b = client.get("/api/v1/books?size=5", headers=komga_on).json()["content"][0]
    print(f"\npagesCount={b['media']['pagesCount']}")
    # 未读 ⇒ 不给 page（Komga 这一档是 null），只给 locator
    assert "page" not in b["readProgress"], "未读的书不该报一个假页码"

    spine = library._spine(library.abs_path(library.by_id(b["id"])))
    client.put(f"/api/v1/books/{b['id']}/read-progress",
               json={"locator": {"href": spine[len(spine) // 2],
                                 "locations": {"progression": 0.5}}}, headers=komga_on)
    after = client.get(f"/api/v1/books/{b['id']}", headers=komga_on).json()
    total = after["media"]["pagesCount"]
    page = after["readProgress"].get("page")
    assert total > 10 and page is not None
    ratio = page / total
    assert abs(ratio - 0.5) < 0.05, f"page={page} / pagesCount={total} = {ratio:.1%}，应≈50%"


# ---------------------------------------------------------------- 2. 卷号保真

def test_小数卷号不许与整数卷号撞号(client, auth_headers, make_library, tmp_path, komga_on):
    root = tmp_path / "S"
    for i, name in ((1, "第1卷"), (1.5, "第1.5卷"), (2, "第2卷")):
        _epub(root / "某系列" / f"{name}.epub", name, series="某系列", index=str(i))
    make_library("S", "书库", "ebook", root)
    _scan(client, auth_headers)

    s = client.get("/api/v1/series?size=5", headers=komga_on).json()["content"][0]
    bs = client.get(f"/api/v1/series/{s['id']}/books", headers=komga_on).json()["content"]
    got = {b["metadata"]["number"]: b["metadata"]["numberSort"] for b in bs}
    print(f"\n卷号 -> {got}")
    assert got.get("1.5") == 1.5, "1.5 卷被压成整数了（会与真正的第 1 卷撞号）"
    assert got.get("1") == 1.0 and got.get("2") == 2.0


def test_无卷号不许冒充第一卷(client, auth_headers, make_library, tmp_path, komga_on):
    root = tmp_path / "N"
    for nm in ("甲", "乙", "丙"):
        _cbz(root / "无编号系列" / f"{nm}.cbz")
    make_library("N", "库", "comic", root)
    _scan(client, auth_headers)

    s = client.get("/api/v1/series?size=5", headers=komga_on).json()["content"][0]
    bs = client.get(f"/api/v1/series/{s['id']}/books", headers=komga_on).json()["content"]
    print(f"\n{[b['metadata']['number'] for b in bs]}")
    assert all(b["metadata"]["number"] == "" for b in bs), "无卷号被写成了具体卷号"
    assert all(b["metadata"]["numberSort"] == 0.0 for b in bs)


# ---------------------------------------------------------------- 6. oneshot

def test_oneshot_只给没有系列元数据的书(client, auth_headers, make_library,
                                   tmp_path, komga_on):
    root = tmp_path / "O"
    _epub(root / "独立" / "独立.epub", "独立")                      # 没系列
    _epub(root / "真系列" / "真系列 第1卷.epub", "第1卷",
          series="真系列", index="1")                              # 真系列、只有一本
    make_library("O", "书库", "ebook", root)
    _scan(client, auth_headers)

    got = {s["name"]: s["oneshot"]
           for s in client.get("/api/v1/series?size=20", headers=komga_on).json()["content"]}
    print(f"\noneshot -> {got}")
    assert got.get("独立") is True, "没有系列的书应标 oneshot"
    assert got.get("真系列") is False, "真实的单本系列不该标 oneshot（那会藏掉系列层级）"


# ---------------------------------------------------------------- 3. manifest 可取

def test_manifest_里的_href_真的取得到(client, auth_headers, make_library,
                                  tmp_path, komga_on):
    root = tmp_path / "M"
    _epub(root / "M" / "M #1.epub", "M #1", series="M", index="1")
    make_library("M", "书库", "ebook", root)
    _scan(client, auth_headers)

    b = client.get("/api/v1/books?size=5", headers=komga_on).json()["content"][0]
    man = client.get(f"/api/v1/books/{b['id']}/manifest", headers=komga_on).json()
    hrefs = [x["href"] for x in man.get("readingOrder") or []]
    assert hrefs, "manifest 没有 readingOrder"
    for href in hrefs[:3]:
        r = client.get(f"/api/v1/books/{b['id']}/resource/{href}", headers=komga_on)
        assert r.status_code == 200, f"manifest 指了 {href} 却取不到（{r.status_code}）"
        assert r.headers.get("x-content-type-options") == "nosniff"
    # 不可见的书连资源也取不到
    assert client.get(f"/api/v1/books/{b['id']}/resource/../../etc/passwd",
                      headers=komga_on).status_code in (403, 404)


# ---------------------------------------------------------------- 4. 缓存口径

def test_认证过的媒体资源是_private_缓存(client, auth_headers, make_library,
                                  tmp_path, komga_on):
    """`public` 会让共享缓存把受保护的封面 / 漫画页交给没登录的人。"""
    root = tmp_path / "C"
    _cbz(root / "S" / "S #1.cbz")
    _cbz(root / "S" / "S #2.cbz")
    make_library("C", "库C", "comic", root)
    _scan(client, auth_headers)
    s = client.get("/api/v1/series?size=5", headers=komga_on).json()["content"][0]
    b = client.get(f"/api/v1/series/{s['id']}/books", headers=komga_on).json()["content"][0]
    for ep in (f"/api/v1/books/{b['id']}/thumbnail", f"/api/v1/series/{s['id']}/thumbnail",
               f"/api/v1/books/{b['id']}/pages/1"):
        cc = client.get(ep, headers=komga_on).headers.get("cache-control", "")
        assert cc.startswith("private"), f"{ep} 的 Cache-Control 是 {cc!r}"


# ---------------------------------------------------------------- 5. 批量写

def test_系列标记已读走批量写(client, auth_headers, make_library, tmp_path,
                        komga_on, monkeypatch):
    """逐本写 = 每条一次提交：200 本 460 ms，2000 章到秒级（客户端超时会重试重写）。"""
    root = tmp_path / "R"
    for i in range(30):
        _cbz(root / "大系列" / f"大系列 #{i + 1}.cbz", pages=1)
    make_library("R", "库R", "comic", root)
    _scan(client, auth_headers)

    per_book = {"n": 0}
    real_one = db.set_progress

    def counted(*a, **kw):
        per_book["n"] += 1
        return real_one(*a, **kw)
    monkeypatch.setattr(db, "set_progress", counted)

    s = client.get("/api/v1/series?size=5", headers=komga_on).json()["content"][0]
    r = client.post(f"/api/v1/series/{s['id']}/read-progress", headers=komga_on)
    assert r.status_code == 204
    assert per_book["n"] == 0, f"又逐本写了（{per_book['n']} 次）"
    # 结果仍然正确：整系列 100%
    bs = client.get(f"/api/v1/series/{s['id']}/books?size=100",
                    headers=komga_on).json()["content"]
    assert all(b["readProgress"]["completed"] for b in bs)
    # 再标未读，同样批量
    assert client.delete(f"/api/v1/series/{s['id']}/read-progress",
                         headers=komga_on).status_code == 204
    bs = client.get(f"/api/v1/series/{s['id']}/books?size=100",
                    headers=komga_on).json()["content"]
    assert not any(b["readProgress"]["completed"] for b in bs)


# ---------------------------------------------------------------- 7. 错误体形状

def test_komga的错误体带_spring_的键(client, auth_headers, komga_on):
    r = client.get("/api/v1/books/根本没有这个id", headers=komga_on)
    assert r.status_code == 404
    body = r.json()
    print(f"\n/api/v1 404 -> {body}")
    for k in ("detail", "status", "error", "message", "path"):
        assert k in body, f"缺 {k}（客户端读 message，缺了就显示空白）"
    assert body["status"] == 404 and body["message"] == body["detail"]
    assert body["path"].startswith("/api/v1/")


def test_应用自己的错误体不被改(client, auth_headers):
    """协议面的兼容性修补**不许**动应用自己的错误契约（前端与几十个用例读 `detail`）。"""
    r = client.get("/api/books/根本没有这个id", headers=auth_headers)
    assert r.status_code == 404
    assert set(r.json()) == {"detail"}, r.json()


def test_401_的_WWW_Authenticate_没被吞掉(client):
    r = client.get("/api/v1/libraries")
    assert r.status_code in (401, 404)
    if r.status_code == 401:
        assert r.headers.get("www-authenticate", "").startswith("Basic")
