<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 完成耗时（上游 `CompletionLatencyChart.vue`）：从开始读到读完隔了多少天，
 * 7 档直方图 + Median / P75 / P90 三个读数。
 *
 * 三处后端口径，这里只负责如实呈现（细节见 `core/stats.py` 文件头）：
 *
 * 1. **窗口 5 年**：长尾很长，「买了三年才读完」不该被窗口切掉。
 * 2. **分位为 `null` 时显示 `—`**，不是 0 —— 0 天会被读成「当天就读完」。
 * 3. **脏数据已跳过**（结束早于开始的日期被手工改过）：记成负数会把 P50 拉到 0 附近。
 *
 * 数据不足走空态（上游 `MIN_COMPLETIONS = 5`）：一两本书的分布就是一根孤零零的柱子。
 */
const MIN_COMPLETIONS = 5

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const stat = computed(() => props.data.completion_latency)
const total = computed(() => stat.value.total)
const lowConfidence = computed(() => total.value > 0 && total.value < MIN_COMPLETIONS)

/** 分位读数：`null` = 没有数据，显示 `—`（**不是** `0d`） */
function metric(value: number | null): string {
  return value == null ? '—' : `${value} 天`
}

const metrics = computed(() => [
  { label: '中位', value: metric(stat.value.median_days) },
  { label: 'P75', value: metric(stat.value.p75_days) },
  { label: 'P90', value: metric(stat.value.p90_days) },
])

const option = computed(() => {
  const t = theme.value
  const buckets = stat.value.buckets
  if (!buckets.length || lowConfidence.value) return {}

  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number }>) => {
        const p = params[0]
        const b = p ? buckets[p.dataIndex] : undefined
        return b ? `${b.label}: <strong>${b.count}</strong> 本` : ''
      },
      ...t.tooltip,
    },
    grid: { left: '4%', right: '3%', bottom: '8%', top: '10%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: buckets.map((b) => b.label),
      axisLabel: { ...t.axisLabelStyle, fontSize: 10, rotate: 45 },
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
        type: 'bar',
        data: buckets.map((b) => b.count),
        barMaxWidth: 26,
        itemStyle: { borderRadius: [3, 3, 0, 0] },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="完成耗时"
    icon="clock"
    :color-index="2"
    :empty="!total"
    empty-title="还没有读完的书"
    empty-description="从「开始读」到「读完」隔了多少天；只看两个时间都记着的书。"
    :note="total ? `共 ${total} 本可测耗时 · 窗口取近 5 年` : ''"
  >
    <ChartEmptyState
      v-if="lowConfidence"
      icon="clock"
      title="数据不足"
      :description="`至少要有 ${MIN_COMPLETIONS} 本读完才看得出分布，目前 ${total} 本。`"
    />

    <div v-else class="flex h-full min-h-0 flex-col gap-2">
      <div class="grid shrink-0 grid-cols-3 gap-2 text-xs">
        <div v-for="m in metrics" :key="m.label" class="rounded-md border border-border px-2 py-1">
          <span class="text-muted-foreground">{{ m.label }}</span>
          <div class="text-foreground text-sm font-semibold">{{ m.value }}</div>
        </div>
      </div>
      <div class="min-h-0 flex-1">
        <ChartFrame :option="option" />
      </div>
    </div>
  </ChartCard>
</template>
