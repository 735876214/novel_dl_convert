<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 题材共现（上游 `GenreCooccurrenceChart.vue`）：弦图，弧长 = 该题材的本数、
 * 弦的粗细 = 两个题材同时出现的本数。
 *
 * 三件后端已经定好、这里**只负责画**的事（免得两边各算一套）：
 *
 * - 节点上限 12（`stats._CHORD_NODES`）—— 弦图靠弧长与粗细读数，节点一多就糊成一团；
 * - 只保留两端都在节点集里的边（否则会画出指向不存在节点的弦）；
 * - 对是**无序**的（同一对题材只记一条弦，值 = 同时出现的本数）。
 *
 * 空态分两种：没有任何题材（书都没打标签）与只有一个题材（配不成对）——
 * 后者上游是画一个孤零零的圆，读不出东西，这里也走空态并说明原因。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const chord = computed(() => props.data.genre_cooccurrence)
const tooFew = computed(() => chord.value.nodes.length === 1)

const option = computed(() => {
  const t = theme.value
  const { nodes, links } = chord.value

  return {
    color: palette.value,
    tooltip: {
      trigger: 'item',
      formatter: (params: {
        dataType: string
        name: string
        value: number
        data: { source?: string; target?: string; value?: number }
      }) => {
        if (params.dataType === 'edge') {
          const value = params.data.value ?? 0
          return `<strong>${params.data.source} + ${params.data.target}</strong><br/>${value} 本同时属于这两个题材`
        }
        return `<strong>${params.name}</strong>`
      },
      ...t.tooltip,
    },
    series: [
      {
        type: 'chord',
        // 逆时针：与上游一致（弧长从 12 点方向往左排，书多的题材落在左上）
        clockwise: false,
        label: { show: true, fontSize: 11, color: t.axisLabel },
        lineStyle: { color: 'target', opacity: 0.6 },
        itemStyle: { borderWidth: 1 },
        emphasis: { focus: 'adjacency' },
        data: nodes,
        links,
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="题材共现"
    icon="layers"
    :color-index="3"
    :empty="!chord.nodes.length"
    empty-title="还没有题材数据"
    empty-description="题材来自 EPUB 的 dc:subject，一本书可以有多个。"
    :note="chord.nodes.length > 1
      ? `节点取本数最多的 ${chord.nodes.length} 个题材 · 弦的粗细 = 两题材同时出现的本数`
      : ''"
  >
    <ChartEmptyState
      v-if="tooFew"
      icon="layers"
      title="只有一个题材"
      description="共现图要至少两个题材才画得出来 —— 只有一个时上游画的是个孤零零的圆，读不出东西。"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
