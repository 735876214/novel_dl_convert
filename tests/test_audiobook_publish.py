"""第 29 期：**目录型有声书出版**（一章一文件整目录 = 一本书）。

出版模块原先用 ``if not src.is_file()`` 一票否决，目录型条目直接判「跳过」。这个文件
钉住放开之后必须同时成立的四件事 —— 其中第 1、2 条是本项风险最高的地方：

1. **源目录只读**：逐文件指纹（相对路径 / inode / 大小 / mtime / 内容哈希）与目录名
   分毫不动，源里也不多出任何文件；
2. **副本是真目录且逐文件同 inode**：``os.link`` 不能对目录用，所以逐文件链；只要有一个
   文件退化成复制，``mode`` 就必须如实报 ``copy``（页面那一栏是给用户看占不占空间的）；
3. **指纹必须是整树指纹**：单文件那套 ``[size, mtime]`` 对目录是**错的** —— 目录自身的
   mtime 不随内部文件内容变化（改一轨音频不碰父目录），而**音轨改名改变章序**（顺序就是
   文件名顺序），两件事都必须被 ``source_sig`` 逮到；
4. **既有不变量一条不松**：旧副本目录进回收目录不留双份、落点被占时退让不覆盖、
   重出版不外呼、``relpath_for`` 对目录条目**不落扩展名**。

另钉一处一致性：目录条目的落点与入库侧（``pipeline.dispatch``）**同规则**
（都走 ``komga.relpath_for_dir``），否则「入库放 A、出版放 B」。
"""
from __future__ import annotations

import hashlib
import os
import pathlib

import pytest

from novelforge.core import (db, fileops, komga, lib_settings, library, metafetch,
                             pipeline, publish, scrape)


# ---------------------------------------------------------------------------
# 夹具与工具（与 test_naming_publish.py 同构：库根 + 平级成品目录）
# ---------------------------------------------------------------------------

@pytest.fixture
def env(isolated, tmp_path: pathlib.Path) -> dict:  # noqa: ARG001 —— 依赖 isolated 切目录
    root = tmp_path / "libraries" / "audio"
    pdir = tmp_path / "libraries" / "_sorted"
    root.mkdir(parents=True, exist_ok=True)
    db.create_library("audio", "有声书库", "audiobook", "inplace", str(root),
                      source_subdir="audio", publish_path=str(pdir))
    library.invalidate()
    return {"lid": "audio", "root": root, "pdir": pdir}


def _audio_dir(root, name: str, tracks=("01 第一章.mp3", "02 第二章.mp3"),
               pad: int = 16) -> pathlib.Path:
    """造一个「一章一文件」的有声书目录。

    不写真 mp3：本项目对音频**只看扩展名**（``audio.AUDIO_EXTS``），轨道清单与体积
    都来自文件系统元数据，所以内容是不是合法音频与出版链路无关。
    """
    d = pathlib.Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(tracks):
        (d / t).write_bytes(b"ID3" + bytes([i]) * pad)
    return d


def _book(env: dict, name: str) -> dict:
    library.invalidate()
    b = next((x for x in library.books(env["lid"]) if x["name"] == name), None)
    assert b is not None, f"扫描不到 {name}"
    return b


def _tree_fp(root) -> list:
    """目录指纹：逐文件 (相对路径, inode, 大小, mtime, 内容哈希)。"""
    root = pathlib.Path(root)
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        st = p.stat()
        out.append((p.relative_to(root).as_posix(), st.st_ino, st.st_size, st.st_mtime_ns,
                    hashlib.sha256(p.read_bytes()).hexdigest()))
    return out


def _rule(env: dict, pattern: str, scope: str = "all") -> None:
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
# ① 源目录只读 + 副本是真目录、逐文件同 inode
# ---------------------------------------------------------------------------

