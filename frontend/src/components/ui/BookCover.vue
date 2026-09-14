<script setup lang="ts">
import type { Book } from '@/data/books'

/**
 * 书封。渐变取自 book 数据的 c1/c2（oklch，色相已对齐 BookOrbit 调色板）。
 * 阴影与「书脊」效果复用 BookOrbit 的 cover-effects.css（.book-cover-surface / .book-cover-spine-layer），
 * 而不是自己重写一套 —— 那正是照搬策略的意义。
 */
withDefaults(
  defineProps<{
    book: Pick<Book, 'title' | 'c1' | 'c2'>
    /** 是否显示书名（书架大封面显示，网格小封面可不显示） */
    showTitle?: boolean
    /** 悬停时抬起 */
    interactive?: boolean
  }>(),
  { showTitle: true, interactive: true },
)
</script>

<template>
  <div
    class="book-cover-surface relative aspect-3/4 w-full overflow-hidden rounded-md transition-transform duration-200 ease-out"
    :class="interactive ? 'group-hover:-translate-y-0.5' : ''"
    data-cover-spine="subtle"
    :style="{ backgroundImage: `linear-gradient(160deg, ${book.c1}, ${book.c2})` }"
  >
    <div class="book-cover-spine-layer absolute inset-0" data-cover-spine="subtle" />

    <span
      v-if="showTitle"
      class="absolute inset-0 z-2 flex items-center p-2 text-center font-serif text-[13px] leading-snug font-semibold text-white/92"
      style="text-shadow: 0 1px 2px oklch(0 0 0 / 0.35)"
    >
      {{ book.title }}
    </span>
  </div>
</template>
