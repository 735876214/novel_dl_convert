"""核心数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

SEVERITIES = ("high", "medium", "low")
SEVERITY_WEIGHT = {"high": 8, "medium": 3, "low": 1}

# 问题类别，同时也是报告里的分组依据
ISSUE_TYPES = {
    "contrast": "色彩对比度",
    "font-size": "字号",
    "line-height": "行高",
    "tap-target": "点击区域",
    "radius": "圆角一致性",
    "spacing": "间距栅格",
    "shadow": "阴影",
    "focus": "键盘焦点",
    "line-length": "阅读行长",
    "overflow": "内容溢出",
    "image-alt": "图片替代文本",
    "heading-order": "标题层级",
    "color-count": "色彩数量",
    "visual": "视觉观感（模型）",
}


@dataclass
class Issue:
    """一条诊断问题。"""

    type: str
    severity: str
    element: str
    detail: str
    suggestion: str
    source: str = "rule"  # rule | llm
    viewport: Optional[int] = None
    # 可自动修复时给出：{"props": {...}, "pseudo": Optional[str], "selector": Optional[str]}
    fix: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            self.severity = "low"
        if self.element is None:
            self.element = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def key(self) -> str:
        """去重键。"""
        return f"{self.type}|{self.element}|{self.viewport or 0}"

    def type_label(self) -> str:
        return ISSUE_TYPES.get(self.type, self.type)


@dataclass
class ViewportResult:
    """某个视口下的产物。"""

    width: int
    height: int
    before: str = ""
    after: str = ""
    diff: str = ""
    change_ratio: float = 0.0
    diff_bbox: Optional[List[int]] = None


@dataclass
class Diagnosis:
    """一次完整诊断的结果集合。"""

    url: str
    style: str
    issues: List[Issue]
    tokens: Dict[str, Any]
    css: str
    changes: List[Dict[str, Any]]
    viewports: List[ViewportResult]
    axe_before: Optional[Dict[str, Any]] = None
    axe_after: Optional[Dict[str, Any]] = None

    def counts(self) -> Dict[str, int]:
        out = {"high": 0, "medium": 0, "low": 0}
        for issue in self.issues:
            out[issue.severity] = out.get(issue.severity, 0) + 1
        return out

    def score(self) -> int:
        """健康分：满分 100，按严重度扣分。"""
        counts = self.counts()
        penalty = sum(SEVERITY_WEIGHT[k] * counts.get(k, 0) for k in SEVERITIES)
        return max(0, 100 - penalty)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "style": self.style,
            "score": self.score(),
            "counts": self.counts(),
            "issues": [i.to_dict() for i in self.issues],
            "tokens": self.tokens,
            "changes": self.changes,
            "viewports": [asdict(v) for v in self.viewports],
            "axe_before": self.axe_before,
            "axe_after": self.axe_after,
        }
