<script setup lang="ts">
import { computed } from 'vue'

import { RHYTHM_28D } from '@/data/dashboard-stats'

/**
 * 入库节奏（对应 BookOrbit 的 ReadingRhythmWidget）。
 * 最近 28 天每日入库数量柱状图，柱高按数值映射；下方一行平均读数。
 * 数据是确定性常量，因此每次渲染图形一致。
 */
const days = RHYTHM_28D
const peak = computed(() => Math.max(1, ...days))

/** 柱高百分比（0 值保留 2% 底座，避免完全看不见） */
function heightOf(n: number): string {
  if (n <= 0) return '2%'
  return `${Math.max(6, (n / peak.value) * 100).toFixed(1)}%`
}

/** 平均读数：只对「有记录的天」求平均，与 BookOrbit 的口径一致 */
const activeDays = computed(() => days.filter((n) => n > 0))
const average = computed(() => {
  if (!activeDays.value.length) return '0'
  const sum = activeDays.value.reduce((a, b) => a + b, 0)
  return (sum / activeDays.value.length).toFixed(1)
})

const total = computed(() => days.reduce((a, b) => a + b, 0))
</script>

<template>
  <div class="flex h-full flex-col rounded-lg border border-border bg-card p-4 shadow-sm">
    <div class="flex items-baseline justify-between">
      <h3 class="text-[13px] font-semibold text-foreground">入库节奏</h3>
      <span class="text-[11px] text-muted-foreground tabular-nums">近 28 天 · 共 {{ total }} 本</span>
    </div>

    <!-- 柱状图：纯 CSS 高度映射，无图表库 -->
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
