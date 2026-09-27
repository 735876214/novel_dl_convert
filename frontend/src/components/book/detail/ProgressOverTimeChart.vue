<script setup lang="ts">
import { computed, ref } from 'vue'

import ChartFrame from '@/components/charts/ChartFrame.vue'
import Card from '@/components/ui/Card.vue'
import type { ReadingDayPoint } from '@/lib/api'
import { useChartTheme } from '@/lib/charts'
import { fmtMinutes } from '@/lib/format'

/**
 * PROGRESS OVER TIME：这本书的「读到哪」与「读了多久」两条时间序列，同一个 x 轴。
 *
 * 双轴（左 = 位置 %，右 = 分钟数）而不是两条归一化曲线：这两个量的单位本来就不同，
 * 归一化之后「今天读了 10 分钟、位置从 3% 跳到 4%」会画成两条缠绕的线，什么也读不出来。
 *
 * ⚠️ **本组件是全站第二个引 ECharts 的地方**，必须由父级 `defineAsyncComponent` 加载
 * （第一个是统计页，走路由级懒加载）。详情页是高频入口，让它在首屏就拖下那个
 * 800 kB 量级的图表库是不可接受的 —— 所以父级是「**第一次打开这个标签页才 import**」，
 * 不是一直挂着。（构建产物里它单独成 chunk，与统计页**共用**一个 `charts-*.js`。）
 *
 * **这是本项目的图，不是上游那张的复刻**（照搬会撒谎，如实说明）：上游的
 * `PROGRESS OVER TIME` 画在 `page_progress` 历史表上，那是每次翻页都记一行的高频采样；
 * 本项目的 `days` 来自**会话**（一次连续阅读一行），所以这里每个点 = 某天最后一次
 * 已知位置，点与点之间**没有采样**。
 *
 * 那个 `曲线 / 散点` 开关就是这件事的出口：
 * - **曲线**：连线看趋势。适合「这本书我是越读越快还是越读越慢」。
 * - **散点**：只画实测点。适合「我到底在哪些天读过」—— 一眼看出哪几天没读，
 *   而曲线会把空档用一条斜线连起来，读起来像是那几天也在读。
 *
 * 两种都不插值、不补零：`connectNulls: false` + `null` 值 ⇒ 没有位置记录的那天**断开**。
 * 位置未知（第 63 期之前的会话没有进度快照）一律 `null`，绝不画到 0% ——
 * 那条线跌到 0 会被读成「读回开头了」。
 */
const props = defineProps<{
  /** 升序（服务端已排好，x 轴从左到右） */
  days: ReadingDayPoint[]
}>()

type Mode = 'curve' | 'trace'
const mode = ref<Mode>('curve')

const MODES: { key: Mode; label: string; hint: string }[] = [
  { key: 'curve', label: '曲线', hint: '连线看趋势' },
  { key: 'trace', label: '散点', hint: '只画实测点，不连线' },
]

const { palette, theme } = useChartTheme()

/** `MM-DD`：折线图的 x 轴标签放不下年份，年份写在脚注里 */
const labels = computed(() => props.days.map((d) => d.date.slice(5)))

/** 位置：`null` = 那天没有位置记录（图上断开），**不是 0** */
const percents = computed(() =>
  props.days.map((d) => (d.end_percent == null ? null : Math.round(d.end_percent * 10) / 10)),
)

const minutes = computed(() => props.days.map((d) => Math.round(d.seconds / 60)))

/** 有几天是「老数据」：只有时长没有位置 —— 脚注里如实说一句，否则用户会以为图坏了 */
const missingPos = computed(() => percents.value.filter((p) => p === null).length)

const span = computed(() => {
  const d = props.days
  if (!d.length) return ''
  return d.length === 1 ? d[0].date : `${d[0].date} → ${d[d.length - 1].date}`
})

const option = computed(() => {
  const t = theme.value
  const p = palette.value
  const posColor = p[0] ?? '#888888'
  const timeColor = p[1] ?? posColor

  const position =
    mode.value === 'curve'
      ? {
          type: 'line',
          name: '读到哪',
          yAxisIndex: 0,
          data: percents.value,
          smooth: true,
          // 没有位置的那天断开，**不**用斜线连过去
          connectNulls: false,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: { width: 2, color: posColor },
          itemStyle: { color: posColor },
          z: 3,
        }
      : {
          type: 'scatter',
          name: '读到哪',
          yAxisIndex: 0,
          data: percents.value,
          symbolSize: 9,
          itemStyle: { color: posColor },
          z: 3,
        }

  return {
    color: p,
    tooltip: {
      trigger: 'axis',
      formatter: (ps: { dataIndex: number }[]) => {
        const i = ps?.[0]?.dataIndex
        const d = props.days[i]
        if (!d) return ''
        const where = d.end_percent == null ? '位置未记录' : `读到 ${d.end_percent.toFixed(1)}%`
        return (
          `<strong>${d.date}</strong><br/>` +
          `${fmtMinutes(d.seconds)}（${d.sessions} 次）<br/>${where}`
        )
      },
      ...t.tooltip,
    },
    legend: { ...t.legend, data: ['读到哪', '读了多久'], top: 0, right: 0 },
    grid: { left: '3%', right: '3%', bottom: '3%', top: 34, containLabel: true },
    xAxis: {
      ...t.axis,
      type: 'category',
      data: labels.value,
      axisLabel: { ...t.axisLabelStyle, fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: [
      {
        ...t.axis,
        type: 'value',
        name: '位置',
        min: 0,
        max: 100,
        axisLabel: { ...t.axisLabelStyle, fontSize: 10, formatter: '{value}%' },
      },
      {
        ...t.axis,
        type: 'value',
        name: '时长',
        // 右轴不画分割线：两条轴的分割线错位会让整张图看着像有网格没对齐
        splitLine: { show: false },
        axisLabel: { ...t.axisLabelStyle, fontSize: 10, formatter: '{value} 分' },
      },
    ],
    series: [
      position,
      {
        type: 'bar',
        name: '读了多久',
        yAxisIndex: 1,
        data: minutes.value,
        // 柱子压到轴后面：位置点/线是这张图的主语，时长是背景
        itemStyle: { color: timeColor, opacity: 0.28 },
        barMaxWidth: 22,
        z: 1,
      },
    ],
  }
})
</script>

<template>
  <Card padding="none">
    <div class="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
      <div class="min-w-0 flex-1">
        <h3 class="text-[13px] font-semibold text-foreground">进度随时间</h3>
        <p class="mt-1 text-[11px] text-muted-foreground">
          每个点是<strong class="text-foreground/70">当天最后一次</strong>已知位置；柱子是当天读了多少。
        </p>
      </div>
      <!-- 两种看法，不是两种美化：见文件头那张开关的说明 -->
      <div class="flex shrink-0 items-center gap-1">
        <button
          v-for="m in MODES"
          :key="m.key"
          type="button"
          class="cursor-pointer rounded-md border px-2 py-1 text-[11.5px] transition-colors"
          :class="
            mode === m.key
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-border text-muted-foreground hover:border-ring hover:text-foreground'
          "
          :title="m.hint"
          @click="mode = m.key"
        >
          {{ m.label }}
        </button>
      </div>
    </div>

    <div class="h-[280px] px-2 py-3">
      <ChartFrame :option="option" />
    </div>

    <p class="border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
      {{ span }} · 共 {{ days.length }} 天有阅读记录<template v-if="missingPos">
        · 其中 {{ missingPos }} 天没有位置记录（图上断开）</template>
    </p>
  </Card>
</template>
