"""pytest 全局夹具（第 11 期「工程护栏」）。

# 为什么文件顶部这么啰嗦：两条前置必须在 import 业务模块**之前**完成

1. `novelforge/config.py` 在**模块导入时**就按 `os.getenv` 把各目录固化成模块级常量；
   `novelforge/server.py` 更是在 import 阶段直接执行 `config.ensure_dirs()`。
   若先 import 再改环境变量，`ensure_dirs()` 已经去建**真实**的 `/app/...` 目录了。
2. `novelforge/core/db.py` 用 `_conn` / `_db_path` 两个模块级缓存，首次调用后就固定住 ——
   所以「每个用例一套独立空库」必须靠 `db.close()` 重置（见 `isolated` 夹具）。

因此本文件把「建会话级临时根 → 写 os.environ → 补 sys.path」放在最前面，
**之后**才 import 业务模块。

约定（改测试前先读这三条）：
- 碰书库或数据库的用例**必须**声明 `isolated`（否则断言会互相污染、且产生顺序依赖）；
- 打接口的用例用 `client` + `auth_headers`（`/api/*` 无令牌一律 401）；
- 造数据用 `make_book` / `make_audio_dir` / `make_epub` / `make_library`，别自己在测试里拼路径。
"""
import os
import pathlib
import shutil
import sys
import tempfile
import zipfile
from typing import Iterator

import pytest

# ---------------------------------------------------------------------------
# ① 会话级临时根 + 环境变量（必须早于任何业务 import）
# ---------------------------------------------------------------------------

#: 整轮测试的临时根目录；`pytest_sessionfinish` 里会整棵删掉
_SESSION_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="novelforge-tests-"))

#: 兜底补 sys.path：不依赖调用方式（`pytest` / `python -m pytest` 都能跑）
_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: 测试账号（与本地冒烟实例保持一致，便于人工复现同一套命令）
TEST_USER = "admin"
TEST_PIN = "test1234"

os.environ.update({
    "CONFIG_DIR": str(_SESSION_ROOT / "config"),
    "INPUT_DIR": str(_SESSION_ROOT / "input"),
    "OUTPUT_DIR": str(_SESSION_ROOT / "output"),
    "DATA_DIR": str(_SESSION_ROOT / "data"),
    "CACHE_DIR": str(_SESSION_ROOT / "cache"),
    "LOG_DIR": str(_SESSION_ROOT / "logs"),
    "BACKUP_DIR": str(_SESSION_ROOT / "backups"),
    "FONTS_DIR": str(_SESSION_ROOT / "fonts"),
    "COOKIE_DIR": str(_SESSION_ROOT / "cookies"),
    "SOURCES_DIR": str(_SESSION_ROOT / "sources"),
    "LIBRARY_SOURCE_DIR": str(_SESSION_ROOT / "libraries"),
    # 不起监听线程：本套测试不测 watcher，多一个后台轮询只会让失败更难定位
    "AUTO_WATCH": "false",
    "AUTH_USER": TEST_USER,
    "AUTH_PIN": TEST_PIN,
    "AUTH_SECRET": "test-secret-not-for-production",
})

# ---------------------------------------------------------------------------
# ② 后端开关（第 62 期）：默认 sqlite；PG 侧跑法见 README「第 62 期」
# ---------------------------------------------------------------------------

#: 本轮是不是跑在 PostgreSQL 上。**不设 NOVELFORGE_DB 时是 False**，
#: 离线全量（939 例基线）的行为与第 61 期逐字节一致。
_PG = (os.environ.get("NOVELFORGE_DB") or "").strip().lower() in (
    "pg", "postgres", "postgresql")

