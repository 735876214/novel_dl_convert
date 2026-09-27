"""收书目录（Book Dock）的单项操作（第 65 期）。

这条链路此前**零后端测试** —— 第 65 期给它加了「重命名」与「入库到…」两个动作，
正好把地基一起钉住：

- 改名的八条前置（不存在 / 已就绪 / 换扩展名 / 非法字符 / 清洗成空 / 同名幂等 /
  重名 / 命中忽略清单），每条都断言**磁盘与登记行一个字段都没动**；
- 入库目标的三条校验（库存在 / 文件夹属于该库 / 该库收得了这个格式）；
- 以及最容易悄悄破的那条：**不指定目标时行为与第 65 期之前逐字一致**。

这里也钉住两个**顺序**上的约定（看代码看不出，只能靠用例）：
① 目标校验在 `db.dock_update(status="pending")` **之前** —— 被拒的条目不该从
「出错」变成「待处理」；② 改名失败时**磁盘与库两边都不动**（不能只改一边）。

全部离线：扫描只按扩展名收书，不需要真 EPUB。
"""
import json
import pathlib

import pytest

from novelforge import server
from novelforge.core import bookdock, db, library
from novelforge.core.watcher import FolderWatcher


def _watcher(tmp_path, **wcfg) -> FolderWatcher:
    """本用例专属的 watcher：输入目录与 state 文件都落在 tmp_path 里。

    ⚠️ `state_file` **必须**显式给：默认值是会话级 `CACHE_DIR` 下的共享文件，而
    「忽略名单」就存在它里面 —— 不隔离的话，前一个用例忽略掉的文件名会被后一个
    用例当成已忽略（表现为「单独跑绿、全量跑红」）。
    """
    cfg = {"watcher": {"enabled": True, "copy_non_txt": True, **wcfg}}
    return FolderWatcher(input_dir=tmp_path / "input",
                         state_file=tmp_path / "watcher-state.json", cfg=cfg)


def _drop(w: FolderWatcher, name: str, data: bytes = b"EPUB") -> pathlib.Path:
    w.input_dir.mkdir(parents=True, exist_ok=True)
    p = w.input_dir / name
    p.write_bytes(data)
    return p


def _seed(w: FolderWatcher, name: str, status: str = "error", **over) -> dict:
    """投一个文件 + 登记一条同名的条目，返回登记行。"""
    _drop(w, name)
    db.dock_upsert(name, name, ext=pathlib.PurePosixPath(name).suffix.lower(),
                   size=4, status=status)
    if over:
        db.dock_update(name, **over)
    return db.dock_get(name)


def _both_untouched(w: FolderWatcher, name: str, before: dict) -> None:
    """「磁盘与登记行都没动」的统一断言（失败路径专用）。"""
    assert (w.input_dir / name).is_file(), "被拒的操作不该动磁盘"
    after = db.dock_get(name)
    assert after is not None, "被拒的操作不该动登记行"
    for k in ("id", "name", "ext", "status", "output", "detail", "retries", "created_at"):
        assert after[k] == before[k], f"被拒的操作改了 {k}"


# ---------------------------------------------------------------------------
# rename：改文件名 = 换主键
# ---------------------------------------------------------------------------

def test_rename_改文件名并换主键(isolated, tmp_path):
    """文件真的改名了，登记行**换主键**，且状态 / 创建时间不是改名的对象。"""
    w = _watcher(tmp_path)
    before = _seed(w, "三体.epub", retries=3)
    assert before["retries"] == 3

    item = bookdock.rename(w, "三体.epub", "三体（新版）.epub")

    assert not (w.input_dir / "三体.epub").exists()
    assert (w.input_dir / "三体（新版）.epub").read_bytes() == b"EPUB"
    assert item["id"] == "三体（新版）.epub" and item["name"] == item["id"], \
        "条目 id 就是文件名，改名必须换主键"
    assert db.dock_get("三体.epub") is None, "旧 id 上不该再查得到"
    assert item["status"] == "error", "状态不是改名的对象"
    assert item["created_at"] == before["created_at"], "创建时间不是改名的对象"
    assert item["retries"] == 0, "新名字是没试过的条目，旧的失败计数不该继续拦它"
    assert item["ext"] == ".epub"
    assert "三体.epub" in item["detail"], "旧文案说的是旧名字，得如实换掉"


