<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { useStatsStore } from '@/stores/stats'

/**
 * 阅读基因：篇幅 / 多样性 / 节奏 / 时段四项刻画。
 * 全部由 /api/stats 的真实聚合推导（无则显示 —）。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 */
defineProps<{
  /** 宽度档由部件行下发（对齐上游契约） */
  size?: WidgetSize
}>()

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

/** 数据态：加载中 / 失败可重试；「暂无数据」仅在确实加载完且无聚合时出现 */
const state = useWidgetState(() => ({
  loading: !stats.loaded && !stats.error,
  error: stats.error,
  empty: stats.loaded && !stats.error && dims.value.length === 0,
}))
</script>

<template>
  <div class="flex h-full flex-col p-3">
    <template v-if="state === 'loading'">
      <div class="h-3.5 w-16 animate-pulse rounded bg-muted" />
      <div class="mt-3 flex flex-1 flex-col justify-center gap-3">
        <div v-for="n in 4" :key="n" class="space-y-1.5">
          <div class="h-2.5 w-full animate-pulse rounded bg-muted" />
          <div class="h-1 w-full animate-pulse rounded bg-muted" />
        </div>
      </div>
    </template>

    <div v-else-if="state === 'error'" class="flex flex-1 items-center gap-2 text-[11.5px] text-muted-foreground">
      <span>统计加载失败</span>
      <button type="button" class="cursor-pointer text-primary hover:underline" @click="stats.load(true)">
        重试
      </button>
    </div>

    <template v-else>
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
    </template>
  </div>
</template>
