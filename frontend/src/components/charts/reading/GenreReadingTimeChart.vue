<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 题材阅读时长（上游 `GenreReadingTimeTreemapChart.vue`）：矩形树图，面积 = 时长。
 *
 * ⚠️ **两条口径必须写在卡片上**（后端文件头有完整推导，这里给用户看得懂的版本）：
 *
 * 1. **各题材之和 ≥ 实际总时长**：一本书的整段时长会计入它的**每个**题材 ——
 *    一本书归入「科幻 + 悬疑」两个块里各算一遍。这是照搬上游的语义
 *    （上游是 `bookGenres` 内连接后 `SUM`，扇出同义），但不说清就会被当成「算重了」的 bug。
 * 2. **没打题材的书完全不进这张图**：题材是它唯一的维度，那些阅读时间不在任何块里。
 *
 * 两处与上游的对齐：窗口 365 天（「最近一年的口味」，不跟随页首的统计范围选择器）、
 * 题材数取前 30（上游 `slice(0, 30)`，块再多标签就叠满了）。
 */
const MIN_GENRES = 2

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const items = computed(() => props.data.genre_reading)
const sumSeconds = computed(() => items.value.reduce((s, x) => s + x.seconds, 0))
const lowConfidence = computed(() => items.value.length < MIN_GENRES)

function hours(seconds: number): string {
  return (seconds / 3600).toFixed(1)
}

const option = computed(() => {
  const t = theme.value
  const rows = items.value
  if (!rows.length || lowConfidence.value) return {}
  const total = sumSeconds.value || 1

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string; value: number }) =>
        `<strong>${params.name}</strong><br/>${hours(params.value)} 小时` +
        `<br/>占各题材合计数 ${((params.value / total) * 100).toFixed(1)}%`,
      ...t.tooltip,
    },
    series: [
      {
        type: 'treemap',
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        top: 4,
        bottom: 4,
        left: 2,
        right: 2,
        data: rows.map((r, i) => ({
          name: r.genre,
          value: r.seconds,
          itemStyle: {
            color: palette.value[i % palette.value.length],
            borderWidth: 2,
            borderColor: t.border,
          },
        })),
        label: {
          show: true,
          fontSize: 12,
          fontWeight: 500,
          overflow: 'truncate',
          // 块色取自调色板（浅色主题下偏亮），白字在两个主题下都压得住
          color: '#ffffff',
        },
        // 关掉 hover 高亮：面积已经在表达大小，再放大只会让相邻块跳动
        emphasis: { disabled: true },
        upperLabel: { show: false },
        levels: [{ itemStyle: { borderWidth: 0, gapWidth: 3 } }],
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="题材阅读时长"
    icon="note"
    :color-index="6"
    :empty="!items.length"
    empty-title="还没有题材阅读数据"
    empty-description="题材来自 EPUB 的 dc:subject，只看打了题材的书、近 365 天的会话。"
    :note="items.length
      ? `共 ${hours(sumSeconds)} 小时（各题材合计）· ⚠️ 一本书的时长会算进它的每个题材，所以合计 ≥ 实际总时长；没打题材的书不计入`
      : ''"
  >
    <ChartEmptyState
      v-if="lowConfidence"
      icon="note"
      title="数据不足"
      :description="`至少要有 ${MIN_GENRES} 个有阅读时长的题材才画得出树图，目前 ${items.length} 个。`"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
