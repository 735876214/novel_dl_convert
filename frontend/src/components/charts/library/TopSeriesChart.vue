<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * Top 系列（上游 `TopSeriesChart.vue`）：横向条形 + 累计占比折线（双 x 轴）。
 *
 * 与 `TopAuthorsChart` **同构**（同样的双轴与三档配色，照上游也是两份文件）——
 * 改其中一张的轴/配色时记得另一张。两处差异：
 *
 * - 标题写 50（本项目固定 `top=50`，上游是 50，一致）；
 * - 左侧类目标签宽 150（系列名普遍比人名长），故 `grid.right` 也留得更宽。
 *
 * 与保留的明细卡（「Top 系列」）是**互补关系**：卡片那侧每行可点，跳到 `/series/:name`；
 * 图这侧给累计占比曲线的全局视角。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

/** 按本数降序；同数按系列名排，避免每次刷新条形顺序乱跳 */
const items = computed(() =>
  [...(props.data.series.top ?? [])].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)),
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

/** 条形配色分三档（照上游）：前 3 名满色、4–10 名 65%、其余 35% */
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
      return `<strong>${bar.name}</strong><br/>${bar.value} 本 · 占前 ${items.value.length} 个的 ${pct}%`
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
  grid: { left: 2, right: 68, bottom: 6, top: 26, containLabel: true },
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
    axisLabel: { ...theme.value.axisLabelStyle, fontSize: 11, width: 150, overflow: 'truncate' },
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
      lineStyle: { color: theme.value.axisLabel, width: 1.5 },
      itemStyle: { color: theme.value.axisLabel },
    },
  ],
}))
</script>

<template>
  <ChartCard
    title="Top 50 系列"
    icon="layers"
    :color-index="8"
    :empty="!items.length"
    empty-title="还没有系列数据"
    empty-description="系列来自 EPUB 的 calibre:series 或标题里的系列名。"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
