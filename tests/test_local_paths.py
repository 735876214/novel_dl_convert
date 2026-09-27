"""第 63 期（5/6）：「服务器上的绝对路径」只给本机 / 局域网（决策 6）。

这条判据有两个面，各钉一批 —— 一面是**泄露**，一面是**误导**：

1. **来源判据**（`_is_local_request`）：回环 / 私网对端才给；出现任何**转发头**就降级。
   ⚠️ 尤其是**不看** `X-Forwarded-For` 里写的来源 —— 那个头客户端可以随便伪造，
   信它等于让任何远程客户端写一个 `127.0.0.1` 就把服务器目录结构拿走。所以专门
   有一条「伪造 XFF 也拿不到」的用例盯着这个「别优化它」。
2. **给出来的路径必须真的存在**：**给一个不存在的路径比不给更糟** —— 用户照着去
   找，找不到，还会以为文件丢了。所以端点里那次 `exists()` 不是多余的防御，
   `test_文件不在磁盘上就一条都不给` 专门把它走到。

`GET /api/books/{bid}` 那个响应是**与请求者无关**的资源表示，所以绝对路径**不塞
进它**，而是单开这个端点（判据只有一处）。这也是本文件用「扮演不同来源的客户端」
来测的原因：`TestClient(client=(host, port))` 就是 ASGI scope 里的 `client` 字段，
也就是服务端看到的那条连接的对端地址 —— 没有它，「远程拿不到」只能靠读代码相信。
"""
import contextlib
import pathlib
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from novelforge import server as server_mod
from novelforge.core import db, epub_builder, library
from novelforge.server import _is_local_request, app

# 与 `conftest.TEST_USER` / `TEST_PIN` 同值。这里不 import conftest：本文件自建
# client（见 `_client_as`），拿不到 `auth_headers` 那条路，索性把常量写在手边。
TEST_USER = "admin"
TEST_PIN = "test1234"


# ---------------- 判据层：`_is_local_request` ----------------

class _Req:
    """`_is_local_request` 只碰两个地方：`request.client.host` 与 `request.headers`。

    `headers` 必须是 starlette 的 `Headers`（**大小写不敏感**）：用普通 dict 的话，
    用例给 `"X-Forwarded-For"`、函数查 `"x-forwarded-for"` —— 本该命中的判据会静默
    放行，而真实请求走的从来是 starlette 那一套。这个坑当场踩到过一次。
    """

    def __init__(self, host, headers=None):
        self.client = None if host is None else type("_C", (), {"host": host})()
        self.headers = Headers(headers or {})


@pytest.mark.parametrize("host, expected", [
    ("127.0.0.1", True),
    ("::1", True),
    ("192.168.0.9", True),
    ("10.1.2.3", True),
    ("172.20.0.4", True),
    # IPv4-mapped IPv6：双栈监听（uvicorn 默认）下对端常长这样。不还原成 IPv4 的话
    # 它既非回环也非私网，本机访问会被白白降级 —— 现象是「绝对路径偶尔不出现」。
    ("::ffff:192.168.0.9", True),
    ("::ffff:8.8.8.8", False),
    # 公网地址要挑**真的全球可路由**的。文档段（192.0.2.0/24、198.51.100.0/24、
    # 203.0.113.0/24）看着像「典型公网例子」，实际落在 ipaddress 的非全球集合里
    # —— 拿它当公网会让判据用例**指向反面**。
    ("8.8.8.8", False),
    ("1.1.1.1", False),
    ("2001:4860:4860::8888", False),
    ("testclient", False),           # 解析不出 IP 的 host（TestClient 的默认值）
    ("", False),
])
def test_来源判据(host, expected):
    assert _is_local_request(_Req(host)) is expected


def test_对端地址缺失时判否():
    """ASGI 允许 `client` 为 None —— 不能炸，更不能当成「本机」。"""
    assert _is_local_request(_Req(None)) is False


@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Real-IP", "Forwarded",
                                    "X-Forwarded-Host"])
def test_带转发头一律降级(header):
    """经过一层转发时，对端地址是**代理自己的**（通常是 172.16/12 的容器网段）。

    只看对端地址会把「反代来的公网请求」判成本机 —— 这不是假想：本项目部署在 NAS 上，
    前面挂一层反代是最常见的形态。
    """
    assert _is_local_request(_Req("172.17.0.1", {header: "127.0.0.1"})) is False


