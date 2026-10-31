<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import Icon from '@/components/ui/Icon.vue'
import { SETTINGS_PAGES } from '@/data/settingsNav'
import { useLibraryStore } from '@/stores/library'

/**
 * 命令面板（第 194 期，⌘/Ctrl+K）。
 *
 * 只做**导航**：页面、设置页、书名 → 直接跳转。不在这里执行破坏性动作
 * （删书 / 移除书库），也不发任何写请求 —— 面板是入口，不是第二个操作台。
 */
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const library = useLibraryStore()
const q = ref('')
const active = ref(0)
const input = ref<HTMLInputElement | null>(null)

const NAV = [
  { label: '仪表盘', to: '/', hint: '页面' },
  { label: '书架', to: '/shelf', hint: '页面' },
  { label: '探索发现', to: '/explore', hint: '页面' },
  { label: '实体总览', to: '/browse', hint: '页面' },
  { label: '系列', to: '/series', hint: '页面' },
  { label: '作者', to: '/authors', hint: '页面' },
  { label: '收藏夹', to: '/collections', hint: '页面' },
  { label: '智能书架', to: '/smart-scopes', hint: '页面' },
  { label: '播客', to: '/podcasts', hint: '页面' },
  { label: '数据统计', to: '/stats', hint: '页面' },
  { label: '阅读记录', to: '/log', hint: '页面' },
  { label: '阅读活动', to: '/reading-activity', hint: '页面' },
  { label: '通知中心', to: '/notifications', hint: '页面' },
  { label: '成就', to: '/achievements', hint: '页面' },
  { label: '任务中心', to: '/tasks', hint: '页面' },
  { label: '工具', to: '/tools', hint: '页面' },
  { label: '收书目录', to: '/book-dock', hint: '页面' },
]

const items = computed(() => {
  const term = q.value.trim().toLowerCase()
  const match = (label: string, extra = '') =>
    !term || label.toLowerCase().includes(term) || extra.toLowerCase().includes(term)
  const out = [
    ...NAV.filter((x) => match(x.label, x.to)).map((x) => ({ ...x, key: `nav:${x.to}` })),
    ...SETTINGS_PAGES.filter((p) => match(p.zh, p.label))
      .map((p) => ({ label: p.zh, to: `/settings/${p.path}`, hint: '设置', key: `set:${p.path}` })),
    ...(library.books || [])
      .filter((b) => match(String(b.title || b.name || ''), String(b.author || '')))
      .slice(0, 8)
      .map((b) => ({
        label: String(b.title || b.name || ''),
        to: `/book/${b.id}`,
        hint: b.author ? `书 · ${b.author}` : '书',
        key: `book:${b.id}`,
      })),
  ]
  return out.slice(0, 40)
})

function close(): void {
  emit('close')
}

function pick(i = active.value): void {
  const item = items.value[i]
  if (!item) return
  close()
  void router.push(item.to)
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    active.value = Math.min(items.value.length - 1, active.value + 1)
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    active.value = Math.max(0, active.value - 1)
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    pick()
  }
}

watch(() => props.open, (open) => {
  if (!open) return
  q.value = ''
  active.value = 0
  void nextTick(() => input.value?.focus())
})

watch(q, () => { active.value = 0 })
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-[60] flex items-start justify-center bg-black/40 p-4 pt-[12vh]"
    @click.self="close"
  >
    <div class="w-full max-w-lg overflow-hidden rounded-lg border border-border bg-card shadow-xl">
      <div class="flex items-center gap-2 border-b border-border px-3 py-2">
        <Icon name="search" class="h-4 w-4 shrink-0 text-muted-foreground" />
        <input
          ref="input"
          v-model="q"
          type="text"
          aria-label="命令面板"
          placeholder="跳转到页面 / 设置 / 书名…（↑↓ 选择，回车打开）"
          class="min-w-0 flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-muted-foreground"
          @keydown="onKey"
        >
        <kbd class="shrink-0 rounded border border-border px-1 text-[10px] text-muted-foreground">Esc</kbd>
      </div>
      <ul v-if="items.length" class="max-h-[50vh] overflow-y-auto py-1">
        <li v-for="(item, i) in items" :key="item.key">
          <button
            type="button"
            class="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-[12.5px]"
            :class="i === active ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted/60'"
            @mouseenter="active = i"
            @click="pick(i)"
          >
            <span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
            <span class="shrink-0 text-[10.5px] text-muted-foreground">{{ item.hint }}</span>
          </button>
        </li>
      </ul>
      <p v-else class="px-3 py-6 text-center text-[12px] text-muted-foreground">没有匹配的页面 / 设置 / 书</p>
    </div>
  </div>
</template>
