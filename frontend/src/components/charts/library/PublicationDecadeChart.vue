<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 出版年代（上游 `PublicationDecadeChart.vue`）：按十年一档的柱图。
 *
 * 承接的是统计页原有的**手写「出版年份」卡**（第 33 期迁移，卡片已删）。那张卡
 * 每行都直接写着本数，而上游的柱子不带数字（数量只在 tooltip 里），故这里
 * **把数量画到柱顶** —— 信息量不减。
 *
 * 那张卡右下角还有一句「另有 N 本未标注年份」，改由 `ChartCard` 的 `note` 承载
 * （本项目的 `note` 就是干这个的，对应上游 ChartCard 的 `unknown-count`）。
 *
 * 与既有的 `publication-year-timeline`（逐年、4x1）是**两个视角**：这张看十年一档
 * 的大势，那张看逐年细节与黄金年代标注 —— 不重复。
 */
const props = defineProps<{ data: StatsOverview }>()

const { theme } = useChartTheme()

const decades = computed(() => props.data.years.decades ?? [])
const unknownCount = computed(() => props.data.years.unknown ?? 0)

const option = computed(() => ({
  tooltip: { trigger: 'axis', ...theme.value.tooltip },
  grid: { left: 2, right: 6, bottom: 2, top: 24, containLabel: true },
  xAxis: {
    ...theme.value.axis,
    type: 'category',
    data: decades.value.map((d) => `${d.decade}s`),
    // ⚠️ 先展开 axis 再覆盖 axisLabel：反过来会被 axis 自带的 axisLabel 盖回去
    axisLabel: { ...theme.value.axisLabelStyle, fontSize: 11 },
  },
  yAxis: {
    ...theme.value.axis,
    type: 'value',
    minInterval: 1,
    axisLabel: { ...theme.value.axisLabelStyle, fontSize: 11 },
  },
  series: [
    {
      type: 'bar',
      data: decades.value.map((d) => d.count),
      itemStyle: { borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 48,
      label: {
        show: true,
        position: 'top',
        fontSize: 10,
        color: theme.value.axisLabel,
        formatter: (p: { value: number }) => `${p.value}`,
      },
    },
  ],
}))
</script>

<template>
  <ChartCard
    title="出版年代"
    icon="library"
    :color-index="5"
    :empty="!decades.length"
    empty-title="没有可解析的出版年份"
    empty-description="年份来自 EPUB 的 dc:date；没写或解析不出的书不计入。"
    :note="unknownCount ? `另有 ${unknownCount} 本未标注年份，未计入。` : ''"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
