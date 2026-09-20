<script setup lang="ts">
import { computed, ref } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 入库节奏 · 全时段（上游 `BooksAddedOverTimeChart.vue`）：按月 / 按年的柱图。
 *
 * 与本项目既有卡片「入库节奏」的分工（**标题也据此避重名，改叫「入库趋势」**）：
 * 那张看**近 N 天**的逐日细节奏（跟随页首的窗口选择器），这张图看**全时段**的月度 /
 * 年度走势。两者口径都是成品文件 mtime。
 *
 * 粒度与时间范围是**页内状态**，不持久化 —— 与页首「统计范围」选择器一致
 * （那个也不持久化）。上游把这两个存进 Configure 偏好里，本项目等 Configure
 * 落地时再一并考虑收纳。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

type Granularity = 'monthly' | 'yearly'
type RangeKey = 'all-time' | 'last-5-years' | 'last-year'

const granularity = ref<Granularity>('monthly')
const range = ref<RangeKey>('all-time')

const GRANULARITY_OPTIONS: Array<{ value: Granularity; label: string }> = [
  { value: 'monthly', label: '月度' },
  { value: 'yearly', label: '年度' },
]

const RANGE_OPTIONS: Array<{ value: RangeKey; label: string }> = [
  { value: 'all-time', label: '全部时间' },
  { value: 'last-5-years', label: '近 5 年' },
  { value: 'last-year', label: '近 12 个月' },
]

// 页面打开的那一刻算「现在」——统计页本来就是一份快照，不必逐分钟重算
const now = new Date()
const currentYear = now.getFullYear()

/** 先按时间范围裁，再按粒度聚合 */
const series = computed(() => {
  let rows = props.data.added_monthly

  if (range.value === 'last-5-years') {
    rows = rows.filter((r) => r.year >= currentYear - 4)
  } else if (range.value === 'last-year') {
    // 最近 12 个自然月（含当月）：用月初做比较，避开月末日期的坑
    const cutoff = new Date(currentYear, now.getMonth() - 11, 1)
    rows = rows.filter((r) => new Date(r.year, r.month - 1, 1) >= cutoff)
  }

  if (granularity.value === 'yearly') {
    const byYear = new Map<number, number>()
    for (const r of rows) byYear.set(r.year, (byYear.get(r.year) ?? 0) + r.count)
    return [...byYear.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([year, count]) => ({ label: String(year), count }))
  }

  return rows.map((r) => ({ label: `${r.year}-${String(r.month).padStart(2, '0')}`, count: r.count }))
})

const total = computed(() => series.value.reduce((sum, r) => sum + r.count, 0))

const option = computed(() => {
  const t = theme.value
  const rows = series.value
  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ name: string; value: number }>) => {
        const p = params[0]
        return p ? `${p.name}：<strong>${p.value}</strong> 本` : ''
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '4%', bottom: '8%', top: '8%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: rows.map((r) => r.label),
      // 标签太多就隔几个显示一个（照搬上游的间隔算法）
      axisLabel: {
        ...t.axisLabelStyle,
        fontSize: 11,
        rotate: 45,
        interval: Math.max(0, Math.floor(rows.length / 8) - 1),
      },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      minInterval: 1,
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        data: rows.map((r) => r.count),
        itemStyle: { borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 40,
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="入库趋势"
    icon="shelf"
    :color-index="3"
    :empty="!series.length"
    empty-title="还没有入库记录"
    empty-description="按成品文件的修改时间统计。"
    :note="series.length ? `共 ${total} 本 · ${granularity === 'yearly' ? '按年' : '按月'}聚合` : ''"
  >
    <template #controls>
      <div class="border-border flex rounded-md border text-xs">
        <button
          v-for="(g, i) in GRANULARITY_OPTIONS"
          :key="g.value"
          type="button"
          class="cursor-pointer px-2 py-1 transition-colors"
          :class="[
            i === 0 ? 'rounded-l-md' : 'rounded-r-md',
            granularity === g.value
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:text-foreground',
          ]"
          @click="granularity = g.value"
        >
          {{ g.label }}
        </button>
      </div>

      <select
        v-model="range"
        class="border-border text-muted-foreground hover:text-foreground cursor-pointer rounded-md border bg-transparent px-2 py-1 text-xs outline-none transition-colors"
      >
        <option v-for="r in RANGE_OPTIONS" :key="r.value" :value="r.value">{{ r.label }}</option>
      </select>
    </template>

    <ChartFrame :option="option" />
  </ChartCard>
</template>
