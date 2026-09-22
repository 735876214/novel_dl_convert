"""第 18 期：刮削出版 —— 硬链接副本 + 源文件永不改 + 副本被删只标记待确认。

钉死四条硬约束（这是「不改变原有书籍信息」的落地口径）：

1. **源文件绝对只读**：出版 / 重建 / 删副本 / 校验之后，源文件的 inode / 大小 /
   mtime / sha256 都不变；
2. **副本禁止原地写**：写元数据必须换 inode（临时文件 + ``replace``），因此
   "内嵌过元数据" 的副本不再与源共享数据块（``link_shared=0``），而**没有内容要写**
   的副本是同 inode 的纯硬链接（``st_nlink=2``、``link_shared=1``）；
3. **副本被删只降级标记**：``verify()`` 把 ``ok`` 降成 ``removed`` + 记一条
   「原文件待确认」日志，**不自动删源、不自动重建**；
4. **删除原文件必须显式确认**且走回收目录（``CACHE_DIR/recycle``，绝不 ``unlink``）。

全部离线：``metadata_fetch`` 默认关闭 → 不外呼；真 OPF 用 ``epub_builder`` 生成。
"""
import errno
import hashlib
import os
import pathlib

import pytest

from novelforge import config
from novelforge.core import (activity_log, db, epub_builder, fileops, library,
                             publish, scrape)


# ---------------------------------------------------------------------------
# 夹具与工具
# ---------------------------------------------------------------------------

@pytest.fixture
def env(isolated, tmp_path: pathlib.Path) -> dict:  # noqa: ARG001 —— 依赖 isolated 切目录
    """一套「库根 + 独立成品目录」的环境。

    成品目录刻意放在与库根**平级**的位置（``libraries/_sorted``）：
    与库根 / 扫描源目录相交会被后端拒绝（副本会被扫回来变成重复书）。
    """
    root = tmp_path / "libraries" / "novels"
    pdir = tmp_path / "libraries" / "_sorted"
    root.mkdir(parents=True, exist_ok=True)
    db.create_library("novels", "小说库", "ebook", source_dirs=str(root),
                      publish_path=str(pdir))
    library.invalidate()
    return {"lid": "novels", "root": root, "pdir": pdir}


