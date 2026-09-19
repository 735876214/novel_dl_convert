"""每库覆盖（第 13 期）：让每个书库各用各的投递 / 元数据 / 命名策略。

**它是配置的第四层，不是新配置体系**。全局分层仍是
``DEFAULTS → config.yaml → settings.json → 环境变量``（见 :func:`config.load_config`）；
本模块只在**「目标库已知」的那一刻**叠加一层：

    生效值 = 每库覆写 ?? 全局值

三条设计约束：

1. **只存被覆写的键**（``libraries.settings`` 是一个稀疏 JSON）。于是全局改了策略，
   没覆写过的库**会自动跟着变** —— 若存全量副本就做不到这一点。
2. **绝不修改 `config.load_config()` 的语义**。要「全局 + 该库」就用
   :func:`config_for`（返回深拷贝），其它调用方继续拿纯全局值。
3. **与能力矩阵联动**：库类型不具备的能力，对应覆盖项**不返回、不生效**（见
   :func:`features.allows_setting`）—— 免得界面给出一个「设了却没反应」的开关。

键名一律用**全局配置的点分路径**（``output.layout`` / ``metadata_fetch.fields`` …），
这样「继承全局」就是字面意义上的「取全局同名键的值」，不需要第二张映射表。
"""
from __future__ import annotations

import copy
import json
import re

from .. import config
from . import db, features, library

#: 允许每库覆写的项：(键, 标签, 类型, 枚举选项, 说明)。
#: 类型：``bool`` / ``enum`` / ``number`` / ``str`` / ``policy_map``（逐字段策略，按字段合并）。
ITEMS = (
    ("output.format", "转换产物格式", "enum", ("epub", "mobi", "azw3"),
     "派生 MOBI / AZW3 需要 Calibre，缺失时自动降级为 EPUB"),
    ("output.layout", "落盘布局", "enum", ("flat", "komga"),
     "komga = 有系列的书落「系列名/系列名 #N.ext」"),
    ("watcher.recursive", "递归子目录", "bool", None,
     "投递时是否连子目录一起处理"),
    ("watcher.copy_non_txt", "非 TXT 原样收取", "bool", None,
     "关闭后只有 TXT 会被转换入库，其它格式不收"),
    ("metadata_fetch.enabled", "在线元数据抓取", "bool", None,
     "新书入库时是否自动在线抓元数据（会外呼公网）"),
    ("metadata_fetch.auto_on_import", "入库自动抓取", "bool", None,
     "新书入库后是否自动在线补元数据（会外呼公网）；关掉则该库不自动抓，仅手动"),
    ("metadata_fetch.threshold", "置信度阈值", "number", None,
     "低于它的候选不自动应用，只在页面上列出（0–1）"),
    ("metadata_fetch.fields", "字段写回策略", "policy_map", None,
     "逐字段：overwrite / fill_only / skip；未列的字段继承全局"),
    ("naming.pattern", "命名规则", "str", None,
     "占位符：{title} {author} {series} {index}；刮削出版的副本文件名也用它"),
    ("naming.scope", "命名适用格式", "str", None,
     "all 或某个扩展名（如 epub）"),
    ("scrape.enabled", "刮削出版", "bool", None,
     "扫描入库后自动把刮削结果写进该库**成品目录**的硬链接副本（源文件不改）；"
     "关闭后只能手动跑。要先在书库上设置成品目录"),
    ("opds.expose", "对 OPDS 暴露", "bool", None,
     "关闭后该书库不出现在对外 OPDS 目录里，直连它的单库地址也返回 404"),
)

_ITEM_MAP = {spec[0]: spec for spec in ITEMS}

#: 逐字段策略的合法取值（与 ``config.DEFAULTS["metadata_fetch"]["fields"]`` 同口径）
POLICIES = ("overwrite", "fill_only", "skip")


# ---------------- 读 ----------------

