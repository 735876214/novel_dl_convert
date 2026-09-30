<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { useStatsStore } from '@/stores/stats'

/** 连续天数：当前连续阅读天数 + 最近 7 天点阵（来自会话记录）。 */
const stats = useStatsStore()
onMounted(() => stats.load())

defineProps<{
  /** 宽度档由部件行下发（对齐上游契约） */
  size?: WidgetSize
}>()

/** 数据态：只读 store 的真实字段（加载中 / 失败可重试） */
const state = useWidgetState(() => ({
  loading: !stats.loaded && !stats.error,
  error: stats.error,
}))

const streak = computed(() => stats.data?.reading.streak ?? 0)
const last7 = computed<number[]>(() => (stats.data?.reading_28d ?? []).slice(-7))
</script>

<template>
  <div class="flex h-full flex-col justify-between p-3">
    <template v-if="state === 'loading'">
      <div class="space-y-3">
        <div class="h-7 w-20 animate-pulse rounded bg-muted" />
        <div class="flex gap-1.5">
          <div v-for="n in 7" :key="n" class="h-2.5 w-2.5 animate-pulse rounded-full bg-muted" />
        </div>
      </div>
      <div class="h-2.5 w-16 animate-pulse rounded bg-muted" />
    </template>

    <div v-else-if="state === 'error'" class="flex flex-1 items-center gap-2 text-[11.5px] text-muted-foreground">
      <span>统计加载失败</span>
      <button type="button" class="cursor-pointer text-primary hover:underline" @click="stats.load(true)">
        重试
      </button>
    </div>

    <template v-else>
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
    </template>
  </div>
</template>