if _PG and (os.environ.get("NOVELFORGE_PG_RESET") or "").strip() not in ("1", "true", "yes", "on"):
    # 没有商量的余地：PG 侧的用例级隔离**就是**每个用例重建 schema，而那个动作会
    # 把库里现有的东西全删掉。不开这个开关就跑，等于悄悄对着一个没隔离的库写
    # 一千多个用例 —— 失败会以「随机某例挂掉」的面目出现，没人查得出来。
    pytest.exit(
        "在 PostgreSQL 后端下跑测试必须设 NOVELFORGE_PG_RESET=1"
        "（例：NOVELFORGE_DB=pg NOVELFORGE_PG_DSN=… NOVELFORGE_PG_RESET=1 python -m pytest）。"
        "⚠️ 这个库里的数据会**每个用例被整库删除**，请只对测试库使用。",
        returncode=2,
    )

# ---------------------------------------------------------------------------
# ③ 仓库根防删除守卫（防回归：任何测试都不得删除 / 移走仓库根内文件）
# ---------------------------------------------------------------------------
# 背景：第 44 期曾出现「全量 pytest 后 14 个仓库根跟踪文件从工作树消失」的事故。
# 根因是测试运行期的目录重定向（见 ①）在某些启动方式下未生效，导致某个清理逻辑
# 把仓库根当成了它的数据 / 配置目录来清空。本守卫作为**最后一道防线**：
# 无论 ① 的环境重定向是否生效，只要路径解析到仓库根内，删除 / 移走一律拒绝。
# 测试本就只在 tmp_path / 会话临时根里增删文件，命中本守卫即说明有测试越界，应修测试。

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _path_under_repo_root(p) -> bool:
    """p 解析后是否落在仓库根内（含仓库根本身）。"""
    try:
        return pathlib.Path(p).resolve().is_relative_to(_REPO_ROOT)
    except (OSError, ValueError):
        return False


def _repo_root_guard_fail(verb, p):
    import traceback

    pytest.fail(
        "[REPO-ROOT GUARD] 拒绝{verb}仓库根内路径 {p}\n调用栈：\n{stack}".format(
            verb=verb, p=p, stack="".join(traceback.format_stack())
        )
    )


# 预热 `anyio.open_file`（第 64 期）。**必须在守卫安装之前**，所以是模块级而不是夹具 ——
# 守卫是 session 级 fixture，写在夹具里已经晚了一步。
#
# 起因：`FileResponse` 第一次真正吐文件时，会在**事件循环线程里**惰性 import
# `anyio._core._fileio`（`anyio/_lazyimport.py` → `import_module`），而 pytest 的断言
# 重写钩子会给这次 import 写一个 `...-pytest-<版本>.pyc` —— 写 pyc 是「先写同目录临时文件、
# 再 os.replace」。**`.venv` 就在仓库根内**，于是守卫把这次 replace 判成「移走仓库根内文件」
# 并 fail：第一个真正返回文件的接口（`/download`）一测就红，报错还指在 conftest 上、
# 完全看不出是被测代码的问题。（第 44 期那条守卫针对的是**跟踪文件从工作树消失**；
# 而 `__pycache__` 里的字节码是生成物，不该走这条判据。）
#
# 先 import 一次就够：模块进了 `sys.modules`，重写钩子之后不再插手（谁先 import 谁说了算）。
from anyio import open_file as _prewarm_anyio_open_file  # noqa: E402, F401


