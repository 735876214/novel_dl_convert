"""Legado / 阅读 **2.x** 旧方言（`legado-2`）：`ruleSearchUrl` / `ruleChapterList` /
`ruleBookContent` 那一代键名（实测样本：`202003.txt`，1537 条真实书源）。

## 本适配器只做一件事：键名归一，然后交给 3.x 那条**唯一**的转换路

决不做第二套 `convert`。归一实现只有 :func:`legado.normalize_legacy` 一处，
映射表在 `model.LEGACY_ALIASES`（**只收实测出现过的键**）。

⚠️ 第 94 期之前这 1537 条是**全灭**：`analyze` 一个键都读不到（它只认 3.x 键名），
逐条被判 `no`，且理由里看不出「是方言不认识」还是「这源真不行」。
"""
from .. import legado
from .base import FORMAT_LEGADO2, FormatAdapter, register_format
from .legado3 import Legado3Adapter


@register_format
class Legado2Adapter(FormatAdapter):
    format_id = FORMAT_LEGADO2
    display_name = "Legado / 阅读 App 旧版书源（2.x）"

    def sniff(self, payload) -> float:
        # 0.9 > legado-3 的 0.8：2.x 的源**同时**带 `bookSourceName`（3.x 的特征也有），
        # 差别只在「有没有旧键名」⇒ 用分数表达「2.x 更具体」，别在调用方写 if。
        if legado.detect_format(payload) != "legado":
            return 0.0
        try:
            entries = legado.parse_sources(payload)
        except Exception:                                    # noqa: BLE001 —— 嗅探不许炸
            return 0.0
        return 0.9 if any(legado.legacy_keys(e) for e in entries) else 0.0

    def map(self, entry) -> dict:
        """委托 3.x 适配器（`analyze` 内部也会归一一次 —— 幂等，3.x 键一个字都不动）。"""
        return Legado3Adapter().map(entry)
