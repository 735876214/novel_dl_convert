"""第 36 期：用户点选的**跨库移动**（``migrate`` 里 ``direction="bookmove"`` 那一半）。

自动归库（``preview`` / ``plan``）与跨库移动共用 manifest / 逐条独立 / remap / 回滚这台
机器，但移动多出三条自己的口径，逐条钉住：

1. **类型相容才许搬**：白名单决定扫描认不认这个文件 —— 搬进不相容的库，书**不是半可见，
   是直接消失**（``library.books()`` 扫不到），所以这条是数据完整性闸门，不是 UX 偏好；
2. **副本随书搬**（用户口径③）：正本走了副本还留在原库，等于原库架上少一本、新库多一本
   不在那儿的书 —— 移动只做了一半；
3. **预览 == 落盘**：预览说的落点与副本名，就是执行时用的那一个（共用同一份算法，
   不是两边各写一遍）。

另有三条老纪律在新路径上同样要成立：同名**拒绝覆盖**（只给建议名）、
**回滚把关联数据与副本一起带回来**、自动归库那条路的**行为一字不变**
（它的 ``direction`` 仍是 ``move``，仍是「最近一次可回滚批次」的取值来源）。
"""
from __future__ import annotations

import pathlib

import pytest

from novelforge.core import db, epub_builder, library, migrate, scrape


# ---------------------------------------------------------------------------
# 夹具与工具
# ---------------------------------------------------------------------------

