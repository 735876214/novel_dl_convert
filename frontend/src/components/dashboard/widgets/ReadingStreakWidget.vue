<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useStatsStore } from '@/stores/stats'

/** 连续天数：当前连续阅读天数 + 最近 7 天点阵（来自会话记录）。 */
const stats = useStatsStore()
onMounted(() => stats.load())

const streak = computed(() => stats.data?.reading.streak ?? 0)
const last7 = computed<number[]>(() => (stats.data?.reading_28d ?? []).slice(-7))
</script>

<template>
  <div class="flex h-full flex-col justify-between rounded-lg border border-border bg-card p-4 shadow-sm">
    <div>
      <div class="flex items-baseline gap-1.5">
        <span class="text-[24px] leading-none font-semibold text-foreground tabular-nums">{{ streak }}</span>
        <span class="text-[11.5px] text-muted-foreground">天连续阅读</span>
      </div>
      <div class="mt-3 flex items-center gap-1.5">
        <span
          v-for="(n, i) in last7"
          :key="i"
          class="h-2.5 w-2.5 rounded-full"
          :class="n > 0 ? 'bg-primary' : 'bg-muted'"
          :title="`${7 - i} 天前${n > 0 ? ' · 有阅读' : ''}`"
        />
      </div>
    </div>
    <p class="mt-2 text-[10.5px] text-muted-foreground">最近 7 天</p>
  </div>
</template>
