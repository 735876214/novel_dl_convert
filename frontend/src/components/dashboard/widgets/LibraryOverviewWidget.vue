<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { LIBRARY_BYTES } from '@/data/dashboard-stats'
import { useLibraryStore } from '@/stores/library'

/**
 * 书库概览卡（对应 BookOrbit 的 LibraryOverviewWidget）。
 * 几组数字横排 + 底部一条提示条，点任一统计项跳到对应板块。
 */
const library = useLibraryStore()
const router = useRouter()

const authorCount = computed(() => new Set(library.books.map((b) => b.author)).size)
const seriesCount = computed(() => new Set(library.books.filter((b) => b.series).map((b) => b.series)).size)

function fmtBytes(bytes: number): string {
  const gb = bytes / 1024 ** 3
  return `${gb.toFixed(1)} GB`
}

const stats = computed(() => [
  { label: '书籍', value: String(library.books.length), to: '/shelf' },
  { label: '作者', value: String(authorCount.value), to: '/placeholder/_authors' },
  { label: '系列', value: String(seriesCount.value), to: '/placeholder/_series' },
  { label: '占用', value: fmtBytes(LIBRARY_BYTES), to: '/placeholder/stats' },
])
</script>

<template>
  <div class="flex h-full flex-col rounded-lg border border-border bg-card p-4 shadow-sm">
    <div class="flex flex-1 items-start justify-between gap-4">
      <button
        v-for="s in stats"
        :key="s.label"
        type="button"
        class="group flex flex-1 cursor-pointer flex-col items-start gap-0.5 rounded-md px-2 py-1 text-left transition-colors hover:bg-muted"
        @click="router.push(s.to)"
      >
        <span class="text-[22px] leading-tight font-semibold tracking-tight text-foreground tabular-nums">
          {{ s.value }}
        </span>
        <span class="text-[11px] tracking-wide text-muted-foreground">{{ s.label }}</span>
      </button>
    </div>

    <!-- 底部提示条：今年新增 -->
    <div class="mt-3 flex items-center gap-2 rounded-md bg-muted px-3 py-2">
      <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
      <span class="text-[11.5px] text-muted-foreground">
        今年已入库 <span class="font-semibold text-foreground tabular-nums">38</span> 本，较去年同期多 11 本
      </span>
    </div>
  </div>
</template>
