<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 读完时间轴（上游 `CompletionTimelineChart.vue`）：按月的读完成本数折线。
 *
 * 两处与本项目对齐：
 *
 * 1. 月份标签用 `2024-01`（上游是 `Jan 2024`）—— 与统计页既有的「入库趋势」同一口径，
 *    中文界面下也更省横向空间（x 轴还要 rotate 40°）。
 * 2. **补月份空洞**：后端只返回有读完记录的月份，直接连点会把「3 月读完、9 月又读完」
 *    画成一条上升斜线，像 4–8 月也有产出。中间那些月补 0 才是实话。
 */
const MIN_COMPLETIONS = 3

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

/** 补齐空洞后的序列（年月升序） */
const series = computed(() => {
  const raw = props.data.completion_monthly
  if (!raw.length) return []
  const byMonth = new Map(raw.map((p) => [p.year * 12 + (p.month - 1), p.count]))
  const first = raw[0]
  const last = raw[raw.length - 1]
  if (!first || !last) return []
  const start = first.year * 12 + (first.month - 1)
  const end = last.year * 12 + (last.month - 1)
  const out: Array<{ label: string; count: number }> = []
  for (let k = start; k <= end; k++) {
    const y = Math.floor(k / 12)
    const m = (k % 12) + 1
    out.push({ label: `${y}-${String(m).padStart(2, '0')}`, count: byMonth.get(k) ?? 0 })
  }
  return out
})

const total = computed(() => props.data.completion_monthly.reduce((sum, p) => sum + p.count, 0))
const lowConfidence = computed(() => total.value > 0 && total.value < MIN_COMPLETIONS)

const option = computed(() => {
  const t = theme.value
  const rows = series.value
  if (!rows.length || total.value < MIN_COMPLETIONS) return {}

  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ axisValue: string; data: number }>) => {
        const p = params[0]
        return p ? `${p.axisValue}<br/><strong>${p.data}</strong> 本读完` : ''
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '3%', bottom: '8%', top: '6%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: rows.map((r) => r.label),
      boundaryGap: false,
      axisLabel: {
        ...t.axisLabelStyle,
        fontSize: 11,
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
        data: rows.map((r) => r.count),
        smooth: 0.2,
        showSymbol: false,
        areaStyle: { opacity: 0.2 },
        lineStyle: { width: 2 },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="读完时间轴"
    icon="check"
    :color-index="8"
    :empty="!total"
    empty-title="还没有读完的书"
    empty-description="书目状态标为「读完」时记下时间，按这个时间统计。"
    :note="total ? `共读完 ${total} 本` : ''"
  >
    <ChartEmptyState
      v-if="lowConfidence"
      icon="check"
      title="数据不足"
      :description="`至少要有 ${MIN_COMPLETIONS} 本读完才画得出趋势，目前 ${total} 本。`"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
