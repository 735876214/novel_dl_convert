"""跨库同名冲突（第 13 期）：``book_id`` 由 basename 派生 → 两个库各有一本同名书就撞 id。

撞了会怎样：进度 / 批注 / 评分只有一份，``library.by_id`` 还会直接抛
``BookIdConflict``（详情页与进度接口都打不开那本书）。所以这一期要同时做到
「拦得住新问题」和「修得了老数据」，本地测的就是这两件事的四条约束：

1. **入库闸门**：跨库同名 → ``IngestConflict``（带建议名）；**同库同名必须放行** ——
   那是「重新投递一版」的正常覆盖流程，本期最容易误伤的就是它；
2. **判据是库身份，不是目录**：Komga 布局下 ``系列/书.epub`` 与 ``书.epub`` 不在同一
   路径，却撞同一个 id，所以只比 basename；
3. **修复入口**：新加的拦截救不了库里已经躺着的历史冲突，清单 + 一键改名是必需的；
4. **改名必须搬关联数据**：改名会换 ``book_id``，不调 ``db.remap_book_id`` 就等于把
   阅读进度清零 —— 而用户点这个按钮的意图恰恰相反。

外加「范围参数零行为变化」：``library_id`` 为空 = 全部书库 = 加参数之前的行为。
"""
import pytest

from novelforge.core import db, fileops, library, library_rules


def _roots(tmp_path, a="lib-a", b="lib-b"):
    """两个待用库根（与 ``test_library_settings`` 同写法，便于人工复现）。"""
    return tmp_path / "libraries" / a, tmp_path / "libraries" / b


# ---------------------------------------------------------------------------
# 判据：只算「别的库」
# ---------------------------------------------------------------------------

def test_id_conflict_with_only_counts_other_libraries(isolated, make_library, make_book, tmp_path):
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "甲.epub")          # 各自只有自己的一本
    make_book(root_b, "乙.epub")
    library.invalidate()

    hit = library.id_conflict_with("乙.epub", a)
    assert hit is not None, "乙.epub 在别的库 —— 站在甲库看就是冲突"
    assert hit["library_id"] == b

    assert library.id_conflict_with("乙.epub", b) is None, \
        "站在乙库看「乙.epub」就是它自己：同库同名 = 重新投递一版，必须放行"
    assert library.id_conflict_with("甲.epub", a) is None
    assert library.id_conflict_with("球状闪电.epub", a) is None


def test_id_conflicts_lists_group_with_suggestion(isolated, make_library, make_book, tmp_path):
    """清单要能直接渲染表格：保留项、待改项、建议名后端一次算好（口径只有一处）。"""
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "三体.epub")
    make_book(root_b, "三体.epub")
    library.invalidate()

    groups = library.id_conflicts()

    assert len(groups) == 1, "只列撞 id 的组"
    g = groups[0]
    assert g["cross_library"] is True and g["library_count"] == 2
    assert {i["library_id"] for i in g["items"]} == {a, b}
    assert len(g["items"]) == 2

    keep = [i for i in g["items"] if i["keep"]]
    assert len(keep) == 1, "保留项有且只有一个（扫描顺序确定性）"
    assert keep[0]["suggest"] == "", "保留项不动，不该给建议名"

    renamable = [i for i in g["items"] if not i["keep"]]
    assert renamable[0]["suggest"] == "三体 (2).epub"
    assert g["suggest"] == "三体 (2).epub", "组级建议名 = 第一个待改名项（界面「一键」打底）"


# ---------------------------------------------------------------------------
# 入库闸门
# ---------------------------------------------------------------------------

def test_guard_conflict_blocks_cross_library_but_passes_same_library(
        isolated, make_library, make_book, tmp_path):
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "甲.epub")
    make_book(root_b, "乙.epub")
    library.invalidate()

    library_rules.guard_conflict(root_a, "甲.epub")     # 同库同名 → 放行（覆盖是正常流程）

    with pytest.raises(library_rules.IngestConflict) as ei:
        library_rules.guard_conflict(root_a, "乙.epub")  # 乙.epub 已经在乙库
    err = ei.value
    assert err.suggest == "乙 (2).epub"
    assert err.existing["library_id"] == b
    assert "乙库" in str(err), "给人看的消息里要带上是**哪个库**撞了"


def test_resolve_target_reports_conflict_and_passes_same_library(
        isolated, make_library, make_book, tmp_path):
    """摄入侧唯一入口的冲突字段：漫画库是唯一的 comic 库 → .cbz 必归它。"""
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "混合库", "mixed", root_a)
    make_library(b, "漫画库", "comic", root_b)
    make_book(root_a, "三体.cbz")                          # 同名已在**别的**库
    library.invalidate()

    d = library_rules.resolve_target(name="三体.cbz")
    assert d["library_id"] == b and d["root"] == root_b
    assert d["conflict"] is True
    assert d["suggest"] == "三体 (2).cbz"
    assert d["existing"]["library_id"] == a

    # 换成「只剩目标库自己有」的场景：同名落在**同一**库 = 重新投递一版
    (root_a / "三体.cbz").unlink()
    make_book(root_b, "三体.cbz")
    library.invalidate()
    d2 = library_rules.resolve_target(name="三体.cbz")
    assert d2["library_id"] == b
    assert d2["conflict"] is False and d2["suggest"] == "", "同库同名一律放行"


