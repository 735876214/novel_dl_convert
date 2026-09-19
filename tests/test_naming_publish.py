"""第 28 期：命名规则 → **副本名**（预览 == 落盘、只动副本、冲突不静默落盘）。

「批量重命名」并入刮削后，改名只剩一个口径：**改硬链接副本的文件名，源文件永远只读**。
这个文件钉住那条口径落地时的四件事：

1. **预览 == 落盘**：``/api/naming/preview``（``scrape.plan_naming``）给出的 ``new_rel``
   必须与重出版后台账里的 ``link_rel`` **逐字相同** —— 两者共用
   ``publish.relpath_for``，走岔了就是「预览说 A、磁盘上叫 B」。
2. **只动副本**：源文件指纹（inode / 大小 / mtime / 哈希）与源文件名分毫不动，
   ``book_id`` 因此不变、挂在这个 id 上的数据（元数据覆盖 / 批注）不受影响；
   旧副本名进回收目录，成品目录里**不留双份**。
3. **不外呼**：重出版走 ``process(bid, fetch=False)``，即使把在线抓取打开也不调
   ``metafetch``（下面直接把 auto_fetch 换成会炸的函数来钉死）。
4. **冲突不静默落盘**：落点被别人占着 / 同批内重名 → 预览标 ``conflict``、
   重出版跳过，且**不会**出现 ``书名 (2).ext`` 这种「预览没说过」的名字。

同批钉死旧接口已删干净：``/api/rename/preview`` 与 ``/api/rename/apply`` 必须 404。
"""
from __future__ import annotations

import hashlib
import os
import pathlib

import pytest

from novelforge.core import (db, epub_builder, fileops, lib_settings, library,
                             metafetch, publish, scrape)


# ---------------------------------------------------------------------------
# 夹具与工具（与 test_scrape_publish.py 同构：库根 + 平级成品目录）
# ---------------------------------------------------------------------------

@pytest.fixture
def env(isolated, tmp_path: pathlib.Path) -> dict:  # noqa: ARG001 —— 依赖 isolated 切目录
    root = tmp_path / "libraries" / "novels"
    pdir = tmp_path / "libraries" / "_sorted"
    root.mkdir(parents=True, exist_ok=True)
    db.create_library("novels", "小说库", "ebook", "inplace", str(root),
                      source_subdir="novels", publish_path=str(pdir))
    library.invalidate()
    return {"lid": "novels", "root": root, "pdir": pdir}


