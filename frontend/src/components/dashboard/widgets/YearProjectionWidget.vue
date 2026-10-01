<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import Icon from '@/components/ui/Icon.vue'
import { useStatsStore } from '@/stores/stats'

/**
 * 年度预测：按近 28 天入库节奏，推算年底累计册数。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 * 第 83 期：补趋势图标（升 / 降 / 平）——把「最近半程比前半程快还是慢」摆出来，
 * 否则一个孤零零的预测数看不出节奏在往哪走。
 */
defineProps<{
  /** 宽度档由部件行下发（对齐上游契约） */
  size?: WidgetSize
}>()

const stats = useStatsStore()
onMounted(() => stats.load())

/** 数据态：只读 store 的真实字段（加载中 / 失败可重试） */
const state = useWidgetState(() => ({
  loading: !stats.loaded && !stats.error,
  error: stats.error,
}))

const proj = computed(() => {
  const s = stats.data
  if (!s) return null
  const rate = s.added_28d.reduce((a, b) => a + b, 0) / 28
  const now = new Date()
  const start = new Date(now.getFullYear(), 0, 0)
  const dayOfYear = Math.floor((now.getTime() - start.getTime()) / 86400000)
  const year = now.getFullYear()
  const daysInYear = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0 ? 366 : 365
  return {
    rate,
    projected: Math.round(s.books.total + rate * Math.max(0, daysInYear - dayOfYear)),
  }
})

/**
 * 趋势：窗口**后半程**日均 vs **前半程**日均（同一份 `added_28d`，零新增请求）。
 *
 * ⚠️ 阈值 0.15 本/天是**刻意的**：库里每天 0.1 本的抖动不该被画成「在加速」，
 * 那会让人按一个假的趋势去调目标。差异小于阈值算「持平」。
 */
const trend = computed<'up' | 'down' | 'flat'>(() => {
  const d = stats.data?.added_28d ?? []
  if (d.length < 4) return 'flat'
  const half = Math.floor(d.length / 2)
  const prevDays = d.slice(0, half)
  const curDays = d.slice(half)
  const avg = (xs: number[]): number => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0)
  const diff = avg(curDays) - avg(prevDays)
  if (Math.abs(diff) < 0.15) return 'flat'
  return diff > 0 ? 'up' : 'down'
})

/** 趋势图标与语义色（升 = 成功、降 = 警示、平 = 次要；不硬编码颜色） */
const TREND_META = {
  up: { icon: 'trendingUp', cls: 'text-success', label: '比前半程快' },
  down: { icon: 'trendingDown', cls: 'text-warning', label: '比前半程慢' },
  flat: { icon: 'minus', cls: 'text-muted-foreground', label: '与前半程持平' },
} as const

const trendMeta = computed(() => TREND_META[trend.value])
</script>

<template>
  <div class="flex h-full flex-col justify-between p-3">
    <template v-if="state === 'loading'">
      <div class="h-3.5 w-16 animate-pulse rounded bg-muted" />
      <div class="space-y-2">
        <div class="h-7 w-16 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-24 animate-pulse rounded bg-muted" />
      </div>
    </template>

    <div v-else-if="state === 'error'" class="flex flex-1 items-center gap-2 text-[11.5px] text-muted-foreground">
      <span>统计加载失败</span>
      <button type="button" class="cursor-pointer text-primary hover:underline" @click="stats.load(true)">
        重试
      </button>
    </div>

    <template v-else>
    <h3 class="text-[13px] font-semibold text-foreground">年度预测</h3>
    <div>
      <div class="flex items-baseline gap-1.5">
        <span class="text-[24px] leading-none font-semibold text-foreground tabular-nums">
          {{ proj?.projected ?? 0 }}
        </span>
        <span class="text-[11.5px] text-muted-foreground">本</span>
        <!-- 趋势：最近半程 vs 前半程（图标 + 语义色，tooltip 说清方向） -->
        <Icon :name="trendMeta.icon" class="h-3.5 w-3.5" :class="trendMeta.cls" :title="trendMeta.label" />
      </div>
      <p class="mt-1.5 text-[10.5px] text-muted-foreground tabular-nums">
        按 {{ (proj?.rate ?? 0).toFixed(1) }} 本/天 推算 · {{ trendMeta.label }}
      </p>
    </div>
    </template>
  </div>
</template>
