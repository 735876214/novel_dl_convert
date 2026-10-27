"""history 路由的 SPA 兜底 + 全局安全响应头（第 153 期）。

为什么单开一个文件：这两件事都是**跨端契约**（前端路由 ↔ FastAPI 兜底、
安全头 ↔ 媒体出口的 sandbox 头），散在别处容易被一次重构悄悄改掉，
而「深链 404」和「CSP 把界面挡坏」都不会在普通接口用例里红。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

from novelforge import server


@pytest.fixture
def fake_bundle(monkeypatch: pytest.MonkeyPatch):
    """把 `STATIC_DIR` 指到临时目录，避免依赖真实构建产物（CI clone 里没有）。

    ⚠️ 不用 pytest 的 `tmp_path`：本机 `.venv` 解释器的 `tempfile.gettempdir()` 落回
    仓库根，pytest 建/删 `current` 符号链接时会撞 `tests/conftest.py` 的仓库根守卫
    （见 docs/TODO.md 的同一条环境说明）。这里显式把临时目录建到用户 `%TEMP%` 下。
    """
    base = pathlib.Path(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")) / "Temp"
    base.mkdir(parents=True, exist_ok=True)
    root = pathlib.Path(tempfile.mkdtemp(prefix="nf-spa-", dir=str(base)))
    v2 = root / "v2"
    v2.mkdir()
    (v2 / "index.html").write_text("<!doctype html><title>NF-SHELL</title>", encoding="utf-8")
    (v2 / "sw.js").write_text("self.addEventListener('install',()=>{})", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC_DIR", root)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_深链刷新回外壳(client: TestClient, fake_bundle: pathlib.Path) -> None:  # noqa: ARG001
    for path in ("/shelf", "/settings/appearance/theme", "/book/abc123", "/docs"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} 没有回 index.html（history 路由会 404）"
        assert "NF-SHELL" in r.text


def test_系列名带点也走兜底(client: TestClient, fake_bundle: pathlib.Path) -> None:  # noqa: ARG001
    """`/series/Vol.04` 的 `.04` 不是静态扩展名 —— 判据必须是扩展名白名单，不是「有没有点」。"""
    r = client.get("/series/Vol.04")
    assert r.status_code == 200
    assert "NF-SHELL" in r.text


def test_api_未知路径仍是_json_404(
    client: TestClient, auth_headers: dict, fake_bundle: pathlib.Path,  # noqa: ARG001
) -> None:
    # `/api/*` 先过鉴权中间件：不带令牌是 401（正确行为），带上才轮到路由 404。
    r = client.get("/api/nope", headers=auth_headers)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert "NF-SHELL" not in r.text


def test_静态资源缺失不回外壳(client: TestClient, fake_bundle: pathlib.Path) -> None:  # noqa: ARG001
    """缺的 .js 必须 404：回一份 HTML 会被浏览器当 JS 执行，报错完全对不上。"""
    for path in ("/static/v2/assets/missing.js", "/favicon.ico", "/robots.txt"):
        assert client.get(path).status_code == 404, path


def test_后端前缀永不兜底(
    client: TestClient, auth_headers: dict, fake_bundle: pathlib.Path,  # noqa: ARG001
) -> None:
    """这些前缀归后端所有：找不到就 401/404，绝不能回一份 HTML 外壳。"""
    cases = (
        ("/api", auth_headers),
        ("/api/", auth_headers),
        ("/opds", None),
        ("/koreader", None),
        ("/download", None),
        # 第 97 期删掉的旧端点：必须是 404，不能被兜底回 200 的 HTML
        ("/content?url=https://example.com/x", auth_headers),
    )
    for path, headers in cases:
        r = client.get(path, headers=headers or {})
        assert r.status_code != 200, f"{path} 被 SPA 兜底抢走了（回了 200）"
        assert "NF-SHELL" not in r.text, f"{path} 回了 SPA 外壳"


def test_安全响应头在成功与_401_上都在(
    client: TestClient, fake_bundle: pathlib.Path,  # noqa: ARG001
) -> None:
    ok = client.get("/shelf")
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert ok.headers["referrer-policy"] == "no-referrer"
    assert ok.headers["x-frame-options"] == "SAMEORIGIN"
    csp = ok.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "connect-src 'self' ws: wss:" in csp

    denied = client.get("/api/books")
    assert denied.status_code == 401
    assert denied.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in denied.headers["content-security-policy"]


def test_service_worker_从根路径提供且作用域覆盖全站(
    client: TestClient, fake_bundle: pathlib.Path,  # noqa: ARG001
) -> None:
    """SW 必须挂在 `/sw.js`（构建产物在 static/v2/ 下，靠 header 放开作用域）。"""
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers["service-worker-allowed"] == "/"
    assert "no-cache" in r.headers["cache-control"]


def test_service_worker_构建缺失时_404(
    client: TestClient, fake_bundle: pathlib.Path,  # noqa: ARG001
) -> None:
    (fake_bundle / "v2" / "sw.js").unlink()
    assert client.get("/sw.js").status_code == 404


def test_媒体出口的_sandbox_头不被全局_csp_覆盖() -> None:
    """`/asset` 这类不可信字节出口刻意用 `CSP: sandbox`；中间件必须 setdefault 而非覆盖。

    直接调中间件（不经真实书库夹具）：只要 call_next 返回的响应已经带了
    `Content-Security-Policy: sandbox`，中间件就不能把它换成全局 default-src。
    """
    import asyncio

    from starlette.requests import Request
    from starlette.responses import Response

    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": "/x", "raw_path": b"/x", "query_string": b"", "root_path": "",
        "headers": [], "server": ("testserver", 80), "client": ("127.0.0.1", 1234),
    }
    req = Request(scope)

    async def call_next(_request):  # noqa: ANN001
        return Response("x", headers={"Content-Security-Policy": "sandbox"})

    resp = asyncio.run(server._security_headers_middleware(req, call_next))
    assert resp.headers["content-security-policy"] == "sandbox"
    assert resp.headers["x-content-type-options"] == "nosniff"
