"""前端单测护栏自身的契约（第 39 期）。

第 39 期给前端立了第一套单测（vitest + @vue/test-utils）。但**护栏本身也会被拆掉** ——
删掉 npm script、把配置块挪走、或者把 `ChartGrid` 那条编译期类型标注放宽，
都能让护栏悄悄失效，而 `pytest` 与 `npm run test:unit` 两边都不会报错。

所以这里钉的不是「某个功能对不对」，而是「**护栏还在不在**」。

## 为什么是纯文本断言，而不是从 pytest 里调 `npx vitest`

本仓库的硬前提是**全量测试离线**。从 pytest 里拉子进程跑 node 会破坏它；
退一步写成「有 node 才跑、没有就 skip」则更糟 —— 那是一个**永远绿**的假交互，
比没有测试更误导人。故两边各管各的：前端 spec 由 `npm run test:unit` 跑，这里只静态核对。

## 为什么不重复断言 `ChartGrid` 的「id 都有组件」

那条不变式是**编译期**的：`StatisticsChartId = keyof typeof STATISTICS_CHART_META`
（`lib/statistics-charts.ts`），于是 `Record<StatisticsChartId, Component>` 里少一个 id
**直接编译失败**。再写运行期断言只是把 `npm run type-check` 重做一遍，且更弱。
真正的回归风险是**有人把这条标注放宽**（比如改成 `Record<string, Component>`）——
那会让编译期保护失效却依然能构建通过。所以这里钉的是**标注本身**。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PKG_JSON = FRONTEND / "package.json"
VITE_CONFIG = FRONTEND / "vite.config.ts"
CHART_GRID = FRONTEND / "src" / "components" / "charts" / "ChartGrid.vue"
STATISTICS_CHARTS = FRONTEND / "src" / "lib" / "statistics-charts.ts"

#: 第 39 期的三个 devDependency。少任何一个，`npm run test:unit` 都跑不起来。
REQUIRED_DEV_DEPS = ("vitest", "@vue/test-utils", "happy-dom")

#: 本期立的前端 spec。每个都必须真的存在**且含至少一个用例** ——
#: 空文件同样会让 `vitest run` 报绿。
EXPECTED_SPECS = (
    "src/views/ReaderView.spec.ts",
    "src/stores/library.spec.ts",
    # 第 40 期：阅读阈值是「全前端唯一的判定入口」，它的行为由这条 spec 兜住
    "src/lib/readingThresholds.spec.ts",
    # 第 40 期：新建向导。「立即创建」必须**真的建库**（不是只关浮层），这条 spec 兜住
    "src/components/tools/LibraryWizard.spec.ts",
    # 第 40 期：路径判据（向导与编辑弹窗共用一份）。原来两处各写一遍 `startsWith('/')`，
    # Windows 上把 `C:\…` 判成非绝对 ⇒ 向导卡在第 2 步。
    "src/lib/paths.spec.ts",
    # 第 43 期：书架首字母分桶（跳转条的唯一判据源）。分错桶不会报错、只是跳错位置，
    # 故用 spec 把「拉丁按首字 / 非拉丁归 # / 桶序升序」钉死。
    "src/lib/shelfBuckets.spec.ts",
    # 第 63 期：详情页此前**零测试**。重做时修掉两个 bug（概览里那个挂错地方的 `v-else`、
    # 面包屑读全局 `shelfTitle`），两条都不是崩溃型 —— 页面照常渲染，只是多一块 / 显示
    # 上一次导航的标题。没有 spec 的话下次重排还会原样长回来。
    "src/views/BookDetailView.spec.ts",
    # 第 63 期：会话边界是「一次连续阅读 = 数据库里一行」这条契约的**唯一**执行处，
    # 而它的失效方式全是静默的 —— 少算一段时长、把上一本书的秒数记到下一本头上、
    # 切后台那一刻吞掉最多 30 秒。三种都不会报错，只是日志页上的数字偏小/串行。
    "src/lib/readingSession.spec.ts",
    # 第 63 期：这本书的「阅读日志」标签（详情页第 7 个）。它同时是三条纪律的交汇处，
    # 每条都有一族静默失效方式：把「没记录」渲染成「读了 00:00」、把 `change: null`
    # 写成伪造的 0%、拿会话去闸重读轮次（于是那块凭空消失）。
    "src/components/book/detail/ReadingLogTab.spec.ts",
    # 第 63 期：阅读速度判据从 `/log` 页抽出来，详情页与它**共用同一份**。抽之前是两处
    # 各写一遍 —— 那种情况下「哪一处算错了」不会有任何提示，只会两边数字对不上。
    "src/lib/readingPace.spec.ts",
    # 第 64 期：成品文件的下载地址。它是一个**纯字符串函数**，错了不抛异常、页面照常
    # 渲染、链接照常可点 —— 只是点下去 404，或下到另一个文件。三种静默失效（整串编码
    # 把 `/` 变 `%2F`、`#` 不编码被当成锚点、漏传 `library_id` 使基根退回 OUTPUT_DIR）
    # 都不会有任何提示，故用 spec 逐条钉住。
    "src/lib/downloadUrl.spec.ts",
    # 第 64 期：书卡 ⋮ 菜单的状态模块。三件事写错都不报错：两个面板一起亮（只是「有点怪」）、
    # 每张卡各挂一份 document 监听（功能完全正常，只有处理器数量悄悄涨）、点菜单项时
    # 面板先关掉而动作没执行（用户读成「点了没反应」）。
    "src/lib/bookMenu.spec.ts",
    # 第 64 期：⋮ 菜单的**哪些项出现**。菜单里多一项 / 少一项都不会报错，只是用户点下去
    # 才发现「进了个打不开的阅读器」或「本来能下的书没有下载入口」。故用格式矩阵钉死
    # EPUB / TXT / AUDIO / MOBI 四种情况，并钉住删除确认的文案与「取消就一个请求都不发」。
    "src/components/book/BookActionsMenu.spec.ts",
    # 第 64 期：书架的**接线**。这一页此前零 spec，而本期在它身上动了三处（网格卡结构重构
    # + 三个视图各接一个 ⋮）。漏接一个视图 ⇒ 那个视图里没有入口，用户只会以为「这个视图
    # 不支持」；系列折叠行误接上 ⋮ ⇒ 点下去会删掉整个系列。核心断言是触发器**数量**。
    "src/views/ShelfView.spec.ts",
    # 第 64 期：快速预览浮层。两条契约写错都只会悄悄给错信息：详情拉失败时把整块内容换成
    # 错误页（把真数据说成「没有」）或照常写「0 章」（把「没拿到」说成「没有」）；
    # 以及给 AUDIO 发一个没有可下文件的「下载」。
    "src/components/book/BookPreviewDialog.spec.ts",
)


def _pkg() -> dict:
    return json.loads(PKG_JSON.read_text(encoding="utf-8"))


def test_前端单测脚本存在且口径正确():
    """脚本名是 `test:unit`，**不是** `test`。

    本仓库说的「测试」历来专指 pytest 那 632 例；把前端单测也叫 `test`
    会让「跑一下测试」这句话失去唯一含义，基线数字也会被混着算。
    """
    scripts = _pkg().get("scripts", {})
    assert "test:unit" in scripts, (
        "package.json 缺 `test:unit` 脚本 —— 前端护栏没有入口了。"
        f"现有脚本：{sorted(scripts)}"
    )
    assert scripts["test:unit"] == "vitest run", (
        f"`test:unit` 必须是 `vitest run`（跑完即退，不进 watch），实际是 {scripts['test:unit']!r}"
    )


def test_三个前端测试依赖都在_devDependencies():
    dev = _pkg().get("devDependencies", {})
    missing = [d for d in REQUIRED_DEV_DEPS if d not in dev]
    assert not missing, f"package.json 的 devDependencies 缺：{missing}"


def test_vite_config_承载_vitest_配置():
    """vitest 配置写在 `vite.config.ts` 里，**不另起 `vitest.config.ts`**。

    理由：`vite.config.ts` 的 `resolve.alias['@']` 是本仓库**唯一**的 `@` 定义，
    另起一个配置文件就得把它复制一份 —— 那正是本仓库一直在避免的「两处各写一遍」。
    """
    cfg = VITE_CONFIG.read_text(encoding="utf-8")
    assert 'reference types="vitest/config"' in cfg, (
        "vite.config.ts 顶部缺 `/// <reference types=\"vitest/config\" />` —— "
        "没有它 `defineConfig` 不认 `test` 字段"
    )
    assert re.search(r"\btest:\s*\{", cfg), "vite.config.ts 里找不到 `test:` 配置块"
    assert "environment: 'happy-dom'" in cfg or 'environment: "happy-dom"' in cfg, (
        "test 块里没有 environment: 'happy-dom'"
    )
    assert "include:" in cfg, "test 块里没有 include（会把非 spec 文件也当用例收）"
    assert not (FRONTEND / "vitest.config.ts").exists(), (
        "出现了 vitest.config.ts —— 会把 `@` 别名复制成第二份真值源"
    )


def test_前端_spec_文件存在且不是空壳():
    for rel in EXPECTED_SPECS:
        p = FRONTEND / rel
        assert p.exists(), f"前端 spec 缺失：{rel}"
        body = p.read_text(encoding="utf-8")
        assert re.search(r"\b(it|test)\(", body), (
            f"{rel} 里没有任何 `it(` / `test(` —— 空壳 spec 同样会让 vitest 报绿"
        )


def test_书架三个视图各留了一个菜单入口():
    """`ShelfView.vue` 里 `<BookActionsMenu` 必须**正好 3 处**（网格 / 列表 / 表格各一）。

    为什么用源码计数而不是只靠 `ShelfView.spec.ts` 的数量断言：那三条用例是
    「mount 起来数触发器」，**漏接一个视图时它数的是另外两个视图**——
    三处都漏了才会红，漏一处时它是绿的（渲染出来的那一处照样有 ⋮）。
    计数是唯一能一眼看出「少了一处」的判据。多出来（第 4 处）同样要拦：
    多接一处意味着某处被渲染了两遍，两个 ⋮ 会互相串开。
    """
    view = FRONTEND / "src" / "views" / "ShelfView.vue"
    body = view.read_text(encoding="utf-8")
    n = len(re.findall(r"<BookActionsMenu\b", body))
    assert n == 3, (
        f"ShelfView.vue 里 `<BookActionsMenu` 出现 {n} 次，应为 3 次（网格 / 列表 / 表格各一）—— "
        "少一处则那个视图里没有 ⋮ 入口（用户只会以为「这个视图不支持」）"
    )


def test_菜单里没有通过电子邮件发送这一项():
    """用户明确不做这一项（第 64 期决策 3，逐字：「通过电子邮件发送不勾」）。

    这条不是「还没做」，是**决定不做** —— 上游截图里有这一项，后人照着图补齐时
    最顺手的做法就是把它加回来。加回来意味着一个真实的发信动作，
    而本项目**没有任何邮件配置**，点了只会失败。
    灰置也不行：灰置等于承认「本该有但不给你」，比没有更糟。
    """
    menu = FRONTEND / "src" / "components" / "book" / "BookActionsMenu.vue"
    body = menu.read_text(encoding="utf-8")
    # 只看 `<template>`（用户看得见的那半边）：`<script>` 顶部的注释**正是**在记录
    # 「这一项不做」这个决策，把它一起禁掉等于禁止后人写下理由
    tpl = body[body.index("<template>") :]
    low = tpl.lower()
    assert "邮件" not in tpl and "email" not in low and "mail" not in low, (
        "BookActionsMenu.vue 的模板里出现了邮件相关项 —— 第 64 期决策是「不做」，"
        "本项目没有邮件配置，这一项点下去只会失败"
    )


def test_chartgrid_的编译期穷尽性标注还在():
    """`Record<StatisticsChartId, Component>` 是「忘登记组件」的唯一防线。

    放宽成 `Record<string, Component>` 后，少登记一个 id 不再编译失败，
    而 tile 的 `<div>` 照占栅格、里面什么都没有 —— 第 33 期修掉的那个静默空白会回来。
    """
    grid = CHART_GRID.read_text(encoding="utf-8")
    assert re.search(r"Record<\s*StatisticsChartId\s*,\s*Component\s*>", grid), (
        "ChartGrid.vue 的 `Record<StatisticsChartId, Component>` 标注被改了 —— "
        "编译期穷尽性保护失效"
    )
    charts = STATISTICS_CHARTS.read_text(encoding="utf-8")
    assert re.search(r"type\s+StatisticsChartId\s*=\s*keyof\s+typeof\s+STATISTICS_CHART_META", charts), (
        "`StatisticsChartId` 不再由目录的键推导 —— ChartGrid 那条 Record 就兜不住了"
    )
