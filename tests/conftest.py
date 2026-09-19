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
- 造数据用 `make_book` / `make_audio_dir` / `make_library`，别自己在测试里拼路径。
"""
import os
import pathlib
import shutil
import sys
import tempfile
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
# ② 到这里才可以 import 业务模块
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from novelforge import config  # noqa: E402
from novelforge.core import db, library  # noqa: E402
from novelforge.server import app  # noqa: E402


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """整轮跑完删掉会话级临时根：测试不该在磁盘上留东西。"""
    shutil.rmtree(_SESSION_ROOT, ignore_errors=True)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _stop_scrape_worker():
    """每个用例结束后停掉**刮削 worker**（第 18 期）。

    接口用例（`POST /api/scrape/run`、单库扫描）会真的把 daemon worker 叫起来，
    而本套测试的 DB 是**用例级隔离**的（`db.close()` + `db.init()`）——
    一个跨用例活着的线程会拿着旧连接去查新库（还会 invalidate 全局扫描缓存），
    于是出现「单独跑必过、全量跑随机挂」的假故障。与 watcher 同一条纪律：
    **测试不养后台轮询**。这里带 timeout 等它真退出，不留窗口期。
    """
    yield
    try:
        from novelforge.core import scrape
        scrape.stop(timeout=2.0)
    except Exception:                                 # noqa: BLE001 —— 收尾失败不该让用例变红
        pass


@pytest.fixture(scope="session")
def session_root() -> pathlib.Path:
    """会话级临时根（所有测试数据的父目录）。"""
    return _SESSION_ROOT


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
    monkeypatch.setattr(config, "LIBRARY_SOURCE_DIR", tmp_path / "libraries")
    db.close()
    db.init()
    library.ensure_default_library()
    library.invalidate()
    try:
        yield
    finally:
        db.close()


@pytest.fixture
def default_root(isolated) -> pathlib.Path:  # noqa: ARG001 —— 依赖 isolated 完成目录切换
    """默认书库的根目录（= 本用例的 `OUTPUT_DIR`）。"""
    return pathlib.Path(config.OUTPUT_DIR)


@pytest.fixture
def client(isolated) -> Iterator[TestClient]:  # noqa: ARG001
    """走过 lifespan 的 TestClient（自动建表 + 落默认书库）。

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


@pytest.fixture
def make_library(isolated) -> "callable":  # noqa: ARG001
    """登记一个书库实体（`root` 需要本地路径；**只登记，不动文件**）。

    刻意依赖 `isolated`：这样「用了它却没隔离」在写法上就不可能 ——
    否则会把测试数据写进会话级共享库，后一个用例的断言就被前一个污染了。
    """

    def _make(lid: str, name: str, ltype: str, root, mode: str = "inplace",
              source_subdir: str = "", rules: str = "") -> dict:
        r = pathlib.Path(root)
        r.mkdir(parents=True, exist_ok=True)
        lib = db.create_library(lid, name, ltype, mode, str(r),
                               source_subdir=source_subdir, rules=rules)
        library.invalidate()
        return lib

    return _make
