"""`.zip` 的**内容分派**（第 87 期）：容器看内容，不看后缀。

`.zip` 是通用容器、**不是一种书籍格式** —— 里面可能是漫画图片序列，也可能是一份被改了
后缀的 EPUB，还可能是别的文档。它到底算什么书只能看内容（与 `core/comics.py` 顶部
「靠魔数嗅探、不信任扩展名」是同一条纪律的延伸：`.cbz` 与 `.zip` 在字节层面本就等价）。

结论分档，**判不出就如实报「无法判定」** —— 本项目的一条硬纪律：静默猜测的下场是
用户看到一本打不开的书，而原因离现象十万八千里。

===============  ==============  ==================================================
kind             format          含义
===============  ==============  ==================================================
``comic``        ``CBZ``         容器内是图片序列 ⇒ 与 .cbz **完全同等待遇**（可读）
``epub``/``pdf`` 同名大写       容器内**恰好一份**文档（典型是被改了后缀的 EPUB）
``nested``       ``ZIP``         内层还是压缩包 ⇒ 需先展开
``multi``        ``ZIP``         内有多份文档 ⇒ 需先展开
``mixed``        ``ZIP``         图文混装 ⇒ 判不准，不猜
``empty``        ``ZIP``         一个文件都没有
``broken``       ``ZIP``         坏包 / 根本不是压缩包
===============  ==============  ==================================================

⚠️ **目前只有 ``comic`` 一档能读**（页序、封面、逐页接口全部复用漫画那一套）。
其余各档一律**不假装能读**：调用方按「无法解析」登记，让它在「待修复」里看得见 ——
文件在磁盘上、书目里却找不到，比直接拒收更糟（见 `library.accepts_ext` 的说明）。
"""
import pathlib

from . import comics

#: 需要内容分派才能定形态的扩展名（`.cbz` / `.cbr` 是漫画专属后缀，不走这里）
CONTAINER_EXTS = (".zip",)

#: 容器内出现任一 ⇔ 它其实是一份 EPUB
_EPUB_MARKERS = ("mimetype", "META-INF/container.xml")

#: 容器内**恰好一份**这些文档时，它就是这个格式
_DOC_FORMATS = {".epub": "EPUB", ".pdf": "PDF", ".txt": "TXT", ".mobi": "MOBI",
                ".azw3": "AZW3", ".fb2": "FB2"}

#: 内层还是压缩包 ⇒ 需先展开
_ARCHIVE_EXTS = (".zip", ".cbz", ".cbr", ".rar")


def is_container(path) -> bool:
    """这个后缀要不要走内容分派。"""
    return pathlib.PurePath(str(path)).suffix.lower() in CONTAINER_EXTS


def _suffix(name: str) -> str:
    return pathlib.PurePath(str(name)).suffix.lower()


def _junk(name: str) -> bool:
    """垃圾条目（`__MACOSX/`、`.DS_Store`、隐藏文件）—— 与取页那份判据同源。"""
    if any(j in name for j in comics._JUNK_PARTS):      # noqa: SLF001 —— 同包同源，刻意复用
        return True
    return pathlib.PurePath(name).name.startswith(".")


def analyze(path) -> dict:
    """判定容器里到底是什么。**只读、不改盘、不抛异常**。

    返回 ``{kind, format, reason, readable, needs_unwrap, evidence}``：
    ``format`` 是该形态**对应**的书目 format（只有 ``comic`` 一档会被上层直接采用，
    其余各档上层一律记成 ``ZIP`` + 无法解析 —— 见模块文档）。
    坏包 / 缺 RAR 依赖折算成 ``broken``（与 `comics.probe` 同口径，绝不抛异常）。
    """
    p = pathlib.Path(str(path))
    out = {"kind": "unknown", "format": "ZIP", "reason": "", "readable": False,
           "needs_unwrap": False,
           "evidence": {"files": 0, "images": 0, "docs": [], "archives": 0, "sample": []}}
    try:
        with comics._open(str(p)) as arc:               # noqa: SLF001 —— 归档句柄的唯一owner
            names = [n for n in arc.names() if not _junk(n)]
    except Exception as e:                              # noqa: BLE001 —— 坏包如实报，不抛
        out.update(kind="broken",
                   reason=f"不是可读的压缩包（{type(e).__name__}）")
        return out

    images = [n for n in names if comics._keep(n)]      # noqa: SLF001 —— 「算不算一页」的唯一判据
    docs = [n for n in names if _suffix(n) in _DOC_FORMATS]
    archives = [n for n in names if _suffix(n) in _ARCHIVE_EXTS]
    out["evidence"] = {"files": len(names), "images": len(images),
                       "docs": docs[:5], "archives": len(archives), "sample": names[:5]}

    if any(n in _EPUB_MARKERS for n in names):
        out.update(kind="epub", format="EPUB", needs_unwrap=True,
                   reason="容器内是一份 EPUB（有 mimetype / container.xml），只是改了后缀"
                          " —— 需要先展开才能读")
    elif archives:
        out.update(kind="nested", needs_unwrap=True,
                   reason=f"容器内还有 {len(archives)} 个压缩包，需要先展开")
    elif images and not docs:
        out.update(kind="comic", format="CBZ", readable=True,
                   reason=f"容器内是 {len(images)} 张图片，按漫画包读取")
    elif len(docs) == 1 and not images:
        fmt = _DOC_FORMATS[_suffix(docs[0])]
        out.update(kind=fmt.lower(), format=fmt, needs_unwrap=True,
                   reason=f"容器内是一份 {fmt}，需要先展开才能读")
    elif len(docs) > 1:
        out.update(kind="multi", needs_unwrap=True,
                   reason=f"容器内有 {len(docs)} 份文档，需要先展开")
    elif images and docs:
        out.update(kind="mixed",
                   reason=f"容器内既有 {len(images)} 张图片又有文档，判不准（不猜）")
    elif not names:
        out.update(kind="empty", reason="容器内没有任何文件")
    else:
        out.update(kind="unknown",
                   reason=f"容器内没有可识别的内容（{len(names)} 个文件）")
    return out
