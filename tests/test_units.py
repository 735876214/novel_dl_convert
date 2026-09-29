"""序号单元判据（第 73 期）：``units`` 的解析表、形态判据与指纹。

这个文件只测**判据本体**（`novelforge/core/units.py`），不碰 DB / 不碰扫描链路 ——
链路侧的对拍在 ``tests/test_units_scan.py``（枚举 / 探测 / 索引 / 搬家）。分开的理由：
判据是「什么算一话」的**唯一真值源**（枚举、探测、指纹、搬家闸门、服务端全读它），
它值得一组不依赖环境的表驱动用例；而这些用例一旦混进夹具，失败时看不出究竟是
解析判错还是链路接错。

用例里的树都按**用户实况**造：`《转生魔女宣告毁灭（1-43话）》/第1卷/第1话.pdf`，
序号写法故意不统一（`第1话` / `第二话` / `第03话` / `4 第4话`）。
"""
import pathlib

from novelforge.core import units


def _tree(root: pathlib.Path, rel: str, names) -> pathlib.Path:
    """在 ``root/rel`` 下造一棵树（``names`` 里带 ``/`` 的自动建子目录）。"""
    d = pathlib.Path(root) / rel
    d.mkdir(parents=True, exist_ok=True)
    for name in names:
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4 fake")
    return d


# ---------------------------------------------------------------------------
# ① 序号解析：唯一的解析点
# ---------------------------------------------------------------------------

#: ``(文件名 stem, 期望序号)``。**每条反例都对应一种真实存在的文件名** ——
#: 反例比正例重要：错合并（把几本独立的书粘成一本）只能靠改目录名来救。
PARSE_CASES = [
    # 正例：标记在开头，单位词在
    ("第1话", 1), ("第01话", 1), ("第十二话", 12), ("第二话", 2), ("第03卷", 3),
    ("第1話", 1), ("第100话", 100), ("第二章", 2),
    # 正例：标记之后还有内容（`第1话 番外` / `第01话 某标题` 都很常见）
    ("第1话 番外", 1), ("第1话 某标题", 1),
    # 正例：前缀序号 `4 第4话` / 裸数字 `01`
    ("4 第4话", 4), ("04-第4話", 4), ("01", 1), ("007", 7),
    # 正例：**前缀 + 尾部编号**（第 79 期，用户实况 `超人前传0904.pdf`）
    ("超人前传0904", 904), ("超人前传1408", 1408), ("作品名1408", 1408),
    ("超人前传1", 1), ("ULTRAMAN0904", 904),
    # 反例：尾部编号的四种边界（第 79 期）
    ("A01", None),               # 前缀只有 1 个字符（见 `_MIN_PREFIX`）
    ("1408", None),              # 纯数字且超 `_MAX_UNIT`：**不许**拆成 pre="1" + num="408"
    ("超人前传12345", None),     # 尾部编号超过 4 位
    ("超人前传-0904", None),     # 编号没**紧贴**标题文字（连字符）
    ("超人前传_0904", None),     # 同上（下划线）
    ("超人前传 0904", None),     # 同上（空白）
    # 反例：中文数字不能用「按位读」的方式算（一〇一 = 101，但口语里没人这么编号）
    ("一〇一", None),
    # 反例：范围备注（这正是书名里要剥掉的那种）
    ("第1-43话", None), ("《转生魔女宣告毁灭（1-43话）》", None),
    # 反例：标记不在开头（`《甲》(第1卷).cbz` 是一本独立的漫画，不是「第 1 话」）
    ("《甲》(第1卷)", None), ("作品名 第1话", None),
    # 反例：前缀不是纯数字
    ("4x 第4话", None),
    # 反例：序号上界（年份 / 日期不能被当成话号）
    ("2024", None), ("第1000话", None), ("第0话", None),
    # 反例：根本不是序号
    ("vol.1", None), ("封面", None), ("序章", None), ("", None),
]


def test_序号解析表():
    """``parse_unit`` 一张表定死：正例要认得出，反例一个都不许认。"""
    bad = [f"parse_unit({stem!r}) = {units.parse_unit(stem)!r}，期望 {want!r}"
           for stem, want in PARSE_CASES if units.parse_unit(stem) != want]
    assert not bad, "序号解析与判据不符：\n" + "\n".join(bad)