def test_rename_同名是幂等的_不动磁盘也不动库(isolated, tmp_path):
    w = _watcher(tmp_path)
    before = _seed(w, "三体.epub")

    item = bookdock.rename(w, "三体.epub", "三体.epub")

    assert item["updated_at"] == before["updated_at"], "同名不该写库（连 updated_at 都不该动）"
    assert (w.input_dir / "三体.epub").is_file()


def test_rename_清洗非法字符后落盘的是清洗过的名字(isolated, tmp_path):
    """`?` 不是路径分隔符，`_clean_name` 放行，但落盘前必须被 sanitize 掉。

    不洗的话这个名字在 Windows 上根本创建不出来（OSError），或者洗了却仍按
    用户输入的字符串去找文件 —— 两种都会让条目与磁盘长期对不上。
    """
    w = _watcher(tmp_path)
    _seed(w, "三体.epub")

    item = bookdock.rename(w, "三体.epub", "三体?第二部.epub")

    assert (w.input_dir / "三体第二部.epub").is_file(), \
        f"落盘的应当是清洗后的名字，实际 {item['name']}"
    assert item["id"] == "三体第二部.epub"
    assert not (w.input_dir / "三体.epub").exists()


def test_rename_扩展名不许换(isolated, tmp_path):
    """扩展名决定这个文件怎么被处理 —— 悄悄换掉等于替用户换了一种处理方式。

    先红过的判据：这条路径一度只是「把 suffix 拼回去」，于是 `.txt` → `.epub`
    改名成功而内容还是纯文本，接下去每一步都按 EPUB 走。
    """
    w = _watcher(tmp_path)
    before = _seed(w, "三体.epub")

    with pytest.raises(bookdock.DockError) as ei:
        bookdock.rename(w, "三体.epub", "三体.txt")

    assert ei.value.status == 400
    _both_untouched(w, "三体.epub", before)


def test_rename_名字里没有可用字符则拒(isolated, tmp_path):
    """`sanitize_stem` 是**静默删字符**的，能删成空串（名字全是非法字符时）。"""
    w = _watcher(tmp_path)
    before = _seed(w, "三体.epub")

    with pytest.raises(bookdock.DockError) as ei:
        bookdock.rename(w, "三体.epub", "???.epub")

    assert ei.value.status == 400
    _both_untouched(w, "三体.epub", before)


def test_rename_含路径分隔符或上跳一律拒(isolated, tmp_path):
    """收书目录是平的，id 只允许单个文件名（`_clean_name`）。"""
    w = _watcher(tmp_path)
    before = _seed(w, "三体.epub")

    for bad in ("sub/三体.epub", "../三体.epub", "/tmp/三体.epub", ".."):
        with pytest.raises(bookdock.DockError) as ei:
            bookdock.rename(w, "三体.epub", bad)
        assert ei.value.status == 400, bad
    _both_untouched(w, "三体.epub", before)
    assert not (tmp_path / "sub").exists(), "不该建出任何目录"


def test_rename_重名被拒(isolated, tmp_path):
    """平铺目录里文件名唯一 —— 覆盖 = 悄悄少掉一个条目。

    ⚠️ 不能只靠 `Path.rename` 判：同名已存在时 Windows 抛 FileExistsError、
    POSIX **静默覆盖**，跨平台不一致。
    """
    w = _watcher(tmp_path)
    before = _seed(w, "三体.epub")
    _seed(w, "球状闪电.epub")

    with pytest.raises(bookdock.DockError) as ei:
        bookdock.rename(w, "三体.epub", "球状闪电.epub")

    assert ei.value.status == 409
    _both_untouched(w, "三体.epub", before)
    assert (w.input_dir / "球状闪电.epub").read_bytes() == b"EPUB", "被撞的那本也不许动"


def test_rename_命中运行时忽略清单的名字被拒(isolated, tmp_path):
    """忽略清单按**文件名**记，且不在这个页面上 —— 用户看不出自己做了什么。"""
    w = _watcher(tmp_path)
    before = _seed(w, "三体.epub")
    w.add_ignore("球状闪电.epub")

    with pytest.raises(bookdock.DockError) as ei:
        bookdock.rename(w, "三体.epub", "球状闪电.epub")

    assert ei.value.status == 409
    assert "忽略" in str(ei.value)
    _both_untouched(w, "三体.epub", before)


