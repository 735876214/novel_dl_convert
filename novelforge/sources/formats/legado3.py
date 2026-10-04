"""Legado / 阅读 **3.x** 书源 JSON（`legado-3`）：现代格式（顶层 `searchUrl` +
`ruleSearch` / `ruleToc` / `ruleContent`，`bookSourceType` 是整数）。

本适配器**只包装** `legado` 那唯一一份实现（`detect_format` / `parse_sources` / `analyze`）：
sniff → 判是不是 Legado JSON；map → `analyze`（它内部已含「转换产物过 `audit_native_rule`」这道闸）。
"""
from .. import legado
from .base import FORMAT_LEGADO3, FormatAdapter, register_format


@register_format
class Legado3Adapter(FormatAdapter):
    format_id = FORMAT_LEGADO3
    display_name = "Legado / 阅读 App 书源"

    def sniff(self, payload) -> float:
        # 「是不是 Legado JSON」的判据只有 `legado.detect_format` 一处（它同时服务老契约：
        # `test_legado_import::test_嗅探三种输入`）。2.x 由隔壁适配器用更高分抢走。
        if legado.detect_format(payload) != "legado":
            return 0.0
        entries = _entries(payload)
        if entries and all(legado.legacy_keys(e) for e in entries):
            return 0.0                      # 整份都是 2.x ⇒ 让 legado-2 认领
        return 0.8

    def map(self, entry) -> dict:
        """→ 能力报告。`analyze` 已经在入口归一 2.x 键名、并在出口过诚实闸，这里不再重复。"""
        return legado.analyze(entry)


def _entries(payload) -> list:
    """嗅探用的「能不能解出条目」探测：解不出就当没有（嗅探**不许炸**）。"""
    try:
        return legado.parse_sources(payload)
    except Exception:                                        # noqa: BLE001
        return []
