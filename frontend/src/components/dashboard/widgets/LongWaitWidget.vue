<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useLibraryStore } from '@/stores/library'

/** 等待最久：书库中未读、入库时间最早的一本书。 */
const library = useLibraryStore()
const router = useRouter()

onMounted(() => library.loadBooks())

const book = computed(() => {
  const unread = library.books.filter((b) => !(b.percent ?? 0))
  if (!unread.length) return null
  return [...unread].sort((a, b) => (a.mtime || 0) - (b.mtime || 0))[0]
})

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
</script>

<template>
  <div class="flex h-full flex-col justify-between rounded-lg border border-border bg-card p-4 shadow-sm">
    <h3 class="text-[13px] font-semibold text-foreground">等待最久</h3>

    <p v-if="!book" class="mt-2 text-[11.5px] text-muted-foreground">{{ emptyText }}</p>

    <button v-else type="button" class="mt-2 cursor-pointer text-left" @click="router.push(`/book/${book.id}`)">
      <div class="truncate text-[12.5px] font-medium text-foreground">{{ book.title }}</div>
      <div class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ book.author }}</div>
    </button>

    <p v-if="book" class="mt-2 text-[10.5px] text-muted-foreground tabular-nums">已等待 {{ days }} 天未读</p>
  </div>
</template>