def _epub(root, name: str, title: str = "书", author: str = "作者",
          **meta) -> pathlib.Path:
    """真 EPUB；``meta`` 里的字段（series_index / date…）写进 OPF —— 扫描才读得到。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": author, "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    if meta:
        assert fileops.patch_epub_meta(path, meta), f"OPF 改写失败：{name}"
    return path


def _book(env: dict, name: str) -> dict:
    library.invalidate()
    b = next((x for x in library.books(env["lid"]) if x["name"] == name), None)
    assert b is not None, f"扫描不到 {name}"
    return b


def _fp(path) -> tuple:
    """文件指纹：inode / 大小 / mtime / 内容哈希。源文件「分毫未动」靠它断言。"""
    p = pathlib.Path(path)
    st = os.stat(p)
    return (st.st_ino, st.st_size, st.st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest())


def _rule(env: dict, pattern: str, scope: str = "all") -> None:
    """改该库的命名规则（走每库覆盖，与面板同一条路径）。"""
    lib_settings.set_overrides(env["lid"], {"naming.pattern": pattern,
                                            "naming.scope": scope})
    library.invalidate()


def _publish(env: dict, name: str) -> dict:
    """出版一本，返回它的台账行。"""
    book = _book(env, name)
    assert scrape.enqueue(book)["queued"] is True
    assert scrape.run_once()["processed"] == 1
    row = db.scrape_get(book["id"])
    assert row["status"] == "ok", row
    return row


# ---------------------------------------------------------------------------
# ① 预览 == 落盘
# ---------------------------------------------------------------------------

def test_预览名就是重出版后的落盘名(env):
    """含 {series_index} 的规则：**出版侧原先不认这个占位符**，会把字面 token 写进文件名。

    预览与落盘共用 fill_pattern 之后，两边必须逐字一致。
    """
    _epub(env["root"], "基地.epub", title="基地", series_index="2")
    _rule(env, "{author} - {title}")            # 先按默认规则出版
    row = _publish(env, "基地.epub")
    old_rel = row["link_rel"]
    assert (env["pdir"] / old_rel).is_file()

    _rule(env, "{series_index}. {author} - {title}")
    plan = scrape.plan_naming(env["lid"])
    item = next(it for it in plan["items"] if it["book_id"] == row["book_id"])
    assert item["changed"] is True
    # {series_index} 是书目原值（2），{index} 才是两位补零的卷号（02）
    assert item["new_rel"] == "2. 作者 - 基地.epub"
    assert "{" not in item["new_rel"]

    res = scrape.republish(None, env["lid"])
    assert res["done"] == 1 and res["failed"] == 0, res

    # ★ 预览说的名字 == 台账（也就是磁盘）上的名字
    after = db.scrape_get(row["book_id"])
    assert after["link_rel"] == item["new_rel"]
    assert (env["pdir"] / after["link_rel"]).is_file()


def test_重出版把旧副本移入回收不留双份(env):
    _epub(env["root"], "旧名.epub", title="旧名")
    _rule(env, "{title}")
    row = _publish(env, "旧名.epub")
    old_rel = row["link_rel"]
    _rule(env, "{author} - {title}")

    scrape.republish(None, env["lid"])

    new_rel = db.scrape_get(row["book_id"])["link_rel"]
    assert new_rel != old_rel
    assert not (env["pdir"] / old_rel).exists()          # 旧名不留（回收，不是 unlink）
    assert (env["pdir"] / new_rel).is_file()
    recycled = [p.name for p in fileops.recycle_dir().iterdir()]
    assert any(pathlib.PurePosixPath(old_rel).name in n for n in recycled), recycled


# ---------------------------------------------------------------------------
# ② 只动副本：源文件与挂在 book_id 上的数据都不受影响
# ---------------------------------------------------------------------------

def test_重出版不动源文件也不动关联数据(env):
    src = _epub(env["root"], "只读.epub", title="只读")
    _rule(env, "{title}")
    row = _publish(env, "只读.epub")
    bid = row["book_id"]
    before, fp_before = src.name, _fp(src)
    db.set_override(bid, "title", "用户改过的名字")
    db.add_annotation(bid, chapter=0, quote="批注", color="teal", note="")

    _rule(env, "{author} —— {title}")
    assert scrape.republish(None, env["lid"])["done"] == 1

    # 源文件名 / 指纹分毫未动
    assert src.name == before and _fp(src) == fp_before
    # book_id 不变 → 挂在上面的覆盖与批注照旧（曾经的真缺陷：改文件名会把这些搁浅）
    assert db.get_overrides(bid).get("title") == "用户改过的名字"
    assert db.annotation_counts().get(bid) == 1
    assert library.by_id(bid) is not None


# ---------------------------------------------------------------------------
# ③ 不外呼
# ---------------------------------------------------------------------------

def test_重出版不外呼(env, monkeypatch):
    """把在线抓取**打开**，并且让 auto_fetch 直接炸 —— 重出版仍须成功。"""
    _epub(env["root"], "离线.epub", title="离线")
    _publish(env, "离线.epub")
    _rule(env, "{author} · {title}")
    lib_settings.set_overrides(env["lid"], {"metadata_fetch.enabled": True})

    def _boom(*a, **k):                               # noqa: ANN002, ANN003
        raise AssertionError("重出版不该外呼在线元数据抓取")

    monkeypatch.setattr(metafetch, "auto_fetch", _boom)

    res = scrape.republish(None, env["lid"])
    assert res["done"] == 1 and res["failed"] == 0, res


# ---------------------------------------------------------------------------
# ④ 冲突：标出来、跳过去、不落「(2)」名
# ---------------------------------------------------------------------------

def test_落点被占用时预览标冲突且不落盘(env):
    _epub(env["root"], "占用.epub", title="占用")
    _rule(env, "{author} - {title}")
    row = _publish(env, "占用.epub")
    _rule(env, "{title}")
    plan = scrape.plan_naming(env["lid"])
    item = next(it for it in plan["items"] if it["book_id"] == row["book_id"])
    new_rel = item["new_rel"]

    # 往目标位置放一个「别人的」文件（成品目录是给人看的普通目录）
    foreign = env["pdir"] / new_rel
    foreign.write_text("用户自己的东西", encoding="utf-8")

    plan2 = scrape.plan_naming(env["lid"])
    item2 = next(it for it in plan2["items"] if it["book_id"] == row["book_id"])
    assert item2["conflict"] == "occupied"
    assert plan2["stats"]["ready"] == 0

    res = scrape.republish(None, env["lid"])
    assert res["total"] == 0 and res["skipped"] == 1, res
    # 别人的文件原样保留，且没有被逼出一个 (2) 名
    assert foreign.read_text(encoding="utf-8") == "用户自己的东西"
    assert not list(env["pdir"].glob("* (2)*"))


def test_同批内落点重复时都不动(env):
    _epub(env["root"], "甲.epub", title="同名", author="甲")
    _epub(env["root"], "乙.epub", title="同名", author="乙")
    _rule(env, "{author} - {title}")
    _publish(env, "甲.epub")
    _publish(env, "乙.epub")

    _rule(env, "{title}")                              # 两本都叫「同名.epub」
    plan = scrape.plan_naming(env["lid"])
    assert {it["conflict"] for it in plan["items"]} == {"dup"}
    assert plan["stats"]["ready"] == 0

    res = scrape.republish(None, env["lid"])
    assert res["total"] == 0, res
    assert not list(env["pdir"].glob("* (2)*"))


def test_名字没变的书直接跳过(env):
    _epub(env["root"], "不动.epub", title="不动")
    _rule(env, "{author} - {title}")
    _publish(env, "不动.epub")

    res = scrape.republish(None, env["lid"])

    # 白搬一次文件没有意义（还会白写一遍副本）→ 计划为空，一本都不动
    assert (res["total"], res["done"], res["failed"], res["skipped"]) == (0, 0, 0, 1)


# ---------------------------------------------------------------------------
# ⑤ 接口：新入口在、旧入口已删干净（method + path 一起断言）
# ---------------------------------------------------------------------------

def test_旧改名接口已删除返回404(client, auth_headers, env):  # noqa: ARG001
    """删功能要删干净：旧入口必须是 404，而不是还能用或改个名继续活着。"""
    for path in ("/api/rename/preview", "/api/rename/apply"):
        r = client.post(path, headers=auth_headers, json={"items": []})
        assert r.status_code == 404, f"{path} → {r.status_code}"


def test_重出版接口只认服务端算出的目标(client, auth_headers, env):
    """客户端给 book_ids 只做**收窄**：冲突项与无变化的书一律不做（说了不算）。"""
    _epub(env["root"], "收窄.epub", title="收窄")
    _rule(env, "{author} - {title}")
    row = _publish(env, "收窄.epub")

    # 名字没变 → 即便点名也跳过
    r = client.post("/api/naming/apply", headers=auth_headers,
                    json={"library_id": env["lid"], "book_ids": [row["book_id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0 and r.json()["skipped"] == 1

    # 未知 book_id 同样只收窄、不报错
    r2 = client.post("/api/naming/apply", headers=auth_headers,
                     json={"library_id": env["lid"], "book_ids": ["不存在"]})
    assert r2.status_code == 200 and r2.json()["total"] == 0


def test_预览接口回显生效规则(client, auth_headers, env):
    _rule(env, "{series_index}. {title}")
    r = client.post("/api/naming/preview", headers=auth_headers,
                    json={"library_id": env["lid"]})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pattern"] == "{series_index}. {title}"
    assert body["scope"] == "all"
    assert body["fields"] == list(fileops.PATTERN_FIELDS)


def test_未出版的书不进预览(client, auth_headers, env):
    """预览只列**已出版**的书：没副本的书归「开始刮削」管，列出来只是噪声。"""
    _epub(env["root"], "没出版.epub", title="没出版")
    _rule(env, "{title}")

    body = client.post("/api/naming/preview", headers=auth_headers,
                       json={"library_id": env["lid"]}).json()

    assert body["items"] == []
    assert body["stats"]["total"] == 0


def test_预览_落盘_接口两条路径同源(client, auth_headers, env):
    """走 HTTP 的端到端：预览拿到的 new_rel == 重出版后台账里的 link_rel。"""
    _epub(env["root"], "同源.epub", title="同源")
    _rule(env, "{title}")
    row = _publish(env, "同源.epub")
    _rule(env, "{author} - {title}")

    body = client.post("/api/naming/preview", headers=auth_headers,
                       json={"library_id": env["lid"]}).json()
    item = next(it for it in body["items"] if it["book_id"] == row["book_id"])
    assert item["changed"] is True

    r = client.post("/api/naming/apply", headers=auth_headers,
                    json={"library_id": env["lid"]})
    assert r.status_code == 200 and r.json()["done"] == 1, r.text
    assert db.scrape_get(row["book_id"])["link_rel"] == item["new_rel"]


def test_publish的落点判据与预览一致(env):
    """`rel_verdict` 是预览与落盘共用的唯一判据 —— 直接钉住它的三档语义。"""
    _epub(env["root"], "判据.epub", title="判据")
    _rule(env, "{title}")
    row = _publish(env, "判据.epub")
    rel = row["link_rel"]
    src = env["root"] / "判据.epub"

    # 落点空着 → 直接用
    assert publish.rel_verdict(env["pdir"], "空着.epub", src, "") == publish.REL_REUSE
    # 落点已是**本源**的硬链接 → 也是直接用（纯硬链接副本没写过元数据，本来就同 inode）
    assert publish.rel_verdict(env["pdir"], rel, src, rel) == publish.REL_REUSE
    # 落点被占、又判不出是本源的东西（这里用「源已不在」代表）→ 退让改名
    assert publish.rel_verdict(env["pdir"], rel, pathlib.Path("/nowhere"),
                               "别的名字.epub") == publish.REL_DECLINE
    # 落点就是本书记台账的旧副本 → 回收后重建（不是退让、也不是复用）
    assert publish.rel_verdict(env["pdir"], rel, pathlib.Path("/nowhere"), rel) \
        == publish.REL_REBUILD


# ---------------------------------------------------------------------------
# ⑤ 与实体改名不交叉：改名只写元数据，重出版只改副本名
# ---------------------------------------------------------------------------

def test_实体改名后重出版用新名字而源文件名不变(env):
    """两条路各管一头，谁也不碰源文件：

    · 实体改名 → 写服务端元数据（源文件名不动）；
    · 重出版   → 按规则展开**生效**元数据 ⇒ 副本名跟着变成新作者名。
    """
    src = _epub(env["root"], "基地.epub", title="基地", author="阿西莫夫")
    _rule(env, "{author} - {title}")
    _publish(env, "基地.epub")
    fp_before = _fp(src)

    res = fileops.apply_entity_rename("author", "阿西莫夫", "艾萨克·阿西莫夫", env["lid"])
    assert res["count"] == 1 and res["errors"] == []
    assert src.name == "基地.epub" and _fp(src) == fp_before, "实体改名不碰源文件"

    plan = scrape.plan_naming(env["lid"])
    it = plan["items"][0]
    assert it["old_rel"] == "阿西莫夫 - 基地.epub"
    assert it["new_rel"] == "艾萨克·阿西莫夫 - 基地.epub", "规则展开读的是生效值"
    assert it["changed"] is True and not it["conflict"]

    assert scrape.republish(None, env["lid"])["done"] == 1
    assert db.scrape_get(it["book_id"])["link_rel"] == it["new_rel"]
    assert src.name == "基地.epub" and _fp(src) == fp_before, "重出版也不碰源文件"
    assert not (env["pdir"] / "阿西莫夫 - 基地.epub").exists(), "旧副本已回收，不留双份"
