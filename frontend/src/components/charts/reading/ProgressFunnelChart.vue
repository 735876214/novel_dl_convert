<script setup lang="ts">
import { computed, ref } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 进度漏斗（上游 `ProgressFunnelChart.vue`）：开始 → 25% → 50% → 75% → 读完
 * 五档的留存，三种看法（相对开始的比例 / 本数 / 相邻档流失）。
 *
 * 口径见后端 `stats.py` 文件头：**走进度、不走真实状态** —— 真实状态允许把一本
 * 20% 的书手动标成 finished，跟着它走会出现「后档比前档多」的畸形图。
 *
 * 与本项目对齐的两处：
 *
 * 1. 上游用 shadcn 的 DropdownMenu 切模式，本项目没有那套组件 ⇒ 用原生 `<select>`，
 *    与同页「入库趋势」的时间范围选择器同款（不新造第二套控件样式）。
 * 2. 上游还有一块「与上一周期对比」（`data.previous`）。本项目后端只给当前值，
 *    没有可比的历史快照 ⇒ **不做**，不编造。
 */
const MIN_STARTED = 10

type FunnelMode = 'percent' | 'counts' | 'dropoff'

const MODE_OPTIONS: Array<{ value: FunnelMode; label: string }> = [
  { value: 'percent', label: '占开始的比例' },
  { value: 'counts', label: '本数' },
  { value: 'dropoff', label: '相邻档流失' },
]

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const mode = ref<FunnelMode>('percent')

const stages = computed(() => {
  const f = props.data.progress_funnel
  const raw = [
    { key: 'started', label: '开始', count: f.started },
    { key: 'reached25', label: '25%', count: f.reached25 },
    { key: 'reached50', label: '50%', count: f.reached50 },
    { key: 'reached75', label: '75%', count: f.reached75 },
    { key: 'completed', label: '读完', count: f.completed },
  ] as const

  return raw.map((stage, index) => {
    const prev = index === 0 ? stage : (raw[index - 1] ?? stage)
    return {
      ...stage,
      pct: f.started > 0 ? (stage.count / f.started) * 100 : 0,
      drop: index === 0 ? 0 : Math.max(0, prev.count - stage.count),
      fromLabel: prev.label,
    }
  })
})

const started = computed(() => props.data.progress_funnel.started)
const isEmpty = computed(() => started.value === 0)
const lowConfidence = computed(() => started.value > 0 && started.value < MIN_STARTED)
/** 五档全等 ⇒ 漏斗退化成五个一样宽的方块，画出来没有信息量 */
const isFlat = computed(() => stages.value.every((s) => s.count === started.value))

const transitions = computed(() =>
  stages.value.slice(1).map((s) => ({ label: `${s.fromLabel} → ${s.label}`, drop: s.drop })),
)

const option = computed(() => {
  const t = theme.value
  if (isEmpty.value || lowConfidence.value || isFlat.value) return {}

  if (mode.value === 'dropoff') {
    return {
      color: palette.value,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: Array<{ axisValue: string; data: number }>) => {
          const p = params[0]
          return p ? `${p.axisValue}<br/>流失 <strong>${p.data}</strong> 本` : ''
        },
        ...t.tooltip,
      },
      grid: { left: '10%', right: '8%', bottom: '12%', top: '14%', containLabel: true },
      xAxis: {
        ...t.axis,
        type: 'value',
        min: 0,
        minInterval: 1,
        axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
      },
      yAxis: {
        ...t.axis,
        type: 'category',
        data: transitions.value.map((x) => x.label),
        inverse: true,
        axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
      },
      series: [
        {
          type: 'bar',
          data: transitions.value.map((x) => x.drop),
          barWidth: 16,
          itemStyle: { borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: 'right', formatter: '{c}', fontSize: 11 },
        },
      ],
    }
  }

  const rows = stages.value.map((s) => ({
    name: s.label,
    value: mode.value === 'counts' ? s.count : Number(s.pct.toFixed(1)),
    rawCount: s.count,
    pct: Number(s.pct.toFixed(1)),
  }))

  return {
    color: palette.value,
    tooltip: {
      trigger: 'item',
      formatter: (params: { data: { name: string; rawCount: number; pct: number } }) => {
        const d = params.data
        return `${d.name}<br/><strong>${d.rawCount}</strong> 本（占开始 ${d.pct.toFixed(1)}%）`
      },
      ...t.tooltip,
    },
    series: [
      {
        type: 'funnel',
        sort: 'none',
        top: 18,
        bottom: 16,
        left: '16%',
        width: '68%',
        gap: 6,
        min: 0,
        max: mode.value === 'counts' ? Math.max(...stages.value.map((s) => s.count), 1) : 100,
        minSize: '28%',
        maxSize: '100%',
        // 漏斗块本身按序列色深浅分档，文字压在上面 —— 用白色保证在两套主题下都读得出
        label: {
          show: true,
          position: 'inside',
          fontSize: 11,
          color: '#fff',
          formatter: (params: { data: { name: string; rawCount: number; pct: number } }) =>
            mode.value === 'counts'
              ? `${params.data.name}：${params.data.rawCount}`
              : `${params.data.name}：${params.data.pct.toFixed(1)}%`,
        },
        labelLine: { show: false },
        itemStyle: { borderColor: 'rgba(255,255,255,0.12)', borderWidth: 1, borderRadius: 3 },
        data: rows,
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="进度漏斗"
    icon="layers"
    :color-index="10"
    :empty="isEmpty"
    empty-title="还没有开始读的书"
    empty-description="按阅读进度分档统计，与书目状态无关。"
  >
    <template #controls>
      <select
        v-model="mode"
        class="border-border text-muted-foreground hover:text-foreground cursor-pointer rounded-md border bg-transparent px-2 py-1 text-xs outline-none transition-colors"
      >
        <option v-for="m in MODE_OPTIONS" :key="m.value" :value="m.value">{{ m.label }}</option>
      </select>
    </template>

    <ChartEmptyState
      v-if="lowConfidence"
      icon="layers"
      title="数据不足"
      :description="`至少要有 ${MIN_STARTED} 本开始读过的书，目前 ${started} 本。`"
    />
    <ChartEmptyState
      v-else-if="isFlat"
      icon="layers"
      title="还没有分层"
      description="所有开始读过的书都停在同一档，漏斗还看不出留存差异。"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
