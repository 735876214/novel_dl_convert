<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import type { BookCard } from '@/lib/api'
import { useCollectionsStore } from '@/stores/collections'
import { useLibraryStore } from '@/stores/library'

/**
 * 实体总览（第 34 期）：按元数据维度浏览**本地**书库。
 *
 * 与「探索发现」(`/explore`) 是两件事：那个是**外部书源检索**（`POST /api/search`），
 * 这个只读本地书目、不发任何外网请求。
 *
 * 数据全部来自 `library.scopedBooks`（= `/api/books` 的结果按当前书库过滤）——
 * **刻意不新增后端接口**：这些维度本来就是同一份书目的不同投影，
 * 另起一套聚合只会造出「这里数出来的跟书架不一样」的第二份真值源。
 * 「收藏」维度同样如此：成员关系由 `/api/books` 的 `collection_ids` 批量附带。
 */
const router = useRouter()
const library = useLibraryStore()
const collections = useCollectionsStore()

type DimKey = 'author' | 'series' | 'genre' | 'publisher' | 'language' | 'collection'

interface Dim {
  key: DimKey
  label: string
  icon: string
  /** 一本书 → 它在该维度上的条目名（空数组 = 这本书没这个字段，不进任何条目） */
  valuesOf: (b: BookCard) => string[]
  /** 空态说明：讲清「为什么可能没有」，不只说「暂无数据」 */
  emptyHint: string
}

function single(v?: string): string[] {
  const s = (v || '').trim()
  return s ? [s] : []
}

/**
 * 六个维度。⚠️ 上游 catalog 把「题材(genre)」与「标签(tag)」分成两个字段，
 * 本项目只有 `tags`（OPF 的 `dc:subject`，界面既有的「题材」筛选用的就是它）
 * —— 拆成两个维度就是把同一份数据换个名字列两遍，属假交互，故**只做一个**。
 * 演播者维度本项目没有实体（第 34 期明确不做），不在列。
 */
const DIMS: Dim[] = [
  { key: 'author', label: '作者', icon: 'users', valuesOf: (b) => single(b.author),
    emptyHint: '书的 OPF 里没有 dc:creator 时就归不到任何作者。' },
  { key: 'series', label: '系列', icon: 'layers', valuesOf: (b) => single(b.series),
    emptyHint: 'EPUB 元数据里标注了「系列」的书才会出现在这里。' },
  { key: 'genre', label: '题材', icon: 'sparkle', valuesOf: (b) => (b.tags || []).map((t) => String(t).trim()).filter(Boolean),
    emptyHint: '题材来自 OPF 的 dc:subject；本项目转换出的 EPUB 默认不带它，刮削抓取后才会有。' },
  { key: 'publisher', label: '出版社', icon: 'library', valuesOf: (b) => single(b.publisher),
    emptyHint: '出版社来自 OPF 的 dc:publisher，多数文件缺这一项，可到书籍详情页手工补。' },
  { key: 'language', label: '语言', icon: 'globe', valuesOf: (b) => single(b.language),
    emptyHint: '语言来自 OPF 的 dc:language。' },
  { key: 'collection', label: '收藏', icon: 'star', valuesOf: (b) => (b.collection_ids ?? []).map(String),
    emptyHint: '还没有收藏夹，或当前书库里没有书被收进收藏夹。' },
]

const dim = ref<DimKey>('author')
const selected = ref('')
const filter = ref('')

const current = computed(() => DIMS.find((d) => d.key === dim.value)!)

/** 当前书库的书目（与书架同一个 scope；「全部书库」时不裁剪） */
const scoped = computed(() => library.scopedBooks)

const collectionNames = computed(
  () => new Map(collections.items.map((c) => [String(c.id), c.name])),
)

interface Entry {
  key: string
  label: string
  count: number
  /** 该条目下第一本书（做瓷片封面用）；取不到时回退到渐变占位 */
  cover?: BookCard
}

/** 没有封面时的渐变占位（与系列页同一份取值，保证观感一致） */
const FALLBACK = { title: '—', c1: 'oklch(0.62 0.16 260)', c2: 'oklch(0.48 0.13 300)' }

