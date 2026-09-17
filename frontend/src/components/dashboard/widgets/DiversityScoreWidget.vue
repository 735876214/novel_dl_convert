<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useStatsStore } from '@/stores/stats'

/**
 * 多样性评分：作者 / 系列 / 格式 / 语言 四维覆盖率综合得分。
 * 本项目生成的 EPUB 常缺 dc:subject，故不把「体裁」计入，改用稳定可得的四维。
 */
const stats = useStatsStore()
onMounted(() => stats.load())

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
  <div class="flex h-full flex-col rounded-lg border border-border bg-card p-4 shadow-sm">
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
  </div>
</template>
