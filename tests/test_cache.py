"""第 62 期 C：Redis 缓存层 —— **可以缺席的一层**，三条不许破的规矩。

1. **没配 = 空操作**：不设 ``NOVELFORGE_REDIS_URL`` 时行为与第 62 期之前一致，
   而且**一次网络都不发**（不是「连了才发现没配」）；
2. **配了连不上 = 静默降级**：业务照常直读 PG/SQLite，异常不许冒到调用方；
   并且不许「每个请求都去等一次超时」—— 连续失败即熔断，静默期内一次网络都不发；
3. **改了就得看得见**：写操作（``library.invalidate()``）与索引真的变了
   （刷新报告 added / removed）必须让列表缓存立刻失效；章节的键带**源文件指纹**，
   文件一变键就变 —— 这条是 D2「改了分章规则要看得见效果」的前提。

用例需要一个**真的** Redis：连不上就整组 skip（仓库纪律「测试完全离线」不破，
与 PG 侧同一范式）。默认连本机 6380 的 **db 15** —— 专用测试库，**绝不碰 db 0**；
要换地址就设 ``NOVELFORGE_TEST_REDIS_URL``。
"""
import os
import pathlib

import pytest

from novelforge import server
from novelforge.core import cache, catalog, db, epub_builder, library

#: 默认测试 Redis。db 15 是刻意的：本机开发用的缓存实例若是 db 0，测试绝不能碰它。
_DEFAULT_TEST_URL = "redis://127.0.0.1:6380/15"


@pytest.fixture
def redis_url(monkeypatch):
    """指向一个**可用**的 Redis；连不上就 skip。用完清干净（含 db 15 残留键）。"""
    import redis as redis_pkg

    url = os.environ.get("NOVELFORGE_TEST_REDIS_URL") or _DEFAULT_TEST_URL

    def _flush():
        try:
            c = redis_pkg.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0)
            c.flushdb()
            c.close()
        except Exception:                      # noqa: BLE001 —— 清不掉也不该让用例挂
            pass

    try:
        c = redis_pkg.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0)
        c.ping()
        c.close()
    except Exception as e:                     # noqa: BLE001
        pytest.skip(f"没有可用的测试 Redis（{url}）：{e}")
    _flush()
    monkeypatch.setenv("NOVELFORGE_REDIS_URL", url)
    cache.reset()                              # 丢掉上一个用例留下的客户端
    try:
        yield url
    finally:
        cache.reset()
        _flush()


@pytest.fixture
def env(isolated, tmp_path: pathlib.Path) -> dict:  # noqa: ARG001 —— 依赖 isolated 切目录
    """一个书库 + 它的根目录（与 test_scrape_shutdown 同款起手式）。"""
    root = tmp_path / "libraries" / "novels"
    root.mkdir(parents=True, exist_ok=True)
    db.create_library("novels", "小说库", "ebook", source_dirs=str(root))
    library.invalidate()
    return {"lid": "novels", "root": root}


def _put_epub(root, name: str, body: str = "<p>正文</p>") -> pathlib.Path:
    """建一本真 EPUB 并让它出现在书目里。

    ⚠️ 父目录要自己建：``epub_builder.build_epub`` 不建目录，而 ebooklib 写不进去时
    **只告警不抛**（``UserWarning: throwing exceptions while writing will be default
    behavior``）—— 少了这一句，用例会挂在「书怎么没扫到」上，而现场只有一个警告。
    """
    src = pathlib.Path(root) / name
    src.parent.mkdir(parents=True, exist_ok=True)
    # nav=False：不把目录页放进 spine —— 否则章节 index 0 是**目录页**，
    # 「取第 0 章」拿到的会是 nav（第 55 期给 TXT 派生 EPUB 定的同一口径）。
    epub_builder.build_epub({"title": name.split(".")[0], "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": body}], str(src), nav=False)
    library.invalidate()
    return src


