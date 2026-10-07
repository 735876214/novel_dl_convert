"""第 112 期：容器**自动展开**契约（默认开启、可关；源容器原样保留）。

口径（用户拍板）：打进库里的压缩包（`.zip` / `.rar` / `.7z`）若是「里面装的是别的书」，
后台**按间隔自动**展开成可读书 —— **默认开启、可关**；展开成功后**源容器原样保留**
（只新增文件，不移动也不删）。手动入口（工具 → 书库管理 → 副本与容器）仍在，对自动失败的
容器兜底。

实现落点：`watcher.FolderWatcher._auto_unpack_tick()`，跑在**既有的监听线程**里
（不新起线程 —— 本仓有「新增旁路线程必须进 `tests/conftest.py::_quiesce_background`
收尾清单」的硬规矩），节流到 `index_interval`，幂等标记落 `app_state`（键 `autounpack:{bid}`
存**源指纹**：容器不可变 ⇒ 源一改指纹就变、自然重试；坏包也不会每轮刷屏）。

⚠️ **`.7z` 是本文件唯一能现场造真归档的容器**（`py7zr` 已在 `requirements.txt`）。
`.rar` 无法用纯 Python 造（需要 `rar` 二进制）⇒ **只测判据不伪造样本** —— 拿一个假装成
`.rar` 的文件测「它在自动展开的候选里」这一条，绝不用假归档冒充真解压。
"""

import pathlib

import pytest

from novelforge import config
from novelforge.core import db, library, watcher, zipkind

pytest.importorskip("py7zr", reason="`.7z` 容器需要 py7zr（requirements.txt 里已有）")

#: 容器里那份「别的书」（内容任意字节：展开只做字节搬运，不解析）
_DOC = b"%PDF-1.4\n" + b"fake-pdf-payload" * 8


def _make_7z(path: pathlib.Path, entries: "dict[str, bytes]") -> pathlib.Path:
    """造一个**真的** `.7z`（本文件不伪造归档）。"""
    import py7zr
    path.parent.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(str(path), "w") as z:
        for name, data in entries.items():
            z.writestr(data, name)
    return path


def _put_root(root, name: str, data: bytes) -> pathlib.Path:
    """往库根放一个文件（`isolated` 只建了收书目录，库根要自己建）。"""
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _watcher(cfg_libs: dict) -> watcher.FolderWatcher:
    """造一个只用于调 `_auto_unpack_tick` 的监听器（**不 start**，不起线程）。"""
    w = watcher.FolderWatcher(
        input_dir=config.INPUT_DIR, output_dir=config.OUTPUT_DIR,
        cfg={"libraries": cfg_libs, "watcher": {"interval": 5.0}})
    w.index_interval = 0.0          # 关掉节流（默认 60s）：用例里要立刻跑一轮
    return w


def _scan():
    library.invalidate()
    return {b["name"]: b for b in library.books()}


# ---------------------------------------------------------------------------
# 默认开启：展开了、源还在
# ---------------------------------------------------------------------------

def test_默认开启时容器被自动展开且源容器原样保留(isolated, default_root):  # noqa: ARG001
    _make_7z(pathlib.Path(default_root) / "合集.7z", {"内层书.pdf": _DOC})
    books = _scan()
    assert "合集.7z" in books, f"`.7z` 该被收成一本书（容器）：{sorted(books)}"
    assert str(books["合集.7z"]["format"]).upper() == "7Z"

    src = pathlib.Path(default_root) / "合集.7z"
    before = (src.stat().st_size, src.stat().st_mtime_ns)

    _watcher({"auto_unpack": True})._auto_unpack_tick()

    out = pathlib.Path(default_root) / "内层书.pdf"
    assert out.is_file(), "容器里那份文档该被展开到容器所在目录"
    assert out.read_bytes() == _DOC, "展开出来的内容必须与容器里那份逐字节相同"
    # **源容器原样保留**（用户口径：只新增文件，不移动也不删）
    assert src.is_file()
    assert (src.stat().st_size, src.stat().st_mtime_ns) == before


