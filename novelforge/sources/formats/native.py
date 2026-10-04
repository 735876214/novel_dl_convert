"""本项目自己的书源规则（`nf-native`）：格式轴的基准。

它**没有任何转换**（`:func:`model.to_native` 是恒等函数）—— 但这个适配器不是摆设：
它把「手写规则 / 导出文件里的规则」也拉进**同一条**审计路（`validate_rule` + `audit_native_rule`），
于是「引擎能不能跑」这条判据对所有格式一致，**不再有例外通道**
（第 94 期之前 native 条目的 `supported` 是 `ledger.plan` 里硬编码的 `"yes"`）。
"""
from .. import rules
from ..model import to_native
from .base import FORMAT_NATIVE, FormatAdapter, register_format


@register_format
class NativeAdapter(FormatAdapter):
    format_id = FORMAT_NATIVE
    display_name = "本项目书源规则"

    def sniff(self, payload) -> float:
        """认「本项目规则」的判据只有 `legado._detect_obj` 一处（`ours` 那一支）。"""
        from .. import legado
        return 0.8 if legado.detect_format(payload) == "ours" else 0.0

    def map(self, entry) -> dict:
        ent = dict(entry or {}) if isinstance(entry, dict) else {}
        bad = [{"field": "（必填项）", "construct": "required", "why": e,
                "instead": "请在「书源管理」的手动表单里补齐后保存"}
               for e in rules.validate_rule(ent)]
        bad += rules.audit_native_rule(ent)
        return {
            "supported": "no" if bad else "yes",
            "unsupported_fields": bad,
            # ⚠️ 判 no 也把规则本体带上：差异表里要能显示「是哪一条、长什么样」，
            #    而 `plan` 的行名取自它（不带就得回退成 `lg-<哈希>`，用户认不出是自己的哪条源）。
            #    `ledger.apply` 对 `unsupported` 只记台账、**不落规则**，所以带上不会写出去。
            "converted_rule": to_native(ent),
            "notes": [],
            "source_type": str((ent.get("legado") or {}).get("source_type") or "text"),
        }
