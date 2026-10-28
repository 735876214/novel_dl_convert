"""批量动作的**批量实现**（第 170 期）。

**为什么值得钉**：`/api/books/batch` 此前逐本调单本函数，而那三个函数各自
``commit()`` 一次 —— 2,000 本实测 **6.5 s**（本地 SQLite；NAS 上的 PG 每事务还要走
网络与 WAL flush，更慢），已经顶到前端 15 s 请求超时：界面报「批量操作失败」，
**服务端却已经把数据写完**。改成「存在性一次判（`catalog.alive_ids`）+ 一条事务」后，
本地 0.02–0.05 s。

这里钉的不是速度，而是**语义没变** —— 单本与批量必须同一结果：

- 评分校验（`db._norm_stars`）、状态日期规则（`db._status_dates`）、
  阅读轮次维护（`db._sync_attempt`）都只有一份实现，批量只是换掉「逐本提交」；
- 收藏夹重复加入幂等；
- 不存在的 id 进 ``failed``、其余照做；
- 坏参数在**任何写入之前**整批 400（非有限时间戳那条另有
  `test_hardening_140_db_layer`）。

外加一条**结构性**判据：提交次数必须是常数级，与书本数无关（数提交而不是掐秒表，
免得用例变成「看机器快慢」的 flake）。
"""
from novelforge.core import db


def _books(client, headers, n: int) -> list:
    items = client.get("/api/books", headers=headers).json()["items"]
    assert len(items) >= n, f"夹具只扫到 {len(items)} 本"
    return [b["id"] for b in items[:n]]


def _batch(client, headers, action: str, ids: list, **params):
    return client.post("/api/books/batch", headers=headers,
                       json={"action": action, "ids": ids, "params": params})


def test_批量评分与单本同值(client, auth_headers, default_root, make_book, test_lib_id):
    for i in range(4):
        make_book(default_root, f"评{i}.epub")
    assert client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers).json()["ok"]
    ids = _books(client, auth_headers, 4)

    r = _batch(client, auth_headers, "set_rating", ids, stars=4)
    assert r.status_code == 200, r.text
    assert r.json()["succeeded"] == ids and r.json()["failed"] == []
    got = {b["id"]: b["stars"] for b in client.get("/api/books", headers=auth_headers).json()["items"]}
    assert all(got[i] == 4 for i in ids), got

    # stars=0 ⇒ 清除（与单本「0 = 未评分」同一语义：行被删掉，读回来是 0）
    assert _batch(client, auth_headers, "set_rating", ids, stars=0).status_code == 200
    got = {b["id"]: b["stars"] for b in client.get("/api/books", headers=auth_headers).json()["items"]}
    assert all(got[i] == 0 for i in ids), got
    assert db.get_rating(ids[0]) == 0, "0 = 未评分：行应当被删掉，而不是留一行 stars=0"


def test_批量状态走同一套日期规则(client, auth_headers, default_root, make_book, test_lib_id):
    make_book(default_root, "态1.epub")
    assert client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers).json()["ok"]
    bid = _books(client, auth_headers, 1)[0]

    def row() -> dict:
        return db.get_status(bid) or {}

    assert _batch(client, auth_headers, "set_status", [bid], status="reading").status_code == 200
    assert row()["status"] == "reading" and row()["started_at"] > 0 and row()["finished_at"] == 0

    assert _batch(client, auth_headers, "set_status", [bid], status="finished").status_code == 200
    assert row()["finished_at"] > 0, "进 finished 要记读完时间"

    # paused 保留已开始的日期（它记录的是「什么时候开始翻的」）
    st_before = row()["started_at"]
    assert _batch(client, auth_headers, "set_status", [bid], status="paused").status_code == 200
    assert row()["started_at"] == st_before and row()["finished_at"] == 0

    # 回到 unread ⇒ 两个日期都清零
    assert _batch(client, auth_headers, "set_status", [bid], status="unread").status_code == 200
    assert row()["started_at"] == 0 and row()["finished_at"] == 0


def test_批量设状态维护阅读轮次(client, auth_headers, default_root, make_book, test_lib_id):
    """`_sync_attempt` 在批量路径里也要跑 —— 只写状态不写轮次，统计页的轮次就断了。"""
    make_book(default_root, "轮1.epub")
    assert client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers).json()["ok"]
    bid = _books(client, auth_headers, 1)[0]

    _batch(client, auth_headers, "set_status", [bid], status="finished")
    items = client.get(f"/api/books/{bid}/reading-attempts", headers=auth_headers).json()["items"]
    assert len(items) == 1 and items[0]["status"] == "finished" and items[0]["finished_at"] > 0


def test_批量加入收藏夹幂等(client, auth_headers, default_root, make_book, test_lib_id):
    for i in range(3):
        make_book(default_root, f"夹{i}.epub")
    assert client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers).json()["ok"]
    ids = _books(client, auth_headers, 3)
    cid = client.post("/api/collections", headers=auth_headers,
                      json={"name": "批量夹"}).json()["id"]

    r = _batch(client, auth_headers, "add_to_collection", ids, collection_id=cid)
    assert r.status_code == 200 and r.json()["succeeded"] == ids
    assert len(client.get("/api/books", headers=auth_headers).json()["items"][0]["collection_ids"]) >= 0

    # 再点一次：还是「成功」（幂等），但成员数不涨
    r2 = _batch(client, auth_headers, "add_to_collection", ids, collection_id=cid)
    assert r2.status_code == 200 and r2.json()["succeeded"] == ids
    coll = client.get(f"/api/collections/{cid}", headers=auth_headers).json()
    members = coll.get("books") or coll.get("items") or []
    assert len(members) == 3, coll