def test_前缀序号必须与自己的号码一致():
    """`4 第4话` 是「第 4 话」的另一种写法；`5 第4话` 不是 —— 前缀与标记矛盾时**不猜**。

    这条钉的是「宁可解析不出」：矛盾的文件名多半来自复制粘贴 / 手工改名，
    按哪一边算都是猜，而猜错会让话序错位（`4 第4话` 排到第 5 位）。
    """
    assert units.parse_unit("4 第4话") == 4
    assert units.parse_unit("5 第4话") is None
    # 反过来不算：`第4话 4` 的标记在开头 ⇒ **是**第 4 话（标记之后的尾巴随便写，
    # `第1话 番外` / `第01话 某标题` 都是常见写法）。这里钉住「要求前缀与号码一致」
    # 只针对**前缀序号**那种写法，不是给所有文件名加要求。
    assert units.parse_unit("第4话 4") == 4


def test_中文数字():
    """`cn_to_int`：位值写法、大写数字、廿卅，以及解析不出时的 ``None``。"""
    assert units.cn_to_int("十二") == 12
    assert units.cn_to_int("二十三") == 23
    assert units.cn_to_int("一百零三") == 103
    assert units.cn_to_int("廿五") == 25
    assert units.cn_to_int("肆拾贰") == 42
    assert units.cn_to_int("99") == 99
    assert units.cn_to_int("") is None and units.cn_to_int("abc") is None


# ---------------------------------------------------------------------------
# ①b 前缀 + 尾部编号（第 79 期）：解析点收敛 + 两个上界 + 前缀语义
# ---------------------------------------------------------------------------

def test_前缀语义_只有尾部编号形态给得出前缀():
    """`_split_unit` 是**唯一**的解析点：既有三形态回空串，第四形态才给非空前缀。

    前缀只服务于 `is_unit_dir` 的「同前缀」闸。若给既有形态也硬编一个前缀出来
    （比如把 `4 第4话` 的 `4` 当作作品名），同一棵树里的 `4 第4话` 与 `第4话` 就会被
    判成两种前缀、反而**不再合并** —— 那是把「支持一种新写法」做成了回归。
    """
    assert units._split_unit("第1话") == ("", 1)
    assert units._split_unit("4 第4话") == ("", 4)
    assert units._split_unit("01") == ("", 1)
    assert units._split_unit("超人前传0904") == ("超人前传", 904)
    assert units._split_unit("A01") is None
    # 公开契约不变：`parse_unit` 只要序号
    assert units.parse_unit("超人前传0904") == 904
    assert units.parse_unit("A01") is None


def test_尾部编号与纯数字是两套上界():
    """`1408` 能当尾号、`2024` 不能当裸号 —— 两个上界**刻意分开**（第 79 期）。

    ⚠️ 这条钉的是「不得抬高 `_MAX_UNIT`」：把**纯数字**上界抬到 9999 之后
    `2024.pdf`（年份）会被认成「第 2024 话」，而那是明确的回归。
    """
    assert units._MAX_UNIT == 999, "纯数字上界不许动（`2024.pdf` 会变成「第 2024 话」）"
    assert units._MAX_TAIL_UNIT == 9999
    assert units.parse_unit("2024") is None
    assert units.parse_unit("超人前传9999") == 9999
    assert units.parse_unit("超人前传10000") is None      # 5 位 ⇒ 尾号形态也不收


def test_尾部编号必须紧贴标题文字():
    """`vol.1` 不能变成「第 1 话」—— 现有契约表里它是 `None`（一本漫画的第 1 卷）。

    编号与标题之间夹分隔符（`.` `-` `_` 空白）时一律不收：那种命名更常见于
    「系列的第 N 卷 / 第 N 批」，认成连载会把几本独立的书粘成一本。
    """
    for stem in ("vol.1", "vol-1", "作品名-1408", "作品名_1408", "作品名 1408"):
        assert units.parse_unit(stem) is None, f"{stem!r} 不该被认成话号"


