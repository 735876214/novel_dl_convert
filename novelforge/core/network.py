"""网络加固层：类浏览器标头、Cookie 持久化、429 退避重试、域名替换、JS eval。

对应 denovel 的「伪造标头 / 类浏览器 Cookie 持久化 / 原生 JS eval」三大爬取特色。
- BrowserClient：封装 httpx.AsyncClient，自动带上浏览器标头，并把 Cookie 落盘到
  CONFIG_DIR/cookies/<source>.cookies.txt，跨请求保留登录态。
- 429 自动按 Retry-After 或 2^n 退避；传输/超时错误有限次重试。
- run_js / run_js_async：借助本机 Node 执行站点专用解密脚本（应对字体加密 / 内容混淆）。

⚠️ **规则里的 JS 走 :func:`run_source_js`（沙箱优先）**，不是直接走 Node：书源文件是第三方
给的，`@js:` 片段在 Node 里拿得到 `require('fs')` / 出网，而且**没有任何上限**。
第 94 期阶段 4b 起：有 `quickjs` 就在沙箱里跑（时间 / 内存 / 栈三道上限，实测真中断），
没有才回落 Node，并由 :func:`js_engine` **如实标注「那不是沙箱」**。
"""
import asyncio
import json
import logging
import os
import pathlib
import subprocess
import tempfile

from http.cookiejar import CookieJar

import httpx

from . import jssandbox

logger = logging.getLogger(__name__)

# urllib3 仅为关闭 InsecureRequestWarning 而引入；httpx 0.28 改用 httpcore，
# 不再依赖 urllib3。这里做防御式处理：存在时才关闭告警，避免干净环境因缺包崩溃。
try:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:  # pragma: no cover - 依赖可选
    pass

# 类浏览器默认标头（可被各书源覆盖）
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

NODE_BIN = os.environ.get("NODE_BIN") or "node"

#: 书源规则里的 `timeout` 允许范围（秒）。**唯一**一处判据：`clamp_timeout` 用它，
#: 校验与执行都只问它 —— 否则「校验放行 0.1 秒 / 执行真的按 0.1 秒超时」这种假配置
#: 会在真机上表现成「这个源全部超时」而看不出原因。
TIMEOUT_MIN, TIMEOUT_MAX = 5.0, 120.0

#: `timeout` 没写时的默认值（与 `BrowserClient` 的默认参数**同一个数**，改就一起改）。
TIMEOUT_DEFAULT = 30.0


