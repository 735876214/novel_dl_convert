"""本项目**导出文件**（`nf-export`）：``{"nf_export": 1, "entries": [...]}``。

第 94 期之前这份文件**导不回本项目** —— 「书源管理 → 导入书源」卡只认 native schema，
把信封本身判成「缺少 name / 缺少 domains」，而「导出 → 导入幂等」是第 86 期就钉住的承诺。

⚠️ 信封判据（:func:`is_export_env`）**只有这一份**：`intake.detect` 与 `unpack_entries`
都读它，不再各自写一遍（两份判据一旦漂移，表现是「导出文件一会儿认得出一会儿认不出」）。
"""
import json

from .base import FORMAT_EXPORT, FormatAdapter, map_entry, register_format


def as_obj(payload):
    """字符串先按 JSON 解析；解析不了回 ``None``（可能仍是 JSONL，交给别的适配器判）。"""
    if isinstance(payload, (dict, list)):
        return payload
    s = str(payload or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:                                        # noqa: BLE001
        return None


def is_export_env(obj) -> bool:
    """本项目的导出信封：``{"nf_export": 1, "entries": [...]}``，或早期 ``{"version", "entries"}``。"""
    if not isinstance(obj, dict):
        return False
    if obj.get("nf_export"):
        return True
    return "version" in obj and isinstance(obj.get("entries"), list)


@register_format
class NativeExportAdapter(FormatAdapter):
    format_id = FORMAT_EXPORT
    display_name = "本项目导出文件"

    def sniff(self, payload) -> float:
        # 1.0（不是 0.8）：信封必须**压过**所有按条目认的适配器 ——
        # 信封本身既没有 `bookSourceName` 也没有 `name`+`domains`，但它内部是任意条目。
        return 1.0 if is_export_env(as_obj(payload)) else 0.0

    def parse(self, payload) -> list:
        obj = as_obj(payload)
        if not is_export_env(obj):
            raise ValueError("不是本项目的导出文件（缺 nf_export / entries）")
        return [e for e in (obj.get("entries") or []) if isinstance(e, dict)]

    def map(self, entry) -> dict:
        """信封里的条目**逐条再分派**（导出保留原文 ⇒ 里面可能是 Legado 原文，也可能是 native 规则）。

        刻意不在这里复制一份「native 还是 Legado」的判据：调 :func:`base.map_entry`。
        不会递归回本适配器 —— 单个条目不可能是信封（见 `is_export_env`）。
        """
        return map_entry(entry)
