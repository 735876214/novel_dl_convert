# 上游首页（Dashboard）样式对照基线 —— NovelForge 仪表盘 vs BookOrbit dashboard

> **本文件管什么**：把「本项目首页（`/` → 仪表盘）」与**上游 BookOrbit 首页**做一次逐区块的**样式 / 结构**对照，
> 给出四档判定（**已对齐 / 形态不同 / 缺失 / 待确认**）与改造优先级。
> ⚠️ **本文件只对照、不改代码** —— 它是第 82 期第一步的产物；第二步按 §5 的优先级逐项改造。
> 与既有 5 份 `bookorbit-*.md` 的分工：那 5 份按**能力 / 模块 / 设置 / 契约**对照，本文件专管**首页的样式与结构**。

---

## 0. 取回口径（可复现）

| 项 | 值 |
|---|---|
| 上游仓库 | `735876214/bookorbit`（public，默认分支 `main`） |
| **实测 commit** | `c292d6ccd2b5f32ffdc9368e907df76c383e94ea`（2026-09-18T16:32:18Z，`fix(metadata): honor configured Amazon domain in book links`） |
| 与既有基线的关系 | 与 `MEMORY-REF.md` 记的「`main @ c292d6cc`」**逐字一致** ⇒ 上游基线声明无需更新（自 v2.10.0 起未推进） |
| 取回方式 | 部分克隆 + 稀疏检出到 `%TEMP%`（**不入库、不进提交**）：`git clone --filter=blob:none --no-checkout --depth 1` → `sparse-checkout set client/src/features/dashboard client/src/views client/src/assets packages/types/src` → `checkout main` |
| 出网 | 本机直连 GitHub 会被 reset ⇒ 全程经本机代理 `127.0.0.1:7897`（`-c http.proxy=… -c https.proxy=…`，**未修改持久 git config**） |
| 实际检出的四个上游目录 | `client/src/features/dashboard`、`client/src/views`、`client/src/assets`、`packages/types/src` |

⚠️ **引用上游路径的写法约定（本文件硬约束）**：只写**路径**，不写 `路径:行号`。
理由：`tests/check_doc_anchors.py` 的 `EXTERNAL_PREFIXES` 只白名单了 `packages/`、`apps/`、`modules/`、`plugins/`、`scripts/`、`src/lib/`，
而上游首页文件的前缀是 **`client/`**，不在其中 ⇒ 写成锚点会被按**仓内路径**解析、判成「文件不存在」＝硬错。
需要指位置时写成「上游 `X.vue` 的第 N 行」（`MEMORY-REF.md` 已有此非锚点写法先例）。

---

## 1. 两侧文件清单

### 1.1 上游（首页相关）

| 类别 | 上游路径 |
|---|---|
| 页面 | `client/src/views/DashboardView.vue` |
| 壳组件 | `client/src/features/dashboard/components/DashboardWidgetRow.vue`、`DashboardScroller.vue`、`DashboardWelcome.vue`、`DashboardSettingsSheet.vue` |
| 12 件部件 | `client/src/features/dashboard/components/widgets/*.vue`（12 个） |
| 数据 composable | `client/src/features/dashboard/composables/useDashboardConfig.ts`、`useDashboardLabels.ts`、`useDashboardScroller.ts`、`useDashboardWidgets.ts`、`useWidgetData.ts`、`useDraggableList.ts` + 逐部件 data composable |
| 纯函数 | `client/src/features/dashboard/lib/greeting.ts`、`lib/shelf-rows.ts` |
| 接口 | `client/src/features/dashboard/api/dashboard-widget.api.ts`（`/api/v1/dashboard/widgets/batch`、`/api/v1/dashboard/scrollers/batch`） |
| 类型 | `packages/types/src/dashboard.ts` |
| 主题 token | `client/src/assets/theme/{tokens,accents,bridge,radius,cover-effects}.css` + 入口 `client/src/assets/main.css` |
| 截图 | `docs/images/dashboard-overview.png`（**对象库里有**；本轮稀疏检出未包含，见 §6 待确认 1） |

### 1.2 本项目

| 类别 | 本项目路径 |
|---|---|
| 页面 | `frontend/src/views/DashboardView.vue` |
| 壳组件 | `frontend/src/components/dashboard/` 的 `DashboardWidgetRow.vue`、`DashboardScroller.vue`、`DashboardWelcome.vue`、`DashboardSettingsSheet.vue`、`DashboardShelfRow.vue`、`FirstRunNotice.vue` |
| 12 件部件 | `frontend/src/components/dashboard/widgets/`（12 个 `*.vue` + `registry.ts`） |
| 标识与元信息 | `frontend/src/data/dashboard.ts`（`WidgetId` / `WidgetMeta` / `WIDGET_META` / `ShelfType` / `ShelfDef` / `MAX_SHELVES` / `DEFAULT_SHELVES` / `SCOPE_OPTIONS`） |
| 状态 | `frontend/src/stores/dashboard.ts`（Pinia，落 `localStorage`：`dashboard-widgets` / `dashboard-shelves`） |
| 主题 token | `frontend/src/assets/theme/{tokens,accents,bridge,radius,cover-effects}.css` + 入口 `frontend/src/assets/main.css` |
| 视觉口径 | `docs/DESIGN.md`（照搬上游 token、组件**禁写死颜色/圆角/阴影**） |

