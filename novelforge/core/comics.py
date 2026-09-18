"""漫画归档（CBZ / CBR）：页清单 / 单页取图 / 封面探测。

支持两种容器，靠**魔数嗅探**选择后端（不信任扩展名）：
- **CBZ** = 普通 zip，标准库 ``zipfile`` 直接解；
- **CBR** = RAR，需 ``rarfile`` + 一个外部解压器（``bsdtar`` / ``unrar``）。
  容器里由 ``libarchive-tools`` 提供 ``bsdtar``，macOS 本机自带 ``bsdtar``。

对外接口（``probe`` / ``pages`` / ``page_bytes`` / ``cover_entry`` / ``cover_bytes``）
对两种格式**完全一致**，上层（library / server）无需分支。

三个必须处理的现实问题：
- macOS 压缩会塞进 ``__MACOSX/`` 与 ``.DS_Store``，不过滤的话漫画里会混进垃圾「页」；
- 页序必须**自然排序**（page2 < page10），字典序会把 page10 排到 page2 前面；
- RAR 没有 zip 那样的 ``is_dir()``，目录项靠「名字以 / 结尾」判定。

容错口径与 EPUB 一致：坏包 / 缺依赖 / 不是归档一律折算成 ``unparsable`` 或空结果，
**绝不抛异常** —— 书架里宁可显示「无法解析」，也不要因为一个坏文件让整次扫描崩掉。
"""
import mimetypes
import pathlib
import re
import zipfile

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif"}
_JUNK_PARTS = ("__MACOSX/", ".DS_Store", "Thumbs.db", ".thumbnails/")

#: 归档魔数：RAR4/RAR5 都是 "Rar!\x1a\x07"，zip 以 "PK" 开头
_RAR_MAGIC = b"Rar!\x1a\x07"
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

COMIC_EXTS = (".cbz", ".cbr")


def is_comic(path) -> bool:
    """是不是漫画归档（只看扩展名，供书架白名单与路由判定用）。"""
    return pathlib.PurePath(str(path)).suffix.lower() in COMIC_EXTS


def is_cbz(path) -> bool:
    return pathlib.PurePath(str(path)).suffix.lower() == ".cbz"


def is_cbr(path) -> bool:
    return pathlib.PurePath(str(path)).suffix.lower() == ".cbr"


def rar_available() -> bool:
    """RAR 后端是否可用（``rarfile`` 已装 + 能找到外部解压器）。

    设置页与接口错误提示据此给出「缺依赖」的准确原因，而不是笼统的「打不开」。
    """
    try:
        import rarfile  # noqa: F401
    except Exception:
        return False
    try:
        rarfile.tool_setup()
        return True
    except Exception:
        return False


def _sniff(path) -> str:
    """按魔数判断容器类型：``"zip"`` / ``"rar"`` / ``""``（都不是）。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return ""
    if head.startswith(_RAR_MAGIC):
        return "rar"
    if head[:4] in _ZIP_MAGICS:
        return "zip"
    return ""


def _natural_key(name: str) -> list:
    """把文件名切成「文字段 / 数字段」再比较，使 page2 < page10。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _keep(name: str) -> bool:
    """条目是否算一页（过滤垃圾、目录项与非图片）。"""
    if any(j in name for j in _JUNK_PARTS):
        return False
    if pathlib.PurePath(name).name.startswith("."):
        return False
    return pathlib.PurePath(name).suffix.lower() in IMAGE_EXTS


class _Archive:
    """zip / rar 的统一只读句柄：``entries()`` 列表 + ``read(name)``。

    上层只依赖这两个方法，因此 4 个公开函数不必知道底层是什么容器。
    """

    def __init__(self, path):
        self.kind = _sniff(path)
        self._z = None
        self._r = None
        if self.kind == "zip":
            self._z = zipfile.ZipFile(path)
        elif self.kind == "rar":
            import rarfile
            self._r = rarfile.RarFile(str(path))
        else:
            raise ValueError("既不是 zip 也不是 rar 归档")

    def entries(self) -> list:
        """图片条目 ``[(name, size), ...]``，过滤垃圾/目录/非图片后自然排序。"""
        out = []
        if self._z is not None:
            for info in self._z.infolist():
                if info.is_dir():
                    continue
                if _keep(info.filename):
                    out.append((info.filename, info.file_size))
        else:
            for info in self._r.infolist():
                name = info.filename
                # RAR 没有可靠的 is_dir()，目录项以 / 结尾（个别工具还带 isdir 标志）
                if name.endswith("/") or getattr(info, "isdir", lambda: False)():
                    continue
                if _keep(name):
                    out.append((name, getattr(info, "file_size", 0)))
        out.sort(key=lambda kv: _natural_key(kv[0]))
        return out

    def read(self, name: str) -> bytes:
        return self._z.read(name) if self._z is not None else self._r.read(name)

    def close(self) -> None:
        for h in (self._z, self._r):
            try:
                if h is not None:
                    h.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _open(path) -> _Archive:
    return _Archive(path)


def _media_of(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def probe(path) -> dict:
    """书目扫描用：页数 / 是否有封面 / 封面条目。

    坏包 / 缺 RAR 依赖 / 魔数不符 → ``unparsable=True``（与 EPUB 同口径，不抛异常）。
    """
    out = {"has_cover": False, "cover": "", "pages": 0, "pages_source": "archive",
           "unparsable": False}
    try:
        with _open(path) as arc:
            names = arc.entries()
            out["pages"] = len(names)
            if names:
                out["has_cover"] = True
                out["cover"] = names[0][0]
    except Exception:
        out["unparsable"] = True
        out["pages_source"] = ""
    return out


def pages(path) -> dict:
    """页清单。``index`` 是**序号**（0 起），不是归档内的名字 —— 前端按序号取图。"""
    try:
        with _open(path) as arc:
            names = arc.entries()
    except Exception:
        return {"pages": [], "total": 0}
    return {
        "pages": [{"index": i, "name": n, "size": s} for i, (n, s) in enumerate(names)],
        "total": len(names),
    }


def page_bytes(path, index: int):
    """取第 index 页的原始字节 + media type；越界 / 坏包返回 ``(None, "")``。"""
    try:
        with _open(path) as arc:
            names = arc.entries()
            if not (0 <= index < len(names)):
                return (None, "")
            name = names[index][0]
            data = arc.read(name)
    except Exception:
        return (None, "")
    return (data, _media_of(name))


def cover_entry(path) -> str:
    """第一页的条目名（封面用它）；没有图片返回空串。"""
    try:
        with _open(path) as arc:
            names = arc.entries()
            return names[0][0] if names else ""
    except Exception:
        return ""


def cover_bytes(path):
    """封面（= 第一页）的原始字节 + media type；没有返回 ``(None, "")``。

    server 的封面接口直接用它，避免再自己 ``zipfile.ZipFile`` 解一次
    （那样 CBR 会「能列出封面名却读不出来」）。
    """
    return page_bytes(path, 0)
