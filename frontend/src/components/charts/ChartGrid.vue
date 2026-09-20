<script setup lang="ts">
import type { Component } from 'vue'

import BooksAddedOverTimeChart from '@/components/charts/library/BooksAddedOverTimeChart.vue'
import LanguageDistributionChart from '@/components/charts/library/LanguageDistributionChart.vue'
import PageCountDistributionChart from '@/components/charts/library/PageCountDistributionChart.vue'
import PublicationYearTimelineChart from '@/components/charts/library/PublicationYearTimelineChart.vue'
import StorageByFormatChart from '@/components/charts/library/StorageByFormatChart.vue'
import type { StatsOverview } from '@/lib/api'
import type { StatisticsChartMeta, StatisticsChartSize } from '@/lib/statistics-charts'

/**
 * 图表栅格（照搬上游 `StatisticsGrid.vue` 的栅格与跨度映射）。
 *
 * 两处与本项目对齐的改动：
 *
 * 1. **去掉拖拽排序**。上游把整块网格包在 `VueDraggable` 里；本项目不引拖拽库，
 *    排序改到 Configure 面板里用上移/下移按钮（功能等价，零新依赖）。
 * 2. **不做 `defineAsyncComponent`**。上游 33 张图各自异步加载；本项目本期 10 张图
 *    在同一屏同时渲染，拆成 10 个 chunk 只是把一次请求变成 11 次。等图多起来
 *    （尤其是 Configure 里默认隐藏的那些）再考虑。
 */
defineProps<{
  charts: StatisticsChartMeta[]
  data: StatsOverview
}>()

/** 加图时在这里登记，id 与 `lib/statistics-charts.ts` 的目录一致 */
const CHART_COMPONENTS: Record<string, Component> = {
  'language-distribution': LanguageDistributionChart,
  'storage-by-format': StorageByFormatChart,
  'page-count-distribution': PageCountDistributionChart,
  'books-added-over-time': BooksAddedOverTimeChart,
  'publication-year-timeline': PublicationYearTimelineChart,
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
      v-for="(chart, index) in charts"
      :key="chart.id"
      :class="tileClass(chart.size)"
      class="animate-fade-up min-w-0"
      :style="{ animationDelay: `${index * 60}ms` }"
    >
      <component :is="CHART_COMPONENTS[chart.id]" v-if="CHART_COMPONENTS[chart.id]" :data="data" />
    </div>
  </div>
</template>