### 1.3 ⚠️ 一个必须先说清的命名陷阱

**两侧都有 `DashboardScroller.vue`，但职责完全不同**：

- 上游 `DashboardScroller.vue` = **一个书架行**（横向封面滚动 + 1..N 行分带 + 骨架 / 错误 / 空态）；
- 本项目 `frontend/src/components/dashboard/DashboardScroller.vue` = **页面级栅格容器**（14 行：`flex min-w-0 flex-col gap-6` + `<slot>`）；
- 本项目真正的书架行是 `frontend/src/components/dashboard/DashboardShelfRow.vue`。

⇒ §2.5 的比较对象是 **上游 `DashboardScroller.vue` ↔ 本项目 `DashboardShelfRow.vue`**；按文件名对会比较出完全错误的结论。

---

## 2. 逐区块对照

### 2.1 页面骨架与三态

| 维度 | 上游（`client/src/views/DashboardView.vue`） | 本项目（`frontend/src/views/DashboardView.vue`） |
|---|---|---|
| 状态机 | `libraryState` computed → `loading / error / empty / ready` **四分支** | **无整页状态机**；只有 `stats.error` 一条提示 + `dashboard.isEmpty` 空态 |
| loading | `role="status"` + `Loader2 class="animate-spin"` + `py-16 text-sm text-muted-foreground` | 无（部件各自退化成 0 / 空） |
| error | `role="alert"` 卡片：`max-w-md rounded-2xl border border-destructive/30 bg-card/30 px-8 py-12 text-center shadow-sm` + `AlertTriangle` + 重试按钮 `rounded-md bg-primary px-4 py-2 text-sm font-medium` | `Card padding="sm"` + `text-[12.5px] text-destructive` + `Button size="sm" variant="secondary"` 重试 |
| empty | `DashboardWelcome`（条件 = **0 个书库**） | `FirstRunNotice`（0 库）+ `DashboardWelcome`（**全部部件与书架被关**）——两件都在本项目 |
| 外层容器 | `<main class="relative flex-none">` → `div.space-y-5 pb-8 pt-4 sm:pr-2` | `DashboardScroller` → `div.flex min-w-0 flex-col gap-6` |
| 垂直间距 | `space-y-5`（1.25rem） | `gap-6`（1.5rem） |
| 页面内边距 | `pb-8 pt-4 sm:pr-2` | 无页面级 padding |
| 入场动效 | 问候语行 `animate-fade-up` + `animation-delay:40ms`；部件行整块 `animate-fade-up`；每个书架 `animate-fade-up` + `index*100ms` | 页面**未消费任何 `animate-*`**（`frontend/src/assets/main.css` 里有 `.animate-fade-up`，但仪表盘没用；只有图表组件在用） |
| 「全部书架隐藏」兜底 | 一行 `text-sm text-muted-foreground` + 「自定义」链接 | 由 `dashboard.isEmpty` 的 `DashboardWelcome` 承担 |
| 引导 | `useOnboardingTour().maybeStartTour`（`nextTick` + 500ms） | 无 |

**判定**：三态骨架 = **缺失**；入场动效 = **缺失**；容器间距/内边距 = **形态不同**。

### 2.2 问候语行 + 「自定义」入口

| 维度 | 上游 | 本项目 |
|---|---|---|
| 位置 | 页面内联一行（上游 `DashboardView.vue` 的第 122–140 行），`flex items-center justify-between gap-3 px-1` + `animate-fade-up` | **页面无问候语行**；入口是 `DashboardSettingsSheet.vue` 里的右下角悬浮按钮（FAB） |
| 问候文本 | `Sparkles` 图标 + `text-[1.05rem] font-medium tracking-[-0.01em] sm:text-[1.18rem]`，用户名 `ml-1 font-semibold text-primary` | 无 |
| 按钮外观 | `rounded-md border border-primary/40 bg-card/40 px-2 py-1.5 text-sm font-medium shadow-sm transition-colors hover:border-primary/70 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring`，标签 `hidden sm:inline` | FAB：`fixed right-6 bottom-6 z-40 h-11 w-11 rounded-full border border-border bg-card shadow-lg transition-transform hover:scale-105` |
| 数据 | `lib/greeting.ts` 按小时分段（night/morning/afternoon/evening）+ 用户时区；名字取 `name.split(/\s+/)[0]` | 无对应实现 |
| 文案机制 | `vue-i18n`（`views.dashboard.customize`） | 中文字面量「自定义仪表盘」 |

**判定**：问候语行 = **缺失**（上游首页最显眼的一行）；「自定义」入口 = **形态不同**（FAB vs 内联按钮）；文案机制 = **形态不同**（本项目**没有 i18n**，不算缺口）。

### 2.3 部件行 `DashboardWidgetRow`

