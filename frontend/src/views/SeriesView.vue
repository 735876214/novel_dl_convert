<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type SeriesItem } from '@/lib/api'

/**
 * 系列总览：按 EPUB 元数据里的 series 聚合。
 * 数据来自 /api/series（见 library.series_list）。
 */
const router = useRouter()
const items = ref<SeriesItem[]>([])
const loading = ref(true)

const FALLBACK = { title: '—', c1: 'oklch(0.62 0.16 260)', c2: 'oklch(0.48 0.13 300)' }

onMounted(async () => {
  try {
    items.value = (await api.series()).items
  } catch {
    /* 忽略：保持空列表并显示空状态 */
  }
  loading.value = false
})

function open(name: string): void {
  router.push(`/series/${encodeURIComponent(name)}`)
}
</script>

<template>
  <div>
    <PageHead title="系列" :desc="`共 ${items.length} 个系列`" />

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <div
      v-else-if="items.length"
      class="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
    >
      <button
        v-for="s in items"
        :key="s.name"
        type="button"
        class="group cursor-pointer text-left"
        @click="open(s.name)"
      >
        <div class="relative">
          <BookCover :book="s.covers[0] ?? FALLBACK" :show-title="false" />
          <span
            class="absolute right-1.5 bottom-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white tabular-nums"
          >
            {{ s.count }} 册
          </span>
        </div>
        <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ s.name }}</div>
        <div class="truncate text-[11.5px] text-muted-foreground">
          {{ s.authors.join('、') || '未知作者' }}
        </div>
        <!-- 简介摘要：有值才渲染（第 12 期 C3）；没抓到的系列不占位、不留空行 -->
        <div
          v-if="(s.description ?? '').trim()"
          class="mt-0.5 line-clamp-2 text-[10.5px] leading-snug text-muted-foreground/80"
        >
          {{ s.description }}
        </div>
      </button>
    </div>

    <EmptyState
      v-else
      icon="layers"
      title="还没有系列"
      desc="EPUB 元数据里标注了「系列」的书会自动归到这里。"
    />
  </div>
</template>
