"""KOReader 批注导出文件（``.annotations.lua``）的解析与映射。

样本文件是**按上游算法手写**的，不是从别处抄的：`frontend/dump.lua` 的
``_serialize`` 产出 ``[键] = 值,``、4 空格缩进、每个键总带方括号，``luasettings.lua``
的 ``flush`` 用 ``dump(self.data, nil, true)``（``ordered=true`` ⇒ 键有序）落盘。

**为什么测这么细**：这份数据要写进用户的批注库。解析器「尽力而为」地吐出一部分，
调用方拿到的是一个**成功的返回值** —— 丢的那部分永远不会有人发现。所以下面一半的用例
是「读不懂就该整份拒收」。
"""
import time

import pytest

from novelforge.core import koreader_anno as ka


#: 一份仿真的导出文件：一条 EPUB 高亮带笔记，一条改过时间。
SAMPLE = """{
    ["annotations"] = {
        [1] = {
            ["chapter"] = "第一章 远行",
            ["color"] = "yellow",
            ["datetime"] = "2026-09-01 10:00:00",
            ["datetime_updated"] = "2026-09-02 11:30:00",
            ["drawer"] = "lighten",
            ["note"] = "这里说得对",
            ["page"] = "/body/DocFragment[3]/body/div/p[5]/text().0",
            ["pageno"] = 42,
            ["pos0"] = "/body/DocFragment[3]/body/div/p[5]/text().0",
            ["pos1"] = "/body/DocFragment[3]/body/div/p[5]/text().40",
            ["text"] = "这是被划线的原文",
        },
        [2] = {
            ["chapter"] = "第二章",
            ["color"] = "green",
            ["datetime"] = "2026-09-03 08:00:00",
            ["drawer"] = "underscore",
            ["page"] = "/body/DocFragment[4]/body/div/p[2]/text().0",
            ["pos0"] = "/body/DocFragment[4]/body/div/p[2]/text().0",
            ["pos1"] = "/body/DocFragment[4]/body/div/p[2]/text().12",
            ["text"] = "第二条划线",
        },
    },
    ["datetime"] = "2026-09-27 20:15:00",
    ["device_id"] = "a1b2c3",
    ["paging"] = false,
}
"""


# ---------------------------------------------------------------------------
# 1. 正常解析
# ---------------------------------------------------------------------------

def test_sample_file_parses():
    got = ka.parse(SAMPLE)
    assert got["device_id"] == "a1b2c3"
    assert got["datetime"] == "2026-09-27 20:15:00"
    assert got["paging"] is False
    assert len(got["annotations"]) == 2
    a = got["annotations"][0]
    assert a["text"] == "这是被划线的原文"
    assert a["note"] == "这里说得对"
    assert a["pageno"] == 42                      # 数字读成数字，不是字符串
    assert a["datetime_updated"] == "2026-09-02 11:30:00"


def test_annotation_order_follows_the_array_index():
    """`[1]` 在前 `[2]` 在后 —— 不能靠字典顺序（那样 `[10]` 会跑到 `[2]` 前面）。"""
    text = 'return { ["annotations"] = { [10] = { ["text"] = "十" }, [2] = { ["text"] = "二" } } }'
    got = ka.parse(text)
    assert [a["text"] for a in got["annotations"]] == ["二", "十"]


def test_missing_annotations_is_an_empty_list_not_an_error():
    """只有 device_id 的文件是合法的（上游没批注就不导出，但空表也不该炸）。"""
    got = ka.parse('return { ["device_id"] = "x", ["paging"] = true }')
    assert got["annotations"] == [] and got["paging"] is True


def test_leading_return_and_block_comments_are_tolerated():
    got = ka.parse('--[[ header ]]\nreturn {\n  ["annotations"] = {},\n}\n')
    assert got["annotations"] == []