def test_同前缀文件夹合并_两种前缀不合并(tmp_path):
    """尾部编号形态的「同前缀」闸：**同一部作品**的连载才合并。

    `超人前传0904.pdf` + `超人前传1408.pdf` 是一部；换成两个不同的作品名就是两本 ——
    只看文件名的话两者都「解析得出序号」，判据必须落在前缀一致性上。
    """
    same = _tree(tmp_path, "同一部", ["超人前传0904.pdf", "超人前传1408.pdf"])
    assert units.is_unit_dir(same) is True
    assert [it["num"] for it in units.units(same)] == [904, 1408]

    mixed = _tree(tmp_path, "两部", ["超人前传0904.pdf", "另一部作品0905.pdf"])
    assert units.is_unit_dir(mixed) is False, "两种前缀 ⇒ 不合并（宁可少合并）"


def test_一字符前缀与同号不合并(tmp_path):
    """前缀闸的两条边：前缀太短是噪声；序号全相同是两本书各自的第一话。"""
    short = _tree(tmp_path, "短前缀", ["A01.pdf", "A02.pdf"])
    assert units.is_unit_dir(short) is False, "1 个字符的前缀是扫描批次号，不是作品名"

    dup = _tree(tmp_path, "同号", ["超人前传01.pdf", "超人前传1.pdf"])
    assert units.is_unit_dir(dup) is False, "序号全相同 ⇒ 那不是一个序号体系的两处写法"


def test_前缀闸不动既有写法(tmp_path):
    """护栏：加了前缀闸之后，既有三形态的合并与排序**逐字不变**。

    三形态的前缀都是空串 ⇒ 前缀集合恰好一种 ⇒ 闸门对它们是透明的。
    """
    d = _tree(tmp_path, "混合写法", ["第1话.pdf", "第二话.pdf", "01.pdf", "007.pdf"])
    assert units.is_unit_dir(d) is True
    nums = [it["num"] for it in units.units(d)]
    assert nums == sorted(nums) == [1, 1, 2, 7], "话序仍按序号，不是按文件名/前缀"


# ---------------------------------------------------------------------------
# ② 形态判据：什么算「一棵树 = 一本书」
# ---------------------------------------------------------------------------

def test_用户实况的树被认成一本(tmp_path):
    """用户实况：老书写法不统一的 4 个 PDF ⇒ 恰好一棵单元树，序号 1..4。"""
    d = _tree(tmp_path, "《转生魔女宣告毁灭（1-43话）》/第1卷",
              ["第1话.pdf", "第二话.pdf", "第03话.pdf", "4 第4话.pdf"])
    assert units.is_unit_dir(d) is True
    items = units.units(d)
    assert [it["num"] for it in items] == [1, 2, 3, 4], "话序必须按序号，不是按文件名"
    assert [it["name"] for it in items] == [
        "第1话.pdf", "第二话.pdf", "第03话.pdf", "4 第4话.pdf"]
    assert [it["kind"] for it in items] == ["pdf"] * 4
    assert [it["index"] for it in items] == [0, 1, 2, 3]


def test_解析不出序号的话排在最后(tmp_path):
    """`序章.pdf` / `番外.pdf` 如实按自然序排在**最后**，不猜位置。"""
    d = _tree(tmp_path, "树", ["第2话.pdf", "序章.pdf", "第10话.cbz", "番外.pdf"])
    assert [it["name"] for it in units.units(d)] == [
        "第2话.pdf", "第10话.cbz", "序章.pdf", "番外.pdf"]


def test_不过度合并_同一个目录里几本独立漫画(tmp_path):
    """护栏：`《甲》(第1卷).cbz` + `《乙》(第2卷).cbz` 是**两本**书，不是一部连载。"""
    d = _tree(tmp_path, "两本独立漫画", ["《甲》(第1卷).cbz", "《乙》(第2卷).cbz"])
    assert units.is_unit_dir(d) is False


def test_不过度合并_容器目录(tmp_path):
    """护栏（第 73 期实现时补的判据）：`作者/《甲》/第1话.cbz` + `作者/《乙》/第1话.cbz`。

    两个文件都解析得出序号，但**序号相同** ⇒ 那是两本书各自的第一话。
    只看「有 ≥2 个可解析序号的文件」会把整个作者目录粘成一本 —— 而错误合并
    用户只能靠改目录名来救（改名是源文件操作，本项目承诺源不可变），
    所以判据取「≥2 个**不同**序号」。
    """
    d = _tree(tmp_path, "作者", ["《甲》/第1话.cbz", "《乙》/第1话.cbz"])
    assert units.is_unit_dir(d) is False


