<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { openTargetOf } from '@/lib/bookOpen'
import { useLibraryStore } from '@/stores/library'

/**
 * 等待最久：书库中未读、入库时间最早的一本书。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 * 第 83 期：补封面缩略图与「开始阅读 / 收听」入口（打开目标走 `lib/bookOpen.ts`）。
 */
defineProps<{
  /** 宽度档由部件行下发（对齐上游契约） */
  size?: WidgetSize
}>()

const library = useLibraryStore()
const router = useRouter()

onMounted(() => library.loadBooks())

const book = computed(() => {
  const unread = library.books.filter((b) => !(b.percent ?? 0))
  if (!unread.length) return null
  return [...unread].sort((a, b) => (a.mtime || 0) - (b.mtime || 0))[0]
})

/** 打开目标（能读就读、能听就听；都没有这个按钮干脆不出现，见模板） */
const target = computed(() => (book.value ? openTargetOf(book.value) : null))

function openBook(): void {
  const b = book.value
  if (!b) return
  void router.push(target.value?.to ?? `/book/${b.id}`)
}

const days = computed(() => {
  const t = book.value?.mtime ?? 0
  if (!t) return 0
  return Math.max(0, Math.floor((Date.now() / 1000 - t) / 86400))
})

/**
 * 空态分两种情况说（第 38 期）。
 *
 * 原来只有一句「书库里的书都读过啦。」—— 可是**一个书库都没有**时这句话
 * 是在宣称一件没发生过的事：没有书，哪来的「都读过」。0 库时如实说「还没有书」。
 */
const emptyText = computed(() => {
  // 书目还没回来时不下结论（`hasNoLibraries` 本身也要求书库已成功拉到）
  if (!library.loaded) return '正在载入…'
  return library.hasNoLibraries ? '还没有书库。' : '书库里的书都读过啦。'
})

/** 数据态：书目没回来时是「加载中」（此前用一行文字充当），不再与「没有」混说 */
const state = useWidgetState(() => ({
  loading: !library.loaded,
  empty: library.loaded && !book.value,
}))
</script>

<template>
  <div class="flex h-full flex-col justify-between p-3">
    <h3 class="text-[13px] font-semibold text-foreground">等待最久</h3>

    <template v-if="state === 'loading'">
      <div class="mt-2 space-y-1.5">
        <div class="h-3 w-3/4 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-1/2 animate-pulse rounded bg-muted" />
      </div>
      <div class="h-2.5 w-1/2 animate-pulse rounded bg-muted" />
    </template>

    <p v-else-if="!book" class="mt-2 text-[11.5px] text-muted-foreground">{{ emptyText }}</p>

    <div v-else class="mt-2 flex items-center gap-2.5">
      <div class="w-9 shrink-0 overflow-hidden rounded-sm">
        <BookCover :book="book" :show-title="false" :interactive="false" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="truncate text-[12.5px] font-medium text-foreground">{{ book.title }}</div>
        <div class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ book.author }}</div>
      </div>
    </div>

    <div v-if="book" class="mt-2 flex items-center justify-between gap-2">
      <span class="min-w-0 truncate text-[10.5px] text-muted-foreground tabular-nums">
        已等待 {{ days }} 天未读
      </span>
      <!-- 不能读也不能听的格式（如未归一成书的 ZIP 容器）不给入口 —— 灰置等于承认「本该有但不给你」 -->
      <button
        v-if="target"
        type="button"
        class="shrink-0 cursor-pointer text-[11px] font-medium text-primary hover:underline"
        @click="openBook"
      >
        开始{{ target.label }}
      </button>
    </div>
  </div>
</template>