def _epub(root, name: str, title: str = "书") -> pathlib.Path:
    """真 EPUB —— 出版链路要改写 OPF，占位字节过不去。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": title, "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(path))
    return path


def _audio_dir(root, name: str) -> pathlib.Path:
    """目录型有声书（一章一文件）；内容是不是合法音频与出版链路无关。"""
    d = pathlib.Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    for t in ("01 第一章.mp3", "02 第二章.mp3"):
        (d / t).write_bytes(b"ID3" + b"\x00" * 16)
    return d


@pytest.fixture
def env(isolated, tmp_path):                       # noqa: ARG001 —— 依赖 isolated 切目录
    """覆盖本期要验证的四种库关系（每库各有自己的成品目录，除丙库外）。"""
    def _lib(lid, name, ltype, sub, publish=False):
        root = tmp_path / "libraries" / sub
        pdir = tmp_path / "out" / sub
        db.create_library(lid, name, ltype, "inplace", str(root), source_subdir=sub,
                          publish_path=str(pdir) if publish else "")
        return {"id": lid, "name": name, "root": root,
                "pdir": pdir if publish else None}

    out = {
        # 甲 → 乙：正常移动，两边都有成品目录 → 副本随迁
        "a": _lib("a", "甲库", "ebook", "a", publish=True),
        "b": _lib("b", "乙库", "ebook", "b", publish=True),
        # 甲 → 丙：目标库**没配成品目录** → 副本留在原库
        "c": _lib("c", "丙库", "ebook", "c"),
        # 甲 → 有声：**类型不相容**，搬不进去
        "audio": _lib("audio", "有声书库", "audiobook", "audio", publish=True),
        # 有声 → 有声二：目录型条目，副本整树随迁
        "audio2": _lib("audio2", "有声书二库", "audiobook", "audio2", publish=True),
    }
    library.invalidate()
    return out


def _book(lib: dict, name: str) -> dict:
    library.invalidate()
    b = next((x for x in library.books(lib["id"]) if x["name"] == name), None)
    assert b is not None, f"扫描不到 {name}"
    return b


def _publish(lib: dict, name: str) -> dict:
    """真出版一本，返回它的台账行（副本按该库的规则落进成品目录）。"""
    b = _book(lib, name)
    assert scrape.enqueue(b)["queued"] is True
    assert scrape.run_once()["processed"] == 1
    row = db.scrape_get(b["id"])
    assert row["status"] == "ok", row
    return row


class _Watcher:
    """假 watcher：只记「谁被登记过」。

    真 watcher 会起线程、写状态文件 —— 测试不养后台轮询（见 conftest 的纪律），
    这里要验的也只是「移动后有没有把新位置登记进去」这一件事。
    """

    def __init__(self):
        self.seen: list = []

    def mark_processed(self, path) -> None:
        self.seen.append(str(path))


# ---------------------------------------------------------------------------
# ① 相容闸门：判据只有库扫描白名单
# ---------------------------------------------------------------------------

def test_相容判据与库扫描白名单一致(env):
    """拦与放行都只由 ``library._exts_for_type`` 决定 —— 不新写第二处相容表。

    尤其钉住**目录型有声书**：它只有在白名单含音频扩展名时才被算作一本书
    （``_iter_book_entries`` 的 ``allow_audio_dir``），所以「有声书目录搬进漫画库」
    同样要拦 —— 只看条目名有没有扩展名会漏掉这一整类。
    """
    _epub(env["a"]["root"], "三体.epub")
    _audio_dir(env["audio"]["root"], "活着")
    library.invalidate()
    books = {b["name"]: b for b in library.books()}
    libs = {l["id"]: l for l in library.libraries()}

    why = migrate.compat_reason(books["三体.epub"], libs["audio"])
    assert why.startswith("「有声书库」只收") and "EPUB" not in why.split("，")[0]

    why = migrate.compat_reason(books["活着"], libs["c"])
    assert "有声书目录" in why, "目录型条目也要按白名单判，不能因为「没有扩展名」放行"

    assert migrate.compat_reason(books["三体.epub"], libs["c"]) == ""
    assert migrate.compat_reason(books["活着"], libs["audio2"]) == ""
    # 默认库是 mixed（全量白名单）：搬回它永远可行
    default = next(l for l in library.libraries() if l["id"] == library.DEFAULT_LIBRARY_ID)
    assert all(migrate.compat_reason(b, default) == "" for b in books.values())


# ---------------------------------------------------------------------------
# ② 正本 + 副本 + 关联数据一起走
# ---------------------------------------------------------------------------

def test_移动把正本副本与关联数据一起搬到新库(env):
    _epub(env["a"]["root"], "三体.epub", title="三体")
    old = _book(env["a"], "三体.epub")
    row = _publish(env["a"], "三体.epub")
    old_rel = row["link_rel"]
    assert (env["a"]["pdir"] / old_rel).is_file()
    db.set_progress(old["id"], 7, 33.0)
    db.set_override(old["id"], "title", "用户改过的书名")
    db.set_cover(old["id"], b"\xff\xd8cover")

    pv = migrate.move_preview([old["id"]], "b")
    assert pv["ready"] == 1 and pv["movable"] == 1 and pv["blocked"] == 0
    item = pv["items"][0]
    assert item["dst"] == str(env["b"]["root"] / "三体.epub")
    assert item["copy"]["action"] == "move"
    new_rel = item["copy"]["rel"]

    planned = migrate.move_plan([old["id"]], "b")
    manifest = db.migration_batch(planned["batch_id"])[0]
    # 预览说的落点就是落进 manifest 的落点（预览 == 落盘的第一道）
    assert manifest["src"] == item["src"] and manifest["dst"] == item["dst"]
    assert manifest["direction"] == "bookmove"

    w = _Watcher()
    res = migrate.execute(planned["batch_id"], watcher=w)
    assert res["ok"] is True and res["moved"] == 1 and res["copies"] == 1, res

    new_id = library.book_id("三体.epub", "b")
    assert (env["b"]["root"] / "三体.epub").is_file()
    assert not (env["a"]["root"] / "三体.epub").exists()
    # ★ 关联数据跟着 id 走，旧 id 不留残留
    assert db.get_progress(new_id)["locator"] == 7
    assert db.get_overrides(new_id)["title"] == "用户改过的书名"
    assert db.get_cover(new_id)[0] == b"\xff\xd8cover"
    assert db.get_progress(old["id"]) is None
    # ★ 副本：预览算出来的名字 == 磁盘上的名字
    assert (env["b"]["pdir"] / new_rel).is_file()
    assert not (env["a"]["pdir"] / old_rel).exists()
    led = db.scrape_get(new_id)
    assert led["library_id"] == "b" and led["source_rel"] == "三体.epub"
    assert led["link_rel"] == new_rel
    assert db.scrape_get(old["id"]) is None
    # ★ 移进来的文件要登记给 watcher：去重键是「相对路径 + (size, mtime)」，
    #   新路径在它眼里是**全新投递**，不登记会被再入库一次
    assert w.seen == [str(env["b"]["root"] / "三体.epub")]


def test_有声书目录的副本整树随迁(env):
    """目录型条目：正本是一个目录，副本也是一个目录（逐文件链）——一起搬。"""
    _audio_dir(env["audio"]["root"], "活着")
    old = _book(env["audio"], "活着")
    row = _publish(env["audio"], "活着")
    old_rel = row["link_rel"]
    assert (env["audio"]["pdir"] / old_rel).is_dir()

    planned = migrate.move_plan([old["id"]], "audio2")
    item = planned["preview"]["items"][0]
    assert item["status"] == "ready" and item["is_dir"] is True
    res = migrate.execute(planned["batch_id"])
    assert res["ok"] is True and res["copies"] == 1, res

    new_rel = item["copy"]["rel"]
    assert not new_rel.endswith(".mp3") and "/" not in new_rel, \
        f"目录型副本名不该落扩展名：{new_rel}"
    assert (env["audio2"]["pdir"] / new_rel).is_dir()
    assert sorted(p.name for p in (env["audio2"]["pdir"] / new_rel).iterdir()) == \
        ["01 第一章.mp3", "02 第二章.mp3"]
    assert not (env["audio"]["pdir"] / old_rel).exists()
    assert (env["audio2"]["root"] / "活着").is_dir()
    assert not (env["audio"]["root"] / "活着").exists()


# ---------------------------------------------------------------------------
# ③ 冲突：拒绝覆盖 + 一键改名；不相容 / 源没了 -> 搬不动
# ---------------------------------------------------------------------------

def test_同名拒绝覆盖并给建议名(env):
    _epub(env["a"]["root"], "三体.epub")
    _epub(env["b"]["root"], "三体.epub")            # 乙库已有同名（内容不同）
    keep = (env["b"]["root"] / "三体.epub").read_bytes()
    bid = _book(env["a"], "三体.epub")["id"]

    pv = migrate.move_preview([bid], "b")
    item = pv["items"][0]
    assert item["status"] == "conflict" and item["suggest"] == "三体 (2).epub"
    assert migrate.move_plan([bid], "b")["batch_id"] == "", "冲突条目不进批次"
    assert (env["a"]["root"] / "三体.epub").is_file(), "预览不该动磁盘"
    assert (env["b"]["root"] / "三体.epub").read_bytes() == keep

    # 一键改名移入：用户选了建议名 → 搬得动，且 id 随新名字变
    db.set_progress(bid, 3, 12.0)
    planned = migrate.move_plan([bid], "b",
                               [{"id": bid, "action": "rename", "new_name": "三体 (2).epub"}])
    assert planned["created"] == 1
    assert migrate.execute(planned["batch_id"])["ok"] is True
    assert (env["b"]["root"] / "三体 (2).epub").is_file()
    assert (env["b"]["root"] / "三体.epub").read_bytes() == keep, "原文件不许被顶掉"
    assert db.get_progress(library.book_id("三体 (2).epub", "b"))["locator"] == 3
    assert db.get_progress(bid) is None


def test_改名不许换扩展名也不许改形态(env):
    _epub(env["a"]["root"], "三体.epub")
    _epub(env["b"]["root"], "三体.epub")
    bid = _book(env["a"], "三体.epub")["id"]

    for bad, why in (("三体.txt", "扩展名"), ("三体", "形态"), ("", "文件名")):
        pv = migrate.move_preview([bid], "b", [{"id": bid, "action": "rename", "new_name": bad}])
        item = pv["items"][0]
        assert item["status"] == "blocked" and why in item["reason"], (bad, item)
    # 路径穿越归 fileops.safe_path 管（与改名 / 回收同一道闸门）
    for bad in ("../三体.epub", "a/b/c/三体.epub"):
        pv = migrate.move_preview([bid], "b", [{"id": bid, "action": "rename", "new_name": bad}])
        assert pv["items"][0]["status"] == "blocked"


def test_目标库已有同名不同路径的书会撞id(env):
    """文件不重名、但**撞同一个 book_id**（同库同名不同路径）——搬过去该库的读点会全挂。"""
    _epub(env["a"]["root"], "三体.epub")
    _epub(env["b"]["root"], "科幻/三体.epub")        # 同 basename → 与「三体.epub」同 id
    bid = _book(env["a"], "三体.epub")["id"]

    item = migrate.move_preview([bid], "b")["items"][0]
    assert item["status"] == "conflict" and "撞 id" in item["reason"]
    assert item["suggest"] == "三体 (2).epub"


def test_不相容与源消失都搬不动(env):
    _epub(env["a"]["root"], "三体.epub")
    bid = _book(env["a"], "三体.epub")["id"]

    item = migrate.move_preview([bid], "audio")["items"][0]
    assert item["status"] == "blocked" and "有声书库" in item["reason"]
    assert migrate.move_plan([bid], "audio")["batch_id"] == ""

    (env["a"]["root"] / "三体.epub").unlink()
    item = migrate.move_preview([bid], "b")["items"][0]
    # 文件没了 → 扫描里也没有这本书了：这条报的是「已不在库里」，
    # 而不是「源已不在磁盘上」（后者只在扫描还看得见、文件却 stat 不到时才可能）
    assert item["status"] == "blocked" and "不在" in item["reason"]

    with pytest.raises(ValueError):
        migrate.move_preview([bid], "没有这个库")


# ---------------------------------------------------------------------------
# ④ 副本的三条边界：目标没成品目录 / 批次幂等 / 回滚
# ---------------------------------------------------------------------------

def test_目标库没配成品目录时副本留在原库并如实记账(env):
    _epub(env["a"]["root"], "三体.epub")
    old = _book(env["a"], "三体.epub")
    row = _publish(env["a"], "三体.epub")
    old_rel = row["link_rel"]

    item = migrate.move_preview([old["id"]], "c")["items"][0]
    assert item["copy"]["action"] == "left"
    assert "留在原库" in item["copy"]["reason"]

    res = migrate.execute(migrate.move_plan([old["id"]], "c")["batch_id"])
    assert res["ok"] is True and res["copies"] == 0
    assert (env["a"]["pdir"] / old_rel).is_file(), "副本要原地不动"
    led = db.scrape_get(library.book_id("三体.epub", "c"))
    assert led is not None, "台账要跟着书走（书的详情页按**当前** id 查）"
    assert led["status"] == "skipped" and led["link_rel"] == "", \
        "留着指旧库成品目录的 link_rel 就是一句假话"
    assert str(env["a"]["pdir"] / old_rel) in led["error"], "副本在哪必须写清楚"


def test_重复点移动得到同一批次(env):
    _epub(env["a"]["root"], "三体.epub")
    bid = _book(env["a"], "三体.epub")["id"]
    p1 = migrate.move_plan([bid], "b")
    p2 = migrate.move_plan([bid], "b")
    assert p1["batch_id"] and p1["batch_id"] == p2["batch_id"]
    assert p1["reused"] is False and p2["reused"] is True
    assert len(db.migration_batch(p1["batch_id"])) == 1, "幂等：不重复落行"


def test_bookmove批次不占用自动归库的回滚入口(env):
    """``migration_last_batch("move")`` 是自动归库的回滚入口 —— 移动不许把它顶掉。"""
    _epub(env["a"]["root"], "三体.epub")
    bid = _book(env["a"], "三体.epub")["id"]
    planned = migrate.move_plan([bid], "b")
    assert migrate.execute(planned["batch_id"])["ok"] is True

    assert migrate.DIR_AUTO == "move", "自动归库的历史字面量不能改（存量批次按它取）"
    assert migrate.last_batch() == ""
    assert migrate.last_batch(migrate.DIR_BOOKMOVE) == planned["batch_id"]


def test_回滚把副本与关联数据一起带回来(env):
    """只搬正本不算回滚：副本留在新库 → 原库架上少一本、新库多一本不在那儿的书。"""
    _epub(env["a"]["root"], "三体.epub")
    old = _book(env["a"], "三体.epub")
    row = _publish(env["a"], "三体.epub")
    old_rel = row["link_rel"]
    db.set_progress(old["id"], 5, 20.0)
    db.set_override(old["id"], "title", "用户改过的书名")
    old_id = old["id"]
    new_id = library.book_id("三体.epub", "b")

    planned = migrate.move_plan([old_id], "b")
    new_rel = planned["preview"]["items"][0]["copy"]["rel"]
    migrate.execute(planned["batch_id"], watcher=_Watcher())
    assert db.get_progress(new_id) is not None and (env["b"]["pdir"] / new_rel).is_file()

    res = migrate.rollback(planned["batch_id"])
    assert res["ok"] is True and res["restored"] == 1, res
    library.invalidate()

    assert (env["a"]["root"] / "三体.epub").is_file()
    assert not (env["b"]["root"] / "三体.epub").exists()
    # 数据搬回原 id，新 id 上不残留（否则是走不到的孤儿行）
    assert db.get_progress(old_id)["locator"] == 5
    assert db.get_overrides(old_id)["title"] == "用户改过的书名"
    assert db.get_progress(new_id) is None
    # 副本搬回原库，台账也跟着挂回原 id 并指向磁盘上的真名
    assert not (env["b"]["pdir"] / new_rel).exists()
    back = db.scrape_get(old_id)
    assert back["library_id"] == "a" and back["source_rel"] == "三体.epub"
    assert back["link_rel"] not in ("", new_rel)
    # ⚠️ 名字**不等于**当初出版时的 ``old_rel``：落点按「原库规则 + **当前生效元数据**」
    # 重算（这里改过书名，``{title}`` 就跟着变）。正向也是这么算的 —— 两边一致、
    # 且台账与磁盘逐字相符，才是这条链路的不变量；「原样搬回旧文件名」不是。
    assert back["link_rel"] != old_rel
    assert (env["a"]["pdir"] / back["link_rel"]).is_file()
    assert [p.name for p in env["a"]["pdir"].iterdir()] == [back["link_rel"]], \
        "原库成品目录里不多不少就这一份"
    assert db.scrape_get(new_id) is None
    assert [b["id"] for b in library.books() if b["name"] == "三体.epub"] == [old_id]