def test_多卷重启编号仍然算一部连载(tmp_path):
    """`第1卷/第1话` + `第2卷/第1话` + `第2卷/第2话` ⇒ 序号 {1,2} 不同 ⇒ 合并。

    它的反面就是上面那条容器护栏 —— 判据是「序号不全相同」，不是「文件分布在几层」。
    """
    d = _tree(tmp_path, "多卷", ["第1卷/第1话.cbz", "第2卷/第1话.cbz", "第2卷/第2话.cbz"])
    assert units.is_unit_dir(d) is True


def test_单话不合并(tmp_path):
    """只有一话说明不了是连载（`《书名》/第1话.pdf`）⇒ 退回今天的处理。"""
    assert units.is_unit_dir(_tree(tmp_path, "单话", ["第1话.pdf"])) is False
    assert units.is_unit_dir(_tree(tmp_path, "空", [])) is False
    assert units.is_unit_dir(_tree(tmp_path, "无关", ["封面.jpg", "说明.txt"])) is False


def test_隐藏项不算话(tmp_path):
    """`.hidden/` 目录与 `.第8话.pdf` 都不算 —— 与 `audio._audio_files` 同口径。"""
    d = _tree(tmp_path, "树", ["第1话.pdf", "第2话.pdf",
                               ".hidden/第9话.pdf", ".第8话.pdf"])
    assert [it["name"] for it in units.units(d)] == ["第1话.pdf", "第2话.pdf"]


def test_深度上限(tmp_path):
    """嵌套有上限（`_MAX_DEPTH`）：`若干级文件夹` 以内照收，超了就不算这一话。"""
    deep = "a/b/c/d/e/f"
    d = _tree(tmp_path, "深树", [f"第1话.pdf", f"第2话.pdf", f"{deep}/第3话.pdf"])
    assert [it["name"] for it in units.units(d)] == ["第1话.pdf", "第2话.pdf"]


def test_超限不合并(tmp_path):
    """文件数超 `_MAX_FILES` ⇒ 整棵树**不合并**（宁可退回今天的行为）。

    `media_files` 的 ``None`` 与「空树」的 ``[]`` 必须能区分：前者要退回今天的行为，
    后者只是没东西 —— 两者对 `is_unit_dir` 都是「不合并」，但指纹的语义不同
    （超限时也没有指纹 ⇒ 不会出现「合并了却没有指纹」的条目）。
    """
    names = [f"第{i}话.pdf" for i in range(1, 4)]
    names += [f"图{i:05d}.jpg" for i in range(units._MAX_FILES)]
    d = _tree(tmp_path, "超限", names)
    assert units.media_files(d) is None
    assert units.is_unit_dir(d) is False
    assert units.dir_fingerprint(d) is None


# ---------------------------------------------------------------------------
# ③ 形态（shape_of / collected_by）：与库类型、白名单的关系
# ---------------------------------------------------------------------------

def test_形态判据的顺序_平铺音频优先(tmp_path):
    """`01.mp3`…`03.mp3` 既像音轨又像序号 ⇒ 取**平铺音频**。

    编号轨的有声书是常态，而「N 轨 + 播放器」是改造前就有的行为 —— 取音频形态
    才能让它逐字不变（卡片显示「N 轨」、按自然序播放）。
    """
    flat = _tree(tmp_path, "编号音轨", ["01.mp3", "02.mp3", "03.mp3"])
    assert units.shape_of(flat) == "audio"
    assert units.tracks_of(flat)["items"][0]["name"] == "01.mp3"

    nested = _tree(tmp_path, "嵌套有声书", ["第1卷/第1话.mp3", "第1卷/第2话.mp3",
                                            "第1卷/第3话.mp3"])
    assert units.shape_of(nested) == "units", "嵌套的音频树不是「平铺音频目录」"
    assert [it["name"] for it in units.tracks_of(nested)["items"]] == [
        "第1卷/第1话.mp3", "第1卷/第2话.mp3", "第1卷/第3话.mp3"]

    assert units.shape_of(_tree(tmp_path, "无", ["封面.jpg"])) == ""