def clamp_timeout(value, default: float = TIMEOUT_DEFAULT) -> float:
    """书源规则里的 ``timeout`` → 可直接交给 httpx 的秒数（**唯一**一处夹逼）。

    空 / 非数字 / ≤0 ⇒ 用 ``default``；超出范围 ⇒ 夹到 ``[TIMEOUT_MIN, TIMEOUT_MAX]``。
    夹逼而不是报错，是因为这一项是**可选护栏**：写歪了不该让整条源变成不可用。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float(default)
    if v <= 0:
        return float(default)
    return min(max(v, TIMEOUT_MIN), TIMEOUT_MAX)


class ResponseTooLarge(RuntimeError):
    """响应体超过 `network.max_response_bytes` —— **边收边数、超限即断**。

    刻意不复用 `httpx` 的异常类型：它要能穿过 `_request` 的「传输错误重试」分支
    （重试一个已经确定超限的响应没有意义，只是把同样的几百 MB 再拉一遍）。
    """


class _Unlimited:
    """`max_concurrency <= 0` 时的空闸（显式关掉并发限制，不是「忘了配」）。"""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


#: 全局出网闸的缓存（按**上限值**缓存：设置页改了上限就换一个闸）
_gate_cache: dict = {}


def global_gate():
    """**全局**在途请求闸：所有 `BrowserClient` 共用（模块级，不是每个客户端一份）。

    为什么必须是模块级的：书源是**并发**跑的（`asyncio.gather` 逐源），
    「每源自己限流」拦不住「20 个源各开 8 个请求」这类总量。上限读
    `config.network.max_concurrency`（默认值写在 `config.DEFAULTS`，这里**不另写一份**）。
    """
    try:
        from .. import config

        limit = int(((config.load_config().get("network") or {}).get("max_concurrency")) or 0)
    except Exception:                                    # 配置读不出来 ⇒ 不拦，别把抓取锁死
        limit = 0
    if _gate_cache.get("limit") != limit:
        _gate_cache.clear()
        _gate_cache.update({"limit": limit,
                            "sem": asyncio.Semaphore(limit) if limit > 0 else None})
    sem = _gate_cache["sem"]
    return sem if sem is not None else _UNLIMITED


_UNLIMITED = _Unlimited()


def _response_max_bytes() -> int:
    """单次响应体上限（字节）；≤0 表示不限（显式关掉）。"""
    try:
        from .. import config

        return int(((config.load_config().get("network") or {}).get("max_response_bytes")) or 0)
    except Exception:
        return 0


#: 重建响应体时必须摘掉的头 —— 它们描述的是**传输时的实体**，而重建时手里拿的
#: 已经是解压后的字节。留着 `Content-Encoding` 会让 httpx 再解一次（对 gzip 数据
#: 解两遍 ⇒ `DecodingError: incorrect header check`，即所有开压缩的站点全挂）；
#: `Content-Length` 则是长度已变，留着会给出错的数字。见 `BrowserClient._send_capped`。
_ENTITY_HEADERS = frozenset(("content-encoding", "content-length"))


def _drop_entity_headers(headers) -> "list[tuple[str, str]]":
    """去掉描述传输实体的头，其余（含 Content-Type / Set-Cookie）原样保留。"""
    return [(k, v) for k, v in headers.items() if k.lower() not in _ENTITY_HEADERS]


def verify_tls_enabled(cfg: dict | None = None) -> bool:
    """书源抓取要不要校验证书 —— `network.verify_tls` 的**唯一**读点与默认值。

    默认 **False** = 与第 94 期之前逐字一致（当时写死 `verify=False`）。不少书源站证书
    不规范（自签 / 链不全 / 域名不匹配），把默认改成 True 等于静默让一批书源失效 ——
    所以只**提供**开关，由部署者自己决定；MITM 风险写在设置页的 hint 里。

    `cfg` 给了就用它（`DownloadManager` 收的是注入的配置，测试要能自己造），
    没给 / 给了空 dict 就自己读一次**全局**配置（`tests/test_source_url_import.py` 钉着这条退路；
    第 97 期删掉 `/content` 之后，生产侧唯一的调用点是 `DownloadManager`）。
    """
    net = (cfg or {}).get("network") if isinstance(cfg, dict) else None
    if not isinstance(net, dict):
        try:
            from .. import config

            net = config.load_config().get("network") or {}
        except Exception:
            net = {}
    return bool(net.get("verify_tls", False))


class BrowserClient:
    """带持久 Cookie 与浏览器标头的异步 HTTP 客户端（scraping 友好）。"""

    def __init__(
        self,
        source_name: str = "default",
        cookie_dir: str | pathlib.Path | None = None,
        headers: dict | None = None,
        host_replace: dict | None = None,
        max_retries: int = 3,
        timeout: float = TIMEOUT_DEFAULT,
        verify_tls: bool = False,
        request_guard=None,
        max_bytes: int | None = None,
    ):
        self.cookie_dir = pathlib.Path(cookie_dir or ".")
        self.cookie_dir.mkdir(parents=True, exist_ok=True)
        self.cookie_path = self.cookie_dir / f"{source_name}.cookies.txt"
        # ⚠️ 是**标准库** `http.cookiejar.CookieJar`，不是 `httpx.CookieJar` ——
        # 后者根本不存在（httpx 0.28 的 cookie 相关导出只有 `Cookies` / `CookieConflict`），
        # 写成 `httpx.CookieJar()` 的后果是**每个书源一构造客户端就 AttributeError**：
        # 搜索恒返回 0 条、下载恒失败。这条路径没被测试挡住是因为单测都用桩 client
        # （`tests/test_sources_registry.py` 的 `_NoNetworkClient`），所以只有真机会现形
        # ——第 71 期把「逐源失败原因」显示出来时才顺带查到（见 roadmap 第 71 期）。
        # httpx 的 `cookies=` 接受标准库 CookieJar，与下面 _load/_save_cookies 直接配套。
        self.jar = CookieJar()
        # Cookie 持久化走下方 _load_cookies / _save_cookies（LWPCookieJar 落盘）
        self._load_cookies()
        merged = dict(DEFAULT_HEADERS)
        if headers:
            merged.update(headers)
        self.client = httpx.AsyncClient(
            headers=merged,
            cookies=self.jar,
            follow_redirects=True,
            timeout=timeout,
            # ⚠️ 默认 False = **保持不变**（第 94 期阶段 4a）：不少书源站证书不规范，
            # 改默认值等于静默改掉所有既有书源的抓取行为。要打开就设 `network.verify_tls`。
            # URL 导入那条路**强制 True**（见 `core/urlguard.py`）。
            verify=bool(verify_tls),
            # 逐跳复查出站目标（URL 导入用）；None = 不查（书源抓取照旧）
            event_hooks={"request": [request_guard]} if request_guard else {},
        )
        self.host_replace = host_replace or {}
        self.max_retries = max_retries
        # 上限的**默认值**仍由 `network.max_response_bytes` 给出（唯一读点不变）；
        # 传值只为「URL 导入」这种别的场景有自己的上限，避免多出一份实现。
        self.max_bytes = None if max_bytes is None else int(max_bytes)

    # ---- Cookie 持久化（LWPCookieJar 格式，便于人工查看/调试）----
    def _load_cookies(self):
        if not self.cookie_path.exists():
            return
        try:
            from http.cookiejar import LWPCookieJar

            jar = LWPCookieJar(str(self.cookie_path))
            jar.load(ignore_discard=True, ignore_expires=True)
            for c in jar:
                self.jar.set(c)
        except Exception:
            pass

    def _save_cookies(self):
        try:
            from http.cookiejar import LWPCookieJar

            jar = LWPCookieJar(str(self.cookie_path))
            for c in self.jar:
                jar.set(c)
            jar.save(ignore_discard=True, ignore_expires=True)
        except Exception:
            pass

    def _fix_url(self, url: str) -> str:
        for old, new in self.host_replace.items():
            if old in url:
                url = url.replace(old, new)
        return url

    async def _send_capped(self, method: str, url: str, **kw):
        """发一次请求并**边收边数**：超过 `network.max_response_bytes` 立即中断。

        ⚠️ 为什么不能拿 `client.request()` 之后再看 `len(resp.content)`：那时整个响应体
        已经在内存里了 —— 上限的意义正是**不把它拉进来**。所以这里走 `client.stream()`。
        重建 `httpx.Response` 时会**保留原 headers 与 extensions**（`.text` 的编码判据、
        `raise_for_status()` 的原文都还在），并且 httpx 在 `_send_single_request` 里已经
        抽过 Cookie ⇒ Set-Cookie 照旧生效（用例钉住）。

        ⚠️ **`Content-Encoding` / `Content-Length` 必须摘掉**（第 94 期实测踩出来的真 bug）：
        `resp.aiter_bytes()` 交给我们的**已经是解压后**的字节，而 `httpx.Response(...,
        content=…)` 构造时会立刻按 headers 里的 `Content-Encoding` **再解一遍** ⇒
        任何 gzip / deflate / br 响应都会当场抛
        `DecodingError: Error -3 while decompressing data: incorrect header check`。
        换言之：留着这两个头 = **所有开了压缩的真实站点全抓不到**（而本地/单测的 mock
        响应不带压缩，所以只有真网才暴露）。`Content-Length` 同理——重算后的长度已不同，
        留着它只会让下游读到错的数字。

        顺带：计数用的是**解压后**的字节数，正是我们要的语义（压缩炸弹在这里被拦住）。
        """
        cap = _response_max_bytes() if self.max_bytes is None else self.max_bytes
        async with self.client.stream(method, url, **kw) as resp:
            if cap <= 0:                                     # 显式关掉上限
                await resp.aread()
                return resp
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > cap:
                    raise ResponseTooLarge(
                        f"响应体超过上限 {cap} 字节（已收 {total}）—— 已中断：{url}"
                        "（可到「设置 → 网络」调大 network.max_response_bytes）")
                chunks.append(chunk)
            body = b"".join(chunks)
            return httpx.Response(
                resp.status_code,
                headers=_drop_entity_headers(resp.headers),
                content=body,
                # `request` 必须带上：`raise_for_status()` 靠它拼错误原文
                # （httpx 在 `_send_single_request` 里已经塞好了）
                request=resp.request,
                extensions=dict(resp.extensions or {}),
            )

    async def _request(self, method: str, url: str, **kw):
        """**唯一**出网口：重试 / 429 退避 / Cookie / host_replace / 全局闸只在这一处。

        `get` / `get_text` / `get_bytes` 与 POST 全走它 —— 各自复制一份重试逻辑的下场是
        「某一条路没有退避 / 不认 host_replace」，而现象只是**偶发失败**（最难查的那种）。
        """
        url = self._fix_url(url)
        for attempt in range(self.max_retries):
            try:
                async with global_gate():                    # 全局在途上限（模块级，全客户端共享）
                    resp = await self._send_capped(method, url, **kw)
                if resp.status_code == 429:
                    await self._backoff(resp, attempt)
                    continue
                return resp
            except (httpx.TransportError, httpx.TimeoutException):
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("下载重试次数耗尽")

    async def get(self, url: str, **kw):
        return await self._request("GET", url, **kw)

    async def get_text(self, url: str, *, method: str = "GET", body=None,
                       headers: "dict | None" = None, charset: "str | None" = None) -> str:
        """取文本。**不给选项时与旧行为一字不差**（GET + httpx 自己的解码）。

        第 94 期新增三个**由书源规则显式要求**的选项（阅读的 `,{'method':…}` / `|char=…`）：

        - ``method`` / ``body``：站点只认 POST 的搜索接口（实测 6 条真实源）；
        - ``headers``：该请求自带的标头（阅读的选项字典里就叫 `headers`）；
        - ``charset``：站点是 GBK 这类**页面没写编码**的编码时按它解 —— 走
          :func:`novelforge.core.pipeline.decode_bytes`（与「上传文件」**同一份**判据），
          不在这里另写一份「先试 gbk 再试 utf-8」。

        ⚠️ 刻意**不改**默认路径：`charset` 没给时仍旧 `resp.text`（httpx 自己按
        Content-Type / 内容猜）。把默认改成我们的探测器会**静默改变**所有既有书源的抓取
        结果（方向可能更好，但那是另一件事，得单独测过真网再改）。
        """
        opts = {}
        if headers:
            opts["headers"] = headers
        if body is not None:
            opts["content"] = body
        resp = await self._request(method, url, **opts)
        resp.raise_for_status()
        if not charset:
            return resp.text
        from . import pipeline                         # 编码判据**只有一处**（见 docstring）
        text, _info = pipeline.decode_bytes(resp.content, encoding=charset)
        return text

    async def get_bytes(self, url: str, **kw) -> bytes:
        """取**字节流**（图片 / 音频这类二进制资源，第 86 期）。

        ⚠️ 不能拿 `get_text()` 凑：`resp.text` 会按文本编码解一遍二进制，得回来的字节与站上
        那一份**不一样** —— 表现是图片打不开、音频放不出，而且**看起来像站点的问题**。
        走的就是 :meth:`get` 的同一条路（重试 / 退避 / Cookie / host_replace 口径一致），
        只差最后一步取 `.content`。
        """
        resp = await self.get(url, **kw)
        return resp.content

    async def _backoff(self, resp, attempt):
        ra = resp.headers.get("Retry-After")
        try:
            delay = float(ra) if ra else 2 ** (attempt + 1)
        except (TypeError, ValueError):
            delay = 2 ** (attempt + 1)
        await asyncio.sleep(min(delay, 60))

    async def aclose(self):
        self._save_cookies()
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()


#: `node_state()` 的缓存（键是 `NODE_BIN` 当前值：换了 bin 就重新探一次）
_node_cache: dict = {}


def node_state(refresh: bool = False) -> dict:
    """Node 可用性：``{available, bin, version, reason}``（结果按 `NODE_BIN` 缓存）。

    ⚠️ **为什么必须有这个函数**：Docker 镜像里是自带 Node 的
    （多阶段构建，`NODE_BIN=/usr/local/bin/node`），但**NAS / 手工部署未必有** ——
    而 `NODE_BIN` 默认就是 `"node"`。少了这一层，缺 Node 时 `subprocess` 抛的是
    `[Errno 2] No such file or directory: 'node'`：用户看到一句英文系统错误，
    完全不知道「是这台机器要装 Node / 要么改用不需要解密的书源」。
    现在改成：**先探一次，然后把「不能做什么 + 怎么补」说清楚**（`reason` 就是那句人话）。
    """
    if not refresh and _node_cache.get("bin") == NODE_BIN:
        return dict(_node_cache)
    info = {"available": False, "bin": NODE_BIN, "version": "", "reason": ""}
    try:
        proc = subprocess.run([NODE_BIN, "--version"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=10)
        ver = (proc.stdout or "").strip()
        if proc.returncode == 0 and ver:
            info.update(available=True, version=ver)
        else:
            info["reason"] = ((proc.stderr or "").strip()[:200]
                              or f"{NODE_BIN} --version 返回了非零退出码")
    except FileNotFoundError:
        info["reason"] = (
            f"找不到 Node（NODE_BIN={NODE_BIN}）：这台机器没有装 Node。"
            "需要字体解密 / 内容混淆的书源跑不了（其余书源不受影响）。"
            "补法：装上 Node 并把环境变量 NODE_BIN 指到它的可执行文件；"
            "或改用不需要解密的书源。")
    except Exception as e:                                   # noqa: BLE001 —— 原文照回
        info["reason"] = f"{type(e).__name__}: {str(e)[:160]}"
    _node_cache.clear()
    _node_cache.update(info)
    return dict(info)


def ensure_node() -> dict:
    """确认 Node 可用；不可用就**带着能照做的说明**抛错（而不是抛系统错误）。"""
    st = node_state()
    if not st["available"]:
        raise RuntimeError(st["reason"] or "Node 不可用：无法运行站点专用 JS 脚本")
    return st


def run_js_sync(js_code: str, *args):
    """在 Node 中执行 js_code；args 作为全局数组 __args 传入；stdout 优先按 JSON 解析。"""
    ensure_node()
    script = "const __args = " + json.dumps(list(args), ensure_ascii=False) + ";\n" + js_code + "\n"
    fd, path = tempfile.mkstemp(suffix=".js", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        try:
            proc = subprocess.run(
                [NODE_BIN, path], capture_output=True, text=True,
                # ⚠️ **必须显式指定 UTF-8**（第 86 期真机跑出来的坑）：不指定就用系统区域编码
                # （Windows 上是 GBK），Node 输出的中文会撞 `UnicodeDecodeError`；而异常发生在
                # subprocess 的**读线程**里 ⇒ `proc.stdout` 变成 `None`，用户看到的是
                # `AttributeError: 'NoneType' object has no attribute 'strip'` ——
                # 离真正的原因（编码）十万八千里。离线桩永远抓不到这一类问题。
                encoding="utf-8", errors="replace", timeout=30
            )
        except FileNotFoundError:
            # 探测之后到执行之间 Node 被挪走 / 卸掉（少见，但不能让原始系统错误漏出去）
            raise RuntimeError(node_state(refresh=True)["reason"]
                               or "Node 在运行前消失了") from None
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "").strip() or "node 执行失败")
        out = (proc.stdout or "").strip()
        try:
            return json.loads(out)
        except (json.JSONDecodeError, ValueError):
            return out
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def run_js(js_code: str, *args):
    """异步包装：在默认线程池里跑 Node 子进程，避免阻塞事件循环。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: run_js_sync(js_code, *args))


