<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 元数据覆盖率（上游 `MetadataCompletenessChart.vue`）：按字段的覆盖百分比柱状图。
 *
 * 与上游的三处对齐：
 *
 * 1. **x 轴倒序**（上游 `[...items].reverse()`）—— 字段按权重从低到高排在前面，
 *    因为 12 个中文标签在 1x1 格子里必然要旋转 45°，倒过来能让最常缺的字段
 *    （封面、页数）落在柱子最矮那一侧、不跟轴标签的斜角打架。
 * 2. **y 轴固定 0–100**，不按最大值自适应 —— 覆盖率是个百分比，自适应会把
 *    「全库 30%」画成一根顶到顶的柱子，是最容易骗人的那种图。
 * 3. tooltip 给「百分比 + 本数」两个读数（只有百分比看不出分母多大）。
 *
 * 口径差异（后端已写明，这里照实说明给用户）：分母是**在册书总数**，与元数据页的
 * 字段覆盖率同一个数；封面 / 页数只对 EPUB 有意义，不做格式归一。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

/** 倒序后的字段（覆盖率的柱子顺序） */
const items = computed(() => [...props.data.metadata_fields].reverse())

/**
 * ⚠️ 空态**不能**判 `items.length` —— 后端给的是 `metascore.FIELDS` 的全 12 个字段，
 * 库里一本书都没有时它照样是 12 条（覆盖率全 0）。那样空库会画出一排零高的柱子，
 * 正是「假图」。真正的「没有数据」只有一种：在册书总数为 0。
 */
const hasBooks = computed(() => props.data.books.total > 0)

const option = computed(() => {
  const t = theme.value
  const rows = items.value
  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number }>) => {
        const p = params[0]
        const item = p ? rows[p.dataIndex] : undefined
        if (!item) return ''
        return `${item.label}: <strong>${item.percent}%</strong>（${item.present} / ${item.total} 本）`
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '3%', bottom: '6%', top: '8%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: rows.map((r) => r.label),
      axisLabel: { ...t.axisLabelStyle, fontSize: 10, rotate: 45, interval: 0 },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { ...t.axisLabelStyle, fontSize: 11, formatter: '{value}%' },
    },
    series: [
      {
        type: 'bar',
        data: rows.map((r) => r.percent),
        barMaxWidth: 26,
        itemStyle: { borderRadius: [3, 3, 0, 0] },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="元数据覆盖率"
    icon="check"
    :color-index="4"
    :empty="!hasBooks"
    empty-title="还没有书目"
    empty-description="覆盖率来自元数据完整度评分，与元数据页同一份口径。"
    :note="hasBooks ? '分母是在册书总数；封面与页数只对 EPUB 有意义' : ''"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
