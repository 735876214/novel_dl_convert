"""Playwright 截图：多视口 before/after 采集。

关键点：前后两次截图必须"同环境、同状态"，因此统一注入稳定化 CSS
（关掉动画/过渡/光标），否则像素对比会被动效噪声污染。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

STABILIZE_CSS = """
*, *::before, *::after {
  animation-duration: 0s !important;
  animation-delay: 0s !important;
  transition-duration: 0s !important;
  transition-delay: 0s !important;
  scroll-behavior: auto !important;
  caret-color: transparent !important;
}
"""


class PlaywrightNotInstalled(RuntimeError):
    pass


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 环境相关
        raise PlaywrightNotInstalled(
            "未检测到 playwright。请先安装：\n"
            "  pip install -r beautifier/requirements.txt\n"
            "  python -m playwright install chromium"
        ) from exc
    return sync_playwright


def start():
    """返回 (sync_playwright, browser)。由调用方负责关闭。"""
    sync_playwright = _require_playwright()
    manager = sync_playwright().start()
    return manager, manager.chromium.launch(args=["--force-color-profile=srgb", "--font-render-hinting=none"])


def new_page(browser, width: int, height: int, timeout: int = 30000):
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=1,
        ignore_https_errors=True,
    )
    context.set_default_timeout(timeout)
    page = context.new_page()
    return context, page


def prepare_page(page, url: str, wait_ms: int = 600, timeout: int = 30000) -> None:
    """打开页面并进入稳定状态。"""
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout, 8000))
    except Exception:
        # 长轮询 / 埋点会导致 networkidle 永不触发，忽略即可
        pass
    page.add_style_tag(content=STABILIZE_CSS)
    page.wait_for_timeout(wait_ms)


def shoot(page, path: Path, full_page: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=full_page)
    return path


def inject_css(page, css: str) -> None:
    if css and css.strip():
        page.add_style_tag(content=css)


def normalize_url(url: str) -> str:
    """把用户输入补成可被浏览器打开的地址。"""
    from urllib.parse import urlparse

    candidate = url.strip()
    parsed = urlparse(candidate)
    if parsed.scheme in ("http", "https", "file"):
        return candidate
    local = Path(candidate)
    if local.exists():
        return local.resolve().as_uri()
    if parsed.scheme:
        return candidate
    return "https://" + candidate
