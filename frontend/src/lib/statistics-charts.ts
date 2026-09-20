/**
 * 统计页图表目录：每张图的 id / 标题 / 图标 / 栅格尺寸 / 所属分区，以及默认顺序。
 *
 * 对标上游 `client/src/features/statistics/statistics-chart-meta.ts`（33 张）。本项目
 * **分两批**落地，这里是第一批 10 张（书库侧 5 + 阅读侧 5）；id 与上游保持一致，
 * 以后补图时照上游的 id 接着加，Configure 的偏好数据才不会错位。
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

export const STATISTICS_CHART_META: Record<string, StatisticsChartMeta> = {
  // ---- 书库侧 ----
  'language-distribution': {
    id: 'language-distribution',
    label: '语言分布',
    icon: 'globe',
    size: '1x1',
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
  'page-count-distribution': {
    id: 'page-count-distribution',
    label: '页数分布',
    icon: 'book',
    size: '1x1',
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
  // ---- 阅读侧 ----
  'reading-clock': {
    id: 'reading-clock',
    label: '阅读时钟',
    icon: 'clock',
    size: '1x1',
    tab: 'reading',
  },
  'peak-reading-hours': {
    id: 'peak-reading-hours',
    label: '高峰时段',
    icon: 'bell',
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
  'completion-timeline': {
    id: 'completion-timeline',
    label: '读完时间轴',
    icon: 'check',
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
}

/** 分区内的默认顺序（也是 Configure 面板的初始顺序） */
export const DEFAULT_CHART_ORDER: Record<StatisticsTab, string[]> = {
  library: [
    'language-distribution',
    'storage-by-format',
    'page-count-distribution',
    'books-added-over-time',
    'publication-year-timeline',
  ],
  reading: [
    'reading-clock',
    'peak-reading-hours',
    'progress-funnel',
    'completion-timeline',
    'favorite-reading-days',
  ],
}