def test_rename_就绪条目不许改名(isolated, tmp_path):
    """用户口径：只改**未入库**的条目。就绪条目的成品已经在书库里了。"""
    w = _watcher(tmp_path)
    before = _seed(w, "三体.epub", status="ready", output="三体.epub")

    with pytest.raises(bookdock.DockError) as ei:
        bookdock.rename(w, "三体.epub", "三体（新版）.epub")

    assert ei.value.status == 409
    _both_untouched(w, "三体.epub", before)


def test_rename_文件已不在投递目录时清条目并报不存在(isolated, tmp_path):
    """与 `rescan` 同一处置（端点据此回 404）：文件都没了，改名无从谈起。"""
    w = _watcher(tmp_path)
    db.dock_upsert("三体.epub", "三体.epub", ext=".epub", status="error")

    with pytest.raises(ValueError):
        bookdock.rename(w, "三体.epub", "三体（新版）.epub")

    assert db.dock_get("三体.epub") is None, "悬空条目该被清掉"


def test_rename_条目不存在报_ValueError(isolated, tmp_path):
    """`ValueError` 是既有的「404」通道（`_row` 抛），端点只认它和 DockError。"""
    w = _watcher(tmp_path)

    with pytest.raises(ValueError):
        bookdock.rename(w, "从来没有过的.epub", "x.epub")


# ---------------------------------------------------------------------------
# rescan：入库前指定目标库 / 目标文件夹（「入库到…」）
# ---------------------------------------------------------------------------

def _two_dir_ebook_lib(tmp_path, lid="lib-a") -> "tuple[str, pathlib.Path, pathlib.Path]":
    """建一个**两个文件夹**的 ebook 库；返回 (库 id, 第一个文件夹, 第二个文件夹)。

    `settings` 显式打开 `copy_non_txt`：本用例要测的是**落点**，不该被这个开关
    的默认值牵着走。
    """
    r1 = tmp_path / "libs" / "one"
    r2 = tmp_path / "libs" / "two"
    db.create_library(lid, "甲库", "ebook", source_dirs=[str(r1), str(r2)],
                      settings=json.dumps({"watcher": {"copy_non_txt": True}}))
    library.invalidate()
    return lid, r1, r2


def test_rescan_不指定目标时落在该库第一个文件夹(isolated, tmp_path):
    """**老调用点的行为一字不改**：不传 library_id 就走既有 `_target` 路由。"""
    w = _watcher(tmp_path)
    lid, r1, _r2 = _two_dir_ebook_lib(tmp_path)
    _seed(w, "Book-1.epub", status="pending")

    item = bookdock.rescan(w, "Book-1.epub")

    assert item["status"] == "ready"
    assert (r1 / "Book-1.epub").is_file(), "路由命中该库后落它的第一个文件夹"


def test_rescan_指定第二个文件夹时落在第二个根(isolated, tmp_path):
    w = _watcher(tmp_path)
    lid, r1, r2 = _two_dir_ebook_lib(tmp_path)
    _seed(w, "Book-1.epub", status="pending")

    item = bookdock.rescan(w, "Book-1.epub", library_id=lid, root=str(r2))

    assert item["status"] == "ready"
    assert (r2 / "Book-1.epub").is_file(), "显式指定的文件夹优先"
    assert not (r1 / "Book-1.epub").exists(), "不该同时落进第一个"


def test_rescan_只给库不给文件夹时用第一个(isolated, tmp_path):
    """口径 7：目标文件夹默认为该库的第一个文件夹。"""
    w = _watcher(tmp_path)
    lid, r1, r2 = _two_dir_ebook_lib(tmp_path)
    _seed(w, "Book-1.epub", status="pending")

    bookdock.rescan(w, "Book-1.epub", library_id=lid)

    assert (r1 / "Book-1.epub").is_file() and not (r2 / "Book-1.epub").exists()


