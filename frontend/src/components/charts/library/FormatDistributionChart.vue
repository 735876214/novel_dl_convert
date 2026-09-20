<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme, useIsWide } from '@/lib/charts'

/**
 * 格式分布（上游 `FormatDistributionChart.vue`）：环形饼 + 可滚动 legend。
 *
 * 承接的是统计页下方原有的**手写「格式分布」chip 卡**（第 33 期迁移，卡片已删 ——
 * 那张卡就是「`EPUB · 120` 一眼看全」，与这张图同一份数据，没必要两份）。
 *
 * 与上游的**一处有意加强**：上游关掉 `label`，数量只在 tooltip 里；那张 chip 卡
 * 却是数量直接可见的，故这里**把数量写进 legend** —— 信息量不减（还多了占比与
 * 配色），也不去挤环形饼那点宽度（1x1 格子里放外置标签会互相压）。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()
const wide = useIsWide()

/** 按本数降序；同数按格式名排，避免每次刷新配色顺序乱跳 */
const items = computed(() =>
  Object.entries(props.data.books.by_format ?? {})
    .map(([format, count]) => ({ format, count }))
    .sort((a, b) => b.count - a.count || a.format.localeCompare(b.format)),
)

/**
 * legend 文案：`EPUB  120`。
 *
 * ⚠️ 它必须与 series 的 `name` 逐字对得上 —— ECharts 的 legend 是按名字关联的，
 * 所以这里也走 `.toUpperCase()`（data 里就是大写后的名字）。
 */
function legendLabel(name: string): string {
  const hit = items.value.find((x) => x.format.toUpperCase() === name)
  return hit ? `${name}  ${hit.count}` : name
}

const option = computed(() => ({
  color: palette.value,
  tooltip: { trigger: 'item', ...theme.value.tooltip },
  legend: {
    type: 'scroll',
    orient: wide.value ? 'vertical' : 'horizontal',
    left: wide.value ? '50%' : 'center',
    right: wide.value ? 0 : 'auto',
    top: wide.value ? 8 : 'auto',
    bottom: wide.value ? 8 : 0,
    itemWidth: 12,
    itemHeight: 8,
    pageIconSize: 10,
    pageButtonGap: 4,
    ...theme.value.legend,
    // 展开在主题之后：主题只给 textStyle，但顺序反了将来加键就会盖掉文案
    formatter: legendLabel,
  },
  series: [
    {
      type: 'pie',
      // 比语言分布那张细一档：legend 文案更长，环形把宽度让给右侧文字
      radius: ['40%', '64%'],
      center: wide.value ? ['25%', '50%'] : ['50%', '38%'],
      data: items.value.map((x) => ({ name: x.format.toUpperCase(), value: x.count })),
      label: { show: false },
    },
  ],
}))
</script>

<template>
  <ChartCard
    title="格式分布"
    icon="chart"
    :color-index="1"
    :empty="!items.length"
    empty-title="还没有书目"
    empty-description="扫描入库后，这里按成品文件的扩展名统计本数。"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
