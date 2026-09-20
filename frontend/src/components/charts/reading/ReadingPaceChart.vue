<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 阅读速度（上游 `ReadingPaceScatterChart.vue`）：x = 累计阅读时长（小时）、
 * y = 当前进度，按格式分色。快书靠左下、难啃的靠右下。
 *
 * ⚠️ **口径与上游不同，卡片脚注必须写明**（后端文件头有完整推导）：
 * 上游要的是 per-session 的 `progressDelta`（这一次会话读了多少百分比），
 * 而本项目的 `reading_sessions` **没有这一列**、历史会话也补不回来。与其编一个
 * 增量，这里换成**按书聚合**：累计时长 × 当前进度。散点形状与上游同义，
 * **读数不同**（同一个点代表一本书，不是一次会话）。
 *
 * 两处与本项目对齐：
 *
 * 1. **按格式分色**，不用上游的 `BreakdownSelect`（那要 `source` 维度，
 *    本项目 `reading_sessions` 没有来源列；格式是现成的）。
 * 2. 数据不足走空态（上游 `MIN_SESSIONS = 10`，这里是**书**数）。
 */
const MIN_POINTS = 10

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const items = computed(() => props.data.reading_pace)
const lowConfidence = computed(() => items.value.length > 0 && items.value.length < MIN_POINTS)

/** 出现过的格式（升序，颜色按它在列表里的下标取 —— 每次刷新都同一个格式同一个色） */
const formats = computed(() => [...new Set(items.value.map((x) => x.format || '未知'))].sort())

const option = computed(() => {
  const t = theme.value
  const rows = items.value
  const list = formats.value
  if (!rows.length || lowConfidence.value) return {}

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: {
        seriesName: string
        data: { value: [number, number]; name: string }
      }) => {
        const [h, pct] = params.data.value
        return `<strong>${params.data.name}</strong><br/>累计读了 ${h} 小时<br/>进度 <strong>${pct}%</strong>`
      },
      ...t.tooltip,
    },
    legend: { type: 'scroll', top: 0, itemWidth: 10, itemHeight: 10, ...t.legend },
    grid: { left: '3%', right: '5%', bottom: '12%', top: 28, containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      name: '累计时长（小时）',
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: { fontSize: 10, color: t.axisLabel },
      axisLabel: { ...t.axisLabelStyle, fontSize: 10 },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      max: 100,
      name: '进度 %',
      nameLocation: 'middle',
      nameGap: 32,
      nameTextStyle: { fontSize: 10, color: t.axisLabel },
      axisLabel: { ...t.axisLabelStyle, fontSize: 10 },
    },
    series: list.map((f, i) => ({
      name: f,
      type: 'scatter',
      symbolSize: 7,
      itemStyle: { color: palette.value[i % palette.value.length], opacity: 0.6 },
      data: rows
        .filter((x) => (x.format || '未知') === f)
        .map((x) => ({
          name: x.title,
          // 秒 → 小时，留一位小数：这本书累计读了多久
          value: [Number((x.seconds / 3600).toFixed(1)), x.percent],
        })),
    })),
  }
})
</script>

<template>
  <ChartCard
    title="阅读速度"
    icon="sparkle"
    :color-index="1"
    :empty="!items.length"
    empty-title="还没有可算的书"
    empty-description="要同时有阅读时长与阅读进度才算得出一个点。"
    :note="items.length
      ? '⚠️ 与上游口径不同：这里是按书聚合（累计时长 × 当前进度），不是单次会话的进度增量 —— 本项目的会话表没有那列'
      : ''"
  >
    <ChartEmptyState
      v-if="lowConfidence"
      icon="sparkle"
      title="数据不足"
      :description="`至少要读过 ${MIN_POINTS} 本才看得出分布，目前 ${items.length} 本。`"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
