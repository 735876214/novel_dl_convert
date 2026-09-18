"""OPDS 按库暴露（第 14 期）。

钉住四条口径：

1. **库维度只在路径上** —— 客户端订阅的是固定 URL，所以是 `/opds/lib/<id>/...`，
   不是查询参数（多数客户端连自定义头都不支持，更不会替你带 `?library=`）；
2. **默认零变化** —— 既有 `/opds`、`/opds/all` 的输出不受影响，只有**可见库多于一个**
   时根导航才多出「按书库」入口（单库部署连这个入口都不加）；
3. **不可见与不存在一律 404** —— 关掉暴露的库不给客户端「这里有个库只是不给你看」的暗示；
4. **单库取书只在本库内找** —— 跨库同名时 `library.by_id()` 会抛 `BookIdConflict`，
   单库路由走「库内查找」，所以不属于该库的书一律 404。

全程离线：不触任何外部网络，OPDS 开关用配置覆盖层（用完还原），不写真实配置文件。
"""
import base64
import pathlib
import xml.etree.ElementTree as ET

import pytest

from novelforge import config
from novelforge.core import library

NS = "{http://www.w3.org/2005/Atom}"


def _basic(user: str = "admin", pin: str = "test1234") -> dict:
    """OPDS 走 HTTP Basic（既有 `auth_headers` 是 Bearer，这里不能复用）。"""
    token = base64.b64encode(f"{user}:{pin}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _entries(xml_text: str) -> list:
    return ET.fromstring(xml_text).findall(f"{NS}entry")


def _titles(xml_text: str) -> list:
    return [str(e.findtext(f"{NS}title") or "") for e in _entries(xml_text)]


def _hrefs(xml_text: str) -> list:
    out = []
    for e in _entries(xml_text):
        out.extend(str(l.get("href") or "") for l in e.findall(f"{NS}link"))
    return out


def _put(root, name: str) -> pathlib.Path:
    """占位书文件（扫描只按扩展名收书，不需要真实 EPUB）。"""
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"EPUB")
    return p


def _new_library(client, headers, name: str, root, ltype: str = "ebook") -> dict:
    r = client.post("/api/libraries", headers=headers,
                    json={"name": name, "type": ltype, "mode": "inplace",
                          "root_path": str(root)})
    assert r.status_code == 200, r.text
    library.invalidate()
    return r.json()["library"]


@pytest.fixture
def enable_opds_cfg():
    """同上，但走配置覆盖层（`config.save_overrides`）——与接口冒烟既有写法一致。"""
    config.save_overrides({"opds": {"enabled": True}})
    try:
        yield _basic()
    finally:
        config.save_overrides({})


# ---------------------------------------------------------------------------
# 开关与鉴权
# ---------------------------------------------------------------------------

def test_OPDS关闭时单库地址404(client):
    """未启用时，库导航与单库地址都不该暴露（既有全局地址同理）。"""
    assert client.get("/opds/libraries", headers=_basic()).status_code == 404
    assert client.get("/opds/lib/default", headers=_basic()).status_code == 404


def test_OPDS单库地址需要Basic认证(client, enable_opds_cfg):
    """客户端只发 Basic；不带凭据一律 401（凭据错也是 401，不区分——少给信息）。"""
    r = client.get("/opds/lib/default")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").startswith("Basic")


# ---------------------------------------------------------------------------
# 书库导航
# ---------------------------------------------------------------------------

def test_书库导航列出全部可见库(client, auth_headers, enable_opds_cfg, default_root):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    lib_b = _new_library(client, auth_headers, "comics", src / "comics", "comic")
    _put(default_root, "默认库的书.epub")
    _put(src / "comics", "漫画库的一本.cbz")
    library.invalidate()

    r = client.get("/opds/libraries", headers=enable_opds_cfg)
    assert r.status_code == 200, r.text
    titles = _titles(r.text)
    assert len(titles) == 2
    assert any("/opds/lib/" + lid in h for h in _hrefs(r.text)
               for lid in ("default", lib_b["id"]))


def test_单库才多出书库入口(client, auth_headers, enable_opds_cfg, default_root):
    """可见库 > 1 才加「按书库」入口：单库部署的根导航必须与加它之前逐字节一致。"""
    _put(default_root, "a.epub")
    library.invalidate()

    before = client.get("/opds", headers=enable_opds_cfg).text
    assert "按书库" not in before

    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    _new_library(client, auth_headers, "comics", src / "comics", "comic")
    _put(src / "comics", "b.cbz")
    library.invalidate()

    after = client.get("/opds", headers=enable_opds_cfg).text
    assert "按书库" in after


