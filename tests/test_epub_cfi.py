"""第 54 期：EPUB CFI 精确阅读位置的契约测试。

钉住四件事：
1. **CFI 往返不变量**：``cfi_for_position`` → ``position_from_cfi`` 对任意
   (章, 偏移)（含越界被夹到末端）必须回到原值 —— 这是「保存 → 恢复」的根基。
2. **KOReader 兼容层**：``to_nf`` 认 ``epubcfi(...)``（取 spine 步当章序号）、
   XPointer / 页码字符串行为不变；``from_nf`` 刻意维持章首 XPointer（下发真 CFI
   会破坏 KOReader 的解析，见 koreader.from_nf 的注释）。
3. **progress.cfi 的来源纪律**：CFI 只由 NF 阅读器进度写入（接口带 offset ⇒ 服务端
   生成）；**不带 offset 的写入一律清空 cfi**（KOReader / Komga / 完成标记等来源
   改了章序号，旧 CFI 还挂在旧章就是矛盾行）。
4. **端点往返**：PUT 带 offset → GET 返回 cfi + 反解 offset；不换算不了时保存
   仍成功（cfi 为空）—— 精确坐标是增强，绝不是保存进度的前置条件。
"""
import pathlib

import pytest

from novelforge.core import db, epub_builder, epub_cfi, koreader, library

_META = {"title": "CFI测试书", "author": "测试者", "language": "zh"}
_CHAPTERS = [
    {"title": "第一章", "body_html": "<p>这是第一章的正文，用来测试字符偏移的往返映射。</p><p>第二段落。</p>"},
    {"title": "第二章", "body_html": "<p>" + "长" * 200 + "</p>"},
    {"title": "第三章", "body_html": "<p>&nbsp;实体与<b>加粗</b>混排文本。</p>"},
]


@pytest.fixture
def real_epub(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "book.epub"
    epub_builder.build_epub(dict(_META), [dict(c) for c in _CHAPTERS], str(p))
    return p


def _total_chars(path: pathlib.Path, spine_index: int) -> int:
    body = epub_cfi._body_of_doc(path, spine_index)
    assert body is not None, "前置失败：这一章应当解析得出 body"
    return sum(len(c[2]) for c in epub_cfi._chunks(body))


# ---------------------------------------------------------------------------
# 1. 往返不变量
# ---------------------------------------------------------------------------

def test_CFI往返不变量(real_epub):
    # epub_builder 的 spine[0] 是 nav 页，章节从 1 开始
    for idx in (1, 2, 3):
        total = _total_chars(real_epub, idx)
        for off in (0, 1, 5, 18, total - 1, total, total + 7):
            cfi = epub_cfi.cfi_for_position(real_epub, idx, off)
            assert cfi.startswith("epubcfi(") and cfi.endswith(")")
            back = epub_cfi.position_from_cfi(real_epub, cfi)
            expect = min(max(0, off), total)
            assert back == (idx, expect), (idx, off, cfi, back, expect)


def test_CFI生成是确定性的(real_epub):
    assert (epub_cfi.cfi_for_position(real_epub, 1, 7)
            == epub_cfi.cfi_for_position(real_epub, 1, 7))


def test_CFI混排实体与加粗也可往返(real_epub):
    # 第三章有 &nbsp; 实体与 <b> 加粗 —— 解析口径对这类内容不能退化
    total = _total_chars(real_epub, 3)
    assert total > 5, "前置失败：第三章应有可见文本"
    cfi = epub_cfi.cfi_for_position(real_epub, 3, total - 2)
    assert epub_cfi.position_from_cfi(real_epub, cfi) == (3, total - 2)


# ---------------------------------------------------------------------------
# 2. 坏输入与越界
# ---------------------------------------------------------------------------

def test_坏输入一律安全回落(real_epub):
    assert epub_cfi.cfi_for_position(real_epub, 999, 0) == "", "spine 越界 ⇒ 空串"
    assert epub_cfi.position_from_cfi(real_epub, "garbage") is None
    assert epub_cfi.position_from_cfi(real_epub, "") is None
    assert epub_cfi.position_from_cfi(real_epub, "epubcfi(/6/99!/4/1:0)") is None
    assert epub_cfi.position_from_cfi(real_epub, None) is None
    assert epub_cfi.locator_from_cfi("garbage") == -1
    assert epub_cfi.cfi_to_xpointer("garbage") == ""


# ---------------------------------------------------------------------------
# 3. KOReader 兼容层
# ---------------------------------------------------------------------------

def test_兼容层取DocFragment序号():
    assert epub_cfi.locator_from_cfi("epubcfi(/6/4!/4/2/1:0)") == 1   # spine 1
    assert epub_cfi.cfi_to_xpointer("epubcfi(/6/4!/4/2/1:0)") == "/body/DocFragment[2]/text().0"


def test_to_nf认CFI取章序号():
    loc, pct = koreader.to_nf({"progress": "epubcfi(/6/8!/4/2/1:0)", "percentage": 0.42})
    assert loc == 3
    assert pct == pytest.approx(42.0)


def test_to_nf对XPointer与页码行为不变():
    # 既有口径：XPointer 的 DocFragment[N] ⇒ locator N-1；页码字符串 ⇒ 页码 - 1
    assert koreader.to_nf({"progress": "/body/DocFragment[20]/body/p[22]/img.0",
                           "percentage": 0.5})[0] == 19
    assert koreader.to_nf({"progress": "7", "percentage": 0.0})[0] == 6
    assert koreader.to_nf({"progress": "", "percentage": 0.3}) == (0, 30.0)


def test_from_nf维持章首XPointer不下发CFI():
    """CFI 不下发给 KOReader：kosync 只按 XPointer 定位 EPUB（取舍见 from_nf 注释）。"""
    body = koreader.from_nf({"format": "EPUB"},
                            {"locator": 4, "percent": 66.6, "cfi": "epubcfi(/6/10!/4/1:0)",
                             "updated_at": 123.0})
    assert body["progress"] == "/body/DocFragment[5]/text().0"
    assert "epubcfi" not in body["progress"]
    assert body["percentage"] == pytest.approx(0.666)
    assert body["timestamp"] == 123


# ---------------------------------------------------------------------------
# 4. progress.cfi 的来源纪律（db 层）
# ---------------------------------------------------------------------------

def test_进度cfi往返与非NF来源清空(isolated):  # noqa: ARG001
    db.set_progress("lib$x", 3, 42.0, "epubcfi(/6/8!/4/1:0)")
    row = db.get_progress("lib$x")
    assert row["locator"] == 3 and row["cfi"] == "epubcfi(/6/8!/4/1:0)"

    # 不带 cfi 的写入（KOReader / Komga / 完成标记都走这个形态）必须清掉精确坐标：
    # 章序号已变，旧 CFI 还挂在旧章就是矛盾行，恢复会跳错位置。
    db.set_progress("lib$x", 5, 60.0)
    row = db.get_progress("lib$x")
    assert row["locator"] == 5 and row["cfi"] == ""
    assert db.get_progress("lib$none") is None


# ---------------------------------------------------------------------------
# 5. 端点往返（真 EPUB）
# ---------------------------------------------------------------------------

def _scan_real_epub(root: pathlib.Path) -> str:
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True)   # 隔离夹具不预建目录，ebooklib 会静默写失败
    epub_builder.build_epub(dict(_META), [dict(c) for c in _CHAPTERS],
                            str(root / "cfi-book.epub"))
    assert (root / "cfi-book.epub").exists(), "前置失败：EPUB 没写出来（多半是目录没建）"
    library.invalidate()
    books = library.books()
    assert books, "前置失败：扫描应当收进这本真 EPUB"
    return books[0]["id"]


