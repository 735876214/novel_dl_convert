"""第 125 期：第二轮「格式识别与入库」审查的五条修复（契约）。

每条都对应一个用户看得见的错误现象，不是实现细节：

1. **隐藏文件 / 系统影子文件被当成书**：macOS 拷进 NAS 的每本书旁边都有一个
   ``._书名.epub``（AppleDouble 资源叉，200 来字节），此前它会成为一本
   ``title="._书名"``、``issues=["unparsable"]`` 的书 —— 书架里凭空多出一倍条目。
   收书侧（watcher）本来就过滤隐藏项，是**库扫描侧**漏了，两条摄入路径口径不一。
2. **「没有可接收的库」被记成失败**：用户先把文件丢进收书目录、几分钟后才去建库 ——
   此前 3 轮之后该文件被**永久跳过**，建完库也不会自己进来，只能手动「忘记失败」。
   这不是这个文件的毛病，是等条件。
3. **容器单条目解压无上限**：上传侧只限**压缩后**字节，而 zip 的压缩比可以到 ~1000:1
   ⇒ 一个 65 KB 的 ``.cbz`` 能让 ``GET /api/books/{bid}/comic/0`` 吐出 64 MB；
   换成零填充就是一次 OOM。
4. **符号链接被当作库内书籍**：``外部链接.txt -> /xxx/secret`` 进了书目，
   正文接口把库外内容原样发出去。
5. **同名覆盖换了内容、进度静默跟随**：``book_id`` 由路径派生 ⇒ 换内容不换 id，
   阅读位置与批注继续指到新正文上，而界面上一个字都不提示。
"""
import pathlib
import zipfile

import pytest

from novelforge import config
from novelforge.core import catalog, comics, db, library, zipkind
from novelforge.core.watcher import FolderWatcher

#: 1×1 PNG（真字节；`comics` 只看后缀不看内容，但 unpack 那侧会校验扩展名）
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010a2db40000000049454e44ae426082")


def _cbz(target, pages: dict, compression=zipfile.ZIP_STORED):
    target = pathlib.Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression) as z:
        for name, data in pages.items():
            z.writestr(name, data)
    return target


def _names(lib_id):
    return [b["name"] for b in library.books(lib_id)]


def _by_name(lib_id, name):
    for b in library.books(lib_id):
        if b["name"] == name:
            return b
    raise AssertionError(f"书目里没有 {name}：{[b['name'] for b in library.books(lib_id)]}")


def _put(root, rel: str, data: bytes = b"x") -> pathlib.Path:
    p = pathlib.Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


# ---------------------------------------------------------------------------
# 1. 隐藏文件与系统影子文件不入书目（两条摄入路径同一个判据）
# ---------------------------------------------------------------------------

def test_is_hidden_name_是唯一隐藏判据():
    """点开头就是隐藏（`.DS_Store` / `.隐藏书.txt` / `._三体.epub` 一视同仁）。"""
    assert library.is_hidden_name(".隐藏书.txt")
    assert library.is_hidden_name("._三体.epub")        # AppleDouble 资源叉
    assert library.is_hidden_name(".DS_Store")
    assert not library.is_hidden_name("三体.epub")
    assert not library.is_hidden_name("说明.txt")
    assert not library.is_hidden_name("a.b.epub")      # 中间的点不算


def test_隐藏文件与苹果双份影子文件都不进书目(isolated, tmp_path, make_library):  # noqa: ARG001
    root = tmp_path / "root"
    lib = make_library("hid", "隐藏库", "mixed", root)
    _put(root, ".隐藏书.txt", "偷偷的".encode())
    # AppleDouble：macOS 在 NAS 上给每个文件配的资源叉（200 来字节，不是书）
    _put(root, "._三体.epub", b"\x00\x05\x16\x07" + b"\x00" * 200)
    _put(root, "看得见.txt", "正文".encode())

    names = _names(lib["id"])
    assert names == ["看得见.txt"], f"隐藏项漏进书目：{names}"


# ---------------------------------------------------------------------------
# 2. 符号链接：指向库根外的**不算本库的书**，根内的照旧
# ---------------------------------------------------------------------------

