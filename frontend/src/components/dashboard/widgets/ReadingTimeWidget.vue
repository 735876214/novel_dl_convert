<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { fmtDuration } from '@/lib/format'
import { useStatsStore } from '@/stores/stats'

/**
 * 阅读时长（第 83 期新增 —— 本项目自开的第 13 件部件）。
 *
 * 为什么另开一件而不是改 `ReadingRhythmWidget`：上游 `reading-rhythm` 是**阅读时长**语义，
 * 但本项目那个 id 已落定为「入库节奏」（入库数量 `added_28d`），且 id 是 localStorage 键、
 * 不可改名 ⇒ 保留原 id 的语义，另开本件把上游的时长语义补回来。
 *
 * 数据来自 `/api/stats` 的 `reading_28d`（近 N 天每日**阅读秒数**；索引 0 = N-1 天前、
 * 末尾 = 今天；N 取 `window`）—— 与统计页的节奏图**同源**，零新增接口。
 * ⚠️ 卡片外壳在 `DashboardWidgetRow`，本件只负责填满卡片。
 */
defineProps<{
  /** 宽度档由部件行下发（对齐上游契约） */
  size?: WidgetSize
}>()

const stats = useStatsStore()
onMounted(() => stats.load())

const days = computed<number[]>(() => stats.data?.reading_28d ?? [])
const windowDays = computed(() => stats.data?.window ?? days.value.length)

const totalSeconds = computed(() => days.value.reduce((a, b) => a + b, 0))
const activeDays = computed(() => days.value.filter((n) => n > 0).length)

/**
 * 活跃日平均：**只按有阅读记录的天数**平均（与统计页「每个活跃日平均」同口径）。
 * 没有活跃日时给 null（不编造 0）。
 */
const avgSeconds = computed(() =>
  activeDays.value ? Math.round(totalSeconds.value / activeDays.value) : null,
)

/** 数据态：只读 store 的真实字段（加载中 / 失败可重试 / 窗口内没记录） */
const state = useWidgetState(() => ({
  loading: !stats.loaded && !stats.error,
  error: stats.error,
  empty: stats.loaded && !stats.error && totalSeconds.value === 0,
}))

const peak = computed(() => Math.max(1, ...days.value))

/** 柱高百分比（0 值保留小底座，避免完全看不见 —— 与「入库节奏」同口径） */
function heightOf(n: number): string {
  if (n <= 0) return '3%'
  return `${Math.max(8, (n / peak.value) * 100).toFixed(1)}%`
}

/** 悬停提示：「N 天前：X 分」 */
function titleOf(n: number, i: number): string {
  const ago = Math.max(0, windowDays.value - i)
  return ago <= 0 ? `今天：${fmtDuration(n)}` : `${ago} 天前：${fmtDuration(n)}`
}
</script>

<template>
  <div class="flex h-full flex-col p-3">
    <template v-if="state === 'loading'">
      <div class="flex items-baseline justify-between">
        <div class="h-3.5 w-16 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-20 animate-pulse rounded bg-muted" />
      </div>
      <div class="mt-3 flex h-[68px] flex-1 items-end gap-[3px]">
        <div
          v-for="n in windowDays || 28"
          :key="n"
          class="min-w-0 flex-1 animate-pulse rounded-[2px] bg-muted"
          style="height: 30%"
        />
      </div>
      <div class="mt-2.5 h-2.5 w-32 animate-pulse rounded bg-muted" />
    </template>

    <div
      v-else-if="state === 'error'"
      class="flex flex-1 items-center gap-2 text-[11.5px] text-muted-foreground"
    >
      <span>统计加载失败</span>
      <button type="button" class="cursor-pointer text-primary hover:underline" @click="stats.load(true)">
        重试
      </button>
    </div>

    <div
      v-else-if="state === 'empty'"
      class="flex flex-1 flex-col items-center justify-center gap-2 text-center"
    >
      <h3 class="text-[13px] font-semibold text-foreground">阅读时长</h3>
      <p class="text-[11.5px] text-muted-foreground">近 {{ windowDays }} 天还没有阅读记录</p>
    </div>

    <template v-else>
      <div class="flex items-baseline justify-between">
        <h3 class="text-[13px] font-semibold text-foreground">阅读时长</h3>
        <span class="text-[11px] text-muted-foreground tabular-nums">
          近 {{ windowDays }} 天 · 共 {{ fmtDuration(totalSeconds) }}
        </span>
      </div>

      <div
        class="mt-3 flex h-[68px] flex-1 items-end gap-[3px]"
        role="img"
        :aria-label="`最近 ${windowDays} 天每日阅读时长`"
      >
        <div
          v-for="(n, i) in days"
          :key="i"
          class="min-w-0 flex-1 rounded-[2px] transition-[height] duration-300 ease-out"
          :class="n > 0 ? 'bg-primary/85 hover:bg-primary' : 'bg-muted'"
          :style="{ height: heightOf(n) }"
          :title="titleOf(n, i)"
        />
      </div>

      <p class="mt-2.5 text-[11.5px] text-muted-foreground">
        活跃日平均
        <span class="font-semibold text-foreground tabular-nums">
          {{ avgSeconds === null ? '—' : fmtDuration(avgSeconds) }}
        </span>
        <span v-if="activeDays" class="ml-1 text-[10.5px]">（{{ activeDays }} 天有记录）</span>
      </p>
    </template>
  </div>
</template>
