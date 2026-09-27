<script setup lang="ts">
import { computed } from 'vue'

import BookCover from '@/components/ui/BookCover.vue'
import type { BookCard, SimilarBook } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'

/**
 * 相似书横滚条（第 63 期从 `BookDetailView` 抽出并重做）。
 *
 * 改了两处：
 * - **带封面**。后端从第 35 期起就返回 `has_cover`，前端一直只用了标题与 `reasons`。
 * - **改横滚**。此前是竖排列表塞在概览右栏的一张卡里，每行只有两行字；
 *   横滚后一屏能看到书名与封面，与书架的 `DashboardShelfRow` 同一套观感。
 *
 * 无信号时后端给空数组（至少要有一条实质重合才会返回），父级据此整块不渲染 ——
 * 这里不做「暂无推荐」空态。
 */
const props = defineProps<{
  items: SimilarBook[]
  /** 已展开到上限 */
  expanded: boolean
  /** 预览条数：**只有满这个数才可能有更多**，所以只在满的时候给「查看全部」 */
  preview: number
  /** 接口上限（与后端 `recommend.MAX_LIMIT` 对齐） */
  max: number
}>()

const emit = defineEmits<{ expand: []; open: [string] }>()

const library = useLibraryStore()

const byId = computed(() => new Map(library.books.map((b) => [b.id, b])))

/**
 * 给 `BookCover` 造一个书对象。优先用书架列表里的真身（有 c1/c2 占位渐变）；
 * 跨库推荐时本库列表里没有它，回落到 token 组成的渐变 —— 与「真实封面加载失败」
 * 是同一类兜底：**纯装饰，不是数据**。
 */
function coverOf(s: SimilarBook): BookCard {
  const known = byId.value.get(s.id)
  if (known) return known
  return {
    id: s.id,
    title: s.title,
    has_cover: s.has_cover,
    c1: 'var(--muted)',
    c2: 'var(--card)',
  } as BookCard
}
</script>

<template>
  <div>
    <!-- 一屏放得下就不滚（`overflow-x-auto` 在内容不足时本来就是空操作，这里只是省掉多余的内边距） -->
    <div class="no-scrollbar -mx-1 flex gap-3 overflow-x-auto px-1 pb-1">
      <button
        v-for="s in props.items"
        :key="s.id"
        type="button"
        :title="s.reasons.join(' · ')"
        class="w-[104px] shrink-0 cursor-pointer text-left"
        @click="emit('open', s.id)"
      >
        <BookCover :book="coverOf(s)" :interactive="true" :show-title="true" />
        <span class="mt-1.5 block truncate text-[12px] text-foreground">{{ s.title }}</span>
        <span class="block truncate text-[10.5px] text-muted-foreground">{{ s.reasons.join(' · ') }}</span>
      </button>
    </div>

    <button
      v-if="!expanded && items.length >= preview"
      type="button"
      class="mt-2 cursor-pointer text-[11.5px] text-primary transition-opacity hover:opacity-80"
      @click="emit('expand')"
    >
      查看全部（最多 {{ max }} 本）
    </button>
  </div>
</template>
