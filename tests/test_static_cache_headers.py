"""静态资源的缓存头（第 152 期）。

**为什么值得钉**：前端 chunk 名带内容 hash（`index-C0gTUMu4.js`），内容一变名字必变 ——
这类文件本可以 `immutable` 缓存一年。此前 `/static` 一律没有 `Cache-Control`：每次进站
都要对首屏二十来个 chunk 逐个发**条件请求**（304 也是至少一次 RTT），在 NAS 上把首屏
白拖慢几百毫秒。而页面壳（`/`）相反：它引用的 chunk 名会变，**必须**每次重验证。

⚠️ 不碰真实 `static/v2`：它不入库（镜像构建时才生成），CI 的 clone 里没有 ——
所以这里用临时目录直接测 `_ImmutableStatic` 与 `index()` 的行为，不依赖构建产物。
"""
import asyncio
import os
import pathlib

from novelforge import server


def _scope(path: str, headers: dict | None = None) -> dict:
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    return {
        "type": "http", "method": "GET", "path": path, "root_path": "",
        "scheme": "http", "query_string": b"", "headers": raw,
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


# ---------------------------------------------------------------------------
# 预压缩件协商（第 179 期）
# ---------------------------------------------------------------------------

def _mk_asset(tmp_path, name="x-1.js", body=b"console.log('hello');" * 100):
    (tmp_path / "assets").mkdir(exist_ok=True)
    f = tmp_path / "assets" / name
    f.write_bytes(body)
    # 构建期的旁路件：内容不重要（这里只验「选了哪一份」），但要真实存在
    f.with_name(f.name + ".gz").write_bytes(b"GZDATA")
    f.with_name(f.name + ".br").write_bytes(b"BRDATA")
    return f


def test_接受_gzip_时发预压缩件(tmp_path):
    _mk_asset(tmp_path)
    st = server._ImmutableStatic(directory=str(tmp_path))
    resp = asyncio.run(st.get_response(
        "assets/x-1.js", _scope("/static/assets/x-1.js", {"accept-encoding": "gzip, deflate"})))
    assert resp.headers.get("content-encoding") == "gzip"
    assert pathlib.Path(resp.path).name.endswith(".js.gz")
    assert "Accept-Encoding" in resp.headers.get("vary", "")
    assert "immutable" in resp.headers.get("cache-control", "")


def test_同时接受_br_时优先_br(tmp_path):
    """br 更小；但浏览器只在安全上下文才报它 —— 报了就优先用。"""
    _mk_asset(tmp_path)
    st = server._ImmutableStatic(directory=str(tmp_path))
    resp = asyncio.run(st.get_response(
        "assets/x-1.js", _scope("/static/assets/x-1.js", {"accept-encoding": "gzip, br"})))
    assert resp.headers.get("content-encoding") == "br"
    assert pathlib.Path(resp.path).name.endswith(".js.br")


def test_q等于0视为不接受(tmp_path):
    _mk_asset(tmp_path)
    st = server._ImmutableStatic(directory=str(tmp_path))
    resp = asyncio.run(st.get_response(
        "assets/x-1.js", _scope("/static/assets/x-1.js", {"accept-encoding": "gzip;q=0, br;q=0"})))
    assert resp.headers.get("content-encoding") is None
    assert pathlib.Path(resp.path).name == "x-1.js"


def test_没有旁路件就发原文件(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "y-1.js").write_bytes(b"console.log(1);")
    st = server._ImmutableStatic(directory=str(tmp_path))
    resp = asyncio.run(st.get_response(
        "assets/y-1.js", _scope("/static/assets/y-1.js", {"accept-encoding": "gzip"})))
    assert resp.headers.get("content-encoding") is None


def test_直接请求旁路件是_404(tmp_path):
    """旁路件是给服务端选用的 —— 被当普通文件下载出去就是一串压缩字节冒充 JS。"""
    _mk_asset(tmp_path)
    st = server._ImmutableStatic(directory=str(tmp_path))
    for suffix in (".gz", ".br"):
        resp = asyncio.run(st.get_response(
            f"assets/x-1.js{suffix}", _scope(f"/static/assets/x-1.js{suffix}")))
        assert resp.status_code == 404, suffix


def test_带_range的请求走原文件(tmp_path):
    """区间语义按**原始字节**定义；用压缩件回区间会错位。"""
    _mk_asset(tmp_path)
    st = server._ImmutableStatic(directory=str(tmp_path))
    resp = asyncio.run(st.get_response(
        "assets/x-1.js",
        _scope("/static/assets/x-1.js", {"accept-encoding": "gzip", "range": "bytes=0-9"})))
    assert resp.headers.get("content-encoding") is None
    assert pathlib.Path(resp.path).name == "x-1.js"


def test_条件请求命中旁路件的_etag_时_304_仍带编码头(tmp_path):
    """`NotModifiedResponse` 只保留少数几个头（会摘掉 content-encoding）—— 必须补回去。"""
    _mk_asset(tmp_path)
    st = server._ImmutableStatic(directory=str(tmp_path))
    first = asyncio.run(st.get_response(
        "assets/x-1.js", _scope("/static/assets/x-1.js", {"accept-encoding": "gzip"})))
    etag = first.headers["etag"]

    resp = asyncio.run(st.get_response(
        "assets/x-1.js",
        _scope("/static/assets/x-1.js", {"accept-encoding": "gzip", "if-none-match": etag})))
    assert resp.status_code == 304
    assert resp.headers.get("content-encoding") == "gzip"
    assert "Accept-Encoding" in resp.headers.get("vary", "")


def test_不可压的类型不找旁路件(tmp_path):
    """字体 / 图片本身已压缩：即便有人放了旁路件也不选用（构建期也不会生成）。"""
    (tmp_path / "assets").mkdir()
    f = tmp_path / "assets" / "f-1.woff2"
    f.write_bytes(b"woff2")
    f.with_name(f.name + ".gz").write_bytes(b"GZ")
    st = server._ImmutableStatic(directory=str(tmp_path))
    resp = asyncio.run(st.get_response(
        "assets/f-1.woff2", _scope("/static/assets/f-1.woff2", {"accept-encoding": "gzip"})))
    assert resp.headers.get("content-encoding") is None


def test_编码协商的边界():
    assert server._accepts_encoding("gzip, deflate, br", "br")
    assert server._accepts_encoding("gzip", "gzip")
    assert not server._accepts_encoding("", "gzip")
    assert not server._accepts_encoding("identity", "gzip")
    assert not server._accepts_encoding("gzip;q=0", "gzip")
    # `*` **只兜底、不覆盖显式条目**（第 179 期评审抓到的）：`gzip;q=0, *;q=0.5` 里的
    # `q=0` 是「我不要 gzip」，`*` 不能把它抬成「要」—— 写 q=0 的客户端通常就是解不了。
    assert not server._accepts_encoding("gzip;q=0, *;q=0.5", "gzip")
    assert server._accepts_encoding("*;q=0.5", "br")
    assert server._accepts_encoding("br;q=0, *;q=0.5", "gzip")   # `*` 兜底「没列出」的
    assert server._accepts_encoding("br;q=0.9, gzip;q=0.1", "br")


def test_只带_If_Modified_Since_的复验不走旁路件(tmp_path):
    """旁路件与原件是 `deploy.mjs` 同一批 `cpSync` 出来的，`Last-Modified` 常常同秒 ⇒
    只带 `If-Modified-Since` 的复验会命中 304，而客户端手里那份缓存体是**未压缩**的。
    这时若还贴 `Content-Encoding: gzip`，缓存会把 identity 体当压缩体解码
    （`ERR_CONTENT_DECODING_FAILED`，那支 JS 永不执行）。这类请求一律回落原文件。"""
    from email.utils import formatdate

    f = _mk_asset(tmp_path)
    stamp = f.stat().st_mtime
    for suffix in (".gz", ".br"):
        os.utime(f.with_name(f.name + suffix), (stamp, stamp))   # 模拟 cpSync 的同一时刻

    st = server._ImmutableStatic(directory=str(tmp_path))
    resp = asyncio.run(st.get_response("assets/x-1.js", _scope(
        "/static/assets/x-1.js",
        {"accept-encoding": "gzip", "if-modified-since": formatdate(stamp, usegmt=True)},
    )))
    assert resp.status_code == 304
    assert resp.headers.get("content-encoding") is None, "identity 体不能被标记成压缩体"

    # 对照：带 If-None-Match（ETag 按旁路件算）时，304 仍须带编码头，否则浏览器拿旧头解码
    first = asyncio.run(st.get_response(
        "assets/x-1.js", _scope("/static/assets/x-1.js", {"accept-encoding": "gzip"})))
    resp2 = asyncio.run(st.get_response("assets/x-1.js", _scope(
        "/static/assets/x-1.js",
        {"accept-encoding": "gzip", "if-none-match": first.headers["etag"]},
    )))
    assert resp2.status_code == 304 and resp2.headers.get("content-encoding") == "gzip"


def test_字体_MIME_被登记(tmp_path):
    """第 179 期：`.woff2` 认不出来时静态出口回 `application/octet-stream`，而响应带
    `X-Content-Type-Options: nosniff` —— 浏览器可能因此**拒用**自托管字体（线上 1.4.5
    实测 10 个 woff2 全是 octet-stream）。判据在 `server` 导入时登记一次，这里钉住。"""
    import mimetypes

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "f-1.woff2").write_bytes(b"wOF2")
    st = server._ImmutableStatic(directory=str(tmp_path))
    resp = asyncio.run(st.get_response("assets/f-1.woff2", _scope("/static/assets/f-1.woff2")))
    assert resp.headers.get("content-type", "").startswith("font/woff2"), resp.headers.get("content-type")
    assert mimetypes.guess_type("x.woff2")[0] == "font/woff2"