def test_目录型有声书出版成真目录且逐文件同inode(env):
    src = _audio_dir(env["root"], "基地")
    row = _publish(env, "基地")

    dst = env["pdir"] / row["link_rel"]
    assert dst.is_dir() and not dst.is_symlink(), "副本必须是真目录（符号链接会让写副本改到源）"
    assert row["link_mode"] == publish.LINK_HARD
    assert row["link_shared"] == 1, "逐文件都同 inode 才算共享数据块"

    # 逐文件同 inode（这是「不额外占盘」的**唯一**证据）
    for f in sorted(src.rglob("*")):
        if f.is_file():
            assert publish.same_file(f, dst / f.relative_to(src)), f.name
    # 目录名逐字不变、源里不多出任何文件
    assert src.name == "基地" and len(_tree_fp(src)) == 2


def test_源目录逐文件指纹与目录名分毫未动(env):
    src = _audio_dir(env["root"], "只读有声书")
    before, fp_before = src.name, _tree_fp(src)

    _rule(env, "{title}")
    _publish(env, "只读有声书")
    scrape.republish(None, env["lid"])

    assert src.name == before, "源目录名不许改"
    assert _tree_fp(src) == fp_before, "源目录内逐文件都不许动（inode/大小/mtime/内容）"


def test_元数据只落服务端不写副本目录(env):
    """音频目录没有 OPF 可写 —— 元数据照旧只存 DB，副本里不许凭空多出文件。"""
    src = _audio_dir(env["root"], "不写盘")
    row = _publish(env, "不写盘")
    db.set_override(row["book_id"], "title", "用户改过的名字")
    db.set_override(row["book_id"], "author", "用户改过的作者")

    assert scrape.republish(None, env["lid"])["total"] == 0     # 名字没变，一本都不动
    assert scrape.resolve(row["book_id"], "rebuild")["ok"] is True

    dst = env["pdir"] / db.scrape_get(row["book_id"])["link_rel"]
    assert [p.name for p in sorted(dst.rglob("*")) if p.is_file()] \
        == [p.name for p in sorted(src.rglob("*")) if p.is_file()], "副本里不许多出元数据文件"
    assert db.get_overrides(row["book_id"])["title"] == "用户改过的名字"


# ---------------------------------------------------------------------------
# ② 整树指纹：目录 mtime 看不出的事，指纹必须看出来
# ---------------------------------------------------------------------------

def test_改一轨音频内容会触发重刮(env):
    """**单文件 size/mtime 那一套对目录是错的**：改内部文件的字节不会碰父目录的 mtime。"""
    src = _audio_dir(env["root"], "改内容")
    _publish(env, "改内容")

    dir_mtime = os.stat(src).st_mtime_ns
    (src / "01 第一章.mp3").write_bytes(b"ID3" + b"x" * 64)     # 换内容，大小也变了

    assert os.stat(src).st_mtime_ns == dir_mtime, "前置条件：目录自身 mtime 不变"
    book = _book(env, "改内容")
    r = scrape.enqueue(book)
    assert r["queued"] is True and "已是最新" not in r["reason"], r


def test_音轨改名也算源变更(env):
    """音轨顺序 = 文件名顺序 ⇒ 改名等于换章序。

    这里把两轨故意做成**同尺寸、只有 mtime 不同**：于是「01 里装的是哪一轨」这件事
    除了*相对路径*没有别的字段能表达 —— 只有把路径纳入指纹才逮得到互换。
    （``rename`` 保 mtime，所以互换后 01/02 各自带着对方的 mtime，配对变了。）
    """
    src = _audio_dir(env["root"], "换章序")
    (src / "02 第二章.mp3").write_bytes((src / "01 第一章.mp3").read_bytes())
    os.utime(src / "01 第一章.mp3", ns=(1_600_000_001_000_000_000,) * 2)
    os.utime(src / "02 第二章.mp3", ns=(1_600_000_002_000_000_000,) * 2)
    _publish(env, "换章序")
    sig_before = publish.source_sig(src)

    (src / "01 第一章.mp3").rename(src / "tmp.mp3")
    (src / "02 第二章.mp3").rename(src / "01 第一章.mp3")
    (src / "tmp.mp3").rename(src / "02 第二章.mp3")

    assert publish.source_sig(src) != sig_before, "互换章序必须改变源指纹"
    r = scrape.enqueue(_book(env, "换章序"))
    assert r["queued"] is True and "已是最新" not in r["reason"], r