| 维度 | 上游 | 本项目 |
|---|---|---|
| 布局 | 横向滚动：`flex gap-4 overflow-x-auto px-1 pb-1 pt-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden` | 响应式栅格：`grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-6` |
| 卡片尺寸 | 固定 `h-55`；宽 `w-[220px]`（1x1）/ `w-[336px]`（1x1.5），`shrink-0` | 无固定高；宽度由列跨度决定（`registry.ts` 的 `SIZE_SPAN`：`lg: col-span-6` / `md: col-span-3` / `sm: col-span-2`） |
| 尺寸模型 | 两档 `1x1` / `1x1.5` | 三档 `sm` / `md` / `lg`（`frontend/src/data/dashboard.ts` 的 `WidgetSize`） |
| 卡片外壳 | **在行组件上**：`group/card relative h-55 shrink-0 overflow-hidden rounded-2xl border border-primary/40 bg-card/30 shadow-sm backdrop-blur-[1px]` | **在各部件内部**：每件自带 `rounded-lg border border-border bg-card p-4 shadow-sm` |
| 圆角 / 边框 / 底色 | `rounded-2xl`（≈18px）/ `border-primary/40`（主色 40% 半透）/ `bg-card/30` + `backdrop-blur-[1px]` | `rounded-lg`（`--radius` = 10px）/ `border-border`（实心中性）/ `bg-card`（不透明、无毛玻璃） |
| 内边距 | 部件内容根 `flex h-full flex-col p-3` | `p-4` |
| 阴影 | `shadow-sm` | `shadow-sm`（**一致**） |
| 入场动效 | 每卡 `animation: dashboardWidgetFadeUp 0.35s ease both` + `index*80ms`（局部 keyframes，`translateY(10px)`） | 无 |
| 行内控件 | 悬停显现左右滚动按钮（`h-7 w-7 rounded-md`，`scrollBy(±300)`）+ 每卡拖拽手柄（`GripVertical`，`group-hover/card:opacity-100`） | 无滚动按钮、无卡上拖拽手柄（排序在设置面板里） |
| 排序 | `vue-draggable-plus` 的拖拽排序，落 PATCH 服务端 | 设置面板内原生 DnD + ▲▼ 按钮 |
| 数据机制 | `useDashboardWidgets()` 读 `user.settings.dashboardConfig` | `useDashboardStore()` 读 `localStorage` |

**判定**：部件清单与顺序 = **已对齐**（见 §2.4）；网格模型 = **形态不同**；卡片外壳 token = **形态不同**；拖拽排序 = **形态不同**（能力等价）；滚动按钮 / 拖拽手柄 / `dashboardWidgetFadeUp` = **缺失**。

### 2.4 十二件部件逐个对照

**先核对名单**：上游 `packages/types/src/dashboard.ts` 的 `WIDGET_TYPE` 与本项目 `frontend/src/data/dashboard.ts` 的 `WidgetId`
是**同一组 12 个 id 字符串**，逐一对应、**无增减、无改名**（`reading-streak` / `currently-reading` / `reading-goal` / `reading-dna` /
`monthly-challenge` / `highlight-of-the-day` / `neglected-gems` / `reading-rhythm` / `diversity-score` / `library-overview` /
`year-projection` / `long-wait`）。