@pytest.fixture(scope="session", autouse=True)
def _repo_root_guard():
    """会话级守卫：拦截任何指向仓库根的删除 / 移走操作。

    只拦「删除类」（remove / unlink / rmdir / rmtree）与「移走类」
    （rename / replace / move，且**源**在仓库根内）—— 这两类会让仓库根文件从工作树
    消失。读 / 写（open、Path.write_text）不拦，测试合法读取源码 / 前端文件不受影响。

    注：手动打补丁而非用 monkeypatch 夹具——后者是 function 作用域，
    无法在 session 级夹具里请求（会 ScopeMismatch）。进程退出即自然还原。
    """
    _orig = {
        "os.remove": os.remove,
        "os.unlink": os.unlink,
        "os.rmdir": os.rmdir,
        "shutil.rmtree": shutil.rmtree,
        "os.rename": os.rename,
        "os.replace": os.replace,
        "shutil.move": shutil.move,
        "Path.unlink": pathlib.Path.unlink,
        "Path.rmdir": pathlib.Path.rmdir,
    }

    def _g_remove(path, *a, **k):
        if _path_under_repo_root(path):
            _repo_root_guard_fail("os.remove 于", path)
        return _orig["os.remove"](path, *a, **k)

    def _g_unlink(path, *a, **k):
        if _path_under_repo_root(path):
            _repo_root_guard_fail("os.unlink 于", path)
        return _orig["os.unlink"](path, *a, **k)

    def _g_rmdir(path, *a, **k):
        if _path_under_repo_root(path):
            _repo_root_guard_fail("os.rmdir 于", path)
        return _orig["os.rmdir"](path, *a, **k)

    def _g_rmtree(path, *a, **k):
        if _path_under_repo_root(path):
            _repo_root_guard_fail("shutil.rmtree 于", path)
        return _orig["shutil.rmtree"](path, *a, **k)

    def _g_rename(src, dst, *a, **k):
        if _path_under_repo_root(src):
            _repo_root_guard_fail("os.rename 于", src)
        return _orig["os.rename"](src, dst, *a, **k)

    def _g_replace(src, dst, *a, **k):
        if _path_under_repo_root(src):
            _repo_root_guard_fail("os.replace 于", src)
        return _orig["os.replace"](src, dst, *a, **k)

    def _g_move(src, dst, *a, **k):
        if _path_under_repo_root(src):
            _repo_root_guard_fail("shutil.move 于", src)
        return _orig["shutil.move"](src, dst, *a, **k)

    def _g_path_unlink(self, *a, **k):
        if _path_under_repo_root(self):
            _repo_root_guard_fail("Path.unlink 于", self)
        return _orig["Path.unlink"](self, *a, **k)

    def _g_path_rmdir(self, *a, **k):
        if _path_under_repo_root(self):
            _repo_root_guard_fail("Path.rmdir 于", self)
        return _orig["Path.rmdir"](self, *a, **k)

    os.remove = _g_remove
    os.unlink = _g_unlink
    os.rmdir = _g_rmdir
    shutil.rmtree = _g_rmtree
    os.rename = _g_rename
    os.replace = _g_replace
    shutil.move = _g_move
    pathlib.Path.unlink = _g_path_unlink
    pathlib.Path.rmdir = _g_path_rmdir
    try:
        yield
    finally:
        os.remove = _orig["os.remove"]
        os.unlink = _orig["os.unlink"]
        os.rmdir = _orig["os.rmdir"]
        shutil.rmtree = _orig["shutil.rmtree"]
        os.rename = _orig["os.rename"]
        os.replace = _orig["os.replace"]
        shutil.move = _orig["shutil.move"]
        pathlib.Path.unlink = _orig["Path.unlink"]
        pathlib.Path.rmdir = _orig["Path.rmdir"]


# ---------------------------------------------------------------------------
# ② 到这里才可以 import 业务模块
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from novelforge import config  # noqa: E402
from novelforge.core import db, library, pg  # noqa: E402
from novelforge.server import app  # noqa: E402


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """整轮跑完删掉会话级临时根：测试不该在磁盘上留东西。"""
    shutil.rmtree(_SESSION_ROOT, ignore_errors=True)
    # 防回归：跑完后确认仓库根关键跟踪文件没被误删（非致命告警）。
    _expected = [
        "config.yaml", "Dockerfile", ".gitattributes", ".gitignore",
        ".dockerignore", "README.md", "pytest.ini", "start.sh",
    ]
    import glob as _glob

    _missing = [f for f in _expected if not (_REPO_ROOT / f).is_file()]
    _req = _glob.glob(str(_REPO_ROOT / "requirements*.txt"))
    _compose = _glob.glob(str(_REPO_ROOT / "docker-compose*.yml"))
    if _missing or not _req or not _compose:
        print(
            "\n[REPO-ROOT GUARD] ⚠️ 仓库根关键文件缺失（可能被测试误删）："
            f" 缺失固定文件={_missing}  requirements*.txt={_req}  docker-compose*.yml={_compose}"
        )


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

