"""第 55 期：TXT 阅读契约（派生 EPUB 优先 / 原生分章兜底）。

计划「两者都要」的落地口径：

- **转得动** ⇒ 用派生 EPUB 阅读（目录 / 批注 / CFI / 进度全部免费复用 EPUB 全链路），
  派生件落 `CACHE_DIR/txt-epub/<book_id>/`（派生缓存，**不进库、不落成品目录**）；
- **转不动**（超大 / 编码坏 / 构建失败）⇒ 回落**原生分章**，目录与内容照样能出；
- **形态锁定**：源文件指纹不变 ⇒ 两次请求必须给同一形态的章节树
  （两条路线索引空间不同，中途换形态会让章节号整体漂移、批注跳错章）。
"""
import pathlib

import pytest

from novelforge import config
from novelforge.core import detect, library, pipeline, txtcache


@pytest.fixture(autouse=True)
def _cache_dir_in_tmp(tmp_path, monkeypatch):
    """CACHE_DIR 默认指向真实配置目录；派生缓存必须落进用例专属目录。"""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    txtcache._SPLIT_CACHE.clear()


def _write_txt(root, name: str, chapters: int = 4) -> pathlib.Path:
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    for i in range(1, chapters + 1):
        # 正文**刻意不含「第 N 章」字样**：第 62 期起分章已按行首锚定（正文中间提到章号
        # 不再算边界，见 test_detect_chapters），这里保持原样只是为了让章节数一眼可数。
        parts.append(f"第{i}章 标题{i}\n" + "正文内容在这里，写长一点。" * 25)
    p.write_text("\n".join(parts), encoding="utf-8")
    return p


def _scan(root, name: str = "讲义.txt") -> str:
    _write_txt(root, name)
    library.invalidate()
    books = [b for b in library.books() if b["name"] == name]
    assert books, f"扫描没找到 {name}"
    return books[0]["id"]


def _flat_chapters(detail: dict) -> list:
    return [c for v in detail["chapters"] for c in v["chapters"]]


def test_TXT_详情下发章节树且可读(client, auth_headers, default_root):  # noqa: ARG001
    bid = _scan(default_root)

    r = client.get(f"/api/books/{bid}", headers=auth_headers)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert str(detail["format"]).upper() == "TXT"
    chaps = _flat_chapters(detail)
    assert len(chaps) >= 3, f"TXT 该有目录：{detail.get('chapters')}"

    # 派生件落在缓存目录，**不落库根**（成品目录纪律：不凭空多出第二个书目条目）
    assert txtcache._cache_dir(bid).exists()
    assert not (pathlib.Path(default_root) / txtcache.EPUB_NAME).exists()
    assert txtcache._cache_dir(bid) != pathlib.Path(default_root)

    # 派生 EPUB 用 nav=False 组装 ⇒ 章节 index 0 基、与原生分章索引空间对齐
    assert [c["index"] for c in chaps] == list(range(len(chaps))), chaps

    # 请求**详情下发的 index**（客户端也只认这些值）
    ch = client.get(f"/api/books/{bid}/chapter/{chaps[0]['index']}", headers=auth_headers)
    assert ch.status_code == 200, ch.text
    assert "正文" in ch.json()["html"]