# ---------------------------------------------------------------------------
# 修复入口：清单 + 一键改名（真改磁盘）
# ---------------------------------------------------------------------------

def test_conflicts_api_lists_and_apply_moves_progress(
        client, auth_headers, make_library, make_book, tmp_path):
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "三体.epub")
    make_book(root_b, "三体.epub")
    library.invalidate()

    old_id = library.book_id("三体.epub")
    db.set_progress(old_id, 7, 33.0)      # 冲突的两本书本来就共用这一行

    r = client.get("/api/library-conflicts", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1 and body["cross_library"] == 1
    assert {l["id"] for l in body["libraries"]} >= {a, b}

    item = [i for i in body["groups"][0]["items"] if not i["keep"]][0]
    r = client.post("/api/library-conflicts/apply", headers=auth_headers,
                    json={"items": [{"old": item["name"], "new": item["suggest"],
                                     "library_id": item["library_id"]}]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["errors"] == []
    assert res["count"] == 1 and res["remapped"] == 1

    new_id = library.book_id(item["suggest"])
    assert (library.root_of(item["library_id"]) / item["suggest"]).is_file(), "真改名了"
    assert db.get_progress(new_id)["locator"] == 7, "进度跟着新 id 走"
    assert db.get_progress(old_id) is None, "旧 id 上不残留数据（否则两本书共享进度）"
    assert client.get("/api/library-conflicts", headers=auth_headers).json()["total"] == 0


def test_apply_conflict_rename_rejects_rename_keeping_the_id(
        isolated, make_library, make_book, tmp_path):
    """只换目录 = id 没变 = 冲突照旧 → 必须拒，且**不动磁盘**。"""
    a = "lib-a"
    root_a = tmp_path / "libraries" / a
    make_library(a, "甲库", "ebook", root_a)
    make_book(root_a, "三体.epub")
    library.invalidate()

    res = fileops.apply_conflict_rename([
        {"old": "三体.epub", "new": "系列/三体.epub", "library_id": a},
    ])

    assert res["count"] == 0 and res["remapped"] == 0
    assert "id 相同" in res["errors"][0]["error"]
    assert (root_a / "三体.epub").is_file() and not (root_a / "系列").exists()


def test_apply_conflict_rename_rejects_bad_targets(
        isolated, make_library, make_book, tmp_path):
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "三体.epub")
    make_book(root_a, "三体 (2).epub")      # 目标名在**本库**已被占
    make_book(root_b, "三体 (3).epub")      # 目标名会撞**别的**库
    library.invalidate()

    res = fileops.apply_conflict_rename([
        {"old": "三体.epub", "new": "三体 (2).epub", "library_id": a},
    ])
    assert res["count"] == 0 and "已存在" in res["errors"][0]["error"]

    res = fileops.apply_conflict_rename([
        {"old": "三体.epub", "new": "三体 (3).epub", "library_id": a},
    ])
    assert res["count"] == 0 and "撞名" in res["errors"][0]["error"]

    with pytest.raises(ValueError):
        fileops.apply_conflict_rename([])   # 接口层翻 400


# ---------------------------------------------------------------------------
# 工具页「范围」参数：空 = 全部 = 零行为变化
# ---------------------------------------------------------------------------

def test_tool_scope_empty_equals_all_and_narrows_when_given(
        client, auth_headers, make_library, make_book, tmp_path):
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "甲书.epub")
    make_book(root_b, "乙书.epub")
    library.invalidate()

    # 空串 = 全部：与「不带这个参数」逐字节相同（老前端 / 脚本不受影响）
    for url, params in (("/api/duplicates", {}), ("/api/entities", {"type": "author"}),
                        ("/api/missing", {})):
        all_ = client.get(url, headers=auth_headers, params=params).json()
        empty = client.get(url, headers=auth_headers,
                           params={**params, "library_id": ""}).json()
        assert all_ == empty, f"{url} 空范围必须等价于不带参数"

    only_a = client.get("/api/entities", headers=auth_headers,
                        params={"type": "author", "library_id": a}).json()
    everything = client.get("/api/entities", headers=auth_headers,
                            params={"type": "author"}).json()
    assert only_a["total"] == 1
    assert everything["total"] == 2, "全部书库 = 不裁剪（第 10 期的既定决策）"

    assert client.get("/api/entities", headers=auth_headers,
                      params={"type": "author", "library_id": "没有这个库"}).status_code == 404
