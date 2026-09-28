"""第 55 期：TXT 阅读契约（派生 EPUB 优先 / 原生分章兜底）。

计划「两者都要」的落地口径：

- **转得动** ⇒ 用派生 EPUB 阅读（目录 / 批注 / CFI / 进度全部免费复用 EPUB 全链路），
  派生件落 `CACHE_DIR/txt-epub/<book_id>/`（派生缓存，**不进库、不落成品目录**）；
- **转不动**（超大 / 编码坏 / 构建失败）⇒ 回落**原生分章**，目录与内容照样能出；
- **形态锁定**：源文件指纹不变 ⇒ 两次请求必须给同一形态的章节树
  （两条路线索引空间不同，中途换形态会让章节号整体漂移、批注跳错章）。

**第 72 期**：派生缓存的有效性多一个分量 —— **编码判据版本**（`txtcache.ENC_RULE_VERSION`）。
正文是从源文件**解码**出来的，判据改了而源文件一个字节没动时，已缓存的正文（可能是乱码）
必须失效，否则「改了判据看不见效果」（与分章规则版本同一个道理）。同一期还给
「正文读不出」补了一条活动日志 —— 此前那条路整条是静默的。
"""
import json
import pathlib

import pytest

from novelforge import config
from novelforge.core import activity_log, detect, library, pipeline, txtcache


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