def test_转不动时回落原生分章且仍可读(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(txtcache, "SOURCE_MAX_BYTES", 1)   # 任何 TXT 都算「超大」
    bid = _scan(default_root, "超大书.txt")

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    chaps = _flat_chapters(detail)
    assert len(chaps) >= 3, "转换失败也必须能列出原生分章目录"

    ch = client.get(f"/api/books/{bid}/chapter/1", headers=auth_headers)
    assert ch.status_code == 200, ch.text
    body = ch.json()
    assert body["index"] == 1 and "正文" in body["html"]

    # 失败路线不产出派生件（也没有半成品残留）
    assert not (txtcache._cache_dir(bid) / txtcache.EPUB_NAME).exists()
    assert not (txtcache._cache_dir(bid) / (txtcache.EPUB_NAME + ".tmp")).exists()


def test_形态锁定_源不变两次请求同一章节树(client, auth_headers, default_root):  # noqa: ARG001
    bid = _scan(default_root, "锁定.txt")

    first = _flat_chapters(client.get(f"/api/books/{bid}", headers=auth_headers).json())
    second = _flat_chapters(client.get(f"/api/books/{bid}", headers=auth_headers).json())

    assert first == second, "源没变时形态必须稳定（索引空间不能漂）"


def test_源变更后重建派生件(client, auth_headers, default_root):  # noqa: ARG001
    bid = _scan(default_root, "更新.txt")
    client.get(f"/api/books/{bid}", headers=auth_headers)          # 触发首次派生
    epub = txtcache._cache_dir(bid) / txtcache.EPUB_NAME
    assert epub.exists()
    before = len(_flat_chapters(client.get(f"/api/books/{bid}", headers=auth_headers).json()))

    # 源文件加一章（mtime/size 变）⇒ 指纹失效 ⇒ 重建
    p = pathlib.Path(default_root) / "更新.txt"
    p.write_text(p.read_text(encoding="utf-8") + "\n第99章 新增\n" + "新增正文。" * 25,
                 encoding="utf-8")
    library.invalidate()

    after = _flat_chapters(client.get(f"/api/books/{bid}", headers=auth_headers).json())
    assert len(after) > before, "源变了必须重建（否则读到旧章节）"


def test_分章规则升级会重切重转并留痕(tmp_path, monkeypatch):
    """第 62 期：源文件**一个字节没动**，但分章规则升级了 ⇒ 派生件与切分都必须重来。

    只比源指纹是不够的 —— 旧派生件会一直命中并原样返回，**改了规则看不见效果**
    （用户升级完版本，目录还是老的，且不报任何错）。两份缓存都得带上版本号：
    派生件在 `state.json` 里比，切分结果在 `_SPLIT_CACHE` 的键里比 ——
    只改前者的结果是「重新组装了一本拿旧规则切的 EPUB」，白忙。
    """
    p = pathlib.Path(tmp_path) / "规则升级.txt"
    p.write_text("第1章 甲\n" + "甲。" * 100 + "\n第2章 乙\n" + "乙。" * 100, encoding="utf-8")
    book = {"id": "lib$rulever", "title": "规则升级", "author": ""}

    def _count() -> int:
        vols = txtcache.native_chapters(book, path=p)
        return sum(len(v["chapters"]) for v in vols)

    assert txtcache.derived_epub(book, path=p) is not None, "前置失败：这本该转得动"
    assert _count() == 2
    assert txtcache._read_state(txtcache._cache_dir(book["id"]))["rule"] == txtcache.RULE_VERSION

    # 「新规则」= 多切一章（模拟规则升级后切分结果变了）
    real = detect.detect_chapters_cfg

    def _new_rule(text, cfg=None, merge=None):   # noqa: ANN001
        return real(text, cfg, merge) + [{"title": "第99章", "body": "新规则多切的一章", "vol": "正文"}]

    logged: list = []
    monkeypatch.setattr(txtcache, "_log_rule_rebuild", logged.append)
    monkeypatch.setattr(detect, "detect_chapters_cfg", _new_rule)

    # ① 版本没变 ⇒ 源指纹没变就命中缓存，连检测都不重跑（这正是缓存存在的意义）
    assert txtcache.derived_epub(book, path=p) is not None
    assert _count() == 2 and not logged

    # ② 版本 +1 ⇒ 必须重切（切分缓存也得失效）、重转，并留一条痕
    monkeypatch.setattr(txtcache, "RULE_VERSION", txtcache.RULE_VERSION + 1)
    assert txtcache.derived_epub(book, path=p) is not None, "规则版本变了，派生件没重建"
    assert logged, "规则升级导致的重建必须留痕（活动日志）"
    assert _count() == 3, "规则版本变了，切分仍取到旧规则的结果"


# ---------------------------------------------------------------------------
# 编码探测（第 62 期 D3）：**能解码 ≠ 解对了**
# ---------------------------------------------------------------------------

#: 繁体样本：**标点是关键**。「，」在 Big5 是 A141、在 GBK 是 A3AC，拿错编码解出来
#: 的那一片全是不成字的怪符号；只含汉字是分不出两种编码的。
_CN_NUM = "一二三四五六七八九十"


def _sample_text(body: str, chapters: int = 4) -> str:
    parts = []
    for i in range(1, chapters + 1):
        parts.append(f"第{_CN_NUM[i - 1]}章 第{_CN_NUM[i - 1]}節\n" + body * 20)
    return "\n".join(parts)


_BIG5_TEXT = _sample_text("這是一本繁體書，內容用 Big5 編碼寫成。他說：「風起了。」\n")
_GBK_TEXT = _sample_text("这是一本简体书，用 GBK 编码写成。他说：「风起了。」\n")


def _enc_file(root, name: str, text: str, enc: str) -> pathlib.Path:
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode(enc))
    return p


