"""漫画归档与通用容器（CBZ / CBR / ZIP / RAR / 7Z）：页清单 / 单页取图 / 封面探测。

支持三种容器，靠**魔数嗅探**选择后端（不信任扩展名）：
- **zip**（`.cbz` / `.zip`）= 标准库 ``zipfile`` 直接解；
- **rar**（`.cbr` / `.rar`）= ``rarfile`` + 一个外部解压器（``bsdtar`` / ``unrar``）。
  容器镜像里由 ``libarchive-tools`` 提供 ``bsdtar``，macOS 本机自带 ``bsdtar``；
  Windows 上装了 WinRAR 也能用（把 ``UnRAR.exe`` 所在目录加进 ``PATH``，或设 ``UNRAR_TOOL``）。
- **7z**（`.7z`）= ``py7zr``（第 111 期）。纯 Python、**不需要外部解压器** —— 这一条是
  选它的主要理由：容器镜像不必再装系统包，Windows 开发机也能直接读。

⚠️ 「缺依赖」必须**如实**报出来（第 111 期）：:func:`backend_problem` 是这件事的**唯一判据**
（返回「缺什么」，空串 = 现在能读）。此前只有 RAR 一条判据散在 server 的三处守卫里，
`.7z` 一进来就会漏 —— 缺 ``py7zr`` 时表现为「容器里一个文件都没有」这种静默失败。

对外接口（``probe`` / ``pages`` / ``page_bytes`` / ``cover_entry`` / ``cover_bytes``）
对三种容器**完全一致**，上层（library / server）无需分支。

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

#: 归档魔数：RAR4/RAR5 都是 "Rar!\x1a\x07"，zip 以 "PK" 开头，7z 是固定 6 字节签名
_RAR_MAGIC = b"Rar!\x1a\x07"
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_7Z_MAGIC = b"7z\xbc\xaf\x27\x1c"

# ⚠️ `.zip` 也在列（第 87 期）：它与 `.cbz` 在**字节层面本就等价**，而 `_Archive` 是靠
# 魔数嗅探选后端的（见 `_sniff`），所以「能读」这一步不需要任何改动。
# 但 `.zip` **是一个通用容器**：里面装的是图片还是别的文档，由 `core/zipkind.py`
# 按内容分派 —— 本常量只回答「这个后缀要不要按归档处理」，不回答「它是什么书」。
# 第 111 期：`.rar` / `.7z` 同理入列 —— 它们是同一种通用容器的另外两个壳（`.rar` 与
# `.cbr`、`.7z` 与前面两者只是打包算法不同）。入列的**唯一**理由是「按归档读」这条路径
# 要认它们；「它是什么书」仍然只由 `zipkind.analyze` 按内容答。
# ⚠️ 副作用是 `is_comic` 对它们返回**真**（它只看后缀）⇒ 调用方必须像 `.zip` 那样带上
# 附加判据（见 `library._probe_entry` 里 `zip_v["kind"] == "comic"` 那一条）。
COMIC_EXTS = (".cbz", ".cbr", ".zip", ".rar", ".7z")


def write_cbz(dest, pages):
    """把 ``[(文件名, 字节), ...]`` 写成 CBZ（第 86 期：从书源下载漫画的落盘点）。

    · **原子写**：先写同目录的 `.part` 再 `Path.replace` —— 与项目「源不可变、副本禁原地写」
      同一条纪律。中途失败只会留下一个 `.part`，不会留下半个打不开的归档
      （那在书架上就是一本书「无法解析」的假漫画，比没有更糟）；
    · **不压缩**（`ZIP_STORED`）：JPG/PNG 本身已压缩，再 deflate 只是白赔 CPU；
    · **页序 = 传入顺序**：调用方负责有序（站点给的顺序就是阅读顺序，本函数不重排）。
    """
    dest = pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for name, data in pages:
            z.writestr(str(name), data)
    tmp.replace(dest)
    return dest


_PAGE_NUM_RE = re.compile(r"^(\d+)$")


def append_pages(cbz, pages) -> dict:
    """把新一话的页**追加**到 CBZ 末尾（第 86 期追更；既有条目一字不动）。

    · **真追加**：用 `zipfile.ZipFile(path, "a")`，只写新条目 —— 既有条目的压缩数据
      连一个字节都不动（比「全读出来再重写」更省也更安全：重写要重新压缩每一页，
      还可能顺手改掉既有条目的元数据）；
    · 页号**续着既有最大编号往下排**（已有 `0001.jpg` ⇒ 新页从 `0005.jpg` 起），
      既有页序因此不变 —— 阅读进度按页序记录，这一条就是它不漂移的根据；
    · 撞名一律**跳号，绝不覆盖既有页**；`pages` = ``[(扩展名, 字节), ...]``。
    """
    cbz = pathlib.Path(cbz)
    pages = list(pages or [])
    if not pages:
        return {"path": cbz, "added": [], "start": None}
    with zipfile.ZipFile(cbz) as z:
        existing = {n for n in z.namelist() if not n.endswith("/")}
    nums = [int(m.group(1)) for m in
            (_PAGE_NUM_RE.match(pathlib.PurePath(n).stem) for n in existing) if m]
    n = (max(nums) + 1) if nums else 1
    added: list = []
    with zipfile.ZipFile(cbz, "a", zipfile.ZIP_STORED) as z:
        for ext, data in pages:
            while f"{n:04d}{ext}" in existing:
                n += 1
            name = f"{n:04d}{ext}"
            z.writestr(name, data)
            existing.add(name)
            added.append(name)
            n += 1
    return {"path": cbz, "added": added, "start": int(pathlib.PurePath(added[0]).stem)}


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


def seven_available() -> bool:
    """7z 后端是否可用（``py7zr`` 已装）。第 111 期。

    与 :func:`rar_available` 的区别是**不需要外部解压器** —— 纯 Python 包，装了就能读。
    """
    try:
        import py7zr  # noqa: F401
    except Exception:
        return False
    return True


def backend_problem(path) -> str:
    """这个归档**现在**读不了的**能力**原因；空串 = 能读。

    ⚠️ **「缺依赖」的唯一判据**（第 111 期）：server 的三处守卫、`zipkind.analyze` 的
    坏包分档都问这里，别各自再写一遍「是不是 rar、装没装」—— 那种散判据正是漏掉 `.7z`
    的成因（缺 `py7zr` 时表现为「容器里一个文件都没有」，用户完全看不出原因）。

    只回答**能力**问题：文件本身坏 / 魔数不认识**不算**（那是「这本书坏了」，
    由 :func:`_sniff` 回空串 + 调用方按坏包处理，文案也不同）。

    ⚠️ 魔数认不出时会**退回后缀**再判一次：`.cbr` / `.rar` / `.7z` 的扩展名与「需要哪个
    后端」是确定的，而真实世界里坏包、半截下载、占位文件都会让魔数落空 —— 那时若只说
    「缺能力」是错怪用户，只说「坏包」又漏掉了「这台服务器本来就读不了 RAR」这个更该先
    知道的事实。两害相权，先报能力（与改造前按后缀判的既有行为一致）。
    """
    kind = _sniff(path)
    if not kind:
        kind = {".cbr": "rar", ".rar": "rar", ".7z": "7z"}.get(
            pathlib.PurePath(str(path)).suffix.lower(), "")
    if kind == "rar" and not rar_available():
        return "服务器缺少 RAR 解压能力（需 bsdtar 或 unrar）"
    if kind == "7z" and not seven_available():
        return "服务器缺少 7z 解压能力（需 py7zr）"
    return ""


def _sniff(path) -> str:
    """按魔数判断容器类型：``"zip"`` / ``"rar"`` / ``"7z"`` / ``""``（都不是）。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return ""
    if head.startswith(_RAR_MAGIC):
        return "rar"
    if head.startswith(_7Z_MAGIC):
        return "7z"
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
    """zip / rar / 7z 的统一只读句柄：``entries()`` 列表 + ``read(name)``。

    上层只依赖这两个方法，因此 4 个公开函数不必知道底层是什么容器。
    """

    def __init__(self, path):
        self.kind = _sniff(path)
        self._z = None
        self._r = None
        self._s = None
        self._sizes = None
        if self.kind == "zip":
            self._z = zipfile.ZipFile(path)
        elif self.kind == "rar":
            import rarfile
            self._r = rarfile.RarFile(str(path))
        elif self.kind == "7z":
            import py7zr
            self._s = py7zr.SevenZipFile(str(path))
        else:
            raise ValueError("既不是 zip、rar 也不是 7z 归档")

    def _size_of(self, name: str) -> int:
        """7z 条目的解压后大小（给内存工厂设上限用）；查不到回 0。"""
        if self._sizes is None:
            self._sizes = {str(getattr(i, "filename", "")): int(getattr(i, "uncompressed", 0) or 0)
                           for i in self._s.list()}
        return self._sizes.get(str(name), 0)

    def names(self) -> list:
        """全部**文件**条目名（跳过目录项，**不**过滤非图片）。

        给内容分派用（`core/zipkind.py`）：那边要自己分辨「图片 / 文档 / 内层压缩包」，
        所以不能拿 :meth:`entries` 那份已经筛成图片的表。
        """
        if self._z is not None:
            return [i.filename for i in self._z.infolist() if not i.is_dir()]
        if self._r is not None:
            return [i.filename for i in self._r.infolist() if not i.isdir()]
        return [i.filename for i in self._s.list()
                if not getattr(i, "is_directory", False)]

    def entries(self) -> list:
        """图片条目 ``[(name, size), ...]``，过滤垃圾/目录/非图片后自然排序。"""
        out = []
        if self._z is not None:
            for info in self._z.infolist():
                if info.is_dir():
                    continue
                if _keep(info.filename):
                    out.append((info.filename, info.file_size))
        elif self._r is not None:
            for info in self._r.infolist():
                name = info.filename
                # RAR 没有可靠的 is_dir()，目录项以 / 结尾（个别工具还带 isdir 标志）
                if name.endswith("/") or getattr(info, "isdir", lambda: False)():
                    continue
                if _keep(name):
                    out.append((name, getattr(info, "file_size", 0)))
        else:
            for info in self._s.list():
                name = str(getattr(info, "filename", ""))
                if getattr(info, "is_directory", False) or name.endswith("/"):
                    continue
                if _keep(name):
                    out.append((name, int(getattr(info, "uncompressed", 0) or 0)))
        out.sort(key=lambda kv: _natural_key(kv[0]))
        return out

    def read(self, name: str):
        """取一个条目的字节。**取不到回 ``None``**（7z 后端的能力边界，见下）。"""
        if self._z is not None:
            return self._z.read(name)
        if self._r is not None:
            return self._r.read(name)
        # 7z：py7zr 1.1.3 实测**没有**「读单个条目」的直接 API（只有 extract/extractall），
        # 官方给的路子是传一个内存工厂 ⇒ 这里把该条目抽进 BytesIO：**不落盘**、
        # 也**不整包读进内存**（工厂的 limit 按该条目的解压后大小给）。
        import py7zr.io
        factory = py7zr.io.BytesIOFactory(limit=max(self._size_of(name), 1))
        self._s.reset()                     # py7zr 的句柄有状态：再抽一次前必须复位
        self._s.extract(targets=[name], factory=factory)
        buf = factory.products.get(name)
        return buf.read() if buf is not None else None

    def close(self) -> None:
        for h in (self._z, self._r, self._s):
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