def test_指向库根外的符号链接不算这本书(isolated, tmp_path, make_library):  # noqa: ARG001
    root = tmp_path / "root"
    lib = make_library("ln", "链接库", "mixed", root)
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET-OUTSIDE-ROOT", encoding="utf-8")
    _put(root, "真书.txt", "正文".encode())
    (root / "外部链接.txt").symlink_to(outside)

    names = _names(lib["id"])
    assert names == ["真书.txt"], f"库外链接漏进书目：{names}"


def test_指向库根内的符号链接照旧收录(isolated, tmp_path, make_library):  # noqa: ARG001
    """根内链接是一种正常用法（同一本书两处可见），必须照旧收录、不能一刀切禁掉。"""
    root = tmp_path / "root"
    lib = make_library("ln2", "链接库2", "mixed", root)
    real = _put(root, "真书.txt", "正文".encode())
    (root / "别名.txt").symlink_to(real)

    names = _names(lib["id"])
    assert "别名.txt" in names, f"根内链接被误杀：{names}"


# ---------------------------------------------------------------------------
# 3. 容器单条目解压上限
# ---------------------------------------------------------------------------

def test_单条目超上限时取页抛EntryTooLarge(tmp_path, monkeypatch):
    """把上限调到 1 KB，放一条 4 KB 的页 ⇒ 取页必须**如实报错**，不是回空。"""
    monkeypatch.setattr(comics, "MAX_ENTRY_BYTES", 1024)
    p = _cbz(tmp_path / "炸弹.cbz", {"001.png": PNG + b"\x00" * 4096})

    with pytest.raises(comics.EntryTooLarge) as ei:
        comics.page_bytes(p, 0)
    assert "超过上限" in str(ei.value)

    # 正常大小的页不受影响（别把闸门做成「谁都不能读」）
    small = _cbz(tmp_path / "正常.cbz", {"001.png": PNG})
    data, media = comics.page_bytes(small, 0)
    assert data == PNG and media == "image/png"


def test_展开时超上限的那条只跳过它自己(tmp_path, monkeypatch):
    """`zipkind.unpack` 里一条超限 ⇒ 该条 `ok=False` + 人话原因，其余照常落盘。"""
    monkeypatch.setattr(comics, "MAX_ENTRY_BYTES", 1024)
    src = tmp_path / "in" / "容器.zip"
    # 必须是**要展开的容器**：里面有 2 份文档才判 `multi`（图片容器直接按漫画读，
    # 根本不会展开 —— 那种容器里没有「解压超限」这条路可走）。
    _cbz(src, {"书.epub": b"EPUB" * 10, "巨无霸.epub": b"EPUB" + b"\x00" * 4096})

    out = zipkind.unpack(src)
    by_dest = {a["dest"]: a for a in out["actions"]}
    big = next(a for d, a in by_dest.items() if d.endswith("巨无霸.epub"))
    assert big["ok"] is False and "超过上限" in big["note"]
    small = next(a for d, a in by_dest.items() if d.endswith("书.epub"))
    assert small["ok"] is True, f"其它条目被连坐：{out['actions']}"
    assert (src.parent / "书.epub").read_bytes() == b"EPUB" * 10


def test_漫画页接口超限回413(client, auth_headers, isolated, tmp_path, make_library,
                            monkeypatch):  # noqa: ARG001
    root = tmp_path / "comics"
    lib = make_library("cmx", "漫画库", "comic", root)
    _cbz(root / "炸弹.cbz", {"001.png": PNG + b"\x00" * 4096})
    bid = _by_name(lib["id"], "炸弹.cbz")["id"]

    monkeypatch.setattr(comics, "MAX_ENTRY_BYTES", 1024)
    r = client.get(f"/api/books/{bid}/comic/0", headers=auth_headers)
    assert r.status_code == 413, r.text
    assert "超过上限" in r.text


# ---------------------------------------------------------------------------
# 4. 「没有可接收的库」= 等条件，不消耗重试次数
# ---------------------------------------------------------------------------

def _watcher(**kw):
    cfg = {"watcher": {"enabled": True, "copy_non_txt": True}}
    cfg["watcher"].update(kw)
    return FolderWatcher(cfg=cfg)


