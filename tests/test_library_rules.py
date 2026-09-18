"""入库归库规则（`core/library_rules.py`）。

判决优先级是**契约**（第 10 期确认）：来源子目录名 > 格式 > 元数据关键词 > 回退默认库。
这里逐条钉住它 —— 顺序一变，用户的书就会悄无声息地落进别的库。
"""
import pathlib

import pytest

from novelforge import config
from novelforge.core import library, library_rules


@pytest.fixture
def typed_libraries(isolated, tmp_path, make_library):  # noqa: ARG001 —— isolated 负责切目录
    """三个类型库，就地引用 `LIBRARY_SOURCE_DIR` 下的子目录（与向导的默认方案一致）。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    return {
        "ebook": make_library("ebook", "电子书库", "ebook", src / "ebooks", source_subdir="ebooks"),
        "comic": make_library("comic", "漫画库", "comic", src / "comics", source_subdir="comics"),
        "audiobook": make_library("audiobook", "有声书库", "audiobook",
                                  src / "audiobooks", source_subdir="audiobooks"),
    }


# ---------------------------------------------------------------------------
# 正常路径
# ---------------------------------------------------------------------------

def test_格式决定目标库(typed_libraries):
    # Act & Assert：三种媒体各归各库
    assert library_rules.decide(name="三体.epub")["id"] == "ebook"
    assert library_rules.decide(name="测试漫画 01.cbz")["id"] == "comic"
    assert library_rules.decide(name="测试漫画 02.cbr")["id"] == "comic"
    assert library_rules.decide(name="活着.m4b")["id"] == "audiobook"
    assert library_rules.decide(name="活着.mp3")["id"] == "audiobook"


def test_target_root落在命中的库根(typed_libraries):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    assert library_rules.target_root(name="三体.epub") == src / "ebooks"
    assert library_rules.target_root(name="测试漫画.cbz") == src / "comics"


def test_来源子目录名优先于格式推断(typed_libraries):
    """放在 `comics/` 下的 .epub 仍然进漫画库 —— 用户的显式摆放意图高于格式推断。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    hit = library_rules.decide(src=src / "comics" / "随便什么.epub")
    assert hit is not None
    assert hit["id"] == "comic"


def test_decide_for_path与decide同源(typed_libraries):
    """`watcher.target_root` 走的入口必须与 `decide` 结论一致（两套逻辑必然写歪）。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    p = src / "audiobooks" / "某书.m4b"
    assert library_rules.decide_for_path(p, None)["id"] == "audiobook"


# ---------------------------------------------------------------------------
# 边界与异常
# ---------------------------------------------------------------------------

def test_都不命中时回退默认库(typed_libraries, default_root):
    # 未知格式 + 无关键词 → 不给结论，由调用方回退默认库（宁可落默认库也不乱归）
    assert library_rules.decide(name="未知文件.xyz") is None
    assert library_rules.target_root(name="未知文件.xyz") == default_root


def test_未知扩展名不产生格式结论(typed_libraries):
    assert library_rules._type_of_name("x.xyz") == ""
    assert library_rules._type_of_name("") == ""


def test_缺文件的扩展名判定(typed_libraries):
    # 边界：没有扩展名 / 只有点 / 大写扩展名
    assert library_rules._type_of_name("无扩展名") == ""
    assert library_rules._type_of_name("怪文件.") == ""
    assert library_rules._type_of_name("大写.EPUB") == "ebook"


def test_坏JSON规则不抛且退化为无规则(isolated, tmp_path, make_library):  # noqa: ARG001
    """`rules` 是给人填的字段：写坏了只该「没有规则」，不该把入库流程打崩。"""
    make_library("bad", "坏配置库", "mixed", tmp_path / "libraries" / "bad", rules="{这不是 JSON")
    row = library.get_library("bad")
    assert library_rules.rules_of(row) == {"keywords": [], "subdirs": []}
    assert library_rules.decide(name="未知文件.xyz") is None


def test_关键词规则支持纯文本与JSON两种写法(isolated, tmp_path, make_library):  # noqa: ARG001
    root = tmp_path / "libraries"
    make_library("plain", "纯文本库", "mixed", root / "plain", rules="科幻、太空, 硬核")
    make_library("js", "JSON库", "mixed", root / "js",
                 rules='{"keywords": ["某本书"], "subdirs": ["js"]}')
    assert library_rules.rules_of(library.get_library("plain"))["keywords"] == ["科幻", "太空", "硬核"]
    js = library_rules.rules_of(library.get_library("js"))
    assert js["keywords"] == ["某本书"]
    assert js["subdirs"] == ["js"]


def test_关键词在格式无法判定时生效(isolated, tmp_path, make_library):  # noqa: ARG001
    """格式优先于关键词：只有「格式给不出结论」时才轮到关键词（避免规则抢走 .cbz）。"""
    make_library("scifi", "科幻专区", "mixed", tmp_path / "libraries" / "scifi", rules="科幻、太空")
    hit = library_rules.decide(name="未知文件.xyz", meta={"title": "基地", "tags": ["科幻"]})
    assert hit is not None and hit["id"] == "scifi"
    # 反例：同一本书但格式明确 → 绝不走关键词
    make_library("comic", "漫画库", "comic", tmp_path / "libraries" / "comics",
                 source_subdir="comics")
    assert library_rules.decide(name="基地.cbz", meta={"tags": ["科幻"]})["id"] == "comic"


def test_同类多个库时取排序靠前的(isolated, tmp_path, make_library):  # noqa: ARG001
    """同类多库不报错也不静默丢弃：按 sort_order 取第一个（迁移预览会另行提示需指定目标）。"""
    make_library("ebook-a", "电子书库 A", "ebook", tmp_path / "libraries" / "a")
    make_library("ebook-b", "电子书库 B", "ebook", tmp_path / "libraries" / "b")
    hit = library_rules.decide(name="三体.epub")
    assert hit["id"] in ("ebook-a", "ebook-b")


def test_库名也能作为来源子目录名匹配(isolated, tmp_path, make_library):  # noqa: ARG001
    """宽容匹配：用户把目录命名成库名（而非 source_subdir）时也应认得。"""
    make_library("comic", "漫画库", "comic", tmp_path / "libraries" / "comics")
    assert library_rules._by_subdir("漫画库")["id"] == "comic"
