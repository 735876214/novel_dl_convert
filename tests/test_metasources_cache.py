"""第 102 期：检索缓存 与 主动限流 的行为契约。

两块都是**进程内**能力，且都有一类「看起来对、实际有害」的写法，本文件专门钉住：

**缓存**
- 命中时**不再外呼**（这是它存在的唯一理由 —— 用调用计数证明，不是看返回值）；
- **空结果不缓存**：一次网络抖动 / 站点抽风不该让这家源「假死」整个 TTL；
- 该源的 `opts`（`resolution` / `region` / `api_key`…）**进缓存键**：换选项必须换结果；
- `force=True` = **诊断模式：缓存与限流都旁路**（体检 / 「测试这一家」必须反映当下）；
- TTL 到期后重新外呼；`cache_ttl<=0` 等于关掉；
- 上限淘汰：超过 `_SEARCH_CACHE_MAX` 不无限涨；
- 缓存值**浅拷贝**：调用方往候选里写 score 不能污染缓存（否则第二次命中会带着上次的分）。

**限流**
- 声明的 `(次数, 秒)` 真的补足间隔（用假时钟，不真等）；
- 未声明限流的家**不 sleep**；
- 体检（`health_one`）与自检（`probe`）走 `force=True` ⇒ **缓存与限流都旁路**：
  并发 4 路 + 单家 12s 超时下，串行补间隔（comicvine 声明 18s）会被当成源超时；
- 只给 source 不传书名时，体检**回落到该家的地区样本**，而不是报「书名为空」。

⚠️ 全程离线：把 `_FETCHERS[源]` 换成桩函数，**任何真网络调用都会以计数暴露出来**。
"""
import pytest

from novelforge.core import metasources as M
from novelforge.core.sources import registry


@pytest.fixture(autouse=True)
def _clean_state():
    """每个用例前后都清干净：缓存与「上次调用时刻」都是模块级状态。"""
    M.clear_cache()
    M._LAST_CALL.clear()
    yield
    M.clear_cache()
    M._LAST_CALL.clear()


class _Counter:
    """桩 fetcher：数调用次数，可切换返回值。"""

    def __init__(self, entries=None, error=None):
        self.calls = 0
        self.entries = entries if entries is not None else [
            {"title": "三体", "author": "刘慈欣", "source": "stub"}]
        self.error = error
        self.titles = []

    def __call__(self, title, author, limit, opts):
        self.calls += 1
        self.titles.append(title)
        if self.error:
            raise self.error
        return [dict(e) for e in self.entries]


@pytest.fixture
def stub(monkeypatch):
    """把 openlibrary 的抓取器换成计数器（其余家不动）。"""
    def _install(**kw):
        c = _Counter(**kw)
        monkeypatch.setitem(M._FETCHERS, "openlibrary", c)
        return c
    return _install


# ---------------------------------------------------------------- 缓存

def test_命中缓存时不再外呼(stub):
    """**缓存存在的唯一理由**：第二次同样检索不发第二次外呼。"""
    c = stub()
    a = M.search("openlibrary", "三体", "刘慈欣", 5)
    b = M.search("openlibrary", "三体", "刘慈欣", 5)

    assert c.calls == 1, f"第二次应命中缓存，实际外呼 {c.calls} 次"
    assert a["ok"] and b["ok"]
    assert [e["title"] for e in a["entries"]] == [e["title"] for e in b["entries"]]


def test_书名的归一化差异也算同一个缓存键(stub):
    """`norm_key` 口径：大小写 / 全半角 / 多余空格不同仍是同一本书，不该重复外呼。"""
    c = stub()
    M.search("openlibrary", "Three Body", "", 5)
    M.search("openlibrary", "  three   body  ", "", 5)
    assert c.calls == 1, f"归一化后应命中同一缓存键，实际 {c.calls} 次"


def test_不同limit不共用缓存(stub):
    """limit 是外呼参数的一部分（它决定源侧返回几条）—— 必须进缓存键。"""
    c = stub()
    M.search("openlibrary", "三体", "", 3)
    M.search("openlibrary", "三体", "", 9)
    assert c.calls == 2, f"limit 不同应各算一次，实际 {c.calls} 次"


def test_不同的选项不共用缓存(stub):
    """`opts` 必须进缓存键 —— 换选项就会换结果。

    ⚠️ 这条是**真事故**的回填：键里漏了 `opts` 时，itunes 先按 `resolution=high`
    取到 1000x1000 封面，再按 `standard` 查会**命中上一条缓存**，返回 1000x1000 ——
    用户改了设置却看不出变化（`tests/test_metasources_parsers.py` 抓到的）。
    """
    c = stub()
    M.search("openlibrary", "三体", "", 5, {"resolution": "high"})
    M.search("openlibrary", "三体", "", 5, {"resolution": "standard"})
    assert c.calls == 2, f"选项不同应各算一次，实际 {c.calls} 次"
    # 键里存的是摘要而不是原值：密钥不该以明文躺在缓存里
    M.search("openlibrary", "三体", "", 5, {"api_key": "SECRET-abc"})
    assert all("SECRET" not in str(k) for k in M._SEARCH_CACHE), M._SEARCH_CACHE


