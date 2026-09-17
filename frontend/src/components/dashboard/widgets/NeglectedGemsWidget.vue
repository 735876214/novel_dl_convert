<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useLibraryStore } from '@/stores/library'

/** 被遗忘的佳作：已开始却最久未触碰的一本书。 */
const library = useLibraryStore()
const router = useRouter()

onMounted(() => library.loadBooks())

const gem = computed(() => {
  const list = library.books.filter(
    (b) => (b.percent ?? 0) > 0 && (b.percent ?? 0) < 99.5 && (b.updated_at ?? 0) > 0,
  )
  if (!list.length) return null
  return [...list].sort((a, b) => (a.updated_at ?? 0) - (b.updated_at ?? 0))[0]
})

const daysAgo = computed(() => {
  const t = gem.value?.updated_at ?? 0
  if (!t) return 0
  return Math.max(0, Math.floor((Date.now() / 1000 - t) / 86400))
})
</script>

<template>
  <div class="flex h-full flex-col justify-between rounded-lg border border-border bg-card p-4 shadow-sm">
    <h3 class="text-[13px] font-semibold text-foreground">被遗忘的佳作</h3>

    <p v-if="!gem" class="mt-2 text-[11.5px] text-muted-foreground">暂时没有搁置的书。</p>

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