def test_端点offset进cfi出offset(client, auth_headers, default_root):  # noqa: ARG001
    bid = _scan_real_epub(default_root)

    r = client.put(f"/api/books/{bid}/progress", headers=auth_headers,
                   json={"locator": 1, "percent": 12.5, "offset": 10})
    assert r.status_code == 200, r.text

    body = client.get(f"/api/books/{bid}/progress", headers=auth_headers).json()
    assert body["locator"] == 1 and body["percent"] == pytest.approx(12.5)
    assert body["cfi"].startswith("epubcfi(/6/4!"), body["cfi"]
    assert body["offset"] == 10, "服务端反解的偏移必须与保存时同值（同坐标系）"


def test_端点不带offset仍是旧行为且清掉旧cfi(client, auth_headers, default_root):  # noqa: ARG001
    bid = _scan_real_epub(default_root)
    client.put(f"/api/books/{bid}/progress", headers=auth_headers,
               json={"locator": 1, "percent": 12.5, "offset": 10})
    client.put(f"/api/books/{bid}/progress", headers=auth_headers,
               json={"locator": 2, "percent": 30.0})

    body = client.get(f"/api/books/{bid}/progress", headers=auth_headers).json()
    assert body["locator"] == 2
    assert body["cfi"] == "" and "offset" not in body, "非 NF 来源的写入必须清精确坐标"


def test_端点offset坏值拒400不碰进度(client, auth_headers, default_root):  # noqa: ARG001
    bid = _scan_real_epub(default_root)
    r = client.put(f"/api/books/{bid}/progress", headers=auth_headers,
                   json={"locator": 1, "percent": 12.5, "offset": "abc"})
    assert r.status_code == 400
    # 进度本体不许被顺手写坏（校验先于任何落库）
    body = client.get(f"/api/books/{bid}/progress", headers=auth_headers).json()
    assert body["locator"] == 0 and body["percent"] == 0
