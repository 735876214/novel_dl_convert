<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 页数分布（上游 `PageCountDistributionChart.vue`）：按格式分组的**箱线图**
 * （上游就是箱线图，不是直方图）。
 *
 * ⚠️ 口径：`pages` 的 0 是「不知道」不是「0 页」（EPUB 是估算值、漫画是归档实际值、
 * 其余格式恒 0），**后端已把 pages=0 的书排除**，否则 PDF / 有声书会在图上压出
 * 一根假底线。被排除的本数在脚注里如实告知。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const items = computed(() => props.data.pages_by_format)

/** 有页数记录的本数 / 全部本数 —— 差额就是脚注要交代的那部分 */
const counted = computed(() => items.value.reduce((sum, g) => sum + g.count, 0))
const skipped = computed(() => Math.max(0, props.data.books.total - counted.value))

const SOURCE_LABELS: Record<string, string> = {
  estimate: '估算',
  archive: '归档实测',
  unknown: '来源未知',
}

/** 各格式的页数来源（同一格式可能混着估算值与实测值，如实列出） */
function sourceNote(sources: Record<string, number>): string {
  const parts = Object.entries(sources)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${SOURCE_LABELS[k] ?? k} ${n}`)
  return parts.length ? `页数来源：${parts.join('、')}` : ''
}

const option = computed(() => {
  const t = theme.value
  return {
    color: palette.value,
    tooltip: {
      trigger: 'item',
      formatter: (p: { dataIndex: number }) => {
        const row = items.value[p.dataIndex]
        if (!row) return ''
        return [
          `${row.format}（${row.count} 本）`,
          `最小值 ${row.min}`,
          `下四分位 ${Math.round(row.q1)}`,
          `中位数 ${Math.round(row.median)}`,
          `上四分位 ${Math.round(row.q3)}`,
          `最大值 ${row.max}`,
          sourceNote(row.sources),
        ].filter(Boolean).join('<br/>')
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '3%', bottom: '4%', top: '6%', containLabel: true },
    // 先展开 t.axis 再覆盖 axisLabel —— 反过来会被 t.axis 自带的那个盖回去
    xAxis: {
      ...t.axis,
      type: 'category',
      data: items.value.map((x) => x.format),
      axisLabel: { ...t.axisLabelStyle, fontSize: 11, rotate: 35, interval: 0 },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    series: [
      {
        type: 'boxplot',
        data: items.value.map((x) => [x.min, x.q1, x.median, x.q3, x.max]),
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="页数分布"
    icon="book"
    :color-index="2"
    :empty="!items.length"
    empty-title="还没有页数记录"
    empty-description="只有 EPUB（估算）与漫画（归档实测）会记录页数。"
    :note="skipped ? `另有 ${skipped} 本没有页数记录，未入图。` : ''"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
