<script setup lang="ts">
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 出版年时间轴（上游 `PublicationYearTimelineChart.vue`）：折线 + 面积 + 5 年滑动
 * 均线，带可缩放的 dataZoom、20 年窗口的「黄金年代」区间标注与峰值标注，底部一排
 * 6 个统计卡。
 *
 * 字段对应：上游的 `topTitles` 在本项目是 `top_titles`（后端已在 `publication_yearly`
 * 里给出每年最多 3 本样例书名，只进 tooltip）。
 */
const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const currentYear = new Date().getFullYear()

/**
 * 补齐年份空洞：1950 年有书、1952 年没有、1953 年又有 —— 中间那年要画成 0，
 * 不然折线会把两点直连，看起来像「1951 年也有书」。
 */
const filled = computed(() => {
  const pts = props.data.publication_yearly
  if (!pts.length) return []
  const byYear = new Map(pts.map((p) => [p.year, p]))
  const min = pts[0]?.year ?? 0
  const max = pts[pts.length - 1]?.year ?? 0
  const result: Array<{ year: number; count: number; topTitles: string[] }> = []
  for (let y = min; y <= max; y++) {
    const p = byYear.get(y)
    result.push({ year: y, count: p?.count ?? 0, topTitles: p?.top_titles ?? [] })
  }
  return result
})

/** 5 年滑动平均（±2 年窗口），抹掉单年噪声，看出趋势 */
const movingAvg = computed(() => {
  const f = filled.value
  return f.map((_, i) => {
    const lo = Math.max(0, i - 2)
    const hi = Math.min(f.length - 1, i + 2)
    const sum = f.slice(lo, hi + 1).reduce((s, p) => s + p.count, 0)
    return +(sum / (hi - lo + 1)).toFixed(2)
  })
})

/** 「黄金年代」＝ 本数最多的那 20 年窗口（照搬上游的算法与窗口宽度） */
const goldenEra = computed(() => {
  const f = filled.value
  if (f.length < 2) return null
  const last = f[f.length - 1]?.year ?? 0
  let best = { start: f[0]?.year ?? 0, end: f[0]?.year ?? 0, count: 0 }
  for (let i = 0; i < f.length; i++) {
    const current = f[i]
    if (!current) continue
    const windowEnd = current.year + 19
    const count = f
      .slice(i)
      .filter((p) => p.year <= windowEnd)
      .reduce((s, p) => s + p.count, 0)
    if (count > best.count) {
      best = { start: current.year, end: Math.min(windowEnd, last), count }
    }
  }
  return best
})

const peakItem = computed(() => {
  const f = filled.value
  if (!f.length) return null
  return f.reduce((best, p) => (p.count > best.count ? p : best), f[0] as { year: number; count: number })
})

/** 底部 6 个统计卡（上游同款六项） */
const statCards = computed(() => {
  const items = props.data.publication_yearly
  if (!items.length) return null
  const first = items[0]
  const last = items[items.length - 1]
  if (!first || !last) return null

  const total = items.reduce((s, p) => s + p.count, 0)
  const last10 = items.filter((p) => p.year >= currentYear - 10).reduce((s, p) => s + p.count, 0)
  const classics = items.filter((p) => p.year < 1970).reduce((s, p) => s + p.count, 0)
  const pct = (n: number) => (total > 0 ? `${Math.round((n / total) * 100)}%` : '0%')

  return [
    { label: '峰值年', value: peakItem.value?.year ?? 0, sub: `${peakItem.value?.count ?? 0} 本` },
    { label: '近 10 年', value: pct(last10), sub: '占全库' },
    { label: '经典', value: pct(classics), sub: '1970 年前' },
    { label: '有书年份', value: items.length, sub: '个' },
    { label: '跨度', value: last.year - first.year, sub: '年' },
    { label: '年均', value: items.length > 0 ? +(total / items.length).toFixed(1) : 0, sub: '本' },
  ]
})

