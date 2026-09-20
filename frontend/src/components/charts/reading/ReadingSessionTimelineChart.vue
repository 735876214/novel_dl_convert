<script setup lang="ts">
import { graphic } from 'echarts/core'
import { computed } from 'vue'

import ChartCard from '@/components/charts/ChartCard.vue'
import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import ChartFrame from '@/components/charts/ChartFrame.vue'
import type { StatsOverview } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'

/**
 * 会话时间轴（上游 `ReadingSessionTimelineChart.vue`）：一周七行（周一–周日），
 * 横轴是一天内的时刻，每根横条是一次会话。看的是「我这周的作息长什么样」。
 *
 * 与上游的**三处差别**（都是本期如实记下的缺口，不假装一致）：
 *
 * 1. **只读**。上游那张图可以拖动会话条改时间、还带冲突检测；拖动要写库、
 *    要新接口、要处理并发冲突，本期不做，作为独立缺口记在
 *    `docs/bookorbit-capability-gap.md`。这里把「能读出来的东西」照原样画出来。
 * 2. **没有周选择器**。上游按 `year + week` 向后端取数；本项目的
 *    `session_timeline` 是**最近 400 条**会话的明细（不按周切），所以这里画
 *    「**最近 7 天**（含今天）」这一条滚动窗口，并把更早的条数写在脚注里 ——
 *    挂一个只能翻到部分历史的周选择器，比不给更误导。
 * 3. **窗口是滚动的 7 天，不是自然周**。上游画的是本周一→本周日；但本项目的
 *    这张图在**周一凌晨**打开时自然周里只有几十分钟的数据，几乎是一片空白
 *    （实测：00:18 打开，14 本书的当周会话只有 2 条）。滚动 7 天永远给满一行。
 *    行标签相应改成日期 + 周几，今天在最上面（`yAxis.inverse`）。
 *
 * 用 `custom` 系列而不是 `bar`：一根横条有「起点 + 长度」两个自由度，
 * bar 只能表达一个（要么堆叠错位、要么用透明底座硬凑）。
 */
const MINUTES_PER_DAY = 1440
/** 窗口天数（含今天） */
const WINDOW_DAYS = 7
const DAY_LABELS = ['日', '一', '二', '三', '四', '五', '六']

const props = defineProps<{ data: StatsOverview }>()

const { palette, theme } = useChartTheme()

const items = computed(() => props.data.session_timeline)

