"""第 121 期「功能审查」四条缺陷的契约用例。

四条都是**功能上对不上承诺**，不是崩溃：

1. `/koreader/*` 三条路由被同名的 Komga 守卫覆盖（模块级后定义覆盖前定义）⇒ 只开 KOReader
   的部署一律 404「Komga 兼容服务未启用」，而只开 Komga 时应用账号能同步 KOReader。
2. 同一物理文件被两个库各登记一次时，`/api/duplicates` 把它当成「两本重复的书」；
   用户「保留一本、清掉另一本」时 `recycle_items` 按路径把**唯一那份文件**搬进回收站，
   保留方跟着从书架消失。
3. `AUTO_WATCH=false`（该变量覆盖 `watcher.enabled`）＋ 界面上点「启动监听」：线程跑起来了、
   `/api/watcher` 回 `running: true`，但收书目录每轮都被跳过 —— 丢进去的文件永远不收。
4. EPUB 的 `linear="no"` 条目（封面页 / 版权页）与 `properties="nav"` 的目录页被列成章节。

第 4 条的判据是「**不列章节、但 index 不平移**」：坐标空间不动，升级前后已存的进度/批注
仍指同一段正文（代价是列表里的 index 可能出现空档）。
"""

import hashlib
import pathlib
import zipfile

from novelforge.core import fileops, library
from novelforge.core.watcher import FolderWatcher

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------- 1. 两个守卫不再同名 ----------------

def test_两个守卫不再同名():
    """同名 = 后定义静默覆盖前定义，而且 import 期不报错（只在跑起来时走错分支）。"""
    src = (ROOT / "novelforge" / "server.py").read_text("utf-8")
    assert src.count("def _ko_guard(") == 1, "KOReader 守卫只该有一处定义"
    assert src.count("def _komga_guard(") == 1, "Komga 守卫只该有一处定义"
    assert src.count("_ko_guard(request)") >= 3, "三条 /koreader/* 路由都要走 KOReader 守卫"
    assert src.count("_komga_guard(request)") >= 10, "/api/v1/* 仍走 Komga 守卫"


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _set_ko(client, auth_headers, *, enabled: bool, key: str = "") -> None:
    r = client.put("/api/config", headers=auth_headers,
                   json={"koreader": {"enabled": enabled, "username": "koreader", "key": key}})
    assert r.status_code == 200, r.text


def test_只开KOReader也能同步(client, auth_headers):
    key = _md5("pass123")
    _set_ko(client, auth_headers, enabled=True, key=key)   # komga 保持默认关闭
    h = {"x-auth-user": "koreader", "x-auth-key": key}
    assert client.get("/koreader/healthcheck").status_code == 200
    r = client.get("/koreader/users/auth", headers=h)
    assert r.status_code == 200, f"只开 KOReader 时鉴权必须过：{r.status_code} {r.text}"
    assert r.json() == {"authorized": "OK"}
    bad = client.get("/koreader/users/auth", headers={**h, "x-auth-key": "0" * 32})
    assert bad.status_code == 401, "密钥不对要 401（kosync 客户端只认 401 为鉴权失败）"


def test_KOReader没开时仍然是404(client, auth_headers):
    _set_ko(client, auth_headers, enabled=False, key=_md5("pass123"))
    r = client.get("/koreader/users/auth",
                   headers={"x-auth-user": "koreader", "x-auth-key": _md5("pass123")})
    assert r.status_code == 404
    assert "KOReader" in r.json()["detail"], "关掉 KOReader 时说「Komga 未启用」就是又串了守卫"


# ---------------- 2. 同一物理文件不是重复书目 ----------------

def _book(bid: str, path, lib: str, title: str = "容器包", author: str = "某人") -> dict:
    return {"id": bid, "name": pathlib.PurePosixPath(str(path)).name, "path": str(path),
            "size": 193, "mtime": 1792397973.0, "format": "ZIP", "title": title,
            "author": author, "library_id": lib, "issues": None}


def test_同一物理文件不算重复(monkeypatch):
    same = "/书库/容器包.zip"
    monkeypatch.setattr(library, "books", lambda *a, **k: [
        _book("a$1", same, "a"), _book("b$1", same, "b")])
    out = library.duplicate_groups()
    assert out["groups"] == [], "同一个 path 被两个库各登记一次，是同一本书而不是重复"


def test_不同路径的同名书照旧算重复(monkeypatch):
    """反向断言：修法只排除「同一 path」，没把跨库重复检测弄瞎。"""
    monkeypatch.setattr(library, "books", lambda *a, **k: [
        _book("a$1", "/书库A/容器包.zip", "a"), _book("b$1", "/书库B/容器包.zip", "b")])
    out = library.duplicate_groups()
    assert len(out["groups"]) == 1
    assert out["groups"][0]["cross_library"] is True
    assert len(out["groups"][0]["items"]) == 2


