"""书源**格式**适配器（第 94 期）：一条与执行层**正交**的轴。

## 两条轴，别混

- **执行轴**（第 86 期）：`sources/base.py` 的 `SourceAdapter` + `REGISTRY` —— 「怎么抓」；
- **格式轴**（本期）：本模块的 `FormatAdapter` + `FORMATS` —— 「这份输入是什么格式、怎么读成条目」。

两者**不合并、不互为第二实现**：格式适配器只做 sniff / parse / map / serialize，
**绝不产出第二套可执行结构** —— 产物一律是 native 规则，能不能跑由
`rules.validate_rule` + `rules.audit_native_rule` 说话（`legado.analyze` 也一样）。

## 格式标识（`format_id`）的唯一定义处

就是本模块顶部那几个 `FORMAT_*` 常量：接口返回体、差异表、界面文案都读它。
`sources/intake.py` 只**再导出**旧名字（`intake.FORMAT_LEGADO` 等），不另写一份字面量。

## `map()` 的产出形状（与 `legado.analyze` **刻意**同一形状）

    {"supported": "yes" | "partial" | "no",   # 引擎到底能不能跑（由 audit_native_rule 定）
     "unsupported_fields": [{field, why, instead, construct?}],
     "converted_rule": dict | None,           # native 规则（判 no 时也可能给，供差异表展示）
     "notes": [str],
     "source_type": "text" | "audio" | "image" | "file" | "unknown"}

`ledger.plan` 不关心条目来自哪个格式 —— 所以这里的形状必须与 `analyze` 一致。
⚠️ 计划里 `map()` 的签名写作 ``-> tuple[UnifiedBookSource | None, list[dict]]``：
落地改成上面这个 dict，因为 `plan` 还要 `notes` / `source_type` / `supported` 三样，
元组塞不下；硬拆成两个方法会出现「一半走元组、一半走报告」的两套口径。
"""
from abc import ABC, abstractmethod

#: 格式标识：**唯一定义处**（见模块 docstring）
FORMAT_NATIVE = "nf-native"
FORMAT_EXPORT = "nf-export"
FORMAT_LEGADO3 = "legado-3"
FORMAT_LEGADO2 = "legado-2"
FORMAT_JSONL = "legado-jsonl"


class FormatAdapter(ABC):
    """一种输入格式。子类**只包装**既有实现，不复制解析 / 转换逻辑。"""

    format_id: str = ""
    display_name: str = ""

    def sniff(self, payload) -> float:
        """0..1 的置信度（0 = 不是这个格式）。

        同一份输入取**分数最高**的适配器，同分按注册顺序 —— 所以「2.x 比 3.x 更具体」
        可以直接用分数表达（0.9 > 0.8），不必在调用方写 if。
        """
        return 0.0

    def parse(self, payload) -> list:
        """解析成条目列表。坏输入抛 ``ValueError``（措辞可直接给用户看）。

        默认实现**委托** `legado.parse_sources`：它做的是「JSON / 数组 / 对象 / JSONL → dict 列表」，
        与 Legado 无关的通用解析 —— 全项目只有这一份，本项目导出信封要自己解（见 `nf_export`）。
        """
        from .. import legado
        return legado.parse_sources(payload)

    @abstractmethod
    def map(self, entry) -> dict:
        """一个条目 → 能力报告（见模块 docstring）。"""

    def serialize(self, source) -> dict:
        """native 规则 → 本格式。默认**恒等**（本项目自己的格式就是 native）。"""
        from ..model import to_native
        return to_native(source)


#: 格式轴注册表（**不是** `base.REGISTRY` —— 那是执行轴）
FORMATS: list = []


def register_format(adapter):
    """把适配器登记进格式轴（**装饰器**用法：加在**类**上）。

    ⚠️ 注册表里存的是**实例**、返回值仍是**类**：存类的话 ``a.sniff(payload)`` 会少一个
    `self` 直接 TypeError，而 `sniff_format` 的 except 会把它吞成「置信度 0」——
    表现是「所有格式都认不出」，最难查的那种。
    """
    FORMATS.append(adapter() if isinstance(adapter, type) else adapter)
    return adapter


def adapter_for(format_id: str) -> "FormatAdapter | None":
    return next((a for a in FORMATS if a.format_id == format_id), None)


def sniff_format(payload) -> tuple:
    """输入 → ``(适配器 | None, 置信度)``。认不出回 ``(None, 0.0)``。"""
    best, score = None, 0.0
    for a in FORMATS:
        try:
            s = float(a.sniff(payload) or 0.0)
        except Exception:                                    # noqa: BLE001 —— 嗅探不许炸
            s = 0.0
        if s > score:
            best, score = a, s
    return best, score


def map_entry(entry) -> dict:
    """**条目 → 能力报告**的唯一入口（`ledger.plan` 只调它）。

    「这个条目是 native 还是 Legado」这条判据**只存在于适配器的 `sniff` 里** ——
    `plan` 当年内联的那句 ``"name" in ent and "domains" in ent`` 已经删掉，
    否则同一件事就有两份判据（改一处漏一处 = 静默错判）。

    认不出的条目交给 native 适配器：它会用 `rules.validate_rule` 逐条说清缺什么
    （「缺少 name（唯一标识）」…）—— 比一句「未知条目」有用得多，也**不会**静默放行。
    """
    for a in FORMATS:
        try:
            if float(a.sniff(entry) or 0.0) > 0:
                return a.map(entry)
        except Exception:                                    # noqa: BLE001 —— 嗅探不许炸
            continue
    fallback = adapter_for(FORMAT_NATIVE)
    if fallback is None:                                     # 理论上不可能（导入即注册）
        return {"supported": "no", "unsupported_fields": [{
            "field": "（条目）", "construct": "no_adapter",
            "why": "没有任何格式适配器认领这个条目",
            "instead": "请到仓库提 issue（格式注册表没被加载）"}],
            "converted_rule": None, "notes": [], "source_type": "unknown"}
    return fallback.map(entry)


def serialize_native(source) -> dict:
    """native 规则 → 本项目格式（导出用）。走注册表，避免调用方自己找适配器。"""
    ad = adapter_for(FORMAT_NATIVE)
    return ad.serialize(source) if ad else dict(source or {})


def format_label(format_id: str) -> str:
    """格式标识 → 界面用的中文名（认不出就原样回显，不吞）。"""
    ad = adapter_for(format_id)
    return ad.display_name if ad else str(format_id or "")
