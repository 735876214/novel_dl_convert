<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'
import { fmtBytes } from '@/lib/format'

/**
 * 体积榜（上游 `LargestBooksChart.vue`）：横向条形 + `dataZoom`（默认显示最大的 10 本）。
 *
 * 与保留的明细卡（「体积榜」）是**互补关系**：图给「大小差距有多大」的直观对比，
 * 卡片给逐行可点（跳 `/book/:id`）的列表、以及 0 字节书的告警 —— 那两样图都给不了，
 * 故卡片第 33 期**刻意保留**，不是没迁干净的残留。
 *
 * 两处与本项目对齐的改动：
 *
 * 1. **条形按格式配色，且与「格式分布」图同序**。上游用一张独立的 `format-colors`
 *    表；本项目没有（也不该为一张图新造一份会漂移的颜色表），改用同一个调色板 +
 *    同一套降序规则 —— 于是「EPUB 在两张图里是同一个色」自然成立。
 * 2. **柱子带数量标签**。上游的数量只在 tooltip 里。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

/** 按字节升序 —— 横向条形图的 y 轴自下而上排，升序即「最大的在最上面」（同上游） */
const items = computed(() => [...(props.data.largest ?? [])].sort((a, b) => a.size_bytes - b.size_bytes))

/** 格式 → 调色板序号的映射：与「格式分布」图同一套降序规则，故同格式同色 */
const formatOrder = computed(() =>
  Object.entries(props.data.books.by_format ?? {})
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([format]) => format),
)

function colorOf(format: string): string {
  const i = formatOrder.value.indexOf(format)
  return palette.value[(i < 0 ? 0 : i) % palette.value.length] ?? '#6b7280'
}

const option = computed(() => ({
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'none' },
    ...theme.value.tooltip,
    formatter: (params: Array<{ name: string; value: number }>) => {
      const p = params[0]
      if (!p) return ''
      return `<strong>${p.name}</strong><br/>${fmtBytes(p.value)}`
    },
  },
  grid: { left: 2, right: 62, bottom: 6, top: 8, containLabel: true },
  dataZoom: [
    {
      type: 'inside',
      yAxisIndex: 0,
      // 默认只看最大的 10 本（升序数组的末尾 10 个）
      startValue: Math.max(0, items.value.length - 10),
      endValue: items.value.length - 1,
      zoomOnMouseWheel: false,
      moveOnMouseMove: true,
      moveOnMouseWheel: true,
    },
    {
      type: 'slider',
      yAxisIndex: 0,
      right: 2,
      width: 14,
      borderColor: 'transparent',
      fillerColor: 'rgba(150, 150, 150, 0.2)',
      handleSize: 0,
      showDetail: false,
      brushSelect: false,
    },
  ],
  xAxis: {
    ...theme.value.axis,
    type: 'value',
    axisLabel: {
      ...theme.value.axisLabelStyle,
      fontSize: 11,
      formatter: (v: number) => fmtBytes(v),
    },
  },
  yAxis: {
    ...theme.value.axis,
    type: 'category',
    data: items.value.map((x) => x.title),
    axisLabel: { ...theme.value.axisLabelStyle, fontSize: 11, width: 150, overflow: 'truncate' },
  },
  series: [
    {
      type: 'bar',
      data: items.value.map((x) => ({
        value: x.size_bytes,
        itemStyle: { color: colorOf(x.format), borderRadius: [0, 3, 3, 0] },
      })),
      barCategoryGap: '20%',
      barMaxWidth: 32,
      label: {
        show: true,
        position: 'right',
        fontSize: 10,
        color: theme.value.axisLabel,
        formatter: (p: { value: number }) => fmtBytes(p.value),
      },
    },
  ],
}))
</script>

<template>
  <ChartCard
    title="Top 50 最大书籍"
    icon="file"
    :color-index="2"
    :empty="!items.length"
    empty-title="还没有书目"
    empty-description="按成品文件大小排序，最多 50 本。"
    note="下方的「体积榜」卡片可逐本点开，并对 0 字节的文件给出告警。"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
