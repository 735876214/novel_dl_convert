"""有声书（单文件 / 多轨目录）：轨道清单、封面探测与体积统计。

「一本书」的两种形态：
- **单文件音频**（``.m4b`` / ``.mp3`` / ...）：一个文件 = 一本书，只有一条轨；
- **音频目录**：一个目录 = 一本书，目录内每个音频文件是一「轨」（一章一文件）。

目录形态是 `library` 扫描的扩展点（见 ``library._iter_book_entries``）：
含音频的目录会被当成**一本书**，而不再逐个音频文件入库。

只做「读」：枚举与统计，不碰磁盘写入（摄入由 pipeline / watcher 负责）。
"""
import pathlib
import re

#: 有声书格式清单（与 docs/bookorbit-library-contract.md 的 AUDIO_FORMAT_LIST 对齐）
AUDIO_EXTS = (".m4b", ".mp3", ".m4a", ".opus", ".ogg", ".flac", ".aac", ".wav")

#: 目录内可能作为封面的图片名（不含扩展名，大小写不敏感）
_COVER_STEMS = ("cover", "folder", "poster", "front", "album")
_COVER_EXTS = (".jpg", ".jpeg", ".png", ".webp")

_JUNK_PARTS = ("__MACOSX/", ".DS_Store", "Thumbs.db")


def is_audio(path) -> bool:
    """是不是单个音频文件（只看扩展名）。"""
    return pathlib.PurePath(str(path)).suffix.lower() in AUDIO_EXTS


def _natural_key(name: str) -> list:
    """自然排序：chapter2 < chapter10（字典序会反）。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _audio_files(d: pathlib.Path) -> list:
    """目录内**直接包含**的音频文件，自然排序（不递归）。"""
    try:
        items = sorted(d.iterdir(), key=lambda p: _natural_key(p.name))
    except OSError:
        return []
    return [p for p in items
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in AUDIO_EXTS]


def is_audio_dir(path) -> bool:
    """目录内直接包含至少一个音频文件 → 视作一本有声书。

    只看直接子文件（不递归）：与 library 的「只下探一层」约定一致，
    这样「系列目录 / 一本有声书子目录」的层级不会被整棵子树吞成一本。
    """
    p = pathlib.Path(path)
    return p.is_dir() and bool(_audio_files(p))


def cover_in_dir(d) -> str:
    """音频目录里的封面文件名（``cover.jpg`` / ``folder.jpg`` / ``poster.*`` 之类），无则空串。"""
    p = pathlib.Path(d)
    try:
        items = sorted(p.iterdir())
    except OSError:
        return ""
    for f in items:
        if f.is_file() and f.suffix.lower() in _COVER_EXTS and f.stem.lower() in _COVER_STEMS:
            return f.name
    return ""


def tracks(path) -> dict:
    """轨道清单。

    - 单文件音频：一条轨（``index=0``，``name=文件名``）；
    - 音频目录：目录内音频自然序排列，``index`` 从 0 起。

    返回 ``{"items": [{index, name, size}], "total": n}``。``name`` 对目录形态是
    **相对目录的文件名**（不含目录前缀），可直接拼媒体 URL。
    """
    p = pathlib.Path(path)
    if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        return {"items": [{"index": 0, "name": p.name, "size": size}], "total": 1}
    files = _audio_files(p)
    items = []
    for i, f in enumerate(files):
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        items.append({"index": i, "name": f.name, "size": size})
    return {"items": items, "total": len(items)}


def track_path(path, index: int):
    """第 index 轨的绝对路径；越界 / 不是音频 → ``None``。"""
    p = pathlib.Path(path)
    if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
        return p if index == 0 else None
    files = _audio_files(p)
    return files[index] if 0 <= index < len(files) else None


def dir_size_and_mtime(d) -> tuple:
    """音频目录的 ``(音频总体积, 最新音频 mtime)``；无音频返回 ``(0, 0.0)``。"""
    total, newest = 0, 0.0
    for f in _audio_files(d):
        try:
            st = f.stat()
        except OSError:
            continue
        total += st.st_size
        newest = max(newest, st.st_mtime)
    return total, newest
