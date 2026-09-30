<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { useStatsStore } from '@/stores/stats'

/**
 * 年度预测：按近 28 天入库节奏，推算年底累计册数。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
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
      </div>
      <p class="mt-1.5 text-[10.5px] text-muted-foreground tabular-nums">
        按 {{ (proj?.rate ?? 0).toFixed(1) }} 本/天 推算
      </p>
    </div>
    </template>
  </div>
</template>