def test_real_file_header_is_tolerated():
    """真文件的**第一行是它自己的绝对路径**，作为行注释。

    `util.writeToFile(..., lua_dofile_ready=true)` 加的前缀是
    ``"-- " .. filepath .. "\\nreturn " .. data`` —— 所以认 ``return`` 之前必须
    先跳过注释。这类前缀最容易在「本地跑得好好的、拿真文件一试就炸」时暴露。
    """
    real = ("-- /mnt/onboard/books/某书.epub.sdr/某书.epub.annotations.lua\n"
            "return {\n    [\"device_id\"] = \"d1\",\n}\n")
    got = ka.parse(real)
    assert got["device_id"] == "d1"


# ---------------------------------------------------------------------------
# 2. Lua 的转义（不是 JSON 的）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ('"a\\"b"', 'a"b'),            # 引号
    ('"a\\\\b"', 'a\\b'),          # 反斜杠
    ('"a\\rb"', "a\rb"),           # %q 把 \r 写成反斜杠 r
    ('"a\\0b"', "a\x00b"),         # %q 把 \0 写成反斜杠 0
    ('"a\\9b"', "a\tb"),           # 其它控制字符走十进制转义
    ('"a\\nb"', "a\nb"),           # 常规 \n 也认
])
def test_string_escapes_follow_lua(raw, expected):
    got = ka.parse('return { ["annotations"] = { [1] = { ["text"] = %s } } }' % raw)
    assert got["annotations"][0]["text"] == expected


def test_qq_writes_a_newline_as_backslash_plus_a_real_newline():
    """Lua 的 `string.format("%q")` 遇到换行写的是**反斜杠后跟一个真换行**，
    不是 `\\n` 两个字符。多行笔记在真文件里就长这样 —— 认不出来就会把笔记截断。"""
    text = 'return { ["annotations"] = { [1] = { ["text"] = "第一行\\\n第二行" } } }'
    got = ka.parse(text)
    assert got["annotations"][0]["text"] == "第一行\n第二行"


# ---------------------------------------------------------------------------
# 3. 读不懂就整份拒收（这一组是同一条纪律的多个面）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad,why", [
    ('return { ["annotations"] = { [1] = { ["text"] = "没结尾 }', "截断"),
    ('return { ["annotations"] = { [1] = { ["text"] = "x" } } } 剩下垃圾', "尾部多余"),
    ('return { ["annotations"] = { [1] = { ["text"] = [[长字符串]] } } }', "长字符串不认识"),
    ('return { ["annotations"] = { [1] = { ["text"] = 0x1f } } }', "十六进制数字不认识"),
    ('return { ["annotations"] = { [1] = { ["text"] = "a\\qb" } } }', "没见过的转义"),
    ('return { ["annotations"] = 42 }', "annotations 不是表"),
    ('return { ["annotations"] = { [1] = 42 } }', "某一条不是表"),
    ('return { ["annotations"] = { [1] = { ["text"] = nil --[[ LOOP:\n    ^--- ]] } } }', "成环"),
    ('', "空文件"),
    ('return 42', "顶层不是表"),
])
def test_unreadable_files_are_rejected_whole(bad, why):
    """**一条都不许「尽力解析」出来。** 解析出一半 = 静默丢一半，
    而调用方拿到的是一个成功的返回值。"""
    with pytest.raises(ka.KoreaderAnnoError):
        ka.parse(bad)


# ---------------------------------------------------------------------------
# 4. 位置锚：EPUB 与 PDF 的形态**不一样**
# ---------------------------------------------------------------------------

def test_epub_anchor_is_the_xpointer():
    item = {"page": "/body/DocFragment[3]/body/div/p[5]/text().0",
            "pos0": "/body/DocFragment[3]/body/div/p[5]/text().0"}
    assert ka.page_anchor(item) == "/body/DocFragment[3]/body/div/p[5]/text().0"


