"""第 89 期：TXT 上传 / 编码判据 —— **BOM 确定性优先 + 绝不静默丢字节**。

本文件**只加不改**（既有编码契约仍在 ``tests/test_txt_reading.py``，逐条不许动）：

1. **BOM 是确定证据**：UTF-8 / UTF-16LE / UTF-16BE 带 BOM 的书必须**整本**读对 ——
   老实现没有 BOM 分支，UTF-16LE 的 ``FF FE`` 不是合法 UTF-8 ⇒ 落到 gb18030 打分，
   而 gb18030 几乎「总能解码成功」⇒ 整本乱码、既不报错也看不出问题。
2. **成功路径不许退化**：GBK 仍判 gb18030、Big5 不被当成 gb18030、大文件尾部截断仍判 UTF-8。
3. **失败路径不许静默**：主体合法 GBK、中间夹 1 个非法字节 ⇒ 正文照样读得出，
   且**有可观察的「无法解码」记录**（计数 / 字段），**不是**静默变短。
4. 编码判据版本升级 ⇒ 派生件重读重切（对齐既有 ``test_编码判据升级会重读重切`` 的写法）。
"""
import codecs
import pathlib

import pytest

from novelforge import config
from novelforge.core import detect, library, pipeline, txtcache

_CN = "一二三四五六七八九十"


@pytest.fixture(autouse=True)
def _cache_dir_in_tmp(tmp_path, monkeypatch):
    """CACHE_DIR 默认指向真实配置目录；派生缓存 / 内存缓存必须落进用例专属目录。"""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    txtcache._SPLIT_CACHE.clear()
    txtcache._DECODE_CACHE.clear()


def _text(chapters: int = 4) -> str:
    parts = []
    for i in range(1, chapters + 1):
        parts.append(f"第{_CN[i - 1]}章 标题\n" + "正文内容在这里，写长一点。" * 20)
    return "\n".join(parts)


def _big5_text() -> str:
    """繁体样本：**标点是关键**。「，」在 Big5 是 A141、在 GBK 是 A3AC，拿错编码解出来
    的那一片全是不成字的怪符号（与既有 `_BIG5_TEXT` 同构）。"""
    return "\n".join(
        f"第{_CN[i - 1]}章 第{_CN[i - 1]}節\n" + "這是一本繁體書，內容用 Big5 編碼寫成。他說：「風起了。」\n" * 20
        for i in range(1, 5)
    )


def _gbk_text() -> str:
    return "\n".join(
        f"第{_CN[i - 1]}章 第{_CN[i - 1]}節\n" + "这是一本简体书，用 GBK 编码写成。他说：「风起了。」\n" * 20
        for i in range(1, 5)
    )


def _write(root, name: str, data: bytes) -> pathlib.Path:
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _flat_chapters(detail: dict) -> list:
    return [c for v in detail["chapters"] for c in v["chapters"]]


# ---------------------------------------------------------------------------
# 1. BOM 确定性判定（老实现整段缺失 —— 这几条在修之前是红的）
# ---------------------------------------------------------------------------

#: (标签, 期望的探测结果, 应写在前面的 BOM 字节序列)
_BOM_CASES = (
    ("utf8bom", "utf-8-sig", lambda body: codecs.BOM_UTF8 + body.encode("utf-8")),
    ("utf16le", "utf-16", lambda body: codecs.BOM_UTF16_LE + body.encode("utf-16-le")),
    ("utf16be", "utf-16", lambda body: codecs.BOM_UTF16_BE + body.encode("utf-16-be")),
)


@pytest.mark.parametrize("tag,enc,mk", _BOM_CASES)
def test_带BOM的书整本读对(tmp_path, tag, enc, mk):  # noqa: ARG001
    body = _text()
    p = _write(tmp_path, f"{tag}.txt", mk(body))

    assert pipeline._detect_encoding(p) == enc, f"{tag} 的探测结果不是 {enc}"

    decoded, info = pipeline.decode_file(p)
    # 开头那个 U+FEFF 必须被吃掉（读出来是「第一章…」，不是「\ufeff第一章…」）
    assert decoded.startswith("第一章"), f"{tag} 读出来是乱码：{decoded[:40]!r}"
    assert "\ufffd" not in decoded
    assert info["encoding"] == enc
    assert info["undecodable"] == 0


