<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import Segment from '@/components/ui/Segment.vue'
import { api, type AuthorItem } from '@/lib/api'

/** 作者总览：按 EPUB 元数据里的 author 聚合（见 library.authors_list）。
 *  前端排序（书量 / 姓名）与「2+ 本」筛选；「本周新增」需后端给作者级 added 字段，留待轻后端批次。 */
const router = useRouter()
const items = ref<AuthorItem[]>([])
const loading = ref(true)

const sortMode = ref<'count' | 'name'>('count')
const onlyMulti = ref(false)

const FALLBACK = { title: '—', c1: 'oklch(0.62 0.16 200)', c2: 'oklch(0.48 0.13 240)' }

const sortOptions = [
  { value: 'count', label: '按书量' },
  { value: 'name', label: '按姓名' },
]

const display = computed(() => {
  let list = items.value
  if (onlyMulti.value) list = list.filter((a) => a.count >= 2)
  return [...list].sort((a, b) =>
    sortMode.value === 'name' ? a.name.localeCompare(b.name, 'zh') : b.count - a.count,
  )
})

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

    <template v-else>
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <Segment :options="sortOptions" :model-value="sortMode" @update:model-value="(v: string) => (sortMode = v as 'count' | 'name')" />
        <button
          type="button"
          class="cursor-pointer rounded-full border px-3 py-1 text-[12px] font-medium transition-colors"
          :class="onlyMulti ? 'border-primary/40 bg-[var(--shell-accent-tint)] text-primary' : 'border-border bg-muted text-muted-foreground hover:text-foreground'"
          @click="onlyMulti = !onlyMulti"
        >
          2+ 本
        </button>
        <span class="ml-auto text-[11.5px] text-muted-foreground">显示 {{ display.length }} 位</span>
      </div>

      <div
        v-if="display.length"
        class="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
      >
        <button
          v-for="a in display"
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

      <EmptyState
        v-else
        icon="users"
        :title="onlyMulti ? '没有 2 本以上的作者' : '还没有作者'"
        :desc="onlyMulti ? '关掉「2+ 本」筛选看看全部作者。' : 'EPUB 元数据里带「作者」的书会自动归到这里。'"
      />
    </template>
  </div>
</template>
