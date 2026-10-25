"""静态资源的缓存头（第 152 期）。

**为什么值得钉**：前端 chunk 名带内容 hash（`index-C0gTUMu4.js`），内容一变名字必变 ——
这类文件本可以 `immutable` 缓存一年。此前 `/static` 一律没有 `Cache-Control`：每次进站
都要对首屏二十来个 chunk 逐个发**条件请求**（304 也是至少一次 RTT），在 NAS 上把首屏
白拖慢几百毫秒。而页面壳（`/`）相反：它引用的 chunk 名会变，**必须**每次重验证。

⚠️ 不碰真实 `static/v2`：它不入库（镜像构建时才生成），CI 的 clone 里没有 ——
所以这里用临时目录直接测 `_ImmutableStatic` 与 `index()` 的行为，不依赖构建产物。
"""
import asyncio
import pathlib

from novelforge import server


def _scope(path: str) -> dict:
    return {
        "type": "http", "method": "GET", "path": path, "root_path": "",
        "scheme": "http", "query_string": b"", "headers": [],
        "server": ("testserver", 80), "client": ("testclient", 123),
        "http_version": "1.1",
    }


def test_带_hash的_assets_是_immutable(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("x", encoding="utf-8")
    st = server._ImmutableStatic(directory=str(tmp_path))

    resp = asyncio.run(st.get_response("assets/index-abc123.js", _scope("/static/assets/index-abc123.js")))

    cc = resp.headers.get("cache-control", "")
    assert "immutable" in cc and "max-age=31536000" in cc, cc


def test_非_assets_的静态文件只给一小时(tmp_path):
    """没有 hash 的文件不能 immutable —— 内容改了名字不变，缓存一年就再也更新不掉。"""
    (tmp_path / "cover.jpg").write_bytes(b"x")
    st = server._ImmutableStatic(directory=str(tmp_path))

    resp = asyncio.run(st.get_response("cover.jpg", _scope("/static/cover.jpg")))

    cc = resp.headers.get("cache-control", "")
    assert "immutable" not in cc, cc
    assert "max-age=3600" in cc, cc


def test_页面壳每次重验证(tmp_path, monkeypatch):
    """`/` 引用的 chunk 名随构建变化 —— 缓存住旧壳会让升级后指向已删的 bundle。"""
    v2 = tmp_path / "v2"
    v2.mkdir()
    (v2 / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC_DIR", pathlib.Path(tmp_path))

    resp = server.index()

    assert resp.headers.get("cache-control") == "no-cache"

def test_平台分隔符不影响_immutable_判定():
    r"""Starlette 的 `get_response(path)` 用的是**平台分隔符**：Windows 上是 ``v2\assets\x.js``。

    第 152 期审计抓到：第一版实现直接 grep ``"/assets/"``，在 Windows 上恒为假 ⇒ 开发机
    永远拿不到 immutable（生产是 Linux 所以没暴露）。判据抽成 `_static_cache_control` 之后
    这里直接钉它 —— **不经过 Starlette**，两种分隔符在任何平台上都能验。

    （第一版这个用例是把反斜杠路径直接喂给 `get_response`：在 Linux 上那不是分隔符，
      于是 404 —— CI 红了一次。判据与「Starlette 怎么传」解耦后不再依赖平台。）
    """
    assert "immutable" in server._static_cache_control("assets\\x-1.js")
    assert "immutable" in server._static_cache_control("v2/assets/x-1.js")
    assert "immutable" in server._static_cache_control("v2\\assets\\x-1.js")
    assert "immutable" not in server._static_cache_control("cover.jpg")
    assert "max-age=3600" in server._static_cache_control("v2/cover.jpg")
