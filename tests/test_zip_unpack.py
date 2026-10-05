"""容器展开（第 87 期第①步的另一半）。

用户口径「`.zip` 里含 EPUB/PDF 就按对应格式读」—— 本文件钉住兑现它的那条路：
**把容器展开成真正的书**（而不是让阅读链路去认一个容器）。三条纪律：

· 只在容器所在目录落新文件；**原子写**（先 `.part` 再 replace）；
· **绝不覆盖已有文件**（撞名如实报，不静默改名 —— 改名会换 book_id）；
· **默认不动源容器**；要求回收时也**只移入回收站**（第 96 期：有台账、可还原，从不 `unlink`）。

零网络。
"""
import zipfile

import pytest

from novelforge import config
from novelforge.core import db, fileops, library, publish, recycle, zipkind


@pytest.fixture
def recycle_env(isolated, monkeypatch, tmp_path) -> None:   # noqa: ARG001 —— 只做隔离副作用
    """把**回收落点**也切到本用例的临时目录。

    ⚠️ `CACHE_DIR` 是**会话级**的（`tests/conftest.py` 里那份环境一次性定死），而 `isolated`
    只切 `DATA_DIR` / `OUTPUT_DIR` / `LIBRARY_SOURCE_ROOTS` / `INPUT_DIR` ⇒ 不自己切的话，
    「回收目录里有什么」会撞上别的用例留下的条目（台账是按用例隔离的：DB 在 `DATA_DIR` 下）。
    """
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return path


def _epub_container(path, extra=()):
    """造一个「改了后缀的 EPUB」：容器内有 mimetype + container.xml。"""
    return _zip(path, [("mimetype", b"application/epub+zip"),
                       ("META-INF/container.xml", b"<container/>"), *extra])


# ---------------- 计划（只算不做）----------------

def test_计划_改了后缀的_epub_整份另存为_epub(tmp_path):
    p = _epub_container(tmp_path / "书.zip")
    plan = zipkind.unpack_plan(p)
    assert plan["ok"] is True
    assert [a["kind"] for a in plan["actions"]] == ["repackage"]
    assert plan["actions"][0]["dest"] == "书.epub"


def test_计划_图片档不需要展开(tmp_path):
    p = _zip(tmp_path / "m.zip", [("001.jpg", b"JPG")])
    plan = zipkind.unpack_plan(p)
    assert plan["ok"] is False and "已经能直接" in plan["reason"], \
        "图片档本来就能读，不该劝用户展开"


def test_计划_内含文档逐个提取(tmp_path):
    p = _zip(tmp_path / "包.zip", [("甲.pdf", b"%PDF"), ("乙.epub", b"PK")])
    plan = zipkind.unpack_plan(p)
    assert plan["ok"] is True
    assert sorted(a["dest"] for a in plan["actions"]) == ["乙.epub", "甲.pdf"]


# ---------------- 真展开 ----------------

def test_展开_epub_容器后能当真正的书读(tmp_path):
    p = _epub_container(tmp_path / "书.zip", extra=[("OEBPS/c1.xhtml", b"<html/>")])
    res = zipkind.unpack(p)
    assert res["ok"] is True and [a["ok"] for a in res["actions"]] == [True]
    out = tmp_path / "书.epub"
    assert out.is_file() and out.read_bytes() == p.read_bytes(), \
        "EPUB 就是 zip：整份另存，字节必须一模一样"
    assert p.exists(), "默认不删源容器（删除不可逆）"


def test_展开_提取内层文档(tmp_path):
    p = _zip(tmp_path / "包.zip", [("甲.pdf", b"%PDF-1.4")])
    res = zipkind.unpack(p)
    assert res["ok"] is True
    assert (tmp_path / "甲.pdf").read_bytes() == b"%PDF-1.4"