def test_没有可接收的库时返回waiting(isolated, tmp_path):  # noqa: ARG001
    w = _watcher()
    p = _put(tmp_path / "input", "投递.zip", b"PK\x03\x04")
    monkeypatch_ok = w._target
    w._target = lambda _p: (None, None)          # 模拟「一个库都不收它」
    try:
        kind, detail = w.handle_file(p)
    finally:
        w._target = monkeypatch_ok
    assert kind == "waiting", f"应该是等条件而不是失败：{kind} / {detail}"
    assert "没有可接收的书库" in detail


def test_等条件的文件不会撞上重试上限(isolated, tmp_path):  # noqa: ARG001
    """连扫 5 轮（> 默认 max_retries=3）都必须**继续尝试**：建库后它就该自己进来。"""
    w = _watcher()
    w.max_retries = 3
    inp = pathlib.Path(config.INPUT_DIR)
    _put(inp, "投递.zip", b"PK\x03\x04")

    calls = []

    def _fake_handle(p, owner_lib=None, owner_root=None):
        calls.append(p.name)
        return ("waiting", "没有可接收的书库：缺一个漫画库")

    w.handle_file = _fake_handle
    for _ in range(5):
        w._scan_locked(inp, tkey="input")

    assert len(calls) == 5, f"第 4 轮起被永久跳过了（只试了 {len(calls)} 次）"
    assert w.stats["waiting"] >= 5
    assert w.stats["failed"] == 0, "等条件被记成了失败"


def test_真失败仍然照旧撞上限(isolated, tmp_path):  # noqa: ARG001
    """对照：真正的失败（坏文件）不能被这条放行 —— 否则坏文件会无限刷日志。"""
    w = _watcher()
    w.max_retries = 3
    inp = pathlib.Path(config.INPUT_DIR)
    _put(inp, "坏文件.zip", b"PK\x03\x04")

    calls = []

    def _fake_handle(p, owner_lib=None, owner_root=None):
        calls.append(p.name)
        return ("failed", "解不开")

    w.handle_file = _fake_handle
    for _ in range(5):
        w._scan_locked(inp, tkey="input")

    assert len(calls) == 3, f"失败该在 3 次后停手，实际试了 {len(calls)} 次"


# ---------------------------------------------------------------------------
# 5. 同名覆盖 ⇒ replaced 标记
# ---------------------------------------------------------------------------

def test_同名覆盖后标记为replaced(isolated, tmp_path, make_library):  # noqa: ARG001
    root = tmp_path / "root"
    lib = make_library("rep", "覆盖库", "mixed", root)
    p = _put(root, "同名书.txt", "旧正文".encode())
    lib = db.get_library(lib["id"])
    catalog.refresh_library(lib, force=True)
    assert "replaced" not in _by_name(lib["id"], "同名书.txt")["issues"]

    # 覆盖成**另一本书**（体积与 mtime 都变）
    p.write_text("换了一整本完全不同的长正文" * 50, encoding="utf-8")
    out = catalog.refresh_library(lib)
    assert out["added"] == 1

    b = _by_name(lib["id"], "同名书.txt")
    assert "replaced" in b["issues"], f"覆盖没有留下任何痕迹：{b['issues']}"


def test_没变过的书不会被误标replaced(isolated, tmp_path, make_library):  # noqa: ARG001
    root = tmp_path / "root"
    lib = make_library("rep2", "覆盖库2", "mixed", root)
    _put(root, "安静.txt", "正文".encode())
    lib = db.get_library(lib["id"])
    catalog.refresh_library(lib, force=True)
    out = catalog.refresh_library(lib)
    assert out["unchanged"] == 1
    assert "replaced" not in _by_name(lib["id"], "安静.txt")["issues"]


def test_issues_of_只依赖文件事实():
    """`replaced` 与其它 issue 同级、由 `_issues_of` 单点产出（不是第二份实现）。"""
    assert library._issues_of("a.txt", 10, False, False, False, True) == ["replaced"]
    assert library._issues_of("a.txt", 10, False, False, False, False) == []
    assert "zero-bytes" in library._issues_of("a.txt", 0, False, False, False, True)
