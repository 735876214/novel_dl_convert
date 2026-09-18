<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SeriesMetaPanel from '@/components/book/SeriesMetaPanel.vue'
import SeriesRenumberDialog from '@/components/book/SeriesRenumberDialog.vue'
import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import Segment from '@/components/ui/Segment.vue'
import {
  formatLabel,
  pubLabel,
  seriesIndexLabel,
  sortBySeriesIndex,
  tagsLabel,
} from '@/lib/bookInfo'
import { api, type BookCard, type SeriesGroup, type SeriesMeta } from '@/lib/api'

/**
 * 系列详情：该系列下的全部书目。
 *
 * 两处刻意的行为：
 *   · **按系列序号排序** —— 系列页的要点就是阅读顺序，按扫描顺序列出来等于没排。
 *     后端 `series_books()` 保持扫描顺序（其它调用方依赖），排序在这里做。
 *   · 展示 `#序号` 与格式徽章 —— 序号是这一页最该突出的字段（见 §2 书卡信息补全）。
 *     缺序号的书排在最后，并明确标「序号未知」，不假装它是第一册。
 *
 * 第 6 期补充（A4/A5）：首册标记（FIRST IN SERIES）+ 顺序/倒序切换。
 *
 * 第 12 期 C3：系列简介与系列级字段（出版社 / 首发年 / 题材 / 册数）已接入，
 * 由 `SeriesMetaPanel` 承载（简介可编辑、可「恢复在线」、可抓取）；
 * 重排册号在 `SeriesRenumberDialog` 里先预览再应用。
 * 这些数据**只存服务端数据库、不写回 EPUB** —— 详见后端 `core/series_meta.py`。
 */
const route = useRoute()
const router = useRouter()
const name = computed(() => String(route.params.name))
const books = ref<BookCard[]>([])
const groups = ref<SeriesGroup[]>([])
const loading = ref(true)
/** 系列级元数据（第 12 期 C3）：简介 / 出版社 / 首发年 / 题材 / 册数 */
const meta = ref<SeriesMeta | null>(null)
const renumberOpen = ref(false)

const dir = ref<'asc' | 'desc'>('asc')
const dirOptions = [
  { value: 'asc', label: '顺序' },
  { value: 'desc', label: '倒序' },
]

/** 序号是否齐全：只要有一本缺，就在页头提示，避免用户以为排序错了 */
const hasMissingIndex = computed(() => books.value.some((b) => !b.series_index))

/** 升序排列后的首册（最小 series_index 的那本；缺序号的已在末尾） */
const firstId = computed(() => {
  const first = sortBySeriesIndex(books.value).find((b) => b.series_index)
  return first ? first.id : null
})

const sorted = computed(() => {
  const arr = sortBySeriesIndex(books.value)
  return dir.value === 'desc' ? [...arr].reverse() : arr
})

/**
 * 按**媒体**分段渲染（第 10 期 C2）。
 *
 * 只有多于一组时才显示组标题 —— 单媒体的系列本来就好读，多一行标题只是噪音。
 * 组内沿用同一个排序/倒序切换：序号是**每种媒体各自**的顺序，跨媒体比较没有意义。
 */
const sections = computed(() => {
  const order = (arr: BookCard[]) => {
    const a = sortBySeriesIndex(arr)
    return dir.value === 'desc' ? [...a].reverse() : a
  }
  if (!books.value.length) return []
  if (groups.value.length <= 1) return [{ label: '', books: sorted.value }]
  return groups.value.map((g) => ({ label: `${g.label} · ${g.count} 册`, books: order(g.books) }))
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const res = await api.seriesDetail(name.value)
    books.value = res.books
    groups.value = res.groups ?? []
    meta.value = res.meta ?? null
  } catch {
    books.value = []
    groups.value = []
    meta.value = null
  }
  loading.value = false
}

onMounted(load)
watch(name, load)
</script>

<template>
  <div>
    <button
      type="button"
      class="mb-4 flex cursor-pointer items-center gap-1 text-[12px] text-muted-foreground transition-colors hover:text-primary"
      @click="router.push('/series')"
    >
      <Icon name="arrowLeft" class="h-3.5 w-3.5" />全部系列
    </button>

    <PageHead :title="name" :desc="`共 ${books.length} 册 · 按系列序号排序`" />
    <p v-if="!loading && hasMissingIndex" class="-mt-2 mb-3 text-[11.5px] text-muted-foreground">
      部分书目在 EPUB 元数据里没有系列序号，已排在末尾并标注「序号未知」。
    </p>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else>
      <!-- 系列简介与系列级字段：数据只存服务端，**不写入书本文件** -->
      <SeriesMetaPanel :name="name" :meta="meta" class="mb-4" @changed="load" />

      <div v-if="books.length" class="mb-4 flex flex-wrap items-center gap-2">
        <Segment
          :options="dirOptions"
          :model-value="dir"
          @update:model-value="(v: string) => (dir = v as 'asc' | 'desc')"
        />
        <Button size="sm" variant="ghost" class="ml-auto" @click="renumberOpen = true">
          重排册号
        </Button>
      </div>

      <!-- 按媒体分段（有多组时每组一个标题）；序号是每种媒体各自的顺序，故按组渲染 -->
      <div v-for="sec in sections" :key="sec.label || 'all'" class="mb-5">
        <div v-if="sec.label" class="mb-2 text-[12px] font-medium text-muted-foreground">
          {{ sec.label }}
        </div>
        <div
          class="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8"
        >
        <button
          v-for="b in sec.books"
          :key="b.id"
          type="button"
          class="group cursor-pointer text-left"
          @click="router.push(`/book/${b.id}`)"
        >
          <div class="relative">
            <BookCover :book="b" :show-title="false" />
            <!-- 序号：这一页最该突出的字段，压在封面左上角 -->
            <span
              class="absolute top-1 left-1 rounded px-1.5 py-0.5 text-[10.5px] font-semibold tabular-nums"
              :class="b.series_index ? 'bg-black/60 text-white' : 'bg-black/45 text-white/70'"
            >
              {{ b.series_index ? seriesIndexLabel(b) : '序号未知' }}
            </span>
            <span
              v-if="formatLabel(b)"
              class="absolute top-1 right-1 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[9.5px] text-white"
            >
              {{ formatLabel(b) }}
            </span>
            <!-- 首册标记（FIRST IN SERIES） -->
            <span
              v-if="b.id === firstId"
              class="absolute bottom-1 left-1 rounded bg-primary px-1.5 py-0.5 text-[10.5px] font-semibold text-white"
            >
              首册
            </span>
          </div>

          <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">
            {{ b.title || b.name }}
          </div>
          <div class="truncate text-[11.5px] text-muted-foreground">{{ b.author || '未知作者' }}</div>
          <div v-if="pubLabel(b)" class="truncate text-[10.5px] text-muted-foreground">
            {{ pubLabel(b) }}
          </div>
          <div v-if="tagsLabel(b)" class="truncate text-[10.5px] text-muted-foreground/80">
            {{ tagsLabel(b) }}
          </div>
        </button>
        </div>
      </div>

      <EmptyState v-if="!books.length" icon="layers" title="这个系列暂时没有书"
                  desc="书目可能已被移出导出目录。" />
    </template>

    <!-- 重排册号：只改 OPF 序号、不动文件名（book_id 不变 → 进度/批注不断链） -->
    <SeriesRenumberDialog
      :name="name"
      :open="renumberOpen"
      @close="renumberOpen = false"
      @applied="load"
    />
  </div>
</template>
