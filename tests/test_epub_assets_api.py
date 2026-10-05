"""第 76 期：书内资源的两个端点 —— `/asset`（字节）与 `/epub-css`（书内样式）。

守的是「插图能不能真的显示出来」这条链路的**最后一段**：

- **`/asset` 的鉴权**：`<img>` 是浏览器原生请求、带不了 `Authorization` 头，只能走
  `?token=`。改造前正文里的 URL **不含令牌** ⇒ 整本书的插图**全是 401**（一个字都不显示，
  也不报错 —— 页面上只是空位 / 破图）；
- **`/asset` 取文件必须用书目里的 `path`**：多文件夹的库里用 `root_of(b) / b["name"]`
  会指到**另一个根**，表现为「这本书的插图全是 404」；
- **令牌只在响应期注入**：正文与书内样式里带令牌，而**被缓存的那一份不带** ——
  写进缓存的话，令牌一过期整章插图就全 401，而且缓存还新鲜着、不会重建。
"""
import pathlib

from novelforge import config
from novelforge.core import db, library

#: 带样式表链接的章节（`chapter_assets` 从 OPF manifest 取表，head 里的内联 `<style>`
#: 另有一路扫描 —— 这条用例把两路都覆盖到）
CHAPTER_WITH_STYLE = (
    '<html><head><title>一</title>'
    '<link rel="stylesheet" href="../Styles/style.css"/>'
    '<style>em{background:url(../Images/pic.png)}</style>'
    '</head><body><p>正文</p><img src="../Images/pic.png"/></body></html>'
)


def _token(auth_headers: dict) -> str:
    return auth_headers["Authorization"][7:]


def _setup(client, auth_headers, make_library, make_epub, *,
           root_name: str = "assets", lid: str = "lib-assets"):
    """建一个库、放一本带插图的 EPUB，返回 `(库根, epub 路径, 书 id)`。"""
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / root_name
    make_library(lid, "素材库", "ebook", root)
    ep = make_epub(root, "插图.epub")
    cards = client.get("/api/books", headers=auth_headers).json()["items"]
    bid = next(b["id"] for b in cards if b["name"] == "插图.epub")
    return root, ep, bid


# ---------------------------------------------------------------------------
# `/asset`：鉴权
# ---------------------------------------------------------------------------

def test_asset没有令牌一律401(client, auth_headers, make_library, make_epub):
    _root, _ep, bid = _setup(client, auth_headers, make_library, make_epub)
    r = client.get(f"/api/books/{bid}/asset", params={"p": "OEBPS/Images/pic.png"})
    assert r.status_code == 401, r.text


def test_asset带query令牌能取到字节(client, auth_headers, make_library, make_epub):
    _root, _ep, bid = _setup(client, auth_headers, make_library, make_epub)
    r = client.get(f"/api/books/{bid}/asset",
                   params={"p": "OEBPS/Images/pic.png", "token": _token(auth_headers)})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG"), r.content[:16]


def test_asset把未折叠的路径归一后命中(client, auth_headers, make_library, make_epub):
    """第 76 期之前**缓存下来的**正文里带的是未折叠的 `OEBPS/Text/../Images/…` ——
    归一化后仍要能取到，否则老正文会一直 404（而正文是缓存的，不会自己重建）。"""
    _root, _ep, bid = _setup(client, auth_headers, make_library, make_epub)
    r = client.get(f"/api/books/{bid}/asset",
                   params={"p": "OEBPS/Text/../Images/pic.png", "token": _token(auth_headers)})
    assert r.status_code == 200, r.text


def test_asset缺条目404(client, auth_headers, make_library, make_epub):
    _root, _ep, bid = _setup(client, auth_headers, make_library, make_epub)
    r = client.get(f"/api/books/{bid}/asset",
                   params={"p": "OEBPS/nope.png", "token": _token(auth_headers)})
    assert r.status_code == 404, r.text


