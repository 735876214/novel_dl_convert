<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useStatsStore } from '@/stores/stats'

/**
 * 阅读基因：篇幅 / 多样性 / 节奏 / 时段四项刻画。
 * 全部由 /api/stats 的真实聚合推导（无则显示 —）。
 */
const stats = useStatsStore()
onMounted(() => stats.load())

interface Dim {
  label: string
  value: string
  pct: number
}

const dims = computed<Dim[]>(() => {
  const s = stats.data
  if (!s) return []
  const total = Math.max(1, s.books.total)

  const avgMb = total ? s.books.size / total / 1024 / 1024 : 0
  const diversity = s.authors.total / total
  const rhythm = s.reading.days ? s.reading.sessions / s.reading.days : 0

  const peak = Math.max(0, ...s.hours)
  const peakHour = peak > 0 ? s.hours.indexOf(peak) : -1
  const peakLabel = peakHour >= 0 ? `${String(peakHour).padStart(2, '0')}:00` : '—'

  return [
    { label: '篇幅', value: avgMb ? `${avgMb.toFixed(1)} MB` : '—', pct: Math.min(1, avgMb / 5) },
    { label: '多样性', value: `${Math.round(diversity * 100)}%`, pct: Math.min(1, diversity) },
    { label: '节奏', value: rhythm ? `${rhythm.toFixed(1)} 次/日` : '—', pct: Math.min(1, rhythm / 3) },
    { label: '时段', value: peakLabel, pct: peak > 0 ? Math.min(1, peak / Math.max(1, s.reading.sessions)) : 0 },
  ]
})
</script>

<template>
  <div class="flex h-full flex-col rounded-lg border border-border bg-card p-4 shadow-sm">
    <h3 class="text-[13px] font-semibold text-foreground">阅读基因</h3>
    <p v-if="!dims.length" class="mt-2 text-[11.5px] text-muted-foreground">暂无数据。</p>
    <div v-else class="mt-2.5 flex flex-1 flex-col justify-between gap-2">
      <div v-for="d in dims" :key="d.label">
        <div class="flex items-baseline justify-between">
          <span class="text-[11.5px] text-muted-foreground">{{ d.label }}</span>
          <span class="text-[11.5px] font-medium text-foreground tabular-nums">{{ d.value }}</span>
        </div>
        <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div class="h-full rounded-full bg-primary/80" :style="{ width: `${d.pct * 100}%` }" />
        </div>
      </div>
    </div>
  </div>
</template>
