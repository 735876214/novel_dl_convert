"""第 94 期 · 阶段 4b：规则里的 JS 走**真沙箱**（quickjs），带时间/内存/栈三道上限。

**要钉住的病**：书源文件是**第三方**给的，`@js:` / `<js>` 片段等于把任意代码执行交出去。
第 86 期的 Node 通道里那些片段拿得到 `require('fs')` / 出网，而且**没有任何上限** ——
`while(true){}` 会把子进程一直挂着。

本文件分两截：

* **路由与接线**（`js_engine` / `run_source_js` / `rules`）—— 本机装不上 quickjs 也能跑，
  靠 monkeypatch；
* **真引擎**（`skipif not jssandbox.available()`）—— 逐条钉住「超时真的中断、
  无宿主能力、三道上限各自生效」。本机 Python 3.14 装不上 quickjs
  （PyPI 只有 cp38–cp312 的预编译包），这部分在本机 skip；**在 3.12 上另跑一遍**
  （见提交说明），而 3.12 正是生产镜像的版本。
"""
import asyncio
import ast
import pathlib
import time

import pytest

from novelforge.core import jssandbox, network
from novelforge.sources import rules

_NEED_QJS = pytest.mark.skipif(not jssandbox.available(),
                               reason="本机没有 quickjs（部署前提见 /api/sources/capabilities）")
_REPO = pathlib.Path(__file__).resolve().parents[1]


def _no_sandbox(monkeypatch):
    monkeypatch.setattr(jssandbox, "_AVAILABLE", False)
    monkeypatch.setattr(jssandbox, "_IMPORT_ERROR", "ImportError: 测试桩")


def _fake_sandbox(monkeypatch, *, result="明文", exc=None):
    """把沙箱换成桩：只管「路由有没有走对」，不碰真引擎。"""
    monkeypatch.setattr(jssandbox, "_AVAILABLE", True)
    calls: list = []

    async def fake_run(code, *args, **kw):
        calls.append((code, args))
        if exc:
            raise exc
        return result

    monkeypatch.setattr(jssandbox, "run_js", fake_run)
    return calls


# ---------------- ① state() 如实 ----------------

def test_有quickjs时state说真话():
    if not jssandbox.available():
        pytest.skip("本机没有 quickjs")
    st = jssandbox.state()
    assert st["available"] is True and st["engine"] == "quickjs"
    assert st["time_limit"] > 0 and st["memory_limit"] > 0 and st["stack_limit"] > 0
    assert st["reason"] == ""


def test_没有quickjs时state标明没有沙箱(monkeypatch):
    _no_sandbox(monkeypatch)
    st = jssandbox.state()
    assert st["available"] is False and st["engine"] == ""
    assert "沙箱" in st["reason"] and "quickjs" in st["reason"]
    assert "pip install quickjs" in st["reason"], "要给能照做的补法"
    # 3.14 上确实没有预编译包 —— 这句话比「没装」有用得多，必须写进原因里
    assert "3.14" in st["reason"] and "3.12" in st["reason"]


def test_没有引擎时抛人话而不是偷偷跑(monkeypatch):
    """**最关键的一条**：沙箱不可用时 `run_js_sync` 必须抛，**绝不**换成别的通道。

    这就是「绝不偷偷回退 Node」的落法：路由层可以回落（并如实标注），
    但沙箱这一层**自己**不许变通 —— 不然「有个叫沙箱的模块」就成了空话。
    """
    _no_sandbox(monkeypatch)
    with pytest.raises(jssandbox.JSSandboxUnavailable) as e:
        jssandbox.run_js_sync("return 1;")
    assert "quickjs" in str(e.value)


def test_没有引擎时异步入口也抛(monkeypatch):
    _no_sandbox(monkeypatch)
    with pytest.raises(jssandbox.JSSandboxUnavailable):
        asyncio.run(jssandbox.run_js("return 1;"))


# ---------------- ② 真引擎：语义与上限 ----------------

@_NEED_QJS
def test_基本语义_args与result两种读法都能用():
    assert jssandbox.run_js_sync("return __args[0].toUpperCase();", "abc") == "ABC"
    assert jssandbox.run_js_sync("return result + '（已解密）';", "密文") == "密文（已解密）"
    assert jssandbox.run_js_sync("return __args.length;", 1, 2, 3) == 3
    assert jssandbox.run_js_sync("return 42;") == 42
    assert jssandbox.run_js_sync("return true;") is True


