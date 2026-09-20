<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 题材分布（上游 `GenreDistributionChart.vue`）：矩形树图。
 *
 * 与保留的明细卡（「Top 题材」）是**互补关系**，不是重复：
 *
 * - 图：块面积即占比，一眼看出「哪几类撑起了整个库」，且每块的标签直接写着
 *   `题材 / 本数 (占比%)` —— 这是 chip 列表给不了的；
 * - 卡片：逐条可读的列表 + 「展开全部 N 类」。
 *
 * ⚠️ 题材来自 `dc:subject`，**一本书可贡献多个**（见 `StatsOverview.genres` 的注释），
 * 所以各块之和会大于书籍总数 —— `note` 里点明，免得被当成「重复计数」。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

/** 按本数降序；同数按题材名排，避免每次刷新配色乱跳 */
const items = computed(() =>
  [...(props.data.genres.top ?? [])].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)),
)
const total = computed(() => items.value.reduce((s, x) => s + x.count, 0))

const option = computed(() => ({
  tooltip: {
    trigger: 'item',
    ...theme.value.tooltip,
    formatter: (p: { name: string; value: number }) => {
      const pct = total.value > 0 ? ((p.value / total.value) * 100).toFixed(1) : '0'
      return `<strong>${p.name}</strong><br/>${p.value} 本 · 占 ${pct}%`
    },
  },
  series: [
    {
      type: 'treemap',
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      top: 6,
      bottom: 6,
      left: 6,
      right: 6,
      data: items.value.map((x, i) => ({
        name: x.name,
        value: x.count,
        itemStyle: { color: palette.value[i % palette.value.length] },
      })),
      label: {
        show: true,
        fontSize: 11,
        color: '#fff', // 块色取自调色板的中等明度，白字两种主题下都读得清（同上游）
        overflow: 'truncate',
        formatter: (p: { name: string; value: number }) => {
          const pct = total.value > 0 ? ((p.value / total.value) * 100).toFixed(1) : '0'
          return `${p.name}\n${p.value} (${pct}%)`
        },
      },
      emphasis: { disabled: true },
      upperLabel: { show: false },
      // 块与块之间留缝（露出卡片底色）—— 上游靠给每块描背景色的边做到，同一效果
      levels: [{ itemStyle: { borderWidth: 0, gapWidth: 3 } }],
    },
  ],
}))
</script>

<template>
  <ChartCard
    title="题材分布"
    icon="note"
    :color-index="8"
    :empty="!items.length"
    empty-title="还没有题材数据"
    empty-description="题材来自 EPUB 的 dc:subject；没有的书不计入。"
    note="题材来自 dc:subject，一本书可归入多类，故各块之和大于书籍总数。"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