| # | 部件 id | 上游文件（`client/src/features/dashboard/components/widgets/`） | 本项目文件（`frontend/src/components/dashboard/widgets/`） | 判定 | 差异要点（可核对的判据） |
|---|---|---|---|---|---|
| 1 | `reading-goal` | `ReadingGoalWidget.vue` | `ReadingGoalWidget.vue` | 形态不同 | 上游 `vue-echarts` 环形（`radius:['78%','100%']`，124×124）+ 服务端值；本项目 `ProgressRing :size=92 :thickness=9` + `localStorage` 键 `year-goal-target` |
| 2 | `currently-reading` | `CurrentlyReadingWidget.vue` | `CurrentlyReadingWidget.vue` | 形态不同 | 上游有封面缩略图（`BookCoverSurface size="mini"`）+ 悬停 `Play` 按钮；本项目无封面、`text-[12.5px]` 书名 + 右侧百分比 |
| 3 | `reading-streak` | `ReadingStreakWidget.vue` | `ReadingStreakWidget.vue` | 形态不同 | 上游 `Flame text-orange-500` + `text-3xl font-bold` + `Trophy` 最长连续 + `h-3 w-3` 点阵；本项目 `text-[24px]` 连续 + `h-2.5 w-2.5` 点阵，**无最长连续** |
| 4 | `reading-rhythm` | `ReadingRhythmWidget.vue` | `ReadingRhythmWidget.vue` | **形态不同，且语义不同** | 上游 = **阅读时长**（`readingSeconds`，h/m/s）与日均；本项目 = **入库数量**（`added_28d`，`/api/stats`），标题「入库节奏」（文件注释自陈「对应 BookOrbit 的 ReadingRhythmWidget」） |
| 5 | `reading-dna` | `ReadingDnaWidget.vue` | `ReadingDnaWidget.vue` | 形态不同 | 上游 **5 维** + `archetype` 引号标题 + 每维独立硬编码色（`bg-blue-500` / `bg-emerald-500` / …）；本项目 **4 维**（篇幅/多样性/节奏/时段）+ 统一 `bg-primary/80` |
| 6 | `monthly-challenge` | `MonthlyChallengeWidget.vue` | `MonthlyChallengeWidget.vue` | 形态不同 | 上游文本 + `h-2.5` 进度条 + `bg-green-500` 完成态；本项目 `h-1.5` 进度条 + `text-success` + **可编辑目标输入**（`localStorage` 键 `month-goal`） |
| 7 | `highlight-of-the-day` | `HighlightOfTheDayWidget.vue` | `HighlightOfTheDayWidget.vue` | 形态不同 | 上游 `blockquote border-l-2 border-primary/40 pl-3 text-xs italic` + `ExternalLink`；本项目按日期种子确定性抽取 + 颜色取自高亮色 + 「」引号 |
| 8 | `neglected-gems` | `NeglectedGemsWidget.vue` | `NeglectedGemsWidget.vue` | 形态不同 | 上游有封面 + `Star` 评分 + 「加入队列」/「换一本」两个按钮；本项目只有书名 + 作者 + 「已 N 天未继续」 |
| 9 | `diversity-score` | `DiversityScoreWidget.vue` | `DiversityScoreWidget.vue` | 形态不同 | 上游 `text-3xl font-bold` + 4 维（genre/author/era/language）`h-1.5 bg-primary/70`；本项目 `text-[20px]` + 4 维（作者/系列/格式/语言） |
| 10 | `year-projection` | `YearProjectionWidget.vue` | `YearProjectionWidget.vue` | 形态不同 | 上游 `text-3xl font-bold` + 趋势图标（`TrendingUp/Down/Minus`）+ 页数/小时两格；本项目 `text-[24px]` + 「按 X 本/天 推算」，无趋势图标 |
| 11 | `long-wait` | `LongWaitWidget.vue` | `LongWaitWidget.vue` | 形态不同 | 上游有封面（`h-24 w-18`）+ `text-2xl font-bold text-primary` 等待天数 + 「开始阅读」CTA；本项目只有书名/作者 + `text-[10.5px]`「已等待 N 天未读」 |
| 12 | `library-overview` | `LibraryOverviewWidget.vue` | `LibraryOverviewWidget.vue` | 形态不同 | 上游 `grid-cols-2` 四格（图标块 + `text-[15px] font-bold`）+「今年新增」胶囊；本项目四列可点 + 「近 28 天入库」胶囊 |

**跨 12 件的共性差异（全部成立）**：

1. **卡片外壳归属不同**：上游部件根节点是 `flex h-full flex-col p-3`（外壳在行组件上）；本项目每件自带 `rounded-lg border border-border bg-card p-4 shadow-sm`。
2. **骨架 / 错误分支**：上游每件都有 load/error/empty 三分支 + `animate-pulse` 骨架；本项目多数件无骨架、无 error 分支。
3. **配色纪律相反**：上游大量用 Tailwind 默认调色板硬编码（`text-orange-500` / `bg-green-500` / `bg-blue-500` / `fill-amber-400`）；
   本项目走**语义 token**（`bg-primary` / `text-success`）—— 这与 `docs/DESIGN.md` 禁止组件内硬编码颜色的口径一致，**本项目反而更守规**。
   ⇒ 改造时**不要**为了「像上游」而引入硬编码色。
4. **数据机制**：上游 = `useWidgetData()` + `/api/v1/dashboard/widgets/batch`（带重试退避）；本项目 = 既有 store（`useStatsStore` / `useLibraryStore` / `api.allAnnotations()`）直连既有接口。
   **本项目不引入 `/api/v1/dashboard/widgets/batch`**，数据由既有 store 提供（单用户直连 DB，无此接口层）。

### 2.5 书架行（上游 `DashboardScroller.vue` ↔ 本项目 `DashboardShelfRow.vue`）