def test_伪造转发头不能把远程伪装成本机():
    """⚠️ 判据只取「这个头**存在**」这一个事实，**不解析它的值**。

    解析 `X-Forwarded-For` 里写的来源看似更聪明（反代场景下能认出真实客户端地址），
    但那等于把判据交给一个**客户端完全控制的字符串** —— 任何远程请求写一个
    `127.0.0.1` 就能拿到服务器目录结构。这条用例钉住的就是「别把它优化成解析」。
    """
    assert _is_local_request(_Req("8.8.8.8", {"X-Forwarded-For": "127.0.0.1"})) is False


# ---------------- 端点层：`GET /api/books/{bid}/local-paths` ----------------

@contextlib.contextmanager
def _client_as(host: str, headers: dict | None = None):
    """扮演一个**来自 `host`** 的已登录客户端。

    `TestClient(client=(host, port))` 传下去的就是 ASGI scope 的 `client`，
    也就是服务端看到的那条连接的对端地址；`headers` 是**连接级**的头（模拟反代）。

    ⚠️ 不能用 conftest 的 `client` fixture 顶替：它的对端是 `testclient`（解析不出
    IP ⇒ 一律判否），只能演「远程」。要演「本机 / 局域网」必须自己建这条连接。
    """
    with TestClient(app, client=(host, 50000), headers=headers) as c:
        r = c.post("/api/auth/login", json={"user": TEST_USER, "pin": TEST_PIN})
        assert r.status_code == 200, r.text
        yield c, {"Authorization": f"Bearer {r.json()['token']}"}


def _bid_of(c, h, name: str) -> str:
    items = c.get("/api/books", headers=h).json()["items"]
    return next(x["id"] for x in items if x["name"] == name)


def _scan(root) -> None:
    """让刚放进去的文件进书目（第 62 期起是「标脏，下次读时增量刷」）。"""
    library.invalidate()


def test_本机来源给绝对路径(isolated, default_root, make_book):  # noqa: ARG001
    """回环来源：主文件与它的同 stem 兄弟都给绝对路径，键与 `files[].name` 同一套取值。"""
    make_book(default_root, "三体.epub")
    make_book(default_root, "三体.mobi")
    make_book(default_root, "别的一本.epub")     # 不同 stem ⇒ 不是兄弟，不该出现
    _scan(default_root)
    with _client_as("127.0.0.1") as (c, h):
        bid = _bid_of(c, h, "三体.epub")
        r = c.get(f"/api/books/{bid}/local-paths", headers=h)

    assert r.status_code == 200, r.text
    assert r.headers.get("cache-control") == "no-store", \
        "这个响应取决于请求者，任何中间层都不许缓存它"
    assert r.json() == {"local": True, "paths": {
        "三体.epub": str(default_root / "三体.epub"),
        "三体.mobi": str(default_root / "三体.mobi"),
    }}


def test_局域网来源也给(isolated, default_root, make_book):  # noqa: ARG001
    """「本地」包含局域网：NAS 上这个服务本来就是给家里的机器访问的。"""
    make_book(default_root, "三体.epub")
    _scan(default_root)
    with _client_as("192.168.0.9") as (c, h):
        bid = _bid_of(c, h, "三体.epub")
        r = c.get(f"/api/books/{bid}/local-paths", headers=h)
    assert r.json()["local"] is True
    assert r.json()["paths"] == {"三体.epub": str(default_root / "三体.epub")}


def test_远程来源一条路径都不给(isolated, default_root, make_book):  # noqa: ARG001
    """公网来源：`local` 假、`paths` 空，**而且响应体里不许出现任何绝对路径**。

    ⚠️ 断言写法有个坑：Windows 路径在 JSON 里是 `C:\\\\...`（反斜杠被转义），拿
    `str(root)` 直接去 `in r.text` 找**永远找不到** —— 那样的断言恒真、判据力为零。
    所以先把 JSON 的转义还原回来再比。
    """
    make_book(default_root, "三体.epub")
    _scan(default_root)
    with _client_as("8.8.8.8") as (c, h):
        bid = _bid_of(c, h, "三体.epub")
        r = c.get(f"/api/books/{bid}/local-paths", headers=h)

    assert r.status_code == 200, r.text
    assert r.json() == {"local": False, "paths": {}}
    raw = r.text.replace("\\\\", "\\")           # 还原 JSON 的反斜杠转义
    assert str(default_root) not in raw, "远程响应里出现了服务器绝对路径"
    assert "三体" not in raw, "远程连文件名都不该从这条路给（它本来就有别的入口）"


