<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useStatsStore } from '@/stores/stats'

/**
 * 入库节奏（对应 BookOrbit 的 ReadingRhythmWidget）。
 * 数据来自 /api/stats 的 added_28d（按成品文件 mtime 统计，真实值）。
 */
const stats = useStatsStore()
onMounted(() => stats.load())

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
  <div class="flex h-full flex-col rounded-lg border border-border bg-card p-4 shadow-sm">
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
  </div>
</template>
