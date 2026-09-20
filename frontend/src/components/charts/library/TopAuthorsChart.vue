<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * Top 作者（上游 `TopAuthorsChart.vue`）：横向条形 + 累计占比折线（双 x 轴）。
 *
 * 与保留的明细卡（「Top 作者」）是**互补关系**：图给「前几名占了多少、累计曲线
 * 什么时候拉平」的全局视角，卡片给「展开全部 N 位」的逐条可读列表 —— 图上看不清
 * 第 30 位到底是谁。
 *
 * 两处与本项目对齐的改动：
 *
 * 1. **标题写 50 不写 25**。上游的 composable 只取前 25 位，本项目 `/api/stats`
 *    固定 `top=50`（`lib/api.ts:2952`），照抄「Top 25」就是错的。
 * 2. **加 `dataZoom`（默认显示前 20 位）**。上游 25 条挤在 360px 里尚可，本项目
 *    有 50 条 —— 不缩放就成了一条条 7px 的线。做法与 `TopSeriesChart` 一致。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

/** 按本数降序；同数按姓名排，避免每次刷新条形顺序乱跳 */
const items = computed(() =>
  [...(props.data.authors.top ?? [])].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)),
)
const total = computed(() => items.value.reduce((s, x) => s + x.count, 0))

/** 累计占比（%），与条形一一对应 */
const cumulative = computed(() => {
  let running = 0
  return items.value.map((x) => {
    running += x.count
    return total.value > 0 ? Number(((running / total.value) * 100).toFixed(1)) : 0
  })
})

/**
 * 条形配色分三档（照上游）：前 3 名满色、4–10 名 65%、其余 35%。
 * 这是**明度**上的分层，与调色板的色相无关 —— 换强调色时分层照旧。
 */
function withAlpha(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

const barColors = computed(() => {
  const primary = palette.value[0] ?? '#6b7280'
  return items.value.map((_, i) => {
    if (i < 3) return primary
    if (i < 10) return withAlpha(primary, 0.65)
    return withAlpha(primary, 0.35)
  })
})

const option = computed(() => ({
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'none' },
    ...theme.value.tooltip,
    formatter: (params: Array<{ seriesType: string; name: string; value: number }>) => {
      const bar = params.find((p) => p.seriesType === 'bar')
      if (!bar) return ''
      const pct = total.value > 0 ? ((bar.value / total.value) * 100).toFixed(1) : '0'
      return `<strong>${bar.name}</strong><br/>${bar.value} 本 · 占前 ${items.value.length} 位的 ${pct}%`
    },
  },
  legend: {
    data: ['本数', '累计占比'],
    top: 0,
    right: 0,
    itemWidth: 12,
    itemHeight: 8,
    ...theme.value.legend,
    textStyle: { ...theme.value.legend.textStyle, fontSize: 10 },
  },
  grid: { left: 2, right: 62, bottom: 6, top: 26, containLabel: true },
  dataZoom: [
    {
      type: 'inside',
      yAxisIndex: 0,
      startValue: 0,
      endValue: Math.min(19, items.value.length - 1),
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
  xAxis: [
    {
      ...theme.value.axis,
      type: 'value',
      minInterval: 1,
      axisLabel: { ...theme.value.axisLabelStyle, fontSize: 11 },
    },
    {
      ...theme.value.axis,
      type: 'value',
      position: 'top',
      min: 0,
      max: 100,
      axisLabel: {
        ...theme.value.axisLabelStyle,
        fontSize: 10,
        formatter: (v: number) => `${v}%`,
      },
      splitLine: { show: false },
      axisLine: { show: false },
    },
  ],
  yAxis: {
    ...theme.value.axis,
    type: 'category',
    data: items.value.map((x) => x.name),
    inverse: true, // 第一名在最上面
    axisLabel: { ...theme.value.axisLabelStyle, fontSize: 11, width: 130, overflow: 'truncate' },
  },
  series: [
    {
      name: '本数',
      type: 'bar',
      xAxisIndex: 0,
      data: items.value.map((x, i) => ({ value: x.count, itemStyle: { color: barColors.value[i] } })),
      barMaxWidth: 22,
      itemStyle: { borderRadius: [0, 3, 3, 0] },
      label: {
        show: true,
        position: 'right',
        fontSize: 10,
        color: theme.value.axisLabel,
        formatter: (p: { value: number }) => `${p.value}`,
      },
    },
    {
      name: '累计占比',
      type: 'line',
      xAxisIndex: 1,
      data: cumulative.value,
      symbol: 'circle',
      symbolSize: 4,
      // 中性色：折线是**参考线**，不该跟条形抢注意力（同上游）
      lineStyle: { color: theme.value.axisLabel, width: 1.5 },
      itemStyle: { color: theme.value.axisLabel },
    },
  ],
}))
</script>

<template>
  <ChartCard
    title="Top 50 作者"
    icon="users"
    :color-index="6"
    :empty="!items.length"
    empty-title="还没有作者数据"
    empty-description="作者来自 EPUB 的 dc:creator；没有的书不计入。"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