def _epub(root, name: str, title: str = "书") -> pathlib.Path:
    """真实可解析的 EPUB（写元数据 / 读 OPF 都必须真文件）。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": "作者", "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    return path


def _book(env: dict, name: str) -> dict:
    library.invalidate()
    b = next((x for x in library.books(env["lid"]) if x["name"] == name), None)
    assert b is not None, f"扫描不到 {name}"
    return b


def _fp(path) -> tuple:
    """文件指纹：inode / 大小 / mtime / 内容哈希。源文件「分毫未动」就靠它断言。"""
    p = pathlib.Path(path)
    st = os.stat(p)
    return (st.st_ino, st.st_size, st.st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest())


def _opf_text(path) -> str:
    _opf_path, opf, blob = fileops._read_epub(path)
    assert blob is not None, f"读不出 OPF：{path}"
    return opf


def _logs(action: str) -> list:
    return activity_log.recent(limit=100, action=action)


# ---------------------------------------------------------------------------
# ① 出版：硬链接副本 + 源文件分毫未动
# ---------------------------------------------------------------------------

def test_没有元数据可写时产出纯硬链接副本(env):
    src = _epub(env["root"], "西游.epub", title="西游")
    book = _book(env, "西游.epub")
    before = _fp(src)

    assert scrape.enqueue(book)["queued"] is True
    assert scrape.run_once()["processed"] == 1

    row = db.scrape_get(book["id"])
    assert row["status"] == "ok"
    copy = env["pdir"] / row["link_rel"]
    assert copy.is_file()
    # 没有 override / online 值 → 没有内容要写 → 保持纯硬链接（零额外占盘）
    assert row["link_mode"] == "hardlink"
    assert row["link_shared"] == 1
    assert os.stat(copy).st_ino == os.stat(src).st_ino
    assert os.stat(src).st_nlink == 2
    assert _fp(src) == before


def test_写元数据只改副本不改原文件(env):
    src = _epub(env["root"], "改写.epub", title="原名")
    book = _book(env, "改写.epub")
    db.set_override(book["id"], "title", "用户改过的名字")
    before = _fp(src)

    scrape.enqueue(book)
    scrape.run_once()

    row = db.scrape_get(book["id"])
    assert row["status"] == "ok"
    assert row["embedded"] == "title"
    copy = env["pdir"] / row["link_rel"]
    # 写入必须替换目录项 → 副本换 inode、不再共享数据块（如实记录，界面据此标注）
    assert row["link_shared"] == 0
    assert os.stat(copy).st_ino != os.stat(src).st_ino
    assert "用户改过的名字" in _opf_text(copy)
    # 源文件：内容与 inode 都没动，OPF 里还是原名
    assert _fp(src) == before
    assert "用户改过的名字" not in _opf_text(src)


def test_已是最新时不重复刮削(env):
    _epub(env["root"], "幂等.epub", title="幂等")
    book = _book(env, "幂等.epub")
    scrape.enqueue(book)
    scrape.run_once()

    again = scrape.enqueue(book)
    assert again["skipped"] is True
    assert "已是最新" in again["reason"]
    assert db.scrape_pending(limit=5) == []


def test_未配置成品目录的库不入队也不建台账(env):
    root = env["root"].parent / "nolink"
    root.mkdir(parents=True, exist_ok=True)
    db.create_library("nolink", "无成品库", "ebook", source_dirs=str(root))
    _epub(root, "无成品.epub", title="无成品")
    library.invalidate()
    book = next(x for x in library.books("nolink") if x["name"] == "无成品.epub")

    res = scrape.enqueue(book)
    assert res["skipped"] is True
    assert "未配置成品目录" in res["reason"]
    # 不建行：否则整库书都会冒出来变成噪声
    assert db.scrape_get(book["id"]) is None


def test_硬链接不可用时回退复制且源文件不变(env, monkeypatch):
    src = _epub(env["root"], "回退.epub", title="回退")
    book = _book(env, "回退.epub")
    before = _fp(src)

    def _boom(*_a, **_k):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(os, "link", _boom)
    scrape.enqueue(book)
    scrape.run_once()

    row = db.scrape_get(book["id"])
    assert row["status"] == "ok"
    assert row["link_mode"] == "copy"
    copy = env["pdir"] / row["link_rel"]
    assert copy.read_bytes() == src.read_bytes()
    assert copy.stat().st_ino != src.stat().st_ino
    assert _fp(src) == before


def test_连续失败到上限后标记失败等待人工(env, monkeypatch):
    _epub(env["root"], "失败.epub", title="失败")
    book = _book(env, "失败.epub")
    monkeypatch.setattr(publish, "publish",
                        lambda *_a, **_k: {"ok": False, "error": "磁盘炸了"})

    scrape.enqueue(book)
    scrape.run_once()                                  # 第 1 次：未到上限 → 打回 pending
    assert db.scrape_get(book["id"])["status"] == "pending"
    scrape.run_once()                                  # 第 2 次：到上限 → failed
    row = db.scrape_get(book["id"])
    assert row["status"] == "failed"
    assert row["attempts"] == 2
    assert row["error"] == "磁盘炸了"
    # 已用尽次数：扫描再入队不该反复触发（等人工）
    again = scrape.enqueue(book)
    assert again["skipped"] is True


# ---------------------------------------------------------------------------
# ② 副本被删：只标记待确认，绝不自动善后
# ---------------------------------------------------------------------------

def test_副本被删只标记待确认且不自动重建(env):
    src = _epub(env["root"], "被删.epub", title="被删")
    book = _book(env, "被删.epub")
    scrape.enqueue(book)
    scrape.run_once()
    row = db.scrape_get(book["id"])
    copy = env["pdir"] / row["link_rel"]
    before = _fp(src)

    copy.unlink()                                      # 用户在外部删掉了副本

    rep = scrape.verify()
    assert [x["book_id"] for x in rep["removed"]] == [book["id"]]
    row = db.scrape_get(book["id"])
    assert row["status"] == "removed"
    assert row["removed_path"] == str(copy)
    assert row["removed_at"] > 0
    # 三条「绝不」：不重建副本、不碰源文件、不自动降级为删除
    assert not copy.exists()
    assert _fp(src) == before
    # 日志里留下待确认提示（用户要在转换日志里看到它）
    detail = " ".join(e["detail"] for e in _logs(activity_log.ACTION_SCRAPE))
    assert "硬链接副本已删除" in detail and "原文件待确认" in detail


def test_确认删除原文件走回收目录(env):
    src = _epub(env["root"], "删源.epub", title="删源")
    book = _book(env, "删源.epub")
    scrape.enqueue(book)
    scrape.run_once()
    copy = env["pdir"] / db.scrape_get(book["id"])["link_rel"]
    copy.unlink()
    scrape.verify()

    res = scrape.resolve(book["id"], "delete_source")
    assert res["ok"] is True
    # 原文件被**移动**而不是抹除：回收目录里能找到它
    recycled = pathlib.Path(config.CACHE_DIR) / "recycle"
    names = [p.name for p in recycled.iterdir()] if recycled.is_dir() else []
    assert any(n.endswith("删源.epub") for n in names), names
    assert not src.exists()
    assert db.scrape_get(book["id"])["status"] == "source_removed"
    # 副本此时已经不存在了（用户先前删掉的），台账仍保留处置结果
    assert db.scrape_get(book["id"])["confirmed_at"] > 0


def test_确认保留原文件后不再自动复活(env):
    src = _epub(env["root"], "保留.epub", title="保留")
    book = _book(env, "保留.epub")
    scrape.enqueue(book)
    scrape.run_once()
    copy = env["pdir"] / db.scrape_get(book["id"])["link_rel"]
    copy.unlink()
    scrape.verify()
    before = _fp(src)

    assert scrape.resolve(book["id"], "keep_source")["ok"] is True
    assert db.scrape_get(book["id"])["status"] == "kept"
    assert _fp(src) == before                          # 保留就真的什么都不动

    # 只许降级：扫描再入队不会把它拉回 pending
    again = scrape.enqueue(book)
    assert again["skipped"] is True
    assert db.scrape_get(book["id"])["status"] == "kept"


def test_重新生成副本把降级状态带回已出版(env):
    _epub(env["root"], "重建.epub", title="重建")
    book = _book(env, "重建.epub")
    scrape.enqueue(book)
    scrape.run_once()
    row = db.scrape_get(book["id"])
    copy = env["pdir"] / row["link_rel"]
    copy.unlink()
    scrape.verify()
    assert db.scrape_get(book["id"])["status"] == "removed"

    res = scrape.resolve(book["id"], "rebuild")
    assert res["ok"] is True
    assert db.scrape_get(book["id"])["status"] == "ok"
    assert copy.is_file()                              # 副本回来了


def test_源文件被放回后可重新出版(env):
    """``source_removed`` 是持有状态，但源文件重新出现时**不能把这本书锁死**。

    否则：该状态下页面不给任何处置按钮 + 重新入队又被挡 → 这本书永远出不来。
    """
    src = _epub(env["root"], "放回.epub", title="放回")
    book = _book(env, "放回.epub")
    scrape.enqueue(book)
    scrape.run_once()
    copy = env["pdir"] / db.scrape_get(book["id"])["link_rel"]
    copy.unlink()
    scrape.verify()
    assert scrape.resolve(book["id"], "delete_source")["ok"] is True
    assert db.scrape_get(book["id"])["status"] == "source_removed"
    assert not src.exists()

    _epub(env["root"], "放回.epub", title="放回二版")     # 用户把文件放回源目录
    library.invalidate()
    assert scrape.enqueue(book)["queued"] is True
    scrape.run_once()
    row = db.scrape_get(book["id"])
    assert row["status"] == "ok"
    assert (env["pdir"] / row["link_rel"]).is_file()


def test_源文件不在时标记孤本(env):
    src = _epub(env["root"], "孤本.epub", title="孤本")
    book = _book(env, "孤本.epub")
    scrape.enqueue(book)
    scrape.run_once()
    copy = env["pdir"] / db.scrape_get(book["id"])["link_rel"]
    assert copy.is_file()

    src.unlink()                                       # 源被外部删除，副本还在

    rep = scrape.verify()
    assert [x["book_id"] for x in rep["orphan"]] == [book["id"]]
    row = db.scrape_get(book["id"])
    assert row["status"] == "orphan"
    assert copy.is_file()                              # 副本是唯一留存，绝不自动清理

    assert scrape.resolve(book["id"], "keep_copy")["ok"] is True
    assert db.scrape_get(book["id"])["status"] == "kept"
    assert copy.is_file()


# ---------------------------------------------------------------------------
# ③ 数据层：新库列（漏了白名单会「静默写不进」）
# ---------------------------------------------------------------------------

def test_成品目录列可写可读(isolated, env):  # noqa: ARG001
    lib = db.get_library("novels")
    assert lib["publish_path"] == str(env["pdir"])
    new = str(env["pdir"].parent / "_sorted2")
    db.update_library("novels", publish_path=new)
    assert db.get_library("novels")["publish_path"] == new
    # 空串 = 关闭该库的副本产出
    db.update_library("novels", publish_path="")
    assert db.get_library("novels")["publish_path"] == ""


def test_状态常量与台账统计(isolated):  # noqa: ARG001
    db.scrape_set("b1", library_id="l1", source_rel="a.epub", status="ok")
    db.scrape_set("b2", library_id="l1", source_rel="b.epub", status="removed",
                  removed_at=1.0, removed_path="/tmp/x")
    assert db.scrape_counts("l1") == {"ok": 1, "removed": 1}
    # 多值 status（页面的「待确认」分段就是 removed,orphan）
    assert {r["book_id"] for r in db.scrape_list(library_id="l1", status="ok,removed")} == {"b1", "b2"}
    assert [r["book_id"] for r in db.scrape_list(library_id="l1", status="ok")] == ["b1"]
    assert db.scrape_counts("nope") == {}
    # 移除库登记时台账一并清掉（**只删登记，不动副本文件**）
    assert db.scrape_delete_by_library("l1") == 2
    assert db.scrape_get("b1") is None


# ---------------------------------------------------------------------------
# ④ 接口层：注册顺序 / 鉴权 / 边界校验
# ---------------------------------------------------------------------------

def test_接口_字面量路径不被路径参数吃掉(client, auth_headers):
    """/api/scrape/state 若被 /api/scrape/{bid} 抢先注册就会 404/422。"""
    r = client.get("/api/scrape/state", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"items", "counts", "worker", "total", "needs_confirm"} <= set(body)
    assert body["worker"]["running"] is False

    r = client.post("/api/scrape/run", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    assert r.json()["queued"] == 0                     # 没有配成品目录的库


def test_接口_未登录一律401(client):
    assert client.get("/api/scrape/state").status_code == 401
    assert client.post("/api/scrape/run", json={}).status_code == 401


def test_接口_建库校验成品目录边界(client, auth_headers, tmp_path):
    base = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    root = base / "comics"
    ok = client.post("/api/libraries", headers=auth_headers, json={
        "name": "漫画库", "type": "comic",
        "source_dirs": [str(root)],
        "publish_path": str(base / "_sorted"),
    })
    assert ok.status_code == 200, ok.text
    dto = ok.json()["library"]
    assert dto["publish_path"].endswith("_sorted")
    assert dto["publish_exists"] is True                # 建库时顺手建出来

    # 与**自己**的库根重叠 → 400（副本会被扫回来变成重复书）
    bad = client.post("/api/libraries", headers=auth_headers, json={
        "name": "坏库", "type": "comic",
        "source_dirs": [str(base / "bad")],
        "publish_path": str(base / "bad" / "sorted"),
    })
    assert bad.status_code == 400
    assert "重叠" in bad.json()["detail"]

    # 扫描源目录本身也不行
    bad2 = client.post("/api/libraries", headers=auth_headers, json={
        "name": "坏库2", "type": "comic",
        "source_dirs": [str(base / "bad2")],
        "publish_path": str(base / "bad2"),
    })
    assert bad2.status_code == 400


def test_接口_非法处置动作被拒(client, auth_headers):
    r = client.post("/api/scrape/bx/resolve", headers=auth_headers,
                    json={"action": "rm -rf"})
    assert r.status_code == 400
    r = client.post("/api/scrape/bx/resolve", headers=auth_headers,
                    json={"action": "delete_source"})
    assert r.status_code == 400
    assert "台账" in r.json()["detail"]


def test_接口_扫描后按开关自动入队(client, auth_headers):
    base = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    root = base / "novels"
    root.mkdir(parents=True, exist_ok=True)
    _epub(root, "扫描.epub", title="扫描")
    created = client.post("/api/libraries", headers=auth_headers, json={
        "name": "小说库", "type": "ebook",
        "source_dirs": [str(root)],
        "publish_path": str(base / "_sorted"),
    })
    assert created.status_code == 200, created.text
    # 库 id 由名称派生（中文 slug 为空时是 lib-<sha1[:8]>），不能想当然拼字面量
    lid = created.json()["library"]["id"]

    r = client.post(f"/api/libraries/{lid}/scan", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["scrape_queued"] == 1               # 扫描 → 自动排队刮削

    st = client.get("/api/scrape/state", headers=auth_headers).json()
    assert st["total"] == 1
    item = st["items"][0]
    # ⚠️ worker 是单线程且跑得快：断言「还在排队」会随机挂（它可能已经刮完了）。
    # 「扫描后自动入队」这件事由上面的 `scrape_queued == 1` 钉住，这里只要求它
    # 没落到需要人工处置的终态（失败 / 跳过 / 待确认）。
    assert item["status"] in ("pending", "running", "ok")
    assert item["source_path"].endswith("扫描.epub")
    assert item["actions"] == []                        # 三种状态下都没有需要人工处置的事

    # 关掉该库的自动刮削后，扫描不再入队（存量条目保持原状）
    assert client.put(f"/api/libraries/{lid}/settings", headers=auth_headers,
                      json={"scrape.enabled": False}).status_code == 200
    r = client.post(f"/api/libraries/{lid}/scan", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["scrape_queued"] == 0
    # 不带 library_id 时 auto_enabled 反映的是**全局**开关，所以要指定库来断言
    st = client.get(f"/api/scrape/state?library_id={lid}", headers=auth_headers).json()
    assert st["auto_enabled"] is False
