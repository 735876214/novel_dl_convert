"""GET ``/api/*`` 的条件请求（ETag / 304，第 161 期）。

**为什么值得钉**：`/api/books` 在 2,309 本的库上是 **1.9 MB（146 KB gzip）**，而它
每次进站都会被拉一次（侧栏计数 / 仪表盘 / 浏览页共用）。ETag 让「数据没变」的回访
只花一行 304 —— 但条件请求有一个**失效时不报错**的失败模式：标签算错（比如把不该
忽略的状态忽略了），浏览器就会一直拿旧列表，比不缓存更糟。所以这里钉三条：

1. 只有 **200 + JSON** 才有 ETag（媒体出口、401、写操作一概没有）；
2. `If-None-Match` 命中 ⇒ **304 且没有正文**（带正文的 304 会被浏览器丢弃 / 报错）；
3. **数据一变 ETag 必变**。

`/api/books` 本身在空库上也能走通，所以这里不造书，只断言协议行为。
"""
import pytest


@pytest.fixture
def etag_of(client, auth_headers):
    """取某个 GET 接口的 ETag（顺带断言基本契约）。"""

    def _get(path: str) -> str:
        r = client.get(path, headers=auth_headers)
        assert r.status_code == 200, r.text
        etag = r.headers.get("etag", "")
        assert etag.startswith('"') and etag.endswith('"'), etag
        assert r.headers.get("cache-control") == "private, no-cache"
        # 小响应不经过 gzip（低于 minimum_size）时只有 Authorization；大响应会被
        # GZipMiddleware 追加 Accept-Encoding —— 两种都算对，但 Authorization 必须在。
        vary = r.headers.get("vary", "")
        assert "Authorization" in vary, vary
        return etag

    return _get


def test_列表接口带_etag_且重复请求命中_304(client, auth_headers, etag_of):
    etag = etag_of("/api/libraries")
    r = client.get("/api/libraries", headers={**auth_headers, "If-None-Match": etag})
    assert r.status_code == 304
    assert r.content == b""
    assert r.headers.get("etag") == etag
    # 304 不能带「说的是那份没发出去的表示」的编码 / 长度头
    assert "content-encoding" not in r.headers
    assert "content-length" not in r.headers or r.headers["content-length"] == "0"


def test_弱标签也算命中(client, auth_headers, etag_of):
    """RFC 9110 §13.1.2 的弱比较：`W/"…"` 回传也要命中。"""
    etag = etag_of("/api/libraries")
    r = client.get("/api/libraries", headers={**auth_headers, "If-None-Match": f"W/{etag}"})
    assert r.status_code == 304


def test_标签列表与星号也算命中(client, auth_headers, etag_of):
    etag = etag_of("/api/libraries")
    r = client.get("/api/libraries", headers={
        **auth_headers, "If-None-Match": f'"other", {etag}'})
    assert r.status_code == 304
    r = client.get("/api/libraries", headers={**auth_headers, "If-None-Match": "*"})
    assert r.status_code == 304


def test_数据一变_etag_就变(client, auth_headers, etag_of, make_library, tmp_path):
    before = etag_of("/api/libraries")
    make_library("etag-lib", "ETag 库", "ebook", tmp_path / "etag-lib")
    after = etag_of("/api/libraries")
    assert after != before, "新增书库后 ETag 没变 ⇒ 浏览器会一直拿旧列表"
    r = client.get("/api/libraries", headers={**auth_headers, "If-None-Match": before})
    assert r.status_code == 200
    assert r.json()["items"]


def test_书目列表也走同一套(client, auth_headers, etag_of):
    """最大的那个响应（/api/books）必须被覆盖 —— 它是这条优化的主要目标。"""
    etag = etag_of("/api/books")
    r = client.get("/api/books", headers={**auth_headers, "If-None-Match": etag})
    assert r.status_code == 304


def test_非_json_响应不贴_etag(client, auth_headers):
    """CSV 导出（text/csv）不参与：它不是 JSON，也不该按 JSON 的口径缓存。"""
    r = client.get("/api/books/export", headers=auth_headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "etag" not in r.headers
    assert "cache-control" not in r.headers


def test_大响应的_etag_不随压缩而变(client, auth_headers, default_root, make_book, test_lib_id):
    """ETag 必须在**未压缩**的字节上算（中间件注册在 GZip 之内）。

    否则同一个实体在 `identity` 与 `gzip` 下会得到两个标签：浏览器换一种编码回访时
    条件请求永远失效，每次都 200 重传整份 —— 恰好是这条优化要避免的那件事。
    """
    for i in range(20):
        make_book(default_root, f"etag-{i}.epub")
    r = client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers)
    assert r.status_code == 200, r.text

    plain = client.get("/api/books", headers={**auth_headers, "Accept-Encoding": "identity"})
    gz = client.get("/api/books", headers={**auth_headers, "Accept-Encoding": "gzip"})
    assert plain.status_code == gz.status_code == 200
    assert len(plain.content) > 1024, "响应太小不会触发 gzip，这条用例就失去意义"
    assert "gzip" in gz.headers.get("content-encoding", ""), "大响应没被压缩，这条用例就失去意义"
    assert plain.headers["etag"] == gz.headers["etag"]
    assert "Accept-Encoding" in gz.headers.get("vary", "")


def test_端点自己定的_no_store_不被改写(client, auth_headers, default_root, make_book, test_lib_id):
    """`local-paths` 的 `no-store` 取决于请求者来源 —— 给它贴 ETag 就是把安全语义降级。

    那个端点的正文随「本机 / 远程」而变，而 Vary 表达不了「来源 IP」这件事；
    一旦把它改写成 `private, no-cache`，服务器绝对路径就可能被中间层回放给远程。
    """
    make_book(default_root, "paths.epub")
    assert client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers).status_code == 200
    bid = client.get("/api/books", headers=auth_headers).json()["items"][0]["id"]

    r = client.get(f"/api/books/{bid}/local-paths", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert "etag" not in r.headers


def test_未登录的_401_不贴_etag(client):
    r = client.get("/api/libraries")
    assert r.status_code == 401
    assert "etag" not in r.headers


def test_写操作不贴_etag(client, auth_headers):
    import pathlib

    from conftest import TEST_PIN, TEST_USER
    from novelforge import config

    r = client.post("/api/auth/login", json={"user": TEST_USER, "pin": TEST_PIN})
    assert "etag" not in r.headers
    root = config.LIBRARY_SOURCE_ROOTS[0]["path"]
    r = client.post("/api/libraries", headers=auth_headers, json={
        "name": "写操作不缓存", "type": "ebook",
        "source_dirs": [str(pathlib.Path(root) / "write-lib")],
    })
    assert r.status_code == 200, r.text
    assert "etag" not in r.headers


@pytest.mark.parametrize(("header", "expected"), [
    ('"abc"', True),
    ('W/"abc"', True),
    ('"x", W/"abc"', True),
    ("*", True),
    ('"abcd"', False),
    ("", False),
])
def test_标签比较函数(header, expected):
    from novelforge.server import _etag_matches

    assert _etag_matches(header, '"abc"') is expected
