"""外部服务同步（第 52 期）：匹配口径、状态映射、Hardcover errors 判定、Readwise 请求形状与计数。

⚠️ 本机**没有**三家凭据，故全部用打桩的 httpx 客户端钉住请求形状与判定纪律，
不做真实外呼。三条最容易被写错、也最贵的纪律各有专门用例：
  1. Hardcover 鉴权失败也可能是 **200 + errors** ⇒ 必须判 failed，不能判成功；
  2. Readwise **204 才是成功**（200 也接受，401 必须判失败并逐条计数）；
  3. StoryGraph 校验里**网络异常不能算成「Cookie 无效」**。
"""
import httpx
import pytest

from novelforge.core import sync


# ---------------- 打桩：httpx.Client 替身 ----------------

class _Resp:
    def __init__(self, status=200, data=None, url="https://fake/", text="", headers=None):
        self.status_code = status
        self._data = data
        self.url = url
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


class _Stub:
    """按 URL 给响应的 httpx.Client 替身；记录全部请求供断言。"""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        self.calls.append(("post", url, json, headers))
        return self.handler(url, json)

    def get(self, url, cookies=None, headers=None):
        self.calls.append(("get", url, None, headers))
        return self.handler(url, None)


class _DB:
    """db 替身：只提供同步层用到的那几个读函数与任务写入。"""

    def __init__(self, statuses=None, ratings=None, reviews=None, annos=None):
        self.statuses = statuses or {}
        self.ratings = ratings or {}
        self.reviews = reviews or {}
        self.annos = annos or {}
        self.tasks = []

    def all_statuses(self):
        return self.statuses

    def all_ratings(self):
        return self.ratings

    def all_reviews(self):
        return self.reviews

    def list_annotations(self, book_id):
        return list(self.annos.get(book_id, []))

    def task_create(self, tid, type_, title, detail="", **kw):
        self.tasks.append((tid, type_, title))

    def task_update(self, tid, **kw):
        pass


def _book(bid="b1", title="三体", author="刘慈欣", isbn="9787536692930"):
    return {"id": bid, "name": f"{title}.epub", "title": title, "author": author, "isbn": isbn}


def _use(monkeypatch, dbstub, books, token="tok"):
    monkeypatch.setattr(sync, "db", dbstub)
    monkeypatch.setattr(sync, "_local_books", lambda: books)
    monkeypatch.setattr(sync, "_config",
                        lambda: {"integrations": {"hardcover": {"token": token},
                                                  "readwise": {"token": token},
                                                  "storygraph": {}}})
    monkeypatch.setattr(sync, "_annotations_of",
                        lambda bid: dbstub.list_annotations(bid))


def _patch_client(monkeypatch, handler):
    stub = _Stub(handler)
    monkeypatch.setattr(sync.httpx, "Client", lambda *a, **k: stub)
    return stub


# ---------------- 归一化与状态映射 ----------------

def test_归一化_书名与作者():
    assert sync._norm_text("三体（全集）") == sync._norm_text("三体")
    assert sync._norm_text("Ｔｈｅ　Ｈｏｂｂｉｔ") == "thehobbit"
    assert sync._norm_text("Dune: Book 1") == sync._norm_text("dune book 1")
    # 作者只取第一作者，且不做姓名倒序（中文倒序会把「张三」改成「三张」）
    assert sync._norm_author("刘慈欣, 张三") == "刘慈欣"
    assert sync._norm_author("Ursula K. Le Guin") == "ursulakleguin"


def test_状态映射只含三个可确定取值():
    """paused / abandoned 在 Hardcover 没有一一对应状态 ⇒ 宁可不报，也不挑近似值写错。"""
    assert set(sync.STATUS_IDS) == {"unread", "reading", "finished"}
    assert sync.STATUS_IDS["finished"] == 3


# ---------------- 预览（零外呼）----------------

def test_preview_readwise_按批注计数且不外呼(monkeypatch):
    dbstub = _DB(statuses={"b1": "reading"},
                 annos={"b1": [{"id": 1, "quote": "q1", "chapter": 1, "created_at": 0},
                               {"id": 2, "quote": "q2", "chapter": 2, "created_at": 0}]})
    _use(monkeypatch, dbstub, [_book()])

    def _boom(url, json):
        raise AssertionError("预览不允许外呼")

    _patch_client(monkeypatch, _boom)
    p = sync.preview("readwise")
    assert p["books"] == 1 and p["total"] == 2 and p["remote_match_at_sync"] is False
    # Hardcover 的匹配在同步时才做 ⇒ 预览如实标注，不假装已匹配
    assert sync.preview("hardcover")["remote_match_at_sync"] is True


# ---------------- Hardcover ----------------

