<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { HIGHLIGHT_COLORS, highlightHex } from '@/data/annotationColors'
import { api, type AllAnnotation, type AnnotationOverview } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 批注总览：跨全部书籍的高亮与笔记。
 *
 * 分两档视图：**活跃**与**垃圾桶**。删除是软删除（移入垃圾桶、可恢复），
 * 「彻底删除」只对垃圾桶里的条目开放 —— 后端也会拒绝活跃条目的 purge。
 *
 * 分组是**纯前端**做的（月 / 书 / 颜色 / 来源）：列表本来就在手上，重排即可；
 * 需要跨全量历史聚合的只有顶部的统计条，那个走服务端 `/api/annotations/overview`。
 */
const router = useRouter()
const library = useLibraryStore()
const ui = useUiStore()
const items = ref<AllAnnotation[]>([])
const overview = ref<AnnotationOverview | null>(null)
const loading = ref(true)
const view = ref<'active' | 'trashed'>('active')

type GroupMode = 'month' | 'book' | 'color' | 'source'
const groupBy = ref<GroupMode>('book')
const GROUP_MODES: { key: GroupMode; label: string }[] = [
  { key: 'month', label: '按月份' },
  { key: 'book', label: '按书籍' },
  { key: 'color', label: '按颜色' },
  { key: 'source', label: '按来源' },
]

/** 来源枚举 → 显示名。三来源是上游口径（`origin` 的取值域）。 */
const ORIGIN_LABELS: Record<string, string> = {
  web: '本应用（Web 阅读器）',
  koreader: 'KOReader',
  kobo: 'Kobo',
}

const COLOR_LABELS: Record<string, string> = Object.fromEntries(
  HIGHLIGHT_COLORS.map((c) => [c.key, c.label.replace('高亮', '')]),
)

function fmtDate(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function monthKey(ts: number): string {
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// ---------- 过滤 ----------

const query = ref('')

const scoped = computed(() =>
  items.value.filter((a) => (view.value === 'trashed' ? a.deleted_at > 0 : a.deleted_at === 0)),
)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return scoped.value
  return scoped.value.filter(
    (a) =>
      a.quote.toLowerCase().includes(q) ||
      a.note.toLowerCase().includes(q) ||
      a.book_title.toLowerCase().includes(q),
  )
})

// ---------- 分组 ----------

interface Group {
  key: string
  label: string
  items: AllAnnotation[]
}

const groups = computed<Group[]>(() => {
  const buckets = new Map<string, AllAnnotation[]>()
  for (const a of filtered.value) {
    const k =
      groupBy.value === 'month'
        ? monthKey(a.created_at)
        : groupBy.value === 'book'
          ? a.book_title
          : groupBy.value === 'color'
            ? a.color
            : a.origin || 'web'
    const list = buckets.get(k)
    if (list) list.push(a)
    else buckets.set(k, [a])
  }

  const label = (k: string): string => {
    if (groupBy.value === 'month') return k
    if (groupBy.value === 'color') return COLOR_LABELS[k] || k
    if (groupBy.value === 'source') return ORIGIN_LABELS[k] || k
    return k
  }

  const keys = [...buckets.keys()]
  if (groupBy.value === 'month') {
    keys.sort().reverse() // 近的月份在前
  } else if (groupBy.value === 'color') {
    // 颜色按调色板本身的顺序（黄→…→灰），而不是按条目多少
    const order = HIGHLIGHT_COLORS.map((c) => c.key)
    keys.sort((x, y) => order.indexOf(x) - order.indexOf(y))
  } else if (groupBy.value === 'source') {
    const order = ['web', 'koreader', 'kobo']
    keys.sort((x, y) => order.indexOf(x) - order.indexOf(y))
  } else {
    // 按条目数降序，同数量按名字，避免刷新一次顺序就变
    keys.sort((x, y) => buckets.get(y)!.length - buckets.get(x)!.length || x.localeCompare(y))
  }

  return keys.map((k) => ({ key: k, label: label(k), items: buckets.get(k)! }))
})

/** 来源分组下的如实说明 —— 不给「同步 KOReader/Kobo」的空承诺。 */
const showSourceNote = computed(() => groupBy.value === 'source')

// ---------- 操作 ----------

async function load(): Promise<void> {
  loading.value = true
  try {
    // 一次把垃圾桶也取回来：两个视图共用一份数据，切视图不必再打请求
    const [list, ov] = await Promise.all([api.allAnnotations(true), api.annotationOverview()])
    items.value = list.items
    overview.value = ov
  } catch {
    items.value = []
    overview.value = null
  }
  loading.value = false
}

