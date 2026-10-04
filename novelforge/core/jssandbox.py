"""书源规则里的 JS 的**唯一**执行处：真沙箱（quickjs），带时间 / 内存 / 栈三道上限。

## 为什么不能再只用 Node 子进程

书源文件是**第三方**给的，`@js:` / `<js>` 片段等于把**任意代码执行**交给它：

* Node 通道里那些片段拿得到 `require('fs')` / `process` / 出网 —— 一份书源文件就能读走
  `CONFIG_DIR` 下的 Cookie、书源密钥，甚至改盘上的文件；
* Node 通道**没有任何上限**：`while(true){}` 会把子进程一直挂着，没有超时、没有内存上限。

## 沙箱给了什么（全部实测，不是照文档抄的）

| 能力 | 实测结果 |
|---|---|
| 无宿主能力 | `typeof require / fetch / process` 全是 `undefined`（只有 `globalThis` 与 JS 自带的 `eval`） |
| 超时真的中断 | `set_time_limit(0.4)` + `while(true){}` ⇒ 0.4 秒时抛 `InternalError: interrupted` |
| 内存上限 | `set_memory_limit(8MiB)` + 无限 push ⇒ `InternalError: out of memory` |
| 栈上限 | `set_max_stack_size` + 无限递归 ⇒ `quickjs.StackOverflow` |

三样都齐全，所以这一层**可以**自称沙箱。**缺 `quickjs` 时不冒充**：:func:`state` 如实标
`available: false` + 一句能照做的原因，绝不偷偷退化成「随便跑」。

## ⚠️ 踩过的坑：设了 time limit 就不能回调进 Python

`add_callable("__nf_log", ...)`（把 `console.log` 接到 Python 列表上）在**设了时间上限时直接报错**：

```
InternalError: Can not call into Python with a time limit set.
```

也就是说「有超时」与「Python 回调」在 quickjs 里**二选一**。超时是安全底线（这一层的存在
理由），所以日志改成**纯 JS 侧缓冲**：片段里不产生任何 Python 回调，
`console` 把行推进 `globalThis.__nf_logs`，调用结束（**被中断之后也读得到，实测**）
再用 `Function.globalThis.json()` 一次性取回（见 :func:`_read_logs`）。

## 与 Node 通道的关系

`core/network.py` 的 `run_js_sync` / `run_decrypt` 是**第 86 期留下的 Node 通道**
（**非沙箱**，只为既有契约保留）。书源规则里的 JS 走的是
`network.run_source_js` —— 沙箱优先，缺 quickjs 才回落 Node 并**在 capabilities 里标出来**。
这一层的 `run_js` **永远不碰 Node**：它的契约就是「要么沙箱，要么明说没有沙箱」。
"""
import asyncio
import json
import logging
import re
import time

logger = logging.getLogger(__name__)

try:                                            # 「有没有沙箱引擎」只有这一处判据
    import quickjs as _qjs

    _AVAILABLE = True
    _IMPORT_ERROR = ""
except ImportError as _e:                       # pragma: no cover - 取决于运行环境
    _qjs = None
    _AVAILABLE = False
    _IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

#: 片段时间上限（秒）。书源里的 JS 都是「几行字符串处理」，2 秒已是极宽裕的量级；
#: 超了基本是死循环而不是算得慢。
DEFAULT_TIME_LIMIT = 2.0

#: 内存上限（字节）。Legado 片段处理的是**一章正文**（几十 KB 到几 MB），32 MiB 足够，
#: 又拦得住「无限 new Array 吃光容器内存」。
DEFAULT_MEMORY_LIMIT = 32 * 1024 * 1024

#: 栈上限（字节）。默认 256 KiB（quickjs 默认 256 KiB 量级）—— 拦的是无限递归。
DEFAULT_STACK_LIMIT = 256 * 1024


class JSSandboxUnavailable(RuntimeError):
    """本机没有沙箱引擎（`quickjs` 装不上）。**绝不**因此偷偷换成没有护栏的通道。"""


class JSTimeout(RuntimeError):
    """片段超时（死循环 / 回溯爆炸）。只废掉这一条源，不中断整本。"""


