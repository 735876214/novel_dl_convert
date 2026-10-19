"""仓库根防删除守卫本身的两条断言（第 118 期）。

守卫（`tests/conftest.py::_repo_root_guard`）是**最后一道防线**，自身却出过一次假阳：
它只看 `path`、忽略 `dir_fd`，而 POSIX 的 `shutil.rmtree` 删子项时调的是
`os.unlink(entry.name, dir_fd=topfd)` —— 裸文件名被按 cwd（= 仓库根）解析，
于是**正常的临时目录清理**被当成「删仓库根里的文件」，12 例数据安全用例在 Linux / macOS 上必红。
本文件钉两头：**该让行的让行**、**该拦的仍然拦得住**（放宽守卫不能顺手把它废掉）。
"""
import os
import pathlib
import shutil

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_rmtree_在仓库根当工作目录时不再误判(monkeypatch, tmp_path):
    """cwd 就是仓库根、删的是仓库**外面**的临时目录 ⇒ 必须正常删掉。

    这正是第 118 期之前必红的形态：rmtree 内层把 `derived.epub` 这类裸名交给
    `os.unlink(..., dir_fd=...)`，守卫按 cwd 解析成仓库根里的同名文件。
    """
    monkeypatch.chdir(REPO_ROOT)
    target = tmp_path / "书库"
    (target / "子目录").mkdir(parents=True)
    (target / "derived.epub").write_bytes(b"PK\x03\x04")
    (target / "三体.meta.json").write_text("{}", encoding="utf-8")
    (target / "子目录" / "第1话.mp3").write_bytes(b"\x00")

    shutil.rmtree(target)          # 之前：pytest.fail("[REPO-ROOT GUARD] … derived.epub")

    assert not target.exists()


def test_指向仓库根的绝对路径仍然被拦():
    """`dir_fd` 让行**只**针对相对已打开目录的裸名；绝对路径照旧一律拒绝。

    用不存在的路径调用：守卫在**碰文件系统之前**就 fail ⇒ 这条用例即使守卫坏了
    也不会真删掉仓库里的任何东西（不会造成自杀式回归）。
    """
    victim = REPO_ROOT / "__no_such_file_should_never_exist__"
    with pytest.raises(pytest.fail.Exception, match="REPO-ROOT GUARD"):
        os.unlink(victim)


def test_守卫确实装上了():
    """会话级 fixture 装的是包装函数而不是原生 `os.unlink` ⇒ 上面两条断言才有意义。

    故意**不**去测「`rmtree(仓库根)` 被拒」：那需要真的把仓库根交给 rmtree，
    守卫一旦回归就是**把仓库删掉**的用例 —— 测防线的东西不许自带这种爆炸半径。
    仓库根在入口就被拒这件事由第 44 期起的既有守卫保证，与本次放宽无关。
    """
    assert getattr(os.unlink, "__name__", "") == "_g_unlink", "守卫没装上（session 级 fixture 早退？）"