const option = computed(() => {
  const t = theme.value
  const f = filled.value
  if (!f.length) return {}

  const years = f.map((p) => String(p.year))
  const counts = f.map((p) => p.count)
  const peak = peakItem.value
  const era = goldenEra.value

  const markAreaData = era
    ? [
        [
          {
            xAxis: String(era.start),
            itemStyle: { color: 'rgba(128,128,128,0.07)' },
            label: {
              show: true,
              position: 'insideTopLeft',
              formatter: '黄金年代',
              fontSize: 10,
              opacity: 0.45,
            },
          },
          { xAxis: String(era.end) },
        ],
      ]
    : []

  const markPointData = peak
    ? [
        {
          coord: [String(peak.year), peak.count],
          name: '峰值',
          value: peak.year,
          symbolSize: 30,
          label: { fontSize: 9, fontWeight: 'bold' },
        },
      ]
    : []

  return {
    color: palette.value,
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ axisValue: string; seriesName: string; data: number }>) => {
        const main = params.find((p) => p.seriesName === '书目')
        if (!main) return ''
        const year = parseInt(main.axisValue, 10)
        const pt = props.data.publication_yearly.find((p) => p.year === year)
        let html = `<strong>${main.axisValue}</strong><br/>${main.data} 本`
        if (pt?.top_titles?.length) {
          html +=
            '<br/><span style="opacity:0.65;font-size:11px">' +
            pt.top_titles.map((x) => `- ${x}`).join('<br/>') +
            '</span>'
        }
        return html
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '3%', bottom: 60, top: 16, containLabel: true },
    dataZoom: [
      {
        type: 'slider',
        bottom: 6,
        height: 18,
        start: 0,
        end: 100,
        borderColor: 'transparent',
        fillerColor: 'rgba(128,128,128,0.15)',
        // 下面这四项是**本项目补的**（上游 `:148-159` 只配了 borderColor 与 fillerColor）：
        // 滑块内部的数据轮廓默认走 ECharts 内置的深蓝灰，浅色下像一条异物、深色下几乎
        // 没对比。统一成与 filler 同族的中性灰；把手底色取主题的表面色（tooltip 底色
        // 就是这个语义），两套主题各得其所。
        dataBackground: {
          lineStyle: { color: 'rgba(128,128,128,0.4)' },
          areaStyle: { color: 'rgba(128,128,128,0.15)' },
        },
        selectedDataBackground: {
          lineStyle: { color: 'rgba(128,128,128,0.6)' },
          areaStyle: { color: 'rgba(128,128,128,0.25)' },
        },
        handleStyle: { color: t.tooltip.backgroundColor, borderColor: 'rgba(128,128,128,0.6)' },
        moveHandleStyle: { color: 'rgba(128,128,128,0.6)' },
      },
      { type: 'inside' },
    ],
    xAxis: {
      ...t.axis,
      type: 'category',
      data: years,
      boundaryGap: false,
      axisLabel: {
        ...t.axisLabelStyle,
        fontSize: 11,
        interval: Math.max(0, Math.floor(years.length / 12) - 1),
      },
    },
    yAxis: {
      ...t.axis,
      type: 'value',
      minInterval: 1,
      axisLabel: { ...t.axisLabelStyle, fontSize: 11 },
    },
    series: [
      {
        name: '书目',
        type: 'line',
        data: counts,
        smooth: 0.3,
        showSymbol: false,
        areaStyle: { opacity: 0.15 },
        lineStyle: { width: 2 },
        markArea: { silent: true, data: markAreaData },
        markPoint: {
          data: markPointData,
          label: { color: '#fff', fontSize: 9, fontWeight: 'bold' },
        },
      },
      {
        name: '5 年均线',
        type: 'line',
        data: movingAvg.value,
        smooth: 0.4,
        showSymbol: false,
        lineStyle: { type: 'dashed', width: 1.5, opacity: 0.5 },
        emphasis: { disabled: true },
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="出版年时间轴"
    icon="library"
    :color-index="4"
    :empty="!filled.length"
    empty-title="还没有出版年份"
    empty-description="年份来自 EPUB 的 dc:date，没有的书不在这条时间轴上。"
  >
    <div class="flex h-full min-h-0 flex-col">
      <div class="min-h-0 flex-1">
        <ChartFrame :option="option" />
      </div>
      <div v-if="statCards" class="mt-2 grid shrink-0 grid-cols-3 gap-2 px-1 md:grid-cols-6 md:gap-3">
        <div
          v-for="card in statCards"
          :key="card.label"
          class="border-border/60 bg-muted/40 rounded-md border px-2 py-1 text-center"
        >
          <p class="text-muted-foreground text-[10px] leading-none">{{ card.label }}</p>
          <p class="mt-1 text-sm leading-none font-semibold tabular-nums">{{ card.value }}</p>
          <p class="text-muted-foreground text-[10px] leading-none">{{ card.sub }}</p>
        </div>
      </div>
    </div>
  </ChartCard>
</template>