def test_pdf_anchor_distinguishes_two_highlights_on_the_same_page():
    """**同页两条高亮必须算出两个不同的锚。**

    固定版式的 ``page`` 是页码整数，真位置在 ``pos0``/``pos1`` 的 ``{x,y}`` 里。
    只拿页码当锚 ⇒ 同页第二条判成「已有」⇒ **那一页只导得进第一条**，
    而且每次同步都报「已存在」，看着像去重生效了。
    """
    a = {"page": 12, "pos0": {"x": 10, "y": 20}, "pos1": {"x": 30, "y": 40}}
    b = {"page": 12, "pos0": {"x": 11, "y": 20}, "pos1": {"x": 30, "y": 40}}
    assert ka.page_anchor(a) != ka.page_anchor(b)
    assert ka.page_anchor(a) == ka.page_anchor(dict(a)), "同一条要稳定，否则每次同步都插一条"


def test_no_position_yields_empty_anchor():
    assert ka.page_anchor({"page": None}) == ""
    with pytest.raises(ka.KoreaderAnnoError):
        ka.page_anchor({"page": {"x": 1}})


# ---------------------------------------------------------------------------
# 5. 映射到本项目的批注
# ---------------------------------------------------------------------------

def _items(text):
    return ka.to_items(ka.parse(text))


def test_sample_maps_to_items_with_unknown_chapter_index():
    items, skipped, stats = _items(SAMPLE)
    assert skipped == [] and stats["unknown_color"] == 0
    assert len(items) == 2
    first = items[0]
    assert first["anchor"].endswith("text().0")
    assert first["quote"] == "这是被划线的原文"
    assert first["style"] == "highlight"       # drawer=lighten
    assert first["color"] == "yellow"
    # 上游给的是**章节标题**，本项目要的是序号 ⇒ 序号必须留 -1（未知），
    # 填 0 会让界面把每条设备批注都渲染成「第 1 章」
    assert first["chapter"] == -1
    assert first["chapter_title"] == "第一章 远行"
    assert items[1]["style"] == "underline"    # drawer=underscore
    # 设备改过时间优先（上游合并语义也是 datetime_updated or datetime）
    assert first["created_at"] == time.mktime(time.strptime("2026-09-02 11:30:00",
                                                            "%Y-%m-%d %H:%M:%S"))


def test_falls_back_to_creation_time_when_never_edited():
    items, _, _ = _items(SAMPLE)
    assert items[1]["created_at"] == time.mktime(time.strptime("2026-09-03 08:00:00",
                                                               "%Y-%m-%d %H:%M:%S"))


def test_entries_without_text_or_position_are_skipped_with_a_reason():
    """书签（没有 text）与没有位置的条目都不收 —— 分别记原因，不合并成一个数。"""
    text = """return { ["annotations"] = {
        [1] = { ["page"] = "/p[1]", ["datetime"] = "2026-09-01 10:00:00" },
        [2] = { ["text"] = "有引文没位置" },
        [3] = { ["page"] = "/p[3]", ["text"] = "好的" },
    } }"""
    items, skipped, _ = _items(text)
    assert [s["reason"] for s in skipped] == ["no_text", "no_position"]
    assert [i["quote"] for i in items] == ["好的"]


def test_unknown_color_is_imported_but_counted():
    """映射不上的颜色照收（回落到默认色）**但计数** —— 换个颜色显示也是失真，
    只是没有「丢掉」严重；调用方要能把这件事说给用户听。"""
    text = """return { ["annotations"] = { [1] = {
        ["page"] = "/p[1]", ["text"] = "x", ["color"] = "olive", ["drawer"] = "wat" } } }"""
    items, _, stats = _items(text)
    assert items[0]["color"] == ka.DEFAULT_COLOR
    assert stats["unknown_color"] == 1 and stats["unknown_drawer"] == 1