def _dotted_get(cfg: dict, key: str):
    cur = cfg
    for part in str(key).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _dotted_set(cfg: dict, key: str, value) -> None:
    parts = str(key).split(".")
    cur = cfg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def overrides(library_id) -> dict:
    """该库**已覆写**的项（稀疏 dict）；坏 JSON 一律当「没有覆写」。

    手改坏一个字符不该把书库页整页弄挂 —— 与项目「解析失败只记 issue 不抛」同口径。
    """
    lib = library.get_library(library_id) or {}
    raw = str(lib.get("settings") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:                       # noqa: BLE001 —— 坏数据降级为「无覆盖」
        return {}
    return data if isinstance(data, dict) else {}


def schema(library_type=None) -> list:
    """该库类型可覆写的项（供界面渲染；不具备能力的项直接不出现）。"""
    out = []
    for key, label, kind, options, note in ITEMS:
        if not features.allows_setting(library_type, key):
            continue
        out.append({"key": key, "label": label, "kind": kind,
                    "options": list(options or ()), "note": note,
                    "capability": features.setting_capability(key)})
    return out


def effective(library_id) -> dict:
    """某库的生效设置：``每库覆写 ?? 全局``，并标出哪些键被本库覆写。

    返回 ``{library_id, name, library_type, values, global, overridden, overrides, schema}``。
    - ``values`` / ``global`` 的键与 :data:`ITEMS` 一致（点分路径）；
    - ``overridden[key]`` 为真表示该库显式覆写过（界面据此显示「已覆盖 / 恢复继承」）；
    - ``overrides`` 是**原始覆写**（未与全局合并）。``overridden`` 只能告诉你「这一项
      被改过」，但对 ``policy_map`` 这种**按字段**合并的项不够用 —— 界面要逐字段显示
      「继承 / 覆盖」，就得知道哪个字段真的被改过，所以原样再给一份；
    - 返回项**已按库类型的能力收窄**：漫画库不会返回元数据策略。
    """
    lib = library.get_library(library_id) or {}
    lid = str(lib.get("id") or library_id or "")
    ltype = str(lib.get("type") or "mixed")
    cfg = config.load_config()
    ov = overrides(lid)

    values, glob, overridden = {}, {}, {}
    for key, _label, kind, _options, _note in ITEMS:
        if not features.allows_setting(ltype, key):
            continue
        g = _dotted_get(cfg, key)
        glob[key] = g
        if key in ov:
            values[key] = _merge(kind, g, ov[key])
            overridden[key] = True
        else:
            values[key] = g
            overridden[key] = False
    return {"library_id": lid, "name": str(lib.get("name") or ""), "library_type": ltype,
            "values": values, "global": glob, "overridden": overridden,
            "overrides": ov, "schema": schema(ltype)}


def _merge(kind: str, global_value, override_value):
    """``policy_map`` 按**字段**合并（未列的字段继承全局），其余类型整体替换。"""
    if kind != "policy_map":
        return override_value
    out = dict(global_value or {})
    out.update({k: v for k, v in dict(override_value or {}).items() if v})
    return out


def apply_to(section: dict, library_id, prefix: str) -> dict:
    """把该库在 ``prefix`` 段下**真正覆写过**的键并入给定配置段（返回新 dict）。

    给「按书 / 按条目取策略」的消费者用（``metafetch`` / ``series_meta``）：
    调用方通常已经拿到一份配置段（可能来自显式传参、也可能是全局），这里只覆盖
    该库确实改过的键 —— 于是「**库没覆写过 = 行为与之前完全一致**」这条成立，
    调用方显式传入的值对未覆写的键也不会被静默丢掉。
    """
    out = dict(section or {})
    lid = str(library_id or "").strip()
    if not lid:
        return out
    ov = overrides(lid)
    if not any(str(k).startswith(f"{prefix}.") for k in ov):
        return out
    lib = library.get_library(lid) or {}
    ltype = str(lib.get("type") or "mixed")
    full = config_for(lid)
    for key in ov:
        key = str(key)
        if not key.startswith(f"{prefix}."):
            continue
        # 能力不匹配的遗留覆写不生效（库类型改过之后，旧覆写不该突然活过来）
        if not features.allows_setting(ltype, key):
            continue
        out[key.split(".", 1)[1]] = _dotted_get(full, key)
    return out


def config_for(library_id=None) -> dict:
    """全局配置 + 该库的覆盖（按点分路径写回）。

    **给「已经知道目标库」的调用方用的最小改动入口**：拿到之后照旧读
    ``cfg["output"]["layout"]`` / ``cfg["metadata_fetch"]["fields"]``，
    读法一行都不用改。``library_id`` 为空 → 等价于纯全局配置。

    ⚠️ 返回**深拷贝**：`load_config()` 只做了一层浅拷贝，直接改它的嵌套子字典
    （如 ``metadata_fetch.fields``）会污染模块级 ``DEFAULTS``。
    """
    cfg = copy.deepcopy(config.load_config())
    if not library_id:
        return cfg
    lib = library.get_library(library_id) or {}
    ltype = str(lib.get("type") or "mixed")
    for key, value in overrides(lib.get("id") or library_id).items():
        if key not in _ITEM_MAP:
            continue
        # 能力不匹配的遗留覆写**不生效**：库类型改过之后，旧覆写不该突然活过来
        if not features.allows_setting(ltype, key):
            continue
        kind = _ITEM_MAP[key][2]
        _dotted_set(cfg, key, _merge(kind, _dotted_get(cfg, key), value))
    return cfg


# ---------------- 写 ----------------

def _validate(key: str, raw):
    """按项类型校验并归一化（与既有枚举/类型口径一致；拼 SQL 前也靠这层兜底）。"""
    kind = _ITEM_MAP[key][2]
    if kind == "bool":
        if not isinstance(raw, bool):
            raise ValueError(f"{key} 需要 true / false")
        return raw
    if kind == "enum":
        opts = _ITEM_MAP[key][3] or ()
        s = str(raw or "")
        if s not in opts:
            raise ValueError(f"{key} 只能是 {' / '.join(opts)}")
        return s
    if kind == "number":
        try:
            f = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{key} 需要数字") from None
        if not 0 <= f <= 1:
            raise ValueError(f"{key} 必须在 0–1 之间")
        return round(f, 4)
    if kind == "policy_map":
        if not isinstance(raw, dict):
            raise ValueError(f"{key} 需要对象（字段 → 策略）")
        out = {}
        for field, policy in raw.items():
            if policy is None:              # 该字段恢复继承
                continue
            if str(policy) not in POLICIES:
                raise ValueError(f"字段策略只能是 {' / '.join(POLICIES)}")
            out[str(field)] = str(policy)
        return out
    s = str(raw or "").strip()
    if not s:
        raise ValueError(f"{key} 不能为空")
    # 命名规则会被当文件名用：出现路径分隔符就可能写到库根之外
    if re.search(r"[\\/]", s):
        raise ValueError(f"{key} 不能包含路径分隔符")
    return s


def set_overrides(library_id, values: dict) -> dict:
    """写入（或清除）该库的覆盖项。**值传 ``None`` = 该项恢复继承全局**。

    ``metadata_fetch.fields`` 支持**字段级**恢复：``{"tags": None}`` 只让 tags 回到全局。
    """
    lib = library.get_library(library_id)
    if not lib:
        raise ValueError("书库不存在")
    ltype = str(lib.get("type") or "mixed")
    if not isinstance(values, dict) or not values:
        raise ValueError("没有可更新的覆盖项")

    ov = overrides(lib.get("id"))
    for key, raw in values.items():
        if key not in _ITEM_MAP:
            raise ValueError(f"不支持的覆盖项：{key}")
        if not features.allows_setting(ltype, key):
            raise ValueError(f"「{_ITEM_MAP[key][1]}」不适用于这个库类型")
        if raw is None:
            ov.pop(key, None)
            continue
        if _ITEM_MAP[key][2] == "policy_map":
            # 字段级合并：现存覆写里被显式置 null 的字段先摘掉，再并入本次提交
            cur = dict(ov.get(key) or {})
            for field, policy in _validate(key, raw).items():
                cur[field] = policy
            for field in list((raw or {}).keys()):
                if (raw or {}).get(field) is None:
                    cur.pop(str(field), None)
            if cur:
                ov[key] = cur
            else:
                ov.pop(key, None)
            continue
        ov[key] = _validate(key, raw)

    db.update_library(lib.get("id"), settings=json.dumps(ov, ensure_ascii=False))
    return effective(lib.get("id"))


def clear_overrides(library_id, keys=None) -> dict:
    """恢复继承：``keys`` 为空表示**全部**项都回到全局值。"""
    lib = library.get_library(library_id)
    if not lib:
        raise ValueError("书库不存在")
    ov = overrides(lib.get("id"))
    if keys is None:
        ov = {}
    else:
        for k in keys:
            ov.pop(str(k), None)
    db.update_library(lib.get("id"), settings=json.dumps(ov, ensure_ascii=False))
    return effective(lib.get("id"))