def test_反代来的请求一律降级(isolated, default_root, make_book):  # noqa: ARG001
    """对端是私网（反代容器）+ 带转发头 ⇒ 降级。这是判据里最容易写漏的一档：

    「私网就是本地」在**没有反代**时成立，有了反代就不成立 —— 反代的存在无法从
    对端地址看出来，只能靠转发头这个**存在的证据**判定。
    """
    make_book(default_root, "三体.epub")
    _scan(default_root)
    with _client_as("172.17.0.1", {"X-Forwarded-For": "192.168.0.9"}) as (c, h):
        bid = _bid_of(c, h, "三体.epub")
        r = c.get(f"/api/books/{bid}/local-paths", headers=h)
    assert r.json() == {"local": False, "paths": {}}


def test_整本书是一个目录时也给路径(isolated, default_root, make_audio_dir):  # noqa: ARG001
    """有声书在库里是**一个目录**（`book_detail().files` 为空）—— 但它自己也得有
    「在磁盘上的哪里」，这正是这个端点存在的理由。"""
    make_audio_dir(default_root, "三体 广播剧", tracks=2)
    _scan(default_root)
    with _client_as("127.0.0.1") as (c, h):
        books = c.get("/api/books", headers=h).json()["items"]
        bid = next(x["id"] for x in books if x["name"] == "三体 广播剧")
        r = c.get(f"/api/books/{bid}/local-paths", headers=h)
    assert r.json() == {"local": True, "paths": {
        "三体 广播剧": str(default_root / "三体 广播剧"),
    }}


def test_文件不在磁盘上就一条都不给(isolated, tmp_path, monkeypatch, default_root):  # noqa: ARG001
    """⚠️ **给一个不存在的路径比不给更糟** —— 用户照着去找，找不到，还会以为文件丢了。

    这里直接把 `by_id` 换成「卡片还在、文件没了」，好让这个分支**真的被走到**：
    靠删文件那种间接构造不行 —— 索引一刷新就把这本书从书目里删掉，请求变成 404，
    于是这条分支永远绿着、什么也没测。
    """
    ghost = tmp_path / "不在这里.epub"
    monkeypatch.setattr(server_mod.library, "by_id",
                        lambda bid: {"name": "三体.epub", "path": str(ghost)})
    with _client_as("127.0.0.1") as (c, h):
        r = c.get("/api/books/lib$ghost/local-paths", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"local": True, "paths": {}}, "路径不存在就不该给"


def test_卡片里没有路径时也不给(isolated, tmp_path, monkeypatch, default_root):  # noqa: ARG001
    """`pathlib.Path("")` 是**当前工作目录**、`exists()` 还给你 True —— 不挡这一下，
    服务器的工作目录就被当成「这本书的位置」报出去了。"""
    monkeypatch.setattr(server_mod.library, "by_id",
                        lambda bid: {"name": "三体.epub", "path": ""})
    with _client_as("127.0.0.1") as (c, h):
        r = c.get("/api/books/lib$ghost/local-paths", headers=h)
    assert r.json() == {"local": True, "paths": {}}


def test_书不存在是404(client, auth_headers):
    """这条路走常规 client（远程来源）—— 404 与来源无关，先判书在不在。"""
    assert client.get("/api/books/lib$没有这本/local-paths",
                      headers=auth_headers).status_code == 404


