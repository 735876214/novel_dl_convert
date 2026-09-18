<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import Segment from '@/components/ui/Segment.vue'
import { api, type BookCard } from '@/lib/api'

/** 作者详情：该作者名下的全部书目。前端排序（书名 / 系列 / 最近添加）+ 打开最近添加。 */
const route = useRoute()
const router = useRouter()
const name = computed(() => String(route.params.name))
const books = ref<BookCard[]>([])
const loading = ref(true)

const sortMode = ref<'title' | 'series' | 'added'>('added')

const sortOptions = [
  { value: 'title', label: '书名' },
  { value: 'series', label: '系列' },
  { value: 'added', label: '最近添加' },
]

const sorted = computed(() => {
  const list = [...books.value]
  list.sort((a, b) => {
    if (sortMode.value === 'title') return a.title.localeCompare(b.title, 'zh')
    if (sortMode.value === 'series')
      return (a.series || '').localeCompare(b.series || '', 'zh') || a.title.localeCompare(b.title, 'zh')
    return b.mtime - a.mtime
  })
  return list
})

const latest = computed(() =>
  books.value.length ? books.value.reduce((m, b) => (b.mtime > m.mtime ? b : m)) : null,
)

async function load(): Promise<void> {
  loading.value = true
  try {
    books.value = (await api.authorDetail(name.value)).books
  } catch {
    books.value = []
  }
  loading.value = false
}

function openLatest(): void {
  if (latest.value) router.push(`/book/${latest.value.id}`)
}

onMounted(load)
watch(name, load)
</script>

<template>
  <div>
    <button
      type="button"
      class="mb-4 flex cursor-pointer items-center gap-1 text-[12px] text-muted-foreground transition-colors hover:text-primary"
      @click="router.push('/authors')"
    >
      <Icon name="arrowLeft" class="h-3.5 w-3.5" />全部作者
    </button>

    <PageHead :title="name" :desc="`共 ${books.length} 本`" />

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else>
      <div v-if="books.length" class="mb-4 flex items-center gap-2">
        <Segment
          :options="sortOptions"
          :model-value="sortMode"
          @update:model-value="(v: string) => (sortMode = v as 'title' | 'series' | 'added')"
        />
        <Button size="sm" class="ml-auto" :disabled="!latest" @click="openLatest">
          <Icon name="book" class="mr-1.5 h-3.5 w-3.5" />打开最近添加
        </Button>
      </div>

      <div
        v-if="books.length"
        class="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8"
      >
        <button
          v-for="b in sorted"
          :key="b.id"
          type="button"
          class="group cursor-pointer text-left"
          @click="router.push(`/book/${b.id}`)"
        >
          <BookCover :book="b" />
          <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ b.title }}</div>
          <div class="truncate text-[11.5px] text-muted-foreground">{{ b.series || '独立作品' }}</div>
        </button>
      </div>

      <EmptyState v-else icon="users" title="这位作者名下的书被移除了" desc="书目可能已不在导出目录。" />
    </template>
  </div>
</template>
