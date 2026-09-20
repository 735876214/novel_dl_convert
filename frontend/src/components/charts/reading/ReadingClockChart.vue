<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 阅读时钟（上游 `ReadingClockChart.vue`）：24 小时极坐标柱状图，0 点在正上方，
 * 顺时针走一圈 —— 一天读得多的时段在哪，扫一眼就看得出。
 *
 * 与本项目的数据差异（**只照搬形态，不照搬数据契约**）：
 *
 * 1. 上游每根柱按 `byFormat` / `bySource` **堆叠**，配一个 BreakdownSelect 切换维度。
 *    本项目 `reading_sessions` 表没有 `source` 列、也没有按格式分桶 ⇒ 单序列，
 *    **不做那个选择器**（摆一个切不动的控件就是假交互）。
 * 2. 上游柱高与 tooltip 用**秒**（`readingSeconds / 60` → 分钟）。本项目的
 *    `db.hour_histogram` 给的是**会话次数**（不是时长）⇒ 柱高与文案一律用「次」，
 *    不拿次数冒充满是时长的分钟数。
 */
const MIN_EVENTS = 20

/** 24 小时刻度。中文界面走 24 小时制，不用上游的 12a/12p（那个对中文读者不直观） */
const HOUR_LABELS = Array.from({ length: 24 }, (_, h) => `${h}时`)

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const events = computed(() => props.data.hours)
const total = computed(() => events.value.reduce((sum, n) => sum + n, 0))
/** 样本太少时环形图会画成一根孤零零的柱子，看不出「分布」——照搬上游的阈值 */
const lowConfidence = computed(() => total.value > 0 && total.value < MIN_EVENTS)

const peak = computed(() => {
  const list = events.value
  if (!list.length) return null
  let best = 0
  for (let i = 1; i < list.length; i++) {
    if ((list[i] ?? 0) > (list[best] ?? 0)) best = i
  }
  return (list[best] ?? 0) > 0 ? { hour: best, count: list[best] ?? 0 } : null
})

const option = computed(() => {
  const t = theme.value
  const list = events.value
  if (!list.length || total.value < MIN_EVENTS) return {}

  return {
    color: palette.value,
    // 上游把 legend 放在底部；本项目单序列，legend 没有第二个条目可列 —— 去掉，
    // 信息量不丢（柱高含义由卡片标题与 tooltip 交代）。
    polar: { radius: ['18%', '74%'], center: ['50%', '46%'] },
    angleAxis: {
      type: 'category',
      data: HOUR_LABELS,
      startAngle: 82.5,
      clockwise: false,
      axisLabel: { fontSize: 10, color: t.axisLabel },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    radiusAxis: {
      min: 0,
      axisLabel: { show: false },
      axisLine: { show: false },
      splitLine: { show: false },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'none' },
      formatter: (params: Array<{ dataIndex: number }>) => {
        const p = params[0]
        if (!p) return ''
        const from = HOUR_LABELS[p.dataIndex]
        const to = HOUR_LABELS[(p.dataIndex + 1) % 24]
        const n = list[p.dataIndex] ?? 0
        return `<strong>${from} – ${to}</strong><br/>${n} 次会话`
      },
      ...t.tooltip,
    },
    series: [
      {
        type: 'bar',
        coordinateSystem: 'polar',
        data: list,
        itemStyle: { borderRadius: [2, 2, 0, 0] },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="阅读时钟"
    icon="clock"
    :color-index="5"
    :empty="!total"
    empty-title="还没有阅读记录"
    empty-description="按会话开始时段的分布统计，读过的书才会留下记录。"
  >
    <ChartEmptyState
      v-if="lowConfidence"
      icon="clock"
      title="数据不足"
      :description="`至少要有 ${MIN_EVENTS} 次阅读会话才画得出分布，目前 ${total} 次。`"
    />

    <div v-else class="flex h-full min-h-0 flex-col">
      <p v-if="peak" class="text-muted-foreground mb-1 shrink-0 text-center text-xs">
        高峰：<span class="text-foreground font-medium">{{ HOUR_LABELS[peak.hour] }}</span>
      </p>
      <div class="min-h-0 flex-1">
        <ChartFrame :option="option" />
      </div>
    </div>
  </ChartCard>
</template>
