<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { isInProgress } from '@/lib/readingThresholds'
import { useLibraryStore } from '@/stores/library'

/**
 * 被遗忘的佳作：已开始却最久未触碰的一本书。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 */
defineProps<{
  /** 宽度档由部件行下发（对齐上游契约） */
  size?: WidgetSize
}>()

const library = useLibraryStore()
const router = useRouter()

onMounted(() => library.loadBooks())

const gem = computed(() => {
  // 「在读但没读完」用唯一入口判（第 40 期起阈值可配），不自己写死 99.5
  const list = library.books.filter(
    (b) => isInProgress(b.percent, library.currentLibraryId) && (b.updated_at ?? 0) > 0,
  )
  if (!list.length) return null
  return [...list].sort((a, b) => (a.updated_at ?? 0) - (b.updated_at ?? 0))[0]
})

const daysAgo = computed(() => {
  const t = gem.value?.updated_at ?? 0
  if (!t) return 0
  return Math.max(0, Math.floor((Date.now() / 1000 - t) / 86400))
})

/**
 * 空态分两种情况说（第 38 期口径，此前这里只有一句，未做区分）。
 * 「数据态」用统一封装：书目没回来时是「加载中」，不再把「没有」与「加载中」混说。
 */
const emptyText = computed(() =>
  library.hasNoLibraries ? '还没有书库。' : '暂时没有搁置的书。',
)

const state = useWidgetState(() => ({
  loading: !library.loaded,
  empty: library.loaded && !gem.value,
}))
</script>

<template>
  <div class="flex h-full flex-col justify-between p-3">
    <h3 class="text-[13px] font-semibold text-foreground">被遗忘的佳作</h3>

    <template v-if="state === 'loading'">
      <div class="mt-2 space-y-1.5">
        <div class="h-3 w-3/4 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-1/2 animate-pulse rounded bg-muted" />
      </div>
      <div class="h-2.5 w-2/3 animate-pulse rounded bg-muted" />
    </template>

    <p v-else-if="!gem" class="mt-2 text-[11.5px] text-muted-foreground">{{ emptyText }}</p>

    <button
      v-else
      type="button"
      class="mt-2 cursor-pointer text-left"
      @click="router.push(`/read/${gem.id}`)"
    >
      <div class="truncate text-[12.5px] font-medium text-foreground">{{ gem.title }}</div>
      <div class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ gem.author }}</div>
    </button>

    <p v-if="gem" class="mt-2 text-[10.5px] text-muted-foreground tabular-nums">
      已 {{ daysAgo }} 天未继续 · 读到 {{ Math.round(gem.percent ?? 0) }}%
    </p>
  </div>
</template>