def test_rescan_目标文件夹不属于该库则拒且不复制(isolated, tmp_path):
    """否则这个参数就是「往任意目录写文件」的洞。"""
    w = _watcher(tmp_path)
    lid, r1, _r2 = _two_dir_ebook_lib(tmp_path)
    outside = tmp_path / "别处"
    before = _seed(w, "Book-1.epub", status="error")

    with pytest.raises(bookdock.DockError) as ei:
        bookdock.rescan(w, "Book-1.epub", library_id=lid, root=str(outside))

    assert ei.value.status == 400
    assert not outside.exists(), "被拒的落点不该被建出来"
    assert not (r1 / "Book-1.epub").exists()
    assert db.dock_get("Book-1.epub")["status"] == "error", \
        "被拒的操作不该把条目改成「待处理」（校验必须在置位之前）"
    assert db.dock_get("Book-1.epub")["detail"] == before["detail"]


def test_rescan_书库不存在则拒(isolated, tmp_path):
    w = _watcher(tmp_path)
    _seed(w, "Book-1.epub", status="error")

    with pytest.raises(bookdock.DockError) as ei:
        bookdock.rescan(w, "Book-1.epub", library_id="没有这个库")

    assert ei.value.status == 400
    assert db.dock_get("Book-1.epub")["status"] == "error"


def test_rescan_目标库收不了这个格式则拒且不落盘(isolated, tmp_path):
    """**隐形文件**比拒收更糟：文件落盘了、书目里却没有 —— 用户看得见失败，
    看不见消失。所以判据是**那个库的生效白名单**（`accepts_ext`），不是
    「谁家的规则命中」。"""
    w = _watcher(tmp_path)
    lid, r1, r2 = _two_dir_ebook_lib(tmp_path)
    db.update_library(lid, allowed_exts=json.dumps([".epub"]))
    library.invalidate()
    _seed(w, "画集.pdf", status="error")

    with pytest.raises(bookdock.DockError) as ei:
        bookdock.rescan(w, "画集.pdf", library_id=lid)

    assert ei.value.status == 400
    assert ".pdf" in str(ei.value)
    assert not (r1 / "画集.pdf").exists() and not (r2 / "画集.pdf").exists()
    assert db.dock_get("画集.pdf")["status"] == "error"


def test_rescan_指定库时不受自动处理范围限制(isolated, tmp_path):
    """「待复核」条目恰恰大多是 `.pdf` 这类**不在自动处理范围**的格式 ——
    指定了目标库却还被那条早退拦下，「入库到…」就成了假交互。

    判据因此换成**那个库收不收它**：`.pdf` 不在 `pipeline.EBOOK_EXT` 之外
    （它是 supported），这里换一个真的不在自动范围内的格式来钉：改白名单让它收。
    """
    w = _watcher(tmp_path)
    lid, r1, _r2 = _two_dir_ebook_lib(tmp_path)
    # 自动流水线不认 .xyz（supported 为假），但这个库显式把它列进了白名单
    db.update_library(lid, allowed_exts=json.dumps([".xyz"]))
    library.invalidate()
    _seed(w, "怪格式.xyz", status="needs_review")
    assert not bookdock.supported("怪格式.xyz"), "前置：它确实不在自动处理范围"

    item = bookdock.rescan(w, "怪格式.xyz", library_id=lid)

    assert item["status"] == "ready", "显式指定的库收得下它，就该收进去"
    assert (r1 / "怪格式.xyz").is_file()


def test_rescan_不指定库时仍受自动处理范围限制(isolated, tmp_path):
    """与上一条互为反向：没有显式意图时，判据仍是「自动流水线认不认」。"""
    w = _watcher(tmp_path)
    _two_dir_ebook_lib(tmp_path)
    _seed(w, "怪格式.xyz", status="needs_review")

    item = bookdock.rescan(w, "怪格式.xyz")

    assert item["status"] == "needs_review", "不指定的目标时不该被收进去"
    assert "不在自动处理范围" in item["detail"]


def test_rescan_没有可接收的库时如实记失败(isolated, tmp_path):
    """第 37 期起没有默认库：命不中就是拒收，且**不许**动原文件。"""
    w = _watcher(tmp_path)
    for l in library.libraries():               # 清空书库表（isolated 会建一条）
        db.delete_library(l["id"])
    library.invalidate()
    _seed(w, "Book-1.epub", status="pending")

    item = bookdock.rescan(w, "Book-1.epub")

    assert item["status"] == "error"
    assert "没有可接收的书库" in item["detail"]
    assert (w.input_dir / "Book-1.epub").is_file(), "拒收时不许动原文件"


