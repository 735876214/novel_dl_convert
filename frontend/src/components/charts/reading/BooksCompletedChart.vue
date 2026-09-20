<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 读完累计（上游 `BooksCompletedChart.vue`）：按月读完数的**累计**折线，
 * 看的是「一年下来攒了多少本」。
 *
 * 与同屏既有的「读完时间轴」的分工（两张都吃 `completion_monthly`）：
 * 那张画的是**每月新增**（看节奏：某个月是不是停了），这张画的是**累计**
 * （看总量走势）。同一个数据的两种读法，上游也是两张图。
 *
 * 两处与本项目对齐的做法：
 *
 * 1. **补月份空洞**（照抄「读完时间轴」里那段）：后端只返回有读完记录的月份，
 *    直接连点会把「3 月读完、9 月又读完」画成一条匀速上升的斜线，像 4–8 月也有产出。
 * 2. **数据不足走空态**：上游是 `MIN_COMPLETIONS = 2`，一本都没读完时累计线恒为 0，
 *    画出来是一条贴着 x 轴的直线，读不出东西。
 */
const MIN_COMPLETIONS = 2

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const total = computed(() => props.data.completion_monthly.reduce((sum, p) => sum + p.count, 0))
const lowConfidence = computed(() => total.value < MIN_COMPLETIONS)

/** 补齐空洞后的「年月升序 + 累计值」序列 */
const series = computed(() => {
  const raw = props.data.completion_monthly
  if (!raw.length) return []
  const first = raw[0]
  const last = raw[raw.length - 1]
  if (!first || !last) return []
  const byMonth = new Map(raw.map((p) => [p.year * 12 + (p.month - 1), p.count]))
  const start = first.year * 12 + (first.month - 1)
  const end = last.year * 12 + (last.month - 1)
  const out: Array<{ label: string; value: number; count: number }> = []
  let running = 0
  for (let k = start; k <= end; k++) {
    const count = byMonth.get(k) ?? 0
    running += count
    const y = Math.floor(k / 12)
    const m = (k % 12) + 1
    out.push({ label: `${y}-${String(m).padStart(2, '0')}`, value: running, count })
  }
  return out
})

const option = computed(() => {
  const t = theme.value
  const rows = series.value
  if (!rows.length || lowConfidence.value) return {}

  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number }>) => {
        const p = params[0]
        const row = p ? rows[p.dataIndex] : undefined
        if (!row) return ''
        return `${row.label}<br/>累计 <strong>${row.value}</strong> 本 · 当月 ${row.count} 本`
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '4%', bottom: '8%', top: '8%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: rows.map((r) => r.label),
      boundaryGap: false,
      axisLabel: {
        ...t.axisLabelStyle,
        fontSize: 10,
        rotate: 40,
        interval: Math.max(0, Math.floor(rows.length / 10) - 1),
      },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      minInterval: 1,
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    series: [
      {
        type: 'line',
        data: rows.map((r) => r.value),
        // 与上游一致：略带平滑的累计线 + 淡面积，像一条「攒书曲线」
        smooth: 0.3,
        showSymbol: false,
        lineStyle: { width: 2.5 },
        areaStyle: { opacity: 0.15 },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="读完累计"
    icon="check"
    :color-index="3"
    :empty="!total"
    empty-title="还没有读完的书"
    empty-description="书目状态标为「读完」时记下时间，按这个时间累计。"
    :note="total ? `累计读完 ${total} 本 · 逐月的「新增」见「读完时间轴」` : ''"
  >
    <ChartEmptyState
      v-if="lowConfidence"
      icon="check"
      title="数据不足"
      :description="`至少要有 ${MIN_COMPLETIONS} 本读完才画得出累计曲线，目前 ${total} 本。`"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