def test_全局_mimetypes_被重建后字体_MIME_会自己补回(tmp_path):
    """**这条是全量跑出来的**（单跑绿、连跑红）：`ebooklib.utils.guess_type()` 里调了
    `mimetypes.init()`，而它会 `_db = MimeTypes()` **重建全局库** —— 导入期
    `add_type` 的字体条目被整批冲掉。于是「出版过一本 EPUB」之后，自托管字体又变回
    `application/octet-stream`（与线上 1.4.5 的症状同一个出口）。

    这里把全局库换成一个空库来**确定性地**模拟那次重建（不依赖 `init()` 在 Windows
    注册表 / Linux `/etc/mime.types` 上会不会真冲掉），断言「字体请求进来时自己补回」。
    """
    import mimetypes

    saved = mimetypes._db
    mimetypes._db = mimetypes.MimeTypes(filenames=())      # 空库 = 系统什么都没登记
    try:
        assert mimetypes.guess_type("x.woff2")[0] is None, "前提：此时字体类型确实丢了"
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "f-1.woff2").write_bytes(b"wOF2")
        st = server._ImmutableStatic(directory=str(tmp_path))
        resp = asyncio.run(st.get_response("assets/f-1.woff2", _scope("/static/assets/f-1.woff2")))
        assert resp.headers.get("content-type", "").startswith("font/woff2"), \
            resp.headers.get("content-type")
        assert mimetypes.guess_type("x.woff2")[0] == "font/woff2"
    finally:
        mimetypes._db = saved
