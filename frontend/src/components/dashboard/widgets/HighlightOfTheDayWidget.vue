<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, type AllAnnotation } from '@/lib/api'

/** 每日划线：按当天日期确定性地抽一条批注（同一天刷新不变）。 */
const router = useRouter()
const items = ref<AllAnnotation[]>([])

onMounted(async () => {
  try {
    items.value = (await api.allAnnotations()).items
  } catch {
    /* ignore */
  }
})

const COLORS: Record<string, string> = {
  yellow: '#f5d76e',
  green: '#8fd694',
  blue: '#8fc1f0',
  pink: '#f2a6c4',
}

const today = computed<AllAnnotation | null>(() => {
  if (!items.value.length) return null
  const d = new Date()
  const seed = d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate()
  return items.value[seed % items.value.length] ?? null
})
</script>

<template>
  <div class="flex h-full flex-col rounded-lg border border-border bg-card p-4 shadow-sm">
    <h3 class="text-[13px] font-semibold text-foreground">每日划线</h3>

    <p v-if="!today" class="mt-2 text-[11.5px] text-muted-foreground">
      还没有批注。在阅读器里选中文字即可添加。
    </p>

    <template v-else>
      <div class="mt-2.5 flex-1 border-l-2 pl-2.5" :style="{ borderColor: COLORS[today.color] || COLORS.yellow }">
        <p class="text-[12.5px] leading-relaxed text-foreground">「{{ today.quote }}」</p>
        <p v-if="today.note" class="mt-1 text-[11.5px] text-muted-foreground">{{ today.note }}</p>
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