def test_关掉开关后不再自动展开(isolated, default_root):  # noqa: ARG001
    _make_7z(pathlib.Path(default_root) / "不开.7z", {"没展开.pdf": _DOC})
    _scan()

    _watcher({"auto_unpack": False})._auto_unpack_tick()
    assert not (pathlib.Path(default_root) / "没展开.pdf").exists(), \
        "关掉开关后后台**不许**再动用户的文件"


def test_开关缺省视同开启(isolated, default_root):  # noqa: ARG001
    """老配置里没有这个键（升级上来的）⇒ 取默认值 **True**，与 `config.DEFAULTS` 同口径。"""
    assert config.DEFAULTS["libraries"]["auto_unpack"] is True
    _make_7z(pathlib.Path(default_root) / "缺省.7z", {"缺省展开.pdf": _DOC})
    _scan()
    _watcher({})._auto_unpack_tick()
    assert (pathlib.Path(default_root) / "缺省展开.pdf").is_file()


# ---------------------------------------------------------------------------
# 幂等：源没变就不重复展开（展开要开归档，绝不能每轮都跑）
# ---------------------------------------------------------------------------

def test_幂等_第二轮不再动同一个容器(isolated, default_root, monkeypatch):  # noqa: ARG001
    _make_7z(pathlib.Path(default_root) / "幂等.7z", {"幂等.pdf": _DOC})
    books = _scan()
    bid = books["幂等.7z"]["id"]

    calls: list = []
    real = zipkind.unpack

    def spy(path, **kw):
        calls.append(str(path))
        return real(path, **kw)

    # `_auto_unpack_tick` 里是函数内 `from . import db, zipkind` ⇒ 打模块属性即可生效
    monkeypatch.setattr(zipkind, "unpack", spy)

    w = _watcher({})
    w._auto_unpack_tick()
    assert len(calls) == 1
    assert db.state_get(f"autounpack:{bid}"), "跑过一轮后该留下源指纹标记"
    assert (pathlib.Path(default_root) / "幂等.pdf").is_file()

    w._auto_unpack_tick()
    assert len(calls) == 1, "源指纹没变 ⇒ 第二轮不许再开一次归档"

    # 源改了（重造一份内容不同的）⇒ 指纹变 ⇒ 该重试（用户换了个新包进去）
    src = pathlib.Path(default_root) / "幂等.7z"
    src.unlink()
    _make_7z(src, {"幂等2.pdf": _DOC})
    library.invalidate()
    w._auto_unpack_tick()
    assert len(calls) == 2, "容器换了 ⇒ 指纹变 ⇒ 自然重试"
    assert (pathlib.Path(default_root) / "幂等2.pdf").is_file()


def test_坏容器如实标记且不阻塞(isolated, default_root):  # noqa: ARG001
    """坏包既不能把监听线程打崩，也不能每轮重试一遍（标记**无论成败**都写）。"""
    bad = _put_root(default_root, "坏包.7z", b"this is not a 7z archive at all")
    books = _scan()
    bid = books["坏包.7z"]["id"]

    w = _watcher({})
    w._auto_unpack_tick()           # 不抛 = 通过
    assert db.state_get(f"autounpack:{bid}"), "失败也要记指纹，否则坏包每轮都重试"
    assert bad.read_bytes() == b"this is not a 7z archive at all", "坏包不许被改动"


# ---------------------------------------------------------------------------
# 撞名：不覆盖（与手动展开同一条纪律）
# ---------------------------------------------------------------------------

