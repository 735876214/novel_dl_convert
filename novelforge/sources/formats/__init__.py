"""格式轴（第 94 期）：`FORMATS` 注册表 + 条目级分派。

导入本包即注册 5 个适配器（顺序 = 同分时的优先级），`sources/intake.py` 与 `sources/ledger.py`
都从这里拿判据 —— **不在别处再写一份**「这是什么格式 / 这个条目该怎么读」。

| format_id | 是什么 | 本期 |
|---|---|---|
| `nf-native` | 本项目书源规则 | 做 |
| `nf-export` | 本项目导出文件（信封） | 做 |
| `legado-3` | Legado / 阅读 3.x 书源 | 做 |
| `legado-2` | Legado / 阅读 2.x 旧方言 | 做（1537 条真样本） |
| `legado-jsonl` | 每行一个 JSON | 做 |

**没做**（用户口径：没提供有效样本 ⇒ 不猜、不做空壳）：`.js`（Legado JS/Tauri）、
`.xbs`（香色闺阁）、XML 老格式、纯文本键值对规则。它们从仓库外进来时由
`sources/intake.py` 给「无法识别格式：…」的人话原因。
"""
from .base import (FORMAT_EXPORT, FORMAT_JSONL, FORMAT_LEGADO2, FORMAT_LEGADO3,  # noqa: F401
                   FORMAT_NATIVE, FORMATS, FormatAdapter, adapter_for, format_label,
                   map_entry, register_format, serialize_native, sniff_format)
from . import legado2, legado3, jsonl, native, nf_export                  # noqa: F401 —— 导入即注册

__all__ = ["FORMATS", "FormatAdapter", "FORMAT_NATIVE", "FORMAT_EXPORT", "FORMAT_LEGADO2",
           "FORMAT_LEGADO3", "FORMAT_JSONL", "adapter_for", "format_label", "map_entry",
           "register_format", "serialize_native", "sniff_format"]