# ---------------------------------------------------------------------------
# 接口层：异常映射（DockError → 它的 status，ValueError → 404）
# ---------------------------------------------------------------------------

def test_接口_rename_未登录401(client):
    r = client.post("/api/book-dock/Book-1.epub/rename", json={"name": "Book-2.epub"})
    assert r.status_code == 401


def test_接口_rename_条目不存在404(client, auth_headers, isolated, monkeypatch, tmp_path):
    w = _watcher(tmp_path)
    monkeypatch.setattr(server, "WATCHER", w)

    r = client.post("/api/book-dock/NoSuch.epub/rename",
                    json={"name": "Book-2.epub"}, headers=auth_headers)

    assert r.status_code == 404, r.text


def test_接口_rename_校验失败按_DockError_status_回码(client, auth_headers, isolated,
                                                      monkeypatch, tmp_path):
    """400 / 409 是**规则**拒绝（参数不对 / 与当前状态冲突），不是 404 也不是 500。"""
    w = _watcher(tmp_path)
    monkeypatch.setattr(server, "WATCHER", w)
    _seed(w, "Book-1.epub", status="error")

    r = client.post("/api/book-dock/Book-1.epub/rename",
                    json={"name": "Book-1.txt"}, headers=auth_headers)
    assert r.status_code == 400, r.text

    _seed(w, "Book-2.epub", status="error")
    r = client.post("/api/book-dock/Book-1.epub/rename",
                    json={"name": "Book-2.epub"}, headers=auth_headers)
    assert r.status_code == 409, r.text


def test_接口_rename_成功并返回新条目(client, auth_headers, isolated, monkeypatch, tmp_path):
    w = _watcher(tmp_path)
    monkeypatch.setattr(server, "WATCHER", w)
    _seed(w, "Book-1.epub", status="error")

    r = client.post("/api/book-dock/Book-1.epub/rename",
                    json={"name": "Book-2.epub"}, headers=auth_headers)

    assert r.status_code == 200, r.text
    assert r.json()["item"]["id"] == "Book-2.epub"
    assert db.dock_get("Book-1.epub") is None
    assert (w.input_dir / "Book-2.epub").is_file()


def test_接口_rescan_的库与文件夹参数是可选的(client, auth_headers, isolated,
                                              monkeypatch, tmp_path):
    """**可选**就保证了老调用零改动：不带 body 的 POST 与从前逐字一致。"""
    w = _watcher(tmp_path)
    monkeypatch.setattr(server, "WATCHER", w)
    lid, r1, r2 = _two_dir_ebook_lib(tmp_path)

    _seed(w, "Book-1.epub", status="pending")
    r = client.post("/api/book-dock/Book-1.epub/rescan", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["item"]["status"] == "ready"
    assert (r1 / "Book-1.epub").is_file(), "不带参数 → 走既有路由，落第一个文件夹"

    _seed(w, "Book-2.epub", status="pending")
    r = client.post("/api/book-dock/Book-2.epub/rescan", headers=auth_headers,
                    json={"library_id": lid, "root": str(r2)})
    assert r.status_code == 200, r.text
    assert (r2 / "Book-2.epub").is_file(), "带了参数 → 落在指定的文件夹"


def test_接口_rescan_目标库收不了这个格式回400(client, auth_headers, isolated,
                                                monkeypatch, tmp_path):
    w = _watcher(tmp_path)
    monkeypatch.setattr(server, "WATCHER", w)
    lid, _r1, _r2 = _two_dir_ebook_lib(tmp_path)
    db.update_library(lid, allowed_exts=json.dumps([".epub"]))
    library.invalidate()
    _seed(w, "Pic.pdf", status="error")     # 文件名走 ASCII：URL 里要原样当路径段传

    r = client.post("/api/book-dock/Pic.pdf/rescan", headers=auth_headers,
                    json={"library_id": lid})

    assert r.status_code == 400, r.text
    assert "允许的格式" in r.json()["detail"]
