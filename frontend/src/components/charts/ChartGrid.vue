<script setup lang="ts">
import type { Component } from 'vue'

import BooksAddedOverTimeChart from '@/components/charts/library/BooksAddedOverTimeChart.vue'
import FormatDistributionChart from '@/components/charts/library/FormatDistributionChart.vue'
import GenreDistributionChart from '@/components/charts/library/GenreDistributionChart.vue'
import LanguageDistributionChart from '@/components/charts/library/LanguageDistributionChart.vue'
import LargestBooksChart from '@/components/charts/library/LargestBooksChart.vue'
import LibraryIntegrityGaugeChart from '@/components/charts/library/LibraryIntegrityGaugeChart.vue'
import PageCountDistributionChart from '@/components/charts/library/PageCountDistributionChart.vue'
import PublicationDecadeChart from '@/components/charts/library/PublicationDecadeChart.vue'
import PublicationYearTimelineChart from '@/components/charts/library/PublicationYearTimelineChart.vue'
import StorageByFormatChart from '@/components/charts/library/StorageByFormatChart.vue'
import TopAuthorsChart from '@/components/charts/library/TopAuthorsChart.vue'
import TopSeriesChart from '@/components/charts/library/TopSeriesChart.vue'
import CompletionTimelineChart from '@/components/charts/reading/CompletionTimelineChart.vue'
import FavoriteReadingDaysChart from '@/components/charts/reading/FavoriteReadingDaysChart.vue'
import PeakReadingHoursChart from '@/components/charts/reading/PeakReadingHoursChart.vue'
import ProgressFunnelChart from '@/components/charts/reading/ProgressFunnelChart.vue'
import ReadingClockChart from '@/components/charts/reading/ReadingClockChart.vue'
import type { StatsOverview } from '@/lib/api'
import type { StatisticsChartId, StatisticsChartSize, StatisticsChartTile } from '@/lib/statistics-charts'

/**
 * 图表栅格（照搬上游 `StatisticsGrid.vue` 的栅格与跨度映射）。
 *
 * 两处与本项目对齐的改动：
 *
 * 1. **去掉拖拽排序**。上游把整块网格包在 `VueDraggable` 里；本项目不引拖拽库，
 *    排序改到 Configure 面板里用上移/下移按钮（功能等价，零新依赖）。
 * 2. **不做 `defineAsyncComponent`**。上游 33 张图各自异步加载；本项目第 33 期共
 *    17 张，单屏最多 12 张（书库侧）同时渲染，拆成十几个 chunk 只是把一次请求变成
 *    十几次。等第二批缺口图落地（总数到 30 张）连同包体积一起评估。
 */
defineProps<{
  /** 已解析的图（窄 id + 元信息）。窄 id 是刻意的，见 `CHART_COMPONENTS` 的注释 */
  charts: StatisticsChartTile[]
  data: StatsOverview
}>()

/**
 * id → 组件。加图时在**这里**与 `lib/statistics-charts.ts` 的目录**两处一起加**。
 *
 * 标成 `Record<StatisticsChartId, …>` 是刻意的：`StatisticsChartId` 由目录的键推导，
 * 于是「目录里有 id、这里没组件」会**直接编译失败** —— 此前那是静默空白（tile 的
 * `<div>` 照占栅格、里面什么都没有）。
 */
const CHART_COMPONENTS: Record<StatisticsChartId, Component> = {
  // ---- 书库侧 ----
  'library-integrity-gauge': LibraryIntegrityGaugeChart,
  'format-distribution': FormatDistributionChart,
  'largest-books': LargestBooksChart,
  'genre-distribution': GenreDistributionChart,
  'top-authors': TopAuthorsChart,
  'storage-by-format': StorageByFormatChart,
  'language-distribution': LanguageDistributionChart,
  'page-count-distribution': PageCountDistributionChart,
  'publication-decade': PublicationDecadeChart,
  'top-series': TopSeriesChart,
  'books-added-over-time': BooksAddedOverTimeChart,
  'publication-year-timeline': PublicationYearTimelineChart,
  // ---- 阅读侧 ----
  'peak-reading-hours': PeakReadingHoursChart,
  'favorite-reading-days': FavoriteReadingDaysChart,
  'completion-timeline': CompletionTimelineChart,
  'progress-funnel': ProgressFunnelChart,
  'reading-clock': ReadingClockChart,
}

/** 尺寸 → 栅格跨度（逐条照搬上游 `StatisticsGrid.vue:53-60`） */
function tileClass(size: StatisticsChartSize): string {
  if (size === '2x1') return 'md:col-span-2 md:row-span-1'
  if (size === '2x2') return 'md:col-span-2 md:row-span-2'
  if (size === '1x2') return 'md:col-span-1 md:row-span-2'
  if (size === '3x1') return 'md:col-span-2 xl:col-span-3 md:row-span-1'
  if (size === '4x1') return 'md:col-span-2 xl:col-span-4 md:row-span-1'
  return 'md:col-span-1 md:row-span-1'
}
</script>

<template>
  <div class="grid grid-flow-row-dense grid-cols-1 gap-4 md:grid-cols-2 md:auto-rows-[360px] xl:grid-cols-4">
    <div
      v-for="(tile, index) in charts"
      :key="tile.id"
      :class="tileClass(tile.meta.size)"
      class="animate-fade-up min-w-0"
      :style="{ animationDelay: `${index * 60}ms` }"
    >
      <!-- 不需要 `v-if` 兜底：`tile.id` 是窄类型，`CHART_COMPONENTS[tile.id]` 类型上有值 -->
      <component :is="CHART_COMPONENTS[tile.id]" :data="data" />
    </div>
  </div>
</template>
