<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { useStatsStore } from '@/stores/stats'

/**
 * 多样性评分：作者 / 系列 / 格式 / 语言 四维覆盖率综合得分。
 * 本项目生成的 EPUB 常缺 dc:subject，故不把「体裁」计入，改用稳定可得的四维。
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

const dims = computed(() => {
  const s = stats.data
  if (!s) return []
  const t = Math.max(1, s.books.total)
  return [
    { label: '作者', ratio: s.authors.total / t },
    { label: '系列', ratio: s.series.total / t },
    { label: '格式', ratio: Object.keys(s.books.by_format).length / t },
    { label: '语言', ratio: s.books.languages / t },
  ]
})

const score = computed(() => {
  if (!dims.value.length) return 0
  const avg = dims.value.reduce((acc, d) => acc + Math.min(1, d.ratio * 4), 0) / dims.value.length
  return Math.round(avg * 100)
})
</script>

<template>
  <div class="flex h-full flex-col p-3">
    <template v-if="state === 'loading'">
      <div class="flex items-baseline justify-between">
        <div class="h-3.5 w-16 animate-pulse rounded bg-muted" />
        <div class="h-6 w-10 animate-pulse rounded bg-muted" />
      </div>
      <div class="mt-3 flex flex-1 flex-col justify-center gap-2.5">
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
    <div class="flex items-baseline justify-between">
      <h3 class="text-[13px] font-semibold text-foreground">多样性评分</h3>
      <span class="text-[20px] leading-none font-semibold text-foreground tabular-nums">{{ score }}</span>
    </div>
    <div class="mt-2.5 flex flex-1 flex-col justify-between gap-1.5">
      <div v-for="d in dims" :key="d.label">
        <div class="flex items-baseline justify-between">
          <span class="text-[11px] text-muted-foreground">{{ d.label }}</span>
          <span class="text-[11px] text-muted-foreground tabular-nums">{{ Math.round(d.ratio * 100) }}%</span>
        </div>
        <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div class="h-full rounded-full bg-primary/80" :style="{ width: `${Math.min(1, d.ratio * 4) * 100}%` }" />
        </div>
      </div>
    </div>
    </template>
  </div>
</template>