def test_force旁路缓存(stub):
    """`force=True` 必须真的重新外呼 —— 体检与「测试这一家」靠它反映当下。"""
    c = stub()
    M.search("openlibrary", "三体", "", 5)
    M.search("openlibrary", "三体", "", 5, force=True)
    assert c.calls == 2, f"force 应旁路缓存，实际 {c.calls} 次"


def test_空结果不缓存(stub, monkeypatch):
    """空结果不缓存：一次抖动不该让这家源「假死」整个 TTL。

    反过来说，只有「成功且有内容」才值得记 —— 否则用户看到的是
    「刚才还能用，现在什么都没了」，而实际早就恢复了。
    """
    c = stub(entries=[])
    M.search("openlibrary", "三体", "", 5)
    assert c.calls == 1
    # 第二次仍应外呼（因为上次是空的）
    M.search("openlibrary", "三体", "", 5)
    assert c.calls == 2, f"空结果不该被缓存，实际 {c.calls} 次"

    # 桩改成有结果后，这一次应被缓存
    c.entries = [{"title": "三体", "author": "刘慈欣", "source": "stub"}]
    M.search("openlibrary", "三体", "", 5)
    M.search("openlibrary", "三体", "", 5)
    assert c.calls == 3, f"有结果后应缓存（第 4 次命中），实际 {c.calls} 次"


def test_报错的结果不缓存(stub):
    """失败不缓存：否则「刚才网络抖了一下」会被记成整个 TTL 的失败。"""
    c = stub(error=RuntimeError("boom"))
    r = M.search("openlibrary", "三体", "", 5)
    assert r["ok"] is False and "boom" in r["error"]
    M.search("openlibrary", "三体", "", 5)
    assert c.calls == 2, f"失败不该被缓存，实际 {c.calls} 次"


def test_TTL到期后重新外呼(stub, monkeypatch):
    """过期即失效（用假时钟推进，不真等）。"""
    c = stub()
    fake = {"t": 1000.0}
    monkeypatch.setattr(M.time, "monotonic", lambda: fake["t"])

    M.search("openlibrary", "三体", "", 5)
    assert c.calls == 1
    # TTL 内（默认 600s）
    fake["t"] = 1000.0 + 599
    M.search("openlibrary", "三体", "", 5)
    assert c.calls == 1, "TTL 内不该重新外呼"
    # 过期
    fake["t"] = 1000.0 + 601
    M.search("openlibrary", "三体", "", 5)
    assert c.calls == 2, "TTL 过期后应重新外呼"


def test_cache_ttl为0等于关闭缓存(stub, monkeypatch):
    """`cache_ttl=0` ⇒ 每次外呼（关缓存的出口，给「我就要最新」的用户）。"""
    c = stub()
    monkeypatch.setitem(M.SOURCES["openlibrary"], "cache_ttl", 0)
    M.search("openlibrary", "三体", "", 5)
    M.search("openlibrary", "三体", "", 5)
    assert c.calls == 2, f"ttl=0 应每次外呼，实际 {c.calls} 次"


def test_缓存有上限且不无限增长(stub, monkeypatch):
    """超上限按插入序淘汰最旧 —— 长跑进程不该因为缓存涨到吃内存。"""
    monkeypatch.setattr(M, "_SEARCH_CACHE_MAX", 3)
    c = stub()
    for i in range(6):
        M.search("openlibrary", f"书{i}", "", 5)
        assert len(M._SEARCH_CACHE) <= 3, f"第 {i} 次后缓存涨到 {len(M._SEARCH_CACHE)}"
    assert c.calls == 6
    assert M.cache_stats()["max"] == 3


def test_缓存值不会被调用方污染(stub):
    """缓存必须**浅拷贝**每条：`search_all` 会往候选里写 score。

    不拷贝的话，第二次命中会连着上次算好的分数 —— 而那个分数是对**别的书名**算的，
    会静默给出错误排序（这正是「看起来对、实际有害」那一类）。
    """
    c = stub()
    a = M.search("openlibrary", "三体", "", 5)
    a["entries"][0]["score"] = 0.123
    a["entries"][0]["title"] = "被改过的"
    b = M.search("openlibrary", "三体", "", 5)
    assert c.calls == 1
    assert "score" not in b["entries"][0], "缓存被调用方污染了（score 泄漏）"
    assert b["entries"][0]["title"] == "三体", "缓存被调用方污染了（title 泄漏）"


def test_clear_cache与stats():
    M.clear_cache()
    assert M.cache_stats() == {"entries": 0, "max": M._SEARCH_CACHE_MAX}


# ---------------------------------------------------------------- 限流

