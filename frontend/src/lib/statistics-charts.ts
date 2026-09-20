/**
 * 统计页图表目录：每张图的 id / 标题 / 图标 / 栅格尺寸 / 所属分区，以及默认顺序。
 *
 * 对标上游 `client/src/features/statistics/statistics-chart-meta.ts`（33 张）。本项目
 * **分两批**落地：第 32 期 10 张（书库侧 5 + 阅读侧 5）；第 33 期把统计页原有的 7 张
 * 手写卡片转成正式 id（全在书库侧）、再补 13 张缺口图（书库侧 6 + 阅读侧 7），
 * 合计 30 张。剩下 3 张已声明不做（`metadata-freshness-gauge` /
 * `reading-source-distribution` / `goal-trajectory`），账目见
 * `docs/bookorbit-capability-gap.md`。
 *
 * 两条与上游对齐的规矩：
 *
 * 1. **id 与上游逐字一致** —— 将来补图时照上游的 id 接着加，Configure 里用户已存的
 *    偏好数据才不会错位。
 * 2. **默认顺序也照上游**（`packages/types/src/statistics.ts` 的
 *    `DEFAULT_LIBRARY_CHART_ORDER` / `DEFAULT_USER_CHART_ORDER`，滤掉本项目没有的图）。
 *    所以下面每张图的排列位置不是随手定的，改顺序前先回上游核一遍。
 *
 * ⚠️ **label 的唯一硬要求是「别在同一个分区里重名」**：本页图表与手写卡片同屏共存，
 * 图与卡片重名会让人以为是两张不同的图。已有的避重名先例见 `storage-by-format`
 * 与 `books-added-over-time` 的注释；第 33 期同理把 7 张迁移图取了带规模的名字
 * （「Top 50 作者」对卡片的「Top 作者」）。
 *
 * `size` 的语义与栅格类映射见 `components/charts/ChartGrid.vue`。
 */
export type StatisticsChartSize = '1x1' | '2x1' | '2x2' | '1x2' | '3x1' | '4x1'

/** 分区：对齐上游的 Library Stats / 本项目的「书库统计 / 我的阅读」 */
export type StatisticsTab = 'library' | 'reading'

export interface StatisticsChartMeta {
  id: string
  label: string
  /** 图标名（`lib/icons.ts` 的常量表） */
  icon: string
  size: StatisticsChartSize
  tab: StatisticsTab
}

export const STATISTICS_CHART_META = {
  // ---- 书库侧（顺序 = 上游 DEFAULT_LIBRARY_CHART_ORDER 滤掉未实现的）----
  'library-integrity-gauge': {
    id: 'library-integrity-gauge',
    // 与保留下来的明细卡同名，故卡片那侧改叫「体检明细」（见 StatsView 的注释）
    label: '书库体检',
    icon: 'wrench',
    size: '1x1',
    tab: 'library',
  },
  'format-distribution': {
    id: 'format-distribution',
    // 迁移前是手写卡片「格式分布」；卡片已删，这个名字空出来了
    label: '格式分布',
    icon: 'chart',
    size: '1x1',
    tab: 'library',
  },
  'metadata-score-distribution': {
    id: 'metadata-score-distribution',
    label: '元数据分数分布',
    icon: 'chart',
    size: '1x1',
    tab: 'library',
  },
  'largest-books': {
    id: 'largest-books',
    // 不叫「体积榜」—— 那是下方仍在的明细卡片的名字，这张是它的图形版
    label: 'Top 50 最大书籍',
    icon: 'file',
    size: '2x1',
    tab: 'library',
  },
  'genre-distribution': {
    id: 'genre-distribution',
    // 不叫「Top 题材」—— 那是下方仍在的明细卡片的名字
    label: '题材分布',
    icon: 'note',
    size: '2x1',
    tab: 'library',
  },
  'format-share-over-time': {
    id: 'format-share-over-time',
    // 与「格式分布」（按本数的环形图）、「格式占用」（按体积）区分：这张看的是**构成随时间变**
    label: '格式占比随时间',
    icon: 'shelf',
    size: '2x1',
    tab: 'library',
  },
  'top-authors': {
    id: 'top-authors',
    // 本项目的接口固定 top=50（上游这张图取 25），所以写 50 而不是照抄「Top 25」
    label: 'Top 50 作者',
    icon: 'users',
    size: '2x1',
    tab: 'library',
  },
  'metadata-completeness': {
    id: 'metadata-completeness',
    label: '元数据覆盖率',
    icon: 'check',
    size: '1x1',
    tab: 'library',
  },
  'acquisition-lag-scatter': {
    id: 'acquisition-lag-scatter',
    label: '入库滞后',
    icon: 'clock',
    size: '1x1',
    tab: 'library',
  },
  'library-metadata-completeness': {
    id: 'library-metadata-completeness',
    // 不直译成「各库元数据覆盖率」：同屏已有一张「元数据覆盖率」，差两个字必然看串。
    // 「对比」正是这张图的用途（见组件的注释）。
    label: '各库元数据对比',
    icon: 'library',
    size: '2x1',
    tab: 'library',
  },
  'storage-by-format': {
    id: 'storage-by-format',
    // 不叫「格式体积」之外的译法都行，唯一要求是**别和既有卡片重名**：
    // 统计页下方已经有「格式分布」（按本数）与规模卡「占用」（总量），
    // 这张是「按格式的体积」，故取「格式占用」。
    label: '格式占用',
    icon: 'file',
    size: '1x1',
    tab: 'library',
  },
  'language-distribution': {
    id: 'language-distribution',
    label: '语言分布',
    icon: 'globe',
    size: '1x1',
    tab: 'library',
  },
  'page-count-distribution': {
    id: 'page-count-distribution',
    label: '页数分布',
    icon: 'book',
    size: '1x1',
    tab: 'library',
  },
  'publication-decade': {
    id: 'publication-decade',
    // 不叫「出版年份」—— 那是迁移前手写卡片的名字（卡片已删），且与既有的
    // 「出版年时间轴」（逐年、4x1）要区分开：这张是十年一档的大势
    label: '出版年代',
    icon: 'library',
    size: '1x1',
    tab: 'library',
  },
  'genre-cooccurrence': {
    id: 'genre-cooccurrence',
    // 与「题材分布」（单题材计数、树图）区分：这张是**题材之间**的共同出现
    label: '题材共现',
    icon: 'layers',
    size: '2x2',
    tab: 'library',
  },
  'top-series': {
    id: 'top-series',
    // 不叫「Top 系列」—— 那是下方仍在的明细卡片的名字
    label: 'Top 50 系列',
    icon: 'layers',
    size: '2x1',
    tab: 'library',
  },
  'books-added-over-time': {
    id: 'books-added-over-time',
    // 同样为避重名：下方既有卡片「入库节奏」看的是**近 N 天逐日**（跟随页首范围
    // 选择器），这张看的是**全时段月度/年度**走势，故取「入库趋势」。
    label: '入库趋势',
    icon: 'shelf',
    size: '2x1',
    tab: 'library',
  },
  'publication-year-timeline': {
    id: 'publication-year-timeline',
    label: '出版年时间轴',
    icon: 'library',
    size: '4x1',
    tab: 'library',
  },
  // ---- 阅读侧（顺序 = 上游 DEFAULT_USER_CHART_ORDER 滤掉未实现的）----
  'peak-reading-hours': {
    id: 'peak-reading-hours',
    label: '高峰时段',
    icon: 'bell',
    size: '2x1',
    tab: 'reading',
  },
  'favorite-reading-days': {
    id: 'favorite-reading-days',
    label: '最爱阅读日',
    icon: 'star',
    size: '1x1',
    tab: 'reading',
  },
  'completion-timeline': {
    id: 'completion-timeline',
    label: '读完时间轴',
    icon: 'check',
    size: '2x1',
    tab: 'reading',
  },
  'progress-funnel': {
    id: 'progress-funnel',
    label: '进度漏斗',
    icon: 'layers',
    size: '1x1',
    tab: 'reading',
  },
  'reading-clock': {
    id: 'reading-clock',
    label: '阅读时钟',
    icon: 'clock',
    size: '1x1',
    tab: 'reading',
  },
} satisfies Record<string, StatisticsChartMeta>