def test_撞名不覆盖已有文件(isolated, default_root):  # noqa: ARG001
    _make_7z(pathlib.Path(default_root) / "撞名.7z", {"撞名.pdf": _DOC})
    existed = _put_root(default_root, "撞名.pdf", "用户自己放在这儿的，一个字节都不许动".encode())
    _scan()

    _watcher({})._auto_unpack_tick()
    assert existed.read_bytes() == "用户自己放在这儿的，一个字节都不许动".encode(), \
        "撞名该跳过并如实报，**绝不覆盖**已有文件"


# ---------------------------------------------------------------------------
# 候选判据：哪些容器进自动展开清单
# ---------------------------------------------------------------------------

def test_候选只有容器格式且判据同源(isolated, default_root):  # noqa: ARG001
    """自动展开的候选 = `format ∈ zipkind.CONTAINER_FORMATS`（**唯一判据**，不手写第二份）。"""
    assert set(zipkind.CONTAINER_FORMATS) == {"ZIP", "RAR", "7Z"}
    assert zipkind.CONTAINER_EXTS == (".zip", ".rar", ".7z")

    # 非容器（EPUB）即便丢进库也不该被本机制碰
    _put_root(default_root, "普通书.epub", b"EPUB")
    _scan()
    _watcher({})._auto_unpack_tick()      # 不抛、且不会去开它（没有可断言的副作用即通过）
    assert (pathlib.Path(default_root) / "普通书.epub").read_bytes() == b"EPUB"


def test_RAR在候选里但不伪造样本(isolated, default_root):  # noqa: ARG001
    """`.rar` 造不出来（需要 `rar` 二进制）⇒ **只测判据**：它会被收成容器书、进候选。

    这里刻意**不**造一个假 `.rar` 冒充真归档 —— 那测的是「错误路径」而不是「能解压」。
    """
    _put_root(default_root, "假装.rar", b"not a real rar")
    books = _scan()
    assert str(books["假装.rar"]["format"]).upper() == "RAR"
    assert "RAR" in zipkind.CONTAINER_FORMATS


# ---------------------------------------------------------------------------
# 配置三处同步（写这一格的地方只有一处能漏）
# ---------------------------------------------------------------------------

def test_配置可写且能回显(client, auth_headers):  # noqa: ARG001
    """`libraries.auto_unpack` 必须在**可写白名单**里，且回显要跟着走（否则是个假开关）。"""
    from novelforge import server
    assert "auto_unpack" in (server.EDITABLE.get("libraries") or {})
    assert "index_interval" not in (server.EDITABLE.get("libraries") or {}), \
        "索引间隔不是给用户拧的旋钮，别顺手放进来"

    assert client.put("/api/config", json={"libraries": {"auto_unpack": False}},
                      headers=auth_headers).status_code == 200
    cfg = client.get("/api/config", headers=auth_headers).json()
    assert cfg["config"]["libraries"]["auto_unpack"] is False

    k = client.get("/api/library-containers", headers=auth_headers).json()
    assert k["auto_unpack"] is False, "清单接口要一并回显（前端面板靠它取初值）"

    assert client.put("/api/config", json={"libraries": {"auto_unpack": True}},
                      headers=auth_headers).status_code == 200
    assert client.get("/api/config", headers=auth_headers).json()[
        "config"]["libraries"]["auto_unpack"] is True


def test_保存配置后监听器热生效(isolated, default_root, monkeypatch):  # noqa: ARG001
    """保存配置时 `server._apply_watcher_config` 会把最新 cfg（**含 `libraries`**）刷进 `WATCHER`

    ⇒ 开关**无需重启进程**。开着「保存了但后台还按老配置跑」正是本仓点名的「假开关」。

    这里只钉**传播机制**（`WATCHER.cfg = config.load_config()`）—— 不真起监听线程
    （`is_running` 置真即可让那一支空转，见 `_apply_watcher_config` 的启停判据）。
    """
    from novelforge import server
    w = _watcher({"auto_unpack": True})
    monkeypatch.setattr(w, "is_running", lambda: True)      # 免得它真去 start() 一个线程
    monkeypatch.setattr(server, "WATCHER", w)
    monkeypatch.setattr(config, "load_config", lambda: {
        "libraries": {"auto_unpack": False}, "watcher": {"enabled": True}})

    server._apply_watcher_config()
    assert (w.cfg or {}).get("libraries", {}).get("auto_unpack") is False


