<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { openTargetOf } from '@/lib/bookOpen'
import { isInProgress } from '@/lib/readingThresholds'
import { useLibraryStore } from '@/stores/library'

/**
 * 被遗忘的佳作：已开始却最久未触碰的一本书。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 * 第 83 期：补封面缩略图与「开始阅读 / 收听」入口；打开目标走 `lib/bookOpen.ts`
 * （此前写死 `/read/`，有声书点下去是打不开的阅读器）。
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

/** 打开目标（能读就读、能听就听；都没有这个按钮干脆不出现，见模板） */
const target = computed(() => (gem.value ? openTargetOf(gem.value) : null))

function openGem(): void {
  const g = gem.value
  if (!g) return
  void router.push(target.value?.to ?? `/book/${g.id}`)
}

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

    <div v-else class="mt-2 flex items-center gap-2.5">
      <div class="w-9 shrink-0 overflow-hidden rounded-sm">
        <BookCover :book="gem" :show-title="false" :interactive="false" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="truncate text-[12.5px] font-medium text-foreground">{{ gem.title }}</div>
        <div class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ gem.author }}</div>
      </div>
    </div>

    <div v-if="gem" class="mt-2 flex items-center justify-between gap-2">
      <span class="min-w-0 truncate text-[10.5px] text-muted-foreground tabular-nums">
        已 {{ daysAgo }} 天未继续 · 读到 {{ Math.round(gem.percent ?? 0) }}%
      </span>
      <!-- 不能读也不能听的格式（如 MOBI）不给入口 —— 灰置等于承认「本该有但不给你」 -->
      <button
        v-if="target"
        type="button"
        class="shrink-0 cursor-pointer text-[11px] font-medium text-primary hover:underline"
        @click="openGem"
      >
        开始{{ target.label }}
      </button>
    </div>
  </div>
</template>
