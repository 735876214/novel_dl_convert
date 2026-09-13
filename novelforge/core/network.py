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

import httpx
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        self.jar = httpx.CookieJar()
        # 用 LWPCookieJar 落盘，复用既有 cookie 文件
        self._lwp = httpx.CookieJar()  # 占位，真正持久化见下方 load/save
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


def run_js_sync(js_code: str, *args):
    """在 Node 中执行 js_code；args 作为全局数组 __args 传入；stdout 优先按 JSON 解析。"""
    script = "const __args = " + json.dumps(list(args), ensure_ascii=False) + ";\n" + js_code + "\n"
    fd, path = tempfile.mkstemp(suffix=".js", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        proc = subprocess.run(
            [NODE_BIN, path], capture_output=True, text=True, timeout=30
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "node 执行失败")
        out = proc.stdout.strip()
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
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: run_js_sync(js_code, *args))
