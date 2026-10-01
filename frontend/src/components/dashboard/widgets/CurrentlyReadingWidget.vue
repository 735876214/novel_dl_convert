<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import type { BookCard } from '@/lib/api'
import { openTargetOf } from '@/lib/bookOpen'
import { useLibraryStore } from '@/stores/library'

/**
 * 正在阅读：已打开但未读完的书，按最近阅读时间排序。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 * 第 83 期：补封面缩略图；开书的目标改走 `lib/bookOpen.ts`（此前写死 `/read/`，
 * 有声书点下去是打不开的阅读器 —— 应进 `/listen/`）。
 */
defineProps<{
  /** 宽度档由部件行下发（对齐上游契约） */
  size?: WidgetSize
}>()

const library = useLibraryStore()
const router = useRouter()

onMounted(() => library.loadBooks())

const items = computed(() => library.continueReading.slice(0, 3))

/** 开书目标：能读就读、能听就听，都不支持才落到详情页（不在本件里另写一套判据） */
function openBook(b: BookCard): void {
  void router.push(openTargetOf(b)?.to ?? `/book/${b.id}`)
}

/**
 * 空态分两种情况说（第 38 期）。
 *
 * 「打开一本开始阅读吧」在**一个书库都没有**时是句空话：没有书可打开，
 * 也没有阅读器可进。0 库时改说「还没有书库」，别让人去找一本不存在的书。
 * （书目没回来时是「加载中」，由统一的数据态封装给骨架。）
 */
const emptyText = computed(() =>
  library.hasNoLibraries ? '还没有书库。' : '还没有在读的书，打开一本开始阅读吧。',
)

/** 数据态：只读 store 的真实字段（library 无 error 字段，故只有加载/空两态） */
const state = useWidgetState(() => ({
  loading: !library.loaded,
  empty: library.loaded && !items.value.length,
}))
</script>

<template>
  <div class="flex h-full flex-col p-3">
    <template v-if="state === 'loading'">
      <div class="flex items-baseline justify-between">
        <div class="h-3.5 w-16 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-8 animate-pulse rounded bg-muted" />
      </div>
      <div class="mt-3 space-y-3">
        <div v-for="n in 3" :key="n" class="space-y-1.5">
          <div class="h-3 w-3/4 animate-pulse rounded bg-muted" />
          <div class="h-1 w-full animate-pulse rounded-full bg-muted" />
        </div>
      </div>
    </template>

    <template v-else>
    <div class="flex items-baseline justify-between">
      <h3 class="text-[13px] font-semibold text-foreground">正在阅读</h3>
      <span class="text-[11px] text-muted-foreground tabular-nums">
        {{ library.continueReading.length }} 本
      </span>
    </div>

    <p v-if="!items.length" class="mt-2 text-[11.5px] text-muted-foreground">{{ emptyText }}</p>

    <button
      v-for="b in items"
      :key="b.id"
      type="button"
      class="mt-2 flex w-full cursor-pointer items-center gap-2.5 text-left"
      @click="openBook(b)"
    >
      <div class="w-8 shrink-0 overflow-hidden rounded-sm">
        <BookCover :book="b" :show-title="false" :interactive="false" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="truncate text-[12.5px] text-foreground">{{ b.title }}</div>
        <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div class="h-full rounded-full bg-primary" :style="{ width: `${b.percent ?? 0}%` }" />
        </div>
      </div>
      <span class="shrink-0 text-[11px] text-muted-foreground tabular-nums">
        {{ Math.round(b.percent ?? 0) }}%
      </span>
    </button>
    </template>
  </div>
</template>