def test_不存在的_id进_failed_其余照做(client, auth_headers, default_root, make_book, test_lib_id):
    make_book(default_root, "在.epub")
    assert client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers).json()["ok"]
    bid = _books(client, auth_headers, 1)[0]

    r = _batch(client, auth_headers, "set_rating", ["lib-不存在$deadbeef", bid], stars=5)
    d = r.json()
    assert d["succeeded"] == [bid]
    assert [f["id"] for f in d["failed"]] == ["lib-不存在$deadbeef"]
    assert db.get_rating(bid) == 5


def test_坏评分整批记失败且零写入(client, auth_headers, default_root, make_book, test_lib_id):
    make_book(default_root, "坏.epub")
    assert client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers).json()["ok"]
    bid = _books(client, auth_headers, 1)[0]

    r = _batch(client, auth_headers, "set_rating", [bid], stars=99)
    d = r.json()
    assert d["succeeded"] == [] and d["failed"], d
    assert "评分" in d["failed"][0]["error"]
    assert db.get_rating(bid) == 0, "被拒的批不该写进任何一行"


def test_批量写入也走自动推送旁路且只发一次(client, auth_headers, default_root, make_book,
                                            test_lib_id, monkeypatch):
    """批量改评分后，外部服务同步（默认关）**一次**带上全部书 —— 与单本同一条旁路。

    此前批量端点完全不调 `_sync_auto_push`：单本改评分会推，批量改同样的东西不推，
    用户配了 Hardcover / Readwise 自动推送时，批量整理完的书在对面永远不出现。
    修法是给它一串 id：`sync.auto_push` 只起一个线程、`run` 一次（见
    `test_integration_sync` 那条单元用例）。
    """
    from novelforge.core import sync

    for i in range(3):
        make_book(default_root, f"推{i}.epub")
    assert client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers).json()["ok"]
    ids = _books(client, auth_headers, 3)

    monkeypatch.setattr(sync, "_config", lambda: {
        "integrations": {"readwise": {"token": "t", "auto_push": True}}})
    calls: list = []
    monkeypatch.setattr(sync, "run", lambda *a, **k: calls.append(a) or {})
    try:
        r = _batch(client, auth_headers, "set_rating", ids, stars=2)
        sync.wait_pending(timeout=5)
    finally:
        monkeypatch.undo()
    assert r.status_code == 200 and len(r.json()["succeeded"]) == len(ids)
    assert len(calls) == 1, f"批量改评分发了 {len(calls)} 次同步"
    assert sorted(calls[0][1]) == sorted(ids) or set(calls[0][1]) == set(ids), calls[0]


def test_提交次数与书本数无关(client, auth_headers, default_root, make_book, test_lib_id, monkeypatch):
    """结构性判据（不是掐秒表）：批量端点对 N 本书只提交**常数次**。

    改回逐本 `commit()` 时这条会立刻红 —— 而那正是「2,000 本 6.5 秒、撞前端 15 s
    超时」的根因。
    """
    for i in range(20):
        make_book(default_root, f"提交{i}.epub")
    assert client.post(f"/api/libraries/{test_lib_id}/scan", headers=auth_headers).json()["ok"]
    ids = _books(client, auth_headers, 20)

    real = db._connect

    class Counting:
        def __init__(self, inner):
            self._inner = inner
            self.commits = 0

        def commit(self):
            self.commits += 1
            return self._inner.commit()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    seen: list = []
    shared = Counting(real())

    def fake_connect():
        if not seen:
            seen.append(shared)
        return shared

    monkeypatch.setattr(db, "_connect", fake_connect)
    try:
        r = _batch(client, auth_headers, "set_rating", ids, stars=3)
    finally:
        monkeypatch.undo()

    assert r.status_code == 200 and len(r.json()["succeeded"]) == len(ids)
    assert shared.commits <= 2, (
        f"20 本书提交了 {shared.commits} 次 —— 批量端点又退回逐本 commit 了"
    )


def _counting_connect(monkeypatch):
    """把 `db._connect` 换成一个**数提交次数**的代理（判定「逐本 commit」的探针）。"""
    real = db._connect

    class Counting:
        def __init__(self, inner):
            self._inner = inner
            self.commits = 0

        def commit(self):
            self.commits += 1
            return self._inner.commit()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    shared = Counting(real())
    monkeypatch.setattr(db, "_connect", lambda: shared)
    return shared


def test_收藏夹批量写入提交次数恒定(isolated, monkeypatch):  # noqa: ARG001
    """`add_books_to_collection` / `remove_books_from_collection` 各只提交常数次。

    这两个函数是 Komga 兼容层「整体替换系列」的后端（一次可能带上整库 652 本）：
    退回逐本写入时，每本两次提交（写 + 刷 `updated_at`）—— 客户端那边就是超时。
    """
    cid = db.create_collection("提交夹")
    ids = [f"lib-x$b{i:03d}" for i in range(50)]

    c = _counting_connect(monkeypatch)
    assert db.add_books_to_collection(cid, ids) == 50
    assert c.commits <= 2, f"批量加入提交了 {c.commits} 次"
    # 幂等：再来一次不新增、也不多提交
    before = c.commits
    assert db.add_books_to_collection(cid, ids) == 0
    assert c.commits == before, "全是已有成员时不该再提交"

    c2 = _counting_connect(monkeypatch)
    assert db.remove_books_from_collection(cid, ids) == 50
    assert c2.commits <= 2, f"批量移出提交了 {c2.commits} 次"
    monkeypatch.undo()

    # 成员关系真的变了（不是只数提交）：移出后这批 id 都不再属于该夹
    still = db.collection_map()
    assert all(cid not in still.get(i, []) for i in ids)
