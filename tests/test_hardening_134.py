"""第 134 期：五轮审查的 9 条发现（F1–F9），每条一个用例。

为什么集中在一个文件：这 9 条**全部**是「功能上看不出问题、只在某个边界上出错」的类型
—— 正文开头整段丢、单个根掉线清索引、读失败把设置抹成默认、展开把盘写满、令牌进日志…
在此之前**没有一条用例挡着它们**，所以它们一路活到了审查阶段。文件按发现编号排列，
每个用例的 docstring 写清「去掉这处修复会看到什么」，便于日后反查。
"""
import asyncio
import builtins
import json
import logging
import pathlib
import types
import zipfile

import httpx
import pytest

from novelforge import config, server
from novelforge.core import catalog, comics, db, htmlsafe, urlguard, zipkind

# ---------------------------------------------------------------------------
# F1：以裸文字开头的正文，整段开头被丢
# ---------------------------------------------------------------------------

def test_F1_裸文字开头的正文不被吞掉():
    """``第一段<p>第二段</p>`` 的开头那段必须留下。

    去掉 `htmlsafe.sanitize` 里拼 `root.text` 的那一句 ⇒ 首页第一段**整段消失**
    （只在前端缓存 24 小时内看得见，缓存在就更看不出来）。
    """
    out = htmlsafe.sanitize("第一段纯文本<p>第二段</p>")
    assert "第一段纯文本" in out, out
    assert "第二段" in out, out


def test_F1_裸文字里的标签字符必须重新转义():
    """拼回的裸文本是**解析后**的字符，直接拼回去等于把 `&lt;b&gt;` 变回真标签。"""
    out = htmlsafe.sanitize("a &lt;b&gt; c<p>x</p>")
    assert "a &lt;b&gt; c" in out, out
    assert "<b>" not in out, out


# ---------------------------------------------------------------------------
# F2：force 全量重扫把 replaced 抹成 0
# ---------------------------------------------------------------------------

def _replaced(lid: str, rel: str) -> int:
    row = catalog._exec(                        # noqa: SLF001 —— 只在这里读一列
        f"SELECT replaced FROM {catalog.TABLE} WHERE library_id=? AND rel=?", (lid, rel)
    ).fetchone()
    return int(row["replaced"])


def test_F2_强制重扫不清掉替换标记(isolated, make_library, make_book):
    """「同名路径上的文件被换过」是**结论**，全量重扫判不出来时只能沿用。

    去掉 `replaced_now = bool(cur[2])` 那处沿用 ⇒ 用户每点一次「立即扫描」，
    所有「文件被替换过」的提示一次性消失，且 upsert 整列覆盖后**永不复活**。
    """
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "f2"
    make_library("lib-f2", "替换库", "ebook", root)
    make_book(root, "书.epub", b"EPUB")
    lib = db.get_library("lib-f2")
    catalog.refresh_library(lib, force=True)

    # 同名换内容（体积 + mtime 都变了）⇒ 增量那轮判出「被替换过」
    make_book(root, "书.epub", b"EPUB-v2-second-version-longer")
    catalog.refresh_library(lib)
    assert _replaced("lib-f2", "书.epub") == 1

    catalog.refresh_library(lib, force=True)    # = 用户点「立即扫描」
    assert _replaced("lib-f2", "书.epub") == 1, "全量重扫把「文件被替换过」抹掉了"


# ---------------------------------------------------------------------------
# F7：单个根掉线 ⇒ 那个根下的索引行被当真删除
# ---------------------------------------------------------------------------

def test_F7_根不可用不清掉索引(isolated, make_library, make_book):
    """NAS 未挂载时那一整库的书不许从索引里消失。

    去掉「根不可用就跳过去删」的保护 ⇒ 监听线程每 60 秒的兜底刷新会把整库索引清空，
    而用户看到的现象只是「书库突然空了」（文件还在，只是没挂上）。
    """
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "f7"
    make_library("lib-f7", "掉线库", "ebook", root)
    make_book(root, "书.epub", b"EPUB")
    lib = db.get_library("lib-f7")
    catalog.refresh_library(lib, force=True)
    assert [b["name"] for b in catalog.books_of(lib)] == ["书.epub"]

    root.rename(root.with_name("f7-unmounted"))          # 模拟「根没了」
    out = catalog.refresh_library(lib)                   # 增量那轮（线上每 60 秒一次）
    assert out.get("skipped") and out.get("reason") == "root_unavailable", out
    assert [b["name"] for b in catalog.books_of(lib)] == ["书.epub"], "根掉线不许删索引"


