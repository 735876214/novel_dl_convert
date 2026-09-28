import re
import pathlib

# ---------------- ISBN 形状（**唯一真值源**，第 34 期立）----------------
# 为什么必须只有一处：原先 `library._isbn_of` 与 `fileops._set_isbn` 各写了一遍
# `[\dxX-]{10,17}` 的**子串**判据，而它会把 EPUB 里最常见的 `dc:identifier`
# —— **UUID**（`ec365410-6538-43b9-93e2-9f8cdd3c0c72`）——当成 ISBN：
#   · 界面上冒出一个假 ISBN，元数据完整度还白送 10 分；
#   · `_set_isbn` 更狠：它会**把书自己的标识符覆盖掉**。
# 本仓实测随机 UUID 约 1/3 命中 —— 这正是「同一用例偶发失败」的来源
# （见 `tests/test_stats_integrity.py` 的分位数断言，第 34 期定位）。
#
# 判据只做**形状**（不做校验位）：10 位（末位可为 X）或 13 位纯数字，
# 允许空格 / 连字符分隔与 `urn:isbn:` 前缀。UUID（去连字符后 32 个含字母的字符）
# 与任意数字串都不会命中。
_ISBN10 = re.compile(r"\d{9}[\dXx]")
_ISBN13 = re.compile(r"\d{13}")
#: 分隔符：普通空格（含不换行空格）与常见连字符（- ‐ ‑ ‒ – — ―）
_ISBN_SEP = re.compile(r"[\s\u00a0\u2010-\u2015-]")
_ISBN_URN = re.compile(r"^urn:isbn:", re.I)


def isbn_digits(value) -> str:
    """把候选串规整成 ISBN 字符；**不像 ISBN 就返回空串**。

    返回规整后的 10 / 13 位字符（ISBN-10 的校验位统一大写 X），调用方拿它去检索 / 比对；
    需要原始文本（带连字符 / urn 前缀）的场景自己保留原串。
    """
    s = _ISBN_URN.sub("", str(value or "").strip())
    s = _ISBN_SEP.sub("", s)
    if _ISBN13.fullmatch(s):
        return s
    if _ISBN10.fullmatch(s):
        return s.upper()
    return ""


# ---------------- 书名尾部的「范围 / 话数备注」（**唯一真值源**，第 73 期立）---------
# 为什么要有一处统一剥：连载书在磁盘上常被写成 `《转生魔女宣告毁灭（1-43话）》`，
# 括号里那段是**集数说明**，不是书名的一部分 —— 不剥的话书架上就是一长串
# 「转生魔女宣告毁灭（1-43话）」，与别处（元数据提供商抓回来的书名）对不上，
# 也就聚不到一起。判据放在 ``from_filename`` 里 ⇒ **对所有书生效**（含存量书，
# 经 `library.SCAN_RULE_VERSION` 的自愈通道重探）。
#
# 判据**窄**（宁可不剥，也不剥掉真的书名）：
#   · 括号里**整段**必须是「数 或 数-数（单位词可有可无）」，或「全N + 单位词」；
#   · 单位词只有 `话/話/卷/回/册/集/部/篇/幕/章`（与 `units.UNIT_WORDS` 同一套写法）；
#   · 反例一律**不剥**：`（0079）`（无范围、无单位词 —— 那是标题里的年份）、
#     `（修订版）` / `（上册）` / `（全本）`（压根没有数字）。
# 只剥**一处**（最靠后的那一处）：`（甲）（1-43话）` 这种多段备注不递归去剥，
# 免得把书名里的正当括号一并吃掉。
_COUNT_UNIT = "话話卷回册集部篇幕章"
_COUNT_NOTE_RE = re.compile(
    rf"^(?:第?全?\d*[-–~]\d+[{_COUNT_UNIT}]?|全?\d+[{_COUNT_UNIT}])$")
#: 尾部括号（全角 / 半角都收）：head 必须非空 —— 整个书名就是括号里那点时不动它
_TAIL_NOTE_RE = re.compile(r"^(?P<head>.+?)\s*[（(](?P<note>[^（()）]*)[）)]\s*$")


def strip_count_note(title: str) -> str:
    """剥掉书名尾部的范围 / 话数备注：``转生魔女宣告毁灭（1-43话）`` ⇒ ``转生魔女宣告毁灭``。

    判据与反例见文件头那段注释。**剥不出来就原样返回**（这里不猜、不截断）。
    """
    s = str(title or "").strip()
    m = _TAIL_NOTE_RE.match(s)
    if not m or not _COUNT_NOTE_RE.match(m.group("note").strip()):
        return s
    return m.group("head").strip()


# 知轩藏书等格式：《书名》（校对版全本）作者：远瞳
FILENAME_RE = re.compile(
    r"^(?:《(?P<title>.+?)》)?\s*(?:（[^）]*）)?\s*(?:作者[：:]\s*(?P<author>[^\.]+))?",
    re.U,
)


def from_filename(name: str) -> dict:
    """从文件名解析「书名 / 作者」—— **书名解析的唯一入口**（两分支都过 `strip_count_note`）。

    两个分支指的是 `《…》` 命中与未命中（裸文件名）。它们必须都剥那道备注，
    否则 `《甲（1-43话）》.cbz` 与 `甲（1-43话）.cbz` 会得到两个不同的书名 ——
    而判据只有一份（`strip_count_note`）才不会走样。
    """
    stem = pathlib.Path(name).stem
    m = FILENAME_RE.search(stem)
    if m and m.group("title"):
        title = m.group("title").strip()
        author = (m.group("author").strip() if m.group("author") else "未知")
    else:
        title = stem.strip()
        author = "未知"
    return {"title": strip_count_note(title), "author": author}


def from_body(head: str) -> dict:
    """从正文头部抠元数据。"""
    meta = {}
    for k, p in [
        ("author", r"作者[：:]\s*(.+)"),
        ("description", r"简介[：:]\s*(.+)"),
    ]:
        m = re.search(p, head)
        if m:
            meta[k] = m.group(1).strip()
    return meta


def merge_meta(*metas: dict) -> dict:
    """多来源合并：已解析出的书名/作者优先于占位值。"""
    out = {}
    for m in metas:
        for k, v in m.items():
            if v and (k not in out or out[k] in ("未知", None)):
                out[k] = v
    return out