def test_cyan_maps_to_teal_and_every_mapped_color_exists_in_the_palette():
    """映射表里的每个目标色都必须在**前端调色板**里真的存在。

    写了 `COLOR_MAP["cyan"] = "teal"` 而调色板里没有 `teal`，前端会静默回落成黄色 ——
    映射表看着做过了，实际没生效。
    """
    assert ka.COLOR_MAP["cyan"] == "teal"
    import pathlib
    import re as _re
    src = pathlib.Path("frontend/src/data/annotationColors.ts").read_text(encoding="utf-8")
    palette = set(_re.findall(r"\{ key: '([a-z]+)', label: '[^']*', hex:", src))
    assert palette, "没从调色板里读出颜色键，这个测试的判据已经失效了"
    assert set(ka.COLOR_MAP.values()) <= palette, \
        "映射到了调色板里没有的颜色：%s" % (set(ka.COLOR_MAP.values()) - palette)
    assert ka.DEFAULT_COLOR in palette
    styles = set(_re.findall(r"\{ key: '([a-z]+)', label: '[^']*' \}", src))
    assert set(ka.DRAWER_TO_STYLE.values()) <= styles, \
        "映射到了前端没有的样式：%s" % (set(ka.DRAWER_TO_STYLE.values()) - styles)


def test_unparsable_timestamp_is_counted_not_guessed():
    text = """return { ["annotations"] = { [1] = {
        ["page"] = "/p[1]", ["text"] = "x", ["datetime"] = "不是时间" } } }"""
    items, _, stats = _items(text)
    assert items[0]["created_at"] is None, "认不出来的时间不许猜一个"
    assert stats["no_timestamp"] == 1


@pytest.mark.parametrize("raw,ok", [
    ("2026-09-27 20:15:00", True),
    ("2026-09-27", True),
    ("", False),
    ("昨天", False),
])
def test_parse_ts(raw, ok):
    got = ka.parse_ts(raw)
    assert (got is not None) == ok


# ---------------------------------------------------------------------------
# 6. 找文件 + 导入（走真实书库目录）
# ---------------------------------------------------------------------------

import json
import pathlib

from novelforge.core import db, library


def _bid(root, name: str = "anchor-book.epub") -> str:
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"EPUB")
    library.invalidate()
    books = [b for b in library.books() if b["name"].endswith(name)]
    assert books, "扫描没找到 %s" % name
    return books[0]["id"]


