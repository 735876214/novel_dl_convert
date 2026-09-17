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
</script>

<template>
  <div class="flex h-full flex-col justify-between rounded-lg border border-border bg-card p-4 shadow-sm">
    <h3 class="text-[13px] font-semibold text-foreground">等待最久</h3>

    <p v-if="!book" class="mt-2 text-[11.5px] text-muted-foreground">书库里的书都读过啦。</p>

    <button v-else type="button" class="mt-2 cursor-pointer text-left" @click="router.push(`/book/${book.id}`)">
      <div class="truncate text-[12.5px] font-medium text-foreground">{{ book.title }}</div>
      <div class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ book.author }}</div>
    </button>

    <p v-if="book" class="mt-2 text-[10.5px] text-muted-foreground tabular-nums">已等待 {{ days }} 天未读</p>
  </div>
</template>
