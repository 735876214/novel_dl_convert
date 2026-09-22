"""统计按库筛选（第 30 期）：/api/stats 的 library_id 行为钉死。

- 不传 = 全库（与加该参数之前逐字节一致，8 个仪表盘部件零影响）
- 传库 id = 只算该库
- 不存在的库 = 空集合（不 404，与 /api/duplicates 的 library_id 同一条惯例）
"""
import pathlib

from novelforge import config
from novelforge.core import library, watcher


def _make_lib_and_book(make_library, tmp_path, lid: str, book_name: str) -> None:
    """建一个就地引用库，并把一本书放进它的来源文件夹（与上位测试同口径）。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    make_library(lid, lid, "ebook", src / lid)
    (src / lid).mkdir(parents=True, exist_ok=True)
    (src / lid / book_name).write_bytes(b"EPUB")
    library.invalidate()


def test_stats_scope_empty_equals_all_and_narrows(
        client, auth_headers, make_library, tmp_path):
    _make_lib_and_book(make_library, tmp_path, "stats-a", "书A.epub")
    _make_lib_and_book(make_library, tmp_path, "stats-b", "书B.epub")

    # 空串 = 全部：与「不带这个参数」逐字节相同
    all_ = client.get("/api/stats", headers=auth_headers).json()
    empty = client.get("/api/stats", headers=auth_headers,
                       params={"library_id": ""}).json()
    assert all_ == empty, "空范围必须等价于不带参数"

    only_a = client.get("/api/stats", headers=auth_headers,
                        params={"library_id": "stats-a"}).json()
    only_b = client.get("/api/stats", headers=auth_headers,
                        params={"library_id": "stats-b"}).json()
    assert only_a["books"]["total"] == 1
    assert only_b["books"]["total"] == 1
    assert all_["books"]["total"] == 2, "全部书库 = 不裁剪（第 10 期决策）"

    # 不存在的库 = 空集合，不 404
    none = client.get("/api/stats", headers=auth_headers,
                      params={"library_id": "没有这个库"}).json()
    assert none["books"]["total"] == 0, "未知库 = 空集合，不 404"