def wrap_decrypt(js: str) -> str:
    """把「Legado 风格、用 ``return`` 交出明文」的解密片段包成**可直接跑的 Node 脚本**。

    ⚠️ 这一层包装不是装饰：`run_js_sync` 是把片段**拼在脚本顶层**的，
    而 `return` 在顶层是**语法错误** —— 不包就会得到一句 Node 的
    `SyntaxError: Illegal return statement`，看起来像「这条规则写错了」，
    实际上是**我们的调用方式**错了（`SourceAdapter.decryption_js` 的契约写明是 return）。

    输出统一成一行 JSON ``{"ok": 是否字符串, "v": 值}``：片段返回非字符串（漏了 return /
    返回了对象）时能被调用方**判出来**，而不是把 `undefined` 当成明文写进书里。
    """
    # ⚠️ 同时提供**两种读法**，因为两边的既定约定不同，接不上就是「导入的源静默产出空正文」：
    #   · 本项目手写的片段用 `__args[0]`（与 `run_js_sync` 的形参一致）；
    #   · `legado.js_port` 移植过来的片段读**全局 `result`**（Legado 的写法，
    #     见 `sources/legado.py` 的 `js_port` 文档）。
    # 少给任何一个，都会表现成「脚本跑通了但什么都没取到」，最难查。
    return ("const result = __args[0];\n"
            "const __out = (function () {\n" + str(js or "") + "\n})();\n"
            "console.log(JSON.stringify({ok: typeof __out === 'string', v: String(__out)}));")


