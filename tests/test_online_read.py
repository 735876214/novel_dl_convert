"""第 93 期：**在线阅读的取数层**（`sources/online.py` + 三条读点路由）。

阅读器的本地链路是「书 → 库里的文件 → 单章 XHTML」；这一层补的是
「书 → 书源上的一页 → 单章正文」。用例覆盖用户本轮的四条要求逐条对应的行为：

| 用户原话 | 本文件里钉住它的用例 |
|---|---|
| 「接我给的书源」 | `test_目录…` / `test_单章…`（取数全走源适配器） |
| 「切换客户端进度同步」 | `test_读一章会推进在线位置…` / `test_对得上才写本地进度…` |
| 「允许落盘」 | `test_缓存只落在缓存目录里`（静态契约） |
| 「无网络时还能继续读」 | `test_断网时回落缓存并如实标stale` / `test_缓存也没有就如实报错` |

另外三条硬边界各有专属用例：**第三方标记永不进 `v-html`**（源站 HTML / `script`
必须先被压成纯文本）、**URL 只在服务端**（客户端按 index 取章，「书页地址」由服务端
在响应里下发，客户端传不进来）、**书页变了要清正文缓存**（目录一改版，旧缓存就对应
另一份目录，继续命中会静默显示错章）。

全程零网络：书源一律是本文件的桩。
"""
import json

import pytest

from novelforge import config
from novelforge.core import db, epub_builder, library
from novelforge.core import reading_list
from novelforge.sources import REGISTRY, online
from novelforge.sources.base import SourceAdapter

LOCAL_BODY = "<p>正文</p>"


async def _never_fetch(self, client, item):  # noqa: ANN001
    raise AssertionError("这条用例不该整本取书")


def make_src(name: str, chapters: list, *, mode: str = "toc", may_html: bool = True,
             fail_links: bool = False, fail_body: bool = False, support: str = "") -> type:
    """桩源：`chapters` = ``[{"title", "body"}, ...]``。

    `fail_links` / `fail_body` 用来演断网（抛的错就是真实网络层那类异常文本）；
    `may_html` 对应 `content_may_be_html()`，决定正文要不要过 HTML 解析器。
    """

    class _Stub(SourceAdapter):
        display_name = f"{name} 展示名"

        async def search(self, client, title):  # noqa: ANN001, ARG001
            raise AssertionError("在线阅读用例不该搜索")

        async def fetch_book(self, client, item):  # noqa: ANN001, ARG001
            raise AssertionError("toc 模式的桩不该整本取书")

        async def fetch_book_chapters(self, client, item):  # noqa: ANN001, ARG001
            return [{"title": c["title"], "body": c["body"]} for c in chapters]

        async def chapter_links(self, client, book_url):  # noqa: ANN001, ARG001
            if fail_links:
                raise RuntimeError("连接失败：域名不在白名单内")
            return [{"title": c["title"], "url": f"{book_url}#{i}"}
                    for i, c in enumerate(chapters)]

        async def chapter_body(self, client, url):  # noqa: ANN001, ARG001
            if fail_body:
                raise RuntimeError("连接失败：域名不在白名单内")
            return chapters[int(url.rsplit("#", 1)[1])]["body"]

        def online_support(self) -> str:
            return support

        def online_mode(self) -> str:
            return mode

        def content_may_be_html(self) -> bool:
            return may_html

    _Stub.__name__ = f"Stub_{name}"
    _Stub.name = name
    return _Stub


@pytest.fixture
def book(tmp_path, make_library, isolated):  # noqa: ARG001
    """一本真 EPUB（本地目录是**真的** —— 对齐用例要拿它去比）。"""
    root = tmp_path / "onlinelib"
    make_library("onlinelib", "在线库", "ebook", root)
    epub_builder.build_epub(
        {"title": "三体", "author": "刘慈欣", "language": "zh"},
        [{"title": f"第 {i} 章", "body_html": LOCAL_BODY} for i in range(1, 4)],
        str(root / "三体.epub"),
    )
    library.invalidate()
    return library.books("onlinelib")[0]


