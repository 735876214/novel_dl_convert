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
