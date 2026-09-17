<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useStatsStore } from '@/stores/stats'

/** 年度预测：按近 28 天入库节奏，推算年底累计册数。 */
const stats = useStatsStore()
onMounted(() => stats.load())

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
  <div class="flex h-full flex-col justify-between rounded-lg border border-border bg-card p-4 shadow-sm">
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
  </div>
</template>