def test_UTF16LE_BOM_端到端读出来是正确中文(client, auth_headers, default_root):  # noqa: ARG001
    """从磁盘走到阅读器：UTF-16LE 带 BOM 的书要能列章、正文是**真中文**（不是乱码）。

    老实现把 ``FF FE`` 交给 gb18030 解 ⇒ 满屏怪字；这条用例在修之前是红的。
    """
    _write(default_root, "UTF16书.txt",
           codecs.BOM_UTF16_LE + _text().encode("utf-16-le"))
    library.invalidate()
    books = [b for b in library.books() if b["name"] == "UTF16书.txt"]
    assert books, "扫描没找到 UTF16书.txt"
    bid = books[0]["id"]

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    assert len(_flat_chapters(detail)) >= 3, f"没列出目录：{detail.get('chapters')}"

    body = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers).json()
    assert "正文内容在这里" in body["html"], f"正文是乱码：{body['html'][:200]!r}"
    assert "�" not in body["html"]
    # 第 89 期：解码报告如实随章节下发（识别结果对用户可见）
    assert body["text_encoding"]["encoding"] == "utf-16"
    assert body["text_encoding"]["undecodable"] == 0


def test_无BOM但整篇像UTF16也能判出(tmp_path):
    """无 BOM 的 UTF-16（含大量 ASCII）走**明确判据**：ASCII 的 0x00 按奇偶分布。

    夹具构造成「几乎全 ASCII + 少量中文」：UTF-16LE 下奇数位恒为 0x00 ⇒ 判 ``utf-16-le``。
    """
    body = "Chapter One\nHello world, this is plain ASCII text.\n" * 40 + "\n中文一点点\n"
    p = _write(tmp_path, "无BOM16.txt", body.encode("utf-16-le"))

    assert pipeline._detect_encoding(p) == "utf-16-le"
    decoded, info = pipeline.decode_file(p)
    assert "Chapter One" in decoded and "中文一点点" in decoded
    assert info["undecodable"] == 0


# ---------------------------------------------------------------------------
# 2. 既有口径不许退化
# ---------------------------------------------------------------------------

def test_GBK与Big5仍判得对(tmp_path):
    gbk = _write(tmp_path, "简.txt", _gbk_text().encode("gb18030"))
    big5 = _write(tmp_path, "繁.txt", _big5_text().encode("big5"))

    assert pipeline._detect_encoding(gbk) in ("gb18030", "gbk")
    assert pipeline._detect_encoding(big5) in ("big5", "big5hkscs")
    assert pipeline.decode_file(gbk)[0].startswith("第一章")
    assert pipeline.decode_file(big5)[0].startswith("第一章")
    assert pipeline.decode_file(big5)[1]["undecodable"] == 0


def test_大文件样本切在字符中间仍判UTF8(tmp_path):
    """>256 KiB 的中文 UTF-8：采样窗口按字节切，切点会落在多字节字符中间 ——
    整本严格解码必须成功、不得有坏字节。"""
    body = "第一章 起\n" + "风" * 60000 + "\n第二章 落\n" + "雨" * 60000
    p = _write(tmp_path, "大书.txt", body.encode("utf-8"))
    raw = p.read_bytes()
    assert len(raw) > 256 * 1024
    assert pipeline._detect_encoding(p) == "utf-8"

    decoded, info = pipeline.decode_file(p)
    assert decoded.startswith("第一章") and info["undecodable"] == 0


def test_ASCII前言的中文大书仍判得出(tmp_path):
    """开头是英文版权页（纯 ASCII、超过采样窗口）⇒ 必须往后看，否则整本 GBK 判成 UTF-8。"""
    head = "Copyright (c) 2026 Nobody. All rights reserved.\n" * 20000
    p = _write(tmp_path, "前言.txt", (head + _gbk_text() * 40).encode("gb18030"))
    assert len(head.encode()) > 256 * 1024, "前置条件：必须是超过采样窗口的纯 ASCII 开头"

    assert pipeline._detect_encoding(p) in ("gb18030", "gbk")
    assert pipeline.decode_file(p)[1]["undecodable"] == 0