def test_繁体Big5不再被当成GB18030解成乱码(tmp_path):
    """老实现里 ``big5`` 是**死分支**：GB18030 能解码绝大多数 Big5 字节序列而不抛异常，
    于是繁体书被判成 GB18030、解出一整本乱码却「成功」，调用方再叠加 ``errors="ignore"``，
    连失败兜底都不触发 —— 读者看到满屏怪字，而不是「这本书打不开」。
    """
    raw = _BIG5_TEXT.encode("big5")
    # 前置条件：这条字节序列在 GB18030 下**确实不抛异常**（否则老实现早就落到 big5 了，
    # 本用例也就失去了意义）—— 缺陷成立的前提，得钉住。
    assert raw.decode("gb18030")            # noqa: B018 —— 只验证「不抛异常」
    p = _enc_file(tmp_path, "繁体.txt", _BIG5_TEXT, "big5")

    enc = pipeline._detect_encoding(p)
    assert enc in ("big5", "big5hkscs"), f"繁体书被判成 {enc}"
    assert p.read_text(encoding=enc, errors="ignore").startswith("第一章 第一節")


def test_简体GBK仍判GB18030_不矫枉过正(tmp_path):
    """反向也要成立：放宽判据不能把简体书推到 Big5 去。"""
    p = _enc_file(tmp_path, "简体.txt", _GBK_TEXT, "gb18030")
    enc = pipeline._detect_encoding(p)
    assert enc in ("gb18030", "gbk"), f"简体书被判成 {enc}"
    assert p.read_text(encoding=enc, errors="ignore").startswith("第一章 第一節")


def test_UTF8与带BOM依旧自证(tmp_path):
    """UTF-8 是**自证**的（非 UTF-8 字节几乎必然解失败），不该被后面的打分环节动到。"""
    plain = _enc_file(tmp_path, "utf8.txt", _GBK_TEXT, "utf-8")
    bom = _enc_file(tmp_path, "bom.txt", _GBK_TEXT, "utf-8-sig")
    assert pipeline._detect_encoding(plain) == "utf-8"
    assert pipeline._detect_encoding(bom) == "utf-8-sig"


def test_纯ASCII开头的中文书仍能判出编码(tmp_path):
    """开头若是英文前言 / 版权页（纯 ASCII），窗口内判不出中文编码 —— 必须往后看，
    否则整本 GBK 会被判成 UTF-8，而**错判不会报错**，只会满屏乱码。"""
    head = "Copyright (c) 2026 Nobody.\n" * 400            # ≈ 10 KB ASCII 开头
    p = _enc_file(tmp_path, "带前言.txt", head + _GBK_TEXT * 40, "gb18030")
    assert len(head.encode()) < 256 * 1024, "前置条件：ASCII 开头必须落在首个采样窗口内"
    enc = pipeline._detect_encoding(p)
    assert enc in ("gb18030", "gbk"), f"被英文前言带偏成 {enc}"


def test_繁体Big5_TXT_端到端读出来不是乱码(client, auth_headers, default_root):  # noqa: ARG001
    """从磁盘走到阅读器：详情能列章、正文是**真繁体字**（派生 EPUB 与原生分章两条路线
    共用同一个编码探测，任一条乱码都算失败）。"""
    _enc_file(default_root, "繁體書.txt", _BIG5_TEXT, "big5")
    library.invalidate()
    books = [b for b in library.books() if b["name"] == "繁體書.txt"]
    assert books, "扫描没找到 繁體書.txt"
    bid = books[0]["id"]

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    chaps = _flat_chapters(detail)
    assert len(chaps) >= 3, f"繁体书也该列出目录：{detail.get('chapters')}"

    html = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers).json()["html"]
    assert "繁體" in html or "起風" in html, f"正文全是乱码：{html[:200]!r}"