def test_资产端点不吞别的书(client, auth_headers, make_library, make_epub):
    """A 书的资源请求落到 B 书上是拿错文件 —— 用 `bid` 定位，别用文件名去猜。"""
    _root, _ep, bid = _setup(client, auth_headers, make_library, make_epub)
    r = client.get("/api/books/不存在/asset",
                   params={"p": "OEBPS/Images/pic.png", "token": _token(auth_headers)})
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# `/asset`：多来源文件夹（必须用书目里的 path）
# ---------------------------------------------------------------------------

def test_多文件夹库也能取对文件(client, auth_headers, make_epub):
    """书在**第二个**来源文件夹里时，`root_of(b) / b["name"]`（改造前的写法）会指到
    第一个根 —— 那里根本没有这个文件，于是这本书的插图**全是 404**。"""
    first = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "multi-a"
    second = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "multi-b"
    first.mkdir(parents=True, exist_ok=True)
    second.mkdir(parents=True, exist_ok=True)
    db.create_library("lib-multi", "双根库", "ebook",
                      source_dirs=[str(first), str(second)])
    library.invalidate()
    make_epub(second, "双根.epub")

    cards = client.get("/api/books", headers=auth_headers).json()["items"]
    bid = next(b["id"] for b in cards if b["name"] == "双根.epub")
    r = client.get(f"/api/books/{bid}/asset",
                   params={"p": "OEBPS/Images/pic.png", "token": _token(auth_headers)})
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"\x89PNG")


# ---------------------------------------------------------------------------
# 令牌只在响应期注入（缓存那份不带）
# ---------------------------------------------------------------------------

def test_章节正文的插图URL带令牌_而缓存那份不带(client, auth_headers, make_library, make_epub):
    tok = _token(auth_headers)
    _root, ep, bid = _setup(client, auth_headers, make_library, make_epub)

    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 200, r.text
    html = r.json()["html"]
    # `../Images/pic.png` 已折叠，且 URL 自带令牌 —— 这一条就是「插图能不能出来」的分水岭
    assert f"/asset?p=OEBPS/Images/pic.png&token={tok}" in html, html

    # ⚠️ 生产者产出的那一份（= 会被写进缓存的）**不含令牌**：令牌过期后缓存里那份
    # 仍然「新鲜」，带着旧令牌就永远是 401
    raw = library.chapter_html(ep, 0, bid)["html"]
    assert "/asset?p=" in raw and "token=" not in raw, raw


def test_书内样式端点返回样式且URL带令牌(client, auth_headers, make_library, make_epub):
    tok = _token(auth_headers)
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "styles"
    make_library("lib-styles", "样式库", "ebook", root)
    ep = make_epub(root, "带样式.epub", chapter=CHAPTER_WITH_STYLE,
                   css='p{background:url("../Images/pic.png")}')
    cards = client.get("/api/books", headers=auth_headers).json()["items"]
    bid = next(b["id"] for b in cards if b["name"] == "带样式.epub")

    r = client.get(f"/api/books/{bid}/epub-css", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sheets"] == ["OEBPS/Styles/style.css"], body
    assert body["fixed_layout"] is False
    # 样式里的字体 / 背景图同样是浏览器原生请求 ⇒ 也得带令牌
    assert f"url(/api/books/{bid}/asset?p=OEBPS/Images/pic.png&token={tok})" in body["css"], body["css"]

    # ⚠️ 生产者（会被缓存的那一份）里没有令牌
    assert "token=" not in library.chapter_assets(ep, bid)["css"]


def test_书内样式端点走Bearer_不接受query令牌(client, auth_headers, make_library, make_epub):
    """它**不在** `_MEDIA_TOKEN_PATHS` 里（是前端 `fetch` 取的，不是浏览器原生请求）——
    这条断言防的是「顺手把它也加进白名单」，那会白白扩大 query 令牌的面。"""
    _root, _ep, bid = _setup(client, auth_headers, make_library, make_epub)
    assert client.get(f"/api/books/{bid}/epub-css",
                      params={"token": _token(auth_headers)}).status_code == 401


def test_书内样式端点未知书404(client, auth_headers):
    assert client.get("/api/books/不存在/epub-css", headers=auth_headers).status_code == 404