def test_F7_多根库一个根掉线只影响它自己(isolated, make_library, make_book):
    """A 根掉线、B 根还有书时，A 的索引行同样不许删（第 134 期补的第二个洞）。

    去掉 `k[0] in usable_roots` 那半句 ⇒ `seen` 非空 ⇒ 旧的「整库保护」根本不进，
    A 根下的行全被删；而库因 B 的书仍然「活着」，孤儿清理就会**真删**进度与批注。
    """
    base = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"])
    root_a, root_b = base / "f7a", base / "f7b"
    root_a.mkdir(parents=True, exist_ok=True)
    root_b.mkdir(parents=True, exist_ok=True)
    make_library("lib-f7b", "双根库", "ebook", root_a)
    make_book(root_a, "甲.epub", b"EPUB")
    make_book(root_b, "乙.epub", b"EPUB")
    # 第二个根写进 source_dirs（入库形态是 JSON 数组）
    db.update_library("lib-f7b", source_dirs=json.dumps([str(root_a), str(root_b)]))
    lib = db.get_library("lib-f7b")
    catalog.refresh_library(lib, force=True)
    assert sorted(b["name"] for b in catalog.books_of(lib)) == ["乙.epub", "甲.epub"]

    root_a.rename(root_a.with_name("f7a-unmounted"))     # 只有 A 掉线
    catalog.refresh_library(lib)
    assert sorted(b["name"] for b in catalog.books_of(lib)) == ["乙.epub", "甲.epub"], \
        "A 根掉线却把 A 的索引行删了"


# ---------------------------------------------------------------------------
# F9：settings.json 这一下读不出来 ⇒ 后续写入把设置抹成只剩本次改的键
# ---------------------------------------------------------------------------

def test_F9_读失败不写回也不动文件(tmp_path, monkeypatch):
    """「读不到」不等于「是空的」：拿空壳写回就丢光全部设置。

    去掉 `_OVERRIDES_READ_ERROR` 那道拒绝 ⇒ 一次瞬时读失败（磁盘抖动 / 网络盘掉线 /
    杀软锁文件）之后的下一次保存，会把集成凭据、更新镜像、追踪开关全静默抹掉，
    而界面显示「已保存」。
    """
    target = tmp_path / "settings.json"
    target.write_text('{"net": {"mirror": "https://example.invalid"}}', encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_FILE", target)
    assert config.load_overrides()["net"]["mirror"].startswith("https://")

    real_open = builtins.open

    def _boom(*a, **kw):
        if a and str(a[0]) == str(target):
            raise PermissionError(13, "模拟网络盘掉线")
        return real_open(*a, **kw)

    monkeypatch.setattr(builtins, "open", _boom)
    try:
        assert config.load_overrides() == {}                 # 按空覆盖层继续（设置页还能开）
        assert config._OVERRIDES_READ_ERROR is not None      # noqa: SLF001
        with pytest.raises(OSError):                         # 但绝不拿空壳写回
            config.mutate_overrides(lambda ov: ov.update({"ui": {"theme": "dark"}}))
    finally:
        monkeypatch.setattr(builtins, "open", real_open)
        config._OVERRIDES_READ_ERROR = None                  # noqa: SLF001 —— 别污染后续用例

    assert target.read_text(encoding="utf-8").startswith('{"net"'), "原文件被改动了"


def test_F9_坏JSON仍然留档而不是卡死(tmp_path, monkeypatch):
    """半截 JSON 是另一条路：改名留档 + 返回空覆盖层（否则设置页从此打不开）。"""
    target = tmp_path / "settings.json"
    target.write_text("{半截", encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_FILE", target)
    assert config.load_overrides() == {}
    assert not target.exists()
    assert list(tmp_path.glob("settings.json.corrupt-*")), "坏文件必须留档"


# ---------------------------------------------------------------------------
# F5：容器展开没有累计上限
# ---------------------------------------------------------------------------

def test_F5_展开有累计上限(tmp_path, monkeypatch):
    """单条目闸管「这一条」，这次展开还得管「一共」。

    去掉累计刹车 ⇒ 一个 50 MB 的全零 zip 装几百个 128 MiB 条目就能写满盘，
    而自动展开（`watcher._autounpack`）根本不需要用户点。
    """
    z = tmp_path / "四篇.zip"
    with zipfile.ZipFile(z, "w") as arc:
        for i in range(4):
            arc.writestr(f"第{i}.txt", "正文")
    monkeypatch.setattr(comics, "MAX_UNPACK_ENTRIES", 2)
    monkeypatch.setattr(comics, "MAX_UNPACK_BYTES", 1024 * 1024)

    out = zipkind.unpack(z)
    done = [a for a in out["actions"] if a["ok"]]
    over = [a for a in out["actions"] if not a["ok"]]
    assert len(done) == 2, out
    assert len(over) == 2, out
    assert all("上限" in a["note"] for a in over), over
    assert len(list(tmp_path.glob("*.txt"))) == 2, "超上限的条目不许落盘"


# ---------------------------------------------------------------------------
# F4：书内资源按同源下发 ⇒ 书里的一份 SVG 能拿页面里的令牌
# ---------------------------------------------------------------------------

def test_F4_书内资源带沙箱响应头(client, auth_headers, make_library, make_epub):
    """``/asset`` 下发的字节来自书（可能来自任何下载源），必须关进沙箱。

    去掉 `Content-Security-Policy: sandbox` ⇒ 书里一份 SVG 被当成同源文档打开，
    脚本能读到 `localStorage` 里的令牌，再拿它调 `/api/*`。
    """
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "f4"
    make_library("lib-f4", "素材库", "ebook", root)
    make_epub(root, "插图.epub")
    cards = client.get("/api/books", headers=auth_headers).json()["items"]
    bid = next(b["id"] for b in cards if b["name"] == "插图.epub")
    tok = auth_headers["Authorization"][7:]

    r = client.get(f"/api/books/{bid}/asset",
                   params={"p": "OEBPS/Images/pic.png", "token": tok})
    assert r.status_code == 200, r.text
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# F6：访问日志把媒体令牌打进日志文件
# ---------------------------------------------------------------------------

def test_F6_访问日志抹掉媒体令牌():
    """`?token=` 是登录令牌本身；它进日志就等于进了「设置 → 日志」和用户的 bug 报告。

    去掉日志过滤器 ⇒ 任何一次看图都会写出 ``&token=<真实令牌>``。
    """
    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "GET", "/api/books/abc/asset?p=OEBPS/Images/pic.png&token=SECRET-TOKEN",
         "1.1", 200), None)
    assert server._RedactMediaToken().filter(rec) is True       # noqa: SLF001
    msg = rec.getMessage()
    assert "SECRET-TOKEN" not in msg, msg
    assert "token=***" in msg and "p=OEBPS/Images/pic.png" in msg, msg
    assert "1.2.3.4" in msg and "200" in msg, msg


