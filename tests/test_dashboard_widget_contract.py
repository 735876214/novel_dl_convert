"""仪表盘部件清单契约（第 82 期立，第 83 期扩到 13 件）。

首页部件表的**唯一真值源**是 `frontend/src/data/dashboard.ts`：
`WidgetId`（联合类型，同时是 localStorage 的键）、`WIDGET_META`（顺序 + 宽度档）、
`WIDGET_IDS`、`IMPLEMENTED_WIDGET_IDS`、`DEFAULT_WIDGET_IDS`；
组件挂载在 `components/dashboard/widgets/registry.ts` 的 `IMPLEMENTED` 表。

这些表**互相引用但没有任何编译期约束**，而失真方式全是静默的：
  · `WIDGET_META` 里漏一条 ⇒ 新用户少一张卡、面板里也找不到它；
  · `WidgetId` 有、`WIDGET_META` 没有（或反之）⇒ 类型上「存在」但运行时不渲染；
  · `registry.IMPLEMENTED` 漏登记 ⇒ 卡片渲染成空壳（`component: null`），面板显示「待实现」；
  · `DEFAULT_WIDGET_IDS` 写了不存在的 id ⇒ 默认启用静默失效。

⚠️ 本项目的 id 规则（第 83 期定稿，别再漂移）：
**前 12 个 id 与上游 BookOrbit 的 `WIDGET_TYPE` 逐一对应、无增减无改名**（顺序也照上游
`widgetLayout` 表）；第 13 个 `reading-time` 是**本项目自开**的额外件 —— 上游的
`reading-rhythm` 本身就是「阅读时长」语义，而本项目把那个 id 落定成了「入库节奏」，
id 不可改名，于是另开一件把时长语义补回来。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
DATA = SRC / "data" / "dashboard.ts"
REGISTRY = SRC / "components" / "dashboard" / "widgets" / "registry.ts"
WIDGETS_DIR = SRC / "components" / "dashboard" / "widgets"
STORE = SRC / "stores" / "dashboard.ts"

#: 上游 BookOrbit 的 12 件（`packages/types/src/dashboard.ts` 的 `WIDGET_TYPE`），顺序照上游
#: `widgetLayout` 表的宽度档分配。**这 12 个是契约：不许增、不许减、不许改名。**
UPSTREAM_WIDGET_IDS = (
    "library-overview",
    "reading-goal",
    "reading-rhythm",
    "currently-reading",
    "reading-streak",
    "reading-dna",
    "monthly-challenge",
    "highlight-of-the-day",
    "neglected-gems",
    "diversity-score",
    "year-projection",
    "long-wait",
)

#: 本项目自开的额外件（第 83 期）
EXTRA_WIDGET_IDS = ("reading-time",)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _widget_id_union(src: str) -> list[str]:
    """`export type WidgetId = 'a' | 'b' | ...` 里的成员（按书写顺序）。"""
    block = re.search(r"export type WidgetId =([\s\S]*?)\n\n", src)
    assert block, "没找到 WidgetId 联合类型 —— 契约测试要跟着改"
    # 去掉行注释，免得注释里的 'xxx' 被当成成员
    body = "\n".join(line.split("//", 1)[0] for line in block.group(1).splitlines())
    return re.findall(r"'([^']+)'", body)


def _meta_ids(src: str) -> list[str]:
    """`WIDGET_META` 数组里逐条的 `id: 'xxx'`（按书写顺序）。"""
    block = re.search(r"export const WIDGET_META: WidgetMeta\[\] = \[([\s\S]*?)\n\]", src)
    assert block, "没找到 WIDGET_META —— 契约测试要跟着改"
    return re.findall(r"id:\s*'([^']+)'", block.group(1))


def _const_ids(src: str, name: str) -> list[str]:
    block = re.search(rf"export const {name}: WidgetId\[\] = \[([\s\S]*?)\]", src)
    assert block, f"没找到 {name} —— 契约测试要跟着改"
    return re.findall(r"'([^']+)'", block.group(1))


def test_部件清单是12件上游加1件自开():
    src = _read(DATA)
    union = _widget_id_union(src)
    meta = _meta_ids(src)

    assert union == list(UPSTREAM_WIDGET_IDS) + list(EXTRA_WIDGET_IDS), (
        "WidgetId 与「12 件上游 + 1 件自开」不符。\n"
        "⚠️ 上游那 12 个 id 是 localStorage 的键，**改名会让存量用户的偏好静默丢失**；\n"
        "要新增一律追加在末尾（顺序 = 新用户的默认展示顺序）。\n"
        f"现在是：{union}"
    )
    assert meta == union, (
        "WIDGET_META 的 id 与 WidgetId 联合类型不一致（顺序也要一致）：\n"
        f"WidgetId   = {union}\nWIDGET_META = {meta}"
    )


def test_集合常量与元信息一致():
    src = _read(DATA)
    ids = _widget_id_union(src)

    # 两个派生常量**不许另抄一份清单**（抄了就会与 WIDGET_META 漂移，且没人会发现）
    assert re.search(r"export const WIDGET_IDS: WidgetId\[\] = WIDGET_META\.map\(", src), (
        "WIDGET_IDS 必须由 WIDGET_META 派生"
    )
    assert re.search(r"export const IMPLEMENTED_WIDGET_IDS: WidgetId\[\] = \[\.\.\.WIDGET_IDS\]", src), (
        "IMPLEMENTED_WIDGET_IDS 现在应与 WIDGET_IDS 相同（13 件全部已实现）"
    )

    defaults = _const_ids(src, "DEFAULT_WIDGET_IDS")
    assert set(defaults) <= set(ids), f"默认启用里有不存在的 id：{set(defaults) - set(ids)}"
    # 第 83 期的决定：新增件**不默认开**（存量用户升级后不该凭空多出一张卡）
    assert "reading-time" not in defaults, "阅读时长是新增件，不许进默认启用集"


def test_registry为每个部件挂了真实组件():
    """`component: null` 的卡片会渲染成空壳、面板显示「待实现」—— 用契约拦住漏登记。"""
    src = _read(DATA)
    reg = _read(REGISTRY)
    ids = _widget_id_union(src)

    block = re.search(r"const IMPLEMENTED: Partial<Record<WidgetId, Component>> = \{([\s\S]*?)\n\}", reg)
    assert block, "没找到 registry 的 IMPLEMENTED 映射 —— 契约测试要跟着改"
    entries = dict(re.findall(r"'([^']+)':\s*([A-Za-z0-9_]+)", block.group(1)))

    missing = [i for i in ids if i not in entries]
    assert not missing, f"registry 漏登记：{missing}（卡片会渲染成空壳）"
    assert not set(entries) - set(ids), f"registry 有多余登记：{set(entries) - set(ids)}"

    # 每个登记名都要能解析到一个真实文件（防「import 名写错 / 组件被删」）
    imported = dict(re.findall(r"import\s+(\w+)\s+from\s+'\./([\w.]+\.vue)'", reg))
    for wid, comp in entries.items():
        assert comp in imported, f"{wid} 指向的组件 `{comp}` 没有对应的 import"
        assert (WIDGETS_DIR / imported[comp]).is_file(), f"{wid} 的组件文件不存在：{imported[comp]}"


def test_新增的阅读时长部件守既有约定():
    """第 13 件必须与其余 12 件同形：走 useWidgetState、不加壳、声明 size。"""
    src = _read(WIDGETS_DIR / "ReadingTimeWidget.vue")

    assert "useWidgetState" in src, "数据态判定必须走唯一真值源 useWidgetState"
    assert "WidgetSize" in src, "部件必须接收部件行下发的宽度档（对齐上游契约）"
    # 外壳（大圆角 + 主色描边 + 毛玻璃）由 DashboardWidgetRow 统一提供 —— 部件里再加一层就是双层壳
    assert "border-primary/40" not in src, "壳体归部件行，部件内部不许再加卡片外壳"
    # 真实数据源：/api/stats 的 reading_28d（近 N 天每日阅读秒数），不许另造接口或假数据
    assert "reading_28d" in src, "阅读时长的数据必须取自 /api/stats 的 reading_28d"


def test_库范围字段的默认补齐在store里():
    """`ShelfDef.library_ids` 是新字段：旧偏好必须由 `mergeShelves` 补默认（不写迁移脚本）。"""
    store = _read(STORE)
    assert "library_ids" in store, "store 要负责补 library_ids 默认值"
    assert "normalizeLibraryIds" in store, "库范围要经收敛函数（非字符串 / 重复项会被清掉）"
