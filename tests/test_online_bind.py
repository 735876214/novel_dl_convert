"""第 93 期：在线阅读的**源绑定**（`online_bind` 表 + `POST /api/books/{bid}/online/bind`）。

绑定是本期第一块地基：没有它，「在线阅读」就只剩「从书源下载来的书」能用 ——
而用户要的是「**接我给的书源**」，任何一本在库的书都要能绑。

这里钉住六件事：

1. **闸门只有一条**（`download.enabled`，第 93 期删掉公版闸门后）：关掉时 400、
   文案逐字来自 `gate_reason()`，**且不许碰业务逻辑**（搜索桩会直接失败）；
2. **未知书源当场拒**（400）：与 `/api/download` 同一口径；
3. **自动匹配复用 `toc_sources.best_match`**，匹配不上**如实报错、不落库** ——
   绑错的代价是整本读到别人的书，比「没绑上」严重得多；
4. **手动粘 URL 跳过搜索**（用户指定即确定，置信度 1.0）；
5. **换页才清零**：同一页重复绑定保留在线位置（`pos`）与自动落地凭据（`auto_task`），
   换源 / 换页则清零 —— 那三样都是「在**那个**书页上读到哪儿」的记录；
6. **绑定是用户的声明，不是磁盘的投影**：改名要跟着搬（`REMAP_TABLES`）、
   书没了可被孤儿清理（`ORPHAN_TABLES`）—— 与 store_toc / toc_map 那两张缓存表**相反**。

全程零网络：书源一律是本文件的桩。
"""
import pytest

from novelforge import config
from novelforge.core import db, epub_builder, library
from novelforge.sources import REGISTRY
from novelforge.sources.base import SourceAdapter


async def _never_fetch(self, client, item):  # noqa: ANN001
    raise AssertionError("绑定用例不该取书")


def _src(name: str, items=(), error=None) -> type:
    """只实现 `search` 的桩源（绑定时只用到它）。`error` 非空则搜索抛这个异常。"""

    async def search(self, client, title):  # noqa: ANN001, ARG001
        if error is not None:
            raise error
        return [dict(it) for it in items]

    return type(f"Stub_{name}", (SourceAdapter,), {
        "name": name, "display_name": f"{name} 展示名",
        "search": search, "fetch_book": _never_fetch,
    })


@pytest.fixture
def book(tmp_path, make_library, isolated):  # noqa: ARG001
    """一本真 EPUB（书名 / 作者都在元数据里 —— 自动匹配要拿它们去比）。"""
    root = tmp_path / "onlinelib"
    make_library("onlinelib", "在线库", "ebook", root)
    epub_builder.build_epub(
        {"title": "三体", "author": "刘慈欣", "language": "zh"},
        [{"title": f"第 {i} 章", "body_html": "<p>正文</p>"} for i in range(1, 4)],
        str(root / "三体.epub"),
    )
    library.invalidate()
    return library.books("onlinelib")[0]


@pytest.fixture
def stub(monkeypatch):
    """把一个桩源塞进 REGISTRY（用例结束自动还原，不污染全局书源表）。"""
    def _install(name: str, items=(), error=None) -> str:
        monkeypatch.setitem(REGISTRY, name, _src(name, items, error))
        return name
    return _install