| 维度 | 上游 | 本项目 |
|---|---|---|
| 可配置数量 | `MAX_SCROLLERS = 8`，默认 6 条 | `MAX_SHELVES = 6`，默认 3 条 |
| 类型域 | 7 种：`recently-added` / `continue-reading` / `continue-listening` / `want-to-read` / `up-next-in-series` / `random` / `smart-scope` | 4 种：`continue` / `recent` / `discover` / `scope` |
| 总布局 | `SHELF_LAYOUT` 二选一：`grid gap-5 xl:grid-cols-2` 或 `space-y-5` | 无 `shelfLayout`，恒单列 |
| 行数 | `rows` 1..3（`SHELF_ROW_OPTIONS` + `chunkIntoBands()`），窄屏压到 2 | 无 rows 概念，恒单行 |
| 行卡片外壳 | `section class="group/scroller overflow-hidden rounded-2xl border border-primary/40 bg-card/30 shadow-sm backdrop-blur-[1px]"` | `section class="min-w-0"`（**无边框/底色/圆角/阴影**） |
| 表头 | 图标块 `h-7 w-7 rounded-md border border-border bg-muted/50` + `text-[15px] font-bold` 标题 + 计数胶囊 `rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-bold tabular-nums` + 悬停显现滚动按钮（`scrollBy(±560)`） | `h2 text-[14px] font-semibold` + `text-[11px]`「N 本」 + 「查看全部」链接 |
| 封面卡 | `BookCoverCard`，`w-[120px]` / `w-[150px]`，封面入场 `dashboardFadeUp` + `index*35ms` | `BookCover`，固定 `w-[104px]`，无动画 |
| 交互 | `BookQuickView` / `AddToCollectionSheet` / `DeleteBookDialog` | 点封面进详情；「查看全部」进 `/shelf` |
| 加载/错误/空态 | 骨架 `SKELETONS_PER_BAND=8`；错误带 `RefreshCw` 重试；空态按 type 分文案 | 一行「这一行暂时没有书」 |
| 滚动条处理 | Tailwind 任意值 `[scrollbar-width:none] [&::-webkit-scrollbar]:hidden` | `main.css` 的 `no-scrollbar` 工具类（**语义等价，写法不同**） |
| 数据 | `/api/v1/dashboard/scrollers/batch`（`limit*rows` 上限 50） | `useLibraryStore()` 派生（`MAX_COVERS = 20`） |

**判定**：多行（1..3）+ 两列布局 `shelfLayout` = **缺失**；行卡片外壳 / 表头图标块与计数胶囊 / 滚动按钮 = **缺失**；骨架与错误重试 = **缺失**；可配置数量与类型域 = **形态不同**。

### 2.6 设置面板 `DashboardSettingsSheet` + 首启 / 空态

| 维度 | 上游（549 行） | 本项目（294 行） |
|---|---|---|
| 外壳 | shadcn `Sheet` / `SheetContent`（右侧，`sm:max-w-[480px]`） | 自绘 `<aside>`：`fixed right-0 top-0 z-50 w-[min(23rem,92vw)] border-l border-border bg-background shadow-2xl`，`transition-transform duration-220` |
| 打开方式 | 由页面问候语行的按钮 `v-model:open` 打开 | 面板自带右下 FAB + 遮罩 `bg-black/25 backdrop-blur-[2px]` |
| 头部 | `SheetHeader border-b px-5 py-4` + `SheetTitle text-base font-semibold` | `h-14 border-b px-4` + `text-[13.5px] font-semibold` |
| 分段控件 | `rounded-lg bg-muted p-1`，激活项 `bg-background shadow-sm` | 平铺按钮，激活项 `bg-muted` |
| **书架布局选择器（Rows3 / Columns2）** | **有**（`rounded-lg border p-3` 卡，激活 `border-primary bg-primary/5` + `aria-pressed`） | **无** |
| **书架行数控件（1/2/3）** | **有**（`data-testid="shelf-rows"` 分段） | **无** |
| **库范围筛选** | **有**（手风琴 + 逐库 checkbox + 全选 + 必选校验） | **无** |
| 书架类型选择 | `<select>`（7 类型）+ smart-scope 二级 select | 新增行时选类型（底部 chips），之后不可改 |
| 排序 | `useDraggableList`（HTML5 DnD）+ 桌面 `GripVertical` 手柄 / 触屏 ▲▼ | `useDndSort` + 常驻 ▲▼ 文本按钮 + 6 点 SVG 手柄 |
| 行容器 | `rounded-lg border border-border bg-card transition-all duration-150`；拖过 `border-primary/50 bg-primary/5 shadow-sm` | `mb-1.5 rounded-md border border-border bg-card px-2.5 py-2`；拖过 `border-primary` |
| 开关 | 自绘 `h-5 w-9 rounded-full border-2` + 白拇指 `translate-x-4/0` | `frontend/src/components/ui/Switch.vue`（全站唯一实现） |
| 底部 | `RotateCcw` 重置 + 「取消」+ 「保存」 | **只有**「恢复默认布局」 |
| 保存模型 | 草稿态 → 点「保存」才 PATCH 服务端 | 即时写 store → `localStorage`（无草稿、无保存按钮） |
| 文案机制 | `vue-i18n` 全量 key + `useDashboardLabels()` | 中文字面量 |

| 首启 / 空态 | 上游 | 本项目 |
|---|---|---|
| 文件 | `DashboardWelcome.vue` | `DashboardWelcome.vue` + `FirstRunNotice.vue`（**本项目多一件**） |
| 触发 | `libraryState === 'empty'`（0 个书库） | `FirstRunNotice` = 0 个书库；`DashboardWelcome` = 全部部件与书架被关 |
| 容器 | `max-w-md rounded-2xl border border-primary/40 bg-card/30 shadow-sm backdrop-blur-[1px]` + 内联 `radial-gradient(... color-mix(in oklch, var(--primary) 18%, transparent) ...)` 光晕 | `rounded-lg border-dashed border-border bg-card/50`（`FirstRunNotice` 是细条 `px-4 py-3`） |
| 图标 | `h-14 w-14 rounded-lg border border-border bg-background shadow-sm` + `BookOpen` / `Users` | 圆形 `bg-muted` / `bg-primary/10` + 本地 `Icon`（`dash` / `library`） |
| CTA | `rounded-md bg-primary px-5 py-2 text-sm font-medium` + `Plus`，打开建库弹窗 | 「恢复默认布局」/「新建书库」（`Button`） |
| 引导锚点 | `data-tour="welcome-card"`（配 `useOnboardingTour`） | 无 |

