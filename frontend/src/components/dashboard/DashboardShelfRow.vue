<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Icon from '@/components/ui/Icon.vue'
import type { BookCard } from '@/lib/api'
import type { ShelfDef } from '@/data/dashboard'
import { useLibraryStore } from '@/stores/library'

const props = defineProps<{ shelf: ShelfDef }>()

const library = useLibraryStore()
const router = useRouter()

onMounted(() => library.loadBooks())

/**
 * 「随机发现」改为确定性排序：按 book id 稳定升序，刷新页面顺序固定、无运行时随机。
 * 用 computed 依赖 library.books，仅在数据变化时重算。
 */
const discoverBooks = computed<BookCard[]>(() =>
  [...library.books].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
)

/** 每行最多展示 20 个封面（与 BookOrbit 一致） */
const MAX_COVERS = 20

const books = computed<BookCard[]>(() => {
  switch (props.shelf.type) {
    case 'continue':
      return library.continueReading
    case 'discover':
      return discoverBooks.value
    case 'recent':
      return [...library.books].sort((a, b) => (b.mtime || 0) - (a.mtime || 0))
    case 'scope':
      return props.shelf.scope ? library.smartBooks(props.shelf.scope) : library.books
    default:
      return library.books
  }
})

const visibleBooks = computed(() => books.value.slice(0, MAX_COVERS))

/** 「查看全部」：继续阅读行跳到「在读」智能书架，其余按标题进书库页 */
function openAll(): void {
  if (props.shelf.type === 'continue') library.openSmart('在读', 'reading')
  else library.openShelf(props.shelf.title)
  router.push('/shelf')
}
</script>

<template>
  <section class="min-w-0">
    <div class="mb-2.5 flex items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">{{ shelf.title }}</h2>
      <span class="text-[11px] text-muted-foreground tabular-nums">{{ visibleBooks.length }} 本</span>
      <button
        type="button"
        class="ml-auto flex cursor-pointer items-center gap-1 text-[11.5px] text-primary transition-opacity hover:opacity-80"
        @click="openAll"
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
