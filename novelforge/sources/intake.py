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

所以把**路由决策收进本模块一处**：识别格式 → 解析 → 出差异表（纯计算）。
所有导入入口都调它；识别不出就给**人话原因**，**绝不静默按 native 去校验**。

## 与 `ledger` 的分工（别长成两套）

- **本模块**：认格式（``detect``）、解信封（``unpack_entries``）、出差异表行（``rows_from_payload``）；
- ``ledger``：差异表的**判定**（``plan``）与**落盘**（``apply``，规则文件唯一写者仍是 ``store.add_rule``）。

``ledger.plan`` 需要本模块的产物，本模块需要 ``ledger.plan`` ⇒ 模块级互相导入会成环，
故 ``rows_from_payload`` 内部**局部导入** ``ledger``（这是本仓库唯一一处为破环而做的局部导入）。
"""
from __future__ import annotations

import json

from . import legado, rules

#: 格式标识（**唯一真值源**：接口返回体、差异表、界面上的「识别为 X」都用它）
FORMAT_NATIVE = "nf-native"
FORMAT_EXPORT = "nf-export"
FORMAT_LEGADO = "legado-3"
FORMAT_JSONL = "legado-jsonl"

#: ``legado.detect_format`` 的结论 → 本模块的格式标识
_KINDS = {"legado": FORMAT_LEGADO, "ours": FORMAT_NATIVE, "jsonl": FORMAT_JSONL}

#: 认不出时给用户看的原因（**措辞要能直接照做**，不是「解析失败」）
UNKNOWN_FORMAT_MSG = (
    "无法识别格式：请提供 Legado（阅读 App）书源文件、本项目导出的书源文件，"
    "或本项目的书源规则 JSON（对象 / 数组 / 每行一个 JSON）"
)


def _as_obj(payload):
    """字符串先按 JSON 解析；解析不了返回 ``None``（可能仍是 JSONL，交给下面判）。"""
    if isinstance(payload, (dict, list)):
        return payload
    s = str(payload or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:                                        # noqa: BLE001
        return None


def _is_export_env(obj) -> bool:
    """本项目的导出信封：``{"nf_export": 1, "entries": [...]}``，或早期 ``{"version", "entries"}``。"""
    if not isinstance(obj, dict):
        return False
    if obj.get("nf_export"):
        return True
    return "version" in obj and isinstance(obj.get("entries"), list)


def detect(payload) -> str:
    """嗅探格式 → 格式标识；认不出回空串。

    ⚠️ 导出信封必须在 ``legado.detect_format`` **之前**判：信封本身既没有
    ``bookSourceName`` 也没有 ``name``+``domains``，交给它只会得到「认不出」。
    """
    if _is_export_env(_as_obj(payload)):
        return FORMAT_EXPORT
    return _KINDS.get(legado.detect_format(payload), "")


def unpack_entries(payload) -> list:
    """把输入解成**原始条目列表**（不解信封以外的事：不判定能力、不转换）。

    吃下：本项目导出文件（``{nf_export}`` / ``{version,entries}`` 信封）、Legado 数组 /
    单对象 / JSONL、native 规则、或已经是 list。坏输入抛 ``ValueError``（措辞可直接展示）。
    """
    obj = _as_obj(payload)
    if _is_export_env(obj):
        return [e for e in (obj.get("entries") or []) if isinstance(e, dict)]
    return legado.parse_sources(payload)


def sniff_and_adapt(payload) -> dict:
    """任意输入 → ``{"format": ..., "entries": [...]}``；认不出抛 ``ValueError``。"""
    fmt = detect(payload)
    if not fmt:
        raise ValueError(UNKNOWN_FORMAT_MSG)
    entries = unpack_entries(payload)
    if not entries:
        raise ValueError("没有解析出任何书源条目（顶层既不是对象也不是数组）")
    return {"format": fmt, "entries": entries}


def _missing_reason(row: dict) -> list[dict]:
    """判了「不可执行」却没给出理由时补一条 —— **理由不许留空**。

    native 条目被判不可执行，理由就是「必填项缺失」：由 ``rules.validate_rule``
    出原话（**同一份判据**，这里不另写一套必填项规则）。
    Legado 条目判 ``no`` 时 ``analyze`` 必然给了理由；万一真缺了，也如实说「原因未知」——
    界面上出现一个「不能用但不告诉我为什么」的条目，与本月纪律直接冲突。
    """
    errs = list(rules.validate_rule(row.get("raw") or {}))
    if errs:
        return [{"field": "（必填项）", "why": e,
                 "instead": "请在「书源管理」的手动表单里补齐后保存"}
                for e in errs]
    return [{"field": "（缺少理由）", "why": "本条被判不可执行，但分析器没有给出原因",
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
