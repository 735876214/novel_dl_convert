"""容器展开（第 87 期第①步的另一半）。

用户口径「`.zip` 里含 EPUB/PDF 就按对应格式读」—— 本文件钉住兑现它的那条路：
**把容器展开成真正的书**（而不是让阅读链路去认一个容器）。三条纪律：

· 只在容器所在目录落新文件；**原子写**（先 `.part` 再 replace）；
· **绝不覆盖已有文件**（撞名如实报，不静默改名 —— 改名会换 book_id）；
· **默认不删源**（删除不可逆）。

零网络。
"""
import zipfile

from novelforge.core import library, zipkind


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


def test_展开_删源要显式要求(tmp_path):
    p = _epub_container(tmp_path / "书.zip")
    res = zipkind.unpack(p, remove_source=True)
    assert res["ok"] is True and res["source_removed"] is True
    assert not p.exists()


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


def test_展开接口对不可展开的容器如实_400(isolated, default_root, client, auth_headers):  # noqa: ARG001
    default_root.mkdir(parents=True, exist_ok=True)
    _zip(default_root / "图.zip", [("001.jpg", b"JPG")])
    library.invalidate()
    bid = next(b["id"] for b in library.books() if b["name"] == "图.zip")
    r = client.post(f"/api/books/{bid}/unpack", headers=auth_headers, json={})
    assert r.status_code == 400
    assert "不需要展开" in r.json()["detail"]
