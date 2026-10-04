"""**JSONL**（`legado-jsonl`）：每行一个 JSON 对象（书源站批量导出的常见形态）。

解析复用 `legado.parse_sources`（它本来就有 JSONL 分支，坏行会给「第 N 行不是合法 JSON」）。
每行的条目**再分派一次**（行里可能是 Legado 条目，也可能是 native 规则）。
"""
from .. import legado
from .base import FORMAT_JSONL, FormatAdapter, map_entry, register_format


@register_format
class JsonlAdapter(FormatAdapter):
    format_id = FORMAT_JSONL
    display_name = "每行一个 JSON 的书源清单（JSONL）"

    def sniff(self, payload) -> float:
        # 「是不是 JSONL」的判据只有 `legado.detect_format` 一处；分数低于按条目认的适配器
        # （0.7 < 0.8）：一份**单行**的 JSON 应该由 native / legado 认领，不是 JSONL。
        return 0.7 if legado.detect_format(payload) == "jsonl" else 0.0

    def map(self, entry) -> dict:
        """逐行再分派（JSONL 只是**装箱方式**，不决定条目是什么格式）—— 不复制第二份分派逻辑。

        不会递归回本适配器：单个条目是 dict，而本适配器只认**文本**（见 `sniff`）。
        """
        return map_entry(entry)