def test_ASCII前言的中文大书不再被判成非UTF8(tmp_path):
    """第 72 期缺陷 A2：**中段采样的接缝**。

    `_sample_bytes` 在「开头纯 ASCII」时补采一段中段，起点是 `size // 2` —— 按字节算，
    多半落在字符中间。两段样本**直接拼接**，接缝处就凭空多出一个非法字节（续字节不能
    当字符的开头）。前缀判定只容忍**尾部**不完整，接缝在中间 ⇒ 照样抛错 ⇒ 一本真 UTF-8
    的书被判成 gb18030、满屏乱码且不报错 —— 与缺陷 A 同因同果，只是走另一条采样分支。

    ⚠️ 现有 `test_纯ASCII开头的中文书仍能判出编码` 的夹具约 190 KB，`size > 256 KiB`
    不成立，走不到拼接分支，所以一直没照到这里。
    """
    head = b"Copyright (c) 2026 Nobody. All rights reserved.\n" * 6800      # > 256 KiB
    body = "第一章 起\n" + "风" * 60000 + "\n第二章 落\n" + "雨" * 60000
    # 微调相位：`pad` 个 ASCII 字节让 `size // 2` 落在 3 字节汉字的中间（4 次内必中）
    for pad in range(4):
        raw = head + ("x" * pad + body).encode("utf-8")
        if raw[len(raw) // 2] & 0xC0 == 0x80:
            break
    else:                                                   # pragma: no cover
        pytest.fail("构造不出「中段起点落在字符中间」的夹具")

    p = tmp_path / "前言书.txt"
    p.write_bytes(raw)
    # 前置条件：头部纯 ASCII 且 > 256 KiB ⇒ 必然走到「头 + 中段」的拼接分支
    assert max(raw[:256 * 1024]) < 0x80
    assert pipeline._utf8_prefix_ok(raw[:256 * 1024]), "前置：头部本身是合法 UTF-8 前缀"

    enc = pipeline._detect_encoding(p)

    assert enc == "utf-8", f"ASCII 前言的中文大书被判成 {enc}"
    assert p.read_text(encoding=enc, errors="ignore").startswith("Copyright")


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


# ---------------------------------------------------------------------------
# 第 72 期：采样窗口截断（缺陷 A）与长章书降级（缺陷 B）的合流点
# ---------------------------------------------------------------------------

def _big_utf8(chapters: int = 4, reps: int = 2000) -> str:
    """**大于 256 KiB** 的中文 UTF-8 夹具 —— 现有夹具都远小于采样窗口，照不到缺陷 A。

    正文用 3 字节汉字堆够体积，这样 262,144 这个字节切点才**有机会**落在字符中间
    （实测本夹具正好落在：见 `test_大文件样本切在字符中间仍判UTF8` 的前置断言）。
    """
    return "\n".join(f"第{_CN_NUM[i - 1]}章 第{_CN_NUM[i - 1]}節\n"
                     + "这是一本简体书，用 UTF-8 编码写成。他说：「风起了。」\n" * reps
                     for i in range(1, chapters + 1))


def test_大文件样本切在字符中间仍判UTF8(tmp_path):
    """第 72 期缺陷 A：采样窗口按**字节**截 256 KiB，切点可能落在多字节字符中间。

    老实现拿整段样本 `decode("utf-8-sig")` 自证 —— 那是**严格**解码，把「尾部被切断」
    当成了「不是 UTF-8」。UTF-8 汉字 3 字节 ⇒ 任意切点有 2/3 概率落在字符中间，
    **>256 KiB 的中文 TXT 成片中招**：判成 gb18030、解出满屏乱码，全程不报错
    （调用方还叠加 `errors="ignore"`，连失败兜底都不触发）。
    """
    p = _enc_file(tmp_path, "大书.txt", _big_utf8(), "utf-8")
    data = p.read_bytes()
    # 前置条件（否则用例失去意义，沿用 test_繁体Big5… 钉前置的写法）：
    # ① 必须真的超过采样窗口；② 切点必须落在续字节上；③ 老判据在这份样本上确实失败
    assert len(data) > 256 * 1024, len(data)
    assert data[256 * 1024] & 0xC0 == 0x80, "切点必须落在字符中间（否则老实现也不会判错）"
    with pytest.raises(UnicodeDecodeError):
        data[:256 * 1024].decode("utf-8-sig")

    enc = pipeline._detect_encoding(p)

    assert enc == "utf-8", f"切在字符中间的大 UTF-8 被判成 {enc}"
    assert p.read_text(encoding=enc, errors="ignore").startswith("第一章 第一節")


def test_大文件GBK与Big5不因容错被误判成UTF8(tmp_path):
    """容错的反向边界：放宽「尾部截断」必须**只**放过合法 UTF-8 前缀 ——
    真 GBK / Big5 的样本中间就有非法字节，照样判非 UTF-8（否则是拿一种乱码换另一种）。
    """
    big = 80                       # ×80 ⇒ 337 KB / 369 KB，双双越过 256 KiB 采样窗口
    for name, text, enc in (("大简体.txt", _GBK_TEXT * big, "gb18030"),
                            ("大繁體.txt", _BIG5_TEXT * big, "big5")):
        p = _enc_file(tmp_path, name, text, enc)
        raw = p.read_bytes()
        assert len(raw) > 256 * 1024, (name, len(raw))
        assert not pipeline._utf8_prefix_ok(raw[:256 * 1024]), f"{name} 的样本不该被当成 UTF-8 前缀"

        got = pipeline._detect_encoding(p)

        want = ("gb18030", "gbk") if enc == "gb18030" else ("big5", "big5hkscs")
        assert got in want, f"{name} 被判成 {got}"
        assert p.read_text(encoding=got, errors="ignore").startswith("第一章 第一節")


def test_大UTF8长章书_端到端读出来是正确中文(client, auth_headers, default_root):  # noqa: ARG001
    """**用户报告的那种书**从磁盘走到阅读器：>256 KiB 的中文 UTF-8 长章书。

    两个缺陷在这里合流（编码判错 ⇒ 正文乱码；分章降级 ⇒ 满屏空章），任何一处没修
    这条用例都会红：章数、正文内容、派生件状态三个断言分别钉住不同环节。
    """
    # 4 章 × 2000 行 ≈ 616 KB，平均 ~15 万字/章 ⇒ 密度判据必不通过（长章书）
    _enc_file(default_root, "大書.txt", _big_utf8(), "utf-8")
    library.invalidate()
    books = [b for b in library.books() if b["name"] == "大書.txt"]
    assert books, "扫描没找到 大書.txt"
    bid = books[0]["id"]

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    chaps = _flat_chapters(detail)
    assert len(chaps) == 4, f"长章书被降级了：详情下发 {len(chaps)} 章"

    html = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers).json()["html"]
    assert "这是一本简体书" in html, f"正文全是乱码：{html[:200]!r}"
    assert "�" not in html, "正文里有替换符（编码解错了）"

    # 派生件建成 ok ⇒ 形态稳定在 EPUB 路线（此前正文读不出 ⇒ failed ⇒ 永远走原生兜底）
    state = txtcache._read_state(txtcache._cache_dir(bid))
    assert state.get("status") == "ok", state
    assert state.get("chapters") == 4, state


def test_编码判据升级会重读重切(tmp_path, monkeypatch):
    """第 72 期：正文是从源文件**解码**出来的 ⇒ 编码判据变了、源文件一个字节没动时，
    已缓存的正文（可能是乱码）必须失效。只比源指纹会一直命中 —— **改了看不见效果**
    （与分章规则版本同一个道理：两份缓存都要带上这个分量）。
    """
    p = pathlib.Path(tmp_path) / "编码升级.txt"
    p.write_text("第1章 甲\n" + "甲。" * 100 + "\n第2章 乙\n" + "乙。" * 100, encoding="utf-8")
    book = {"id": "lib$encver", "title": "编码升级", "author": ""}

    assert txtcache.derived_epub(book, path=p) is not None, "前置失败：这本该转得动"
    calls: list = []
    real = detect.detect_chapters_cfg

    def _spy(text, cfg=None, merge=None):       # noqa: ANN001
        calls.append(1)
        return real(text, cfg, merge)

    monkeypatch.setattr(detect, "detect_chapters_cfg", _spy)

    # ① 版本没变 ⇒ 源指纹没变就命中缓存，连检测都不重跑（这正是缓存存在的意义）
    assert txtcache.derived_epub(book, path=p) is not None
    assert not calls, "源指纹没变却重切了"

    # ② 版本 +1 ⇒ 切分缓存与派生件都得失效、重读重切重转
    monkeypatch.setattr(txtcache, "ENC_RULE_VERSION", txtcache.ENC_RULE_VERSION + 1)
    assert txtcache.derived_epub(book, path=p) is not None, "编码判据版本变了，派生件没重建"
    assert calls, "编码判据版本变了，切分仍取到旧结果"
    assert txtcache._read_state(txtcache._cache_dir(book["id"]))["enc_rule"] == \
        txtcache.ENC_RULE_VERSION, "重建后该把新版本写进 state"