# ---------------------------------------------------------------------------
# 3. **绝不静默丢字节**（老实现 errors="ignore" ⇒ 坏字节无声消失、位置全错）
# ---------------------------------------------------------------------------

def _gbk_with_one_bad_byte() -> tuple[bytes, str]:
    """主体合法 GBK、正中间插一个 gb18030 非法字节（``0xFF`` 不是合法首字节）。"""
    good = _text()
    raw = good.encode("gb18030")
    mid = len(raw) // 2
    return raw[:mid] + b"\xff" + raw[mid:], good


def test_坏字节不再静默丢弃_计数可断言(tmp_path):
    bad, good = _gbk_with_one_bad_byte()
    p = _write(tmp_path, "夹坏字节.txt", bad)

    text, info = pipeline.decode_file(p)

    # ① 文本仍然读得出（坏字节前后都是正常中文）
    assert "正文内容在这里" in text
    # ② 有**可观察**的「无法解码」记录（计数 + 位置）
    assert info["undecodable"] >= 1, info
    assert info["positions"], f"没记下坏字节位置：{info}"
    # ③ **不是静默变短**：坏字节被 U+FFFD 顶上，其余一字不差
    assert text.count("\ufffd") == 1, text[:80]
    assert text.replace("\ufffd", "") == good
    assert len(text) == len(good) + 1


def test_坏字节_端到端仍可读且如实上报(client, auth_headers, default_root):  # noqa: ARG001
    bad, _good = _gbk_with_one_bad_byte()
    _write(default_root, "夹坏字节.txt", bad)
    library.invalidate()
    books = [b for b in library.books() if b["name"] == "夹坏字节.txt"]
    assert books, "扫描没找到 夹坏字节.txt"
    bid = books[0]["id"]

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    assert _flat_chapters(detail), "夹了坏字节也必须能列出目录"

    body = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers).json()
    assert "正文内容在这里" in body["html"], f"正文读不出：{body['html'][:200]!r}"
    # 「有 N 字节解不出」这件事必须**随正文一起**带给前端（不是只有服务端日志里才有）
    te = body.get("text_encoding")
    assert te and te["undecodable"] >= 1, f"没如实上报无法解码：{body.get('text_encoding')}"


# ---------------------------------------------------------------------------
# 4. 编码判据版本升级 ⇒ 派生件重读重切（对齐既有 `test_编码判据升级会重读重切`）
# ---------------------------------------------------------------------------

def test_编码判据升到2会重读重切(tmp_path, monkeypatch):
    p = pathlib.Path(tmp_path) / "编码升级.txt"
    p.write_text("第1章 甲\n" + "甲。" * 100 + "\n第2章 乙\n" + "乙。" * 100, encoding="utf-8")
    book = {"id": "lib$enc89", "title": "编码升级", "author": ""}

    assert txtcache.derived_epub(book, path=p) is not None, "前置失败：这本该转得动"
    assert txtcache.ENC_RULE_VERSION == 2, "本期应把编码判据版本升到 2"
    st = txtcache._read_state(txtcache._cache_dir(book["id"]))
    assert st["enc_rule"] == txtcache.ENC_RULE_VERSION and st.get("encoding") == "utf-8", st

    calls: list = []
    real = detect.detect_chapters_cfg

    def _spy(text, cfg=None, merge=None):       # noqa: ANN001
        calls.append(1)
        return real(text, cfg, merge)

    monkeypatch.setattr(detect, "detect_chapters_cfg", _spy)

    # ① 版本没变 ⇒ 源指纹没变就命中缓存，连检测都不重跑
    assert txtcache.derived_epub(book, path=p) is not None
    assert not calls, "源指纹没变却重切了"

    # ② 版本 +1 ⇒ 派生件与切分缓存都得失效、重读重切重转
    monkeypatch.setattr(txtcache, "ENC_RULE_VERSION", txtcache.ENC_RULE_VERSION + 1)
    assert txtcache.derived_epub(book, path=p) is not None, "编码判据版本变了，派生件没重建"
    assert calls, "编码判据版本变了，切分仍取到旧结果"
    assert txtcache._read_state(txtcache._cache_dir(book["id"]))["enc_rule"] == \
        txtcache.ENC_RULE_VERSION, "重建后该把新版本写进 state"