@pytest.fixture
def online_cache(monkeypatch, tmp_path):
    """把**在线缓存根**指到本用例的临时目录。

    ⚠️ 必须做：`conftest` 的 `CACHE_DIR` 是**会话级**的（整个测试会话共用一个），
    不隔离的话前一个用例落下的 `toc.json` / 章节文件会被后一个用例当成自己的缓存命中，
    于是「断网降级」「缓存优先」这类用例会时红时绿。
    """
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    root = online.cache_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def stub(monkeypatch):
    def _install(name: str, chapters, **kw) -> str:
        monkeypatch.setitem(REGISTRY, name, make_src(name, chapters, **kw))
        return name
    return _install


def _set_download(monkeypatch, tmp_path, *, enabled: bool) -> None:
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"download": {"enabled": enabled}})


def _local_titles(b: dict) -> list:
    detail = library.book_detail(b["name"], b.get("library_id")) or {}
    return [c.get("title") or ""
            for g in (detail.get("chapters") or []) for c in (g.get("chapters") or [])]


def _bind(db_, bid, source, url="https://源站/page/1"):
    return db_.online_bind_put(bid, library_id="onlinelib", source=source, url=url,
                               title="三体")


def _chapters(client, headers, bid, **q):
    return client.get(f"/api/books/{bid}/online/chapters", headers=headers, params=q)


def _chapter(client, headers, bid, index, **q):
    return client.get(f"/api/books/{bid}/online/chapter/{index}", headers=headers, params=q)


def _status(client, headers, bid):
    return client.get(f"/api/books/{bid}/online/status", headers=headers)


def _settle():
    """等后台预取收尾。

    ⚠️ 不写这句，「缓存了几章」这类断言就取决于调度时序：读第 1 章时预取的**第 2 章**
    可能已经落盘、也可能还没跑 —— 用例会时红时绿。`_online_prefetch` 用
    `_ops_begin/_ops_end` 记了账，这里就等这本账。
    """
    from novelforge.server import wait_background_ops
    assert wait_background_ops(5.0), "后台预取没收尾"


# ---------------------------------------------------------------------------
# 入口拦截（404 / 400）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("call", [
    lambda c, h, b: _status(c, h, b),
    lambda c, h, b: _chapters(c, h, b),
    lambda c, h, b: _chapter(c, h, b, 0),
    lambda c, h, b: c.delete(f"/api/books/{b}/online/bind", headers=h),
])
def test_未知书籍一律404(client, auth_headers, book, monkeypatch, tmp_path, online_cache, call):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    r = call(client, auth_headers, "根本不存在")
    assert r.status_code == 404, r.text
    assert "书籍不存在" in r.json()["detail"]


def test_没绑定时给出口而不是空白(client, auth_headers, book, monkeypatch, tmp_path, online_cache):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    r = _chapters(client, auth_headers, book["id"])
    assert r.status_code == 400, r.text
    assert "还没绑定书源" in r.json()["detail"]
    assert "详情页" in r.json()["detail"], "拒绝要给出出口"


def test_闸门关闭时读不了且不触网(client, auth_headers, book, monkeypatch, tmp_path, online_cache):  # noqa: ARG001
    """闸门判定必须发生在取数**之前**：桩会直接断言失败，被拦时它一次都不许被调到。"""
    _set_download(monkeypatch, tmp_path, enabled=False)
    monkeypatch.setitem(REGISTRY, "stub-gate", make_src("stub-gate", [], fail_links=True))
    _bind(db, book["id"], "stub-gate")

    for r in (_chapters(client, auth_headers, book["id"]),
              _chapter(client, auth_headers, book["id"], 0)):
        assert r.status_code == 400, r.text
        assert "下载功能未开启" in r.json()["detail"]
        assert "网络与下载" in r.json()["detail"]


