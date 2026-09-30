<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { highlightHex, highlightStyleLabel } from '@/data/annotationColors'
import { api, type AllAnnotation } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'

/**
 * 每日划线：按当天日期确定性地抽一条批注（同一天刷新不变）。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 */
defineProps<{
  /** 宽度档由部件行下发（对齐上游契约） */
  size?: WidgetSize
}>()

const router = useRouter()
const library = useLibraryStore()
const items = ref<AllAnnotation[]>([])
/** 取批注失败：与「还没有批注」是两回事，别把错误混成空态。 */
const failed = ref(false)
/** 拉取中（此前加载期间会误显示「还没有批注」） */
const pending = ref(true)

async function load(): Promise<void> {
  pending.value = true
  try {
    items.value = (await api.allAnnotations()).items
    failed.value = false
  } catch {
    failed.value = true
  } finally {
    pending.value = false
  }
}

onMounted(load)

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

/** 数据态：加载中 / 失败（可重试）/ 空 —— 拉取期间不再误显示「还没有批注」 */
const state = useWidgetState(() => ({
  loading: pending.value,
  error: failed.value,
  empty: !pending.value && !failed.value && !today.value,
}))
</script>

<template>
  <div class="flex h-full flex-col p-3">
    <h3 class="text-[13px] font-semibold text-foreground">每日划线</h3>

    <template v-if="state === 'loading'">
      <div class="mt-3 flex-1 space-y-2">
        <div class="h-2.5 w-full animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-4/5 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-2/3 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-1/3 animate-pulse rounded bg-muted" />
      </div>
    </template>

    <div v-else-if="failed" class="flex flex-1 flex-col justify-center gap-2">
      <p class="text-[11.5px] text-muted-foreground">暂时无法加载划线，请稍后重试。</p>
      <button type="button" class="w-fit cursor-pointer text-[11px] text-primary hover:underline" @click="load">
        重试
      </button>
    </div>

    <p v-else-if="!today" class="mt-2 text-[11.5px] text-muted-foreground">{{ emptyText }}</p>

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
