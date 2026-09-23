<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { highlightHex, highlightStyleLabel } from '@/data/annotationColors'
import { api, type AllAnnotation } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'

/** 每日划线：按当天日期确定性地抽一条批注（同一天刷新不变）。 */
const router = useRouter()
const library = useLibraryStore()
const items = ref<AllAnnotation[]>([])

onMounted(async () => {
  try {
    items.value = (await api.allAnnotations()).items
  } catch {
    /* ignore */
  }
})

// 高亮取色统一来自 data/annotationColors.ts（唯一一份）—— 这里此前自己写了一份
// 四色表，扩容时会把新增颜色静默渲染成黄色。

const today = computed<AllAnnotation | null>(() => {
  if (!items.value.length) return null
  const d = new Date()
  const seed = d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate()
  return items.value[seed % items.value.length] ?? null
})

/**
 * 空态分两种情况说（第 38 期）。
 *
 * 「在阅读器里选中文字即可添加」在**一个书库都没有**时做不到 —— 没有书就没有
 * 阅读器可进。0 库时改说「还没有书库」，不指一条走不通的路。
 */
const emptyText = computed(() =>
  library.hasNoLibraries ? '还没有书库。' : '还没有批注。在阅读器里选中文字即可添加。',
)
</script>

<template>
  <div class="flex h-full flex-col rounded-lg border border-border bg-card p-4 shadow-sm">
    <h3 class="text-[13px] font-semibold text-foreground">每日划线</h3>

    <p v-if="!today" class="mt-2 text-[11.5px] text-muted-foreground">{{ emptyText }}</p>

    <template v-else>
      <div class="mt-2.5 flex-1 border-l-2 pl-2.5" :style="{ borderColor: highlightHex(today.color) }">
        <p class="text-[12.5px] leading-relaxed text-foreground">「{{ today.quote }}」</p>
        <p v-if="today.note" class="mt-1 text-[11.5px] text-muted-foreground">{{ today.note }}</p>
        <p class="mt-1 text-[10.5px] text-muted-foreground">{{ highlightStyleLabel(today.style) }}</p>
      </div>
      <button
        type="button"
        class="mt-2 cursor-pointer text-left text-[11px] text-primary transition-opacity hover:opacity-80"
        @click="router.push(`/read/${today.book_id}?chapter=${today.chapter}`)"
      >
        — {{ today.book_title }}
      </button>
    </template>
  </div>
</template>
