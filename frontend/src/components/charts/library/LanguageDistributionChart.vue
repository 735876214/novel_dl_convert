<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme, useIsWide } from '@/lib/charts'

/**
 * 语言分布（上游 `LanguageDistributionChart.vue`）：环形饼 + 可滚动 legend。
 *
 * 未知语言在**后端**就归到了 `"?"`（照 `by_format` 的既成惯例），所以这里没有
 * 上游那个 `unknownCount` 脚注 —— 未标注语言的书在图上是自成一类的「?」，
 * 不是被藏起来的。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()
const wide = useIsWide()

/** 按本数降序；同数按语言名排，避免每次刷新配色顺序乱跳 */
const items = computed(() =>
  Object.entries(props.data.by_language)
    .map(([language, count]) => ({ language, count }))
    .sort((a, b) => b.count - a.count || a.language.localeCompare(b.language)),
)

const option = computed(() => ({
  color: palette.value,
  tooltip: { trigger: 'item', ...theme.value.tooltip },
  legend: {
    type: 'scroll',
    orient: wide.value ? 'vertical' : 'horizontal',
    left: wide.value ? '56%' : 'center',
    right: wide.value ? 0 : 'auto',
    top: wide.value ? 8 : 'auto',
    bottom: wide.value ? 8 : 0,
    itemWidth: 12,
    itemHeight: 8,
    pageIconSize: 10,
    pageButtonGap: 4,
    ...theme.value.legend,
  },
  series: [
    {
      type: 'pie',
      radius: ['42%', '68%'],
      center: wide.value ? ['27%', '50%'] : ['50%', '38%'],
      data: items.value.map((x) => ({ name: x.language.toUpperCase(), value: x.count })),
      label: { show: false },
    },
  ],
}))
</script>

<template>
  <ChartCard
    title="语言分布"
    icon="globe"
    :color-index="0"
    :empty="!items.length"
    empty-title="还没有语言数据"
    empty-description="书目的语言来自 EPUB 的 dc:language，没有的书会归到「?」。"
  >
    <ChartFrame :option="option" />
  </ChartCard>
</template>
