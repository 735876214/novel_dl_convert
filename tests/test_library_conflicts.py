"""同名冲突（第 13 期 → 第 17 期语义调整）。

第 17 期起 ``book_id`` 是「库$哈希」：跨库同名得到**不同 id**，天然不再冲突 ——
所以「跨库同名即冲突」这一旧约束被移除（这正是 T1 要支持的能力）。真正还会撞的
只剩**同库内不同路径的同名书**（``科幻/三体.epub`` 与 ``三体.epub`` 同 basename →
同 id），它仍会让 ``library.by_id`` 抛 ``BookIdConflict``，必须拦 + 可修。

本文件测的就是这四件事在新语义下的四条约束：

1. **跨库同名不再冲突**：站在甲库看乙库的 ``乙.epub`` 不再报冲突；
2. **同库不同路径同名仍冲突**：``三体.epub`` 与 ``科幻/三体.epub`` 撞同一个 id；
3. **入库闸门**：同库不同路径同名 → ``IngestConflict``（带建议名）；跨库同名放行；
4. **修复入口**：清单 + 一键改名（真改磁盘）必须搬关联数据，否则进度清零。
"""
import pytest

from novelforge.core import db, fileops, library, library_rules


def _roots(tmp_path, a="lib-a", b="lib-b"):
    """两个待用库根（与 ``test_library_settings`` 同写法，便于人工复现）。"""
    return tmp_path / "libraries" / a, tmp_path / "libraries" / b


# ---------------------------------------------------------------------------
# 判据：跨库放行 / 同库不同路径才拦
# ---------------------------------------------------------------------------

def test_id_conflict_with_false_for_cross_library_same_basename(isolated, make_library, make_book, tmp_path):
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "甲.epub")
    make_book(root_b, "乙.epub")
    library.invalidate()

    # 第 17 期：跨库同名各自 id 不同 → 互不冲突
    assert library.id_conflict_with("乙.epub", a) is None
    assert library.id_conflict_with("甲.epub", b) is None
    assert library.id_conflict_with("球状闪电.epub", a) is None


def test_id_conflict_with_true_for_same_library_diff_path(isolated, make_library, make_book, tmp_path):
    a = "lib-a"
    root_a = tmp_path / "libraries" / a
    make_library(a, "甲库", "ebook", root_a)
    make_book(root_a, "三体.epub")            # 平铺
    make_book(root_a, "科幻/三体.epub")       # 同库不同路径同名 → 同 id 撞车
    library.invalidate()

    hit = library.id_conflict_with("三体.epub", a)
    assert hit is not None, "同库不同路径同名 → 真冲突"
    assert hit["name"] == "科幻/三体.epub"


# ---------------------------------------------------------------------------
# 清单：同 id 才分组（跨库不再分组）
# ---------------------------------------------------------------------------

def test_id_conflicts_lists_intra_library_group(isolated, make_library, make_book, tmp_path):
    """同库内不同路径同名 → 撞同一个 id → 列成一组；跨库同名不再成组。"""
    a = "lib-a"
    root_a = tmp_path / "libraries" / a
    make_library(a, "甲库", "ebook", root_a)
    make_book(root_a, "三体.epub")
    make_book(root_a, "科幻/三体.epub")       # 同 id
    library.invalidate()

    groups = library.id_conflicts()
    assert len(groups) == 1, "只列撞 id 的组"
    g = groups[0]
    assert g["cross_library"] is False and g["library_count"] == 1
    assert {i["name"] for i in g["items"]} == {"三体.epub", "科幻/三体.epub"}
    keep = [i for i in g["items"] if i["keep"]]
    assert len(keep) == 1, "保留项有且只有一个（扫描顺序确定性）"
    renamable = [i for i in g["items"] if not i["keep"]]
    assert renamable[0]["suggest"].endswith(".epub")


# ---------------------------------------------------------------------------
# 入库闸门
# ---------------------------------------------------------------------------