#: 「片段没交出字符串」的**唯一**一处文案（Node 通道与沙箱共用，口径不许漂）
_REQUIRE_STR = "解密脚本没有返回字符串（多半是片段里漏了 return，或 return 了非字符串）"


def _demand_str(v) -> str:
    if not isinstance(v, str):
        raise RuntimeError(_REQUIRE_STR)
    return v


async def run_decrypt(js: str, text: str) -> str:
    """跑一段站点解密片段：``__args[0]`` 传密文，片段 ``return`` 明文。

    ⚠️ **这是 Node 通道**（第 86 期）：能跑但没有沙箱、没有超时 / 内存 / 栈上限，
    只保留给既有契约与 `node_state()` 明确的部署。书源规则里的 JS 请走
    :func:`run_source_js`（沙箱优先）。

    结果**必须是字符串**：拿到 `undefined` / 对象就如实抛错。静默把它当明文返回，
    写进书里的就是一段 `undefined`，而用户只会看到「这本书内容是乱的」。
    """
    res = await run_js(wrap_decrypt(js), text)
    if not isinstance(res, dict) or not res.get("ok"):
        raise RuntimeError(_REQUIRE_STR)
    return res["v"]


# ---------------- 书源规则里的 JS：沙箱优先（第 94 期阶段 4b）----------------

