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
SRC = FRONTEND / "src"
PKG_JSON = FRONTEND / "package.json"
VITE_CONFIG = FRONTEND / "vite.config.ts"
CHART_GRID = SRC / "components" / "charts" / "ChartGrid.vue"
STATISTICS_CHARTS = SRC / "lib" / "statistics-charts.ts"
ICONS_TS = SRC / "lib" / "icons.ts"

#: 第 39 期的三个 devDependency。少任何一个，`npm run test:unit` 都跑不起来。
REQUIRED_DEV_DEPS = ("vitest", "@vue/test-utils", "happy-dom")

#: 本期立的前端 spec。每个都必须真的存在**且含至少一个用例** ——
#: 空文件同样会让 `vitest run` 报绿。
EXPECTED_SPECS = (
    "src/views/ReaderView.spec.ts",
    "src/stores/library.spec.ts",
    # 第 40 期：阅读阈值是「全前端唯一的判定入口」，它的行为由这条 spec 兜住
    "src/lib/readingThresholds.spec.ts",
    # 第 86 期：书源列表的统计 / 筛选 / 排序（sources-ui 增强 A~D 的判据源）。
    # ⚠️ 不登记就等于「它可以被悄悄删掉」—— 这张表就是本仓防回潮的方式。
    # 最该保住的一条：统计条上的数字 = 点它筛出来的条数（不一致时界面在骗用户）。
    "src/lib/sourceFilter.spec.ts",
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
    # 第 65 期：侧栏结构（七个入口搬去顶栏、新增收书目录）。三种走样都是静默的：
    # 少一项 ⇒ 入口凭空消失；多一项 ⇒ 同一页两个入口（都能走，于是没人发现多了一条）；
    # 图标名拼错 ⇒ `iconPath()` 返回空串，渲染出看不见的空 <svg>。
    "src/data/nav.spec.ts",
    # 第 65 期：侧栏的**接线**。这一页此前零 spec，而本期在它身上动了三处（删七项、
    # 加收书目录、删 `'running'` 计数分支），每处的失效方式都不会报错。
    "src/components/AppSidebar.spec.ts",
    # 第 65 期：顶栏图标行的**接线**（七个入口搬到这里），该组件此前零 spec。
    # 四种走样全是静默的：少挂一个入口 ⇒ 那个页面从顶栏消失，用户只当「功能没了」；
    # 路径写错 ⇒ 点下去是 404 白页；成就门控判据写反 ⇒ 关掉开关反而显示、或读不到
    # 配置就整块消失；退回抽屉写法 ⇒ 浮层与全屏遮罩叠成两层。
    "src/components/AppHeader.spec.ts",
    # 第 65 期：任务面板从右侧抽屉改成顶栏浮层。两条契约写错都不会报错：
    # 角标改回「全部任务数」——数字照跳，只是含了已完成、越滚越大没人察觉；
    # 打开时不 `refresh()`——浮层照开，只是显示上一次拉到的旧数据。
    "src/components/TaskFlyout.spec.ts",
    # 第 65 期：收书目录页此前零 spec，而它当时是**坏的**（同一条 v-if 链里两个
    # 分支条件逐字相同 ⇒ 条目行永不渲染，页面上只像「还没有文件」）。这条 spec
    # 的核心断言就是条目行的条数；另钉住「批量条与条目行同时在场」与改名换 id 后
    # 选择集里不许留下幽灵 id。
    "src/views/settings/pages/BookDockPage.spec.ts",
    # 第 82 期：仪表盘改造的三个纯函数 / 封装。三种走样全是静默的：
    # 分带与行数收敛算错 ⇒ 书架行只是「渲染错位」，不报错；问候语分段错一个时段 ⇒
    # 早上显示「晚上好」，没人会发现；数据态优先级写反 ⇒ 把「失败」渲染成「空」。
    "src/lib/shelfRows.spec.ts",
    "src/lib/dashboardGreeting.spec.ts",
    "src/composables/useWidgetState.spec.ts",
    # 第 83 期：书架行的「库范围」筛选。它的失效方式是**静默的** —— 空数组代表「全部书库」，
    # 一旦写成「空 = 什么都不显示」，用户删库或库列表尚未加载回来时整行封面会凭空消失，
    # 而界面上没有任何东西能解释为什么。故用 spec 逐条钉住四种退化路径。
    "src/lib/shelfScope.spec.ts",
    # 第 83 期：删书流程（书卡 ⋮ 菜单与快速预览浮层共用）。写错全是静默的：没有兄弟却说
    # 「其它格式不会被删」、有兄弟却漏说、三份里有一份移不动却报「已移入回收站」
    # （静默的部分成功比失败更糟）。
    "src/lib/bookDelete.spec.ts",
    # 第 83 期：自定义面板的「库范围」勾选区。这一条是**界面冒烟实测抓到的真缺陷**：
    # checkbox 是受控的（`:checked` + `@change`），而「取消最后一个勾选」那条路径**故意
    # 不改 store**（拒绝）⇒ Vue 不重渲染 ⇒ 浏览器翻过去的原生勾选态留在原地。用户看到
    # 「未勾选 + 标题还写着「1 个书库」」，而且再点一下会变成**选中**（方向反了）。
    # ⇒ 拒绝时必须把 `input.checked` 翻回去；不测就会静默回归。
    "src/components/dashboard/DashboardSettingsSheet.spec.ts",
    # 第 84 期：更新页的「自动更新状态卡」。默认不挂 docker.sock ⇒ 自动更新开关默认不生效，
    # 页面上必须如实说「不可用」与「怎么才能用」，否则用户对着一个看似能开的开关一直等；
    # 失败改退避重试后，失败原因与下次重试时间也必须显示（否则永远不知道会不会再升上去）。
    "src/views/settings/pages/UpdatePage.spec.ts",
    # 第 84 期：维护页 UPDATES 分组的对照归置。上游那条 «Check for updates» 本项目第 78 期
    # 即已实现，仓内对照却记成「未实现」⇒ 属对照走样。这条钉住「改成了已实现 + 跳转」，
    # 并反向钉住「IMPORT / RECOMMENDATIONS 仍留在未支持卡里」（过滤不能过度）。
    "src/views/settings/pages/MaintenancePage.spec.ts",
    # 第 85 期：目录的「段」——卷 / 卷前 / 卷尾 / 正文。这一层的三种走样全是**静默**的：
    # 位置算错 ⇒ 点目录跳错章；空卷名回落成「目录」⇒ 看着像重复标题；段 key 用段名 ⇒
    # 背靠背的两个无名段互相串折叠。分组与段名是唯一真值源（两处目录共用），故单独钉住。
    "src/lib/chapterGroups.spec.ts",
    "src/components/book/detail/ChaptersTab.spec.ts",
    # 第 85 期批次 B：「目录来源」是**出网**的入口，钉的是「不骗人」——
    # 不可用/未验证要如实标注且按钮点不动；失败要显示原因原文，并且**照样刷新**
    # （负结果同样落库，不刷新就只剩「点了没反应」）。
    "src/components/book/detail/TocSourceCard.spec.ts",
    # 第 88 期：请求健壮性（超时 / 网络错 / 4xx / 5xx 的区分 + 只对 GET 的一次重试）。
    # 这些失效全是**静默**的：超时不生效只是「转圈更久」；写操作被误重试会造成重复副作用
    # 却不报错；调用方取消被误报成超时会让探索页把「我自己取消的旧检索」当失败弹 toast。
    "src/lib/apiRequest.spec.ts",
    # 第 88 期：书库落地页的**加载 / 失败 / 空 三态**。改造前加载期没有任何反馈、
    # 且失败被同一段空态吞掉（「这个书架还是空的」）—— 两种都在**谎报数据状态**，
    # 都不会报错、只会把人往错的方向引。故用 spec 把「三态互斥」钉死。
    "src/views/ShelfView.states.spec.ts",
    # 第 88 期 C 批：书库列表的**分页 / 无限滚动**（`loadBooks` 改为「拉首页」+ `loadMoreBooks`）。
    # 失效方式全是**静默**的：累计少一页只是少几十本；去重没做只是同一本书两张卡；
    # `hasMore` 边界写错只是「能点却拉不到」或「没拉完就停」；续拉失败置 `loaded` 会让
    # 之后永远短路；排序 / 筛选不重置续拉预算会让新筛选永远找不到排在后面的书。
    # 哪一种都不报错，故单独钉住。
    "src/stores/libraryPagination.spec.ts",
    # 第 89 期：上传本地书（收书目录投递）。`POST /convert` 回的是**文件流**，老实现却
    # 用 `request()` 解析 JSON ⇒ 把文件字节按 UTF-8 解出 `�`、抛 `Unexpected token '�'`，
    # 让一次**已经成功**的上传显示成失败。这条失效完全静默（书其实入库了），却最容易被
    # 用户当成「格式不支持 / 上传坏了」，故单独钉住「响应非 JSON 也算成功」。
    "src/lib/convertUpload.spec.ts",
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


def test_收书目录的条目行没有被重复的_v_else_if_顶掉():
    """`BookDockPage.vue` 里 `v-else-if="dock && dock.items.length"` 必须只出现 **1 次**。

    第 65 期 3/5 修掉的就是这条：批量操作条与条目行各写了一遍**逐字相同**的条件，
    `v-if` 链里第一个命中的就终止了，于是后一个分支永不渲染 —— 条目行一条都不显示，
    而复选框长在条目行里，「批量重扫 / 批量忽略」永远禁用、单条按钮点不到。
    页面上看不出异常，只像「投递目录里还没有文件」。

    `BookDockPage.spec.ts` 测的是「渲染出来是几条」，它证明不了**为什么**少；
    而且这类死链是**回归型**的：合并之后有人再拆成两块、条件一复制就又踩一遍。
    计数是唯一一眼可辨的判据（照 `test_书架三个视图各留了一个菜单入口` 的先例）。
    """
    p = FRONTEND / "src" / "views" / "settings" / "pages" / "BookDockPage.vue"
    # ⚠️ 先剥掉 HTML 注释再数：这段代码的注释里**逐字引用**了原条件（用来说明它为什么
    # 被合并），不剥的话注释本身会被数成一个「重复分支」—— 判据被自己的说明绊倒。
    body = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S)
    n = body.count('v-else-if="dock && dock.items.length"')
    assert n == 1, (
        f"BookDockPage.vue 里 `v-else-if=\"dock && dock.items.length\"` 出现 {n} 次，应为 1 次 —— "
        "同一条件写两遍会让后一个分支永不渲染（条目行消失、批量按钮永远禁用），"
        "而页面上只像「投递目录里还没有文件」"
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


# ---------------------------------------------------------------------------
# 图标表（第 65 期）
# ---------------------------------------------------------------------------

#: 收图标名的组件（全仓普查过：`<Icon name="…">` 与 `<EmptyState icon="…">`，
#: 2026-09-27 无第三个宿主）。加新宿主时**必须**加进这里，别放宽成「跳过」。
ICON_HOSTS = ("Icon", "EmptyState")


def _icons_body() -> str:
    src = ICONS_TS.read_text(encoding="utf-8")
    return src[src.index("export const ICONS = {") : src.index("} as const")]


def test_模板里的图标名都在_ICONS_表里():
    """字面量的图标名必须都在表里 —— 这是两个**既存真 bug** 的根因防线。

    `iconPath()` 对未知键**静默返回空串**（`icons.ts` 末行，沿袭 v2 的
    `ICONS[name] || ''`）⇒ 名字拼错（或写了表里没有的图形）会渲染成一个
    **看不见的空 `<svg>`**：不报错、不告警、不占位，页面上就是缺一块。
    第 65 期就是这么发现 `upload` 与 `folder` 两个键从来没有过的
    （`BookDockPage` 的拖拽遮罩大图标、书库向导的文件夹图标，一直是隐形的）。

    ⚠️ 只扫**字面量**。`<Icon :name="item.icon">` 这类动态绑定静态扫不到 ——
    它们由各自的数据源负责（侧栏那条见 `src/data/nav.spec.ts` 里对着
    真实 NAV_GROUPS 跑的那一遍）。
    """
    known = set(re.findall(r"^\s{2}([A-Za-z][\w]*):\s*'", _icons_body(), flags=re.M))
    assert known, "从 icons.ts 里一个图标键都没解析出来 —— 表的结构变了，这条断言已失效"
    # ⚠️ 正则有三个**必须**的细节，少一个就会漏扫（都是实测出来的）：
    #   · `[^>]*?` —— 允许 `icon=` 前面还有别的属性。写死成 `<Icon\s+icon=` 会漏掉
    #     `<EmptyState v-else icon="upload">` 这种（本项目真有，且正好是隐形那处）；
    #   · `(?<!:)`  —— 排除 `:name="…"` / `:icon="…"` 这些**动态绑定**：它们的值
    #     是表达式（如 `:name="target.label === '收听' ? 'volume' : 'book'"`），
    #     照字面抓下来必然误报；
    #   · `[^>]` 不跨 `>` —— 保证只在本标签内找，不会把上一个标签的属性算进来。
    pattern = re.compile(r"<(%s)\b[^>]*?(?<!:)\b(?:name|icon)=\"([^\"]+)\"" % "|".join(ICON_HOSTS))
    bad: list[str] = []
    for p in sorted(SRC.rglob("*.vue")):
        for m in pattern.finditer(p.read_text(encoding="utf-8")):
            if m.group(2) not in known:
                bad.append(f"{p.relative_to(FRONTEND).as_posix()} → <{m.group(1)} {m.group(2)}>")
    assert not bad, (
        "这些图标名不在 ICONS 表里（渲染出来是看不见的空 svg）：\n  " + "\n  ".join(bad)
    )


def test_每个图标都有非空的_path():
    """加了键但值是空串，与「键不存在」渲染出来是同一个东西 —— 都是空白。

    这条守的是「补图标时抄了个空壳」这种半途而废。
    """
    empty = [
        name
        for name, path in re.findall(r"^\s{2}([A-Za-z][\w]*):\s*'([^']*)'", _icons_body(), flags=re.M)
        if not path.strip()
    ]
    assert not empty, f"这些图标的 path 是空的（渲染出来是看不见的空 svg）：{empty}"


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