def test_库收不收这个目录(tmp_path):
    """`collected_by`：同一棵树在不同库里的结论不同 —— 它就是搬家闸门与枚举共用的判据。

    - 漫画库（白名单 .cbz/.cbr/.pdf）收不下**音频**树：与改造前「漫画库不收有声书目录」
      一致（那是「隐形文件」的防线，不是偏好问题）；
    - 有声书库收不下**PDF** 单元树：整棵树对它隐形，与改造前「下探一层也收不到东西」一致；
    - 只有会合并的库类型才有单元树一说（`merges_for`）。
    """
    comics_allowed = (".cbz", ".cbr", ".pdf")
    audio_allowed = tuple(units.audio.AUDIO_EXTS)

    pdf_tree = _tree(tmp_path, "pdf树", ["第1话.pdf", "第2话.pdf"])
    audio_tree = _tree(tmp_path, "音树", ["第1卷/第1话.mp3", "第1卷/第2话.mp3"])
    flat_audio = _tree(tmp_path, "平铺", ["01.mp3", "02.mp3"])

    assert units.collected_by(pdf_tree, comics_allowed, True) == "units"
    assert units.collected_by(pdf_tree, audio_allowed, True) == ""
    assert units.collected_by(audio_tree, audio_allowed, True) == "units"
    assert units.collected_by(audio_tree, comics_allowed, True) == ""
    assert units.collected_by(flat_audio, audio_allowed, False) == "audio"
    assert units.collected_by(pdf_tree, comics_allowed, False) == "", \
        "不合并的库类型（mixed）里，一棵 PDF 树不是一条书 —— 与改造前一致"

    assert units.merges_for("comic") and units.merges_for("audiobook")
    assert not units.merges_for("ebook") and not units.merges_for("mixed")
    assert units.merges_for("COMIC"), "库类型大小写不该改变判据"
    assert units.audio_allowed(comics_allowed) is False
    assert units.audio_allowed(audio_allowed) is True


# ---------------------------------------------------------------------------
# ④ 指纹：增量刷新的闸门（必须递归，必须与形态判据同源）
# ---------------------------------------------------------------------------

def test_指纹是递归的(tmp_path):
    """嵌套树里改**深处**的一个文件，指纹必须变 —— 否则增量刷新永远不会重探。

    改造前目录条目用的是只看直接子文件的音频口径（`audio.dir_size_and_mtime`），
    于是「在 `第1卷/` 里加了一话」在 ``(size, mtime)`` 上**完全看不见**：
    书架上是 0 变化，也不报错。这是本期用递归指纹修掉的存量缺陷。
    """
    d = _tree(tmp_path, "树", ["第1卷/第1话.pdf", "第1卷/第2话.pdf"])
    before = units.dir_fingerprint(d)
    assert before is not None and before[2] == 2

    (d / "第1卷" / "第3话.pdf").write_bytes(b"%PDF-1.4 fake")
    after = units.dir_fingerprint(d)
    assert after != before, "深处新增一话没有改变指纹：增量刷新会静默漏掉它"
    assert after[2] == 3

    # 换成体积不同的内容也要看得见（只看 mtime 在 SMB 上不可靠）
    (d / "第1卷" / "第3话.pdf").write_bytes(b"x" * 4096)
    assert units.dir_fingerprint(d) != after


def test_平铺音频目录不走进阶指纹(tmp_path):
    """平铺音频目录仍是改造前的口径（指纹为 ``None`` ⇒ 调用方回落音频口径）。

    这不是「优化」而是兼容：那套口径含封面等非媒体文件，且已经写进了索引里的
    ``size``/``mtime``（换口径 = 全库音频书重探一次、卡片体积跟着变）。
    """
    flat = _tree(tmp_path, "平铺", ["01.mp3", "02.mp3"])
    assert units.dir_fingerprint(flat) is None


def test_封面可以在子树里(tmp_path):
    """封面找的是 `cover` / `folder` / `poster` 那套名字，可以埋在子树里。"""
    d = _tree(tmp_path, "树", ["第1卷/第1话.pdf", "第1卷/cover.jpg"])
    assert units.cover_in_tree(d) == "第1卷/cover.jpg"
    assert units.cover_in_tree(_tree(tmp_path, "无封面", ["第1话.pdf"])) == ""