def test_hardcover_200加errors判失败不判成功(monkeypatch):
    dbstub = _DB(statuses={"b1": "finished"})
    _use(monkeypatch, dbstub, [_book()])
    _patch_client(monkeypatch, lambda url, json: _Resp(
        200, {"errors": [{"message": "access denied"}]}))

    r = sync.run("hardcover")
    assert r["pushed"] == 0 and len(r["failed"]) == 1
    assert r["skipped"] == []


def test_hardcover_搜索无结果算跳过(monkeypatch):
    dbstub = _DB(statuses={"b1": "reading"})
    _use(monkeypatch, dbstub, [_book()])
    _patch_client(monkeypatch, lambda url, json: _Resp(
        200, {"data": {"search": {"ids": []}}}))

    r = sync.run("hardcover")
    assert r["pushed"] == 0 and r["failed"] == []
    assert r["skipped"] and "未匹配" in r["skipped"][0]["reason"]


def test_hardcover_命中后带上状态评分书评(monkeypatch):
    dbstub = _DB(statuses={"b1": "reading"}, ratings={"b1": 5}, reviews={"b1": "很好看"})
    _use(monkeypatch, dbstub, [_book()])

    seen = {}

    def handler(url, json):
        # 先 search 拿到 id，再 insert_user_book
        if "search" in str(json.get("query", "")):
            return _Resp(200, {"data": {"search": {"ids": [123]}}})
        seen.update(json["variables"]["obj"])
        return _Resp(200, {"data": {"insert_user_book": {"user_book": {"id": 1}}}})

    stub = _patch_client(monkeypatch, handler)
    r = sync.run("hardcover")
    assert r["pushed"] == 1 and r["matched"] == 1
    assert seen["book_id"] == 123
    assert seen["status_id"] == 2 and seen["rating"] == 5.0 and seen["review"] == "很好看"
    # ISBN 查询串应带上书自带的 ISBN（匹配口径的第一段）
    assert "9787536692930" in stub.calls[0][2]["variables"]["q"]


def test_hardcover_状态无法映射但仍有评分也推(monkeypatch):
    """paused 没有对应状态 ⇒ 不上报 status_id，但评分仍要推。"""
    dbstub = _DB(statuses={"b1": "paused"}, ratings={"b1": 4})
    _use(monkeypatch, dbstub, [_book()])
    seen = {}

    def handler(url, json):
        if "search" in str(json.get("query", "")):
            return _Resp(200, {"data": {"search": {"ids": [9]}}})
        seen.update(json["variables"]["obj"])
        return _Resp(200, {"data": {"insert_user_book": {"user_book": {"id": 1}}}})

    _patch_client(monkeypatch, handler)
    r = sync.run("hardcover")
    assert r["pushed"] == 1
    assert "status_id" not in seen and seen["rating"] == 4.0


def test_hardcover_既无状态也无评分书评则跳过(monkeypatch):
    dbstub = _DB(statuses={"b1": "paused"})          # 不可映射且没有评分/书评
    _use(monkeypatch, dbstub, [_book()])
    _patch_client(monkeypatch, lambda url, json: _Resp(200, {"data": {"search": {"ids": [1]}}}))

    r = sync.run("hardcover")
    assert r["pushed"] == 0 and r["failed"] == []


# ---------------- Readwise ----------------

def test_readwise_请求形状与external_id去重键(monkeypatch):
    dbstub = _DB(statuses={"b1": "reading"},
                 annos={"b1": [{"id": 7, "quote": "摘录", "note": "笔记", "chapter": 3,
                                "created_at": 1700000000}]})
    _use(monkeypatch, dbstub, [_book()])
    seen = {}

    def handler(url, json):
        seen.update(json["highlights"][0])
        seen["_auth"] = None
        return _Resp(204)

    stub = _patch_client(monkeypatch, handler)
    r = sync.run("readwise", base_url="http://nas:8992/")
    assert r["pushed"] == 1
    assert seen["external_id"] == "nf-b1-7"
    assert seen["text"] == "摘录" and seen["note"] == "笔记"
    assert seen["title"] == "三体" and seen["location_type"] == "chapter"
    assert seen["source_url"].endswith("/book/b1")
    # 鉴权头必须是 Readwise 的 `Token <token>`（不是 Bearer）
    assert stub.calls[0][3]["Authorization"] == "Token tok"


def test_readwise_401逐条计失败(monkeypatch):
    dbstub = _DB(statuses={"b1": "reading"},
                 annos={"b1": [{"id": 1, "quote": "a", "chapter": 1, "created_at": 0},
                               {"id": 2, "quote": "b", "chapter": 1, "created_at": 0}]})
    _use(monkeypatch, dbstub, [_book()])
    _patch_client(monkeypatch, lambda url, json: _Resp(401))

    r = sync.run("readwise")
    assert r["pushed"] == 0
    assert len(r["failed"]) == 2                      # 逐条计，而不是只报「一批失败」
    assert "无效" in r["failed"][0]["error"]