def test_指纹与链接共用同一份文件清单(env):
    """被跳过的噪声文件既不该进副本，也不该让指纹变 —— 两处各写一套就会在这里分叉。"""
    src = _audio_dir(env["root"], "带垃圾")
    (src / "Thumbs.db").write_bytes(b"junk")
    (src / "__MACOSX").mkdir()
    (src / "__MACOSX" / "x.mp3").write_bytes(b"junk")
    (src / ".DS_Store").write_bytes(b"junk")
    sig_before = publish.source_sig(src)

    row = _publish(env, "带垃圾")
    dst = env["pdir"] / row["link_rel"]
    names = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    assert names == ["01 第一章.mp3", "02 第二章.mp3"], names

    (src / "Thumbs.db").write_bytes(b"junk2")                   # 只动被跳过的文件
    assert publish.source_sig(src) == sig_before, "被跳过的文件不该让指纹变"


# ---------------------------------------------------------------------------
# ③ 命名：目录条目不带扩展名，且与入库侧同规则
# ---------------------------------------------------------------------------

def test_命名规则对目录条目不落扩展名(env):
    """目录名就是装音轨的容器：``.{ext}`` 摘掉，剩下的悬空点由 ``sanitize_stem`` 收掉。"""
    _audio_dir(env["root"], "书名")
    _rule(env, "{title}.{ext}")
    row = _publish(env, "书名")
    assert row["link_rel"] == "书名", row["link_rel"]
    # 断言用**目录列举**而不是 ``(pdir / "书名.").exists()``：Windows 会把路径末位的点
    # 静默吃掉，后者在「真留了尾巴」和「没有尾巴」两种情况下都为真，是假阳性。
    assert [p.name for p in env["pdir"].iterdir()] == ["书名"]

    # 带分隔符的模式同样不留尾巴（目录型条目没有作者元数据 → {author} 回落「未知」）
    _rule(env, "{author} - {title}.{ext}")
    assert scrape.republish(None, env["lid"])["done"] == 1
    after = db.scrape_get(row["book_id"])["link_rel"]
    assert after == "未知 - 书名", after
    assert (env["pdir"] / after).is_dir()


def test_scope不是all时不动有声书目录(env):
    """目录条目**没有扩展名可筛** ⇒ 只有 all 才算命中：scope=epub 不该顺带改有声书。"""
    _audio_dir(env["root"], "别动我")
    _rule(env, "{title}", scope="epub")

    row = _publish(env, "别动我")
    assert row["link_rel"] == "别动我", row["link_rel"]


def test_名字与磁盘形态不一致时跳过(env):
    """目录名自带扩展名 ⇒ 命名规则会把「.epub」当扩展名算 —— 宁可跳过也不产出错名。"""
    d = _audio_dir(env["root"], "伪装.epub")
    book = _book(env, "伪装.epub")
    assert d.is_dir()

    assert scrape.enqueue(book)["queued"] is True
    assert scrape.run_once()["processed"] == 1
    row = db.scrape_get(book["id"])
    assert row["status"] == "skipped" and "名字与磁盘形态" in row["error"], row
    assert not list(env["pdir"].glob("*")), "没出版就不该在成品目录里留下任何东西"


# ---------------------------------------------------------------------------
# ④ 既有不变量一条不松
# ---------------------------------------------------------------------------