def _quiesce_background() -> None:
    """收干净后台线程 —— **必须在 `db.close()` 之前调用**。

    两类要收的东西：

    1. **长驻轮询线程**：刮削 worker、文件监听 watcher（它们都会扫库 / 查库）；
    2. **旁路线程**：`watcher.auto_fetch_async` / `enqueue_scrape_async` 派生的线程 ——
       它们「发了就不管」，但同样要查库（`library.find` → `publish_dir` → `db.get_library`）。

    本套测试的 DB 是**用例级隔离**的（`db.close()` + `db.init()`）：线程晚一步动手就会
    在已关闭的连接上查库 —— 全量跑实测到过 **segfault**（跑到后半程解释器直接崩、
    连汇总行都打不出来）。与既有的「测试不养后台轮询」是同一条纪律。

    ⚠️ 第 39 期两处变化：

    - `db.close()` 现在自己持锁（读路径也纳入锁了），**段错误那条路已封死**；
      但残留线程仍会攥着旧连接去查下一个用例的库 ⇒ 用例级隔离照样破，仍必须收干净。
    - **`wait_pending()` 的返回值不再丢掉**：它返回「超时后仍未结束的数量」，
      非 0 就把这件事**说出来**。此前它被静默吞掉 —— 于是「收尾没干净」只表现为
      后面某个**无关**用例偶发变红（第 39 期实测：5 轮全量里 2 轮
      `library.get_library` 抛 `InterfaceError` 并被吞成 `None`，用户可见的后果是
      每库覆写静默回落全局值）。全量实测该值在干净运行下**恒为 0** ⇒ 硬失败不误伤。
    """
    left = 0
    try:
        from novelforge.core import scrape, watcher
        scrape.stop(timeout=2.0)
        left = watcher.wait_pending(5.0)
    except Exception:                                 # noqa: BLE001 —— 收尾动作本身失败不该让用例变红
        pass
    # 第 88 期：书目索引的**后台刷新线程**（`catalog._spawn_bg` 派生的那批，以及启动预热
    # `catalog.prewarm_async`）。它们都会查库，必须在 `db.close()` **之前**收干净 ——
    # 与 scrape / watcher / embed-refresh 同一条纪律（残留线程攥着旧连接查下一用例的库，
    # 全量跑实测到过 segfault）。
    try:
        from novelforge.core import catalog as _catalog
        left += _catalog.wait_pending(5.0)
    except Exception:                                 # noqa: BLE001
        pass
    try:
        from novelforge import server
        w = getattr(server, "WATCHER", None)
        if w is not None and w.is_running():
            w.stop()
        # 第 54 期：语义向量后台重算线程（/similar 自愈 / 扫描钩子派生）也要收干净
        if not server.wait_embed_refresh(5.0):
            left += 1
        # 第 81 期：长文件操作（移除书库清理 / 回收站还原）的后台任务同样要收干净 ——
        # 它们会 `shutil.move` 跨盘搬文件并写库（任务行 / 回收台账）。
        if not server.wait_background_ops(5.0):
            left += 1
    except Exception:                                 # noqa: BLE001
        pass
    if left:
        # `pytest.fail` 抛的 `Failed` 继承 BaseException ⇒ 不会被上面的 except 吞掉
        pytest.fail(
            f"收尾没干净：还有 {left} 个旁路线程没退出（等满 5s）。它们会攥着旧连接"
            "去查下一个用例的库。⚠️ 泄漏点可能在**更早**的用例，未必是当前这条 —— "
            "别再把这件事吞掉，去把那个线程收干净（见本函数与 `isolated` 的说明）。")


