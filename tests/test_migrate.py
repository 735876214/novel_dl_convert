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


def test_向导建议的两种存放方案(default_with_books):
    specs = migrate.preview()["suggest_specs"]
    assert [s["type"] for s in specs] == ["ebook", "comic", "audiobook"]
    for s in specs:
        assert s["inplace"]["root_path"] == str(pathlib.Path(config.LIBRARY_SOURCE_DIR)
                                                / s["source_subdir"])
        # 独立存储必须落在 DATA_DIR 之内（库根白名单的另一半）
        assert s["import"]["root_path"].startswith(str(config.DATA_DIR))


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


def test_只挪库不改名_保持book_id(default_with_books, typed_libraries):
    """`book_id` 由 basename 派生：名字不变 → id 不变 → 进度/批注/评分不断链。"""
    before = {b["name"]: b["id"] for b in library.books()}
    migrate.execute(migrate.plan()["batch_id"])
    after = {b["name"]: b["id"] for b in library.books()}
    assert before == after


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