# ---------------- ① 没配 = 空操作 ----------------

def test_没配地址时整层是空操作(env, monkeypatch):
    monkeypatch.delenv("NOVELFORGE_REDIS_URL", raising=False)
    cache.reset()

    assert cache.enabled() is False
    # 每个入口都得是「静默的一个空动作」，不许抛
    assert cache.get_json("nf:x") is None
    assert cache.get_bytes("nf:x") is None
    cache.set_json("nf:x", {"a": 1}, 60)
    cache.set_bytes("nf:x", b"a", 60)
    cache.drop("nf:x", "")

    _put_epub(env["root"], "西游.epub")
    names = [b["name"] for b in library.books(env["lid"])]
    assert names == ["西游.epub"]

    st = cache.stats()
    assert st["enabled"] is False
    # 「一次网络都不发」：连客户端都不该建出来
    assert st["client"] is False
    assert st["error"] == 0


# ---------------- ② 配了连不上 = 静默降级 + 熔断 ----------------

def test_Redis连不上时静默降级并熔断(env, monkeypatch):
    # 端口 1 上不会有 Redis：连接**立即被拒**（不是超时），用例不会变慢
    monkeypatch.setenv("NOVELFORGE_REDIS_URL", "redis://127.0.0.1:1/0")
    cache.reset()
    try:
        _put_epub(env["root"], "西游.epub")
        books = library.books(env["lid"])           # 关键：不抛
        assert [b["name"] for b in books] == ["西游.epub"]

        for _ in range(3):
            assert cache.get_json("nf:probe") is None
        st = cache.stats()
        assert st["error"] >= 3, st
        assert st["tripped"] is True, st

        # 熔断期内**一次网络都不发**：错误计数必须纹丝不动
        err = st["error"]
        for _ in range(5):
            assert cache.get_json("nf:probe") is None
        assert cache.stats()["error"] == err
    finally:
        cache.reset()


# ---------------- ③ 列表：命中 / 失效 ----------------

def test_列表走缓存且写操作后立刻失效(env, redis_url):  # noqa: ARG001
    _put_epub(env["root"], "西游.epub")
    key = cache.book_list_key(env["lid"])

    library.books(env["lid"])                       # 第一次：未命中 → 写回
    assert cache.get_bytes(key) is not None, "第一次读就该把列表写进缓存"

    hit0 = cache.stats()["hit"]
    assert [b["name"] for b in library.books(env["lid"])] == ["西游.epub"]
    assert cache.stats()["hit"] == hit0 + 1, "第二次读应当命中缓存"

    library.invalidate(env["lid"])                  # 任何写操作都会走这里
    assert cache.get_bytes(key) is None, "写操作之后列表缓存必须立刻失效"


def test_索引真变了才丢缓存(env, redis_url):  # noqa: ARG001
    """白扫一轮（unchanged）**不许**清缓存 —— 否则每轮刷新都把缓存清一次，等于没有。"""
    _put_epub(env["root"], "西游.epub")
    lib = library.get_library(env["lid"])
    library.books(env["lid"])
    key = cache.book_list_key(env["lid"])
    assert cache.get_bytes(key) is not None

    out = catalog.refresh_library(lib)
    assert out["added"] == 0 and out["removed"] == 0, out
    assert cache.get_bytes(key) is not None, "什么都没变的一轮不该清缓存"

    # 用户绕过 App 直接往 NAS 目录里丢一本：这条变更**没有** invalidate() 可挂，
    # 只能靠刷新报告 added 来失效
    _put_epub(env["root"], "红楼.epub", body="<p>另一本</p>")
    out = catalog.refresh_library(lib)
    assert out["added"] == 1, out
    assert cache.get_bytes(key) is None, "索引真变了就必须丢缓存"
    assert "红楼.epub" in [b["name"] for b in library.books(env["lid"])]


