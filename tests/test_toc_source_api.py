"""第 85 期批次 B：书城目录来源的接口层（闸门 / 落库 / 覆盖生效 / 还原）。

四个关键行为各钉一条：

1. **闸门拦在业务逻辑之前**：取目录未开启时 `POST /api/toc/fetch` 必须 400，且
   `toc_sources.fetch_toc` 一次都不许被调到（与第 71 期下载闸门同一口径、同一个入口）；
2. **两个开关各判各的**：关掉「下载」不影响显式打开了「取目录」的用户 ——
   「取一份章节目录」与「下载整本正文」本来就是两个动作；
3. **失败也落库并如实回显**：`ok=0` + 原因原文要能在详情页读到，
   否则用户只会看到「点了没反应」（也免得每次开详情页都重新外呼一遍）；
4. **覆盖只有一条生效路径**：详情页的章节标题确实变成书城那份，「还原为本地目录」之后
   又确实回到本地那份。

全程零网络：`toc_sources.fetch_toc` 一律换成桩。
"""
import pytest

from novelforge import config
from novelforge.core import epub_builder, library
from novelforge.sources import toc_sources


def _set_toc(monkeypatch, tmp_path, *, toc_enabled: bool, download: bool = False) -> None:
    """把 settings.json 覆盖层指到本用例的临时文件（不动真实配置、也不影响别的用例）。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"download": {"enabled": download, "toc_enabled": toc_enabled}})


@pytest.fixture
def book(tmp_path, make_library, isolated):  # noqa: ARG001
    """一本真 EPUB（3 章，标题是 `第 N 章` 这种兜底名 —— 正是「本地目录不清楚」的情形）。"""
    root = tmp_path / "toclib"
    make_library("toclib", "目录库", "ebook", root)
    epub_builder.build_epub(
        {"title": "三体", "author": "刘慈欣", "language": "zh"},
        [{"title": f"第 {i} 章", "body_html": "<p>正文</p>"} for i in range(1, 4)],
        str(root / "三体.epub"),
    )
    library.invalidate()
    return library.books("toclib")[0]


#: 本地那本真 EPUB 的目录：`epub_builder` 会先放一页书名页（标题 = 书名），再是 3 章。
_LOCAL_TITLES = ["三体", "第 1 章", "第 2 章", "第 3 章"]

#: 书城那份：书名页同名 ⇒ 第一趟「标题相等」直接配上；其余同名不同形 ⇒ 走第二趟顺序对齐
#: （两边**剩下条数一样多**才配 —— 这里正好各剩 3 条）。
_STORE = [{"title": "三体", "depth": None},
          {"title": "第一章 科学边界", "depth": None},
          {"title": "第二章 台球", "depth": None},
          {"title": "第三章 射手", "depth": None}]


def _ok_stub(entries=None):
    async def _f(mgr, source, *, book, url="", query=""):  # noqa: ANN001, ARG001
        return {"source": source, "ok": True, "note": "", "store_ref": "https://x/1",
                "matched_title": "三体", "matched_author": "刘慈欣", "confidence": 1.0,
                "manual": bool(url), "entries": list(_STORE if entries is None else entries)}
    return _f


def _titles(detail: dict) -> list:
    return [c["title"] for g in detail.get("chapters") or [] for c in g.get("chapters") or []]


def test_取目录未开启时被闸门拦下且不碰业务逻辑(client, auth_headers, book, monkeypatch, tmp_path):
    _set_toc(monkeypatch, tmp_path, toc_enabled=False)

    async def _must_not_run(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("闸门已经拒了，却还是去取目录了")

    monkeypatch.setattr(toc_sources, "fetch_toc", _must_not_run)
    r = client.post("/api/toc/fetch", headers=auth_headers,
                    json={"book_id": book["id"], "source": "fanqie"})
    assert r.status_code == 400, r.text
    assert "取目录未开启" in r.json()["detail"]
    assert "网络与下载" in r.json()["detail"], "拒绝要带出口（设置 → 网络与下载）"


def test_开启后取目录成功_详情页用上书城标题(client, auth_headers, book, monkeypatch, tmp_path):
    _set_toc(monkeypatch, tmp_path, toc_enabled=True)
    monkeypatch.setattr(toc_sources, "fetch_toc", _ok_stub())
    r = client.post("/api/toc/fetch", headers=auth_headers,
                    json={"book_id": book["id"], "source": "fanqie"})
    assert r.status_code == 200, r.text
    assert r.json()["mapped"] == 4 and r.json()["total"] == 4

    detail = client.get(f"/api/books/{book['id']}", headers=auth_headers).json()
    assert _titles(detail) == [e["title"] for e in _STORE], "详情页必须用上书城那份标题"
    assert detail["toc_applied"] == "fanqie"
    row = detail["toc_sources"][0]
    assert row["ok"] is True and row["mapped"] == 4
    assert row["label"] == "番茄小说" and row["entry_count"] == 4
    assert "entries" not in row, "状态清单不该把整份书城目录再回传一遍"


def test_失败也落库并在详情页如实回显(client, auth_headers, book, monkeypatch, tmp_path):
    _set_toc(monkeypatch, tmp_path, toc_enabled=True)

    async def _fail(mgr, source, *, book, url="", query=""):  # noqa: ANN001
        return {"source": source, "ok": False, "note": "在「番茄小说」里没匹配到《三体》",
                "store_ref": "", "matched_title": "", "matched_author": "",
                "confidence": 0.2, "manual": False, "entries": []}

    monkeypatch.setattr(toc_sources, "fetch_toc", _fail)
    r = client.post("/api/toc/fetch", headers=auth_headers,
                    json={"book_id": book["id"], "source": "fanqie"})
    assert r.status_code == 502, r.text
    assert "没匹配到" in r.json()["detail"]

    detail = client.get(f"/api/books/{book['id']}", headers=auth_headers).json()
    assert detail["toc_applied"] == "", "没取到就仍该用本地目录"
    assert _titles(detail) == _LOCAL_TITLES, "负结果不许改任何标题"
    row = detail["toc_sources"][0]
    assert row["ok"] is False and "没匹配到" in row["note"], "上次为什么没取到要能读到"


def test_还原为本地目录(client, auth_headers, book, monkeypatch, tmp_path):
    _set_toc(monkeypatch, tmp_path, toc_enabled=True)
    monkeypatch.setattr(toc_sources, "fetch_toc", _ok_stub())
    client.post("/api/toc/fetch", headers=auth_headers,
                json={"book_id": book["id"], "source": "fanqie"})

    r = client.delete(f"/api/toc/{book['id']}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["cleared"] == 1
    detail = client.get(f"/api/books/{book['id']}", headers=auth_headers).json()
    assert _titles(detail) == _LOCAL_TITLES, "还原之后必须回到本地那份目录"
    assert detail["toc_applied"] == "" and detail["toc_sources"] == []


def test_两个开关各判各的(client, auth_headers, book, monkeypatch, tmp_path):
    """关掉「下载」不影响显式打开了「取目录」的用户 —— 它们本来就是两个动作。"""
    _set_toc(monkeypatch, tmp_path, toc_enabled=True, download=False)
    monkeypatch.setattr(toc_sources, "fetch_toc", _ok_stub())
    assert client.post("/api/toc/fetch", headers=auth_headers,
                       json={"book_id": book["id"], "source": "fanqie"}).status_code == 200
    s = client.post("/api/search", headers=auth_headers, json={"title": "三体"})
    assert s.status_code == 400 and "下载功能未开启" in s.json()["detail"]


def test_来源清单_闸门关时每个来源都说清为什么不能用(client, auth_headers, monkeypatch, tmp_path):
    _set_toc(monkeypatch, tmp_path, toc_enabled=False)
    body = client.get("/api/toc/sources", headers=auth_headers).json()
    assert body["enabled"] is False and "取目录未开启" in body["reason"]
    assert body["items"], "清单不能是空的"
    assert all(not it["usable"] for it in body["items"])
    assert all(it["blocked_reason"] for it in body["items"]), "不许有「不可用但不给原因」的来源"


def test_来源清单_闸门开时按档位如实标注(client, auth_headers, monkeypatch, tmp_path):
    _set_toc(monkeypatch, tmp_path, toc_enabled=True)
    rows = {it["id"]: it for it in
            client.get("/api/toc/sources", headers=auth_headers).json()["items"]}
    assert rows["fanqie"]["usable"] is True
    assert rows["fanqie"]["verified"] is False, "本机没验证过就必须如实标出来"
    assert rows["weread"]["usable"] is False
    assert rows["weread"]["label"] == "微信读书"
    assert "只登记" in rows["weread"]["blocked_reason"], "不可用就要说清为什么（这里是「本批未支持」）"


def test_未知书号即时拒绝(client, auth_headers, monkeypatch, tmp_path):
    _set_toc(monkeypatch, tmp_path, toc_enabled=True)   # 闸门放行，考的是书号校验
    r = client.post("/api/toc/fetch", headers=auth_headers,
                    json={"book_id": "根本没有这本书", "source": "fanqie"})
    assert r.status_code == 404 and "书籍不存在" in r.json()["detail"]
