<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { useStatsStore } from '@/stores/stats'

/**
 * 入库节奏（对应 BookOrbit 的 ReadingRhythmWidget）。
 * 数据来自 /api/stats 的 added_28d（按成品文件 mtime 统计，真实值）。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 * 业务语义刻意与上游不同：上游统计「阅读时长」，本件统计**入库数量**（不改）。
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

const days = computed<number[]>(() => stats.data?.added_28d ?? new Array(28).fill(0))
const peak = computed(() => Math.max(1, ...days.value))

/** 柱高百分比（0 值保留小底座，避免完全看不见） */
function heightOf(n: number): string {
  if (n <= 0) return '3%'
  return `${Math.max(8, (n / peak.value) * 100).toFixed(1)}%`
}

const activeDays = computed(() => days.value.filter((n) => n > 0))
const average = computed(() => {
  if (!activeDays.value.length) return '0'
  const sum = activeDays.value.reduce((a, b) => a + b, 0)
  return (sum / activeDays.value.length).toFixed(1)
})
const total = computed(() => days.value.reduce((a, b) => a + b, 0))
</script>

<template>
  <div class="flex h-full flex-col p-3">
    <template v-if="state === 'loading'">
      <div class="flex items-baseline justify-between">
        <div class="h-3.5 w-16 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-20 animate-pulse rounded bg-muted" />
      </div>
      <div class="mt-3 flex h-[68px] flex-1 items-end gap-[3px]">
        <div v-for="n in 28" :key="n" class="min-w-0 flex-1 animate-pulse rounded-[2px] bg-muted" style="height: 30%" />
      </div>
      <div class="mt-2.5 h-2.5 w-32 animate-pulse rounded bg-muted" />
    </template>

    <div v-else-if="state === 'error'" class="flex flex-1 items-center gap-2 text-[11.5px] text-muted-foreground">
      <span>统计加载失败</span>
      <button type="button" class="cursor-pointer text-primary hover:underline" @click="stats.load(true)">
        重试
      </button>
    </div>

    <template v-else>
    <div class="flex items-baseline justify-between">
      <h3 class="text-[13px] font-semibold text-foreground">入库节奏</h3>
      <span class="text-[11px] text-muted-foreground tabular-nums">近 28 天 · 共 {{ total }} 本</span>
    </div>

    <div class="mt-3 flex h-[68px] flex-1 items-end gap-[3px]" role="img" aria-label="最近 28 天每日入库数量">
      <div
        v-for="(n, i) in days"
        :key="i"
        class="min-w-0 flex-1 rounded-[2px] transition-[height] duration-300 ease-out"
        :class="n > 0 ? 'bg-primary/85 hover:bg-primary' : 'bg-muted'"
        :style="{ height: heightOf(n) }"
        :title="`${28 - i} 天前：${n} 本`"
      />
    </div>

    <p class="mt-2.5 text-[11.5px] text-muted-foreground">
      每个活跃日平均 <span class="font-semibold text-foreground tabular-nums">{{ average }}</span> 本
    </p>
    </template>
  </div>
</template>
