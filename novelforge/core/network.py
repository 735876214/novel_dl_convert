"""网络加固层：类浏览器标头、Cookie 持久化、429 退避重试、域名替换、JS eval。

对应 denovel 的「伪造标头 / 类浏览器 Cookie 持久化 / 原生 JS eval」三大爬取特色。
- BrowserClient：封装 httpx.AsyncClient，自动带上浏览器标头，并把 Cookie 落盘到
  CONFIG_DIR/cookies/<source>.cookies.txt，跨请求保留登录态。
- 429 自动按 Retry-After 或 2^n 退避；传输/超时错误有限次重试。
- run_js / run_js_async：借助本机 Node 执行站点专用解密脚本（应对字体加密 / 内容混淆）。
"""
import asyncio
import json
import os
import pathlib
import subprocess
import tempfile

from http.cookiejar import CookieJar

import httpx

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


class BrowserClient:
    """带持久 Cookie 与浏览器标头的异步 HTTP 客户端（scraping 友好）。"""

    def __init__(
        self,
        source_name: str = "default",
        cookie_dir: str | pathlib.Path | None = None,
        headers: dict | None = None,
        host_replace: dict | None = None,
        max_retries: int = 3,
        timeout: float = 30.0,
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
            verify=False,
        )
        self.host_replace = host_replace or {}
        self.max_retries = max_retries

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

    async def get(self, url: str, **kw):
        url = self._fix_url(url)
        for attempt in range(self.max_retries):
            try:
                resp = await self.client.get(url, **kw)
                if resp.status_code == 429:
                    await self._backoff(resp, attempt)
                    continue
                return resp
            except (httpx.TransportError, httpx.TimeoutException):
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("下载重试次数耗尽")

    async def get_text(self, url: str, **kw) -> str:
        resp = await self.get(url, **kw)
        resp.raise_for_status()
        return resp.text

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


async def run_decrypt(js: str, text: str) -> str:
    """跑一段站点解密片段：``__args[0]`` 传密文，片段 ``return`` 明文。

    ⚠️ 结果**必须是字符串**：拿到 `undefined` / 对象就如实抛错。静默把它当明文返回，
    写进书里的就是一段 `undefined`，而用户只会看到「这本书内容是乱的」。
    """
    res = await run_js(wrap_decrypt(js), text)
    if not isinstance(res, dict) or not res.get("ok"):
        raise RuntimeError("解密脚本没有返回字符串（多半是片段里漏了 return，或 return 了非字符串）")
    return res["v"]
