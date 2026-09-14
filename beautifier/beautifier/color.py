"""颜色解析与 WCAG 对比度计算（纯 Python，无第三方依赖）。"""

from __future__ import annotations

import re
from typing import Optional, Tuple

RGB = Tuple[int, int, int]
RGBA = Tuple[int, int, int, float]

_NAMED = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "transparent": None,
    "orange": (255, 165, 0), "yellow": (255, 255, 0), "purple": (128, 0, 128),
    "pink": (255, 192, 203), "teal": (0, 128, 128), "navy": (0, 0, 128),
}

_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+))?\s*\)", re.I)


def parse_color(value: Optional[str]) -> Optional[RGBA]:
    """把 CSS 颜色字符串解析为 (r, g, b, a)；无法解析返回 None。"""
    if not value:
        return None
    v = value.strip().lower()
    if v == "transparent":
        return (0, 0, 0, 0.0)
    if v in _NAMED:
        rgb = _NAMED[v]
        if rgb is None:
            return (0, 0, 0, 0.0)
        return (rgb[0], rgb[1], rgb[2], 1.0)
    if v.startswith("#"):
        hexpart = v[1:]
        if len(hexpart) in (3, 4):
            hexpart = "".join(c * 2 for c in hexpart)
        if len(hexpart) == 6:
            return (int(hexpart[0:2], 16), int(hexpart[2:4], 16), int(hexpart[4:6], 16), 1.0)
        if len(hexpart) == 8:
            return (
                int(hexpart[0:2], 16), int(hexpart[2:4], 16), int(hexpart[4:6], 16),
                int(hexpart[6:8], 16) / 255.0,
            )
        return None
    m = _RGB_RE.match(v)
    if m:
        r, g, b = (int(float(m.group(i))) for i in (1, 2, 3))
        a = float(m.group(4)) if m.group(4) else 1.0
        return (r, g, b, max(0.0, min(1.0, a)))
    # oklch / color() / lab 等新式颜色语法暂不支持
    return None


def to_hex(rgb: RGB) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def blend(fg: RGBA, bg: RGB) -> RGB:
    """把带透明度的前景色叠加到背景色上，得到有效前景色。"""
    a = fg[3]
    return (
        fg[0] * a + bg[0] * (1 - a),
        fg[1] * a + bg[1] * (1 - a),
        fg[2] * a + bg[2] * (1 - a),
    )


def _channel_lin(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: RGB) -> float:
    r, g, b = (_channel_lin(float(c)) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: RGB, bg: RGB) -> float:
    l1, l2 = luminance(fg), luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def contrast_of(fg_css: str, bg_css: str) -> Optional[float]:
    """直接计算两个 CSS 颜色字符串之间的对比度。"""
    fg = parse_color(fg_css)
    bg = parse_color(bg_css)
    if not fg or not bg:
        return None
    bg_rgb = bg[:3]
    return contrast_ratio(blend(fg, bg_rgb), bg_rgb)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def saturation(rgb: RGB) -> int:
    return int(max(rgb) - min(rgb))


def is_neutral(rgb: RGB, threshold: int = 24) -> bool:
    return saturation(rgb) < threshold


def ensure_contrast(fg_css: str, bg_css: str, target: float = 4.5) -> Optional[RGB]:
    """把前景色朝黑/白方向调整到满足 target 对比度，返回改动最小的候选色。"""
    fg = parse_color(fg_css)
    bg = parse_color(bg_css)
    if not fg or not bg:
        return None
    bg_rgb: RGB = bg[:3]
    base = blend(fg, bg_rgb)
    if contrast_ratio(base, bg_rgb) >= target:
        return None

    best: Optional[Tuple[float, RGB]] = None
    for other in ((0, 0, 0), (255, 255, 255)):
        lo, hi = 0.0, 1.0
        if contrast_ratio(mix(base, other, 1.0), bg_rgb) < target:
            continue
        for _ in range(24):
            mid = (lo + hi) / 2
            if contrast_ratio(mix(base, other, mid), bg_rgb) >= target:
                hi = mid
            else:
                lo = mid
        cand = mix(base, other, hi)
        if contrast_ratio(cand, bg_rgb) >= target:
            delta = sum(abs(x - y) for x, y in zip(cand, base))
            if best is None or delta < best[0]:
                best = (delta, cand)
    if best is None:
        return None
    return tuple(int(round(c)) for c in best[1])  # type: ignore[return-value]