@pytest.fixture(autouse=True)
def _stop_scrape_worker():
    """每个用例结束后收干净后台线程（第 18 期；第 22 期扩到旁路线程）。

    接口用例（`POST /api/scrape/run`、单库扫描）会真的把 daemon worker 叫起来，
    而本套测试的 DB 是**用例级隔离**的（`db.close()` + `db.init()`）——
    一个跨用例活着的线程会拿着旧连接去查新库（还会 invalidate 全局扫描缓存），
    于是出现「单独跑必过、全量跑随机挂」的假故障。与 watcher 同一条纪律：
    **测试不养后台轮询**。这里带 timeout 等它真退出，不留窗口期。

    ⚠️ 时序上真正关键的那次收尾在 `isolated` 夹具里（它会在 `db.close()` **之前**收），
    这里只是兜底 —— 让「没用 `isolated` 的用例」也不留线程。
    """
    yield
    _quiesce_background()


#: 夹具 `isolated` 建的**本用例书库** id（根 = 该用例的 `OUTPUT_DIR`）。
#: 以前这行是产品自己播种的；第 37 期起产品不再建任何库，改由夹具显式建。
#: 值叫 "default" 纯属省事，**没有特殊含义**（产品侧已无「默认库」概念）。
TEST_LIB_ID = "default"


@pytest.fixture(scope="session")
def session_root() -> pathlib.Path:
    """会话级临时根（所有测试数据的父目录）。"""
    return _SESSION_ROOT


@pytest.fixture
def test_lib_id() -> str:
    """本用例那条书库的 id（= `TEST_LIB_ID`）；需要断言「书归到了这条库」时用它。"""
    return TEST_LIB_ID


@pytest.fixture(autouse=True)
def _no_notification_merge():
    """用例**默认关闭通知合并**（第 61 期）。

    合并窗口是**尾随去抖**：写一条不再立即落盘，同类型重复还会并成一条 ——
    这对大量既有用例是破坏性的（日志留存 / 轮转 / 按操作者过滤 / 清理都建立在
    「写一条即落一条」这个前提上）。合并本身由 `tests/test_notification_merge.py`
    专门钉住（那里显式打开窗口并断言合并与重置），这里只需要保证其余用例的确定性。
    """
    from novelforge.core import activity_log as al

    orig = al.merge_cfg
    al._pending.clear()
    al.merge_cfg = lambda: {"enabled": False, "window": 0}
    try:
        yield
    finally:
        al.merge_cfg = orig
        al._pending.clear()