def test_回收站拒绝搬共用文件(isolated, tmp_path, monkeypatch):
    f = tmp_path / "容器包.zip"
    f.write_bytes(b"PK")
    monkeypatch.setattr(fileops, "safe_path", lambda name, lid: f)
    monkeypatch.setattr(fileops, "_lib_of", lambda name, item: item.get("library_id") or "a")
    monkeypatch.setattr(library, "books", lambda *a, **k: [
        {"id": "a$1", "path": str(f)}, {"id": "b$1", "path": str(f)}])

    out = fileops.recycle_items([{"name": "容器包.zip", "library_id": "a"}])
    assert out["moved"] == []
    assert out["errors"] and "同一物理文件" in out["errors"][0]["error"]
    assert f.is_file(), "被拒绝的回收绝不能动磁盘"


def test_独占文件照旧可以回收(isolated, tmp_path, monkeypatch):
    """反向断言：护栏不会让正常回收（重复清理的主力路径）失效。"""
    f = tmp_path / "独本.zip"
    f.write_bytes(b"PK")
    monkeypatch.setattr(fileops, "safe_path", lambda name, lid: f)
    monkeypatch.setattr(fileops, "_lib_of", lambda name, item: item.get("library_id") or "a")
    monkeypatch.setattr(library, "books", lambda *a, **k: [{"id": "a$1", "path": str(f)}])

    out = fileops.recycle_items([{"name": "独本.zip", "library_id": "a"}])
    assert len(out["moved"]) == 1 and not out["errors"]
    assert not f.exists(), "回收 = 移入回收站（台账里有 orig_path）"


# ---------------- 3. 线程在跑就是在监听 ----------------

def test_启动监听后收书目录恒在监听(tmp_path):
    """`watcher.enabled` 只是「服务启动时要不要自动起线程」（`AUTO_WATCH` 覆盖它）。"""
    w = FolderWatcher(input_dir=tmp_path / "input",
                      state_file=tmp_path / "state.json",
                      cfg={"watcher": {"enabled": False}})
    targets = {t["tkey"]: t for t in w._derive_targets()}
    assert targets["input"]["watch"] is True, "线程在跑却跳过收书目录 = 文件永远不收"
    assert pathlib.Path(targets["input"]["root"]) == tmp_path / "input"


# ---------------- 4. 非线性条目与目录页不列章节 ----------------

_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>封面测试</dc:title></metadata>
  <manifest>
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine>
    <itemref idref="cover" linear="no"/>
    <itemref idref="c1"/>
    <itemref idref="nav"/>
  </spine>
</package>
"""

_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""


def _epub(tmp_path) -> pathlib.Path:
    p = tmp_path / "封面测试.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", _OPF)
        z.writestr("OEBPS/cover.xhtml", "<html><body><img src='c.jpg'/></body></html>")
        z.writestr("OEBPS/c1.xhtml", "<html><body><p>正文</p></body></html>")
        z.writestr("OEBPS/nav.xhtml",
                   '<html><body><nav epub:type="toc"><ol><li><a href="c1.xhtml">第一章</a>'
                   "</li></ol></nav></body></html>")
    return p


def test_封面不列章节(tmp_path):
    p = _epub(tmp_path)
    chapters = [c for g in library._reading_list(p) for c in g["chapters"]]
    assert [c["index"] for c in chapters] == [1, 2], \
        "封面的 index 0 要保留在坐标空间里，但不该出现在章节目录中"
    assert chapters[0]["title"] == "第一章", "目录里的标题仍要套上"
    # 目录页（properties="nav"）**不**过滤：它在 spine 里是一页真实文档，既有契约如此
    assert library._spine(p)[2] == "OEBPS/nav.xhtml"


def test_坐标空间不平移(tmp_path):
    """`_spine` 含非线性条目且顺序不变 —— 升级前后已存的进度/批注仍指同一段正文。"""
    p = _epub(tmp_path)
    assert library._spine(p) == ["OEBPS/cover.xhtml", "OEBPS/c1.xhtml", "OEBPS/nav.xhtml"]
    info = library.chapter_html(p, 0, "bid")
    assert "img" in info["html"], "index 0 仍是封面页（老进度可以继续读，只是不在章节列表里）"
    assert info["total"] == 3


def test_整条spine都非线性时照旧列出(tmp_path):
    """畸形书（全书都没标 linear="yes"）不能给阅读器一个空目录 —— 点开什么也翻不到。"""
    p = tmp_path / "畸形.epub"
    opf = (_OPF.replace('<itemref idref="c1"/>', '<itemref idref="c1" linear="no"/>')
               .replace('<itemref idref="nav"/>', '<itemref idref="nav" linear="no"/>'))
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/cover.xhtml", "<html><body>封面</body></html>")
        z.writestr("OEBPS/c1.xhtml", "<html><body><p>正文</p></body></html>")
        z.writestr("OEBPS/nav.xhtml", "<html><body>目录</body></html>")
    chapters = [c for g in library._reading_list(p) for c in g["chapters"]]
    assert [c["index"] for c in chapters] == [0, 1, 2]
