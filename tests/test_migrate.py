"""按格式迁移与回滚（`core/migrate.py`）。

断言语义取自第 10 期人工冒烟的实测基线（只是把 25 本缩到 5 本）：
**迁移会不会搬错、会不会重复搬、能不能回滚、冲突会不会被覆盖** —— 这四件事
只要有一件错了就是用户数据事故，所以逐条钉住。
"""
import pathlib

import pytest

from novelforge import config
from novelforge.core import db, library, migrate


@pytest.fixture
def default_with_books(isolated, default_root, make_book, make_audio_dir):  # noqa: ARG001
    """默认库里铺三种媒体（含一个**有声书目录**，它也是一个迁移条目）。"""
    make_book(default_root, "三体.epub")
    make_book(default_root, "流浪地球.epub")
    make_book(default_root, "测试漫画 01.cbz")
    make_book(default_root, "测试漫画 02.cbr")
    make_audio_dir(default_root, "活着", tracks=2)
    library.invalidate()
    return default_root


@pytest.fixture
def typed_libraries(make_library):  # make_library 已强制依赖 isolated
    """三个类型库（就地引用 `LIBRARY_SOURCE_DIR` 下的子目录）。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    return {
        "ebook": make_library("ebook", "电子书库", "ebook", src / "ebooks", source_subdir="ebooks"),
        "comic": make_library("comic", "漫画库", "comic", src / "comics", source_subdir="comics"),
        "audiobook": make_library("audiobook", "有声书库", "audiobook",
                                  src / "audiobooks", source_subdir="audiobooks"),
    }


# ---------------------------------------------------------------------------
# 预览
# ---------------------------------------------------------------------------

def test_建库前预览标记缺目标库(default_with_books):
    pv = migrate.preview()
    assert pv["total"] == 5
    assert pv["ready"] == 0
    assert pv["no_library"] == 5
    assert pv["missing_types"] == ["audiobook", "comic", "ebook"]
    # 一本都搬不动时不谈「确认」——否则会弹一个无事可做的阻塞框
    assert pv["needs_confirm"] is False


def test_建库后预览可迁移且按类型归类(default_with_books, typed_libraries):
    pv = migrate.preview()
    assert pv["total"] == 5 and pv["ready"] == 5
    assert pv["missing_types"] == []
    assert pv["needs_confirm"] is True
    assert sorted(i["target_type"] for i in pv["items"]) == \
        ["audiobook", "comic", "comic", "ebook", "ebook"]


def test_预览条目带绝对源与目标路径(default_with_books, typed_libraries):
    item = next(i for i in migrate.preview()["items"] if i["name"] == "三体.epub")
    assert item["src"] == str(pathlib.Path(default_with_books) / "三体.epub")
    assert item["dst"] == str(pathlib.Path(config.LIBRARY_SOURCE_DIR) / "ebooks" / "三体.epub")


def test_无待迁移时预览为空(default_with_books, typed_libraries):
    migrate.execute(migrate.plan()["batch_id"])
    pv = migrate.preview()
    assert pv["total"] == 0
    assert pv["needs_confirm"] is False


def test_向导建议只为缺失类型给出(typed_libraries, default_with_books):
    # 三个类型库都建好了 → 没有建议
    assert migrate.preview()["suggest_specs"] == []


def test_向导建议只为缺失类型给出就地引用来源(default_with_books):
    """第 41 期：建议只给「缺失类型」库，且内容来源是就地引用的绝对路径（多文件夹）。

    不再有「独立存储（import）」方案 —— 只有一个就地引用方案，来源根下的同名子目录。
    """
    specs = migrate.preview()["suggest_specs"]
    assert [s["type"] for s in specs] == ["ebook", "comic", "audiobook"]
    for s in specs:
        assert s["source_dirs"], "就地引用：建议必须有内容来源文件夹"
        assert isinstance(s["source_dirs"], list)
        for d in s["source_dirs"]:
            dp = pathlib.Path(d)
            assert dp.is_absolute(), "就地引用：来源必须是绝对路径"
            assert dp.is_relative_to(pathlib.Path(config.LIBRARY_SOURCE_DIR)), \
                "就地引用：来源必须落在已配置来源根内"


# ---------------------------------------------------------------------------
# 同名冲突：拒绝覆盖 + 建议名（只建议、不自动改）
# ---------------------------------------------------------------------------

def test_同名冲突被拒绝并给出建议名(default_with_books, typed_libraries, make_book):
    make_book(pathlib.Path(config.LIBRARY_SOURCE_DIR) / "comics", "测试漫画 01.cbz", b"occupied")
    pv = migrate.preview()
    item = next(i for i in pv["items"] if i["name"] == "测试漫画 01.cbz")
    assert item["status"] == "conflict"
    assert item["suggest"] == "测试漫画 01 (2).cbz"
    assert pv["conflict"] == 1
    assert pv["ready"] == 4


def test_建议名遇到占用会继续递增(default_with_books, typed_libraries, make_book):
    root = pathlib.Path(config.LIBRARY_SOURCE_DIR) / "comics"
    make_book(root, "测试漫画 01.cbz")
    make_book(root, "测试漫画 01 (2).cbz")
    item = next(i for i in migrate.preview()["items"] if i["name"] == "测试漫画 01.cbz")
    assert item["suggest"] == "测试漫画 01 (3).cbz"


def test_冲突条目不进入计划(default_with_books, typed_libraries, make_book):
    make_book(pathlib.Path(config.LIBRARY_SOURCE_DIR) / "comics", "测试漫画 01.cbz", b"occupied")
    planned = migrate.plan()
    assert len(planned["items"]) == 4
    assert all(i["name"] != "测试漫画 01.cbz" for i in planned["items"])


# ---------------------------------------------------------------------------
# 计划：确定性幂等
# ---------------------------------------------------------------------------

def test_计划幂等_同集合复用同批次(default_with_books, typed_libraries):
    first = migrate.plan()
    second = migrate.plan()
    assert first["batch_id"] and first["batch_id"] == second["batch_id"]
    assert first["reused"] is False
    assert second["reused"] is True


def test_没有可迁移条目时计划为空(default_with_books, typed_libraries):
    migrate.execute(migrate.plan()["batch_id"])
    planned = migrate.plan()
    assert planned["batch_id"] == ""
    assert planned["items"] == []
    assert planned["message"] == "没有需要迁移的书"


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------

def test_执行迁移把书搬进对应库(default_with_books, typed_libraries):
    res = migrate.execute(migrate.plan()["batch_id"])
    assert res["ok"] is True and res["moved"] == 5 and res["failed"] == 0

    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    assert (src / "ebooks" / "三体.epub").is_file()
    assert (src / "comics" / "测试漫画 01.cbz").is_file()
    assert (src / "comics" / "测试漫画 02.cbr").is_file()
    assert (src / "audiobooks" / "活着").is_dir()      # 目录形态（有声书）照样能搬

    assert list(pathlib.Path(default_with_books).iterdir()) == []
    counts: dict = {}
    for b in library.books():
        counts[b["library_id"]] = counts.get(b["library_id"], 0) + 1
    assert counts == {"ebook": 2, "comic": 2, "audiobook": 1}


def test_搬库后关联数据随库维度id迁移(default_with_books, typed_libraries):
    """库维度 id：搬库后 id 的库前缀会变，但 migrate 会把进度/批注一起 remap，不断链。"""
    before = {b["name"]: b["id"] for b in library.books()}
    # 在旧 id（default$哈希）上写一条进度，验证搬库后跟到新 id
    some_old_id = next(iter(before.values()))
    db.set_progress(some_old_id, 5, 20.0)

    migrate.execute(migrate.plan()["batch_id"])
    after = {b["name"]: b["id"] for b in library.books()}

    # 文件名不变，但库前缀从 default 换成类型库 → id 变了
    assert before != after
    # 进度跟着新 id 走（remap 后的新 id 上能查到）
    assert any(
        db.get_progress(nid) and db.get_progress(nid)["locator"] == 5
        for nid in after.values()
    )
    # 旧 id 上不残留
    assert db.get_progress(some_old_id) is None


def test_逐条独立_单条失败不影响其余(default_with_books, typed_libraries):
    planned = migrate.plan()
    (pathlib.Path(default_with_books) / "三体.epub").unlink()   # 计划之后源文件消失

    res = migrate.execute(planned["batch_id"])
    assert res["ok"] is False
    assert res["moved"] == 4 and res["failed"] == 1
    assert any("源文件已不存在" in e["error"] for e in res["errors"])


def test_重复执行不重复搬(default_with_books, typed_libraries):
    planned = migrate.plan()
    migrate.execute(planned["batch_id"])
    again = migrate.execute(planned["batch_id"])
    assert again["moved"] == 0
    assert again["skipped"] == 5


# ---------------------------------------------------------------------------
# 回滚
# ---------------------------------------------------------------------------

def test_回滚把文件移回原位(default_with_books, typed_libraries):
    planned = migrate.plan()
    migrate.execute(planned["batch_id"])

    rb = migrate.rollback(planned["batch_id"])
    assert rb["ok"] is True and rb["restored"] == 5

    assert (pathlib.Path(default_with_books) / "三体.epub").is_file()
    assert (pathlib.Path(default_with_books) / "活着").is_dir()
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    assert list((src / "ebooks").iterdir()) == []
    assert {r["status"] for r in db.migration_batch(planned["batch_id"])} == {"rolled_back"}


def test_回滚后再次预览可重新迁移(default_with_books, typed_libraries):
    planned = migrate.plan()
    migrate.execute(planned["batch_id"])
    migrate.rollback(planned["batch_id"])
    assert migrate.preview()["ready"] == 5


# ---------------------------------------------------------------------------
# 门禁与异常
# ---------------------------------------------------------------------------

def test_门禁_暂不迁移与复位(default_with_books, typed_libraries):
    assert migrate.preview()["needs_confirm"] is True
    assert migrate.dismiss("测试：暂不迁移")["dismissed"] is True
    assert migrate.preview()["needs_confirm"] is False
    assert migrate.reset_gate()["dismissed"] is False
    assert migrate.preview()["needs_confirm"] is True


def test_不存在的批次要报错而不是静默(default_with_books):
    with pytest.raises(ValueError):
        migrate.execute("不存在的批次")
    with pytest.raises(ValueError):
        migrate.rollback("不存在的批次")


def test_台账可见(default_with_books, typed_libraries):
    planned = migrate.plan()
    migrate.execute(planned["batch_id"])
    batches = migrate.pending_batches()
    assert len(batches) == 1
    assert batches[0]["batch_id"] == planned["batch_id"]
    assert batches[0]["done"] == 5
    assert batches[0]["failed"] == 0


def test_回滚要把关联数据也搬回来(default_with_books, typed_libraries):
    """回滚若只把文件移回原位、**不把关联数据搬回**，用户的进度 / 批注会留在新 id 上 ——
    文件回到了原处，书却「干干净净」，与 T1 修的那类静默断链是同一个病。"""
    before = {b["name"]: b["id"] for b in library.books()}
    old_id = next(iter(before.values()))
    db.set_progress(old_id, 5, 20.0)
    db.set_override(old_id, "title", "用户改过的书名")

    planned = migrate.plan()
    migrate.execute(planned["batch_id"])
    migrate.rollback(planned["batch_id"])

    assert db.get_progress(old_id) is not None, "回滚后进度要回到原位对应的 id 上"
    assert db.get_progress(old_id)["locator"] == 5
    assert db.get_overrides(old_id)["title"] == "用户改过的书名"
    after = {b["name"]: b["id"] for b in library.books()}
    assert after == before
    for nid in set(after.values()) - {old_id}:
        assert db.get_progress(nid) is None, "新 id 上不残留（否则是走不到的孤儿行）"
