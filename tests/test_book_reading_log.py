"""单书阅读记录（第 63 期）：`/api/books/{id}/stats` 与心跳式会话上报。

本期给 `reading_sessions` 补了进度快照（start/end 的 percent 与 locator）、
``session_uid``、``file_rel``、``source`` 四组列，并把「一次连续阅读」从
「每 30 秒一行」改成「一段一行（upsert）」。这里钉的是这次改造的四条契约：

1. **没读过 ≠ 读了 0 分钟** —— 空书返回 ``reading: null``，不是一个全 0 对象；
2. **历史数据如实** —— 改造前的会话没有进度快照，相关字段一律 ``null``（界面显示「—」），
   **绝不回落成 0**（0% 是「翻回开头了」，是另一个结论）；
3. **一段阅读 = 一行** —— 同一 ``session_uid`` 的多次心跳只留一行，且 ``start_*``
   不被后续心跳覆盖（它是「本次读了多少」的被减数）；
4. `db.add_session` 的**前四个位置参数逐字节未变** —— 既有调用点（`/api/reading-log`
   补录、老阅读器）零改动仍然可用。
"""
import pathlib
import time

from novelforge import config
from novelforge.core import db, library


def _make_lib_and_book(make_library, lid, book_name):
    """建一个就地引用库并把一本书放进来源文件夹，返回该书 id（与既有测试同口径）。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"])
    make_library(lid, lid, "ebook", src / lid)
    (src / lid).mkdir(parents=True, exist_ok=True)
    (src / lid / book_name).write_bytes(b"EPUB")
    library.invalidate()
    return library.books(lid)[0]["id"]


def _day(s: str) -> float:
    """本地日零点（与 `active_days` / `reading_day_minutes` 的本地时区口径一致）。"""
    return time.mktime(time.strptime(s, "%Y-%m-%d"))


# ---------------------------------------------------------------- 端到端形状

def test_没读过的书_reading_是_null_而不是全零对象(client, auth_headers, make_library):
    """**这条是「不造假数据」的直接体现。**

    返回 ``{"seconds": 0, "sessions": 0, ...}`` 会让界面把「没记录」渲染成
    「读了 00:00 / 0 次会话」—— 那是编出来的读数。前端只判一处 ``reading === null``
    就能渲染空状态，所以空书这里也必须把四个键都给全（不留 undefined 让前端再防一遍）。
    """
    aid = _make_lib_and_book(make_library, "srl-empty", "空书.epub")
    r = client.get(f"/api/books/{aid}/stats", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["reading"] is None, "没读过必须是 null，不能是全 0 对象"
    assert body["records"] is None
    assert body["days"] == [] and body["sessions"] == []


def test_不存在的书_404(client, auth_headers, make_library):
    """404 而不是「空记录」—— 后者会把「这本书没了」伪装成「这本书没读过」。"""
    assert client.get("/api/books/没有这本书/stats", headers=auth_headers).status_code == 404
    assert client.post("/api/books/没有这本书/session", headers=auth_headers,
                       json={"seconds": 60}).status_code == 404


def test_历史会话没有进度快照时如实给_null(client, auth_headers, make_library):
    """改造前的会话补不出进度 —— 相关字段是 ``null``，**不是 0**。

    这是本期最容易写错的一处：列默认值是 -1（库内哨兵），出到 JSON 必须转 ``None``。
    转丢了就会看到「CHANGE 0%」这种编出来的读数，而它其实只是「当年没记」。
    """
    aid = _make_lib_and_book(make_library, "srl-legacy", "老书.epub")
    d = _day("2024-05-01")
    db.add_session(aid, 600, d + 3600, d + 4200)          # 位置参数老写法：不带任何新字段

    body = client.get(f"/api/books/{aid}/stats", headers=auth_headers).json()
    s = body["sessions"][0]
    for k in ("start_percent", "end_percent", "change", "start_locator", "end_locator"):
        assert s[k] is None, f"{k} 应为 null（历史行没记过），实际 {s[k]!r}"
    assert body["days"][0]["end_percent"] is None, "当天没有已知位置 ⇒ 图上断线，不画到 0%"
    # 时长本身是老数据里唯一真实存在的东西，照常统计
    assert body["reading"]["seconds"] == 600.0
    assert body["reading"]["sessions"] == 1


def test_心跳上报_一段阅读只留一行(client, auth_headers, make_library):
    """同一 ``session_uid`` 反复上报 = 同一段阅读的心跳 ⇒ 一行，且**起点不被覆盖**。

    读两小时从 240 行变成 1 行。``start_percent`` 必须停在**第一次**那次数值上：
    它是 ``change`` 的被减数，被心跳一轮轮覆盖掉的话「本次读了多少」就永远算不出来 ——
    每次都只算最后一次心跳的那一小段。

    ⚠️ 后两次心跳**故意报一个不同的 start**（真实客户端在「起点记成上一次刷新的终点」
    这种写法下就是这个形状）。三次都报同一个值的话，即便 ``start_*`` 泄漏进 SET 子句
    也看不出差别 —— 这条用例就白写了。
    """
    aid = _make_lib_and_book(make_library, "srl-beat", "心跳书.epub")
    uid = "sess-abc123"
    for sec, start, end in ((30, 10, 12), (60, 25, 25), (90, 35, 40)):
        r = client.post(f"/api/books/{aid}/session", headers=auth_headers, json={
            "seconds": sec, "session_uid": uid,
            "start_percent": start, "end_percent": end,
            "start_locator": 100, "end_locator": 900, "source": "web",
        })
        assert r.status_code == 200, r.text

    body = client.get(f"/api/books/{aid}/stats", headers=auth_headers).json()
    assert body["reading"]["sessions"] == 1, "三次心跳必须只留一行"
    s = body["sessions"][0]
    assert s["seconds"] == 90.0, "seconds 是这一段的累计值，取最后一次"
    assert s["start_percent"] == 10.0, "起点只在开段时写一次，心跳不得覆盖"
    assert s["start_locator"] == 100.0, "同上（locator / file_rel / source 同一个道理）"
    assert s["end_percent"] == 40.0, "终点随心跳推进"
    assert s["change"] == 30.0, "10% → 40%；被覆盖的话这里会变成 5%"
    assert s["source"] == "web"
    # 单行 ⇒ 总时长就是这一段的时长，不是三次相加（相加会虚报 180 秒）
    assert body["reading"]["seconds"] == 90.0


def test_不带_uid_的上报一次一行(client, auth_headers, make_library):
    """没有 ``session_uid`` = 「这是一次独立上报」⇒ 插新行（既有调用点零改动）。"""
    aid = _make_lib_and_book(make_library, "srl-plain", "普通书.epub")
    for _ in range(2):
        assert client.post(f"/api/books/{aid}/session", headers=auth_headers,
                           json={"seconds": 60}).status_code == 200
    body = client.get(f"/api/books/{aid}/stats", headers=auth_headers).json()
    assert body["reading"]["sessions"] == 2
    assert body["reading"]["seconds"] == 120.0
    assert all(s["source"] == "" for s in body["sessions"]), "没上报来源就是空串（未知）"


def test_上报参数校验(client, auth_headers, make_library):
    aid = _make_lib_and_book(make_library, "srl-bad", "校验书.epub")
    post = lambda **kw: client.post(f"/api/books/{aid}/session",   # noqa: E731
                                    headers=auth_headers, json=kw)
    assert post(seconds=0).status_code == 400
    assert post(seconds=86401).status_code == 400
    assert post(seconds=-1).status_code == 400
    assert post(seconds="abc").status_code == 400
    assert post(seconds=60, end_percent=150).status_code == 400, "百分比须 ≤ 100"
    assert post(seconds=60, start_percent=-5).status_code == 400
    assert post(seconds=60, source="carrier-pigeon").status_code == 400, "来源须在词表内"
    assert post(seconds=60, source="audio").status_code == 200
    # 空串 = 「这次没上报」而不是「别的东西」—— 与「没给」等价，都该放行
    assert post(seconds=60, end_percent=None, session_uid="").status_code == 200


# ---------------------------------------------------------------- 聚合与图表

def test_records_四格(client, auth_headers, make_library):
    """最长一次 / 最好的一天 / 最忙的一天 / 最长连续 —— 四个结论各自独立。"""
    aid = _make_lib_and_book(make_library, "srl-rec", "记录书.epub")
    a, b, c = _day("2024-05-01"), _day("2024-05-02"), _day("2024-05-08")

    db.add_session(aid, 1800, a + 3600, a + 5400)          # 第 1 天：30 分钟
    db.add_session(aid, 600, a + 7200, a + 7800)           # 第 1 天：10 分钟
    db.add_session(aid, 3600, b + 3600, b + 7200)          # 第 2 天：60 分钟（最长的一次）
    db.add_session(aid, 900, c + 3600, c + 4500)           # 第 8 天：15 分钟
    db.add_session(aid, 900, c + 7200, c + 8100)           # 第 8 天：15 分钟

    rec = client.get(f"/api/books/{aid}/stats", headers=auth_headers).json()["records"]
    assert rec["longest_session"]["seconds"] == 3600.0
    assert rec["longest_session"]["date"] == "2024-05-02"
    assert rec["best_day"]["date"] == "2024-05-02", "60 分钟 > 40 分钟 > 30 分钟"
    assert rec["best_day"]["seconds"] == 3600.0
    assert rec["busiest_day"]["date"] == "2024-05-01", "2 次会话并列，取更早那天（平局先到先得）"
    assert rec["busiest_day"]["sessions"] == 2
    # 5/1–5/2 连续两天 ⇒ 最长连续 2 天；5/8 是孤立的一天
    assert rec["longest_streak"] == {"days": 2, "start": "2024-05-01", "end": "2024-05-02"}


def test_days_升序_sessions_降序(client, auth_headers, make_library):
    """图上从左到右（升序）、流水表新 → 旧（降序）—— 两者刻意不同，别互相迁就。"""
    aid = _make_lib_and_book(make_library, "srl-order", "顺序书.epub")
    for d in ("2024-05-01", "2024-05-02", "2024-05-03"):
        t = _day(d)
        db.add_session(aid, 600, t + 3600, t + 4200, source="web")

    body = client.get(f"/api/books/{aid}/stats", headers=auth_headers).json()
    assert [x["date"] for x in body["days"]] == ["2024-05-01", "2024-05-02", "2024-05-03"]
    assert body["sessions"][0]["started_at"] > body["sessions"][-1]["started_at"], "会话新 → 旧"
    assert len(body["sessions"]) == 3
    assert body["reading"]["active_days"] == 3
    assert body["reading"]["avg_seconds"] == 600.0


def test_days_的_end_percent_取当天最后一次(client, auth_headers, make_library):
    """一天读了两段：图上那天的位置取**后**一段的终点（先降后升的折线不该被前一段盖住）。"""
    aid = _make_lib_and_book(make_library, "srl-last", "同日书.epub")
    t = _day("2024-05-01")
    db.add_session(aid, 600, t + 3600, t + 4200, start_percent=0, end_percent=10)
    db.add_session(aid, 600, t + 7200, t + 7800, start_percent=10, end_percent=55)

    body = client.get(f"/api/books/{aid}/stats", headers=auth_headers).json()
    assert body["days"][0]["end_percent"] == 55.0
    assert body["days"][0]["seconds"] == 1200.0
    assert body["days"][0]["sessions"] == 2


def test_补录的会话标为_manual(client, auth_headers, make_library):
    """手工补录（读了纸质书那种）来源是 ``manual`` —— 不混进阅读器的心跳里。"""
    aid = _make_lib_and_book(make_library, "srl-man", "补录书.epub")
    r = client.post("/api/reading-log", headers=auth_headers, json={
        "book_id": aid, "minutes": 30, "date": "2024-05-01", "start": "08:30",
    })
    assert r.status_code == 200, r.text
    s = client.get(f"/api/books/{aid}/stats", headers=auth_headers).json()["sessions"][0]
    assert s["source"] == "manual"
    assert s["seconds"] == 1800.0
    assert s["start_percent"] is None, "补录不知道读到哪，如实留 null"


# ---------------------------------------------------------------- 纯函数

def test_longest_streak_纯函数():
    """最长连续段：空 → None；单日 → 1；断档重算；平局取**更早**那段。"""
    f = db.longest_streak
    assert f([]) is None
    assert f(["2024-05-01"]) == {"days": 1, "start": "2024-05-01", "end": "2024-05-01"}
    assert f(["2024-05-01", "2024-05-02", "2024-05-05"])["days"] == 2
    # 跨月、跨年都要连着算（按日期差，不是按字符串）
    assert f(["2024-05-31", "2024-06-01"])["days"] == 2
    assert f(["2024-12-31", "2025-01-01"])["days"] == 2
    # 平局取先到的（升序遍历 ⇒ 更早）
    assert f(["2024-05-01", "2024-05-02", "2024-05-08", "2024-05-09"])["start"] == "2024-05-01"
    # 脏数据**跳过而不是打断**：夹在中间的那个坏值不该把连续两天切成两段
    assert f(["2024-05-01", "不是日期", "2024-05-02"]) == {
        "days": 2, "start": "2024-05-01", "end": "2024-05-02"}


def test_session_row_哨兵转_None():
    """出库即对外语义：-1 在 ``_session_row`` 里一次性转成 ``None``，别的层不用再判。"""
    row = {
        "id": 1, "seconds": 60.0, "started_at": 0.0, "ended_at": 60.0,
        "start_locator": db.SESSION_UNKNOWN, "end_locator": 5,
        "start_percent": db.SESSION_UNKNOWN, "end_percent": 50.0,
        "file_rel": None, "source": None,
    }
    out = db._session_row(row)
    assert out["start_percent"] is None and out["change"] is None
    assert out["end_locator"] == 5.0 and out["start_locator"] is None
    assert out["file_rel"] == "" and out["source"] == "", "NULL 也归成空串，不留 None 给前端"
