<script setup lang="ts">
/**
 * 设置项搜索浮层（对齐上游 `Search settings` + Cmd+K 面板）。
 *
 * 索引**完全由 `settingsNav.ts` 派生**，不另建平行清单：
 *   1. 页面级条目 —— 中文名 / 英文原名 / 所属分组，命中即跳到该页；
 *   2. 条目级条目 —— 占位页 `upstream.items`（上游页面内的具体设置项），
 *      命中同样跳到承载它的设置页，让「搜得到但不知道在哪」的问题有落点。
 * 上游实测该面板列出 42 项，本项目页数扩容后条目更多，因此列表限高滚动。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import Icon from '@/components/ui/Icon.vue'
import { SETTINGS_GROUPS } from '@/data/settingsNav'
import { useSettingsSearch } from '@/composables/useSettingsSearch'

interface Row {
  key: string
  to: string
  /** 结果主标题（中文名） */
  zh: string
  /** 次级信息：英文原名 · 所属分组 */
  sub: string
  /** 条目级结果时附上命中的设置项原文 */
  item?: string
  /** 匹配得分，越小越靠前（页面级优先于条目级） */
  rank: number
}

const router = useRouter()
const search = useSettingsSearch()

const keyword = ref('')
const activeIndex = ref(0)
const inputEl = ref<HTMLInputElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

/** 打平后的可搜索索引：页面 + 上游页内设置项 */
const index = computed<Row[]>(() => {
  const rows: Row[] = []
  for (const g of SETTINGS_GROUPS) {
    for (const pg of g.pages) {
      const to = `/settings/${pg.path}`
      const sub = `${pg.label} · ${g.zh}`
      rows.push({ key: `page:${pg.path}`, to, zh: pg.zh, sub, rank: 0 })
      for (const item of pg.upstream?.items ?? []) {
        rows.push({ key: `item:${pg.path}:${item}`, to, zh: pg.zh, sub, item, rank: 1 })
      }
    }
  }
  return rows
})

const results = computed<Row[]>(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return index.value.filter((r) => r.rank === 0)
  const words = q.split(/\s+/).filter(Boolean)
  return index.value
    .filter((r) => {
      const hay = `${r.zh} ${r.sub} ${r.item ?? ''}`.toLowerCase()
      return words.every((w) => hay.includes(w))
    })
    .slice(0, 60)
})

/** 打开时聚焦输入框；关键词变化后把选中行归零，避免高亮停在越界位置 */
watch(
  () => search.open.value,
  async (v) => {
    if (!v) return
    keyword.value = ''
    activeIndex.value = 0
    await nextTick()
    inputEl.value?.focus()
  },
)

watch(keyword, () => {
  activeIndex.value = 0
})

/** 键盘选择后保证高亮行可见（面板限高滚动，不滚动会出现「选中了但看不见」） */
watch(activeIndex, async () => {
  await nextTick()
  listEl.value?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
})

function move(step: number): void {
  const n = results.value.length
  if (!n) return
  activeIndex.value = (activeIndex.value + step + n) % n
}

function jump(row?: Row): void {
  const target = row ?? results.value[activeIndex.value]
  if (!target) return
  search.closePanel()
  if (target.to !== router.currentRoute.value.path) router.push(target.to)
  // 已经在该页时也关掉浮层，避免「回车后什么都没发生」的错觉
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    e.preventDefault()
    search.closePanel()
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    move(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    move(-1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    jump()
  }
}
</script>

<template>
  <Transition
    enter-active-class="transition duration-150 ease-out"
    enter-from-class="opacity-0"
    leave-active-class="transition duration-100 ease-in"
    leave-to-class="opacity-0"
  >
    <div
      v-if="search.open.value"
      class="fixed inset-0 z-50 flex items-start justify-center bg-[#0f172a]/25 px-4 pt-[12vh] backdrop-blur-[2px]"
      @click.self="search.closePanel()"
    >
      <div
        class="flex max-h-[68vh] w-full max-w-[34rem] flex-col overflow-hidden rounded-[14px] border border-border bg-card shadow-lg transition duration-150 ease-out"
        :class="search.open.value ? 'translate-y-0' : '-translate-y-1'"
      >
        <!-- 输入区 -->
        <div class="flex shrink-0 items-center gap-2.5 border-b border-border px-3.5 py-3">
          <Icon name="search" class="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            ref="inputEl"
            v-model="keyword"
            type="text"
            class="min-w-0 flex-1 border-0 bg-transparent p-0 text-[13px] text-foreground shadow-none outline-none placeholder:text-muted-foreground"
            placeholder="搜索设置项…（页面名或设置项关键字）"
            autocomplete="off"
            spellcheck="false"
            aria-label="搜索设置项"
            @keydown="onKeydown"
          >
          <button
            type="button"
            class="shrink-0 cursor-pointer rounded border border-border px-1.5 py-0.5 text-[10.5px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title="关闭"
            aria-label="关闭搜索"
            @click="search.closePanel()"
          >Esc</button>
        </div>

        <!-- 结果列表 -->
        <div ref="listEl" class="min-h-0 flex-1 overflow-y-auto p-1.5">
          <button
            v-for="(r, i) in results"
            :key="r.key"
            type="button"
            :data-active="i === activeIndex"
            class="flex w-full cursor-pointer items-start gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors"
            :class="
              i === activeIndex
                ? 'bg-[var(--shell-accent-tint)]'
                : 'hover:bg-[var(--shell-accent-wash)]'
            "
            @mousemove="activeIndex = i"
            @click="jump(r)"
          >
            <Icon
              :name="r.item ? 'note' : 'settings'"
              class="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
            />
            <span class="min-w-0 flex-1">
              <span class="flex items-baseline gap-1.5">
                <span class="truncate text-[12.5px] font-medium text-foreground">{{ r.zh }}</span>
                <span class="truncate font-mono text-[10.5px] text-muted-foreground">{{ r.sub }}</span>
              </span>
              <span v-if="r.item" class="mt-0.5 block truncate text-[11.5px] text-muted-foreground">
                {{ r.item }}
              </span>
            </span>
            <Icon
              v-if="i === activeIndex"
              name="arrowRight"
              class="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary"
            />
          </button>

          <p v-if="!results.length" class="px-2.5 py-6 text-center text-[12.5px] text-muted-foreground">
            没有匹配的设置项。试试「进度」「抓取」「元数据」这类关键字，或直接按分组浏览左侧导航。
          </p>
        </div>

        <!-- 键位提示 -->
        <div
          class="flex shrink-0 items-center gap-3 border-t border-border px-3.5 py-2 text-[10.5px] text-muted-foreground"
        >
          <span><span class="font-mono">↑↓</span> 选择</span>
          <span><span class="font-mono">↵</span> 打开</span>
          <span><span class="font-mono">Esc</span> 关闭</span>
          <span class="ml-auto">{{ results.length }} 项结果</span>
        </div>
      </div>
    </div>
  </Transition>
</template>
