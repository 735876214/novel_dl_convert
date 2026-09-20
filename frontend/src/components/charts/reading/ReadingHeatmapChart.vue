<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import { api, type ReadingHeatmap, type StatsOverview } from '@/lib/api'
import { chartShades, useChartTheme } from '@/lib/charts'

/**
 * 阅读热力图（上游 `ReadingHeatmapChart.vue`）：GitHub 贡献图那样的日历热力图，
 * 一格一天、颜色越深读得越久。
 *
 * ⚠️ **这是本项目唯一自带请求的图表**，理由与做法：
 *
 * - 数据来自第 31 期的 `/api/reading-activity`（`activity.heatmap`），
 *   **不在 `/api/stats` 里**。计划里就写明了「复用现有序列，不重复造」——
 *   往 `/api/stats` 再塞一份日历数据，等于让同一件事有两个真相源。
 * - 书库范围用 `props.data.library_id`（**不是** `useActivityStore`）：
 *   统计页的「统计范围」是页内局部状态，而 store 跟的是应用当前书库，
 *   两者可以不一致 —— 用 store 会出现「页首选了 A 库、热力图画的却是 B 库」。
 * - **一次请求取全部年份**，再在本地挑「有数据的最新一年」：上游取的是当前年份，
 *   但年初或久未阅读时那会是一片空白。挑最新有数据的一年，空态才留给真正的空。
 */
const MIN_ACTIVE_DAYS = 5

const DAY_LABELS = ['日', '一', '二', '三', '四', '五', '六']

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme, dark } = useChartTheme()

const heat = ref<ReadingHeatmap | null>(null)
const loading = ref(false)
const error = ref(false)

let token = 0

async function load(libraryId: string) {
  const mine = ++token
  loading.value = true
  error.value = false
  try {
    const res = await api.readingActivity(libraryId)
    if (mine === token) heat.value = res.heatmap
  } catch {
    if (mine === token) {
      heat.value = null
      error.value = true
    }
  } finally {
    if (mine === token) loading.value = false
  }
}

watch(() => props.data.library_id, (lid) => void load(lid ?? ''), { immediate: true })

/** 「有数据的最新一年」+ 那一年的逐日分钟 */
const picked = computed(() => {
  const days = heat.value?.days ?? []
  if (!days.length) return null
  let year = ''
  for (const d of days) {
    const y = d.date.slice(0, 4)
    if (y > year) year = y
  }
  const inYear = days.filter((d) => d.date.startsWith(year))
  return { year, days: inYear, activeDays: inYear.filter((d) => d.minutes > 0).length }
})

const lowConfidence = computed(
  () => !!picked.value && picked.value.activeDays < MIN_ACTIVE_DAYS,
)

/** 年份里每一天的分钟数（**补零**：没有会话的日子也要占一格，否则日历会缺格） */
const values = computed(() => {
  const p = picked.value
  if (!p) return []
  const byDay = new Map(p.days.map((d) => [d.date, d]))
  const out: Array<[string, number, number]> = []
  const cursor = new Date(Number(p.year), 0, 1)
  while (cursor.getFullYear() === Number(p.year)) {
    const key = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, '0')}-${String(cursor.getDate()).padStart(2, '0')}`
    const hit = byDay.get(key)
    out.push([key, hit ? hit.minutes : 0, hit ? hit.sessions : 0])
    cursor.setDate(cursor.getDate() + 1)
  }
  return out
})

const option = computed(() => {
  const p = picked.value
  const t = theme.value
  if (!p || !values.value.length) return {}
  const shades = chartShades(palette.value)
  const year = Number(p.year)
  const range: [string, string] = [`${year}-01-01`, `${year}-12-31`]

  return {
    tooltip: {
      formatter: (params: { value: [string, number, number] }) => {
        const [day, minutes, sessions] = params.value
        return `${day}<br/><strong>${minutes}</strong> 分钟 · ${sessions} 次会话`
      },
      ...t.tooltip,
    },
    visualMap: {
      type: 'piecewise',
      show: true,
      calculable: false,
      dimension: 1,
      orient: 'horizontal',
      left: 'center',
      top: 0,
      itemWidth: 12,
      itemHeight: 10,
      itemGap: 6,
      // 分档照搬上游（15 / 30 / 60 分钟）：**固定档位**而不是按最大值自适应 ——
      // 自适应会让「每天读 5 分钟」和「每天读 5 小时」看起来一样深。
      pieces: [
        { value: 0, label: '0', color: shades[0] },
        { gt: 0, lte: 15, label: '1-15', color: shades[1] },
        { gt: 15, lte: 30, label: '16-30', color: shades[2] },
        { gt: 30, lte: 60, label: '31-60', color: shades[3] },
        { gt: 60, label: '60+', color: shades[4] },
      ],
      textStyle: { fontSize: 10, color: t.axisLabel },
    },
    calendar: {
      top: 44,
      left: 30,
      right: 8,
      bottom: 8,
      cellSize: ['auto', 13],
      range,
      yearLabel: { show: false },
      splitLine: { show: false },
      monthLabel: {
        show: true,
        fontSize: 10,
        color: t.axisLabel,
        margin: 8,
        nameMap: ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
      },
      dayLabel: {
        show: true,
        firstDay: 1,
        fontSize: 10,
        color: t.axisLabel,
        margin: 6,
        nameMap: DAY_LABELS,
      },
      itemStyle: {
        // 底色透明：0 分钟那档用 visualMap 的 shades[0]（浅底），不必再叠一层
        color: 'transparent',
        borderWidth: 0.5,
        borderColor: t.border,
        borderRadius: 1,
      },
    },
    series: [
      {
        type: 'heatmap',
        coordinateSystem: 'calendar',
        data: values.value,
        // 关掉 hover 高亮：格子太小，放大反而盖住旁边的日期，读数靠 tooltip
        emphasis: { disabled: true },
        itemStyle: dark.value ? undefined : { borderWidth: 0.5, borderColor: t.border },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="阅读热力图"
    icon="dash"
    :color-index="4"
    :loading="loading"
    :error="error"
    :empty="!picked"
    empty-title="还没有阅读记录"
    empty-description="每次阅读会话都会按天累计分钟数，这里铺成一年的日历。"
    :note="picked
      ? `${picked.year} 年 · ${picked.activeDays} 个活跃日 · 档位固定（15/30/60 分钟），不随数据缩放`
      : ''"
  >
    <ChartEmptyState
      v-if="lowConfidence && picked"
      icon="dash"
      title="数据不足"
      :description="`至少要有 ${MIN_ACTIVE_DAYS} 个活跃日才看得出节奏，${picked.year} 年目前 ${picked.activeDays} 天。`"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
