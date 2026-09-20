<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 最爱阅读日（上游 `FavoriteReadingDaysChart.vue`）：按星期几的**平均每日阅读时长**。
 *
 * 为什么是「日均」而不是「累计」：统计窗口（365 天）未必整除 7 天，直接比累计时长
 * 会造出「某个星期几总是最多」的假信号。上游在前端自己数窗口里各星期几出现几天，
 * 本项目**后端已经给了** `days`（`db.weekday_histogram`），直接用 —— 口径也才和
 * 后端一致（上游用 UTC 数，本项目用本地日，见后端注释）。
 *
 * 索引 0 = 周日（与 `Date.getDay()` 一致），后端也是这个口径。
 */
const MIN_EVENTS = 14

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const rows = computed(() => props.data.weekdays)
const totalEvents = computed(() => rows.value.reduce((sum, r) => sum + r.events, 0))
const lowConfidence = computed(() => totalEvents.value > 0 && totalEvents.value < MIN_EVENTS)

/** 平均每日分钟（不足一天也算一天，避免除以 0） */
const avgMinutes = computed(() =>
  rows.value.map((r) => Number((r.seconds / 60 / Math.max(1, r.days)).toFixed(1))),
)

const option = computed(() => {
  const t = theme.value
  const list = rows.value
  if (!list.length || totalEvents.value < MIN_EVENTS) return {}

  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ axisValue: string; dataIndex: number }>) => {
        const p = params[0]
        if (!p) return ''
        const r = list[p.dataIndex]
        if (!r) return ''
        const avg = avgMinutes.value[p.dataIndex] ?? 0
        const totalMin = Math.round(r.seconds / 60)
        return (
          `<strong>${p.axisValue}</strong><br/>日均 ${avg} 分<br/>` +
          `累计 ${totalMin} 分 · ${r.events} 次会话<br/>` +
          `<span style="opacity:0.65;font-size:11px">窗口内出现 ${r.days} 天</span>`
        )
      },
      ...t.tooltip,
    },
    grid: { left: '5%', right: '3%', bottom: 36, top: '8%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: WEEKDAYS,
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      name: '日均分钟',
      nameTextStyle: { fontSize: 11, color: t.axisLabel },
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        data: avgMinutes.value,
        barMaxWidth: 30,
        itemStyle: { borderRadius: [3, 3, 0, 0] },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="最爱阅读日"
    icon="star"
    :color-index="6"
    :empty="!rows.length"
    empty-title="还没有阅读记录"
    empty-description="按会话开始时间落在星期几统计，看的是最近 365 天。"
  >
    <ChartEmptyState
      v-if="lowConfidence"
      icon="star"
      title="数据不足"
      :description="`至少要有 ${MIN_EVENTS} 次阅读会话才比得出偏好，目前 ${totalEvents} 次。`"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