@_NEED_QJS
def test_非字符串返回值原样交回调用方判():
    """`undefined` / `null` → None，对象 → dict —— 由调用方判「是不是明文」。

    沙箱自己**不许**把 `undefined` String() 成 "undefined"（那正是第 86 期修掉的病）。
    """
    assert jssandbox.run_js_sync("var x = 1;") is None
    assert jssandbox.run_js_sync("return null;") is None
    assert jssandbox.run_js_sync("return {a: 1};") == {"a": 1}
    assert jssandbox.run_js_sync("return [1, 2];") == [1, 2]


@_NEED_QJS
def test_没有宿主能力():
    """沙箱的全部意义在这里：`require` / 出网 / 进程 API 一个都拿不到。"""
    out = jssandbox.run_js_sync(
        "return [typeof require, typeof fetch, typeof process, typeof XMLHttpRequest,"
        " typeof setTimeout, typeof globalThis].join(',');")
    assert out == "undefined,undefined,undefined,undefined,undefined,object", out


@_NEED_QJS
def test_死循环真的被中断():
    """`set_time_limit` 是**中断处理**，不是「跑完再看耗时」—— 证据是它真的返回了。"""
    t0 = time.perf_counter()
    with pytest.raises(jssandbox.JSTimeout) as e:
        jssandbox.run_js_sync("while(true){}", timeout=0.4)
    spent = time.perf_counter() - t0
    assert spent < 5, f"没被中断：跑了 {spent:.1f} 秒"
    assert "超时" in str(e.value)


@_NEED_QJS
def test_内存上限生效():
    with pytest.raises(jssandbox.JSMemoryLimit):
        jssandbox.run_js_sync(
            "var a = []; while (true) { a.push(new Array(10000).fill(0)); }",
            timeout=5, memory=8 * 1024 * 1024)


@_NEED_QJS
def test_栈上限生效():
    with pytest.raises(jssandbox.JSStackOverflow):
        jssandbox.run_js_sync("return (function r(){ return r(); })();",
                              timeout=5, stack=128 * 1024)


@_NEED_QJS
def test_语法错误与运行时错误分得开():
    with pytest.raises(jssandbox.JSError) as e1:
        jssandbox.run_js_sync("return (", )
    assert "语法错误" in str(e1.value)
    with pytest.raises(jssandbox.JSError) as e2:
        jssandbox.run_js_sync("return nope.x;")
    assert "ReferenceError" in str(e2.value), str(e2.value)


@_NEED_QJS
def test_报错时把片段自己的日志带上():
    """`console.log` 不带出来的话，它就是个假接口（调了没反应、报错也看不到）。

    顺带钉住超时**没有被日志机制削弱**：这条路径上日志是在中断 / 报错之后读回来的。
    """
    with pytest.raises(jssandbox.JSError) as e:
        jssandbox.run_js_sync("console.log('我到这里了'); return nope.x;")
    assert "我到这里了" in str(e.value)


@_NEED_QJS
def test_跑通时片段日志进服务端日志(monkeypatch):
    """跑通了也不许把日志吞掉 —— 书源作者写 `console.log` 就是为了看它出现在哪。"""
    seen: list = []
    monkeypatch.setattr(jssandbox.logger, "debug", lambda *a, **kw: seen.append(a))
    assert jssandbox.run_js_sync("console.log('坐标', {a: 1}); return 'ok';") == "ok"
    assert seen and seen[0][1] == '坐标 {"a":1}', seen


@_NEED_QJS
def test_超时中断后的日志同样带得出来():
    """死循环 + 日志 = 最需要日志的一刻（「卡在哪一步」）。"""
    with pytest.raises(jssandbox.JSTimeout) as e:
        jssandbox.run_js_sync("console.log('进入循环'); while(true){}", timeout=0.4)
    assert "进入循环" in str(e.value)


@_NEED_QJS
def test_日志缓冲有上限():
    """片段在循环里刷日志时缓冲不许无限长（内存上限兜得住，但不该指望它兜）。

    直接读缓冲，不走 `run_js_sync`：那里为了报错文案只带前 10 行（**日志本身**不截断）。
    """
    fn = jssandbox._build("for (var i = 0; i < 500; i++) { console.log('第' + i); } return 'ok';")
    fn.set_memory_limit(jssandbox.DEFAULT_MEMORY_LIMIT)
    assert fn() == "ok"
    logs = jssandbox._read_logs(fn)
    assert len(logs) == jssandbox._MAX_LOG_LINES, f"缓冲该封顶，实际 {len(logs)} 行"
    assert logs[0] == "第0" and logs[-1] == f"第{jssandbox._MAX_LOG_LINES - 1}"