def _lua(v):
    """把 Python 值写成 Lua 字面量。

    字符串走 `json.dumps`：这两种语言的字符串转义在**这批用例用到的字符**上是一致的
    （`\\"` / `\\\\` / `\\n`），而且都会写成双引号 —— 而 Python 的 `%r` 会写成**单引号**，
    那不是 Lua。第一版就是这么写错的，解析器正确地拒收了它。
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return json.dumps(str(v), ensure_ascii=False)


def _export_text(*, device="d1", dt="2026-09-27 20:15:00", annos=()):
    """按上游 `dump` + `util.writeToFile` 的形状拼一份导出文件。

    第一行是**文件自己的绝对路径**（`lua_dofile_ready` 加的前缀），第二行起是 `return {`。
    """
    rows = []
    for i, a in enumerate(annos, 1):
        fields = "".join('            ["%s"] = %s,\n' % (k, _lua(v)) for k, v in a.items())
        rows.append("        [%d] = {\n%s        },\n" % (i, fields))
    return ("-- /lib/book.epub.sdr/book.epub.annotations.lua\n"
            "return {\n"
            "    [\"annotations\"] = {\n%s    },\n"
            "    [\"datetime\"] = %s,\n"
            "    [\"device_id\"] = %s,\n"
            "    [\"paging\"] = false,\n"
            "}\n" % ("".join(rows), _lua(dt), _lua(device)))


def _anon(page, text, **kw):
    d = {"page": page, "pos0": page, "text": text,
         "datetime": "2026-09-01 10:00:00"}
    d.update(kw)
    return d


def _put_export(root, book_name, body, *, in_sidecar=False):
    p = pathlib.Path(root) / book_name
    d = p.parent / (book_name + ".sdr") if in_sidecar else p.parent
    d.mkdir(parents=True, exist_ok=True)
    f = d / (book_name + ka.SUFFIX)
    f.write_text(body, encoding="utf-8")
    return f


def test_export_next_to_the_book_is_found_and_imported(default_root, client, auth_headers):
    _bid(default_root)                                   # 放一本占位书并扫描
    name = "anchor-book.epub"
    _put_export(default_root, name, _export_text(
        annos=[_anon("/body/p[1]", "划线一"), _anon("/body/p[2]", "划线二", note="笔记")]))

    # 先 dry-run：**一条都不许落库**
    dry = client.post("/api/annotations/import-koreader", headers=auth_headers).json()
    assert dry["scanned"] == 1 and dry["applied"] is False
    assert dry["files"][0]["items"] == 2
    assert dry["totals"]["added"] == 0, "dry-run 写库了"
    assert client.get("/api/annotations", headers=auth_headers).json()["items"] == []

    got = client.post("/api/annotations/import-koreader?apply=1", headers=auth_headers).json()
    assert got["totals"]["added"] == 2, got
    rows = db.all_annotations()
    assert {r["quote"] for r in rows} == {"划线一", "划线二"}
    assert {r["origin"] for r in rows} == {"koreader"}
    assert {r["chapter"] for r in rows} == {-1}, "设备给的是章节标题，序号必须留「未知」"
    assert next(r for r in rows if r["quote"] == "划线二")["note"] == "笔记"

    # 再导一次：幂等，条目数不变
    again = client.post("/api/annotations/import-koreader?apply=1", headers=auth_headers).json()
    assert again["totals"]["added"] == 0 and again["totals"]["unchanged"] == 2, again
    assert len(db.all_annotations()) == 2


def test_export_in_the_sidecar_dir_is_found(default_root, client, auth_headers):
    """KOReader 默认就往 sidecar 目录里写（`DocSettings:getSidecarDir`）。"""
    _bid(default_root)
    _put_export(default_root, "anchor-book.epub",
                _export_text(annos=[_anon("/body/p[9]", "sidecar 里那条")]),
                in_sidecar=True)
    got = client.post("/api/annotations/import-koreader?apply=1", headers=auth_headers).json()
    assert got["totals"]["added"] == 1, got
    assert [a["quote"] for a in db.all_annotations()] == ["sidecar 里那条"]


def test_unreadable_file_is_reported_and_does_not_block_the_others(default_root, client, auth_headers):
    """一个文件读不懂，**别的文件照样导**，且报告里留下原因。

    最坏的做法是整批失败或整批跳过 —— 用户看到的是「导入了 0 条」，
    而真正的原因是某一个文件坏了。
    """
    _bid(default_root)
    _put_export(default_root, "anchor-book.epub", 'return { ["annotations"] = { [1] = {')  # 截断
    _make_second = pathlib.Path(default_root) / "第二本.epub"
    _make_second.write_bytes(b"EPUB")
    library.invalidate()
    _put_export(default_root, "第二本.epub", _export_text(annos=[_anon("/body/p[1]", "好的那条")]))

    got = client.post("/api/annotations/import-koreader?apply=1", headers=auth_headers).json()
    assert got["scanned"] == 2, got
    bad = [f for f in got["files"] if f["error"]]
    assert len(bad) == 1 and "截断" in bad[0]["error"] or bad[0]["error"]
    assert got["totals"]["added"] == 1, "坏文件把好文件也带崩了"


def test_a_book_without_an_export_file_produces_nothing(default_root, client, auth_headers):
    """没有导出文件不是错误 —— 只是没东西可导。**不报错、也不编造 0 条记录。**"""
    _bid(default_root)
    got = client.post("/api/annotations/import-koreader", headers=auth_headers).json()
    assert got["scanned"] == 0 and got["files"] == []
