"""阅读活动聚合（第 31 期）：/api/reading-activity 的 heatmap + timeline 钉死。

- 空 library_id = 全部书库（与能力预期一致）
- 按库过滤：只返回该库书的会话 / 批注
- 空库 / 无记录：days / events 为空列表（不补假数据）
- 热力图按本地日聚合，同日多会话分钟累加
"""
import pathlib
import time

from novelforge import config
from novelforge.core import activity, db, library, watcher


def _make_lib_and_book(make_library, tmp_path, lid, book_name):
    """建一个就地引用库并把一本书放进来源文件夹，返回该书 id（与上位测试同口径）。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    make_library(lid, lid, "ebook", src / lid)
    (src / lid).mkdir(parents=True, exist_ok=True)
    (src / lid / book_name).write_bytes(b"EPUB")
    library.invalidate()
    return library.books(lid)[0]["id"]


def test_heatmap_buckets_by_local_day(make_library, tmp_path):
    aid = _make_lib_and_book(make_library, tmp_path, "act-c", "书C.epub")
    day = time.mktime(time.strptime("2024-05-01", "%Y-%m-%d"))
    db.add_session(aid, 3600, day, day + 1800)           # 60 分钟
    db.add_session(aid, 3600, day + 600, day + 4200)     # 同日再 +60 分钟
    hm = activity.heatmap("act-c")
    entry = next(d for d in hm["days"] if d["date"] == "2024-05-01")
    assert entry["minutes"] == 120.0
    assert entry["sessions"] == 2


def test_reading_activity_empty_is_all_and_filters(client, auth_headers, make_library, tmp_path):
    aid = _make_lib_and_book(make_library, tmp_path, "act-a", "书A.epub")
    bid = _make_lib_and_book(make_library, tmp_path, "act-b", "书B.epub")

    now = time.time()
    db.add_session(aid, 3600, now - 86400, now - 86400 + 3600)
    db.add_session(bid, 1800, now - 2 * 86400, now - 2 * 86400 + 1800)

    all_ = client.get("/api/reading-activity", headers=auth_headers).json()
    empty = client.get("/api/reading-activity", headers=auth_headers,
                       params={"library_id": ""}).json()
    assert all_ == empty, "空范围等于不带参数"

    only_a = client.get("/api/reading-activity", headers=auth_headers,
                        params={"library_id": "act-a"}).json()
    assert only_a["heatmap"]["library_id"] == "act-a"
    assert only_a["heatmap"]["active_days"] == 1, "按库过滤后只含该书会话"
    assert all(e["book_id"] == aid for e in only_a["timeline"]["events"]
               if e["type"] in ("session", "annotation"))

    # 不在册的库 = 空集合，不 404，且不补假数据
    none = client.get("/api/reading-activity", headers=auth_headers,
                      params={"library_id": "没有这个库"}).json()
    assert none["heatmap"]["active_days"] == 0
    assert none["timeline"]["total"] == 0
    assert none["heatmap"]["days"] == []
    assert none["timeline"]["events"] == []


def test_timeline_events_carry_server_local_date(client, auth_headers, make_library, tmp_path):
    """时间轴每个事件都带 server-local date，且与热力图同日口径一致（消跨时区 ±1 天错位）。

    这是第 47 期修复的契约：前端时间轴分组改读 ``e.date``，不再用浏览器时区从 ``ts`` 重算。
    """
    aid = _make_lib_and_book(make_library, tmp_path, "act-d", "书D.epub")
    day = time.mktime(time.strptime("2024-05-01", "%Y-%m-%d"))
    db.add_session(aid, 3600, day, day + 1800)                 # 会话落在 2024-05-01
    db.add_annotation(aid, 1, "划线", "yellow", "一条笔记")       # 批注分支也要带 date

    resp = client.get("/api/reading-activity", headers=auth_headers,
                     params={"library_id": "act-d"}).json()
    events = resp["timeline"]["events"]
    assert events, "应有事件"

    heat_days = {d["date"] for d in resp["heatmap"]["days"]}
    for e in events:
        assert "date" in e and isinstance(e["date"], str), "事件缺 date 字段"
        assert e["date"] == time.strftime("%Y-%m-%d", time.localtime(e["ts"])), \
            "date 须等于 ts 的 server-local 日"
        assert len(e["date"]) == 10 and e["date"][4] == "-" == e["date"][7], "date 形如 YYYY-MM-DD"

    session_days = {e["date"] for e in events if e["type"] == "session"}
    assert session_days == {"2024-05-01"}, "会话事件须归入 2024-05-01"
    assert session_days <= heat_days, "会话事件的 date 须与热力图同日集合一致"