class JSMemoryLimit(RuntimeError):
    """片段撞内存上限。"""


class JSStackOverflow(RuntimeError):
    """片段递归太深 / 表达式嵌套太深，撞栈上限。"""


class JSError(RuntimeError):
    """片段自己的语法 / 运行时错误（原文照回，不改写成「未知错误」）。"""


def available() -> bool:
    """有沙箱引擎吗 —— 「规则里的 JS 能不能带护栏跑」的**唯一**判据。"""
    return _AVAILABLE


def state() -> dict:
    """给 `/api/sources/capabilities` 与设置页看的如实状态。

    ``available: false`` 时必须同时给出**能照做的原因** —— 缺依赖的报错里
    「为什么装不上」比「没装」有用得多（3.14 上确实没有预编译包）。
    """
    if _AVAILABLE:
        return {"available": True, "engine": "quickjs", "version": _version(),
                "time_limit": DEFAULT_TIME_LIMIT,
                "memory_limit": DEFAULT_MEMORY_LIMIT,
                "stack_limit": DEFAULT_STACK_LIMIT, "reason": ""}
    return {
        "available": False, "engine": "", "version": "",
        "time_limit": DEFAULT_TIME_LIMIT,
        "memory_limit": DEFAULT_MEMORY_LIMIT,
        "stack_limit": DEFAULT_STACK_LIMIT,
        "reason": "未安装 quickjs（JS 沙箱引擎）⇒ 书源规则里的 JS 片段**没有沙箱可用**。"
                  f"（{_IMPORT_ERROR}）"
                  "补法：`pip install quickjs`。注意它目前**没有 CPython 3.14 的预编译包**"
                  "（3.12/3.13 有），要么用 3.12/3.13 跑，要么本机装 C++ 编译器自行构建。",
    }


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("quickjs")
    except Exception:                                    # noqa: BLE001 —— 探不到就如实留空
        return ""


#: 一次调用最多留多少行 `console` 输出 —— 片段在死循环里刷日志时，
#: 缓冲**不许**跟着无限长（内存上限兜得住，但不该指望它兜）。
_MAX_LOG_LINES = 200


#: 片段被包进一个**函数体**里跑 —— 与 `network.wrap_decrypt` 的口径一致（两边都要求片段自己
#: 写 `return`）。`console` 五个方法全指向**纯 JS** 的收集函数（见模块 docstring：设了
#: time limit 后**不能**回调进 Python），行攒在 `globalThis.__nf_logs` 上等 Python 取。
_SCRIPT = """function __nf_main() {
  var __args = Array.prototype.slice.call(arguments);
  var result = __args.length ? __args[0] : undefined;
  var __nf_logs = [];
  var __nf_sink = function () {
    var parts = [];
    for (var i = 0; i < arguments.length; i++) {
      var x = arguments[i];
      try {
        if (typeof x === 'string') { parts.push(x); }
        else {
          var s = JSON.stringify(x);
          parts.push(s === undefined ? String(x) : s);
        }
      } catch (e) { parts.push(String(x)); }
    }
    if (__nf_logs.length < __NF_LOG_MAX__) { __nf_logs.push(parts.join(' ')); }
  };
  var console = {log: __nf_sink, info: __nf_sink, warn: __nf_sink,
                 error: __nf_sink, debug: __nf_sink};
  globalThis.__nf_logs = __nf_logs;
  return (function() {
__NF_CODE__
})();
}
"""


def _build(code: str):
    """编译一次片段的包装脚本。语法错误在这一步就会抛（`SyntaxError` 原文在消息里）。"""
    script = (_SCRIPT.replace("__NF_LOG_MAX__", str(_MAX_LOG_LINES))
                     .replace("__NF_CODE__", str(code or "")))
    return _qjs.Function("__nf_main", script)


