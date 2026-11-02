"""自定义元数据字段：**定义**（全局）+ **值**（按书）。

第 35 期把原先「抓取配置里写死的一串键值对」升级为可管理的字段定义，对齐上游
custom-metadata 的六项操作：建字段 / 排序 / 改标签 / 切适用书库 / 归档 / 软删恢复。

分工
----
- ``db`` 只管存取（两张表：``custom_field_defs`` / ``book_custom_values``）；
- 本模块管**语义**：key 派生、类型校验、适用书库过滤、旧配置迁移。

三条口径
--------
1. **key 与 label 分离**：值表按 key 引用，改显示名不动任何一本书的值。
   key 由显示名派生一次（``slug``）后不再变；纯中文名派生不出 ASCII 时用名字的
   稳定摘要兜底（**不是随机值** —— 换一次进程就换 key 等于把值全丢）。
2. **「行存在」= 这本书的这一项被管过了**：抓取只在**没有值行**时补默认值。
   所以「把值清空」不会被下一次抓取填回来（清空写空串、行仍在）——与元数据那边
   「清空写无值哨兵」是同一个思路的两种实现。
3. **类型只约束录入**：``number`` / ``date`` 是校验规则，不是存储类型；
   对外一律给字符串（``list`` 除外，它给字符串列表，与题材 tags 同形）。
"""
from __future__ import annotations

import hashlib
import re

from .. import config
from . import db

#: 字段类型 → 中文名（界面下拉与校验共用一份，别在页面里再抄一遍）
TYPES = (
    ("text", "文本"),
    ("number", "数字"),
    ("date", "日期"),
    ("list", "多个值"),
)

#: 类型键集合（校验用）
TYPE_KEYS = tuple(k for k, _ in TYPES)

#: **值的**长度上限（字符）。
#:
#: ⚠️ 第 255 期：自定义字段的值此前**一个上限都没有** ⇒ 用户在详情页把一个字段
#: 粘成 1 MB 就能存进去 ⇒ **详情接口**每次都带着它（`custom` 段是详情响应的一部分）
#: ⇒ 打开一次详情页 = 传 1 MB。
#:
#: ⚠️ 更狠的是**默认值**：`default_value` 会被抓取写进**每一本缺这一项的书**
#: （`metafetch._custom_changes`）⇒ 一个 1 MB 的默认值 ⇒ **整个书库**每本都被
#: 写进 1 MB ⇒ **放大到全库**。
#:
#: ⚠️ 上限**按类型**给：`list` 是**多个值**（存成字面量列表）⇒ 它的上限按
#: **整段**算，不是「每条」。数字与日期的长度天然短，但走**同一个上限**即可
#: （它们的取值本来就短 ⇒ 碰不到上限）。
def _text_limit() -> int:
    """文本类字段（text / number / date）的值长度上限。

    ⚠️ **不另抄一份数** —— 取自元数据字段那张表（第 250 期立的「用户能填的
    一段文字」口径）⇒ 两条路**永远同上限**。
    """
    try:
        return int(db.metadata_field_limits().get("description") or 8000)
    except Exception:                     # noqa: BLE001 —— 兜底，不让上限查询把写入搞挂
        return 8000


def value_limits() -> dict:
    """自定义字段**值的**长度上限（类型 → 字符数）。

    ⚠️ 判据**只有一处**（这里）。前端据此给输入框加 `maxlength`
    （用户**输入时**就知道有上限，而不是提交后吃一个「服务器错误」）。
    """
    text = _text_limit()
    return {"text": text, "number": text, "date": text, "list": text}

def slug(name: str) -> str:
    """显示名 → **稳定**的字段 key。

    ASCII 名走「小写 + 非字母数字转下划线」；纯中文（或其它非 ASCII）名派生不出内容，
    回落成名字的 md5 前缀 —— 关键是**稳定**：用 ``hash()`` 或随机值都会让 key 一次一换，
    那等于每次启动都把值表读空。
    """
    s = re.sub(r"[^0-9a-z]+", "_", str(name or "").strip().lower()).strip("_")
    if s:
        return s[:40]
    return "f" + hashlib.md5(str(name or "").encode("utf-8")).hexdigest()[:10]


def normalize(type_: str, value) -> str:
    """校验外部值并转成**存储字符串**（非法值抛 ``ValueError``，接口层转 400）。

    ⚠️ 第 255 期：**长度上限**在这里判（判据 `value_limits()`）。
    处置是**抛 ValueError**（= 拒绝），与第 250 期「用户写入超限 ⇒ 拒绝」同口径
    —— 这是**用户自己填的值**，截断会静默丢数据（用户以为写了整段）。
    ⚠️ 而**批量**那条路（抓取写默认值）走的是**同一个** `normalize`
    ⇒ 也会拒绝 ⇒ 一家源返回异常大的默认值会让那本书的抓取失败（而不是把
    1 MB 写进库里）—— 与第 250 期「抓取跳过该字段」不同，但这里的值来自
    **用户自己的字段定义**，不是外部站点 ⇒ 拒绝是合理的（让用户自己去改短）。
    """
    t = str(type_ or "text")
    limit = value_limits().get(t, _text_limit())
    if t == "list":
        if isinstance(value, (list, tuple)):
            items = [str(x).strip() for x in value]
        else:
            items = [s.strip() for s in re.split(r"[、,，]", str(value or ""))]
        # 存成字面量列表（与 tags 等列同一套存法，见 db._as_list）
        out = repr([x for x in items if x])
        if len(out) > limit:
            raise ValueError(f"太长了（{len(out)} 字符，上限 {limit}）")
        return out
    s = str(value if value is not None else "").strip()
    if t == "number" and s:
        try:
            float(s)
        except (TypeError, ValueError):
            raise ValueError(f"必须是数字：{s}") from None
    if len(s) > limit:
        raise ValueError(f"太长了（{len(s)} 字符，上限 {limit}）")
    return s


