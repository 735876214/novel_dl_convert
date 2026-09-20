<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 书库体检（上游 `LibraryIntegrityGaugeChart.vue`）：半环仪表盘 + 三格覆盖率。
 *
 * 口径与保留下方那张明细卡**完全一致**（都是 `StatsOverview.integrity`），两张的
 * 分工是：图给「一眼看健康度」的仪表，卡给「缺什么、各几本、照着去修」的计数明细。
 * 卡片第 33 期**刻意保留** —— 它有图给不了的东西（可照修的 5 类计数 + 补数据的
 * 去处），不是没迁干净的残留。
 *
 * ⚠️ 三格的 `Metadata` 语义**与上游不同**：上游数的是「有元数据行」的书，本项目
 * 是「完整度评分 ≥ 70」，故这里用本项目的中文口径（与明细卡逐字一致），避免两个
 * 都叫 Metadata 的数字对不上。综合分是三项的算术平均（后端 `stats.py` 算好）。
 */
const props = defineProps<{ data: StatsOverview }>()

const { theme } = useChartTheme()

const integrity = computed(() => props.data.integrity)
const totalBooks = computed(() => integrity.value.total_books ?? 0)

/** 三格：标签与明细卡的 `GAUGES` 逐字一致 */
const stats = computed(() => {
  const g = integrity.value
  return [
    { label: '文件在位', percent: g.present_percent, ratio: `${g.present} / ${g.total_books}` },
    { label: '可解析', percent: g.primary_percent, ratio: `${g.primary} / ${g.total_books}` },
    { label: '元数据达标', percent: g.metadata_percent, ratio: `${g.metadata} / ${g.total_books}` },
  ]
})

/** 分档配色（照上游）：红 → 橙 → 黄 → 绿 → 蓝 */
function scoreColor(score: number): string {
  if (score < 20) return '#ef4444'
  if (score < 40) return '#f97316'
  if (score < 60) return '#eab308'
  if (score < 80) return '#22c55e'
  return '#3b82f6'
}

const option = computed(() => {
  if (totalBooks.value === 0) return {}
  const active = scoreColor(integrity.value.score)

  return {
    tooltip: {
      ...theme.value.tooltip,
      formatter: () =>
        [
          `<strong>完整度 ${integrity.value.score}%</strong>`,
          `文件在位：${integrity.value.present} / ${integrity.value.total_books}`,
          `可解析：${integrity.value.primary} / ${integrity.value.total_books}`,
          `元数据达标：${integrity.value.metadata} / ${integrity.value.total_books}`,
        ].join('<br/>'),
    },
    series: [
      {
        type: 'gauge',
        min: 0,
        max: 100,
        startAngle: 210,
        endAngle: -30,
        center: ['50%', '62%'],
        radius: '96%',
        splitNumber: 5,
        axisLine: {
          lineStyle: {
            width: 14,
            color: [
              [0.2, '#ef4444'],
              [0.4, '#f97316'],
              [0.6, '#eab308'],
              [0.8, '#22c55e'],
              [1, '#3b82f6'],
            ],
          },
        },
        progress: { show: false },
        pointer: { show: true, width: 4, length: '70%', itemStyle: { color: active } },
        axisTick: { show: false },
        splitLine: { distance: -16, length: 6 },
        axisLabel: { distance: -24, fontSize: 10, color: theme.value.axisLabel },
        detail: {
          valueAnimation: true,
          formatter: '{value}%',
          fontSize: 24,
          fontWeight: 700,
          color: active,
          offsetCenter: [0, '22%'],
        },
        title: { show: true, offsetCenter: [0, '46%'], fontSize: 11, color: theme.value.axisLabel },
        data: [{ value: integrity.value.score, name: '完整度' }],
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="书库体检"
    icon="wrench"
    :color-index="4"
    :empty="totalBooks === 0"
    empty-title="书库还是空的"
    empty-description="入库后这里按文件在位、可解析、元数据达标三项算一个综合分。"
    note="综合分 = 三项覆盖率的算术平均；下方「书库体检」卡片列的是可照修的计数明细。"
  >
    <div class="flex h-full flex-col">
      <div class="min-h-0 flex-1">
        <ChartFrame :option="option" />
      </div>
      <div class="mt-1 grid shrink-0 grid-cols-3 gap-1.5">
        <div
          v-for="x in stats"
          :key="x.label"
          class="rounded-md border border-border/60 bg-muted/40 px-1.5 py-1 text-center"
        >
          <p class="truncate text-[10px] leading-none text-muted-foreground">{{ x.label }}</p>
          <p class="mt-1 text-sm leading-none font-semibold text-foreground tabular-nums">
            {{ x.percent }}%
          </p>
          <p class="mt-0.5 text-[10px] leading-none text-muted-foreground tabular-nums">
            {{ x.ratio }}
          </p>
        </div>
      </div>
    </div>
  </ChartCard>
</template>
