"""工具页外壳（`ToolsLayout.vue`）的窄屏布局契约（第 92 期）。

## 为什么需要这个文件

工具页在 360 档曾长期带 `off=16` 的横向越界（`.codebuddy/tools/ui-smoke.ps1` 的
`off` = 有尺寸的交互元素里 `rect` 越出视口的个数）。根因是**两处外壳自身**的写法，
而不是某个工具视图写错了：

1. 内容区 `overflow-x-auto` + `min-w-[32rem]`（512px）—— 360 档内容盒只有 ~336px，
   剩下一百多像素**常驻在视口外**，用户得横向滚才看得到表单右半。
2. 标签条 `overflow-x-auto`：8 个标签合计约 672px，768 档（侧栏展开 240）内容盒
   只有 ~492px，尾部标签被滚出视口。

两者的失效方式都是**静默**的：`ovf` 永远是 `false`（滚动容器把溢出吸收掉了），
页面照常渲染、不报错、测试也全绿 —— 只有真拿 360 档量一次才看得见。
所以这里钉的不是「布局好不好看」，而是**这三条写法不许长回来**。

## 为什么是纯文本断言

与 `tests/test_frontend_unit_contract.py` 同一取向：**全量测试离线**，不从 pytest 拉
子进程跑 node；而「有没有横向溢出」本质是**排版引擎**的结论，happy-dom 量不出来。
真正能静态钉住的是「用了哪几个类」——而这次的回归恰恰就是「有人把类改回去」。

⚠️ 断言前**必须先剥 HTML 注释**：`ToolsLayout.vue` 的模板注释**正在**解释
「这里曾经是 `min-w-[32rem]` + `overflow-x-auto`」，不剥的话判据会被自己的说明绊倒。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
TOOLS_LAYOUT = SRC / "views" / "tools" / "ToolsLayout.vue"
ROUTER = SRC / "router" / "index.ts"

#: 工具页的标签数（第 92 期实测为 8）。少一个都意味着有人把某个工具页从台账上摘掉了。
EXPECTED_SECTION_COUNT = 8


def _strip_html_comments(src: str) -> str:
    return re.sub(r"<!--.*?-->", "", src, flags=re.S)


def _div_class_with_attr(body: str, attr: str) -> str:
    """取带某个属性的 `<div>` 的 `class` 值（属性顺序按 `class` 在前）。"""
    m = re.search(r'<div\s+class="([^"]*)"\s+' + re.escape(attr), body, flags=re.S)
    assert m, f"`ToolsLayout.vue` 里找不到「class 在前、{attr} 在后」的 `<div>` —— 结构变了，这条断言已失效"
    return m.group(1)


def _div_class_with_marker(body: str, marker: str) -> str:
    """取 `class` 里含某个标记的 `<div>` 的 class 值（用于没有独立属性的那层）。"""
    hits = [c for c in re.findall(r'<div\s+class="([^"]*)"', body, flags=re.S) if marker in c]
    assert len(hits) == 1, (
        f"`ToolsLayout.vue` 里含 `{marker}` 的 `<div>` 有 {len(hits)} 个（应为 1）—— 结构变了，这条断言已失效"
    )
    return hits[0]


def _template() -> str:
    return _strip_html_comments(TOOLS_LAYOUT.read_text(encoding="utf-8"))


def test_工具页内容区不许再给最小宽度与横向滚动():
    """`min-w-[32rem]` + `overflow-x-auto` 是 360 档 `off` 的最大来源，不许长回来。

    为什么这条最容易复活：它是第 86 期为「极窄屏卡片被压成 12px、中文一字一行」加的
    **看起来很有道理**的兜底。但那个场景的前提（≤640px 时外壳仍常驻 240px 侧栏）
    第 90 期起已不存在 —— 侧栏在窄屏改成了抽屉。留着它的唯一效果就是
    「内容比视口宽，右侧常驻在视口外」。
    """
    body = _template()
    assert "min-w-[32rem]" not in body, (
        "`ToolsLayout.vue` 的内容区又出现了 `min-w-[32rem]` —— 360 档内容盒只有 ~336px，"
        "多出来的宽度会**常驻在视口外**（`ovf` 仍是 false，因为滚动容器把溢出吸收掉了，"
        "所以这条缺陷不会自己暴露）。窄屏自适应请改各工具视图自己的栅格 / 换行。"
    )
    assert "overflow-x-auto" not in body, (
        "`ToolsLayout.vue` 又出现了 `overflow-x-auto` —— 工具页外壳的两层（标签条 / 内容区）"
        "都不该有横向滚动：会把「元素在视口外」这一事实藏起来，"
        "`.codebuddy/tools/ui-smoke.ps1` 的 `off` 也就量不出真相。"
    )


def test_工具页标签条装不下时要换行而不是滚动():
    """8 个标签在 768 档装不进一行 —— 必须换行，不许横向滚动。

    换行是**惰性**的：位置够时（≥1024）渲染与单行逐字一致，所以宽屏视觉零改动。
    反过来，靠断点「到某档就换控件」算不准 —— 侧栏宽度用户可拖（224–480），
    固定断点猜不出还剩多少位置；`flex-wrap` 没有魔数。
    """
    cls = _div_class_with_attr(_template(), 'role="tablist"')
    assert "flex-wrap" in cls, (
        f"工具页标签条的 class 里没有 `flex-wrap`：{cls!r} —— 装不下就会横向溢出，"
        "尾部标签跑到视口外（768 档实测会丢 2 个）"
    )
    assert "overflow-x-auto" not in cls, f"标签条又回到了横向滚动：{cls!r}"


def test_工具页窄屏入口是一条下拉_而不是把标签藏起来():
    """窄屏（<640px）用下拉换页；宽屏用标签条。**两条路必须是同一份数据源。**

    第 91 期的教训：窄屏顶栏那 7 个入口是**唯一入口**，收进「更多」菜单时写错 `v-if`
    就变成「窄屏没法进设置」——静默、且要用户报上来才会发现。这里的下拉是**换控件**
    不是隐藏：8 个页一个不少，逐个可点。所以判据有两层：
    形态（下拉 / 标签条）与数据源（都来自 `visibleSections`）。

    ⚠️ 断点必须是 `sm`（40rem = 640px，与 `lib/viewport.ts` 的 `NARROW_QUERY` 同档）。
    写成 `md` / `lg` 会与全站「窄屏」的定义错开，变成**两份断点**。
    """
    body = _template()

    select_div_cls = _div_class_with_marker(body, "sm:hidden")
    assert "<select" in body and 'aria-label="工具"' in body, (
        "窄屏那一层没有渲染 `<select>` —— 8 个工具页在窄屏就没有入口了（静默失效："
        "只有真在手机上打开才会发现）"
    )
    tablist_cls = _div_class_with_attr(body, 'role="tablist"')
    assert "hidden" in tablist_cls.split() and "sm:flex" in tablist_cls.split(), (
        f"标签条那一层不是「默认隐藏、sm 起显示」：{tablist_cls!r}"
    )

    # 只许有一档断点：出现 md:/lg: 说明有人又按自己的屏幕调了一次
    for name, cls in (("窄屏下拉层", select_div_cls), ("标签条", tablist_cls)):
        stray = [p for p in ("md:", "lg:", "xl:") if p in cls]
        assert not stray, (
            f"{name} 的标志性 class 里出现了 {stray} —— 工具页头部的显隐只许用 `sm`（40rem），"
            "与 `lib/viewport.ts` 的 NARROW_QUERY 同档；混用第二档 = 两份「窄屏」定义"
        )

    # 数据源同一个：两处都渲染 `visibleSections`
    assert body.count("in visibleSections") == 2, (
        f"`visibleSections` 在模板里出现 {body.count('in visibleSections')} 次（应为 2：标签条 + 下拉）—— "
        "两条路各写一份列表就等于「换个宽度少几个入口」，而且不会有任何报错"
    )


def test_工具页每个标签都指向真实存在的路由():
    """`SECTIONS` 里的 `routeName` 必须在 `router/index.ts` 里真的注册过。

    改路由名时最容易漏掉这里：标签照常渲染、点了没反应（或直接跳到 404），
    控制台只有一条 vue-router 警告。数量也一并钉住 —— 工具页少一个入口
    往往是「有人顺手把某个能力摘了」。
    """
    layout = TOOLS_LAYOUT.read_text(encoding="utf-8")
    names = re.findall(r"routeName:\s*'([^']+)'", layout)
    assert len(names) == EXPECTED_SECTION_COUNT, (
        f"`SECTIONS` 解析出 {len(names)} 条（应为 {EXPECTED_SECTION_COUNT}）：{names} —— "
        "工具页入口数量变了。真有增减，请同批改 `docs/TODO.md` / roadmap 并更新这条常量"
    )
    assert len(set(names)) == len(names), f"`SECTIONS` 里有重复的 routeName：{names}"

    router = ROUTER.read_text(encoding="utf-8")
    registered = set(re.findall(r"name:\s*'([^']+)'", router))
    missing = [n for n in names if n not in registered]
    assert not missing, (
        f"工具页标签指向了 router 里不存在的路由名：{missing} —— "
        "标签照常渲染，点了要么没反应要么落到 404，且不会有测试报错"
    )