def test_重出版把旧副本目录移入回收不留双份(env):
    _audio_dir(env["root"], "旧名")
    _rule(env, "{title}")
    row = _publish(env, "旧名")
    old_rel = row["link_rel"]

    _rule(env, "{author} —— {title}")
    assert scrape.republish(None, env["lid"])["done"] == 1

    new_rel = db.scrape_get(row["book_id"])["link_rel"]
    assert new_rel != old_rel
    assert not (env["pdir"] / old_rel).exists(), "旧目录不留（回收，不是删除）"
    assert (env["pdir"] / new_rel).is_dir()
    recycled = [p.name for p in fileops.recycle_dir().iterdir()]
    assert any(pathlib.PurePosixPath(old_rel).name in n for n in recycled), recycled


def test_落点被别人的目录占用时预览标冲突且不覆盖(env):
    _audio_dir(env["root"], "占用")
    _rule(env, "{author} - {title}")
    row = _publish(env, "占用")

    _rule(env, "{title}")
    new_rel = next(it["new_rel"] for it in scrape.plan_naming(env["lid"])["items"]
                   if it["book_id"] == row["book_id"])

    # 成品目录是给人看的普通目录：用户完全可能在里面放同名目录
    foreign = env["pdir"] / new_rel
    foreign.mkdir(parents=True)
    (foreign / "用户的文件.txt").write_text("别动我", encoding="utf-8")

    plan = scrape.plan_naming(env["lid"])
    item = next(it for it in plan["items"] if it["book_id"] == row["book_id"])
    assert item["conflict"] == "occupied"
    assert plan["stats"]["ready"] == 0

    res = scrape.republish(None, env["lid"])
    assert res["total"] == 0 and res["skipped"] == 1, res
    assert (foreign / "用户的文件.txt").read_text(encoding="utf-8") == "别动我"
    assert not list(env["pdir"].glob("* (2)*"))


def test_有声书重出版不外呼(env, monkeypatch):
    """把在线抓取**打开**并让 auto_fetch 直接炸 —— 重出版仍须成功。"""
    _audio_dir(env["root"], "离线")
    _publish(env, "离线")
    lib_settings.set_overrides(env["lid"], {"metadata_fetch.enabled": True})
    _rule(env, "{author} · {title}")

    def _boom(*a, **k):                               # noqa: ANN002, ANN003
        raise AssertionError("重出版不该外呼在线元数据抓取")

    monkeypatch.setattr(metafetch, "auto_fetch", _boom)
    res = scrape.republish(None, env["lid"])
    assert res["done"] == 1 and res["failed"] == 0, res


# ---------------------------------------------------------------------------
# ⑤ 源被回收 → 副本目录是孤本；确认清理走回收不 unlink
# ---------------------------------------------------------------------------

def test_副本目录也能走回收而不是unlink(env):
    _audio_dir(env["root"], "待清理")
    row = _publish(env, "待清理")
    dst = env["pdir"] / row["link_rel"]

    res = scrape.resolve(row["book_id"], "recycle_copy")

    assert res["ok"] is True
    assert not dst.exists(), "副本目录必须被**移走**"
    recycled = fileops.recycle_dir() / pathlib.PurePosixPath(res["recycled"]).name
    assert recycled.is_dir() and (recycled / "01 第一章.mp3").is_file(), "内容整树保留在回收站"


def test_入库与出版对同一目录算出同一个落点(env, tmp_path):
    """端到端一致性：``pipeline.dispatch`` 的入库落点 == ``publish.relpath_for`` 的出版落点。"""
    stage = tmp_path / "stage" / "某有声书"
    stage.mkdir(parents=True)
    (stage / "01.mp3").write_bytes(b"ID3" + b"a" * 8)

    out = tmp_path / "out"
    kind, landed = pipeline.dispatch(stage, out, {"cfg": {}, "meta": {}})
    assert kind == "copy" and landed.is_dir()
    ingested_rel = landed.relative_to(out).as_posix()

    book = {"name": landed.name, "title": landed.name, "author": "作者",
            "series": "", "series_index": ""}
    assert publish.relpath_for(book, {}) == ingested_rel
    assert publish.relpath_for(book, {"output": {"layout": "komga"}}) \
        == komga.relpath_for_dir(landed.name, "", "", "komga")
