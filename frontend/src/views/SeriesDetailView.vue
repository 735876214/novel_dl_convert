<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import {
  formatLabel,
  pubLabel,
  seriesIndexLabel,
  sortBySeriesIndex,
  tagsLabel,
} from '@/lib/bookInfo'
import { api, type BookCard } from '@/lib/api'

/**
 * 系列详情：该系列下的全部书目。
 *
 * 两处刻意的行为：
 *   · **按系列序号排序** —— 系列页的要点就是阅读顺序，按扫描顺序列出来等于没排。
 *     后端 `series_books()` 保持扫描顺序（其它调用方依赖），排序在这里做。
 *   · 展示 `#序号` 与格式徽章 —— 序号是这一页最该突出的字段（见 §2 书卡信息补全）。
 *     缺序号的书排在最后，并明确标「序号未知」，不假装它是第一册。
 */
const route = useRoute()
const router = useRouter()
const name = computed(() => String(route.params.name))
const books = ref<BookCard[]>([])
const loading = ref(true)

/** 序号是否齐全：只要有一本缺，就在页头提示，避免用户以为排序错了 */
const hasMissingIndex = computed(() => books.value.some((b) => !b.series_index))

async function load(): Promise<void> {
  loading.value = true
  try {
    books.value = sortBySeriesIndex((await api.seriesDetail(name.value)).books)
  } catch {
    books.value = []
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

    <div
      v-else-if="books.length"
      class="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8"
    >
      <button
        v-for="b in books"
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

    <EmptyState v-else icon="layers" title="这个系列暂时没有书" desc="书目可能已被移出导出目录。" />
  </div>
</template>