# ---------------------------------------------------------------------------
# 单库 feed
# ---------------------------------------------------------------------------

def test_单库目录一整套(client, auth_headers, enable_opds_cfg, default_root):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    lib_b = _new_library(client, auth_headers, "comics", src / "comics", "comic")
    _put(default_root, "甲.epub")
    _put(src / "comics", "乙.cbz")
    library.invalidate()
    lid = lib_b["id"]
    prefix = f"/opds/lib/{lid}"

    for path in ("all", "recent", "authors", "series", "tags",
                 "search?q=%E4%B9%99"):
        r = client.get(f"{prefix}/{path}", headers=enable_opds_cfg)
        assert r.status_code == 200, f"{path} → {r.status_code}"

    # 单库 feed 里的条目链接必须留在库内（漏改一处就会在翻页时跳回全局）
    feed = client.get(f"{prefix}/all", headers=enable_opds_cfg).text
    assert feed.count(prefix) >= 1
    assert "/opds/lib/" in feed
    # 漫画库里只有那一本
    assert len(_entries(feed)) == 1


def test_单库搜索只在本库内(client, auth_headers, enable_opds_cfg, default_root):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    lib_b = _new_library(client, auth_headers, "comics", src / "comics", "comic")
    _put(default_root, "共有书名.epub")
    _put(src / "comics", "共有书名.cbz")
    library.invalidate()

    term = "共有书名"
    hits = _entries(client.get(f"/opds/lib/{lib_b['id']}/search",
                               params={"q": term}, headers=enable_opds_cfg).text)
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# 可见性
# ---------------------------------------------------------------------------

def test_关掉暴露后单库地址404(client, auth_headers, enable_opds_cfg, default_root):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    lib_b = _new_library(client, auth_headers, "comics", src / "comics", "comic")
    _put(src / "comics", "b.cbz")
    library.invalidate()

    r = client.put(f"/api/libraries/{lib_b['id']}/settings", headers=auth_headers,
                   json={"opds.expose": False})
    assert r.status_code == 200, r.text

    # 直连 404，且不出现在书库导航里
    assert client.get(f"/opds/lib/{lib_b['id']}", headers=enable_opds_cfg).status_code == 404
    nav = client.get("/opds/libraries", headers=enable_opds_cfg)
    assert nav.status_code == 200
    assert lib_b["id"] not in nav.text
    # 默认库不受影响
    assert client.get("/opds/lib/default", headers=enable_opds_cfg).status_code == 200


def test_不存在的库404(client, auth_headers, enable_opds_cfg):
    assert client.get("/opds/lib/没有这个库", headers=enable_opds_cfg).status_code == 404


# ---------------------------------------------------------------------------
# 单库取书
# ---------------------------------------------------------------------------

def test_单库取书越库404(client, auth_headers, enable_opds_cfg, default_root):
    """详情 / 封面 / 下载都只能在**本库内**找到书，别的库的书一律 404。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    lib_b = _new_library(client, auth_headers, "comics", src / "comics", "comic")
    _put(default_root, "默认库的书.epub")
    _put(src / "comics", "漫画库的书.cbz")
    library.invalidate()

    default_only = library.books(library_id="default")[0]["id"]
    assert client.get(f"/opds/lib/{lib_b['id']}/book/{default_only}",
                      headers=enable_opds_cfg).status_code == 404
    assert client.get(f"/opds/lib/{lib_b['id']}/download/{default_only}",
                      headers=enable_opds_cfg).status_code == 404

    own = library.books(library_id=lib_b["id"])[0]["id"]
    assert client.get(f"/opds/lib/{lib_b['id']}/book/{own}",
                      headers=enable_opds_cfg).status_code == 200


# ---------------------------------------------------------------------------
# 回归：全局路由不受影响
# ---------------------------------------------------------------------------

def test_全局路由输出不变(client, auth_headers, enable_opds_cfg, default_root):
    """既有地址（客户端已订阅的那些）必须照旧，且不出现任何库前缀。"""
    _put(default_root, "甲.epub")
    _put(default_root, "乙.epub")
    library.invalidate()

    for path in ("/opds", "/opds/all", "/opds/recent", "/opds/authors",
                 "/opds/series", "/opds/tags"):
        r = client.get(path, headers=enable_opds_cfg)
        assert r.status_code == 200, path
        assert "/opds/lib/" not in r.text, f"{path} 不该出现库前缀"
    assert len(_entries(client.get("/opds/all", headers=enable_opds_cfg).text)) == 2
