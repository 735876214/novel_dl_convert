<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { chartShades, useChartTheme } from '@/lib/charts'

/**
 * 各库元数据对比（上游 `LibraryMetadataCompletenessHeatmapChart.vue`，
 * 「Library Metadata Completeness」）：行 = 书库、列 = 字段，格子越深覆盖越全。
 *
 * 卡片名不直译成「各库元数据覆盖率」：同屏已经有一张按字段的「元数据覆盖率」，
 * 两个只差两个字的名字必然被看串。「对比」二字正是这张图的用途。
 *
 * ⚠️ 这张图**不跟随统计范围**（见 `core/stats.py` 文件头与后端注释）：它要回答的是
 * 「哪个库的元数据更完整」，跟随筛选就只剩一行、图本身失去意义。故页首选了某个库时，
 * 这一格的数字仍是全部书库的对比 —— 卡片脚注写明了这一点，免得被当成没生效。
 *
 * 两处与上游的差异：
 *
 * 1. **行列顺序由后端定**（行按书库管理里的排序、列按权重表的字段序），这里照单渲染。
 *    上游是在前端按 `FIELD_ORDER` 常量过滤排序 —— 那是第二份字段表，必然与后端漂移。
 * 2. 配色用 `chartShades()`（单色多档），见 `lib/charts.ts` 里那个函数的说明。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme, dark } = useChartTheme()

/** 行（书库）与列（字段）的出现顺序 —— 后端已排好，这里只去重 */
const libraries = computed(() => {
  const out: string[] = []
  for (const row of props.data.library_metadata) {
    if (!out.includes(row.library_name)) out.push(row.library_name)
  }
  return out
})

const fields = computed(() => {
  const out: string[] = []
  for (const row of props.data.library_metadata) {
    if (!out.includes(row.label)) out.push(row.label)
  }
  return out
})

/** 全库都 0 本书时画不出热力图（每格 0%）—— 那属于「没有数据」而不是「覆盖率为 0」 */
const hasBooks = computed(() => props.data.library_metadata.some((r) => r.total > 0))

const option = computed(() => {
  const t = theme.value
  const cols = fields.value
  const rows = libraries.value
  const shades = chartShades(palette.value)
  // 格子上的数字要压在**深浅不一**的底色上，故用与主题同向的强对比色
  const labelColor = dark.value ? '#f8fafc' : '#0f172a'

  const points = props.data.library_metadata.map((r) => [
    cols.indexOf(r.label),
    rows.indexOf(r.library_name),
    r.percent,
    r.present,
    r.total,
  ])

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: { value: number[] }) => {
        const [x, y, percent, present, total] = params.value
        return `${rows[y] ?? ''}<br/>${cols[x] ?? ''}: <strong>${percent}%</strong>（${present} / ${total} 本）`
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '3%', bottom: '6%', top: '6%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: cols,
      axisLabel: { ...t.axisLabelStyle, fontSize: 10, rotate: 40, interval: 0 },
    },
    yAxis: {
      ...t.axis,
      type: 'category',
      data: rows,
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    visualMap: {
      type: 'piecewise',
      show: false,
      calculable: false,
      dimension: 2,
      pieces: [
        { value: 0, color: shades[0] },
        { gt: 0, lte: 25, color: shades[1] },
        { gt: 25, lte: 50, color: shades[2] },
        { gt: 50, lte: 75, color: shades[3] },
        { gt: 75, color: shades[4] },
      ],
    },
    series: [
      {
        type: 'heatmap',
        data: points,
        label: {
          show: true,
          formatter: (params: { value: number[] }) => `${params.value[2]}%`,
          color: labelColor,
          fontSize: 11,
          fontWeight: 500,
        },
        itemStyle: { borderColor: t.border, borderWidth: 0.8 },
        // 关掉 hover 高亮：整格的深色盖在数字上反而更难读，读数靠 tooltip
        emphasis: { disabled: true },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="各库元数据对比"
    icon="library"
    :color-index="7"
    :empty="!hasBooks"
    empty-title="还没有书目"
    empty-description="这条对比要至少一个库里有书才画得出来。"
    :note="hasBooks ? '⚠️ 不跟随页首的统计范围：对比才是它的用途，只统计当前库就只剩一行' : ''"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
