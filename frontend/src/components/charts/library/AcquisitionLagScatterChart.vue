<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { chartShades, useChartTheme } from '@/lib/charts'

/**
 * 入库滞后（上游 `AcquisitionLagScatterChart.vue`）：x = 出版年、y = 出版到入库
 * 隔了多少年，点的大小 = 这个组合的本数。看的是「这个库里躺着多少旧书」。
 *
 * 与上游的三处差异：
 *
 * 1. **配色用单色深浅**（`chartShades`）而不是绿→黄→橙→红：本项目的深浅主题是
 *    运行时换 class，多色相在深色下会有一半档位糊在背景里（见 `lib/charts.ts`）。
 * 2. **未标注出版年的本数**用 `books.total − Σcount` 反推，写进脚注 —— 后端刻意
 *    没为它多给一个键（见 `core/stats.py`）。
 * 3. y 轴不写死 −5～30 的窗口（上游那样），按实际滞后范围给，否则旧书多的时候
 *    点会全挤在顶部一条线上。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const items = computed(() => props.data.acquisition_lag)

/** 出版年 = 入库年 − 滞后年 */
const publishedYears = computed(() => items.value.map((x) => x.added_year - x.lag_years))

/** 没标出版年的本数：画不出 x 坐标，只能进脚注 */
const unknownCount = computed(() => {
  const known = items.value.reduce((sum, x) => sum + x.count, 0)
  return Math.max(0, props.data.books.total - known)
})

const option = computed(() => {
  const t = theme.value
  const rows = items.value
  const shades = chartShades(palette.value)
  const years = publishedYears.value
  const lags = rows.map((x) => x.lag_years)
  const maxCount = Math.max(1, ...rows.map((x) => x.count))

  const minYear = Math.min(...years)
  const maxYear = Math.max(...years)
  const minLag = Math.min(...lags)
  const maxLag = Math.max(...lags)
  // 单点/单行数据时给一个最小跨度，否则 ECharts 会退化成一个点在正中间
  const yearPad = minYear === maxYear ? 1 : 0
  const lagPad = minLag === maxLag ? 1 : 0

  return {
    color: palette.value,
    tooltip: {
      trigger: 'item',
      formatter: (params: { value: number[] }) => {
        const [published, lag, count, added] = params.value
        return (
          `出版 ${published} 年<br/>入库 ${added} 年<br/>` +
          `滞后 <strong>${lag}</strong> 年<br/><strong>${count}</strong> 本`
        )
      },
      ...t.tooltip,
    },
    grid: { left: '5%', right: '4%', top: '12%', bottom: '16%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'value',
      min: minYear - yearPad,
      max: maxYear + yearPad,
      splitNumber: 4,
      axisLabel: {
        ...t.axisLabelStyle,
        fontSize: 10,
        formatter: (value: number) => String(Math.round(value)),
      },
      name: '出版年',
      nameLocation: 'middle',
      nameGap: 24,
      nameTextStyle: { fontSize: 10, color: t.axisLabel },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      min: minLag - lagPad,
      max: maxLag + lagPad,
      minInterval: 1,
      axisLabel: { ...t.axisLabelStyle, fontSize: 10 },
      name: '滞后（年）',
      nameLocation: 'middle',
      nameGap: 30,
      nameTextStyle: { fontSize: 10, color: t.axisLabel },
    },
    visualMap: {
      show: false,
      dimension: 1,
      min: minLag,
      max: maxLag,
      inRange: { color: shades },
    },
    series: [
      {
        type: 'scatter',
        // [出版年, 滞后年, 本数, 入库年] —— 第 4 位只进 tooltip
        data: rows.map((x) => [x.added_year - x.lag_years, x.lag_years, x.count, x.added_year]),
        symbolSize: (value: number[]) => 6 + ((value[2] ?? 1) / maxCount) * 14,
        itemStyle: { opacity: 0.85 },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="入库滞后"
    icon="clock"
    :color-index="6"
    :empty="!items.length"
    empty-title="还没有出版年数据"
    empty-description="这条图只收标了出版年的书 —— 不知道出版年 ≠ 滞后 0 年。"
    :note="items.length
      ? `点越大 = 这个组合的书越多${unknownCount ? ` · 另有 ${unknownCount} 本没标出版年，不在图上` : ''}`
      : ''"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
