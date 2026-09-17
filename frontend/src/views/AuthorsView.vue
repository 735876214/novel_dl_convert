<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type AuthorItem } from '@/lib/api'

/** 作者总览：按 EPUB 元数据里的 author 聚合（见 library.authors_list）。 */
const router = useRouter()
const items = ref<AuthorItem[]>([])
const loading = ref(true)

const FALLBACK = { title: '—', c1: 'oklch(0.62 0.16 200)', c2: 'oklch(0.48 0.13 240)' }

onMounted(async () => {
  try {
    items.value = (await api.authors()).items
  } catch {
    /* 保持空列表 */
  }
  loading.value = false
})

function open(name: string): void {
  router.push(`/authors/${encodeURIComponent(name)}`)
}
</script>

<template>
  <div>
    <PageHead title="作者" :desc="`共 ${items.length} 位作者`" />

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <div
      v-else-if="items.length"
      class="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
    >
      <button
        v-for="a in items"
        :key="a.name"
        type="button"
        class="group cursor-pointer text-left"
        @click="open(a.name)"
      >
        <div class="relative">
          <BookCover :book="a.covers[0] ?? FALLBACK" :show-title="false" />
          <span
            class="absolute right-1.5 bottom-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white tabular-nums"
          >
            {{ a.count }} 本
          </span>
        </div>
        <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ a.name }}</div>
        <div class="truncate text-[11.5px] text-muted-foreground">
          {{ a.series.join('、') || '—' }}
        </div>
      </button>
    </div>

    <EmptyState v-else icon="users" title="还没有作者" desc="EPUB 元数据里带「作者」的书会自动归到这里。" />
  </div>
</template>
