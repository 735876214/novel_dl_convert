"""设计 token 提取：来自页面计算样式，或来自本地仓库的 tailwind/CSS 变量。

说明：本地仓库扫描是启发式正则解析（MVP 阶段不引入 tree-sitter），
只用于"建议时优先复用项目已有 token"，不保证 100% 覆盖。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .color import is_neutral, parse_color, saturation, to_hex

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
_VAR_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+);")
_PX_RE = re.compile(r"^(-?[\d.]+)px$")
_SHADOW_BLUR_RE = re.compile(r"(-?[\d.]+)px\s+(-?[\d.]+)px\s+([\d.]+)px")


def px(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    m = _PX_RE.match(value.strip())
    return float(m.group(1)) if m else None


def _counter_top(counter: Counter, limit: int = 12) -> List[Dict[str, Any]]:
    return [{"value": v, "count": c} for v, c in counter.most_common(limit)]


@dataclass
class DesignTokens:
    colors: List[Dict[str, Any]] = field(default_factory=list)
    fonts: List[Dict[str, Any]] = field(default_factory=list)
    font_sizes: List[Dict[str, Any]] = field(default_factory=list)
    spacings: List[Dict[str, Any]] = field(default_factory=list)
    radii: List[Dict[str, Any]] = field(default_factory=list)
    shadows: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "dom"

    # ---- 派生值 -------------------------------------------------------
    @property
    def accent(self) -> str:
        """最"抢眼"的常用色，用于焦点环等。"""
        for item in self.colors:
            rgba = parse_color(item["value"])
            if not rgba:
                continue
            if not is_neutral(rgba[:3]) and item["count"] >= 2:
                return item["value"]
        return "#2563eb"

    @property
    def dominant_radius(self) -> Optional[float]:
        if not self.radii:
            return None
        return float(self.radii[0]["value"])

    @property
    def text_color(self) -> str:
        return self.colors[0]["value"] if self.colors else "#111827"

    def suggest_spacing(self, value: float, grid: int = 4) -> str:
        return f"{max(0, int(round(value / grid) * grid))}px"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "colors": self.colors,
            "fonts": self.fonts,
            "font_sizes": self.font_sizes,
            "spacings": self.spacings,
            "radii": self.radii,
            "shadows": self.shadows,
            "accent": self.accent,
            "dominant_radius": self.dominant_radius,
        }


def from_snapshot(snapshot: Dict[str, Any]) -> DesignTokens:
    colors: Counter = Counter()
    fonts: Counter = Counter()
    sizes: Counter = Counter()
    spacings: Counter = Counter()
    radii: Counter = Counter()
    shadows: Counter = Counter()

    for el in snapshot.get("elements", []):
        styles = el.get("styles", {})
        text_color = styles.get("color")
        bg_color = styles.get("backgroundColor")
        for raw, weight in ((text_color, 2), (bg_color, 1)):
            rgba = parse_color(raw)
            if not rgba or rgba[3] == 0:
                continue
            colors[to_hex(rgba[:3])] += weight

        family = (styles.get("fontFamily") or "").split(",")[0].strip().strip("'\"")
        if family:
            fonts[family] += 1

        size = px(styles.get("fontSize"))
        if size is not None and el.get("text"):
            sizes[size] += 1

        for key in ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft"):
            value = px(styles.get(key))
            if value is not None and 0 < value <= 200:
                spacings[value] += 1

        radius = px(styles.get("borderTopLeftRadius"))
        if radius and 0 < radius < 200:
            radii[radius] += 1

        shadow = styles.get("boxShadow")
        if shadow and shadow != "none":
            shadows[shadow[:80]] += 1

    return DesignTokens(
        colors=_counter_top(colors),
        fonts=_counter_top(fonts, 6),
        font_sizes=_counter_top(sizes, 10),
        spacings=_counter_top(spacings, 12),
        radii=_counter_top(radii, 8),
        shadows=_counter_top(shadows, 6),
        source="dom",
    )


def _scan_css(path: Path, colors: Counter, radii: Counter, spacings: Counter) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    if len(text) > 800_000:
        return
    for _name, value in _VAR_RE.findall(text):
        value = value.strip()
        rgba = parse_color(value)
        if rgba:
            colors[to_hex(rgba[:3])] += 1
            continue
        p = px(value)
        if p is not None and 0 < p <= 200:
            (radii if p <= 32 else spacings)[p] += 1
    for hexv in _HEX_RE.findall(text):
        rgba = parse_color(hexv)
        if rgba:
            colors[to_hex(rgba[:3])] += 1


def _scan_tailwind(path: Path, colors: Counter, radii: Counter) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for hexv in _HEX_RE.findall(text):
        rgba = parse_color(hexv)
        if rgba:
            colors[to_hex(rgba[:3])] += 2
    for value in re.findall(r"borderRadius\s*:\s*\{([^}]*)\}", text):
        for p in re.findall(r"([\d.]+)px", value):
            radii[float(p)] += 2


def from_repo(root: Optional[str]) -> Optional[DesignTokens]:
    """扫描本地仓库，提取已有设计 token（启发式）。"""
    if not root:
        return None
    base = Path(root)
    if not base.exists():
        return None

    colors: Counter = Counter()
    radii: Counter = Counter()
    spacings: Counter = Counter()

    for name in ("tailwind.config.js", "tailwind.config.ts", "tailwind.config.cjs", "tailwind.config.mjs"):
        candidate = base / name
        if candidate.exists():
            _scan_tailwind(candidate, colors, radii)

    css_files: List[Path] = []
    for pattern in ("**/*.css", "**/*.scss"):
        css_files.extend(list(base.glob(pattern))[:20])
    for css_file in css_files[:40]:
        if "node_modules" in css_file.parts or "dist" in css_file.parts:
            continue
        _scan_css(css_file, colors, radii, spacings)

    if not (colors or radii or spacings):
        return None
    return DesignTokens(
        colors=_counter_top(colors),
        fonts=[],
        font_sizes=[],
        spacings=_counter_top(spacings, 12),
        radii=_counter_top(radii, 8),
        shadows=[],
        source=f"repo:{base}",
    )


def merge(dom_tokens: DesignTokens, repo_tokens: Optional[DesignTokens]) -> DesignTokens:
    """DOM token 为主，仓库 token 用于补充/加权。"""
    if repo_tokens is None:
        return dom_tokens
    merged_colors = Counter({c["value"]: c["count"] for c in dom_tokens.colors})
    for item in repo_tokens.colors:
        merged_colors[item["value"]] += item["count"]
    merged_radii = Counter({str(r["value"]): r["count"] for r in dom_tokens.radii})
    for item in repo_tokens.radii:
        merged_radii[str(item["value"])] += item["count"]
    dom_tokens.colors = _counter_top(merged_colors)
    dom_tokens.radii = [{"value": float(v), "count": c} for v, c in merged_radii.most_common(8)]
    dom_tokens.source = f"dom+{repo_tokens.source}"
    return dom_tokens


def shadow_blur(shadow: str) -> Optional[float]:
    m = _SHADOW_BLUR_RE.search(shadow or "")
    return float(m.group(3)) if m else None


def color_saturation(hex_value: str) -> int:
    rgba = parse_color(hex_value)
    return saturation(rgba[:3]) if rgba else 0
