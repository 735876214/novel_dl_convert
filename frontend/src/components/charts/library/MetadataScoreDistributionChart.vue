<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 元数据分数分布（上游 `MetadataScoreDistributionChart.vue`）：分档柱状图 +
 * P25–P75 阴影带 + P50 / P90 两条虚线，一眼看出「整体水平」与「离群的书多不多」。
 *
 * 与上游的**一处口径差异**：上游是 10 档（每 10 分一档），本项目后端的分档是
 * **4 档**（`< 50` / `50–69` / `70–89` / `90+`，见 `core/metascore.py`），
 * 且它就是书库体检里「元数据达标（≥70）」那条线所在的分档 —— 换成 10 档会让
 * 体检的阈值落在某一档的中间、两处口径又对不上。故这里照后端的分档画，
 * 分位线按**所在档**对齐（`bucketIndex`），而不是上游的 `floor(分值/10)`。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const buckets = computed(() => props.data.metadata_score.buckets)
const score = computed(() => props.data.metadata_score)

/**
 * ⚠️ 空态**不能**判 `buckets.length` —— 后端的分档表是常量（永远 4 档），
 * 空库给的是 4 条计数全 0，画出来是四根零高的柱子（假图）。真正没数据的判断
 * 是 `total`（= 在册书总数，与 `books.total` 同源）。
 */
const hasBooks = computed(() => score.value.total > 0)

/**
 * 分值 → 分档下标。边界照 `metascore._BUCKETS` 的三条线（50 / 70 / 90）写死：
 * 分档是后端的口径，前端不重算，只做一次「这个分值落在哪根柱子上」的定位。
 */
function bucketIndex(value: number): number {
  if (value < 50) return 0
  if (value < 70) return 1
  if (value < 90) return 2
  return 3
}

const option = computed(() => {
  const t = theme.value
  const rows = buckets.value
  const s = score.value
  const p25 = bucketIndex(s.p25)
  const p50 = bucketIndex(s.p50)
  const p75 = bucketIndex(s.p75)
  const p90 = bucketIndex(s.p90)

  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number }>) => {
        const p = params[0]
        const b = p ? rows[p.dataIndex] : undefined
        if (!b) return ''
        return `${b.label} 分: <strong>${b.count}</strong> 本（${b.percent}%）`
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '3%', bottom: '6%', top: '14%', containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: rows.map((b) => b.label),
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      minInterval: 1,
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        data: rows.map((b) => b.count),
        barMaxWidth: 44,
        itemStyle: { borderRadius: [3, 3, 0, 0] },
        // 阴影带 = 中间 50% 的书落在哪几档（P25–P75）
        markArea: {
          silent: true,
          itemStyle: { color: t.border },
          data: [[{ xAxis: p25 }, { xAxis: p75 }]],
        },
        // P50 / P90 两条虚线：中位数与「优秀线」
        markLine: {
          symbol: ['none', 'none'],
          lineStyle: { type: 'dashed' },
          label: { show: true, formatter: '{b}', position: 'insideEndTop' },
          data: [
            { xAxis: p50, name: 'P50' },
            { xAxis: p90, name: 'P90' },
          ],
        },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="元数据分数分布"
    icon="chart"
    :color-index="2"
    :empty="!hasBooks"
    empty-title="还没有书目"
    empty-description="按元数据完整度评分分档统计，分档与书库体检的达标线一致。"
    :note="hasBooks
      ? `平均 ${score.avg} 分 · 阴影带是中间的 50%（P25–P75） · 虚线是中位与 P90`
      : ''"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