def test_console不用Python回调():
    """⚠️ 钉住踩过的坑：quickjs 设了 time limit 后**拒绝**回调进 Python
    （`InternalError: Can not call into Python with a time limit set`）
    —— 也就是 `add_callable` 与「有超时」二选一。我们选了超时（它是这一层的存在理由），
    所以日志走**纯 JS 缓冲**。不许有人「顺手」把 console 接回 Python 回调：
    那会让**每一条带日志的合法片段**直接报错，而且只有真装了 quickjs 才看得出来。
    """
    src = (_REPO / "novelforge" / "core" / "jssandbox.py").read_text(encoding="utf-8")
    bad = [n for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.Attribute) and n.attr == "add_callable"]
    assert not bad, "回调进 Python 与「有超时」在 quickjs 里二选一，我们选超时"
    assert "globalThis.__nf_logs" in src, "日志必须是 JS 侧缓冲、事后一次性读回"


@_NEED_QJS
def test_三道上限都是普通Exception():
    """逐条兜底：`manager._search_one` / `_fetch_toc._one` 用的是 `except Exception`。"""
    for exc in (jssandbox.JSSandboxUnavailable, jssandbox.JSTimeout,
                jssandbox.JSMemoryLimit, jssandbox.JSStackOverflow, jssandbox.JSError):
        assert issubclass(exc, RuntimeError) and issubclass(exc, Exception)


# ---------------- ③ 路由：沙箱优先，回落要如实标注 ----------------

def test_有沙箱时走沙箱(monkeypatch):
    calls = _fake_sandbox(monkeypatch, result="正文")
    eng = network.js_engine()
    assert eng["sandbox"] is True and eng["engine"] == "quickjs" and eng["reason"] == ""
    assert asyncio.run(network.run_source_js("return result;", "密")) == "正文"
    assert calls == [("return result;", ("密",))]


def test_没沙箱时回落Node并且标注非沙箱(monkeypatch):
    _no_sandbox(monkeypatch)
    monkeypatch.setattr(network, "node_state",
                        lambda refresh=False: {"available": True, "bin": "node",
                                               "version": "v22.0.0", "reason": ""})
    seen = []

    async def fake_decrypt(js, text):
        seen.append((js, text))
        return "Node 跑的"

    monkeypatch.setattr(network, "run_decrypt", fake_decrypt)
    monkeypatch.setitem(network._sandbox_warned, "done", True)   # 别在测试里刷日志

    eng = network.js_engine()
    assert eng["sandbox"] is False and eng["engine"] == "node"
    assert "非沙箱" in eng["reason"] and "quickjs" in eng["reason"]
    assert asyncio.run(network.run_source_js("return result;", "密")) == "Node 跑的"
    assert seen == [("return result;", "密")]


def test_沙箱与Node都没有时报人话(monkeypatch):
    _no_sandbox(monkeypatch)
    monkeypatch.setattr(network, "node_state",
                        lambda refresh=False: {"available": False, "bin": "node",
                                               "version": "", "reason": "找不到 Node"})
    called = []

    async def fake_decrypt(js, text):                            # noqa: ARG001
        called.append(1)
        return "不该走到这里"

    monkeypatch.setattr(network, "run_decrypt", fake_decrypt)
    eng = network.js_engine()
    assert eng["engine"] == "" and "Node" in eng["reason"]
    with pytest.raises(RuntimeError) as e:
        asyncio.run(network.run_source_js("return result;", "密"))
    assert "quickjs" in str(e.value) and "Node" in str(e.value)
    assert called == [], "两条通道都没有就不许再试任何一条"


def test_回落时只提醒一次(monkeypatch):
    """每个请求刷一行日志等于没有日志。"""
    _no_sandbox(monkeypatch)
    monkeypatch.setattr(network, "node_state",
                        lambda refresh=False: {"available": True, "bin": "node",
                                               "version": "v22", "reason": ""})
    monkeypatch.setitem(network._sandbox_warned, "done", False)
    warnings: list = []
    monkeypatch.setattr(network.logger, "warning", lambda *a, **kw: warnings.append(a))

    async def fake_decrypt(js, text):                            # noqa: ARG001
        return "ok"

    monkeypatch.setattr(network, "run_decrypt", fake_decrypt)
    asyncio.run(network.run_source_js("return result;", "a"))
    asyncio.run(network.run_source_js("return result;", "b"))
    assert len(warnings) == 1, warnings