@pytest.fixture
def isolated(monkeypatch, tmp_path: pathlib.Path) -> Iterator[None]:
    """**用例级隔离**：数据 / 导出 / 来源目录指向本用例专属路径，并重建一套空库。

    ⚠️ 会话级临时根只保证「不碰真实数据」；用例之间若共用同一套书库表，
    断言就会互相污染。所以碰书库或 DB 的用例都必须声明本夹具。

    注意：`server.py` 在 import 时把 `INPUT_DIR` / `OUTPUT_DIR` 拷成了模块级常量，
    因此**摄入类接口**的兜底目录仍指向会话级临时目录 —— 它们同样是临时目录，
    不会污染真实数据；本套测试也不覆盖摄入链路。
    """
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    # 收书目录也指到用例专属路径（第 93 期）：下载留档（`<名>.meta.json`）写在**原件旁边**，
    # 而原件落在收书目录 —— 追更的候选枚举按它算（`autoupdate.sidecar_of`）。
    #
    # ⚠️ **两处都要指，而且必须指成同一个**：`server.INPUT_DIR` 是 import 时的拷贝
    # （`server.py:217`，注释里那句「摄入类接口仍指向会话级临时目录」说的就是它）。
    # 只指 `config` 那一份的话，用例把文件写进 A、接口去 B 里找 —— 这正是第 93 期
    # 实测踩到的坑（`test_scan_background::test_convert_path` 立刻 404）。
    # 指成同一个之后，读写两侧仍然一致，且摄入链路也一并隔离到用例专属目录。
    monkeypatch.setattr(config, "INPUT_DIR", tmp_path / "input")
    from novelforge import server as _server_mod          # 延迟导入：本模块顶部只导了 app
    monkeypatch.setattr(_server_mod, "INPUT_DIR", tmp_path / "input")
    # ⚠️ 得**建出来**：会话级那个收书目录是 `config.ensure_dirs()` 建好的，而这里换成了
    # 一个全新路径 —— 上传接口（`/convert`、`/convert-path`）是直接往里写的，
    # 目录不在就是一句 `FileNotFoundError`，跟被测的口径毫无关系。
    (tmp_path / "input").mkdir(parents=True, exist_ok=True)
    # 第 41 期：多来源根。测试里就一个来源根 —— **第 97 期起它是「第一个来源根」的唯一读法**
    # （原先还有个 `config.LIBRARY_SOURCE_DIR` 别名，生产代码零引用、纯给测试用，已删）。
    # 同步让服务端的边界校验（normalize_source_dirs 只认 LIBRARY_SOURCE_ROOTS）放行 tmp_path 下的库根。
    monkeypatch.setattr(config, "LIBRARY_SOURCE_ROOTS",
                        [{"name": "libraries", "path": str(tmp_path / "libraries")}])
    db.close()
    # 第 62 期：PG 后端下「换一套空库」= 把 schema 整个重建。
    # SQLite 那条路不需要这一步 —— 上面那行 monkeypatch 已经把 DATA_DIR 指到一个
    # 全新的临时目录，`close()` 之后 `db_path()` 现算出来的就是一个空文件。
    # PG 没有「文件」这个抓手，于是把等价动作显式写在这里。
    #
    # ⚠️ 必须是**夹具**做，不能塞进 `db.close()`：`close()` 同时被那些「关掉再重开
    # 模拟一次重启」的升级用例用着，一删数据它们测的就是空气（见 db.close 的注释）。
    if _PG:
        pg.drop_schema()
    db.init()
    # 第 37 期：产品**不再播种任何书库**（全新部署就是 0 个库，等用户手建），
    # 所以这套测试自己建一条 —— 绝大多数用例都靠「往 `default_root` 放本书再扫描」
    # 起手，没有库就没有根可扫，`library.books()` 会直接是空的。
    #
    # id 沿用 "default" 只是省事：它**没有任何特殊含义**了，产品侧「默认库」
    # 这个概念已经整个下线（`DEFAULT_LIBRARY_ID` / `default_library()` /
    # `ensure_default_library()` 都已删除），`"default"` 现在只是个普通 id 字符串。
    db.create_library(TEST_LIB_ID, "测试书库", "mixed",
                      source_dirs=str(config.OUTPUT_DIR), sort_order=0)
    library.invalidate()
    try:
        yield
    finally:
        # ⚠️ 顺序不能反：先让后台线程收干净，再关连接。反过来就是「线程在已关闭的
        # 连接上查库」，本仓实测到过 segfault（见 `_quiesce_background` 的说明）。
        _quiesce_background()
        db.close()


@pytest.fixture
def default_root(isolated) -> pathlib.Path:  # noqa: ARG001 —— 依赖 isolated 完成目录切换
    """本用例那条书库的根目录（= 本用例的 `OUTPUT_DIR`）。

    名字带 default 是历史包袱（产品侧已无「默认库」）；语义就是「起手那个库」。
    """
    return pathlib.Path(config.OUTPUT_DIR)


