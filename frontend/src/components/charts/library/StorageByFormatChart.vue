<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme, useIsWide } from '@/lib/charts'
import { fmtBytes } from '@/lib/format'

/**
 * 格式占用（上游 `StorageByFormatChart.vue`）：环形饼，数值是**字节**不是本数
 * （本数另有「格式分布」卡片）。
 *
 * 各扇区之和 == `books.size`（后端有条测试钉着这个等式）。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()
const wide = useIsWide()

const items = computed(() =>
  Object.entries(props.data.by_format_size)
    .map(([format, sizeBytes]) => ({ format, sizeBytes }))
    .sort((a, b) => b.sizeBytes - a.sizeBytes || a.format.localeCompare(b.format)),
)

const option = computed(() => ({
  color: palette.value,
  tooltip: {
    trigger: 'item',
    formatter: (p: { name: string; value: number; percent: number }) =>
      `${p.name}：${fmtBytes(p.value)}（${p.percent}%）`,
    ...theme.value.tooltip,
  },
  legend: {
    orient: wide.value ? 'vertical' : 'horizontal',
    right: wide.value ? '2%' : 'auto',
    bottom: wide.value ? 'auto' : 0,
    top: wide.value ? 'middle' : 'auto',
    ...theme.value.legend,
  },
  series: [
    {
      type: 'pie',
      radius: ['40%', '70%'],
      center: wide.value ? ['38%', '50%'] : ['50%', '44%'],
      data: items.value.map((x) => ({ name: x.format.toUpperCase(), value: x.sizeBytes })),
      label: { show: false },
    },
  ],
}))
</script>

<template>
  <ChartCard
    title="格式占用"
    icon="file"
    :color-index="1"
    :empty="!items.length"
    empty-title="还没有文件"
    empty-description="按成品文件的体积统计，不是本数。"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