**判定**：外壳与保存模型 = **形态不同**；布局选择器 / 行数控件 / 库范围筛选 = **缺失**；首启卡片的圆角/半透底/光晕 = **形态不同**；onboarding tour = **缺失**。

---

## 3. 样式 token 层对照（五个主题文件）

| 文件 | 上游 | 本项目 | 同名 token 值 | 上游独有 | 本项目自造 |
|---|---|---|---|---|---|
| `tokens.css` | `client/src/assets/theme/tokens.css`（467 行） | `frontend/src/assets/theme/tokens.css`（412 行） | **全部一致**（`--tint-h` / `--radius` / `--elevation-*` / `--pill-*` / `--format-*` / `--pattern-*` / `--diff-*` / `--path-*` / `--audit-*` / `--provider-*` / `--volume-*` / `--score-*`，浅色段与 `.dark` 段均一致） | 无（上游只是把 `--pill-format-*` **重复写了两遍**） | 无（本项目删掉了那段重复声明，文件头有注明） |
| `accents.css` | 上游同名（1045 行） | `frontend/src/assets/theme/accents.css`（143 行） | **一致**（65 档 = 21 Vivid + 44 Pastel，逐档一致；本项目压成一行/档） | 无 | 无 |
| `radius.css` | 上游同名（19 行） | 同名（15 行） | **一致**（`--shell-radius: min(var(--radius), 1.25rem)`；`.radius-sharp` / `.radius-rounded` / `.radius-pill`） | 无 | 无 |
| `bridge.css` | 上游同名（75 行） | 同名（97 行） | **一致**（`@theme inline` 的 `--radius-*` / `--font-*` / `--color-*` / `--shadow-*` 全表同名同值） | 无 | 无（多中文注释） |
| `cover-effects.css` | 上游同名（178 行） | 同名（174 行） | **一致**（`.book-cover-surface` / `--book-cover-shadow*` / `[data-cover-shadow='strong']` / `[data-cover-spine]` / `.book-cover-artwork-frame*` / `transition: opacity 180ms ease`） | 无 | 无（文件头注明「逐字拷贝」） |

**入口层差异**（`main.css`，影响 token 生效方式，属**形态不同**）：

- 上游 `client/src/assets/main.css` 第 1–4 行：`@import '@fontsource-variable/inter'`、`'@fontsource-variable/fraunces'`、`'tailwindcss'`、**`'tw-animate-css'`**；
- 本项目 `frontend/src/assets/main.css`：`@import './fonts.css'`（自托管 10 个 woff2）+ `'tailwindcss'`，**未引 `tw-animate-css`**，动效由本文件 keyframes 提供；
- 动效词汇表两侧一致：`fade-in 0.25s` / `fade-up 0.3s`（`translateY(8px)`）/ `scale-in 0.25s` / `shimmer 1.5s` / `shake 0.3s` / `float 3s` / `count-pulse 0.2s` / `progress-stripes 0.5s`，且都包在 `@media (prefers-reduced-motion: no-preference)` 内；
  本项目**额外**提供 `prefers-reduced-motion: reduce` 的全局降级，并有 `:focus-visible` 全局焦点环与元素级基线（上游对应能力来自 shadcn 组件类）。

**token 层总判定**：五个主题文件 = **已对齐**；差异仅在入口的字体与动画库引入方式（与 `docs/DESIGN.md` 记的「两处刻意的与上游差异」吻合）。

---

## 4. 差异汇总与改造优先级

**判定汇总**

| 区块 | 判定 |
|---|---|
| 页面三态骨架（loading / error / empty / ready） | **缺失** |
| 页面入场动效（`animate-fade-up` + 错峰 delay） | **缺失** |
| 页面容器间距 / 内边距 | 形态不同 |
| 问候语行（图标 + 问候 + 用户名） | **缺失** |
| 「自定义」入口形态（内联按钮 vs FAB） | 形态不同 |
| 部件清单与顺序（12 件 id） | **已对齐** |
| 部件行网格模型（横向定宽滚动 vs 响应式列栅格） | 形态不同 |
| 部件卡片外壳 token（`rounded-2xl border-primary/40 bg-card/30 backdrop-blur`） | 形态不同 |
| 行内滚动按钮 / 卡上拖拽手柄 / `dashboardWidgetFadeUp` | **缺失** |
| 12 件部件内部视觉细节 | 形态不同（`reading-rhythm` 兼**语义**不同） |
| 部件骨架 / 错误分支 | **缺失** |
| 书架行卡片外壳 / 表头图标块与计数胶囊 / 滚动按钮 | **缺失** |
| 书架多行（1..3）与两列布局 | **缺失** |
| 书架骨架 / 错误重试 | **缺失** |
| 书架可配置数量（8 vs 6）与类型域（7 vs 4） | 形态不同 |
| 设置面板外壳 / 保存模型（草稿+保存 vs 即时落库） | 形态不同 |
| 设置面板的布局选择器 / 行数控件 / 库范围筛选 | **缺失** |
| 首启卡片（大圆角 + 半透底 + 光晕） | 形态不同 |
| onboarding tour 与 `data-tour` 锚点 | **缺失** |
| 五个主题 token 文件 | **已对齐** |
| 入口字体 / 动画库引入方式 | 形态不同 |