def out_value(type_: str, stored) -> "str | list":
    """存储字符串 → 对外值（``list`` 给列表，其余给字符串）。"""
    if str(type_ or "text") == "list":
        return db._as_list(stored)
    return str(stored or "")


def applicable(defs: list, library_id) -> list:
    """筛出对该书库生效的定义：**已归档**的不进编辑界面，**适用书库**不含该库的也不进。

    ``library_ids`` 为空 = 全部书库（默认）—— 加这个维度是因为「漫画版次」这类字段
    对纯电子书库没有意义。
    """
    out = []
    for d in defs or []:
        if d.get("archived"):
            continue
        libs = d.get("library_ids") or []
        if libs and str(library_id or "") not in libs:
            continue
        out.append(d)
    return out


def state(book: dict, defs: list = None) -> list:
    """某本书的自定义字段（按定义顺序）：``[{key, label, type, value, default_value}]``。

    只含**适用该书库且未归档**的定义 —— 详情页直接照着渲染，不需要再判断一次。
    """
    book = book or {}
    defs = db.list_custom_fields() if defs is None else defs
    bid = book.get("id")
    values = db.custom_field_values(bid) if bid else {}
    return [
        {
            "key": d["key"],
            "label": d["label"],
            "type": d["type"],
            "default_value": d["default_value"],
            "value": out_value(d["type"], values.get(d["key"], "")),
        }
        for d in applicable(defs, book.get("library_id"))
    ]


def write(book: dict, payload: dict, defs: list = None) -> dict:
    """写入某本书的自定义字段值。

    ``payload`` 是 ``{key: 值}``。只接受**该书适用**的定义键，其余进 ``ignored``
    （与 ``POST /api/books/{bid}/metadata`` 对未知字段的处置一致：如实回报，不静默丢）。
    值的**空串也算写入**（= 用户显式清空，抓取不会再用默认值填回来），
    所以这里不做「空值跳过」。
    """
    book = book or {}
    bid = str(book.get("id") or "")
    if not bid:
        raise ValueError("书不存在")
    defs = db.list_custom_fields() if defs is None else defs
    by_key = {d["key"]: d for d in applicable(defs, book.get("library_id"))}
    saving: dict = {}
    ignored: list = []
    for key, value in (payload or {}).items():
        d = by_key.get(str(key))
        if d is None:
            ignored.append(str(key))
            continue
        try:
            saving[str(key)] = normalize(d["type"], value)
        except ValueError as e:
            raise ValueError(f"{d['label']}：{e}") from None
    if saving:
        db.set_custom_field_values(bid, saving)
        # ⚠️ 刻意**不** invalidate 扫描缓存：自定义字段值不参与 library.books() 的合并
        # （不进列表 / 搜索 / OPDS），详情页每次都从本接口现取。若将来要进列表，才需要。
    return {
        "saved": sorted(saving.keys()),
        "ignored": sorted(ignored),
        "custom": state(book, defs),
    }


def migrate_from_config(cfg: dict = None) -> list:
    """一次性把旧配置项 ``metadata_fetch.custom_fields`` 迁成字段定义（**幂等**）。

    旧项的语义是「``{name, value}``：写进 EPUB 的 meta 对」——
    ⚠️ 但它**从来没有生效过**：全仓没有一处把 ``custom_fields`` 应用出去
    （只有设置页的一对输入框与配置白名单），所以这次迁移保住的是**用户填过的意图**，
    而不是既有行为。迁法：``name`` → label、``value`` → ``default_value``（抓取补空用），
    key 由 name 派生。

    跑完把该键从 settings.json 覆盖层里删掉（配置项下线）：保存端点是**段级合并**
    （``{**旧段, **新段}``），不主动清就会一直留在盘上。

    返回新建的 key 列表；同 key 已存在（含垃圾桶条目）则跳过。
    """
    mf = ((cfg or {}).get("metadata_fetch") or {})
    created: list = []
    for item in (mf.get("custom_fields") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = slug(name)
        if db.custom_field_by_key(key):
            continue
        db.create_custom_field(
            key=key, label=name, type="text",
            default_value=str(item.get("value") or ""),
        )
        created.append(key)
    drop_legacy_override()
    return created


def drop_legacy_override() -> bool:
    """把 settings.json 覆盖层里的 ``metadata_fetch.custom_fields`` 删掉（有才写盘）。

    第 120 期：走 ``config.mutate_overrides``（锁内读—改—写 + 原子落盘）。
    「先 load 判空、再 save」这种做法在并发保存时会把这期间别处写进去的键抹掉。
    没有要删的键时**连盘都不碰**（这条路径会在迁移里被反复调用）。
    """
    mf0 = config.load_overrides().get("metadata_fetch")
    if not isinstance(mf0, dict) or "custom_fields" not in mf0:
        return False
    dropped = False

    def _merge(ov: dict) -> None:
        nonlocal dropped
        mf = ov.get("metadata_fetch")
        if not isinstance(mf, dict) or "custom_fields" not in mf:
            return
        mf.pop("custom_fields", None)
        dropped = True

    config.mutate_overrides(_merge)
    return dropped
