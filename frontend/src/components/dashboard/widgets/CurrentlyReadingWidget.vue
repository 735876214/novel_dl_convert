<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useLibraryStore } from '@/stores/library'

/** 正在阅读：已打开但未读完的书，按最近阅读时间排序。 */
const library = useLibraryStore()
const router = useRouter()

onMounted(() => library.loadBooks())

const items = computed(() => library.continueReading.slice(0, 3))
</script>

<template>
  <div class="flex h-full flex-col rounded-lg border border-border bg-card p-4 shadow-sm">
    <div class="flex items-baseline justify-between">
      <h3 class="text-[13px] font-semibold text-foreground">正在阅读</h3>
      <span class="text-[11px] text-muted-foreground tabular-nums">
        {{ library.continueReading.length }} 本
      </span>
    </div>

    <p v-if="!items.length" class="mt-2 text-[11.5px] text-muted-foreground">
      还没有在读的书，打开一本开始阅读吧。
    </p>

    <button
      v-for="b in items"
      :key="b.id"
      type="button"
      class="mt-2 flex w-full cursor-pointer items-center gap-2.5 text-left"
      @click="router.push(`/read/${b.id}`)"
    >
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
  </div>
</template>