def test_readwise_只有笔记没有划线也能推(monkeypatch):
    dbstub = _DB(statuses={"b1": "reading"},
                 annos={"b1": [{"id": 3, "quote": "", "note": "只有想法", "chapter": 5,
                                "created_at": 0}]})
    _use(monkeypatch, dbstub, [_book()])
    seen = {}
    _patch_client(monkeypatch, lambda url, json: (seen.update(json["highlights"][0]), _Resp(200))[1])

    assert sync.run("readwise")["pushed"] == 1
    assert seen["text"] == "第 5 章" and seen["note"] == "只有想法"   # text 不能为空


# ---------------- StoryGraph 校验 ----------------

def test_storygraph_被引导到登录页判失效(monkeypatch):
    _patch_client(monkeypatch, lambda url, json: _Resp(
        200, url="https://app.thestorygraph.com/login", text="<form>log in</form>"))
    r = sync.verify_storygraph({"session": "s", "remember_token": "r"})
    assert r["ok"] is False and "失效" in r["message"]


def test_storygraph_网络异常不算cookie无效(monkeypatch):
    def handler(url, json):
        raise httpx.ConnectError("boom")

    _patch_client(monkeypatch, handler)
    r = sync.verify_storygraph({"session": "s"})
    assert r["ok"] is False
    assert "连接失败" in r["message"]
    assert "失效" not in r["message"]        # 不能把「连不上」说成「Cookie 无效」


def test_storygraph_正常页面判可用(monkeypatch):
    _patch_client(monkeypatch, lambda url, json: _Resp(
        200, url="https://app.thestorygraph.com/", text="<html>my books</html>"))
    r = sync.verify_storygraph({"session": "s"})
    assert r["ok"] is True and "启发式" in r["message"]


def test_storygraph_未填cookie直接提示():
    r = sync.verify_storygraph({})
    assert r["ok"] is False and "请先填写" in r["message"]


# ---------------- 自动推送：默认关 ----------------

def test_自动推送默认关_不产生旁路线程(monkeypatch):
    monkeypatch.setattr(sync, "_config",
                        lambda: {"integrations": {"hardcover": {"token": "t"},
                                                  "readwise": {"token": "t"}}})
    assert sync.auto_push_on("hardcover") is False
    sync.auto_push("b1")
    assert sync._BG_THREADS == {}


def test_自动推送开关打开才起线程(monkeypatch):
    monkeypatch.setattr(sync, "_config",
                        lambda: {"integrations": {"readwise": {"token": "t",
                                                               "auto_push": True}}})
    assert sync.auto_push_on("readwise") is True
    called = []
    monkeypatch.setattr(sync, "run", lambda *a, **k: called.append(k.get("actor")) or {})
    sync.auto_push("b1", base_url="http://x/", actor="admin")
    sync.wait_pending(timeout=5)
    assert called == ["admin"]        # 操作者必须在请求线程取好再传进来


# ---------------- 端点到端点到契约 ----------------

def test_sync端点_未配置凭据给出明确结果(client, auth_headers):
    r = client.post("/api/integrations/hardcover/sync", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False and "未配置" in body["message"]


def test_sync端点_storygraph不支持同步返回400(client, auth_headers):
    r = client.post("/api/integrations/storygraph/sync", headers=auth_headers, json={})
    assert r.status_code == 400


def test_集成列表暴露同步能力与自动推送状态(client, auth_headers):
    items = client.get("/api/integrations", headers=auth_headers).json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id["hardcover"]["sync"] is True and by_id["readwise"]["sync"] is True
    assert by_id["storygraph"]["sync"] is False          # 无公开 API ⇒ 不做同步
    assert by_id["hardcover"]["auto_push"] is False      # 默认关
    assert by_id["storygraph"]["verify"] is True          # 第 52 期起可启发式校验


def test_自动推送开关可保存且回显为布尔(client, auth_headers):
    r = client.put("/api/integrations/readwise", headers=auth_headers,
                   json={"auto_push": True})
    assert r.status_code == 200, r.text
    items = client.get("/api/integrations", headers=auth_headers).json()["items"]
    assert next(i for i in items if i["id"] == "readwise")["auto_push"] is True
    # 配置页回显里它必须是布尔，不能变成掩码
    sec = client.get("/api/config", headers=auth_headers).json()["config"]["integrations"]
    assert sec["readwise"]["auto_push"] is True
    client.put("/api/integrations/readwise", headers=auth_headers, json={"auto_push": False})


@pytest.fixture(autouse=True)
def _cleanup_bg():
    yield
    sync.wait_pending(timeout=5)