**建议改造顺序（供第二步逐项执行，先观感后结构）**

| 优先级 | 项目 | 理由 / 影响面 |
|---|---|---|
| **P0** | ① 部件卡片外壳 token 统一为上游口径（`rounded-2xl` + `border-primary/40` + `bg-card/30` + `backdrop-blur-[1px]`） | 首页第一眼观感差异最大；⚠️ 涉及「外壳从部件内部移到行组件」的重构（12 个部件文件根节点），或**折中**：保持外壳在部件内部、只把 token 换成上游口径（改动面小、视觉收益大） |
| **P0** | ② 页面级入场动效（`animate-fade-up` + 部件行整体 + 每个书架 `index*100ms`） | 零结构改动的纯增益；`main.css` 里 `.animate-fade-up` 已存在，只需消费 |
| **P0** | ③ 问候语行（`Sparkles` + 问候 + 用户名 + 「自定义」入口） | 上游首页最显眼的一行，本项目完全缺失；需定「问候语按时段分段」的文案与是否保留 FAB |
| **P1** | ④ 书架行卡片外壳 + 表头（图标块 / 计数胶囊 / 悬停滚动按钮） | 五行书架是首页主体，观感提升大；只改 `DashboardShelfRow.vue` 一个文件 |
| **P1** | ⑤ 页面容器 `space-y-5 pb-8 pt-4 sm:pr-2` 与页面三态骨架 | 骨架/错误态是「加载时不闪空」的体验项，改动集中在 `DashboardView.vue` |
| **P1** | ⑥ 部件行网格模型（定宽横向滚动 + 定高 `h-55`） | ⚠️ **需先定标**（见 §5 待确认 2）：会改变窄屏与多部件下的整体节奏，影响面最大的一处 |
| **P2** | ⑦ 设置面板：书架布局选择器 / 行数控件 / 库范围筛选 | 属「配置能力」而非纯样式；本项目当前 6 行上限也限制了多行布局的收益 |
| **P2** | ⑧ 首启卡片（大圆角 + 半透底 + 径向光晕） | 只在 0 库 / 全关时出现 |
| **P2** | ⑨ 12 件部件内部细节（封面缩略图、进度条高度 `h-1.5`、趋势图标、CTA 按钮） | 逐件小改、收益分散；建议**只统一「外壳 + 字号字重 + 进度条高度」三层**，不逐像素照抄（见 §5 待确认 3） |
| **不做** | 引入 `/api/v1/dashboard/widgets/batch`、`vue-draggable-plus` 拖拽库、i18n、onboarding tour | 前两项与「默认不引外部依赖」取向冲突且现有实现能力等价；i18n 全站未做；tour 属新功能不属样式对照 |

**风险提示**

- `backdrop-blur` 在低端设备 / 大量卡片下有合成开销（上游只 blur 1px）⇒ 若做 ①，建议保留上游的 `1px` 不做加强。
- 上游多处方用 Tailwind 默认调色板硬编码（`orange` / `green` / `blue` / `amber` / `emerald` / `red`）；
  本项目走语义 token。**改造时不要为了「像」而引入硬编码色** —— `docs/DESIGN.md` 明令禁止，且深色主题下硬编码色会失配。
- 部件外壳若真要搬到行组件，需要同批处理 12 个部件的根节点 + 骨架态，属结构性重构，建议单独立项而非混在「样式微调」里。

---

## 5. 待确认项

1. **首屏整体观感未做肉眼比对**：上游 `docs/images/dashboard-overview.png` **确实存在**（对象库里有），但本轮稀疏检出未包含 `docs/images/`。
   如需比对，可单独取该文件（`git cat-file` 或把 `docs/images` 加进 sparse-checkout）；⚠️ 按既有脱敏口径，含账号显示名的截图不归档进本仓库。
2. **部件行网格模型是否要改成上游的「定宽横向滚动 + 定高卡片」**：两侧能力等价但观感差异大，且本项目目前是响应式列栅格
   （`grid-cols-1 sm:grid-cols-2 lg:grid-cols-6` + `sm/md/lg` 三档列跨度）。改成横向滚动会改变窄屏节奏与部件高度统一方式，**需产品决策**。