def test_换库时列表键跟着丢(env, redis_url):  # noqa: ARG001
    """``db.close()`` → ``catalog.reset_state()``：库 id 会被下一个用例重用
    （测试里都叫 'novels'），旧键留着就会读到上一个用例的书。"""
    _put_epub(env["root"], "西游.epub")
    library.books(env["lid"])
    key = cache.book_list_key(env["lid"])
    assert cache.get_bytes(key) is not None

    catalog.reset_state()
    assert cache.get_bytes(key) is None


# ---------------- ④ 章节：键带源指纹，文件一变就换 ----------------

def test_章节命中缓存且源文件一变就换键(client, auth_headers, default_root, redis_url):  # noqa: ARG001
    _put_epub(default_root, "西游.epub", body="<p>甲</p>")
    bid = next(b["id"] for b in library.books() if b["name"] == "西游.epub")
    url = f"/api/books/{bid}/chapter/0"

    r1 = client.get(url, headers=auth_headers)
    assert r1.status_code == 200, r1.text
    assert "甲" in r1.json()["html"]

    hit0 = cache.stats()["hit"]
    r2 = client.get(url, headers=auth_headers)
    assert r2.json() == r1.json()
    assert cache.stats()["hit"] == hit0 + 1, "第二次取同一章应当命中缓存"

    # 同路径重建（章节数不变 ⇒ 只有文件指纹能区分新旧）
    _put_epub(default_root, "西游.epub", body="<p>丙</p>")
    r3 = client.get(url, headers=auth_headers)
    assert r3.status_code == 200, r3.text
    assert "丙" in r3.json()["html"], "文件变了还发旧正文"
    assert "甲" not in r3.json()["html"]


def test_TXT两条路线不串键():
    """派生 EPUB 与原生分章的 index 语义各自内聚（第 55 期），**不许跨路线命中**。"""
    assert cache.chapter_key("b", 0, "1:2", "epub") != cache.chapter_key("b", 0, "1:2", "native")
    assert cache.chapter_key("b", 0, "1:2") == cache.chapter_key("b", 0, "1:2", "epub")
    # 指纹进键：同一个 (书, 章节) 在不同指纹下必须是两个键
    assert cache.chapter_key("b", 0, "1:2") != cache.chapter_key("b", 0, "3:4")


def test_没有指纹就不缓存(monkeypatch, tmp_path):
    """取不到源文件（已经被人删了 / 权限）→ 直接不缓存，而不是拿一个空指纹当真。"""
    assert cache.fingerprint(tmp_path / "不存在.epub") == ""


# ---------------- ⑤ 封面：媒体类型跟着字节一起存 ----------------

def test_封面缓存的媒体类型跟着字节走(tmp_path, redis_url):  # noqa: ARG001
    src = tmp_path / "漫画.cbz"
    src.write_bytes(b"PK\x03\x04")
    # 字节里**故意带 \n**（PNG 头就是 \x89PNG\r\n\x1a\n）：证明分界靠的是我们加的那个
    # 换行，不是「数据里没有换行」这个不成立的假设
    data = b"\x89PNG\r\n\x1a\nBINARY-BYTES"
    calls = []

    def produce():
        calls.append(1)
        return data, "image/png"

    r1 = server._cover_cached("bid1", src, produce)
    assert bytes(r1.body) == data
    assert r1.media_type == "image/png"

    r2 = server._cover_cached("bid1", src, produce)
    assert len(calls) == 1, "第二次应当命中缓存"
    assert bytes(r2.body) == data
    assert r2.media_type == "image/png", "媒体类型没跟着字节一起存回来"

    # 文件一变（指纹变）→ 换键，新内容立刻可见
    src.write_bytes(b"PK\x03\x04\x00\x00")
    os.utime(src, (1, 1))
    r3 = server._cover_cached("bid1", src, lambda: (b"NEW", "image/jpeg"))
    assert len(calls) == 1 and bytes(r3.body) == b"NEW"