def test_展开后书库被标脏以便重新索引(isolated, default_root):  # noqa: ARG001
    """展开出来的新文件必须能被书架看见 —— 展开成功后要 `library.invalidate`。"""
    _make_7z(pathlib.Path(default_root) / "新书.7z", {"展开出来的书.pdf": _DOC})
    _scan()
    _watcher({})._auto_unpack_tick()
    library.invalidate()
    names = {b["name"] for b in library.books()}
    assert "展开出来的书.pdf" in names
    assert "新书.7z" in names, "源容器保留 ⇒ 它自己也照样在架（用户可自行决定删不删）"


# ---------------------------------------------------------------------------
# 线程纪律：不新起线程（否则要在 `_quiesce_background` 收尾清单里加条目）
# ---------------------------------------------------------------------------

def test_不新起线程(isolated, default_root):  # noqa: ARG001
    import threading
    _make_7z(pathlib.Path(default_root) / "线程.7z", {"线程.pdf": _DOC})
    _scan()
    before = {t.ident for t in threading.enumerate()}
    w = _watcher({})
    w._auto_unpack_tick()
    assert {t.ident for t in threading.enumerate()} <= before, \
        "自动展开必须跑在既有监听线程里，不新起线程"


def test_不碰书库外的文件(isolated, default_root, tmp_path):  # noqa: ARG001
    """只往**容器所在目录**落文件 —— 别把解出来的东西丢到别处。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    _make_7z(pathlib.Path(default_root) / "定位.7z", {"定位.pdf": _DOC})
    _scan()
    _watcher({})._auto_unpack_tick()
    assert (pathlib.Path(default_root) / "定位.pdf").is_file()
    assert sorted(p.name for p in outside.iterdir()) == []


def test_手动展开仍在且默认不删源(isolated, default_root):  # noqa: ARG001
    """自动展开落地后，手动的 `zipkind.unpack` 语义**一个字不改**（默认留源）。"""
    src = _make_7z(pathlib.Path(default_root) / "手动.7z", {"手动.pdf": _DOC})
    res = zipkind.unpack(src)
    assert res["ok"] is True and res["source_removed"] is False
    assert src.is_file(), "默认 `remove_source=False` ⇒ 源照旧在"
    assert (pathlib.Path(default_root) / "手动.pdf").is_file()


def test_一轮只展开一层不递归(isolated, default_root):  # noqa: ARG001
    """一次 `unpack` **只解开一层**（`zipkind` 的既有口径），不是「一次调用递归拆到底」。

    嵌套归档被提取出来后**自己是新的书目条目**：下一轮才轮得到它（幂等标记按 `book_id`
    走，内层是新 id）。这条用例钉的是**单轮只有一层**这个边界 —— 免得有人把递归塞进
    `unpack` 里（那会让「撞名 / 坏包」的处置路径一次面对一棵树）。
    """
    import zipfile

    import py7zr
    inner = _put_root(default_root, "内层.zip", b"")
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("还要一层.pdf", _DOC)
    nested = pathlib.Path(default_root) / "嵌套.7z"
    with py7zr.SevenZipFile(str(nested), "w") as z:
        z.write(str(inner), "内层.zip")
    inner.unlink()                      # 只留那个 7z；它内含一个 zip

    _scan()
    _watcher({})._auto_unpack_tick()
    assert (pathlib.Path(default_root) / "内层.zip").is_file(), "内层归档该被提取出来"
    assert not (pathlib.Path(default_root) / "还要一层.pdf").exists(), \
        "**同一轮**里不许递归拆到底"