onMounted(load)

function open(a: AllAnnotation): void {
  router.push(`/read/${a.book_id}?chapter=${a.chapter}`)
}

async function trash(a: AllAnnotation): Promise<void> {
  try {
    await api.deleteAnnotation(a.book_id, a.id)
  } catch {
    /* ignore */
  }
  await load()
}

async function restore(a: AllAnnotation): Promise<void> {
  try {
    await api.restoreAnnotation(a.book_id, a.id)
  } catch {
    /* ignore */
  }
  await load()
}

async function purge(a: AllAnnotation): Promise<void> {
  try {
    await api.purgeAnnotation(a.book_id, a.id)
  } catch {
    /* ignore */
  }
  await load()
}

// ---------- 导出（第 43 期：改为走后端，支持格式与范围）----------
// 后端 `/api/annotations/export` 只导**活跃**批注（`deleted_at=0`）——
// 垃圾桶里是已丢弃的内容，不该出现在导出的书摘里。格式 markdown / json / csv。

const exportFormat = ref<'markdown' | 'json' | 'csv'>('markdown')
/** 只在「当前选中了某个书库」时可勾：全部书库时它没有意义，勾了也不该假装收窄 */
const exportLibraryOnly = ref(false)
const exporting = ref(false)

async function doExport(): Promise<void> {
  exporting.value = true
  try {
    await api.exportAnnotations(exportFormat.value, {
      libraryId: exportLibraryOnly.value ? library.currentLibraryId : undefined,
    })
    ui.toast('已导出批注')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '导出失败')
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div>
    <PageHead
      title="批注"
      :desc="overview
        ? `活跃 ${overview.active} 条 · 垃圾桶 ${overview.trashed} 条 · 有过批注 ${overview.weeks} 周`
        : '全部摘录与笔记'"
    />

    <!-- 统计条：数据来自 /api/annotations/overview（跨全量历史聚合，故放服务端） -->
    <div v-if="overview" class="mb-4 grid gap-2 sm:grid-cols-3">
      <Card padding="sm">
        <p class="text-[11px] text-muted-foreground">活跃批注</p>
        <p class="mt-0.5 text-[19px] leading-none font-semibold text-foreground tabular-nums">{{ overview.active }}</p>
      </Card>
      <Card padding="sm">
        <p class="text-[11px] text-muted-foreground">有过批注的周数</p>
        <p class="mt-0.5 text-[19px] leading-none font-semibold text-foreground tabular-nums">{{ overview.weeks }}</p>
      </Card>
      <Card padding="sm">
        <p class="text-[11px] text-muted-foreground">最长连续无批注</p>
        <p class="mt-0.5 text-[19px] leading-none font-semibold text-foreground tabular-nums">
          {{ overview.longest_quiet_weeks }}<span class="ml-1 text-[11px] font-normal text-muted-foreground">周</span>
        </p>
      </Card>
    </div>

    <!-- 视图切换：活跃 / 垃圾桶 -->
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <div class="flex items-center gap-1 rounded-md border border-border p-0.5">
        <button
          type="button"
          class="cursor-pointer rounded px-2.5 py-1 text-[12px] transition-colors"
          :class="view === 'active' ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="view = 'active'"
        >
          活跃 {{ overview?.active ?? 0 }}
        </button>
        <button
          type="button"
          class="cursor-pointer rounded px-2.5 py-1 text-[12px] transition-colors"
          :class="view === 'trashed' ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="view = 'trashed'"
        >
          垃圾桶 {{ overview?.trashed ?? 0 }}
        </button>
      </div>

      <div class="relative max-w-[22rem] flex-1">
        <Icon name="search" class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          v-model="query"
          type="text"
          placeholder="搜索摘录 / 笔记 / 书名…"
          class="h-8 w-full rounded-md border border-border bg-muted pr-2.5 pl-8 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        >
      </div>

      <div v-if="view === 'active' && overview?.active" class="ml-auto flex shrink-0 items-center gap-2">
        <label
          class="flex items-center gap-1 text-[11.5px]"
          :class="library.currentLibraryId ? 'text-muted-foreground' : 'text-muted-foreground/50'"
          :title="library.currentLibraryId ? '只导出当前书库的批注' : '当前是「全部书库」，无法按库收窄'"
        >
          <input
            v-model="exportLibraryOnly"
            type="checkbox"
            class="h-3.5 w-3.5 cursor-pointer accent-primary"
            :disabled="!library.currentLibraryId"
          >
          仅当前书库
        </label>
        <select
          v-model="exportFormat"
          class="h-8 cursor-pointer rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none focus:border-ring"
        >
          <option value="markdown">Markdown</option>
          <option value="json">JSON</option>
          <option value="csv">CSV</option>
        </select>
        <Button size="sm" variant="ghost" :disabled="exporting" @click="doExport">
          {{ exporting ? '导出中…' : '导出' }}
        </Button>
      </div>
    </div>

    <!-- 分组切换 -->
    <div class="mb-4 flex flex-wrap items-center gap-1.5">
      <span class="text-[11.5px] text-muted-foreground">分组</span>
      <button
        v-for="m in GROUP_MODES"
        :key="m.key"
        type="button"
        class="cursor-pointer rounded-md border px-2 py-0.5 text-[11.5px] transition-colors"
        :class="groupBy === m.key
          ? 'border-ring bg-muted font-medium text-foreground'
          : 'border-border text-muted-foreground hover:text-foreground'"
        @click="groupBy = m.key"
      >
        {{ m.label }}
      </button>
    </div>

    <p v-if="showSourceNote" class="mb-3 text-[11.5px] text-muted-foreground">
      设备回传（KOReader / Kobo）的批注尚未接入 —— 目前只有本应用阅读器里创建的批注，
      因此来源只有「{{ ORIGIN_LABELS.web }}」一种。
    </p>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else-if="filtered.length">
      <section v-for="g in groups" :key="g.key" class="mb-5">
        <h3 class="mb-2 flex items-baseline gap-2 text-[12px] font-semibold text-foreground">
          {{ g.label }}
          <span class="text-[11px] font-normal text-muted-foreground tabular-nums">{{ g.items.length }}</span>
        </h3>
        <div class="flex flex-col gap-2">
          <Card v-for="a in g.items" :key="a.id" padding="sm">
            <div class="flex items-start gap-3">
              <span class="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" :style="{ background: highlightHex(a.color) }" />
              <div class="min-w-0 flex-1">
                <p class="text-[12.5px] leading-relaxed text-foreground" :class="view === 'trashed' ? 'opacity-70' : ''">「{{ a.quote }}」</p>
                <p v-if="a.note" class="mt-1 text-[12px] text-muted-foreground">{{ a.note }}</p>
                <button
                  type="button"
                  class="mt-1.5 cursor-pointer text-left text-[11px] text-primary transition-opacity hover:opacity-80"
                  @click="open(a)"
                >
                  {{ a.book_title }}
                  <span v-if="a.book_author" class="text-muted-foreground"> · {{ a.book_author }}</span>
                  <span class="text-muted-foreground"> · 第 {{ a.chapter + 1 }} 章</span>
                  <span v-if="a.created_at" class="text-muted-foreground"> · {{ fmtDate(a.created_at) }}</span>
                </button>
              </div>

              <!-- 垃圾桶：恢复 / 彻底删除；活跃：移入垃圾桶 -->
              <div v-if="view === 'trashed'" class="flex shrink-0 items-center gap-0.5">
                <button
                  type="button"
                  class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  title="恢复这条批注"
                  @click="restore(a)"
                >
                  <Icon name="undo" class="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
                  title="彻底删除（不可恢复）"
                  @click="purge(a)"
                >
                  <Icon name="trash" class="h-3.5 w-3.5" />
                </button>
              </div>
              <button
                v-else
                type="button"
                class="shrink-0 cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
                title="移入垃圾桶（可在垃圾桶里恢复）"
                @click="trash(a)"
              >
                <Icon name="trash" class="h-3.5 w-3.5" />
              </button>
            </div>
          </Card>
        </div>
      </section>
    </template>

    <EmptyState
      v-else
      :icon="query ? 'search' : 'pencil'"
      :title="query
        ? '没有匹配的批注'
        : view === 'trashed' ? '垃圾桶是空的' : '还没有批注'"
      :desc="query
        ? '换个关键词再试。'
        : view === 'trashed'
          ? '删掉的批注会先放到这里，可以恢复，也可以彻底删除。'
          : '在阅读器里选中文字即可添加高亮与笔记，这里会汇总全部摘录。'"
    />
  </div>
</template>