/** 本维度的条目 + 数量（按数量降序、同数量按名字） */
function entriesOf(d: Dim): Entry[] {
  const bucket = new Map<string, { count: number; cover?: BookCard }>()
  for (const b of scoped.value) {
    for (const v of d.valuesOf(b)) {
      const hit = bucket.get(v)
      if (hit) hit.count += 1
      else bucket.set(v, { count: 1, cover: b })
    }
  }
  return [...bucket.entries()]
    .map(([key, { count, cover }]) => ({
      key,
      count,
      cover,
      label: d.key === 'collection' ? (collectionNames.value.get(key) ?? `收藏夹 #${key}`) : key,
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

const entries = computed(() => {
  const all = entriesOf(current.value)
  const q = filter.value.trim().toLowerCase()
  return q ? all.filter((e) => e.label.toLowerCase().includes(q)) : all
})

/** 维度栏上的角标：该维度有多少个条目（不是多少本书） */
const dimCounts = computed(() =>
  Object.fromEntries(DIMS.map((d) => [d.key, entriesOf(d).length])) as Record<DimKey, number>,
)

/** 当前维度里没有这个字段的书 —— 如实说明，免得用户以为「数量加起来不对」 */
const unlabeled = computed(() => scoped.value.filter((b) => current.value.valuesOf(b).length === 0).length)

const selectedBooks = computed(() =>
  selected.value
    ? scoped.value.filter((b) => current.value.valuesOf(b).includes(selected.value))
    : [],
)

const selectedLabel = computed(
  () => entriesOf(current.value).find((e) => e.key === selected.value)?.label ?? selected.value,
)

watch(dim, () => {
  selected.value = ''
  filter.value = ''
})

onMounted(() => {
  // 深链直达本页时商店可能还没取过书目（侧栏通常会先取一遍，这里只兜底）
  if (!library.loaded) void library.loadBooks()
  void collections.load()
})

function open(entry: Entry): void {
  selected.value = entry.key
}
</script>

<template>
  <div>
    <PageHead
      title="实体总览"
      :desc="`在「${library.currentLibraryName}」里按维度浏览 · 共 ${scoped.length} 本`"
    />

    <div class="flex flex-col gap-4 md:flex-row">
      <!-- 维度栏：窄屏折叠成下拉，避免左栏把结果区挤没 -->
      <aside class="md:w-44 md:shrink-0">
        <label class="mb-1.5 block text-[11px] text-muted-foreground md:hidden">维度</label>
        <select
          v-model="dim"
          class="mb-3 h-8 w-full rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring md:hidden"
        >
          <option v-for="d in DIMS" :key="d.key" :value="d.key">
            {{ d.label }}（{{ dimCounts[d.key] }}）
          </option>
        </select>

        <nav class="hidden md:block">
          <div
            v-for="d in DIMS"
            :key="d.key"
            class="mb-0.5 flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px] transition-colors"
            :class="dim === d.key
              ? 'bg-muted font-semibold text-foreground'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
            @click="dim = d.key"
          >
            <Icon :name="d.icon" class="h-3.5 w-3.5" />
            <span class="truncate">{{ d.label }}</span>
            <span class="ml-auto shrink-0 text-[11px] tabular-nums opacity-70">{{ dimCounts[d.key] }}</span>
          </div>
        </nav>
      </aside>

      <div class="min-w-0 flex-1">
        <!-- 已选条目：返回 + 该条目下的书 -->
        <template v-if="selected">
          <div class="mb-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              class="flex cursor-pointer items-center gap-1 text-[12px] text-muted-foreground transition-colors hover:text-primary"
              @click="selected = ''"
            >
              <Icon name="arrowLeft" class="h-3.5 w-3.5" />{{ current.label }}
            </button>
            <span class="text-[13px] font-medium text-foreground">{{ selectedLabel }}</span>
            <span class="text-[11.5px] text-muted-foreground tabular-nums">{{ selectedBooks.length }} 本</span>
          </div>

          <div class="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8">
            <button
              v-for="b in selectedBooks"
              :key="b.id"
              type="button"
              class="group w-full cursor-pointer text-left"
              @click="router.push(`/book/${b.id}`)"
            >
              <BookCover :book="b" />
              <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ b.title }}</div>
              <div class="truncate text-[11.5px] text-muted-foreground">{{ b.author || '未知作者' }}</div>
            </button>
          </div>
        </template>

        <!-- 未选条目：本维度的条目瓷片 -->
        <template v-else>
          <div v-if="dimCounts[current.key]" class="mb-3 flex flex-wrap items-center gap-2">
            <div class="relative max-w-[20rem] flex-1">
              <Icon name="search" class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                v-model="filter"
                type="text"
                :placeholder="`筛选${current.label}…`"
                class="h-8 w-full rounded-md border border-border bg-muted pr-2.5 pl-8 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
              >
            </div>
            <span v-if="unlabeled" class="text-[11.5px] text-muted-foreground">
              另有 {{ unlabeled }} 本没有{{ current.label }}信息
            </span>
          </div>

          <div
            v-if="entries.length"
            class="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
          >
            <button
              v-for="e in entries"
              :key="e.key"
              type="button"
              class="group cursor-pointer text-left"
              @click="open(e)"
            >
              <div class="relative">
                <BookCover :book="e.cover ?? FALLBACK" :show-title="false" />
                <span class="absolute right-1.5 bottom-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white tabular-nums">
                  {{ e.count }} 本
                </span>
              </div>
              <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ e.label }}</div>
            </button>
          </div>

          <EmptyState
            v-else
            :icon="filter ? 'search' : current.icon"
            :title="filter ? '没有匹配的条目' : `${current.label}维度暂无数据`"
            :desc="filter ? '换个关键词再试。' : current.emptyHint"
          />
        </template>
      </div>
    </div>
  </div>
</template>