def test_老state没有enc_rule字段就重建(tmp_path):
    """**用户那本书的自愈路径**：第 72 期之前生成的 state.json 没有 `enc_rule` 字段，
    而它记的失败状态会一直粘住（「形态一经确定就锁定」）。

    「没有这个字段」本身就是失效信号 ⇒ 不命中 ⇒ 重建一次。少了这条，改完代码用户
    看到的还是老样子（state 命中失败分支直接 return None，**不报错、不重建**）。
    """
    p = pathlib.Path(tmp_path) / "老缓存.txt"
    p.write_text("第1章 甲\n" + "甲。" * 100 + "\n第2章 乙\n" + "乙。" * 100, encoding="utf-8")
    book = {"id": "lib$oldstate", "title": "老缓存", "author": ""}
    cdir = txtcache._cache_dir(book["id"])
    cdir.mkdir(parents=True, exist_ok=True)
    # 模拟第 72 期之前的产物：源指纹与分章规则都对得上，**只是没有 enc_rule**
    (cdir / txtcache.STATE_NAME).write_text(json.dumps({
        "status": "failed", "fingerprint": txtcache._fingerprint(p),
        "rule": txtcache.RULE_VERSION, "reason": "文本读不出可读内容（空文本或编码全坏）",
    }, ensure_ascii=False), encoding="utf-8")

    assert txtcache.derived_epub(book, path=p) is not None, "老 state 该被判失效并重建"

    state = txtcache._read_state(cdir)
    assert state["enc_rule"] == txtcache.ENC_RULE_VERSION, state
    assert state["status"] == "ok" and state["chapters"] == 2, state
    assert (cdir / txtcache.EPUB_NAME).exists()


@pytest.fixture
def logdir(tmp_path):
    """把活动日志目录切到临时目录，用完还原（含内存缓冲与合并缓冲）。

    ⚠️ 日志目录是**模块级全局**，而 conftest 的 `LOG_DIR` 是全会话共用的 —— 不还原、
    不清缓冲，后续用例的 `recent()` 会读到本用例的记录，且待合并条目会落到真实目录。
    """
    old = activity_log.log_dir()
    activity_log.set_dir(tmp_path)
    yield tmp_path
    activity_log.set_dir(old)
    activity_log._memory.clear()
    activity_log._pending.clear()


def test_正文读不出时留一条失败活动日志(tmp_path, logdir, monkeypatch):        # noqa: ARG001
    """第 72 期可观测性：此前这条路整条是**静默**的 —— `state.json` 里记个 failed，
    阅读器照样渲染空章（满屏标题、点进去没正文），用户在界面上拿不到任何提示。
    """
    p = pathlib.Path(tmp_path) / "空书.txt"
    p.write_text("", encoding="utf-8")          # 解出来是空串 ⇒ 守卫「读不出可读内容」触发
    book = {"id": "lib$unreadable", "title": "空书", "author": ""}

    def _mine() -> list:
        # `limit=0` = **只看内存缓冲**、不触发 jsonl 回填（回填会先清空缓冲再灌入盘上条目）；
        # 且按本书名收窄 —— 日志目录与内存缓冲是全进程共享的，同会话其他用例也会写条目。
        return [e for e in activity_log.recent(limit=0)
                if e.get("status") == activity_log.STATUS_FAIL and e.get("file") == "空书.txt"]

    assert txtcache.derived_epub(book, path=p) is None, "读不出内容时不该产出派生件"
    mine = _mine()
    assert mine, "正文读不出必须留一条失败日志（此前整条路静默）"
    assert mine[0]["action"] == activity_log.ACTION_CONVERT, mine[0]
    assert "读不出" in mine[0]["detail"], mine[0]

    # 同一条源 + 同一版判据只写一次：第二次请求走 state 命中失败分支，直接 return None。
    # 用 spy 钉「没再调」，而不是数条目 —— 合并开启时重复写也只会合并成一条，数条目没有区分力。
    calls: list = []
    real = txtcache._log_unreadable
    monkeypatch.setattr(txtcache, "_log_unreadable",
                        lambda path, err: (calls.append(1), real(path, err))[1])
    assert txtcache.derived_epub(book, path=p) is None
    assert not calls, "失败状态已落盘，第二次请求不该再写日志"
