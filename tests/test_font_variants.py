"""服务端字体变体（第 52 期）：子样式 → 字重 / 斜体，OS/2 + head 交叉校验，族分组键。

核心不变量：同一族的 Regular / Bold / Italic 共享 family_key，前端据此把 @font-face 归到
同一 font-family 名下、按 font-weight / font-style 区分 —— 阅读器「选加粗」才命中真实变体。
解析不出（WOFF/WOFF2、name 表缺失、未知子样式）一律回落「不猜」，family_key 留空。
"""
import struct

from novelforge.core import fonts


def _build_ttf(family: str, subfamily: str, os2_weight: int, head_italic: bool) -> bytes:
    """拼一个最小但结构合法的 TTF（只含 name / OS/2 / head 三张表），供解析函数消费。"""
    def name_table() -> bytes:
        recs = []
        str_data = b""

        def add(nid: int, text: str) -> None:
            nonlocal str_data
            b = text.encode("utf-16-be")
            recs.append((3, 1, 0x409, nid, b))

        add(1, family)
        add(2, subfamily)
        rec_data = b""
        for pid, eid, lid, nid, b in recs:
            off = len(str_data)
            str_data += b
            rec_data += struct.pack(">HHHHHH", pid, eid, lid, nid, len(b), off)
        count = len(recs)
        return struct.pack(">HHH", 0, count, 6 + count * 12) + rec_data + str_data

    def os2_table() -> bytes:
        # version(2) + usWeightClass(2) + usWidthClass(2) …… 函数只读 offset 4 的 usWeightClass
        return struct.pack(">HHH", 0, os2_weight or 0, 5)

    def head_table() -> bytes:
        data = bytearray(54)
        struct.pack_into(">H", data, 44, 0x0002 if head_italic else 0)  # macStyle bit1 = italic
        return bytes(data)

    tables = {b"name": name_table(), b"OS/2": os2_table(), b"head": head_table()}
    tags = sorted(tables)
    num = len(tags)
    dir_size = num * 16
    head = struct.pack(">I", 0x00010000) + struct.pack(">HHHH", num, 0, 0, 0)  # 12 字节 sfnt 头
    body = b""
    offsets = {}
    for t in tags:
        if len(body) % 4:
            body += b"\x00" * (4 - len(body) % 4)
        # 表数据实际文件偏移 = 头(12) + 目录(num*16) + 已累积 body
        offsets[t] = 12 + dir_size + len(body)
        body += tables[t]
    directory = b""
    for t in tags:
        directory += t + struct.pack(">III", 0, offsets[t], len(tables[t]))
    return head + directory + body


def test_子样式到字重斜体_已知组合():
    cases = [
        ("Regular", 400, False),
        ("Bold", 700, False),
        ("Italic", None, True),
        ("Bold Italic", 700, True),
        ("Medium", 500, False),
        ("Light", 300, False),
        ("SemiBold", 600, False),
        ("ExtraLight", 200, False),
        ("Black", 900, False),
        ("BoldItalic", 700, True),  # 连写也要能拆
    ]
    for sub, w, it in cases:
        assert fonts._style_to_weight_italic(sub) == (w, it), sub


def test_子样式_已知非变体_不误判斜体():
    # 解析不出字重词 → 字重 None；不含 italic/oblique 词 → 斜体 False（已知「非斜体」）。
    # 「不猜」指不臆造字重/斜体，而非回落成 None；真正的「未知」由上游 OS/2 表补。
    assert fonts._style_to_weight_italic("Caption") == (None, False)
    assert fonts._style_to_weight_italic("Display") == (None, False)
    assert fonts._style_to_weight_italic("") == (None, None)


def test_font_meta_子样式优先于_OS2():
    data = _build_ttf("My Family", "Bold Italic", 400, False)
    family, style, weight, italic, key = fonts._font_meta(data)
    assert family == "My Family" and style == "Bold Italic"
    # 子样式已给 700 + italic，应原样采用，不被 OS/2 的 400 覆盖
    assert weight == 700 and italic is True
    assert key == "myfamily"


def test_font_meta_子样式缺失时回落_OS2与head():
    data = _build_ttf("My Family", "", 700, True)
    family, style, weight, italic, key = fonts._font_meta(data)
    assert weight == 700 and italic is True
    assert key == "myfamily"


def test_font_meta_未知子样式_字重留空():
    data = _build_ttf("My Family", "Caption", 0, False)
    _, _, weight, italic, key = fonts._font_meta(data)
    # Caption 不是已知字重词，OS/2 又是 0 → 字重留空；斜体靠 head 判断为否
    assert weight is None and italic is False
    assert key == "myfamily"


def test_font_meta_WOFF_不解析():
    # 非 TTF/OTF（WOFF magic）_ttf_names 直接返回空，family_key 留空、字重斜体都不猜
    data = b"wOFF" + b"\x00" * 20
    family, style, weight, italic, key = fonts._font_meta(data)
    assert (family, style, weight, italic, key) == ("", "", None, None, "")


def test_save_list_带回变体字段(tmp_path, monkeypatch):
    # 把字体目录切到临时目录，避免污染共享的 FONTS_DIR
    monkeypatch.setattr(fonts.config, "FONTS_DIR", tmp_path)
    data = _build_ttf("Source Han Serif", "Bold", 700, False)
    saved = fonts.save_font("shs-bold.ttf", data)
    assert saved["family_key"] == "sourcehanserif"
    assert saved["weight"] == 700 and saved["italic"] is False

    items = fonts.list_fonts()["items"]
    assert len(items) == 1
    assert items[0]["family_key"] == "sourcehanserif"
    assert items[0]["weight"] == 700

    # 再放一个同族的 Regular，两者应归到同一 family_key（前端据此分组）
    fonts.save_font("shs-regular.ttf", _build_ttf("Source Han Serif", "Regular", 400, False))
    keys = {i["family_key"] for i in fonts.list_fonts()["items"]}
    assert keys == {"sourcehanserif"}
