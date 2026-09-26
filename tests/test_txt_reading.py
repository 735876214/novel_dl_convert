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
from novelforge.core import library, txtcache


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
        # ⚠️ 正文**刻意不含「第 N 章」字样**：分章正则不锚定行首，正文里出现章标记
        # 也会被当成边界（与出版链路同口径，见 test_detect_chapters 的对应契约）。
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


def test_非_epub_非_txt_依旧拒绝在线阅读(client, auth_headers, default_root):  # noqa: ARG001
    p = pathlib.Path(default_root) / "样张.pdf"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4 fake")
    library.invalidate()
    books = [b for b in library.books() if b["name"] == "样张.pdf"]
    assert books, "前置失败：PDF 应当在电子书库里"
    bid = books[0]["id"]

    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 400, r.text