def test_沙箱交回非字符串时按同一口径报错(monkeypatch):
    """`undefined` 被 String() 一下当明文写进书里 —— 第 86 期修掉的正是这个。"""
    _fake_sandbox(monkeypatch, result=None)
    with pytest.raises(RuntimeError, match="没有返回字符串"):
        asyncio.run(network.run_source_js("var x = 1;", "密"))


def test_两条通道的报错文案是同一份():
    """口径不许漂：Node 通道与沙箱通道必须说同一句话。"""
    src = (_REPO / "novelforge" / "core" / "network.py").read_text(encoding="utf-8")
    assert src.count("解密脚本没有返回字符串") == 1, "文案出现了多份 ⇒ 迟早各说各的"


# ---------------- ④ 接线：规则里的两处 JS 都走同一个入口 ----------------

def _js_rule(**book) -> dict:
    return {"name": "带 JS 的源", "domains": ["d.com"],
            "book": {"mode": "toc", "toc": {"mode": "css", "container": "a"},
                     "content": {"mode": "css", "container": "#c"}}, **book}


class _StubClient:
    def __init__(self, pages):
        self.pages = pages

    async def get_text(self, url):
        return self.pages[url]


def test_正文模式js走规则JS的唯一入口(monkeypatch):
    seen = []

    async def fake(js, text):
        seen.append((js, text))
        return "正文一"

    monkeypatch.setattr(network, "run_source_js", fake)

    async def boom(*a, **kw):                                    # noqa: ARG001
        raise AssertionError("正文 mode=js 不许直接走 Node 通道")

    monkeypatch.setattr(network, "run_decrypt", boom)
    src = rules.make_rule_class(_js_rule(
        book={"mode": "toc", "toc": {"mode": "css", "container": "a"},
              "content": {"mode": "js", "script": "return result.split('|')[1];"}}))()
    pages = {"https://d.com/b": '<a href="/c1">一</a>', "https://d.com/c1": "标题|正文一"}
    chaps = asyncio.run(src.fetch_book_chapters(_StubClient(pages), {"url": "https://d.com/b"}))
    assert [c["body"] for c in chaps] == ["正文一"]
    assert seen == [("return result.split('|')[1];", "标题|正文一")]


def test_解密片段也走规则JS的唯一入口(monkeypatch):
    seen = []

    async def fake(js, text):
        seen.append((js, text))
        return "已解密"

    monkeypatch.setattr(network, "run_source_js", fake)
    src = rules.make_rule_class(_js_rule(decrypt_js="return __args[0].replace('X','');"))()
    assert asyncio.run(src._decrypt("密X文")) == "已解密"
    assert seen == [("return __args[0].replace('X','');", "密X文")]


def test_没配解密片段就不碰任何通道():
    src = rules.make_rule_class(_js_rule())()
    assert src.decryption_js() is None
    assert asyncio.run(src._decrypt("原文")) == "原文"


# ---------------- ⑤ 能力接口如实下发 ----------------

def test_capabilities报出js通道(client, auth_headers):
    body = client.get("/api/sources/capabilities", headers=auth_headers).json()
    assert "js" in body and "js" in body["hints"]
    assert body["js"] == network.js_engine(), "接口必须原样下发 js_engine()，不许自己再算一遍"
    assert body["hints"]["js"] == body["js"]["reason"]
    if jssandbox.available():
        assert body["js"]["sandbox"] is True
    else:
        assert body["js"]["sandbox"] is False and body["hints"]["js"]


def test_能力接口在沙箱缺失时如实标非沙箱(client, auth_headers, monkeypatch):
    _no_sandbox(monkeypatch)
    monkeypatch.setattr(network, "node_state",
                        lambda refresh=False: {"available": True, "bin": "node",
                                               "version": "v22", "reason": ""})
    body = client.get("/api/sources/capabilities", headers=auth_headers).json()
    assert body["js"]["sandbox"] is False
    assert "非沙箱" in body["hints"]["js"]