def test_声明的限流真的补足间隔(stub, monkeypatch):
    """按 `(次数, 秒)` 补足最小间隔 —— 用假时钟记录 sleep，不真等。"""
    slept = []
    fake = {"t": 500.0}
    monkeypatch.setattr(M.time, "monotonic", lambda: fake["t"])
    monkeypatch.setattr(M.time, "sleep", lambda s: (slept.append(s), fake.__setitem__("t", fake["t"] + s)))
    # ranobedb 声明 (1, 1.0)：每 1 秒最多 1 次
    assert M.SOURCES["ranobedb"]["rate_limit"] == [1, 1.0]
    monkeypatch.setitem(M._FETCHERS, "ranobedb", stub())

    M.search("ranobedb", "书A", "", 5)
    assert slept == [], "首次调用不该等"
    M.search("ranobedb", "书B", "", 5)
    assert len(slept) == 1, f"第二次应补足间隔，实际 sleep {slept}"
    assert slept[0] == pytest.approx(1.0, abs=0.01)


def test_诊断模式旁路限流(stub, monkeypatch):
    """`force=True`（体检 / 「测试这一家」）不能被自己的限流拖到超时。

    体检是并发 4 路 + 单家 12s 超时，而 comicvine 声明 18s 间隔 ⇒ 若限流照走，
    它会把**自己的 sleep** 记成源超时，把健康源误报成 `timeout`。
    """
    slept = []
    monkeypatch.setattr(M.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setitem(M._FETCHERS, "comicvine", stub())
    M.search("comicvine", "书A", "", 5, force=True)
    M.search("comicvine", "书B", "", 5, force=True)
    assert slept == [], f"诊断模式不该限流，实际 sleep {slept}"


def test_未声明限流的家不sleep(stub, monkeypatch):
    slept = []
    monkeypatch.setattr(M.time, "sleep", lambda s: slept.append(s))
    assert M.SOURCES["openlibrary"]["rate_limit"] == []
    monkeypatch.setitem(M._FETCHERS, "openlibrary", stub())
    for i in range(4):
        M.search("openlibrary", f"书{i}", "", 5)
    assert slept == [], f"未声明限流的家不该 sleep，实际 {slept}"


def test_限流值与官方额度一致():
    """写实、不猜：这三家是声明了限流的全部，值来自各家官方文档。"""
    limited = {sid: M.SOURCES[sid]["rate_limit"] for sid in M.SOURCES
               if M.SOURCES[sid]["rate_limit"]}
    assert limited == {"comicvine": [1, 18.0], "ranobedb": [1, 1.0], "audible": [1, 0.5]}, limited


def test_限流状态按源分开记(stub, monkeypatch):
    """一家的节流不该拖累别家（`_LAST_CALL` 是 per-source 的）。"""
    slept = []
    fake = {"t": 500.0}
    monkeypatch.setattr(M.time, "monotonic", lambda: fake["t"])
    monkeypatch.setattr(M.time, "sleep", lambda s: (slept.append(s), fake.__setitem__("t", fake["t"] + s)))
    monkeypatch.setitem(M._FETCHERS, "ranobedb", stub())
    monkeypatch.setitem(M._FETCHERS, "comicvine", stub())

    M.search("ranobedb", "书A", "", 5)      # 记下 ranobedb 的时刻
    M.search("comicvine", "书B", "", 5)     # 另一家，不该等了
    assert slept == [], f"不同源之间不该互相节流，实际 {slept}"


# ---------------------------------------------------------------- 体检必须反映当下

def test_体检旁路缓存(stub):
    """`health_one` 的结论必须反映**当下** —— 缓存命中会让真断线也显示「可用」。"""
    c = stub()
    M.search("openlibrary", M.HEALTH_SAMPLES["openlibrary"][0],
             M.HEALTH_SAMPLES["openlibrary"][1], 3)
    assert c.calls == 1
    M.health_one("openlibrary")
    assert c.calls == 2, f"体检应强制外呼，实际 {c.calls} 次"


def test_体检只给源时回落到该家样本(stub, monkeypatch):
    """只传 source 不能变成「书名为空」—— 那会把人引去修一个根本没坏的源。"""
    c = stub()
    M.health_one("openlibrary")
    assert c.titles == [M.HEALTH_SAMPLES["openlibrary"][0]], c.titles

    # 有地区样本的家必须用它**自己的**：拿 Dune 去查 RanobeDB（轻小说）本来就搜不到
    ja = stub()
    monkeypatch.setitem(M._FETCHERS, "ranobedb", ja)
    assert M.HEALTH_SAMPLES["ranobedb"][0] != M.HEALTH_SAMPLE_DEFAULT[0]
    M.health_one("ranobedb")
    assert ja.titles == [M.HEALTH_SAMPLES["ranobedb"][0]], ja.titles


def test_probe旁路缓存(stub):
    """`probe`（设置页「测试」）同理。"""
    c = stub()
    M.probe("openlibrary")
    assert c.calls == 1
    M.probe("openlibrary")
    assert c.calls == 2, f"probe 应强制外呼，实际 {c.calls} 次"


# ---------------------------------------------------------------- 声明里真有这些字段

def test_限流与缓存字段进了注册表():
    for p in registry.DECLARED:
        meta = M.SOURCES[p.id]
        assert meta["rate_limit"] == list(p.rate_limit), p.id
        assert meta["cache_ttl"] == p.cache_ttl, p.id