def _set_download(monkeypatch, tmp_path, *, enabled: bool) -> None:
    """把 settings.json 覆盖层指到本用例的临时文件（不动真实配置）。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"download": {"enabled": enabled}})


def _bind(client, headers, bid, **payload):
    return client.post(f"/api/books/{bid}/online/bind", headers=headers, json=payload)


# ---------------------------------------------------------------------------
# 入口拦截
# ---------------------------------------------------------------------------

def test_未知书籍返回404(client, auth_headers, book, monkeypatch, tmp_path):  # noqa: ARG001
    _set_download(monkeypatch, tmp_path, enabled=True)
    r = _bind(client, auth_headers, "根本不存在", source="stub-x")
    assert r.status_code == 404, r.text
    assert "书籍不存在" in r.json()["detail"]


def test_闸门关闭时绑定被拒(client, auth_headers, book, monkeypatch, tmp_path):
    """拒绝必须发生在**业务逻辑之前**：搜索桩会直接失败，被拦时它一次都不许被调到。"""
    _set_download(monkeypatch, tmp_path, enabled=False)

    async def _must_not_run(self, client, title):  # noqa: ANN001
        raise AssertionError("闸门已经拒了，却还是去搜索了")

    monkeypatch.setitem(REGISTRY, "stub-x", type(
        "StubMustNotRun", (SourceAdapter,),
        {"name": "stub-x", "search": _must_not_run, "fetch_book": _never_fetch}))

    r = _bind(client, auth_headers, book["id"], source="stub-x")

    assert r.status_code == 400, r.text
    assert "下载功能未开启" in r.json()["detail"]
    assert "网络与下载" in r.json()["detail"], "拒绝要给出出口（设置 → 网络与下载）"
    assert db.online_bind_get(book["id"]) is None, "被拒的绑定不该留下任何登记"


def test_未知书源被拒(client, auth_headers, book, monkeypatch, tmp_path):
    _set_download(monkeypatch, tmp_path, enabled=True)
    r = _bind(client, auth_headers, book["id"], source="根本不存在的源")
    assert r.status_code == 400, r.text
    assert "未知书源" in r.json()["detail"]
    assert db.online_bind_get(book["id"]) is None


# ---------------------------------------------------------------------------
# 自动匹配 / 手动指定
# ---------------------------------------------------------------------------

def test_自动匹配成功则落库(client, auth_headers, book, monkeypatch, tmp_path, stub):
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-ok", items=[{"title": "别的一本", "author": "某人", "url": "https://x/0"},
                                  {"title": "三体", "author": "刘慈欣", "url": "https://x/9"}])

    r = _bind(client, auth_headers, book["id"], source=name)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == "https://x/9" and body["manual"] is False
    assert body["confidence"] == 1.0, "书名与作者都对上 ⇒ 0.8 + 0.2"
    row = db.online_bind_get(book["id"])
    assert row["source"] == name and row["url"] == "https://x/9"
    assert row["library_id"] == book["library_id"], "绑定记下库归属（跨库同名时才有判据）"
    assert row["pos"] == 0 and row["seen"] == [] and row["auto_task"] == ""


def test_匹配不上如实报错且不落库(client, auth_headers, book, monkeypatch, tmp_path, stub):
    """宁可说「没匹配到」：绑错的代价是整本读到别人的书，比没绑上严重得多。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-miss", items=[{"title": "完全不相干", "author": "别人", "url": "https://x/1"}])

    r = _bind(client, auth_headers, book["id"], source=name)

    assert r.status_code == 502, r.text
    detail = r.json()["detail"]
    assert "没匹配到" in detail and "三体" in detail
    assert "置信度" in detail and "阈值" in detail, "要给出理由与门槛，否则用户不知道差多少"
    assert "手动" in detail, "要给出出口（手动填书页地址）"
    assert db.online_bind_get(book["id"]) is None, "没匹配上就不该留下绑定"


def test_手动粘URL跳过搜索(client, auth_headers, book, monkeypatch, tmp_path):
    """用户指定书页地址 = 确定，不再去猜（这也是搜索 404 的站点唯一的绑定方式）。"""
    _set_download(monkeypatch, tmp_path, enabled=True)

    async def _must_not_run(self, client, title):  # noqa: ANN001
        raise AssertionError("用户已经指定了书页地址，不该再去搜索")

    monkeypatch.setitem(REGISTRY, "stub-manual", type(
        "StubManual", (SourceAdapter,),
        {"name": "stub-manual", "search": _must_not_run, "fetch_book": _never_fetch}))

    r = _bind(client, auth_headers, book["id"], source="stub-manual",
              url="https://x/page/123")

    assert r.status_code == 200, r.text
    assert r.json()["manual"] is True and r.json()["confidence"] == 1.0
    assert db.online_bind_get(book["id"])["url"] == "https://x/page/123"


def test_搜索失败时把源站异常原文交给用户(client, auth_headers, book, monkeypatch, tmp_path, stub):
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-boom", error=RuntimeError("连接失败：域名不在白名单内"))

    r = _bind(client, auth_headers, book["id"], source=name)

    assert r.status_code == 502, r.text
    assert "白名单" in r.json()["detail"], "原因要原文，不要「绑定失败」这种什么也没说的话"
    assert db.online_bind_get(book["id"]) is None


# ---------------------------------------------------------------------------
# 覆盖与清零口径
# ---------------------------------------------------------------------------