def _read_logs(fn) -> list:
    """取回片段 `console` 过的东西。

    ⚠️ 这里**绕了一圈**（读 `globalThis` 再自己解 JSON）而不是用 `add_callable`：
    quickjs 设了时间上限后**拒绝**任何回调进 Python（见模块 docstring 的实测报错）。
    超时不能让，所以让日志换一种走法 —— 实测**被中断之后**这一步照旧读得到。
    读不回来只是**日志**没了，绝不能因此改变片段本身的结论 ⇒ 一律吞掉异常返回空。
    """
    try:
        got = json.loads(fn.globalThis.json()).get("__nf_logs")
    except Exception:                                    # noqa: BLE001 —— 见上：只影响日志
        return []
    if not isinstance(got, list):
        return []
    return [line for line in got if isinstance(line, str)]


def _classify(exc, *, timeout: float, elapsed: float) -> RuntimeError:
    """quickjs 只抛 `JSException` 一种类型（消息里才看得出是哪个上限）。

    ⚠️ 这里**靠消息子串分档**，不是靠类型 —— 所以判不出来时**不硬猜**：
    落回 `JSError` 并把原文交给调用方，超时只多用一条「耗时已到上限」的旁证兜底。
    """
    if isinstance(exc, _qjs.StackOverflow):
        return JSStackOverflow(
            f"JS 片段递归 / 嵌套太深（栈上限 {DEFAULT_STACK_LIMIT} 字节）：{_first_line(exc)}")
    low = str(exc).lower()
    if "out of memory" in low:                # 先判字面证据，再判「耗时已到」这条旁证
        return JSMemoryLimit(
            f"JS 片段撞内存上限（{DEFAULT_MEMORY_LIMIT // (1024 * 1024)} MiB）："
            f"{_first_line(exc)}")
    if "interrupted" in low or elapsed >= timeout * 0.95:
        return JSTimeout(f"JS 片段超时（> {timeout}s，多半是死循环）：{_first_line(exc)}")
    return JSError(f"JS 片段报错：{_first_line(exc)}")


def _first_line(exc) -> str:
    """只取第一条 —— 后面几行是 JS 栈回溯，对书源作者有用但对用户是天书。"""
    return re.sub(r"\s+", " ", str(exc)).strip()[:300]


def run_js_sync(code: str, *args, timeout: float = DEFAULT_TIME_LIMIT,
                memory: int = DEFAULT_MEMORY_LIMIT, stack: int = DEFAULT_STACK_LIMIT):
    """在沙箱里跑一段 JS；``args`` 作为 ``__args`` 传入，``__args[0]`` 同时挂成全局 ``result``。

    返回值就是片段 ``return`` 的东西（`undefined` / `null` → `None`；对象 / 数组 → Python 对象）。

    `console.log/info/warn/error/debug` 都**真的能用**：跑通时进服务端日志（DEBUG），
    报错 / 超时时并入异常文案 —— 见 :func:`_read_logs` 里那段「为什么不是 Python 回调」。
    """
    if not _AVAILABLE:
        raise JSSandboxUnavailable(state()["reason"])
    try:
        fn = _build(code)
    except _qjs.JSException as e:                        # 编译期：语法错误
        raise JSError(f"JS 片段语法错误：{_first_line(e)}") from e
    fn.set_time_limit(float(timeout))
    fn.set_memory_limit(int(memory))
    fn.set_max_stack_size(int(stack))
    started = time.perf_counter()
    try:
        value = fn(*args)
    except _qjs.JSException as e:
        raise _with_logs(_classify(e, timeout=float(timeout),
                                   elapsed=time.perf_counter() - started),
                         _read_logs(fn)) from e
    logs = _read_logs(fn)
    if logs:                                             # 跑通了也**不丢**日志：进服务端日志
        logger.debug("书源 JS 片段 console 输出：%s", " / ".join(logs[:10]))
    return value


def _with_logs(err: RuntimeError, logs: list) -> RuntimeError:
    """片段 `console.log` 过的东西**带上** —— 书源作者写日志就是给这一刻看的。

    不带的话 `console` 就成了假接口（调了没反应，报错时也看不到）。
    只带前 10 行：报错文案要能一眼读完，全量在服务端日志里。
    """
    if not logs:
        return err
    return type(err)(f"{err}｜片段日志：{' / '.join(logs[:10])}")


async def run_js(code: str, *args, **kw):
    """异步包装：quickjs 的 `Function.__call__` 是阻塞的，放进默认线程池，别堵事件循环。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: run_js_sync(code, *args, **kw))
