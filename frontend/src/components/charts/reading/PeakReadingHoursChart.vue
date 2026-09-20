<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 高峰时段（上游 `PeakReadingHoursChart.vue`）：与「阅读时钟」同一份数据（`hours`）
 * 的直角版 —— 环形看形状，直角看精确读数与小差异，上游也是两张图并列摆着。
 *
 * 单位同阅读时钟：本项目给的是**会话次数**不是时长（见那张图的注释），故 y 轴写
 * 「次」而不是上游的 `Minutes`。
 */
const MIN_EVENTS = 20

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const events = computed(() => props.data.hours)
const total = computed(() => events.value.reduce((sum, n) => sum + n, 0))
const lowConfidence = computed(() => total.value > 0 && total.value < MIN_EVENTS)

const option = computed(() => {
  const t = theme.value
  const list = events.value
  if (!list.length || total.value < MIN_EVENTS) return {}

  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ axisValue: string; data: number; dataIndex: number }>) => {
        const p = params[0]
        if (!p) return ''
        const n = list[p.dataIndex] ?? 0
        return `<strong>${p.axisValue}</strong><br/>${n} 次会话`
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '3%', bottom: 36, top: '8%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: list.map((_, h) => `${String(h).padStart(2, '0')}:00`),
      // 24 个刻度全显示会糊成一片，隔一个显示一个（照搬上游）
      axisLabel: { ...t.axisLabelStyle, fontSize: 11, interval: 1 },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      minInterval: 1,
      name: '会话数',
      nameTextStyle: { fontSize: 11, color: t.axisLabel },
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        data: list,
        barMaxWidth: 24,
        itemStyle: { borderRadius: [3, 3, 0, 0] },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="高峰时段"
    icon="bell"
    :color-index="5"
    :empty="!total"
    empty-title="还没有阅读记录"
    empty-description="与「阅读时钟」同一份数据，直角坐标更适合看精确读数。"
  >
    <ChartEmptyState
      v-if="lowConfidence"
      icon="bell"
      title="数据不足"
      :description="`至少要有 ${MIN_EVENTS} 次阅读会话，目前 ${total} 次。`"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
