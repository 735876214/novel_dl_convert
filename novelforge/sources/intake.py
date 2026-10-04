"""书源摄入：任意输入 → 识别格式 → 解析成条目 → 交给台账出差异表（第 94 期）。

## 为什么必须有这个模块

第 86 期起，导入书源有**两条互不相通的路**：

- ``POST /api/sources`` / ``/api/sources/upload``（「书源管理 → 导入书源」卡走的就是它）
  只认**本项目 native schema**，把 Legado 原文一条条判成「缺少 name / 缺少 domains /
  search.url 必填」，然后回 **HTTP 200** + ``{"added": [], "errors": [...]}``；
- ``POST /api/sources/import``（「书源工具」页）才是真正的导入器：认 Legado、出差异表、按决议落盘。

前端只读 ``added``、从不读 ``errors`` ⇒ 用户导入 Legado 书源时**屏幕上什么都不发生**
（提示还是「已添加  个书源」—— ``added`` 是名字数组，被拒时 ``[]`` 渲染成空串）。
用户报的「在书源管理 → 导入书源时导入两个书源，项目中没有反应」就是这条路。

所以把**路由决策收进本模块一处**：识别格式（格式轴的 `sniff_format`）→ 解析（适配器 `parse`）
→ 出差异表（`ledger.plan`，纯计算）。所有导入入口都调它；识别不出就给**人话原因**，
**绝不静默按 native 去校验**。

## 与 `ledger` / `formats` 的分工（别长成三套）

- **本模块**：把「输入」变成「条目 + 格式标识」，并出差异表行（``rows_from_payload``）；
- ``formats``：**格式轴** —— 一种输入怎么读（sniff / parse / 条目 → 能力报告）；
- ``ledger``：差异表的**判定**（``plan``，条目级分派也走 `formats.map_entry`）与**落盘**
  （``apply``，规则文件唯一写者仍是 ``store.add_rule``）。

``ledger.plan`` 需要本模块的产物，本模块需要 ``ledger.plan`` ⇒ 模块级互相导入会成环，
故 ``rows_from_payload`` 内部**局部导入** ``ledger``（这是本仓库唯一一处为破环而做的局部导入）。
"""
from __future__ import annotations

from . import formats, legado
from .formats import (FORMAT_EXPORT, FORMAT_JSONL, FORMAT_LEGADO2, FORMAT_LEGADO3,  # noqa: F401
                      FORMAT_NATIVE)

#: ⚠️ 格式标识的**定义**在 `formats/base.py`（格式轴自己的词汇表），这里只**再导出**。
#: `FORMAT_LEGADO` 是本模块与前端契约里用了两期的旧名字 —— 别名最省事，也最不容易漏改。
FORMAT_LEGADO = FORMAT_LEGADO3


def unknown_format_msg() -> str:
    """认不出格式时的原因。**支持哪几种从格式注册表生成** —— 加一个适配器，这句话自动跟上。"""
    names = "、".join(a.display_name for a in formats.FORMATS)
    return (f"无法识别格式：本项目支持 {names}（对象 / 数组 / 每行一个 JSON）。"
            "其他格式（.js / .xbs / XML / 纯文本规则）暂未支持")


def detect(payload) -> str:
    """嗅探格式 → 格式标识；认不出回空串。

    判据全在**格式轴**（每个适配器只包装既有的识别实现：`legado.detect_format` /
    `legado.legacy_keys` / 导出信封判据），本模块不自己认格式。
    """
    adapter, score = formats.sniff_format(payload)
    return adapter.format_id if adapter and score > 0 else ""


def unpack_entries(payload) -> list:
    """把输入解成**原始条目列表**（不判定能力、不转换）。

    吃下：本项目导出文件（信封）、Legado 3.x / 2.x、JSONL、native 规则、或已经是 list。
    坏输入抛 ``ValueError``（措辞可直接展示）。
    """
    adapter, score = formats.sniff_format(payload)
    if adapter and score > 0:
        return adapter.parse(payload)
    # 认不出的输入仍按老契约抛 `legado.parse_sources` 的原文（措辞没变，测试也钉着它）
    return legado.parse_sources(payload)


def sniff_and_adapt(payload) -> dict:
    """任意输入 → ``{"format": ..., "entries": [...]}``；认不出抛 ``ValueError``。"""
    fmt = detect(payload)
    if not fmt:
        raise ValueError(unknown_format_msg())
    entries = formats.adapter_for(fmt).parse(payload)
    if not entries:
        raise ValueError("没有解析出任何书源条目（顶层既不是对象也不是数组）")
    return {"format": fmt, "entries": entries}


def _missing_reason(row: dict) -> list[dict]:
    """判了「不可执行」却没给出理由时补一条 —— **理由不许留空**。

    正常情况下轮不到它：每个格式适配器的 `map()` 都会给理由（native 走
    `rules.validate_rule` 的原文，Legado 走 `analyze` 的逐字段判定）。这里是**兜底网**：
    万一某个适配器漏了理由，也要在界面上说清，而不是留一个「不能用但不告诉我为什么」的条目。
    """
    from . import rules
    errs = list(rules.validate_rule(row.get("raw") or {}))
    if errs:
        return [{"field": "（必填项）", "construct": "required", "why": e,
                 "instead": "请在「书源管理」的手动表单里补齐后保存"} for e in errs]
    return [{"field": "（缺少理由）", "construct": "no_reason",
             "why": "本条被判不可执行，但分析器没有给出原因",
             "instead": "请在「书源工具」里重新分析一次；若仍无理由，请到仓库提 issue"}]


def rows_from_payload(payload, *, origin: str = "") -> dict:
    """任意输入 → ``{"format": ..., "rows": [...]}``，``rows`` 是 ``ledger.plan`` 的差异表行。

    **纯计算：不落盘、不出网。** 落盘一律由 ``ledger.apply`` 负责（唯一写者链不变）。
    """
    from . import ledger                                     # 局部导入：见模块 docstring 的破环说明

    got = sniff_and_adapt(payload)
    rows = ledger.plan(got["entries"], origin=origin)
    for row in rows:
        if row["verdict"] == "unsupported" and not row["unsupported_fields"]:
            row["unsupported_fields"] = _missing_reason(row)
    return {"format": got["format"], "rows": rows}
