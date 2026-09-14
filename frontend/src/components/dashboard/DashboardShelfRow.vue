<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Icon from '@/components/ui/Icon.vue'
import type { Book } from '@/data/books'
import type { ShelfDef } from '@/data/dashboard'
import { useLibraryStore } from '@/stores/library'

const props = defineProps<{ shelf: ShelfDef }>()

const library = useLibraryStore()
const router = useRouter()

/**
 * 「随机发现」的洗牌只在**模块加载时算一次**：
 *   · 刷新页面会重新洗牌（符合 BookOrbit 的行为）
 *   · 组件重渲染时顺序不变（避免参考页那种每次渲染图形乱跳的问题）
 */
const SHUFFLED: Book[] = (() => {
  const list = [...library.books]
  for (let i = list.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[list[i], list[j]] = [list[j], list[i]]
  }
  return list
})()

/** 每行最多展示 20 个封面（与 BookOrbit 一致） */
const MAX_COVERS = 20

const books = computed<Book[]>(() => {
  switch (props.shelf.type) {
    case 'continue':
      return library.continueReading
    case 'discover':
      return SHUFFLED
    default:
      return library.books
  }
})

const visibleBooks = computed(() => books.value.slice(0, MAX_COVERS))
</script>

<template>
  <section class="min-w-0">
    <div class="mb-2.5 flex items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">{{ shelf.title }}</h2>
      <span class="text-[11px] text-muted-foreground tabular-nums">{{ visibleBooks.length }} 本</span>
      <button
        type="button"
        class="ml-auto flex cursor-pointer items-center gap-1 text-[11.5px] text-primary transition-opacity hover:opacity-80"
        @click="library.openShelf(shelf.title); router.push('/shelf')"
      >
        查看全部
        <Icon name="arrowRight" class="h-3 w-3" />
      </button>
    </div>

    <!-- 横向滚动：隐藏滚动条但保留滚轮与拖拽（.no-scrollbar 由 main.css 提供） -->
    <div class="no-scrollbar -mx-1 flex gap-3 overflow-x-auto px-1 pb-1">
      <button
        v-for="b in visibleBooks"
        :key="b.id"
        type="button"
        class="group w-[104px] shrink-0 cursor-pointer text-left"
        @click="router.push(`/book/${b.id}`)"
      >
        <BookCover :book="b" />
        <div class="mt-1.5 truncate text-[12px] font-medium text-foreground">{{ b.title }}</div>
        <div class="truncate text-[11px] text-muted-foreground">{{ b.author }}</div>
      </button>

      <div v-if="!visibleBooks.length" class="py-6 text-[12px] text-muted-foreground">
        这一行暂时没有书
      </div>
    </div>
  </section>
</template>
