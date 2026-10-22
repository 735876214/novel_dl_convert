"""原子写 / 原子复制的**唯一实现**（第 137 期）。

全仓纪律（AGENTS.md §1）：凡写进「别人可能正在读」的路径 —— 被扫描的库根、出版副本
目录、配置 / 状态 / 缓存 —— 都必须先写同目录临时名再 :meth:`Path.replace`。原地写
（``Path.write_bytes`` / ``shutil.copy2``）中途死掉会留下**半份文件**，而扫描器 / 外部
阅读器 / 下一次启动会把半份文件当成成品：半本书进书架、半份备份被计入配额、截断的字体
被正常列出。判据最早写在 `watcher.py`（第 135 期）与 `landing.py`（第 96 期）的注释里，
第 137 期审计发现同样的手法在 pipeline / publish / backup / fonts / store / authors /
pdfrender 又各写了一份（其中几处干脆没写）⇒ 收敛到这里一份。

为什么不是每个模块各写一段：
 ① 临时名必须落在 watcher 的忽略清单里（``*.part``，见 `watcher.ignore`），否则「半份」
    会被当真书收进书架 —— 名字写错一处就等于没做；
 ② 失败必须**清掉**临时件，否则 SIGKILL / 磁盘满之后残留的 ``.part`` 无人回收；
 ③ 权限必须在 ``replace`` **之前**收敛：先 replace 再 chmod 会留下一个「已是最终名字、
    但仍是 umask 默认 0644」的窗口（凭证 / cookie / db 就靠这个窗口泄露）。

反过来的边界（别拿这个模块去改书文件）：源文件**只读**，成品一律是副本。
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import shutil

#: 临时件后缀。必须与 `config`/`watcher` 的忽略清单一致（``*.part``）—— 改这里等于改判据。
PART_SUFFIX = ".part"

#: 私有文件的目标权限（凭证 / cookie / db / 配置覆盖层）。公开产物（书库成品）用默认。
PRIVATE_MODE = 0o600


def tmp_path_for(dst) -> pathlib.Path:
    """同目录临时名：``a.epub`` → ``a.epub.part``（同目录 ⇒ ``replace`` 不会跨设备）。"""
    p = pathlib.Path(dst)
    return p.with_name(p.name + PART_SUFFIX)


def _restrict(p: pathlib.Path, mode: int) -> None:
    """在 ``replace`` 之前把权限收敛好；非 POSIX 平台（Windows）静默跳过。"""
    if os.name == "posix":
        try:
            os.chmod(p, mode)
        except OSError:
            pass


def _commit(tmp: pathlib.Path, dst: pathlib.Path) -> None:
    tmp.replace(dst)


def write_bytes(dst, data: bytes, *, private: bool = True) -> pathlib.Path:
    """原子写字节串。``private=True`` 时落 0600（凭证类默认私有）。

    实现就一行 —— 提交 / 清理 / 权限的三条口径都在 :func:`access` 里，
    这里只负责把「一组字节」写进去（不在第二处重抄那三条）。
    """
    dst = pathlib.Path(dst)
    with access(dst, private=private) as tmp:
        tmp.write_bytes(data)
    return dst


def write_text(dst, text: str, *, encoding: str = "utf-8", private: bool = True) -> pathlib.Path:
    return write_bytes(dst, text.encode(encoding), private=private)


@contextlib.contextmanager
def access(dst, *, private: bool = False):
    """「边写边流」类落盘的原子外壳：交出**同目录临时文件的路径**，退出时提交。

    ``zipfile.ZipFile(...)`` / ``shutil.copyfile(...)`` / ``pg_dump`` 这类写手拿不到
    「一组字节」，它们要的是一个**自己写的路径**。三种形状（字节 / 文本 / 流）里，
    这个才是主流 —— 前面两个是对它的便捷包装。

    用法::

        with atomicio.access(dest) as tmp:
            with zipfile.ZipFile(tmp, "w") as z:
                ...

    异常路径同样清掉临时件（``.part`` 无人回收，见模块头三条理由）。
    """
    dst = pathlib.Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(dst)
    try:
        yield tmp
        if private:
            _restrict(tmp, PRIVATE_MODE)
        _commit(tmp, dst)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def copy_file(src, dst, *, private: bool = False) -> pathlib.Path:
    """原子地把 ``src`` 复制成 ``dst``（保留 mtime / 权限位：``copy2`` 语义）。

    复制出来的成品默认**不**改权限：书库里的书要能被外部阅读器读到。
    """
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    with access(dst, private=private) as tmp:
        shutil.copy2(src, tmp)
    return dst