@pytest.fixture
def client(isolated) -> Iterator[TestClient]:  # noqa: ARG001
    """走过 lifespan 的 TestClient（自动建表；**不再播种书库**，见 `isolated`）。

    依赖 `isolated`：去掉它就会连到会话级共享库上，断言互相污染。
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client: TestClient) -> dict:
    """已登录的请求头。`/api/*` 没有它一律 401（见 server 的鉴权中间件）。"""
    r = client.post("/api/auth/login", json={"user": TEST_USER, "pin": TEST_PIN})
    assert r.status_code == 200, f"登录失败：{r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_book(root, name: str, content: bytes = b"EPUB") -> pathlib.Path:
    """占位书文件（自动建父目录）。

    内容可以是任意字节：扫描只按扩展名收书，`library.probe_epub()` 全程容错
    （解析不出只记进 `issues`，不抛）—— 所以**不需要**构造真实 EPUB。
    """
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _make_audio_dir(root, name: str, tracks: int = 2) -> pathlib.Path:
    """有声书**目录形态**（一章一文件）：目录 = 一本书，`format` = AUDIO。"""
    d = pathlib.Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, int(tracks) + 1):
        (d / f"{i:02d}.mp3").write_bytes(b"MP3")
    return d


@pytest.fixture
def make_book():
    return _make_book


@pytest.fixture
def make_audio_dir():
    return _make_audio_dir


#: 第 76 期：自建「带插图 + 样式表」的最小 EPUB 用的 OPF / container。
#: 结构刻意贴真实 EPUB —— `OEBPS/{Text,Styles,Images}`，章节里的引用写成 `../Images/pic.png`。
_EPUB_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>插图测试</dc:title>
    <dc:identifier id="uid">test-assets</dc:identifier>
    <dc:language>zh</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="Text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="s1" href="Styles/style.css" media-type="text/css"/>
    <item id="img" href="Images/pic.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>
"""

_EPUB_CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_EPUB_DEFAULT_CHAPTER = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>一</title></head>'
    '<body><p>正文</p><img src="../Images/pic.png" alt="图"/></body></html>'
)


def _build_epub_with_assets(root, name: str = "插图书.epub", *,
                            chapter: str = "", css: str = "", extra_css: str = ""):
    """造一本**带插图与样式表**的最小 EPUB，返回文件路径。

    `epub_builder.build_epub` 只产纯文本章节（既没有插图、也没有样式表），而第 76 期
    的主题恰恰是这两样 —— 所以自己拼 zip。`extra_css` 会落在 `Styles/sub/` 子目录里，
    用来验证「`@import` 的相对路径以**被导入文件自己**为基准解析」。
    """
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _EPUB_CONTAINER)
        z.writestr("OEBPS/content.opf", _EPUB_OPF)
        z.writestr("OEBPS/Text/chapter1.xhtml", chapter or _EPUB_DEFAULT_CHAPTER)
        if css:
            z.writestr("OEBPS/Styles/style.css", css)
        if extra_css:
            z.writestr("OEBPS/Styles/sub/extra.css", extra_css)
        z.writestr("OEBPS/Images/pic.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return p


@pytest.fixture
def make_epub():
    """→ `_build_epub_with_assets(root, name, chapter=…, css=…, extra_css=…)`（第 76 期）。"""
    return _build_epub_with_assets


@pytest.fixture
def make_library(isolated) -> "callable":  # noqa: ARG001
    """登记一个书库实体（`root` 需要本地路径；**只登记，不动文件**）。

    刻意依赖 `isolated`：这样「用了它却没隔离」在写法上就不可能 ——
    否则会把测试数据写进会话级共享库，后一个用例的断言就被前一个污染了。
    """

    def _make(lid: str, name: str, ltype: str, root, mode: str = "inplace",
              source_subdir: str = "", rules: str = "",
              allowed_exts: str = "", exclude: str = "") -> dict:
        r = pathlib.Path(root)
        r.mkdir(parents=True, exist_ok=True)
        # 第 41 期：内容来源 = 多个文件夹的绝对路径（就地引用）。老接口的 `root_path` 即扫描
        # 文件夹本体，`source_subdir` 只是展示用的相对子目录（不拼进路径、不落库）；`mode`
        # 参数已无意义（只剩就地引用），保留签名兼容、忽略之。
        dirs = str(r)
        lib = db.create_library(lid, name, ltype, source_dirs=dirs, rules=rules,
                               allowed_exts=allowed_exts, exclude=exclude)
        library.invalidate()
        return lib

    return _make
