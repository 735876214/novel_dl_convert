"""入库归库规则（`core/library_rules.py`）。

判决优先级是**契约**（第 10 期确认）：来源子目录名 > 格式 > 元数据关键词 > **拒收**。
（第 37 期改口：末档从「回退默认库」改成「拒收」，因为没有默认库了。）
这里逐条钉住它 —— 顺序一变，用户的书就会悄无声息地落进别的库。

⚠️ 第 40 期给三条规则加了一道**共同的前置闸门**（`library_rules._accepts`）：
库的生效扫描白名单收不了的格式，**不算它的候选**，哪怕来源子目录显式命中。
它不改变上面那串优先级，只是把「收了也看不见」的库从候选里去掉。
本例里两条被改写的用例（`来源子目录名优先于格式推断` / `关键词在格式无法判定时生效`）
都写明了为什么换载体 —— 原载体恰好就是这道闸门要拦的隐形文件。
"""
import pathlib

import pytest

from novelforge import config
from novelforge.core import db, library, library_rules


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


def test_库名优先于格式推断(isolated, tmp_path, make_library):  # noqa: ARG001
    """放在与库同名的子目录下的 .epub 进漫画库 —— 显式摆放意图（库名）高于格式推断。

    第 41 期起「来源子目录名」概念移除，改为按**库名**匹配：文件所在子目录名等于某库的
    库名即命中该库，优先级高于按扩展名推断类型。
    """
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    make_library("ebook", "电子书库", "ebook", src / "ebooks")
    make_library("comic", "漫画库", "comic", src / "漫画库",
                 allowed_exts='[".cbz", ".cbr", ".epub"]')
    # .epub 按格式应进电子书库；但放进名为「漫画库」的子目录（与库名相同，且是该库来源
    # 目录的第一层）→ 按库名命中漫画库，显式摆放意图高于格式推断。
    (src / "漫画库").mkdir(parents=True, exist_ok=True)
    hit = library_rules.decide(src=src / "漫画库" / "随便什么.epub")
    assert hit is not None
    assert hit["id"] == "comic"


def test_子目录命中也拦不住格式不匹配(typed_libraries):
    """第 40 期前置闸门：**收不了的库不算候选**，哪怕用户显式放在了它的来源目录里。

    显式意图能让系统「不猜」，但不能让系统「装作收下了」—— `.epub` 进漫画库
    只会落盘、永远不进书目。⚠️ 结果不是拒收而是**改判到电子书库**：
    闸门只排除「收不了的库」，剩下候选之间的优先级一点没动（这是有意的 ——
    书至少还能出现在界面上，用户看得见才好纠正）。
    """
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    hit = library_rules.decide(src=src / "comics" / "随便什么.epub")
    assert hit is not None
    assert hit["id"] == "ebook"


def test_decide_for_path与decide同源(typed_libraries):
    """`watcher.target_root` 走的入口必须与 `decide` 结论一致（两套逻辑必然写歪）。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    p = src / "audiobooks" / "某书.m4b"
    assert library_rules.decide_for_path(p, None)["id"] == "audiobook"


# ---------------------------------------------------------------------------
# 边界与异常
# ---------------------------------------------------------------------------

def test_都不命中时拒收而不是猜一个库(typed_libraries):
    """第 37 期：没有默认库可退，规则不命中 ⇒ `target_root` 返回 None，调用方拒收。

    以前这里会回退「默认库 = OUTPUT_DIR」。现在宁可拒收 + 报清楚原因，
    也不把文件塞进一个用户没指定的库 —— 猜错的代价是书进了没人管的目录。
    """
    assert library_rules.decide(name="未知文件.xyz") is None
    assert library_rules.target_root(name="未知文件.xyz") is None
    d = library_rules.resolve_target(name="未知文件.xyz")
    assert d["library"] is None and d["library_id"] == "" and d["root"] is None
    assert "没有可接收这个文件的书库" in library_rules.no_library_reason()


def test_一个库都没有时的原因文案不一样(isolated, default_root):  # noqa: ARG001
    """「一个库都没建」和「有库但规则不命中」要分开说 —— 否则用户不知道去改哪儿。"""
    libs = library.libraries()
    assert libs, "前置：夹具会建一条本用例的库"
    assert "没有可接收这个文件的书库" in library_rules.no_library_reason()
    for l in libs:                       # 真删干净，模拟全新部署的 0 库状态
        db.delete_library(l["id"])
    library.invalidate()
    assert library.libraries() == []
    assert "还没有书库" in library_rules.no_library_reason()


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
    """格式优先于关键词：只有「格式给不出结论」时才轮到关键词（避免规则抢走 .cbz）。

    ⚠️ **第 40 期换了载体**：原来用 `未知文件.xyz`，但 `.xyz` 不在任何库的扫描白名单里，
    现在会被前置闸门拦下 —— 那正是副作用本来就该拦的隐形文件，于是它再也测不出
    「关键词生效」这件事。改用 `.txt`：**收得了**，而格式推断只给得出 `mixed` 库
    （`decide` 的类型专用库判断不成立）⇒ 照样轮到关键词。用例意图一字未变。
    """
    make_library("scifi", "科幻专区", "mixed", tmp_path / "libraries" / "scifi", rules="科幻、太空")
    hit = library_rules.decide(name="未知文件.txt", meta={"title": "基地", "tags": ["科幻"]})
    assert hit is not None and hit["id"] == "scifi"
    # 反例：同一本书但格式明确 → 绝不走关键词
    make_library("comic", "漫画库", "comic", tmp_path / "libraries" / "comics",
                 source_subdir="comics")
    assert library_rules.decide(name="基地.cbz", meta={"tags": ["科幻"]})["id"] == "comic"


def test_没有库收得了的格式一律拒收不隐形(isolated, tmp_path, make_library):  # noqa: ARG001
    """第 40 期前置闸门：**没有任何库的「允许的格式」含它** ⇒ 拒收，而不是收下后隐形。

    这条是副作用的正身：关键词明明命中，但 `.xyz` 谁的扫描白名单都进不去 ——
    收下来只会落盘、永远不进书目。宁可拒收（用户看得见失败）也不要无声消失。
    """
    make_library("scifi", "科幻专区", "mixed", tmp_path / "libraries" / "scifi",
                 rules="科幻、太空")
    assert library_rules.decide(name="未知文件.xyz", meta={"tags": ["科幻"]}) is None
    # 同一个库、同一条关键词规则，收得了的格式照常进
    assert library_rules.decide(name="未知文件.txt", meta={"tags": ["科幻"]})["id"] == "scifi"
    # 文案要说对成因：这里不是「规则不命中」，是「没有库收得了这个格式」
    assert "允许的格式" in library_rules.no_library_reason(name="未知文件.xyz")


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