#: 「回落到 Node」只提醒一次：每次请求都刷一遍等价于没有日志。
_sandbox_warned = {"done": False}


def js_engine() -> dict:
    """规则里的 JS 会由**谁**执行 —— 沙箱优先，缺 quickjs 才回落 Node。

    回落是**如实标注**的，不是偷偷的：`/api/sources/capabilities` 原样下发这个 dict，
    界面 / 文档据此说清「这台机器上规则里的 JS 跑在没有超时的 Node 通道里」。
    """
    sb = jssandbox.state()
    if sb["available"]:
        return {"sandbox": True, "engine": "quickjs", "version": sb["version"],
                "limits": {"time": sb["time_limit"], "memory": sb["memory_limit"],
                           "stack": sb["stack_limit"]},
                "reason": ""}
    node = node_state()
    why = f"缺 JS 沙箱：{sb['reason']}"
    if node["available"]:
        why += "；再回落 Node 通道（**非沙箱**、无超时 / 内存 / 栈上限）"
    else:
        why += "；本机也没有 Node ⇒ 书源规则里的 JS 片段跑不了（其余书源不受影响）"
    return {"sandbox": False, "engine": "node" if node["available"] else "",
            "version": node["version"], "limits": {}, "reason": why}


async def run_source_js(js: str, text: str) -> str:
    """**书源规则里的 JS 的唯一执行入口**（`decrypt_js` 与 `mode:"js"` 正文共用）。

    契约与 :func:`run_decrypt` 逐字一致：``__args[0]`` 与全局 ``result`` 都是输入，
    片段用 ``return`` 交出**字符串**，拿不到就如实报错。

    引擎选择只有这一处：有沙箱就在沙箱里跑（带时间 / 内存 / 栈上限），
    没有才回落 Node 通道，并在 :func:`js_engine` 里如实说明**那不是沙箱**。
    """
    eng = js_engine()
    if eng["sandbox"]:
        return _demand_str(await jssandbox.run_js(js, text))
    if not eng["engine"]:
        raise RuntimeError(eng["reason"])
    if not _sandbox_warned["done"]:
        _sandbox_warned["done"] = True
        logger.warning("书源规则里的 JS 正走 Node 通道（无沙箱、无超时）：%s", eng["reason"])
    return await run_decrypt(js, text)
