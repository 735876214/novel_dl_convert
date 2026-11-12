"""zip 条目上限：**重写 / 复制路径也必须过闸**（第 292 期）。

第 137 / 242 期把「读书籍本体条目」收敛到 `zipkind.read_entry`（解压后大小上限
`comics.MAX_ENTRY_BYTES`），但**第 292 期发现三处重写 / 复制循环仍在裸 `zin.read()`**：

- `core/publish.py` 的「去音频副本」：container / OPF / 每个被复制的条目；
- `core/epub_update.py` 的「追加章节」：每个未被替换的条目；
- `core/kepub.py` 的「导出 KEPUB」：每个条目。

它们绕过上限 ⇒ 出版 / 追更 / 导出**一本恶意 EPUB** 就能把内存吃光（而扫描侧的
`fileops._write_epub` 早就按同一判据流式读了 —— 这三处是漏网）。

这里用**缩小上限**的方式钉行为（不真的造 128 MB 炸弹）：
`monkeypatch comics.MAX_ENTRY_BYTES = 1024`，再给一份 2 KB 的条目 ⇒ 三条路径都必须抛
`comics.EntryTooLarge`，且不留下半截目标文件。
"""
from __future__ import annotations

import zipfile

import pytest

from novelforge.core import comics, epub_update, kepub, publish


def _epub(path, big_size: int = 2048):
    """最小可解析 EPUB（container/OPF 齐全），外加一个指定大小的条目。"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles>'
            '<rootfile full-path="content.opf"/></rootfiles></container>')
        z.writestr(
            "content.opf",
            '<?xml version="1.0"?><package><metadata/><manifest/><spine/></package>')
        z.writestr("big.bin", b"x" * big_size)
    return path


@pytest.fixture()
def small_cap(monkeypatch):
    monkeypatch.setattr(comics, "MAX_ENTRY_BYTES", 1024)


def test_kepub_导出过条目上限(tmp_path, small_cap) -> None:
    src = _epub(tmp_path / "a.epub")
    dest = tmp_path / "a.kepub.epub"
    with pytest.raises(comics.EntryTooLarge):
        kepub.export_kepub(src, dest)
    assert not dest.exists(), "失败后不该留下目标文件"


def test_epub_追加章节过条目上限(tmp_path, small_cap) -> None:
    src = _epub(tmp_path / "b.epub")
    dst = tmp_path / "b-out.epub"
    with pytest.raises(comics.EntryTooLarge):
        epub_update.copy_with_extra(src, dst)
    assert not dst.exists()


def test_去音频副本过条目上限(tmp_path, small_cap) -> None:
    src = _epub(tmp_path / "c.epub")
    dst = tmp_path / "c-out.epub"
    with pytest.raises(comics.EntryTooLarge):
        publish.export_deaudio_epub(src, dst, [])
    assert not dst.exists()


def test_正常小书仍能导出_kepub(tmp_path) -> None:
    """只加闸、不误伤：正常大小的书照样能导出。"""
    src = _epub(tmp_path / "d.epub", big_size=16)
    dest = tmp_path / "d.kepub.epub"
    kepub.export_kepub(src, dest)
    assert dest.is_file()
    with zipfile.ZipFile(dest) as z:
        assert "META-INF/encryption.xml" in z.namelist()
