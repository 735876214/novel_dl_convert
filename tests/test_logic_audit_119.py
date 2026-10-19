"""第 119 期全量逻辑审查的修复契约（P1/P2 + 可测的 P3）。

每条用例都对着一个**实证过的**缺陷，而不是「按风格加断言」。这里钉的是：

1. **收书目录包含性**（P1-1，未鉴权任意文件读取）：``/convert-path`` 的 ``path``
   与 ``/convert`` 的 ``filename`` 都过 `fileops.input_path`；目录内子目录照旧可用。
2. **库根不可用不是「文件全删了」**（P1-2）：索引不清空、阅读记录不判孤儿、
   回收站还原不往幻影目录里搬。
3. **「天」的口径收敛**（P2-3）：`db.daily_seconds` 按**本地日历日**切桶，
   与 `active_days` / 连续天数 / 近 N 天入库同一判据（此前是滚动 24 小时桶）。
4. **Komga 进度映射**（P2-4）：第 1 章（locator=0）能写入；非法页码不覆盖位置。
5. **分页壳与 Spring 对齐**（P3-7）：空集合 ``totalPages=0``、越界页返回空 ``content``。
6. **后台任务留强引用**（P3-6）：`server._spawn_bg` 期间任务在 `_BG_TASKS` 里、
   结束后移出（`asyncio.create_task` 扔返回值会被 GC）。
"""
import asyncio
import pathlib
import time

import pytest

from novelforge import config, server
from novelforge.core import catalog, db, fileops, komga_api, library, library_rules
from novelforge.core import pipeline
from novelforge.core import recycle


# ---------------------------------------------------------------------------
# ① 收书目录包含性（P1-1）
# ---------------------------------------------------------------------------

def test_input_path接受目录内相对路径(tmp_path):
    """正常输入照旧：平铺名与**多层子目录**都要能解析（下载插件的分目录）。"""
    assert fileops.input_path("三体.epub", base=tmp_path) == (tmp_path / "三体.epub").resolve()
    assert fileops.input_path("sub/三体.epub", base=tmp_path) == \
        (tmp_path / "sub" / "三体.epub").resolve()


@pytest.mark.parametrize("bad", [
    "../secret.epub",           # 一级穿越
    "a/../../secret.epub",      # 绕一层再穿越
    "/etc/passwd",              # 绝对路径
    "",                         # 空
    "..",                       # 纯 ..
])
def test_input_path拒绝穿越与绝对路径(tmp_path, bad):
    """可疑输入一律 ``ValueError`` —— 服务端据此回 400，绝不落到文件系统。"""
    with pytest.raises(ValueError):
        fileops.input_path(bad, base=tmp_path)


def _stub_ingest(monkeypatch, default_root, default_lid="default"):
    """让「归库规则」不再是穿越测试的挡箭牌（它本来也会返回 400）。

    这条很关键：修复前 ``path=../secret.epub`` 也是 400，但那是
    `library_rules.target_root` 返回 None（mixed 库不收该格式）挡的 ——
    换个 typed 库就 200。桩掉归库规则后，唯一的 400 来源就是包含性校验。
    """
    monkeypatch.setattr(library_rules, "target_root", lambda **kw: pathlib.Path(default_root))
    monkeypatch.setattr(library_rules, "library_id_of_root", lambda root: default_lid)
    dst = pathlib.Path(default_root) / "产物.epub"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"EPUB")
    seen = []
    monkeypatch.setattr(pipeline, "dispatch",
                        lambda src, out_dir, opts: (seen.append(pathlib.Path(src)),
                                                    ("copy", dst))[1])
    return seen


def test_convert_path拒绝穿越收书目录(client, default_root, monkeypatch):
    """**不带 Authorization**：这条路由历史上就不强制鉴权，故校验必须在路径层。

    探针（修复前）：收书目录里放 ``../secret.epub`` ⇒ 200 + 原始字节 +
    ``Content-Disposition: attachment``，等于一条未鉴权的任意文件读取。
    """
    src = pathlib.Path(config.INPUT_DIR)
    src.mkdir(parents=True, exist_ok=True)
    secret = src.parent / "secret.epub"
    secret.write_bytes(b"TOPSECRET-EPUB-PAYLOAD")
    seen = _stub_ingest(monkeypatch, default_root)

    r = client.post("/convert-path", data={"path": "../secret.epub"})
    assert r.status_code == 400, r.text
    assert "非法路径" in r.text
    assert b"TOPSECRET" not in r.content
    assert seen == [], "穿越路径不该走到转换链路"