/**
 * 全部合法图表 id —— 由目录的**键**推导，所以「加图」只有这一处真相。
 *
 * 它的用处是把「注册了 id 却忘了登记组件」变成**编译错误**：`ChartGrid.vue` 的
 * `CHART_COMPONENTS` 标了 `Record<StatisticsChartId, Component>`，少登记一个 id
 * 就通不过类型检查。此前那是**静默空白** —— tile 的 `<div>` 照占栅格、里面什么都没有。
 *
 * ⚠️ 目录本身不再标 `Record<string, …>`：那样 `keyof` 会塌成 `string`，守卫就失效了。
 * 需要按**不可信的** string 查表时（localStorage 归一，见 `stores/statsChartPrefs`），
 * 先用 `in` 做运行时收窄，别用 `as` 绕过去。
 */
export type StatisticsChartId = keyof typeof STATISTICS_CHART_META

/**
 * 一张「已解析」的图：**窄 id** + 它的元信息。
 *
 * `ChartGrid` 的 props 用它而不是 `StatisticsChartMeta[]` —— 后者的 `id` 是宽 `string`，
 * 拿它索引 `CHART_COMPONENTS`（`Record<StatisticsChartId, …>`）通不过类型检查，而**正是
 * 那道检查**在防「登记了 id 却没加组件」的静默空白。让 id 的窄类型顺着 props 传下去，
 * 下游就不必写断言、也不必在运行时兜底。
 */
export interface StatisticsChartTile {
  id: StatisticsChartId
  meta: StatisticsChartMeta
}

/**
 * 分区内的默认顺序（也是 Configure 面板的初始顺序）。
 *
 * **照上游滤掉本项目没有的图**（上游 library 19 张、user 14 张）：
 * `statistics-chart-meta.ts` 声明序 ≠ 这个顺序，上游的真相源是
 * `packages/types/src/statistics.ts` 的同名常量 —— 补图时也要去那里核。
 *
 * 老用户的存档不必管：`stores/statsChartPrefs` 的 `read()` 会把存档里没有的 id
 * **补到各自分区末尾**，所以这里重排不会让老用户丢图，只会让新图落在后面。
 */
export const DEFAULT_CHART_ORDER: Record<StatisticsTab, StatisticsChartId[]> = {
  library: [
    'library-integrity-gauge',
    'format-distribution',
    'metadata-score-distribution',
    'largest-books',
    'genre-distribution',
    'format-share-over-time',
    'top-authors',
    'metadata-completeness',
    'acquisition-lag-scatter',
    'library-metadata-completeness',
    'storage-by-format',
    'language-distribution',
    'page-count-distribution',
    'publication-decade',
    'genre-cooccurrence',
    'top-series',
    'books-added-over-time',
    'publication-year-timeline',
  ],
  reading: [
    'peak-reading-hours',
    'favorite-reading-days',
    'completion-timeline',
    'progress-funnel',
    'reading-clock',
  ],
}