def test_展开_撞名不覆盖并如实报(tmp_path):
    p = _zip(tmp_path / "包.zip", [("甲.pdf", b"NEW")])
    (tmp_path / "甲.pdf").write_bytes(b"OLD")       # bytes 字面量只能是 ASCII
    res = zipkind.unpack(p)
    assert res["ok"] is False and "已存在" in res["actions"][0]["note"]
    assert (tmp_path / "甲.pdf").read_bytes() == b"OLD", "绝不能覆盖已有文件"


def test_展开_拒绝_zip_slip(tmp_path):
    """条目名带 `..` / 绝对路径一律不落盘 —— 否则一个恶意 zip 能往库外写文件。"""
    assert not zipkind._safe_entry("../../evil.pdf")
    assert not zipkind._safe_entry("/etc/passwd")
    assert not zipkind._safe_entry("C:/windows/x.pdf")
    assert zipkind._safe_entry("子目录/正常.pdf") and zipkind._safe_entry("正常.pdf")
    p = _zip(tmp_path / "坏.zip", [("../../evil.pdf", b"%PDF")])
    zipkind.unpack(p)
    assert not (tmp_path.parent / "evil.pdf").exists()
    assert not (tmp_path.parent.parent / "evil.pdf").exists()


def test_展开_删源是移入回收站而不是真删(recycle_env, tmp_path):   # noqa: ARG001
    """`remove_source=True` ⇒ 源容器**移入回收站**（第 96 期），不是 `unlink`。

    此前这里是全仓**唯一**能真删用户书文件的地方（第 95 期审计批次 8），与 `AGENTS.md` §1
    「删除一律移入回收站、从不 `unlink`」直接冲突。钉三件事：

    ① 原路径腾空（源容器确实不在原处了）；② 回收目录里那份**逐字节一致**（不是被删、也没被改）；
    ③ 台账记下原路径 ⇒ 「设置 → 维护 → 回收站还原」**真的搬得回来**（可还原不是口号）。
    """
    p = _epub_container(tmp_path / "书.zip")
    blob = p.read_bytes()

    res = zipkind.unpack(p, remove_source=True)

    assert res["ok"] is True and res["source_removed"] is True
    assert res["source_note"] == ""
    assert not p.exists(), "源容器必须已从原处移走"

    recycled = [q for q in fileops.recycle_dir().iterdir() if q.is_file()]
    assert len(recycled) == 1 and recycled[0].read_bytes() == blob, \
        "回收的那一份要与原容器逐字节一致"
    rows = db.recycle_list()
    assert len(rows) == 1 and rows[0]["orig_path"] == str(p)
    assert rows[0]["recycled_name"] == recycled[0].name

    plan = recycle.plan_restore([rows[0]["id"]])
    assert plan["errors"] == [] and plan["items"][0]["dst"] == str(p), \
        "台账要能指出原路径 —— 「可还原」靠的就是它"


def test_展开_回收失败如实报且原容器原样保留(tmp_path, monkeypatch):
    """移不动就**如实说**，并把原容器**原样留着** —— 不因为回收失败就静默当成功。"""
    p = _epub_container(tmp_path / "书.zip")
    blob = p.read_bytes()

    def _boom(*a, **k):
        raise OSError("回收目录写不进去")

    monkeypatch.setattr(publish, "recycle", _boom)
    res = zipkind.unpack(p, remove_source=True)

    assert res["ok"] is True, "展开本身是成功的（条目已经落地）"
    assert res["source_removed"] is False
    assert "回收源容器失败" in res["source_note"] and "OSError" in res["source_note"]
    assert p.is_file() and p.read_bytes() == blob, "回收失败 ⇒ 源容器必须原样保留"


def test_展开_坏包如实报不打异常(tmp_path):
    bad = tmp_path / "坏.zip"
    bad.write_bytes("不是压缩包".encode("utf-8"))
    res = zipkind.unpack(bad)
    assert res["ok"] is False and res["actions"] == [] and res["reason"]


# ---------------- 与书库接起来 ----------------