def test_路径是绝对路径且真的存在(isolated, default_root, make_book):  # noqa: ARG001
    """给出来的每一条都必须是**绝对路径**、且**指向真实存在的文件**。

    这条与「不给不存在的路径」是同一个判据的正面：`paths` 里出现的东西，用户
    拿着去文件管理器里粘贴就该能找到东西。
    """
    make_book(default_root, "三体.epub")
    make_book(default_root, "三体.azw3")
    _scan(default_root)
    with _client_as("127.0.0.1") as (c, h):
        bid = _bid_of(c, h, "三体.epub")
        paths = c.get(f"/api/books/{bid}/local-paths", headers=h).json()["paths"]

    assert paths, "本机来源必须给出路径（否则这条用例是空跑）"
    for name, p in paths.items():
        assert pathlib.Path(p).is_absolute(), f"{name} 给的不是绝对路径：{p}"
        assert pathlib.Path(p).is_file(), f"{name} 给的路径在磁盘上不存在：{p}"


# ---------------- 边界收口：书条目里的绝对路径不再下发 ----------------

def _build_epub(root, rel: str, title: str = "三体", author: str = "刘慈欣") -> pathlib.Path:
    """造一个**真 EPUB**（系列 / 作者这类字段要读真实 OPF，占位字节串探测不出来）。"""
    p = pathlib.Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": author, "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(p),
    )
    return p


def _walk_key(obj, key: str) -> list:
    """递归找出 JSON 里所有名为 ``key`` 的键**所在的对象**（数组里的也算）。"""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                hits.append(obj)
            hits.extend(_walk_key(v, key))
    elif isinstance(obj, list):
        for v in obj:
            hits.extend(_walk_key(v, key))
    return hits


def test_所有会吐书条目的端点都不带绝对路径(isolated, default_root, monkeypatch):  # noqa: ARG001
    """六个出口一起收口（第 63 期 5/6）。

    背景：book 条目（`library._row_of` / `catalog._book_of_row` 产出）里带着一个
    `path` 字段 —— 值是**服务器上的绝对路径**，服务端内部要用它定位文件。以下六处
    端点**不做任何投影**就把它发了出去，于是「远程降为库内相对路径」（决策 6）在
    这些地方等于没做：详情页再怎么降级，DevTools 里 `/api/books` 一打开全都有。

    两种断言各管一件事：**找 `path` 键**管「字段没被带出来」；**找库根字符串**管
    「服务器目录结构没被带出来」—— 后者对「换个键名继续发」同样有效。

    ⚠️ 六个端点都必须真的**有数据**（每个都断言 200）：没有数据时它们是 404，
    投影那行代码压根不执行，用例会绿着却什么也没测。
    """
    _build_epub(default_root, "三体.epub", title="三体", author="刘慈欣")
    _scan(default_root)
    with _client_as("8.8.8.8") as (c, h):        # 远程来源；但收口与来源无关
        bid = _bid_of(c, h, "三体.epub")
        # 系列走**元数据覆盖**（这个 EPUB 的 OPF 里没有系列），作者来自 OPF。
        # 演播者没法用覆盖造：`_apply_overlay` 是**直接赋值**，字符串会让
        # `narrator_books` 的逐成员比较把「某人」拆成单字 —— 那一条在这里打桩。
        r0 = c.post(f"/api/books/{bid}/metadata", headers=h,
                    json={"fields": {"series": "地球往事"}})
        assert r0.status_code == 200, r0.text
        cid = db.create_collection("收藏")
        db.add_book_to_collection(cid, bid)
        monkeypatch.setattr(server_mod.library, "narrator_books", lambda name: [{
            "id": bid, "name": "三体.epub", "path": str(default_root / "三体.epub"),
            "narrators": [name], "format": "AUDIO",
        }])

        urls = {
            "书目列表": "/api/books",
            "书籍详情": f"/api/books/{bid}",
            "系列详情": f"/api/series/{quote('地球往事')}",
            "作者详情": f"/api/authors/{quote('刘慈欣')}",
            "演播者详情": f"/api/narrators/{quote('某人')}",
            "收藏夹详情": f"/api/collections/{cid}",
        }
        for what, url in urls.items():
            r = c.get(url, headers=h)
            assert r.status_code == 200, f"{what}（{url}）→ {r.status_code} {r.text}"
            assert _walk_key(r.json(), "path") == [], f"{what}：响应里出现了 path 键"
            raw = r.text.replace("\\\\", "\\")
            assert str(default_root) not in raw, f"{what}：响应里出现了服务器绝对路径"