def test_重复绑同一页不清零在线位置(client, auth_headers, book, monkeypatch, tmp_path, stub):
    """用户再点一次「绑定」不该把读到哪儿忘掉 —— 那是同一个事实。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    name = stub("stub-same", items=[{"title": "三体", "author": "刘慈欣", "url": "https://x/9"}])
    _bind(client, auth_headers, book["id"], source=name)
    db.online_bind_set_pos(book["id"], 7)
    db.online_bind_mark_seen(book["id"], 7)
    db.online_bind_set_auto_task(book["id"], "tid-1")

    _bind(client, auth_headers, book["id"], source=name)

    row = db.online_bind_get(book["id"])
    assert row["pos"] == 7 and row["seen"] == [7], "同一页 ⇒ 在线位置与已读记录都留着"
    assert row["auto_task"] == "tid-1", "自动落地只触发一次，凭据不能因为重绑被抹掉"


def test_换成另一页则清零在线位置与自动落地凭据(client, auth_headers, book, monkeypatch, tmp_path, stub):
    """换了书页还留着旧位置，读者一打开就会被空降到别的书的某个位置；
    而旧 `auto_task` 会让新绑的源再也触发不了自动落地（明明本地还是空的）。"""
    _set_download(monkeypatch, tmp_path, enabled=True)
    stub("stub-a")
    stub("stub-b")
    assert _bind(client, auth_headers, book["id"],
                 source="stub-a", url="https://x/old").status_code == 200
    db.online_bind_set_pos(book["id"], 40)
    db.online_bind_mark_seen(book["id"], 40)
    db.online_bind_set_auto_task(book["id"], "tid-old")

    r = _bind(client, auth_headers, book["id"], source="stub-b", url="https://y/new")
    assert r.status_code == 200, r.text

    row = db.online_bind_get(book["id"])
    assert row["source"] == "stub-b" and row["url"] == "https://y/new"
    assert row["pos"] == 0 and row["seen"] == [] and row["auto_task"] == "", row


def test_解绑只删登记而不动任何文件(client, auth_headers, book, monkeypatch, tmp_path, stub):
    _set_download(monkeypatch, tmp_path, enabled=True)
    stub("stub-a")
    assert _bind(client, auth_headers, book["id"],
                 source="stub-a", url="https://x/1").status_code == 200

    assert db.online_bind_clear(book["id"]) == 1
    assert db.online_bind_get(book["id"]) is None
    assert library.by_id(book["id"]) is not None, "解绑与书本身无关"


# ---------------------------------------------------------------------------
# 表本身的纪律：搬迁 / 孤儿 / seen 上限（第 36 期那套契约的延伸）
# ---------------------------------------------------------------------------

def test_改名时绑定跟着搬(isolated):  # noqa: ARG001
    """绑定是**用户显式说过的**「这本书在这个源这一页读」——
    改名 / 换库后不搬，用户就得自己重新想起来当初是在哪个站读的这本。"""
    old, new = "lib$oldbook", "lib$newbook"
    db.online_bind_put(old, library_id="lib-a", source="s", url="https://x/1", title="三体")
    db.online_bind_set_pos(old, 12)

    moved = db.remap_book_id(old, new)

    assert moved["online_bind"] == 1, moved
    assert db.online_bind_get(old) is None
    assert db.online_bind_get(new)["pos"] == 12, "在线位置也要跟着走（否则跨客户端续读断在这里）"


def test_书消失后绑定可被孤儿清理(isolated):  # noqa: ARG001
    assert "online_bind" in db.ORPHAN_TABLES
    db.online_bind_put("lib$gone", source="s", url="https://x/1")

    refs = db.book_id_refs()
    assert refs["online_bind"] == ["lib$gone"]

    removed = db.delete_orphans({"online_bind": ["lib$gone"]})
    assert removed["online_bind"] == 1
    assert db.online_bind_get("lib$gone") is None
    assert db.online_bind_list() == []


def test_已读记录去重且封顶(isolated):  # noqa: ARG001
    """去重是必须的：反复翻回第 2 章若每次都算一章，「读满 5 章」就成了「翻 5 次」。"""
    bid = "lib$seen"
    db.online_bind_put(bid, source="s", url="https://x/1")
    for idx in (0, 1, 2, 1, 0):
        seen = db.online_bind_mark_seen(bid, idx)
    assert seen == [2, 1, 0], "同一章只记一次，顺序是「最近读过的在后」"

    for idx in range(200):
        db.online_bind_mark_seen(bid, idx)
    row = db.online_bind_get(bid)
    assert len(row["seen"]) == db.ONLINE_SEEN_MAX, "行不该随阅读无限长大"
    assert row["seen"][-1] == 199, "留下的是最近的痕迹"


def test_非法入参不写坏数据(isolated):  # noqa: ARG001
    bid = "lib$bad"
    db.online_bind_put(bid, source="s", url="https://x/1")
    db.online_bind_set_pos(bid, "不是数字")
    assert db.online_bind_get(bid)["pos"] == 0
    assert db.online_bind_mark_seen(bid, "第2章") == []


def test_见到的坏JSON当没读过(isolated):  # noqa: ARG001
    """手改库 / 半写坏的行不该让详情页炸掉 —— 读不出来就当「还没读过」。"""
    bid = "lib$json"
    db.online_bind_put(bid, source="s", url="https://x/1")
    c = db._connect()
    with db._lock:
        c.execute("UPDATE online_bind SET seen=? WHERE book_id=?", ("{坏", bid))
        c.commit()
    assert db.online_bind_get(bid)["seen"] == []
