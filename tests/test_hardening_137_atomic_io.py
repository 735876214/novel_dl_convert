"""第 137 期：落盘原子性 + 半份文件自愈的契约测试。

背景（只读审计结论）：全仓纪律「副本禁原地写（临时文件 + `Path.replace`）」此前有五套
各自为政的实现、还有几处根本没做 —— 成品用 `shutil.copy2` 直写**被扫描的库根**、
出版副本复制回退支直写、备份失败留半份 `.dump`、字体/书源/头像/PDF 页缓存直写。
后果统一是「名字合法、内容不全」的文件被扫描器 / 外部阅读器 / 下一次启动当成成品。

这些断言都是**回归护栏**：把「谁写盘」钉在 `core/atomicio.py` 一处，谁再写第二份就红。
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ---------------- 单一实现 ----------------

def test_只有一份原子落盘实现():
    """`atomicio` 是唯一实现：其它模块只许调用它，不许自己拼 `.part` + `replace`。"""
    assert "def copy_file(" in _src("novelforge/core/atomicio.py")
    assert "def write_bytes(" in _src("novelforge/core/atomicio.py")
    # 落地侧 / 入库侧 / 出版侧都收敛到它
    for rel in ("novelforge/core/landing.py", "novelforge/core/pipeline.py",
                "novelforge/core/publish.py"):
        assert "atomicio" in _src(rel), rel


def test_入库与出版不再原地复制():
    """成品直接落在**被扫描的库根**里 ⇒ copy2 中途死掉就是「半本书被当成成品索引」。"""
    for rel in ("novelforge/core/pipeline.py", "novelforge/core/publish.py"):
        text = _src(rel)
        assert "shutil.copy2(src" not in text, f"{rel}：入库/出版侧又用回原地写了"
    assert "atomicio.copy_file" in _src("novelforge/core/pipeline.py")
    assert "atomicio.copy_file" in _src("novelforge/core/publish.py")


def test_状态与凭证类写入走同一实现():
    """字体 / 书源 / 头像 / PDF 页缓存 / 派生 state：中断一次就会留下坏文件，全部原子写。"""
    for rel in ("novelforge/core/fonts.py", "novelforge/sources/store.py",
                "novelforge/core/authors.py", "novelforge/core/pdfrender.py",
                "novelforge/core/txtcache.py"):
        text = _src(rel)
        assert "atomicio.write" in text, f"{rel}：仍在直写"


# ---------------- 备份：失败不留半份 ----------------

def test_备份失败不留半份归档():
    text = _src("novelforge/core/backup.py")
    # pg_dump 的输出落临时件（`atomicio.access` 负责提交与失败清理），SQLite 走原子拷贝
    assert "atomicio.access" in text
    assert "atomicio.copy_file" in text
    # 不再有「直写最终名」的 pg_dump、也不再自己拼 `.part` / 自己写清理分支
    assert '"-f", str(dest)' not in text
    assert "shutil.copy2(" not in text
    assert "PART_SUFFIX" not in text, "临时件后缀的第二份实现（应只用 atomicio）"


def test_备份轮转不再直接删用户数据():
    """轮转是后台自动动作 ⇒ 必须移入回收站（唯一一处「非用户动作真删数据」已消除）。"""
    text = _src("novelforge/core/backup.py")
    assert "old.unlink()" not in text
    assert "publish.recycle" in text


# ---------------- 半份副本自愈 ----------------

def test_已有副本不完整会被重建():
    """`exists()` ≠ 完整：半份副本必须重建，而不是永久复用并误报 hardlink。"""
    text = _src("novelforge/core/publish.py")
    assert "_copy_complete" in text
    assert "重建半份副本" in text


def test_pdf_页缓存坏了会重渲染():
    text = _src("novelforge/core/pdfrender.py")
    # Image.open 是惰性的，必须真解一遍才知道是不是截断的 JPEG
    assert "im.load()" in text


# ---------------- 行为：实现本身 ----------------

def test_原子写落盘且不留临时件(tmp_path: pathlib.Path):
    from novelforge.core import atomicio

    target = tmp_path / "a" / "b.txt"
    atomicio.write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert not (target.parent / "b.txt.part").exists()


def test_原子写失败时清掉临时件(tmp_path: pathlib.Path, monkeypatch):
    from novelforge.core import atomicio

    target = tmp_path / "c.bin"

    real = pathlib.Path.write_bytes

    def boom(self, data):
        real(self, b"half")                # 先落一半，再炸
        raise OSError("disk full")

    monkeypatch.setattr(pathlib.Path, "write_bytes", boom)
    with pytest.raises(OSError):
        atomicio.write_bytes(target, b"whole")
    assert not target.exists()
    assert not (tmp_path / "c.bin.part").exists()


def test_原子复制保留内容且不留临时件(tmp_path: pathlib.Path):
    from novelforge.core import atomicio

    src = tmp_path / "src.epub"
    src.write_bytes(b"payload")
    dst = tmp_path / "lib" / "dst.epub"
    atomicio.copy_file(src, dst)
    assert dst.read_bytes() == b"payload"
    assert not (dst.parent / "dst.epub.part").exists()


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX 才有 0600 语义")
def test_凭证类文件默认私有(tmp_path: pathlib.Path):
    from novelforge.core import atomicio

    p = tmp_path / "cookie.txt"
    atomicio.write_text(p, "secret")
    assert p.stat().st_mode & 0o777 == atomicio.PRIVATE_MODE
