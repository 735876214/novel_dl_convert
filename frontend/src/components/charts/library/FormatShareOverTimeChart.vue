<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 格式占比随时间（上游 `FormatShareOverTimeChart.vue`）：按月的**堆叠面积**，
 * 看的是「这个库什么时候开始收 EPUB、什么时候混进了 PDF / 有声书」。
 *
 * 与上游的两处对齐：
 *
 * 1. **纵轴是占比（0–100%）而不是本数** —— 本数走势已经由「入库趋势」那张图回答了；
 *    这里要回答的是构成变化，用本数会被入库总量的起伏带偏。
 * 2. 后端只给计数、占比在**前端**算（见 `core/stats.py` 的注释）：分母是「当月入库
 *    总数」，后端先折算成百分比的话，tooltip 里就没法同时给出本数了。
 *
 * 月份标签用 `2024-01`（上游是 `Jan 2024`）—— 与本项目「入库趋势」「读完时间轴」
 * 同一口径。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

/** 月份键（升序）与每月的格式 → 计数 */
const byMonth = computed(() => {
  const counts = new Map<string, Map<string, number>>()
  for (const item of props.data.format_share_monthly) {
    const key = `${item.year}-${String(item.month).padStart(2, '0')}`
    const inner = counts.get(key) ?? new Map<string, number>()
    inner.set(item.format, (inner.get(item.format) ?? 0) + item.count)
    counts.set(key, inner)
  }
  return counts
})

const months = computed(() => [...byMonth.value.keys()].sort())
const formats = computed(() => {
  const out = new Set<string>()
  for (const inner of byMonth.value.values()) {
    for (const f of inner.keys()) out.add(f)
  }
  return [...out].sort()
})

const totalBooks = computed(() =>
  props.data.format_share_monthly.reduce((sum, x) => sum + x.count, 0),
)

const option = computed(() => {
  const t = theme.value
  const keys = months.value
  const list = formats.value

  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number; marker: string; seriesName: string }>) => {
        const first = params[0]
        if (!first) return ''
        const key = keys[first.dataIndex]
        const inner = key ? byMonth.value.get(key) : undefined
        if (!key || !inner) return ''
        const total = [...inner.values()].reduce((a, b) => a + b, 0)
        // 当月一本都没入库的格式不列（堆叠图里它们的占比是 0，列出来只是噪声）；
        // 同一个分母，故按本数降序排 = 按占比降序排
        const rows = params
          .map((p) => ({ marker: p.marker, name: p.seriesName, count: inner.get(p.seriesName) ?? 0 }))
          .filter((r) => r.count > 0)
          .sort((a, b) => b.count - a.count)
          .map(
            (r) =>
              `${r.marker}${r.name}: <strong>${((r.count / total) * 100).toFixed(1)}%</strong>（${r.count} 本）`,
          )
        return `${key}（${total} 本）<br/>${rows.join('<br/>')}`
      },
      ...t.tooltip,
    },
    legend: { type: 'scroll', top: 0, itemWidth: 12, itemHeight: 8, ...t.legend },
    grid: { left: '3%', right: '3%', bottom: '6%', top: '18%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: keys,
      boundaryGap: false,
      axisLabel: {
        ...t.axisLabelStyle,
        fontSize: 10,
        rotate: 45,
        interval: Math.max(0, Math.floor(keys.length / 10) - 1),
      },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { ...t.axisLabelStyle, fontSize: 11, formatter: '{value}%' },
    },
    series: list.map((format) => ({
      name: format,
      type: 'line',
      stack: 'formats',
      smooth: true,
      showSymbol: false,
      areaStyle: { opacity: 0.7 },
      emphasis: { focus: 'series' },
      data: keys.map((key) => {
        const inner = byMonth.value.get(key)
        if (!inner) return 0
        const total = [...inner.values()].reduce((a, b) => a + b, 0)
        const count = inner.get(format) ?? 0
        return total > 0 ? Number(((count / total) * 100).toFixed(2)) : 0
      }),
    })),
  }
})
</script>

<template>
  <ChartCard
    title="格式占比随时间"
    icon="shelf"
    :color-index="5"
    :empty="!months.length"
    empty-title="还没有入库记录"
    empty-description="按成品文件的修改时间归月，看每个月入库的书里各格式占多少。"
    :note="months.length ? `按当月入库总数算占比 · 共 ${totalBooks} 本` : ''"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
