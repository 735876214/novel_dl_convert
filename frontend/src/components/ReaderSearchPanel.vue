<script setup lang="ts">
import { ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type BookSearchHit } from '@/lib/api'

/**
 * EPUB 书内搜索（第 189 期）。
 *
 * 结果按章返回第一条命中 + 上下文；点一条只做「跳到那一章」，不在正文里再划词高亮
 * —— 片段可能不在当前章的渲染范围内（连续流只挂窗口内的章块），假装能精确滚动会误导。
 */
const props = defineProps<{ bookId: string }>()
const emit = defineEmits<{ jump: [chapterIndex: number]; close: [] }>()

const q = ref('')
const items = ref<BookSearchHit[]>([])
const loading = ref(false)
const msg = ref('')
const scanned = ref(0)
const truncated = ref(false)

async function run(): Promise<void> {
  const term = q.value.trim()
  if (!term || loading.value) return
  loading.value = true
  msg.value = ''
  items.value = []
  try {
    const r = await api.searchBook(props.bookId, term)
    items.value = r.items
    scanned.value = r.scanned
    truncated.value = r.truncated
    if (!r.items.length) msg.value = `没有找到「${term}」（扫描 ${r.scanned} 章）`
  } catch (e) {
    msg.value = e instanceof Error ? e.message : '搜索失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="mb-2 rounded-md border border-border bg-card p-2">
    <div class="flex flex-wrap items-center gap-2">
      <div class="relative min-w-[12rem] flex-1">
        <Icon name="search" class="pointer-events-none absolute top-1/2 left-2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          v-model="q"
          type="search"
          aria-label="书内搜索"
          placeholder="在本书正文里搜索"
          class="h-8 w-full rounded-md border border-border bg-card pl-7 pr-2 text-[12px] text-foreground outline-none focus:border-ring"
          @keyup.enter="run"
        >
      </div>
      <Button size="sm" variant="primary" :disabled="loading || !q.trim()" @click="run">
        {{ loading ? '搜索中…' : '搜索' }}
      </Button>
      <button
        type="button"
        class="cursor-pointer px-1 text-muted-foreground transition-colors hover:text-foreground"
        aria-label="关闭书内搜索"
        @click="$emit('close')"
      >×</button>
    </div>
    <p v-if="msg" class="mt-1.5 text-[11.5px] text-muted-foreground">{{ msg }}</p>
    <div v-if="items.length" class="mt-1.5">
      <div class="mb-1 text-[11px] text-muted-foreground">
        命中 {{ items.length }} 章<template v-if="truncated">（已截断）</template> · 扫描 {{ scanned }} 章
      </div>
      <ul class="max-h-64 divide-y divide-border overflow-y-auto">
        <li v-for="hit in items" :key="hit.chapter_index" class="py-1.5">
          <button
            type="button"
            class="block w-full cursor-pointer text-left text-[11.5px] leading-snug text-foreground hover:text-primary"
            @click="$emit('jump', hit.chapter_index)"
          >
            <span class="font-medium">{{ hit.title || `第 ${hit.chapter_index + 1} 章` }}</span>
            <span class="mt-0.5 block text-muted-foreground">{{ hit.snippet }}</span>
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>