def test_展开出来的文件能被书目扫到(isolated, default_root):  # noqa: ARG001
    default_root.mkdir(parents=True, exist_ok=True)
    _zip(default_root / "包.zip", [("内页.pdf", b"%PDF-1.4")])
    library.invalidate()
    before = {b["name"] for b in library.books()}
    assert "包.zip" in before

    zipkind.unpack(default_root / "包.zip")
    library.invalidate()
    after = {b["name"] for b in library.books()}
    assert "内页.pdf" in after, "展开出来的书必须立刻出现在书目里（否则用户以为失败了）"


def test_展开接口存在且形状稳定(isolated, default_root, client, auth_headers):  # noqa: ARG001
    default_root.mkdir(parents=True, exist_ok=True)
    _zip(default_root / "包.zip", [("内页.pdf", b"%PDF-1.4")])
    library.invalidate()
    bid = next(b["id"] for b in library.books() if b["name"] == "包.zip")

    r = client.post(f"/api/books/{bid}/unpack", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["source_removed"] is False
    assert body["actions"][0]["dest"] == "内页.pdf"
    assert (default_root / "内页.pdf").is_file()

    # 再点一次：撞名 ⇒ 如实报「已存在」，不是 500、也不是静默成功
    again = client.post(f"/api/books/{bid}/unpack", headers=auth_headers, json={})
    assert again.status_code == 200
    assert again.json()["ok"] is False and "已存在" in again.json()["actions"][0]["note"]


def test_展开接口_删源走回收站(recycle_env, default_root, client, auth_headers):   # noqa: ARG001
    """接口这一层：`remove_source=true` 之后源容器在**回收站**、台账有它、回执如实。"""
    default_root.mkdir(parents=True, exist_ok=True)
    src = _zip(default_root / "包.zip", [("内页.pdf", b"%PDF-1.4")])
    blob = src.read_bytes()
    library.invalidate()
    bid = next(b["id"] for b in library.books() if b["name"] == "包.zip")

    r = client.post(f"/api/books/{bid}/unpack", headers=auth_headers,
                    json={"remove_source": True})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_removed"] is True and body["source_note"] == ""
    assert not src.exists(), "源容器不该还在书库里"
    rows = db.recycle_list()
    assert len(rows) == 1 and rows[0]["orig_path"] == str(src)
    recycled = [q for q in fileops.recycle_dir().iterdir() if q.is_file()]
    assert len(recycled) == 1 and recycled[0].read_bytes() == blob


def test_待展开清单只列分派不出形态的容器(isolated, default_root):  # noqa: ARG001
    """图片档 `.zip` 已归一成 CBZ（能直接读）⇒ **不该**出现在待展开清单里。"""
    default_root.mkdir(parents=True, exist_ok=True)
    _zip(default_root / "图片档.zip", [("001.jpg", b"JPG")])
    _zip(default_root / "文档档.zip", [("内页.pdf", b"%PDF-1.4")])
    library.invalidate()

    items = library.container_books()
    names = {i["name"] for i in items}
    assert "文档档.zip" in names
    assert "图片档.zip" not in names, "能直接读的容器不该劝用户展开"
    doc = next(i for i in items if i["name"] == "文档档.zip")
    assert doc["unpackable"] is True and doc["targets"] == ["内页.pdf"]


def test_待展开清单接口形状稳定(isolated, default_root, client, auth_headers):  # noqa: ARG001
    default_root.mkdir(parents=True, exist_ok=True)
    r = client.get("/api/library-containers", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "libraries"}
    assert body["total"] == len(body["items"])


def test_展开接口对不可展开的容器如实_400(isolated, default_root, client, auth_headers):  # noqa: ARG001
    default_root.mkdir(parents=True, exist_ok=True)
    _zip(default_root / "图.zip", [("001.jpg", b"JPG")])
    library.invalidate()
    bid = next(b["id"] for b in library.books() if b["name"] == "图.zip")
    r = client.post(f"/api/books/{bid}/unpack", headers=auth_headers, json={})
    assert r.status_code == 400
    assert "不需要展开" in r.json()["detail"]
