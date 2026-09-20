<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 会话形态（上游 `SessionArchetypesChart.vue`）：x = 一天内的时刻、y = 这次读了
 * 多少分钟，按星期几分色。回答「我几点读得多、周末是不是读得久」。
 *
 * 三处后端口径（见 `core/stats.py`）：
 *
 * 1. **只收 5 分钟以上的会话**（`_ARCHETYPE_MIN_SECONDS = 300`）：翻两页就退出的
 *    会话会在 y 轴底部铺成一条噪声带，把真正的分布盖掉。
 * 2. **按开始时刻定档**，不是结束时刻 —— 跨零点的会话（23:50 开始读到 00:10）
 *    按结束时刻会被算到第二天。
 * 3. **窗口 365 天、最多 2000 条**：`hour` 是小数小时（9:30 → 9.5），
 *    `weekday` 里 **0 = 周日**（与「最爱阅读日」那张图同一套下标）。
 *
 * 与上游的一处差异：**颜色取自调色板**而不是上游写死的 7 个十六进制色，
 * 这样跟随主题与强调色（上游那套在深色主题下有一半糊在背景里）。
 */
const DAY_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const items = computed(() => props.data.session_archetypes)

function formatHour(hour: number): string {
  const total = Math.round(hour * 60)
  const h = Math.floor(total / 60) % 24
  const m = total % 60
  return m === 0 ? `${h}:00` : `${h}:${String(m).padStart(2, '0')}`
}

function formatMinutes(minutes: number): string {
  const rounded = Math.round(minutes)
  if (rounded < 60) return `${rounded} 分钟`
  return `${(rounded / 60).toFixed(1)} 小时`
}

const option = computed(() => {
  const t = theme.value
  const rows = items.value
  if (!rows.length) return {}

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: {
        seriesName: string
        data: { value: [number, number]; name: string }
      }) => {
        const [hour, mins] = params.data.value
        return `<strong>${params.seriesName} ${formatHour(hour)}</strong><br/>${formatMinutes(mins)}<br/>${params.data.name}`
      },
      ...t.tooltip,
    },
    legend: { type: 'scroll', bottom: 0, itemWidth: 10, itemHeight: 10, ...t.legend },
    grid: { left: '3%', right: '4%', bottom: '18%', top: 8, containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      max: 24,
      interval: 3,
      axisLabel: {
        ...t.axisLabelStyle,
        fontSize: 10,
        formatter: (value: number) => `${value}:00`,
      },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      name: '时长（分钟）',
      nameLocation: 'middle',
      nameGap: 34,
      nameTextStyle: { fontSize: 10, color: t.axisLabel },
      axisLabel: { ...t.axisLabelStyle, fontSize: 10 },
    },
    series: DAY_NAMES.map((name, dow) => ({
      name,
      type: 'scatter',
      symbolSize: 6,
      itemStyle: { color: palette.value[dow % palette.value.length], opacity: 0.7 },
      data: rows
        .filter((d) => d.weekday === dow)
        .map((d) => ({ name: `${formatMinutes(d.minutes)}`, value: [d.hour, d.minutes] })),
    })),
  }
})
</script>

<template>
  <ChartCard
    title="会话形态"
    icon="layers"
    :color-index="8"
    :empty="!items.length"
    empty-title="还没有够长的会话"
    empty-description="只看 5 分钟以上的会话、近 365 天；比这短的记下来只是一条噪声带。"
    :note="items.length ? `共 ${items.length} 次会话 · 按开始时刻定档（跨零点的不算到第二天）` : ''"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