def test_convert_path目录内子目录仍然可用(client, auth_headers, default_root, monkeypatch):
    """收紧的是「出不出收书目录」——目录里的一层子目录必须照旧能导入。"""
    src = pathlib.Path(config.INPUT_DIR) / "某下载器"
    src.mkdir(parents=True, exist_ok=True)
    (src / "来源.epub").write_bytes(b"EPUB")
    seen = _stub_ingest(monkeypatch, default_root, "default")

    r = client.post("/convert-path", data={"path": "某下载器/来源.epub"},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    assert [p.name for p in seen] == ["来源.epub"]


def test_convert上传文件名穿越被拒(client, auth_headers, default_root, monkeypatch):
    """``file.filename`` 是**客户端给的**：``../../x.epub`` 不能决定落盘位置。"""
    _stub_ingest(monkeypatch, default_root)
    r = client.post("/convert", data={"traditionalize": "false"},
                    files={"file": ("../../evil.epub", b"EPUB")}, headers=auth_headers)
    assert r.status_code == 400, r.text
    assert "非法路径" in r.text


# ---------------------------------------------------------------------------
# ② 库根不可用不是「文件全删了」（P1-2）
# ---------------------------------------------------------------------------

def _lib_with_books(make_library, lid, names):
    """建一个就地引用库并放几本书，返回 ``(lib, book_ids)``。"""
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / lid
    make_library(lid, lid, "ebook", root)
    root.mkdir(parents=True, exist_ok=True)
    for n in names:
        (root / n).write_bytes(b"EPUB")
    library.invalidate()
    lib = library.get_library(lid)
    return lib, [b["id"] for b in library.books(lid)]


def test_库根不可用时不做删除(isolated, make_library):
    """根掉线 ⇒ 这一轮「扫到 0 个」不可信，**跳过删除**并如实回报原因。

    修复前：把根改名后 ``refresh_library`` 返回 ``removed: 2`` 且索引清空；
    监听线程每 60s 自动跑一次这条路，用户什么都没做，书架就空了。
    """
    lib, bids = _lib_with_books(make_library, "offline-lib", ["三体.epub", "球状闪电.epub"])
    assert catalog.refresh_library(lib, force=True)["scanned"] == 2

    root = library.roots_of(lib)[0]
    root.rename(root.with_name(root.name + "-offline"))
    try:
        res = catalog.refresh_library(lib, force=True)
        assert res["skipped"] is True and res["reason"] == "root_unavailable"
        assert res["removed"] == 0
        # 索引行原样保留 —— 挂载回来后 book_id 不变、进度与批注都还认得
        assert {b["id"] for b in library.books("offline-lib")} == set(bids)
    finally:
        root.with_name(root.name + "-offline").rename(root)


def test_库根真的被清空时照旧删行(isolated, make_library):
    """反方向：根**在**、只是空了 ⇒ 用户真把库清空了，索引必须跟着空。

    没有这条，上一条就退化成「索引永远不删」，删掉的书会留在书架上点不开。
    """
    lib, _ = _lib_with_books(make_library, "empty-lib", ["三体.epub"])
    assert catalog.refresh_library(lib, force=True)["scanned"] == 1
    (library.roots_of(lib)[0] / "三体.epub").unlink()
    res = catalog.refresh_library(lib, force=True)
    assert res["removed"] == 1 and res["skipped"] is False
    assert library.books("empty-lib") == []


def test_库根离线时阅读记录不判孤儿(isolated, make_library):
    """第二道护栏：该库当前一本书都没索引到 ⇒ 它的关联行不进「可清理」清单。

    清理是真 ``DELETE``（不进回收站），而「书架空了」正是根掉线的表现 ——
    没有这道护栏，用户看一眼空书架、点一下清理，进度与批注就永久没了。
    """
    lib, bids = _lib_with_books(make_library, "orphan-lib", ["三体.epub"])
    bid = bids[0]
    db.set_progress(bid, 3, 42.0)
    db.add_annotation(bid, 0, "原文", "yellow", "想法")
    root = library.roots_of(lib)[0]
    root.rename(root.with_name(root.name + "-offline"))
    try:
        # 索引被清空的另一种形态（Docker 挂载缺失：根变成**存在且可读的空目录**，
        # 上面那道「根不可用」判据分辨不出，行会被删掉）—— 用 forget 精确模拟它。
        catalog.forget("orphan-lib")
        library.invalidate("orphan-lib")
        assert library.books("orphan-lib") == []
        refs = server._orphan_refs()
        flat = [i for ids in refs.values() for i in ids]
        assert bid not in flat, f"库根离线时不该把它的行判成孤儿（{refs}）"
    finally:
        root.with_name(root.name + "-offline").rename(root)


def test_库根在线时残留行照旧可清理(isolated, make_library):
    """护栏不能把清理功能废掉：库有书、某本书真没了 ⇒ 它的行仍要能被清掉。"""
    lib, bids = _lib_with_books(make_library, "live-lib", ["三体.epub", "球状闪电.epub"])
    gone = bids[0]
    db.set_progress(gone, 3, 42.0)
    (library.roots_of(lib)[0] / "三体.epub").unlink()
    library.invalidate("live-lib")
    refs = server._orphan_refs()
    flat = [i for ids in refs.values() for i in ids]
    assert gone in flat, f"库在线、这本书确实没了，应判孤儿（{refs}）"


def test_回收站还原不往幻影目录搬(isolated, make_library):
    """库根不在（未挂载）⇒ 还原**拒绝**，文件留在回收站。

    修复前：``target.parent.mkdir(parents=True, exist_ok=True)`` 在本地盘上造出
    幻影目录并把文件搬进去，然后回收站那份就没了 —— 表现为「还原成功、但找不到书」。
    """
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "rc-lib"
    make_library("rc-lib", "rc-lib", "ebook", root)
    root.rmdir()                                   # 模拟「挂载没挂上 / 盘掉了」
    src = fileops.recycle_dir() / "三体.epub"
    src.write_bytes(b"EPUB")

    res = recycle.restore_one(src, root / "三体.epub")
    assert res["state"] == "failed"
    assert "不可用" in res["error"]
    assert src.exists(), "拒绝时文件必须留在回收站"
    assert not root.exists(), "不该在本地盘上造出幻影目录"


# ---------------------------------------------------------------------------
# ③ 「天」的口径（P2-3）
# ---------------------------------------------------------------------------

def _today0() -> float:
    """本地**今天零点**（与 `db.local_day` 同一口径）。"""
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def test_每日阅读按本地日历日切桶(isolated, make_library):
    """昨 23:30 与今 00:30 必须落在**不同**桶里。

    修复前是 ``int((now - ended_at) // 86400)`` 的滚动 24 小时桶 —— 两段都在最近
    24 小时内，于是都算「今天」，而前端把桶标成「1 天前 / 今天」⇒ 图与数字矛盾。
    """
    lib, bids = _lib_with_books(make_library, "day-lib", ["三体.epub"])
    bid = bids[0]
    t0 = _today0()
    db.add_session(bid, 60, started_at=t0 - 3600, ended_at=t0 + 1800)    # 今天 00:30
    db.add_session(bid, 120, started_at=t0 - 4800, ended_at=t0 - 1800)   # 昨天 23:30

    buckets = db.daily_seconds(7)
    assert buckets[-1] == 60.0, buckets
    assert buckets[-2] == 120.0, buckets

    # 同一判据：active_days 也给出两天
    days = db.active_days()
    today = db.local_day(time.time())
    assert days[-1] == today.isoformat()
    assert days[-2] == db.local_day(t0 - 1800).isoformat()


def test_local_day与active_days同一口径(isolated):
    """`db.local_day` 是「哪天」的唯一入口：active_days 必须与它逐值对齐。"""
    ts = 1_700_000_000.0
    assert db.local_day(ts).isoformat() == time.strftime("%Y-%m-%d", time.localtime(ts))


# ---------------------------------------------------------------------------
# ④ Komga 进度映射（P2-4）
# ---------------------------------------------------------------------------

def _epub_book(bid):
    return {"id": bid, "name": "三体.epub", "format": "EPUB"}


def test_komga第一章的位置也能写入(isolated, make_library, monkeypatch):
    """``href`` 对上 spine 第 0 章（locator=0）时必须写入 0。

    修复前用 ``if not locator`` 判「没对上」，把合法的 0 当成缺失 ⇒ 读者在第一章
    时进度永远停在原处（探针：返回 ``(7, 2.0)``，percent 动了、位置没动）。
    """
    lib, bids = _lib_with_books(make_library, "km-lib", ["三体.epub"])
    bid = bids[0]
    db.set_progress(bid, 7, 40.0)
    monkeypatch.setattr(library, "_spine", lambda p: ["ch0.xhtml", "ch1.xhtml"])
    monkeypatch.setattr(library, "root_of", lambda b: pathlib.Path("/tmp"))

    loc, pct = komga_api.apply_read_progress(_epub_book(bid), {
        "locator": {"href": "ch0.xhtml", "locations": {"progression": 0.02}}})
    assert (loc, pct) == (0, 2.0), (loc, pct)


def test_komga对不上的href只更新百分比(isolated, make_library, monkeypatch):
    """``href`` 对不上 spine（换过版本 / 外部 EPUB）⇒ 保留原位置，只动 percent。"""
    lib, bids = _lib_with_books(make_library, "km2-lib", ["三体.epub"])
    bid = bids[0]
    db.set_progress(bid, 7, 40.0)
    monkeypatch.setattr(library, "_spine", lambda p: ["ch0.xhtml"])
    monkeypatch.setattr(library, "root_of", lambda b: pathlib.Path("/tmp"))

    loc, pct = komga_api.apply_read_progress(_epub_book(bid), {
        "locator": {"href": "nope.xhtml", "locations": {"progression": 0.5}}})
    assert loc == 7 and pct == 50.0


def test_komga非法页码不覆盖位置(isolated, make_library):
    """``page=0``（1 起编号里不合法）只把 percent 归零，**位置保留**。

    与 ``completed: true`` 保留 locator 同一取向：拿不到位置就别毁掉位置。
    """
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "km3-lib"
    make_library("km3-lib", "km3-lib", "comic", root)
    (root / "三体.cbz").write_bytes(b"CBZ")
    library.invalidate()
    bids = [b["id"] for b in library.books("km3-lib")]
    bid = bids[0]
    db.set_progress(bid, 5, 30.0)
    book = {"id": bid, "name": "三体.cbz", "format": "CBZ", "pages": 20}
    assert komga_api.apply_read_progress(book, {"page": 0}) == (5, 0.0)
    assert komga_api.apply_read_progress(book, {"page": 3}) == (2, 15.0)


# ---------------------------------------------------------------------------
# ⑤ 分页壳（P3-7）
# ---------------------------------------------------------------------------

def test_分页空集合的totalPages为零():
    """Spring ``PageImpl``：空集合 ``totalPages=0``。给 1 会让客户端以为还有一页。"""
    pg = komga_api.paginate([], page=0, size=20)
    assert pg["totalPages"] == 0
    assert pg["content"] == [] and pg["empty"] is True
    assert pg["first"] is True and pg["last"] is True


def test_分页越界页返回空content():
    """越界页码原样回显、内容为空 —— 夹到最后一页会把客户端算错页伪装成「就这么多」。"""
    pg = komga_api.paginate(list(range(5)), page=9, size=2)
    assert pg["totalPages"] == 3
    assert pg["content"] == [] and pg["number"] == 9
    assert pg["last"] is True


# ---------------------------------------------------------------------------
# ⑥ 后台任务强引用（P3-6）
# ---------------------------------------------------------------------------

def test_后台任务被强引用到结束():
    """``_spawn_bg`` 期间任务在 `_BG_TASKS` 里，结束后移除。

    直接 ``asyncio.create_task(coro)`` 丢掉返回值时，事件循环只持弱引用：
    任务可能在跑完前被 GC（「Task was destroyed but it is pending!」），
    异常也只在那时以「Task exception was never retrieved」打在 stderr 上。
    """
    async def main():
        ev = asyncio.Event()

        async def waiter():
            await ev.wait()

        t = server._spawn_bg(waiter())
        assert t in server._BG_TASKS, "任务必须有强引用"
        ev.set()
        await t
        await asyncio.sleep(0)                 # 让 done callback 跑完
        assert t not in server._BG_TASKS, "结束后要从集合里移除"

    asyncio.run(main())