def test_F6_其它路径的日志原样保留():
    """只抹令牌那一项：别把排障信息一起抹掉（查 404/500 全靠这一段）。"""
    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "GET", "/api/books/abc/asset?p=a.png", "1.1", 200), None)
    path = rec.args[2]
    assert server._RedactMediaToken().filter(rec) is True       # noqa: SLF001
    assert rec.args[2] == path, rec.args


# ---------------------------------------------------------------------------
# F3：书源抓取 / 封面下载没接出站闸（SSRF）
# ---------------------------------------------------------------------------

def _run_guard(url: str, *, allow_private: bool = False) -> None:
    hook = urlguard.make_request_guard(allow_private=allow_private)

    async def _go():
        await hook(httpx.Request("GET", url))

    asyncio.run(_go())


def test_F3_书源抓取默认挡住内网目标():
    """书源规则是导入来的，里面的域名是别人写的 —— 一样能指向内网。

    去掉 `sources/manager._client` 的 `request_guard` ⇒ 一条指向
    `http://169.254.169.254/latest/meta-data/` 的规则就能把内网内容取回来，
    而且会以「正文」的形式显示在阅读器里。
    """
    with pytest.raises(urlguard.UrlBlocked):
        _run_guard("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(urlguard.UrlBlocked):
        _run_guard("http://127.0.0.1:8000/admin")
    _run_guard("http://127.0.0.1:8000/admin", allow_private=True)   # 显式放行不抛


def test_F3_开关默认关且只认配置里的那一个键():
    """内网自建源是真实用法 ⇒ 给显式开关，但默认必须是关的。"""
    assert urlguard.allow_private_sources({}) is False
    assert urlguard.allow_private_sources({"network": {"allow_private_sources": True}}) is True
    assert config.DEFAULTS["network"]["allow_private_sources"] is False


def test_F3_书源客户端默认挂了出站闸(tmp_path):
    """闸门要真的**挂到客户端上**：判据本身存在、但没接线 = 没修。"""
    from novelforge.sources.manager import DownloadManager

    src = types.SimpleNamespace(name="测试源", headers=None, timeout=10)
    dm = DownloadManager({"network": {"cookie_dir": str(tmp_path)}})

    async def _probe():
        client = dm._client(src)                 # noqa: SLF001
        try:
            return client.client.event_hooks
        finally:
            await client.client.aclose()

    hooks = asyncio.run(_probe())
    assert hooks.get("request"), "书源客户端必须挂出站闸"


# ---------------------------------------------------------------------------
# F8：上传件写盘失败 ⇒ 半截 `.upload-*` 留在收书目录
# ---------------------------------------------------------------------------

def test_F8_写盘失败要如实报错(client, tmp_path, monkeypatch):
    """磁盘满 / 只读挂载时：半截临时件要删掉，原因要如实回给用户。

    去掉那处 try ⇒ 抛的 `OSError` 变成一句裸 500（前端只显示「服务器错误」），
    半截 `.upload-*` 永远留在收书目录里（点号前缀让扫描侧看不见它）。
    """
    not_a_dir = tmp_path / "input-is-a-file"
    not_a_dir.write_text("x", encoding="utf-8")
    monkeypatch.setattr(server, "INPUT_DIR", not_a_dir)

    r = client.post("/convert", files={"file": ("书.txt", "正文".encode(), "text/plain")})
    assert r.status_code == 500, r.text
    detail = r.json()["detail"]
    assert "写盘失败" in detail, detail
    assert "Traceback" not in detail, detail
