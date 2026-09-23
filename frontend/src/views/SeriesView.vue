<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type SeriesItem } from '@/lib/api'

/**
 * 系列总览：按 EPUB 元数据里的 series 聚合。
 * 数据来自 /api/series（见 library.series_list）。
 */
const router = useRouter()
const items = ref<SeriesItem[]>([])
const loading = ref(true)
/** 加载失败信息：失败不能退化成「还没有系列」。 */
const error = ref('')

const FALLBACK = { title: '—', c1: 'oklch(0.62 0.16 260)', c2: 'oklch(0.48 0.13 300)' }

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    items.value = (await api.series()).items
  } catch (e) {
    items.value = []
    error.value = e instanceof Error ? e.message : '加载失败'
  }
  loading.value = false
}

onMounted(load)

function open(name: string): void {
  router.push(`/series/${encodeURIComponent(name)}`)
}
</script>

<template>
  <div>
    <PageHead title="系列" :desc="`共 ${items.length} 个系列`" />

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <!-- 加载失败：可重试的错误态（不与「还没有系列」空态混淆） -->
    <Card v-else-if="error" padding="sm">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        <span>系列加载失败：{{ error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="load">重试</Button>
      </div>
    </Card>

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