/** 本地零点（与后端给的 UNIX 秒对齐；跨时区只影响分组，不影响读数） */
function midnight(ms: number): number {
  const d = new Date(ms)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

/** 今天的本地零点 —— 窗口的右端 */
const todayStart = computed(() => midnight(Date.now()))

/** 窗口内的会话（今天 = 第 0 行，越往下越早） */
const inWindow = computed(() => {
  const t0 = todayStart.value - (WINDOW_DAYS - 1) * 86400000
  return items.value.filter((x) => x.started_at * 1000 >= t0)
})

const outsideCount = computed(() => items.value.length - inWindow.value.length)

/** 行标签：今天在最上面，往下是昨天、前天……（`yAxis.inverse` 让下标 0 落在顶部） */
const dayLabels = computed(() => {
  const out: string[] = []
  for (let i = 0; i < WINDOW_DAYS; i++) {
    const d = new Date(todayStart.value - i * 86400000)
    const week = DAY_LABELS[d.getDay()] ?? ''
    const label = `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} 周${week}`
    out.push(i === 0 ? `今天 ${label}` : label)
  }
  return out
})

/** custom 系列的每一行：`[第几天（0 = 今天）, 起（分钟）, 止（分钟）, 书名, 格式, 时长]` */
const rows = computed(() =>
  inWindow.value.map((x) => {
    const s = new Date(x.started_at * 1000)
    const row = Math.round((todayStart.value - midnight(s.getTime())) / 86400000)
    const from = s.getHours() * 60 + s.getMinutes() + s.getSeconds() / 60
    // 跨零点的会话裁到当天 24:00（它在下一行里没有对应的开始时刻，硬画会绕回去）
    const to = Math.min(MINUTES_PER_DAY, from + x.seconds / 60)
    return {
      value: [row, Number(from.toFixed(2)), Number(Math.max(to, from + 0.5).toFixed(2))],
      title: x.title || '（无书名）',
      format: x.format || '未知',
      seconds: x.seconds,
      from,
    }
  }),
)

interface RenderParams {
  coordSys: { x: number; y: number; width: number; height: number }
}

interface RenderApi {
  value: (index: number) => number
  coord: (value: [number, number]) => [number, number]
  style: () => Record<string, unknown>
}

/** 一根横条：竖直方向居中在所属星期的那一行，水平方向从起点铺到终点 */
function renderItem(params: RenderParams, api: RenderApi): Record<string, unknown> | null {
  const barHeight = 9
  const centerY = api.coord([0, api.value(0)])[1]
  const x0 = api.coord([api.value(1), 0])[0]
  const x1 = api.coord([api.value(2), 0])[0]
  const rect = graphic.clipRectByRect(
    // 最短 1.5px：几秒钟的会话也该看得见，否则会读成「这一格没读过」
    { x: x0, y: centerY - barHeight / 2, width: Math.max(1.5, x1 - x0), height: barHeight },
    {
      x: params.coordSys.x,
      y: params.coordSys.y,
      width: params.coordSys.width,
      height: params.coordSys.height,
    },
  )
  if (!rect) return null
  return { type: 'rect', shape: rect, style: api.style() }
}

function formatClock(minutes: number): string {
  const total = Math.round(minutes)
  const h = Math.floor(total / 60) % 24
  const m = total % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function formatDuration(seconds: number): string {
  const mins = Math.round(seconds / 60)
  return mins < 60 ? `${mins} 分钟` : `${(mins / 60).toFixed(1)} 小时`
}

const option = computed(() => {
  const t = theme.value
  const data = rows.value
  const labels = dayLabels.value
  if (!data.length) return {}

  return {
    color: palette.value,
    tooltip: {
      trigger: 'item',
      formatter: (params: { dataIndex: number }) => {
        const r = data[params.dataIndex]
        if (!r) return ''
        const day = labels[r.value[0] ?? 0] ?? ''
        return (
          `<strong>${r.title}</strong><br/>` +
          `${day} ${formatClock(r.from)}` +
          `（${formatDuration(r.seconds)}）<br/>${r.format}`
        )
      },
      ...t.tooltip,
    },
    grid: { left: '3%', right: '4%', bottom: '8%', top: 8, containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'value',
      min: 0,
      max: MINUTES_PER_DAY,
      interval: 180,
      axisLabel: {
        ...t.axisLabelStyle,
        fontSize: 10,
        formatter: (value: number) => `${Math.floor(value / 60)}:00`,
      },
    },
    yAxis: {
      ...t.axis,
      type: 'category',
      data: labels,
      // 下标 0（今天）排到**最上面**：报告类的图从上往下读就是「由近及远」
      inverse: true,
      axisTick: { show: false },
      axisLabel: { ...t.axisLabelStyle, fontSize: 10 },
    },
    series: [
      {
        type: 'custom',
        renderItem,
        encode: { x: [1, 2], y: 0, tooltip: [1, 2] },
        itemStyle: { opacity: 0.85, borderRadius: 2 },
        data,
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="会话时间轴"
    icon="shelf"
    :color-index="7"
    :empty="!items.length"
    empty-title="还没有阅读会话"
    empty-description="每次打开阅读器都会记一段会话，这里按一周七行铺开。"
    :note="items.length
      ? `最近 7 天共 ${inWindow.length} 次（今天在最上面）· 本期只读：上游那张能拖动改会话时间${outsideCount ? ` · 更早的 ${outsideCount} 次不在窗口内` : ''}`
      : ''"
  >
    <ChartEmptyState
      v-if="!rows.length"
      icon="shelf"
      title="最近 7 天没有会话"
      description="这张图只画最近 7 天；更早的会话见「阅读热力图」。"
    />

    <ChartFrame v-else :option="option" />
  </ChartCard>
</template>