def test_guard_conflict_blocks_intra_library_diff_path(isolated, make_library, make_book, tmp_path):
    a = "lib-a"
    root_a = tmp_path / "libraries" / a
    make_library(a, "甲库", "ebook", root_a)
    make_book(root_a, "科幻/三体.epub")       # 已有一本同名（不同路径）
    library.invalidate()

    with pytest.raises(library_rules.IngestConflict) as ei:
        library_rules.guard_conflict(root_a, "三体.epub")  # 同库不同路径同名 → 拦
    assert ei.value.suggest.endswith(".epub")
    # 不撞的路径放行
    library_rules.guard_conflict(root_a, "三体 (2).epub")


def test_guard_conflict_passes_cross_library_same_basename(isolated, make_library, make_book, tmp_path):
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "ebook", root_b)
    make_book(root_a, "甲.epub")
    make_book(root_b, "乙.epub")
    library.invalidate()

    # 第 17 期：跨库同名各自 id 不同 → 入库不再拦截
    library_rules.guard_conflict(root_a, "乙.epub")
    library_rules.guard_conflict(root_b, "甲.epub")


def test_resolve_target_no_conflict_for_cross_library(isolated, make_library, make_book, tmp_path):
    a, b = "lib-a", "lib-b"
    root_a, root_b = _roots(tmp_path)
    make_library(a, "甲库", "ebook", root_a)
    make_library(b, "乙库", "comic", root_b)    # 三体.cbz 是 comic → decide 落此库
    make_book(root_b, "三体.cbz")
    library.invalidate()

    d = library_rules.resolve_target(name="三体.cbz")
    assert d["library_id"] == b and d["root"] == root_b
    assert d["conflict"] is False and d["suggest"] == "", "跨库同名不再冲突（第 17 期）"


def test_resolve_target_conflict_for_intra_library_diff_path(isolated, make_library, make_book, tmp_path):
    a = "lib-a"
    root_a = tmp_path / "libraries" / a
    make_library(a, "漫画库", "comic", root_a)   # comic 类型 → decide 落此库
    make_book(root_a, "科幻/三体.cbz")            # 已有一本同名（不同路径）
    library.invalidate()

    d = library_rules.resolve_target(name="三体.cbz")
    assert d["conflict"] is True, "同库不同路径同名 → 撞 id"
    assert d["existing"]["name"] == "科幻/三体.cbz"
    assert d["suggest"].endswith(".cbz")


# ---------------------------------------------------------------------------
# 修复入口：清单 + 一键改名（真改磁盘）
# ---------------------------------------------------------------------------

def test_conflicts_api_lists_intra_library_and_apply_moves_progress(
        client, auth_headers, make_library, make_book, tmp_path):
    a = "lib-a"
    root_a = tmp_path / "libraries" / a
    make_library(a, "甲库", "ebook", root_a)
    make_book(root_a, "三体.epub")
    make_book(root_a, "科幻/三体.epub")          # 同 id
    library.invalidate()

    same_id = library.book_id("三体.epub", a)    # 两本共用这一行（撞车）
    db.set_progress(same_id, 7, 33.0)

    r = client.get("/api/library-conflicts", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1 and body["cross_library"] == 0
    assert {i["name"] for i in body["groups"][0]["items"]} == {"三体.epub", "科幻/三体.epub"}

    item = [i for i in body["groups"][0]["items"] if not i["keep"]][0]
    r = client.post("/api/library-conflicts/apply", headers=auth_headers,
                    json={"items": [{"old": item["name"], "new": item["suggest"],
                                     "library_id": a}]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["errors"] == []
    assert res["count"] == 1 and res["remapped"] == 1

    new_id = library.book_id(item["suggest"], a)
    assert db.get_progress(new_id)["locator"] == 7, "进度跟着新 id 走"
    assert db.get_progress(same_id) is None, "旧 id 上不残留数据"


def test_apply_conflict_rename_rejects_bad_targets(
        isolated, make_library, make_book, tmp_path):
    a = "lib-a"
    root_a = tmp_path / "libraries" / a
    make_library(a, "甲库", "ebook", root_a)
    make_book(root_a, "三体.epub")
    make_book(root_a, "三体 (2).epub")          # 目标名在本库已被占
    library.invalidate()

    res = fileops.apply_conflict_rename([
        {"old": "三体.epub", "new": "三体 (2).epub", "library_id": a},
    ])
    assert res["count"] == 0 and "已存在" in res["errors"][0]["error"]

    with pytest.raises(ValueError):
        fileops.apply_conflict_rename([])        # 接口层翻 400


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