3. **12 件部件内部细节「照抄到什么程度」需要定标**：像素级照抄会把本项目已落定的业务语义拉回上游语义（例如下面第 4 条），
   且上游部分实现依赖本项目没有的数据（如「最长连续天数」需额外统计口径、`ExternalLink` 指向外部站点）。
   **建议**：只统一「外壳 + 字号字重 + 进度条高度」三层，其余按本项目语义保留。
4. **`reading-rhythm` 同一 id 但语义不同**：上游是**阅读时长**（`readingSeconds` + 一致性 + 日均），本项目是**入库数量**（`added_28d`）。
   本项目其实**有**阅读时长数据（`reading_sessions` 表 + `dailySummary{day,totalMinutes}`，见阅读活动页与阅读记录页），
   所以「切回上游语义」在数据上是可行的 —— 是否切、还是保留「入库节奏」并另开一个时长部件，**需产品决策**。
5. **设置面板是否补「书架布局 / 行数」控件**：这两项在上游与「书架多行 + 两列布局」是**成对**的
   （没有 rows 控件，多行布局无法配置）⇒ 若做 P2 的 ⑦，应与 ⑥ 一起决策，否则会出现「有控件没效果」的假交互。

---

## 6. 与既有结论的关系（不覆盖、只补充）

- `bookorbit-capability-gap.md` 记「**仪表盘部件 12 件：已落地**」、`bookorbit-module-inventory.md` 记「`dashboard` 22 文件 / 第 32 期已对齐 12 件部件」。
  **本文件的补充是粒度**：那两处对齐的是**部件清单与 id**（能力面）；
  而**样式面**仍有多处「形态不同」与「缺失」（卡片外壳 token、横向滚动、入场动效、问候语行、书架多行/两列、骨架态）。
  ⇒ 「能力已覆盖」**不等于**「样式已对齐」，本文件是后者的基线。
- `docs/DESIGN.md` 记的「两处刻意的与上游差异」（字体自托管、不引 `tw-animate-css`）在本轮复核中**成立**，本文件不推翻。
- 既有 5 份 `bookorbit-*.md` 的历史结论一律**不改写**；本文件只做首页样式维度的补充与索引。

---

## 7. 实施结果（第 82 期第二步，2026-10-01 · 本节的判定覆盖 §2–§4 的旧行）

第一步清单确认后已逐项改造完毕（V0.82.0）。**判定翻转**（旧判定 → 现判定）：

| 条目 | §2/§4 旧判定 | 现判定 |
|---|---|---|
| 部件行网格模型（横向定宽 + `h-55` + 滚动按钮） | 形态不同 / 缺失 | **已对齐**（宽度映射、悬停滚动按钮、隐藏滚动条照抄） |
| 卡片外壳 token（`rounded-2xl border-primary/40 bg-card/30 backdrop-blur-[1px]`） | 形态不同 | **已对齐**（壳上移到部件行，12 件部件已去壳，双层壳消灭） |
| 行内拖拽手柄 + 排序 | 缺失 | **已对齐**（`vue-draggable-plus`，触屏可用；可见子集 → 全量索引映射在 store） |
| `dashboardWidgetFadeUp` 逐卡错峰入场 | 缺失 | **已对齐**（scoped keyframes + `index*80ms`） |
| 问候语行（图标 + 问候 + 用户名 + 自定义入口） | 缺失 | **已对齐**（时段分段优先 `auth.timezone`；入口从 FAB 移到本行） |
| 页面入场动效（`animate-fade-up` 错峰） | 缺失 | **已对齐**（40ms / 部件行 / 书架 index×100ms） |
| 书架行卡片外壳 + 表头（图标块 / 计数胶囊 / 滚动按钮） | 缺失 | **已对齐**（`DashboardShelfRow` 重写） |
| 书架多行（1..3）+ 两列布局 + 面板控件 | 缺失 | **已对齐**（`lib/shelfRows.ts` 分带 + 面板布局/行数控件 + 持久化补默认） |
| 首启卡片（大圆角 + 半透底 + 光晕） | 形态不同 | **已对齐**（`FirstRunNotice` / `DashboardWelcome` 重写；失效文案已改） |
| 部件骨架 / 错误 / 空态三分支 | 缺失 | **已对齐**（`useWidgetState` 统一封装，全部真实状态） |
| 主题 token（5 个 css） | 已对齐 | 仍**已对齐**（本轮零 token 改动） |
| 部件清单与顺序（12 件 id） | 已对齐 | 仍**已对齐**（id 一字未改） |
| i18n / 上游硬编码调色板 / `/api/v1/dashboard/*` 接口 / tour | 形态不同 / 缺失 | **保持刻意差异**（中文字面量 / 语义 token / 不引入 / 未做） |
| 整页三态分支、库范围筛选、`BookQuickView` 三件套、封面入场动画 | 缺失 | **未做**（见 §4 的「不做」与 §5 待确认；非本期范围） |

实施细节与测试见 `docs/roadmap-gaps-remaining.md` 第 82 期。**本文件的 §2–§4 保留为「改造前的对照基线」**，
判定以本节为准 —— 下次再对照上游新版本时，从本节的「现判定」继续。
