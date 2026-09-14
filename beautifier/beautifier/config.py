"""阈值、风格档位与默认视口配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class StyleProfile:
    """三档改动强度：保守 / 现代 / 大胆。"""

    key: str
    label: str
    severities: Tuple[str, ...]
    normalize_radius: bool = False
    normalize_spacing: bool = False
    normalize_typography: bool = False
    refine_shadow: bool = False
    line_height: float = 1.6
    max_text_width: str = "72ch"

    def allows(self, severity: str) -> bool:
        return severity in self.severities


STYLES: Dict[str, StyleProfile] = {
    "conservative": StyleProfile(
        key="conservative",
        label="保守（只修高优先级与可访问性问题）",
        severities=("high",),
    ),
    "modern": StyleProfile(
        key="modern",
        label="现代（修高/中优先级 + 圆角与间距归一化）",
        severities=("high", "medium"),
        normalize_radius=True,
        normalize_spacing=True,
    ),
    "bold": StyleProfile(
        key="bold",
        label="大胆（全部问题 + 排版与阴影重构）",
        severities=("high", "medium", "low"),
        normalize_radius=True,
        normalize_spacing=True,
        normalize_typography=True,
        refine_shadow=True,
        line_height=1.65,
        max_text_width="68ch",
    ),
}

DEFAULT_STYLE = "modern"

# 视口宽度 -> 默认高度
VIEWPORT_HEIGHTS: Dict[int, int] = {375: 812, 414: 896, 768: 1024, 1024: 768, 1280: 800, 1440: 900, 1920: 1080}
DEFAULT_VIEWPORTS: Tuple[int, ...] = (375, 768, 1440)

THRESHOLDS = {
    "contrast_normal": 4.5,       # WCAG AA 正文
    "contrast_large": 3.0,        # WCAG AA 大字号
    "large_text_px": 24.0,        # >= 24px 视为大字号
    "large_text_bold_px": 18.66,  # >= 18.66px 且 bold 视为大字号
    "min_font_size": 12.0,
    "target_font_size": 14.0,
    "min_line_height": 1.35,
    "min_tap_target": 32,
    "target_tap_target": 44,
    "spacing_grid": 4,
    "max_shadow_blur": 40.0,
    "max_text_colors": 8,
    "long_text_chars": 200,
    "wide_container_px": 900,
    "diff_pixel_threshold": 12,
}

# 生成 CSS 时强制 !important 的属性（保证注入预览一定生效）
IMPORTANT_PROPS = {"color", "outline", "min-height", "min-width", "max-width", "overflow-x"}

OUT_DIR_DEFAULT = ".beautify"
