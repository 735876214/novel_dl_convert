"""库级扫描范围：**允许的格式**（`libraries.allowed_exts`）＋**排除图案**（`libraries.exclude`）。

两者都是第 40 期新增的库表列，都只经由 `library._iter_book_entries` 生效，
但**判据正交**：白名单管「哪些格式要」，排除图案管「这些名字不要」。

⚠️ 排除图案那几条**只在这里钉得住**。它的语义与 `watcher.ignore` 长得几乎一样，
却**刻意有两处差异**（`library._excluded` 的 docstring）：用 `fnmatch.fnmatchcase`
（平台无关）而不是 `fnmatch.fnmatch`；图案含 `/` 时匹**相对库根**的路径而不是 basename。
「长得像」正是它明天被顺手改回去的理由 —— 而改回去在 Linux 上照样全绿，
只有 Windows 那条大小写用例会红。这就是这几条用例存在的全部理由。

判据一律走 `library.books()`（端到端），不是直接调 `_excluded`：
排除图案的唯一用途就是「不进书目」，只测那个纯函数测不到接线。
"""
import pathlib

import pytest

from novelforge.core import db, library


@pytest.fixture
def scope_lib(isolated, tmp_path, make_library):  # noqa: ARG001 —— isolated 负责切目录
    """一个就地库（根 = 本用例专属目录）+ 一个往库里写文件的 `put(相对路径)`。"""
    root = tmp_path / "root"
    lib = make_library("scope", "扫描范围库", "comic", root, source_subdir="scope")

    def put(rel: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")            # 内容不重要，扫的是名字与扩展名

    return lib, put


def _names(lid: str) -> set:
    """该库当前扫到的条目名（= 相对库根的 posix 路径）。"""
    library.invalidate()
    return {b["name"] for b in library.books(lid)}


# ---------------------------------------------------------------------------
# 允许的格式
# ---------------------------------------------------------------------------

def test_没设过时按库类型默认收(scope_lib):
    """`allowed_exts` 为空串 = **没设过**（不是「空集合」）⇒ 回落该库类型的默认白名单。"""
    lib, put = scope_lib
    put("甲.cbz")
    put("乙.cbr")
    put("丙.epub")                     # 漫画库默认不收 epub
    assert _names(lib["id"]) == {"甲.cbz", "乙.cbr"}


def test_收窄白名单后扫描结果随之变(scope_lib):
    """设过 `allowed_exts` 就按设过的来 —— **CBR 从此扫不到**，且不会有任何报错。"""
    lib, put = scope_lib
    put("甲.cbz")
    put("乙.cbr")
    assert _names(lib["id"]) == {"甲.cbz", "乙.cbr"}

    db.update_library(lib["id"], allowed_exts='[".cbz"]')
    assert _names(lib["id"]) == {"甲.cbz"}


def test_空数组与坏JSON都当没设过(scope_lib):
    """`[]` 与坏 JSON 都回落类型默认 —— 不抛异常、更不留一个一本也扫不出来的死库。

    ⚠️ 这条与「用户一个都不勾 = 继承默认」是同一件事的两面（向导发的是 `[]`）。
    """
    lib, put = scope_lib
    put("甲.cbz")
    for raw in ("[]", "{{{ 不是 JSON", '{"a":1}'):
        db.update_library(lib["id"], allowed_exts=raw)
        assert _names(lib["id"]) == {"甲.cbz"}, f"坏值 {raw!r} 不该让库变空"


# ---------------------------------------------------------------------------
# 排除图案
# ---------------------------------------------------------------------------

def test_没有图案时一个不跳(scope_lib):
    lib, put = scope_lib
    put("甲.cbz")
    put("草稿.draft.cbz")
    assert _names(lib["id"]) == {"甲.cbz", "草稿.draft.cbz"}


def test_basename图案只匹文件名(scope_lib):
    lib, put = scope_lib
    put("草稿.draft.cbz")
    put("正式.cbz")
    db.update_library(lib["id"], exclude='["*.draft.*"]')
    assert _names(lib["id"]) == {"正式.cbz"}


def test_含斜杠的图案匹相对库根的路径(scope_lib):
    """`子/*` 只吞子目录里的东西；`另一个/` 下的文件**不受影响**。

    这正是「含 `/` 走 rel、不含 `/` 走 basename」那一行的判据 ——
    若哪天被改成纯 basename，`子/*` 里的 `*` 就匹不到任何含 `/` 的串，
    于是**整条规则静默失效**：用户写了、界面上也显示着，文件照样进书目。
    """
    lib, put = scope_lib
    put("子/甲.cbz")
    put("另一个/乙.cbz")
    put("丙.cbz")
    db.update_library(lib["id"], exclude='["子/*"]')
    assert _names(lib["id"]) == {"另一个/乙.cbz", "丙.cbz"}


def test_不含斜杠的图案对子目录里的文件同样生效(scope_lib):
    """`草稿*` 匹的是 basename ⇒ 无论那一本在库根还是在子目录里，都跳。"""
    lib, put = scope_lib
    put("草稿三.cbz")
    put("子/草稿四.cbz")
    put("正式.cbz")
    db.update_library(lib["id"], exclude='["草稿*"]')
    assert _names(lib["id"]) == {"正式.cbz"}


def test_图案大小写敏感(scope_lib):
    """`fnmatchcase` 而非 `fnmatch` —— **Windows 上这条是唯一会红的用例**。

    `watcher._ignored` 用的是 `fnmatch.fnmatch`，在 Windows 上大小写不敏感。
    库级排除是用户**显式写下来的可见规则**，不能随平台变：
    用户在 Windows 上写 `*.DRAFT.*` 想排除草稿，不该顺手把 `*.draft.*` 也吞掉。
    """
    lib, put = scope_lib
    put("草稿.draft.cbz")
    put("正式.cbz")

    db.update_library(lib["id"], exclude='["*.DRAFT.*"]')
    assert _names(lib["id"]) == {"草稿.draft.cbz", "正式.cbz"}, "大写图案不该命中小写文件"

    db.update_library(lib["id"], exclude='["*.draft.*"]')
    assert _names(lib["id"]) == {"正式.cbz"}


def test_空数组与坏JSON都当不过滤(scope_lib):
    lib, put = scope_lib
    put("草稿.draft.cbz")
    for raw in ("[]", "{{{ 不是 JSON", '{"a":1}'):
        db.update_library(lib["id"], exclude=raw)
        assert _names(lib["id"]) == {"草稿.draft.cbz"}, f"坏值 {raw!r} 不该吞掉任何书"


def test_图案去重且保留用户填的顺序(scope_lib):
    """后端存的顺序 = 用户填的顺序（界面按它列出可删的条目）。"""
    lib, put = scope_lib
    put("甲.cbz")
    put("乙.cbz")
    db.update_library(lib["id"], exclude='["乙*", "甲*", "乙*"]')
    assert library.parse_excludes(db.get_library(lib["id"])["exclude"]) == ("乙*", "甲*")
    assert _names(lib["id"]) == set()


def test_排除图案与允许格式互不影响(scope_lib):
    """两条轴正交：撤掉排除后回来的是**白名单那一门**（`.cbz`），不是被白名单挡住的 `.cbr`。"""
    lib, put = scope_lib
    put("甲.cbz")
    put("乙.cbr")
    db.update_library(lib["id"], allowed_exts='[".cbz"]', exclude='["甲*"]')
    assert _names(lib["id"]) == set()
    db.update_library(lib["id"], exclude="[]")
    assert _names(lib["id"]) == {"甲.cbz"}


def test_库根不存在只是扫不到不抛(scope_lib, tmp_path):
    """库根被删掉时扫描返回空列表 —— 一条库的扫描不该把调用方打崩。"""
    lib, _ = scope_lib
    pathlib.Path(library.roots_of(lib)[0]).rename(tmp_path / "gone")
    assert _names(lib["id"]) == set()
