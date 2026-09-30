<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { useLibraryStore } from '@/stores/library'
import { useStatsStore } from '@/stores/stats'

/**
 * 书库概览卡（对应 BookOrbit 的 LibraryOverviewWidget）。
 * 数字来自 /api/stats（真实书目聚合），点任一统计项跳到对应板块。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 */
defineProps<{
  /** 宽度档由部件行下发（对齐上游契约）；本件两种档位都是四格横排，不分支渲染 */
  size?: WidgetSize
}>()

const library = useLibraryStore()
const stats = useStatsStore()
const router = useRouter()

onMounted(() => {
  library.loadBooks()
  stats.load()
})

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const gb = bytes / 1024 ** 3
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  return `${(bytes / 1024 ** 2).toFixed(0)} MB`
}

const s = computed(() => stats.data)

const cards = computed(() => [
  { label: '书籍', value: String(s.value?.books.total ?? library.books.length), to: '/shelf' },
  { label: '作者', value: String(s.value?.authors.total ?? 0), to: '/authors' },
  { label: '系列', value: String(s.value?.series.total ?? 0), to: '/series' },
  { label: '占用', value: fmtBytes(s.value?.books.size ?? 0), to: '/stats' },
])

/** 近 28 天入库总数（真实值，替代原演示常量） */
const added28 = computed(() => (s.value?.added_28d ?? []).reduce((a, b) => a + b, 0))

/** 数据态：加载中（首次拉取）/ 失败（可重试）—— 只读 store 的真实字段 */
const state = useWidgetState(() => ({
  loading: !stats.loaded && !stats.error,
  error: stats.error,
}))
</script>

<template>
  <div class="flex h-full flex-col p-3">
    <template v-if="state === 'loading'">
      <div class="flex flex-1 items-start justify-between gap-4">
        <div v-for="n in 4" :key="n" class="flex-1 space-y-1.5 px-2 py-1">
          <div class="h-6 w-14 animate-pulse rounded bg-muted" />
          <div class="h-2.5 w-10 animate-pulse rounded bg-muted" />
        </div>
      </div>
      <div class="mt-3 h-9 animate-pulse rounded-md bg-muted" />
    </template>

    <div v-else-if="state === 'error'" class="flex flex-1 items-center gap-2 text-[11.5px] text-muted-foreground">
      <span>统计加载失败</span>
      <button
        type="button"
        class="cursor-pointer text-primary hover:underline"
        @click="stats.load(true)"
      >
        重试
      </button>
    </div>

    <template v-else>
    <div class="flex flex-1 items-start justify-between gap-4">
      <button
        v-for="c in cards"
        :key="c.label"
        type="button"
        class="group flex flex-1 cursor-pointer flex-col items-start gap-0.5 rounded-md px-2 py-1 text-left transition-colors hover:bg-muted"
        @click="router.push(c.to)"
      >
        <span class="text-[22px] leading-tight font-semibold tracking-tight text-foreground tabular-nums">
          {{ c.value }}
        </span>
        <span class="text-[11px] tracking-wide text-muted-foreground">{{ c.label }}</span>
      </button>
    </div>

    <div class="mt-3 flex items-center gap-2 rounded-md bg-muted px-3 py-2">
      <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
      <span class="text-[11.5px] text-muted-foreground">
        近 28 天入库 <span class="font-semibold text-foreground tabular-nums">{{ added28 }}</span> 本
      </span>
    </div>
    </template>
  </div>
</template>