def test_源不支持则如实说原因(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-nope", [], support="这个书源不支持逐章在线阅读：它只能整本取回")
    _bind(db, book["id"], name)

    r = _chapters(client, auth_headers, book["id"])
    assert r.status_code == 400, r.text
    assert "只能整本取回" in r.json()["detail"]


# ---------------------------------------------------------------------------
# status（入口显隐 / 置灰原因的唯一出处）
# ---------------------------------------------------------------------------

def test_未绑定的status显示未绑定而不是错误(client, auth_headers, book, online_cache):  # noqa: ARG001
    r = _status(client, auth_headers, book["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bound"] is False and body["available"] is False
    assert body["reason"] == "", "没绑定不是「不可用」，前端据此显示绑定入口"
    assert body["cache"]["cached"] == 0


def test_绑定后的status给出展示名与缓存现状(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-st", [{"title": "第 1 章", "body": "<p>甲</p>"}])
    _bind(db, book["id"], name)

    body = _status(client, auth_headers, book["id"]).json()
    assert body["bound"] is True and body["available"] is True
    assert body["display_name"] == "stub-st 展示名", "横幅要显示源站名，不是内部 id"
    assert body["url"] == "https://源站/page/1"

    _chapter(client, auth_headers, book["id"], 0)
    body = _status(client, auth_headers, book["id"]).json()
    assert body["cache"]["cached"] == 1 and body["cache"]["total"] == 1
    assert body["pos"] == 0 and body["seen"] == 1


def test_源不支持时status如实置灰(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-grey", [], support="这条书源的规则里没有正文提取（book.content）")
    _bind(db, book["id"], name)

    body = _status(client, auth_headers, book["id"]).json()
    assert body["available"] is False
    assert "没有正文提取" in body["reason"], "灰掉的入口必须说清为什么灰"


def test_解绑后status回到未绑定(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-un", [{"title": "第 1 章", "body": "甲"}])
    _bind(db, book["id"], name)
    assert _chapter(client, auth_headers, book["id"], 0).status_code == 200

    r = client.delete(f"/api/books/{book['id']}/online/bind", headers=auth_headers)
    assert r.status_code == 200, r.text and r.json()["cleared"] == 1
    assert _status(client, auth_headers, book["id"]).json()["bound"] is False
    assert online.book_cache_stats(book["id"])["cached"] == 1, "解绑不动文件（缓存留着）"
    assert library.by_id(book["id"]) is not None


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------

def test_目录不下发书源内部URL且第二次命中缓存(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-toc", [{"title": f"第 {i} 章", "body": "甲"} for i in range(1, 4)])
    _bind(db, book["id"], name)

    r = _chapters(client, auth_headers, book["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["title"] for e in body["entries"]] == ["第 1 章", "第 2 章", "第 3 章"]
    assert body["total"] == 3 and body["origin"] == "network"
    assert body["display_name"] == "stub-toc 展示名"
    assert all("#" not in json.dumps(e, ensure_ascii=False) for e in body["entries"]), \
        "每章的站内地址不出服务端（客户端按 index 取章）"

    again = _chapters(client, auth_headers, book["id"]).json()
    assert again["origin"] == "cache", "目录取过一次就该落盘，别再外呼"


def test_目录算好local_index前端不自己算(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """线上标题 == 本地标题 ⇒ 同一章；用别的标题 ⇒ `None`（**不猜**）。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    local = _local_titles(book)
    assert len(local) >= 3, f"这本书的本地目录少于 3 章，用例前提不成立：{local}"
    name = stub("stub-align", [{"title": t, "body": "甲"} for t in local])
    _bind(db, book["id"], name)

    body = _chapters(client, auth_headers, book["id"]).json()
    assert [e["local_index"] for e in body["entries"]] == list(range(len(local)))
    assert body["local_total"] == len(local)

    # 换一本「目录完全对不上」的源：一条都不认（而不是挑最像的那条硬配）
    name2 = stub("stub-misalign", [{"title": f"无关标题{i}", "body": "甲"} for i in range(5)])
    _bind(db, book["id"], name2, url="https://源站/page/2")
    body = _chapters(client, auth_headers, book["id"]).json()
    assert all(e["local_index"] is None for e in body["entries"]), body["entries"]


def test_源站目录解析不出来时如实报错(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-empty", [])
    _bind(db, book["id"], name)

    r = _chapters(client, auth_headers, book["id"])
    assert r.status_code == 502, r.text
    assert "没解析出章节" in r.json()["detail"]
    assert "规则" in r.json()["detail"], "要指向真正的原因（规则过期），而不是「失败了」"


# ---------------------------------------------------------------------------
# 单章：纯文本、位置、对齐、缓存
# ---------------------------------------------------------------------------

def test_单章正文是纯文本且不带源站标记(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """**硬要求**：第三方标记永不进 `v-html`。源站正文里的标签 / 事件属性 / 脚本
    一个都不许出现在响应里。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    dirty = ('<div class="content"><script>alert(1)</script>'
             '<p onerror="steal()">甲&amp;乙</p><p>丙</p></div>')
    name = stub("stub-dirty", [{"title": "第 1 章", "body": dirty}])
    _bind(db, book["id"], name)

    body = _chapter(client, auth_headers, book["id"], 0).json()
    html = body["html"]
    assert html == "<p>甲&amp;乙</p>\n<p>丙</p>", html
    for bad in ("<div", "<script", "onerror", "alert(1)"):
        assert bad not in html, f"源站标记混进了正文：{bad}"
    assert body["title"] == "第 1 章" and body["total"] == 1 and body["index"] == 0


def test_纯文本源里的尖括号不被解析器吃掉(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """规则的正文提取本来就给纯文本时（css 默认 / json），正文里合法的 `<` 是内容，
    不是标记 —— 过一遍解析器会把它连同后面一段一起吃掉。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-plain", [{"title": "第 1 章", "body": "他笑了 <3 然后走了\n第二行"}],
                may_html=False)
    _bind(db, book["id"], name)

    html = _chapter(client, auth_headers, book["id"], 0).json()["html"]
    assert "&lt;3" in html, html
    assert "然后走了" in html, "被吃掉了一段"
    assert html == "<p>他笑了 &lt;3 然后走了</p>\n<p>第二行</p>", html


def test_行内标签只剥标记不断段(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """`<b>` / `<em>` / `<a>` / `<span>` 只是包一层样式，**不是段落边界**。

    真机验证逮到的缺陷：早先用 `get_text("\\n")`（每个标签边界都插换行），
    一句「第二段：加粗与斜体标记都…」被 `<b>`/`<em>` 剁成四段，读起来是碎的。
    真实站点用 `<span>` 逐句包裹、用 `<a>` 标章节链接的遍地都是，所以这条钉的是**读得下去**。
    """
    _set_download(monkeypatch, tmp_path, enabled=True)
    body = ('<div class="content">\n  <p>甲<b>乙</b>丙</p>\n'
            '  <div>丁<span class="x">戊</span>己<br>庚</div>\n</div>')
    name = stub("stub-inline", [{"title": "第 1 章", "body": body}])
    _bind(db, book["id"], name)

    html = _chapter(client, auth_headers, book["id"], 0).json()["html"]
    assert html == "<p>甲乙丙</p>\n<p>丁戊己</p>\n<p>庚</p>", html


def test_行内标签不断段_解析器兜底路径(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """bs4 不可用时的兜底去标记同样**只认块级标签断行** —— 兜底也要读得下去。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-fallback", [{"title": "第 1 章",
                                   "body": "<p>甲<b>乙</b>丙</p><p>丁</p>"}])
    _bind(db, book["id"], name)

    import builtins

    real_import = builtins.__import__

    def no_bs4(name_, *a, **kw):
        if name_ == "bs4":
            raise ImportError("模拟没有 bs4")
        return real_import(name_, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_bs4)
    html = _chapter(client, auth_headers, book["id"], 0).json()["html"]
    assert html == "<p>甲乙丙</p>\n<p>丁</p>", html


def test_读一章会推进在线位置与已读章(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """跨客户端续读的唯一依据就是服务端这份记录 —— 两个客户端读到的必须是同一个 `pos`。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    local = _local_titles(book)
    name = stub("stub-pos", [{"title": t, "body": "甲"} for t in local])
    _bind(db, book["id"], name)

    _chapter(client, auth_headers, book["id"], 2)

    row = db.online_bind_get(book["id"])
    assert row["pos"] == 2 and row["seen"] == [2]
    assert _chapters(client, auth_headers, book["id"]).json()["pos"] == 2


def test_对得上才写本地进度且不带偏移(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """匹配成功 ⇒ **额外**写一份本地进度（本地阅读器也能续上）；
    ⚠️ 不带 `offset`：线上正文与本地正文不是同一份文本，字符偏移没有意义。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    local = _local_titles(book)
    name = stub("stub-prog", [{"title": t, "body": "甲"} for t in local])
    _bind(db, book["id"], name)

    body = _chapter(client, auth_headers, book["id"], 1).json()
    assert body["local_index"] == 1

    p = db.get_progress(book["id"], "")
    assert p["locator"] == 1
    assert p["percent"] == pytest.approx(round(1 * 100.0 / len(local), 2))
    assert not (p.get("cfi") or ""), "线上文本没有 CFI 可言"


def test_对不上就不写本地进度只在页内提示(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """宁可提示「对不上，本次不记本地进度」，也不能把进度写到错的位置上。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-nomatch", [{"title": f"无关{i}", "body": "甲"} for i in range(5)])
    _bind(db, book["id"], name)

    body = _chapter(client, auth_headers, book["id"], 0).json()
    assert body["local_index"] is None
    assert db.get_progress(book["id"], "") is None, "对不上就不该有本地进度"
    assert db.online_bind_get(book["id"])["pos"] == 0, "在线位置照记（跨客户端仍能续读）"


def test_章节号越界404(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-oob", [{"title": "第 1 章", "body": "甲"}])
    _bind(db, book["id"], name)

    assert _chapter(client, auth_headers, book["id"], 9).status_code == 404
    assert _chapter(client, auth_headers, book["id"], -1).status_code == 404


# ---------------------------------------------------------------------------
# 落盘与断网降级
# ---------------------------------------------------------------------------

def test_读过的章不再外呼(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-cache", [{"title": "第 1 章", "body": "甲"}])
    _bind(db, book["id"], name)

    first = _chapter(client, auth_headers, book["id"], 0).json()
    assert first["origin"] == "network"
    # 把源「换成会炸的」：缓存命中时它一次都不该被调到
    monkeypatch.setitem(REGISTRY, name,
                        make_src(name, [], fail_body=True, fail_links=True))
    again = _chapter(client, auth_headers, book["id"], 0)
    assert again.status_code == 200, again.text
    assert again.json()["origin"] == "cache"
    assert "甲" in again.json()["html"]


def test_断网时回落缓存并如实标stale(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """「无网络也能继续读」那条要求就落在这里：**刷新失败**不等于读不了，
    但必须如实说这一章是从本机缓存里拿的、什么时候抓的。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-offline", [{"title": "第 1 章", "body": "甲"}])
    _bind(db, book["id"], name)
    _chapter(client, auth_headers, book["id"], 0)
    monkeypatch.setitem(REGISTRY, name,
                        make_src(name, [], fail_body=True, fail_links=True))

    body = _chapter(client, auth_headers, book["id"], 0, refresh=1)
    assert body.status_code == 200, body.text
    out = body.json()
    assert out["origin"] == "cache" and out["stale"] is True
    assert "白名单" in out["error"], "失败原因要原文带出来，别把它藏起来"
    assert out["cached_at"] > 0, "横幅要能写出「抓取于 …」"


def test_缓存也没有就如实报错(client, auth_headers, book, monkeypatch, tmp_path, online_cache):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    monkeypatch.setitem(REGISTRY, "stub-dead", make_src("stub-dead", [], fail_links=True))
    _bind(db, book["id"], "stub-dead")

    r = _chapter(client, auth_headers, book["id"], 0)
    assert r.status_code == 502, r.text
    assert "白名单" in r.json()["detail"], "要原文，不要「读取失败」这种什么也没说的话"


def test_目录改版时清掉正文缓存(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """源站目录一换版，旧缓存就对应**另一份目录** —— 留着会让「第 1 章」显示成别的章，
    而且**没有任何报错**。宁可重取一遍。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    chs = [{"title": f"第 {i} 章", "body": f"旧正文{i}"} for i in range(1, 4)]
    name = stub("stub-rev", chs)
    _bind(db, book["id"], name)
    _chapter(client, auth_headers, book["id"], 0)
    _settle()
    assert online.has_body(book["id"], 0)

    # ① 只是**末尾追加**新章 ⇒ 旧缓存仍然有效，别清
    chs.append({"title": "第 4 章", "body": "新正文4"})
    _chapters(client, auth_headers, book["id"], refresh=1)
    assert online.has_body(book["id"], 0), "追加不该清掉已缓存的章"
    assert "旧正文1" in _chapter(client, auth_headers, book["id"], 0).json()["html"]

    # ② 换版（标题整体变了）⇒ 旧的正文缓存必须清掉
    monkeypatch.setitem(REGISTRY, name, make_src(
        name, [{"title": f"重排{i}", "body": f"新正文{i}"} for i in range(4)]))
    _chapters(client, auth_headers, book["id"], refresh=1)
    _settle()
    assert online.book_cache_stats(book["id"])["cached"] == 0
    assert "新正文" in _chapter(client, auth_headers, book["id"], 0).json()["html"]


def test_换源换页后不会读到上一页的目录与正文(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """缓存只按 `book_id` 分目录，而绑定可以换源 / 换页。

    不核对「这份缓存是哪一页的」，用户换了页之后读到的仍是**旧站点的目录与正文**，
    而且**没有任何报错** —— 他会以为「这个源就只有这些章」。这是本条用例钉住的东西。
    """
    _set_download(monkeypatch, tmp_path, enabled=True)
    a = stub("stub-pageA", [{"title": "甲章", "body": "甲的正文"}])
    _bind(db, book["id"], a, url="https://源站/page/1")
    assert "甲的正文" in _chapter(client, auth_headers, book["id"], 0).json()["html"]

    b = stub("stub-pageB", [{"title": "乙章", "body": "乙的正文"}])
    _bind(db, book["id"], b, url="https://源站/page/2")

    toc = _chapters(client, auth_headers, book["id"]).json()
    assert [e["title"] for e in toc["entries"]] == ["乙章"], "目录要按新的一页重取"
    assert toc["origin"] == "network"
    assert "乙的正文" in _chapter(client, auth_headers, book["id"], 0).json()["html"]
    assert online.book_cache_stats(book["id"], source=b, url="https://源站/page/2")["cached"] == 1


def test_刚换页时status不报上一页的缓存数(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """换页之后、还没读之前，盘上躺的是**上一页**的缓存 ——
    照报出去会显示成「还没读就缓存好了 N 章」。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    a = stub("stub-stA", [{"title": "甲章", "body": "甲的正文"}])
    _bind(db, book["id"], a, url="https://源站/page/1")
    _chapter(client, auth_headers, book["id"], 0)

    b = stub("stub-stB", [{"title": "乙章", "body": "乙的正文"}])
    _bind(db, book["id"], b, url="https://源站/page/2")

    cache = _status(client, auth_headers, book["id"]).json()["cache"]
    assert cache["cached"] == 0 and cache["total"] == 0


def test_预取下一章只在还没缓存时才跑(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """滚动模式读到章末要立刻接上下一章 —— 提前一步取回来，省掉一次往返。
    但**只在下一章确实没缓存**时跑，否则每读一章都白发一次请求。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-pf", [{"title": f"第 {i} 章", "body": f"甲{i}"} for i in range(1, 4)])
    _bind(db, book["id"], name)

    _chapter(client, auth_headers, book["id"], 0)
    _settle()
    assert online.has_body(book["id"], 1), "读第 1 章时该把第 2 章预取回来"
    assert not online.has_body(book["id"], 2), "不该顺手把整本都抓回来"


def test_预取失败不打扰读者(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    import asyncio

    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-pf2", [{"title": "第 1 章", "body": "甲"},
                             {"title": "第 2 章", "body": "乙"}], fail_body=True)
    _bind(db, book["id"], name)

    assert asyncio.run(online.prefetch(_Manager(), book["id"], name, "https://x/1", 1)) is False
    assert not online.has_body(book["id"], 1)


class _Manager:
    """只给 `_client` 的壳（桩源根本不用它做什么）—— 预取用例只走桩，不碰真网络。"""

    def _client(self, src):
        return _NullClient()

    def gate_reason(self, source=None, feature="download"):
        return ""


class _NullClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


# ---------------------------------------------------------------------------
# 写盘点：只许落在缓存目录
# ---------------------------------------------------------------------------

def test_缓存只落在缓存目录里(online_cache):  # noqa: ARG001
    """静态契约：本模块所有路径都必须在 `CACHE_DIR/online/` 之下。

    这条护栏的意义是防「顺手写点别的」—— 一旦在线读能写到书库 / 收书目录，
    它就变成了一个会改用户书文件的模块，而 `AGENTS.md` 的硬约束是**源不可变**。
    """
    root = online.cache_root().resolve()
    bid = "lib$写盘点"
    for p in (online.book_dir(bid), online._index_path(bid),
              online._full_path(bid), online._chapter_path(bid, 3)):
        assert root in p.resolve().parents, f"{p} 落到缓存目录之外了"


def test_模块源码里不出现别的写盘入口():
    """更硬的一条：源码里**连字眼都不该有** `INPUT_DIR` / `OUTPUT_DIR` /
    `LIBRARY_SOURCE_DIR` / 回收站 / `shutil.move`。

    只测路径函数的返回值不够 —— 真正危险的是「某天有人顺手在这里加一句
    `(output_dir / name).write_text(...)`」。出现这些名字就说明它已经伸手到
    书库 / 收书目录上了，而 `AGENTS.md` 的硬约束是**源不可变**。
    """
    import pathlib
    src = pathlib.Path(online.__file__).read_text(encoding="utf-8")
    for bad in ("INPUT_DIR", "OUTPUT_DIR", "LIBRARY_SOURCE_DIR", "recycle_dir",
                "shutil.move", "os.remove", "os.unlink"):
        assert bad not in src, f"在线阅读模块不该出现 {bad}（它只许写缓存目录）"


def test_清在线缓存不碰别的东西(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """`/api/online/cache/clear` 只清在线缓存 —— AI 分章缓存不该陪葬
    （清掉它下一本书要重跑一遍分章，用户点的不是这个）。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-purge", [{"title": "第 1 章", "body": "甲"}])
    _bind(db, book["id"], name)
    _chapter(client, auth_headers, book["id"], 0)
    assert online.book_cache_stats(book["id"])["cached"] == 1

    other = config.CACHE_DIR / "别的缓存"
    other.mkdir(parents=True, exist_ok=True)
    (other / "x.json").write_text("{}", encoding="utf-8")

    r = client.post("/api/online/cache/clear", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["removed_books"] == 1 and r.json()["removed_bytes"] > 0
    assert online.book_cache_stats(book["id"])["cached"] == 0
    assert (other / "x.json").is_file(), "只清在线缓存，别的缓存不动"
    assert library.by_id(book["id"]) is not None

    # 缓存清了，书还在 ⇒ 再读一次照常（只是要重新跑一趟网络）
    assert _chapter(client, auth_headers, book["id"], 0).status_code == 200


def test_维护页报出在线缓存用量(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-maint", [{"title": "第 1 章", "body": "甲"}])
    _bind(db, book["id"], name)
    _chapter(client, auth_headers, book["id"], 0)

    dirs = client.get("/api/maintenance", headers=auth_headers).json()["dirs"]
    assert dirs["online_cache"]["chapters"] == 1
    assert dirs["online_cache"]["bytes"] > 0
    assert dirs["online_cache"]["max_bytes"] == online.MAX_BYTES


# ---------------------------------------------------------------------------
# single 模式（整本一页的源）
# ---------------------------------------------------------------------------

def test_整本一页的源也能逐章读(client, auth_headers, book, monkeypatch, tmp_path, online_cache, stub):  # noqa: ARG001
    """不少书源就是「一页全文」，用户要的是「接我给的书源」——
    这种源**本期支持**：整本取回后按既有分章规则切开，逐章读。
    代价是缓存被清掉后要重取整本（不是错误，是源站形态决定的）。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-single", [{"title": f"第 {i} 章", "body": f"整本里的第{i}段"}
                                for i in range(1, 4)], mode="single")
    _bind(db, book["id"], name)

    toc = _chapters(client, auth_headers, book["id"]).json()
    assert toc["single"] is True and toc["total"] == 3
    assert [e["title"] for e in toc["entries"]] == ["第 1 章", "第 2 章", "第 3 章"]

    body = _chapter(client, auth_headers, book["id"], 2).json()
    assert "整本里的第3段" in body["html"]
    assert online.book_cache_stats(book["id"])["cached"] == 3, "整本一次取回 ⇒ 三章都在缓存里"

    # 再读任一章都是缓存命中，不必再整本取一次
    assert _chapter(client, auth_headers, book["id"], 0).json()["origin"] == "cache"


# ---------------------------------------------------------------------------
# 对齐判据本身（`_same_or_extended` 是缓存层唯一自己写的判据）
# ---------------------------------------------------------------------------

def test_目录延伸判据():
    a = [{"title": "第 1 章", "url": "u1"}, {"title": "第 2 章", "url": "u2"}]
    assert online._same_or_extended(a, a + [{"title": "第 3 章", "url": "u3"}]) is True
    assert online._same_or_extended([], a) is True, "没有旧目录 ⇒ 当延伸（没什么可清的）"
    assert online._same_or_extended(a, a[:1]) is False, "变短了 ⇒ 不是延伸"
    assert online._same_or_extended(a, [{"title": "换个名", "url": "u1"}, a[1]]) is False
    assert online._same_or_extended(a, [{"title": "第 1 章", "url": "别的"}, a[1]]) is False


def test_对齐用的标题归一与书城目录同一份():
    """`align_online` 与 `build_pairs` 必须用同一个 `norm_title` ——
    两套归一的表现是「搜索匹配上了、章节却一条都对不上」，两边各自看着都对。"""
    from novelforge.sources import toc_sources
    assert toc_sources.norm_title is reading_list.norm_title


# ---------------------------------------------------------------------------
# 真·规则源（上面那些用例用的都是桩 —— 取数那条链必须真的接在 rules 上）
# ---------------------------------------------------------------------------

class _StubClient:
    def __init__(self, pages: dict):
        self.pages = pages

    async def get_text(self, url: str) -> str:
        return self.pages[url]


def _rule_src(**book):
    from novelforge.sources import rules as rules_mod
    cls = rules_mod.make_rule_class({"name": "规则源", "domains": ["d.com"], "book": book})
    return cls()


def test_规则源的在线读钩子接在取数链上():
    """在线读**不自己解析页面**：它调的是 `rules.chapter_links` / `chapter_body`。
    这条用例真的走一遍规则源，钉住「接线接对了」——
    上面那些桩用例只能证明本模块的编排正确，证明不了它接到了哪一层。"""
    import asyncio

    src = _rule_src(mode="toc", toc={"mode": "css", "container": "a"},
                    content={"mode": "css", "container": "div.c"})
    assert src.online_support() == "" and src.online_mode() == "toc"
    assert src.content_may_be_html() is False, "css 默认走 get_text() ⇒ 本来就是纯文本"

    pages = {"https://d.com/b": '<a href="/c1">第一话</a><a href="/c2">第二话</a>',
             "https://d.com/c1": '<div class="c">甲&amp;乙</div>'}
    c = _StubClient(pages)
    assert asyncio.run(src.chapter_links(c, "https://d.com/b")) == [
        {"title": "第一话", "url": "https://d.com/c1"},
        {"title": "第二话", "url": "https://d.com/c2"},
    ]
    assert asyncio.run(src.chapter_body(c, "https://d.com/c1")) == "甲&乙"


def test_规则缺正文提取时不放行且说清缺哪一样():
    """「这本书读不了」与「这条规则没写正文提取」对用户是两件事 ——
    后者要去书源管理里补规则，含糊其辞会让人以为源站坏了。"""
    no_content = _rule_src(mode="toc", toc={"mode": "css", "container": "a"})
    assert "book.content" in no_content.online_support()

    no_toc = _rule_src(mode="toc", content={"mode": "css", "container": "div.c"})
    assert "book.toc" in no_toc.online_support()

    # 整页全文（single）的源没有 `book.toc` 却是**能读**的（取回后现切）
    single = _rule_src(content={"mode": "css", "container": "div.c"})
    assert single.online_support() == "" and single.online_mode() == "single"


def test_正则与js正文按可能含标记处理():
    """该剥没剥 ⇒ 源站标记进了 `v-html`；不该剥却剥了 ⇒ 正文被解析器吃掉一段。
    判据在规则源的 `content_may_be_html()` 上，本模块只消费它。"""
    assert _rule_src(content={"mode": "regex", "pattern": "x"}).content_may_be_html() is True
    assert _rule_src(content={"mode": "js", "script": "return result;"}).content_may_be_html() is True
    assert _rule_src(content={"mode": "css", "container": "div.c",
                              "html": True}).content_may_be_html() is True
    assert _rule_src(content={"mode": "json", "path": "$.t"}).content_may_be_html() is False

