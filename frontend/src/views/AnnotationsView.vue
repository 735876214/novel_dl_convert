<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type AllAnnotation } from '@/lib/api'

/** 批注总览：跨全部书籍的高亮与笔记，按创建时间倒序。 */
const router = useRouter()
const items = ref<AllAnnotation[]>([])
const loading = ref(true)

const COLOR_HEX: Record<string, string> = {
  yellow: '#f5d76e',
  green: '#8fd694',
  blue: '#8fc1f0',
  pink: '#f2a6c4',
}
function hex(c: string): string {
  return COLOR_HEX[c] || COLOR_HEX.yellow
}

const query = ref('')
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter(
    (a) =>
      a.quote.toLowerCase().includes(q) ||
      a.note.toLowerCase().includes(q) ||
      a.book_title.toLowerCase().includes(q),
  )
})

function fmtDate(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function exportMarkdown(): void {
  if (!items.value.length) return
  const groups = new Map<string, AllAnnotation[]>()
  for (const a of items.value) {
    const list = groups.get(a.book_title) ?? []
    list.push(a)
    groups.set(a.book_title, list)
  }
  const lines: string[] = [
    '# 全部批注',
    '',
    `> 共 ${items.value.length} 条 · 导出于 ${new Date().toLocaleString()}`,
    '',
  ]
  for (const [title, list] of groups) {
    const author = list[0]?.book_author
    lines.push(`## ${title}${author ? ` · ${author}` : ''}`, '')
    for (const a of list) {
      lines.push(`> ${a.quote}`, '', `— 第 ${a.chapter + 1} 章`, '')
      if (a.note) lines.push(a.note, '')
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const el = document.createElement('a')
  el.href = url
  el.download = `全部批注-${new Date().toISOString().slice(0, 10)}.md`
  el.click()
  URL.revokeObjectURL(url)
}

async function load(): Promise<void> {
  loading.value = true
  try {
    items.value = (await api.allAnnotations()).items
  } catch {
    items.value = []
  }
  loading.value = false
}

onMounted(load)

function open(a: AllAnnotation): void {
  router.push(`/read/${a.book_id}?chapter=${a.chapter}`)
}

async function remove(a: AllAnnotation): Promise<void> {
  try {
    await api.deleteAnnotation(a.book_id, a.id)
  } catch {
    /* ignore */
  }
  items.value = items.value.filter((x) => x.id !== a.id)
}
</script>

<template>
  <div>
    <PageHead title="批注" :desc="`共 ${items.length} 条高亮与笔记`" />

    <div class="mb-4 flex items-center gap-2">
      <div class="relative max-w-[22rem] flex-1">
        <Icon name="search" class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          v-model="query"
          type="text"
          placeholder="搜索摘录 / 笔记 / 书名…"
          class="h-8 w-full rounded-md border border-border bg-muted pr-2.5 pl-8 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        >
      </div>
      <button
        v-if="items.length"
        type="button"
        class="shrink-0 cursor-pointer text-[12px] text-primary transition-opacity hover:opacity-80"
        title="导出全部为 Markdown"
        @click="exportMarkdown"
      >
        导出 Markdown
      </button>
    </div>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <div v-else-if="filtered.length" class="flex flex-col gap-2">
      <Card v-for="a in filtered" :key="a.id" padding="sm">
        <div class="flex items-start gap-3">
          <span class="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" :style="{ background: hex(a.color) }" />
          <div class="min-w-0 flex-1">
            <p class="text-[12.5px] leading-relaxed text-foreground">「{{ a.quote }}」</p>
            <p v-if="a.note" class="mt-1 text-[12px] text-muted-foreground">{{ a.note }}</p>
            <button
              type="button"
              class="mt-1.5 cursor-pointer text-[11px] text-primary transition-opacity hover:opacity-80"
              @click="open(a)"
            >
              {{ a.book_title }}
              <span v-if="a.book_author" class="text-muted-foreground"> · {{ a.book_author }}</span>
              <span class="text-muted-foreground"> · 第 {{ a.chapter + 1 }} 章</span>
              <span v-if="a.created_at" class="text-muted-foreground"> · {{ fmtDate(a.created_at) }}</span>
            </button>
          </div>
          <button
            type="button"
            class="shrink-0 cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
            title="删除批注"
            @click="remove(a)"
          >
            <Icon name="trash" class="h-3.5 w-3.5" />
          </button>
        </div>
      </Card>
    </div>

    <EmptyState
      v-else
      :icon="query ? 'search' : 'pencil'"
      :title="query ? '没有匹配的批注' : '还没有批注'"
      :desc="query ? '换个关键词再试。' : '在阅读器里选中文字即可添加高亮与笔记，这里会汇总全部摘录。'"
    />
  </div>
</template>
