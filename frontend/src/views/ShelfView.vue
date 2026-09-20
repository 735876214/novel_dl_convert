<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type BookCard } from '@/lib/api'
import {
  formatLabel,
  metaOf,
  seriesIndexLabel,
  sortBySeriesIndex,
  tagsLabel,
} from '@/lib/bookInfo'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'
import {
  CARD_INFO_OPTIONS,
  SHELF_SORT_OPTIONS,
  SHELF_VIEW_OPTIONS,
  useShelfPrefsStore,
} from '@/stores/shelfPrefs'

/**
 * 书库落地页。三条入口（库 / 智能书架 / 收藏夹）的共同落点。
 *
 * 本轮重做（对齐上游书架）：三视图（网格 / 列表 / 表格）、搜索、排序、
 * 折叠同系列、统一筛选面板、书卡信息密度。
 *
 * 数据流是**五段串联**，顺序不能换：
 *   store 的基础筛选（标签 / 库分面 / 智能书架）→ 搜索词 → 统一筛选面板 → 排序 → 折叠
 * 排序必须作用在最终可见集合上；折叠放最后，因为它会改变条目粒度（多本 → 一条）。
 */
const library = useLibraryStore()
const prefs = useShelfPrefsStore()
const router = useRouter()
const ui = useUiStore()

/** 当前书库（书架页库级控制：切库 / 扫描 / 管理）。空串 = 全部书库 */
const currentLib = computed<string>({
  get: () => library.currentLibraryId || '',
  set: (v: string) => {
    void library.setCurrentLibrary(v)
  },
})

function scanShelf(): void {
  api
    .scanNow()
    .then(() => {
      ui.toast('已触发一次扫描')
      void library.loadBooks(true)
    })
    .catch((e: Error) => ui.toast(e.message))
}

function manageLibs(): void {
  router.push('/tools/libraries')
}

/** 导出全部书目 CSV（含阅读进度/状态/评分），交给系统下载 */
async function onExport(): Promise<void> {
  try {
    await api.exportBooks()
    ui.toast('已导出书目 CSV')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '导出失败')
  }
}

// ---------------- 多选 + 批量动作 ----------------
// 批量动作镜像单本能力（set_status / set_rating / add_to_collection），不引入新数据模型。
const selectMode = ref(false)
const selected = ref<Set<string>>(new Set())
const batchCollection = ref<number | ''>('')
const collections = ref<Array<{ id: number; name: string }>>([])

function toggleSelect(id: string): void {
  const s = new Set(selected.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selected.value = s
}

/** 当前视图里**可见的书 id**（系列行跳过：它们没有勾选框，选代表本只会让人困惑） */
function visibleIds(): string[] {
  const out: string[] = []
  const push = (b?: { id?: string }): void => { if (b?.id) out.push(b.id) }
  if (prefs.prefs.view === 'list') {
    for (const e of listEntries.value) if (e.kind === 'book') push(e.book)
  } else if (prefs.prefs.view === 'table') {
    for (const row of tableRows.value) if (!row.toggle) push(row.book)
  } else {
    for (const r of rows.value) if (!isSeriesRow(r)) push(r.book)
  }
  return out
}

function selectAllVisible(): void {
  const ids = visibleIds()
  const allOn = ids.length > 0 && ids.every((id) => selected.value.has(id))
  selected.value = allOn ? new Set() : new Set(ids)
}

function enterSelect(): void {
  selectMode.value = !selectMode.value
  if (selectMode.value) {
    collections.value = []
    api.collections().then((r) => (collections.value = r.items)).catch(() => {})
  } else {
    selected.value = new Set()
  }
}

async function runBatch(action: string, params: Record<string, unknown>): Promise<void> {
  if (!selected.value.size) {
    ui.toast('先选几本书')
    return
  }
  const ids = [...selected.value]
  try {
    const r = await api.batch({ action, ids, params })
    ui.toast(`已处理 ${r.succeeded.length}/${r.total} 本` + (r.failed.length ? `，${r.failed.length} 本失败` : ''))
    if (r.failed.length) console.warn('[batch] 部分失败', r.failed)
    await library.loadBooks(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '批量操作失败')
  }
  selected.value = new Set()
}

// 多选模式下，点卡片/行是「切换选中」而不是「打开详情」
function onGridClick(r: any): void {
  if (!r.book) return
  if (selectMode.value && !isSeriesRow(r)) { toggleSelect(r.book.id); return }
  if (r.book) openBook(r.book.id)
}
function onEntryClick(e: any): void {
  if (!e.book) return
  if (selectMode.value && e.kind === 'book') { toggleSelect(e.book.id); return }
  openBook(e.book.id)
}
function onTableRowClick(row: any): void {
  if (!row.book) return
  // 系列行（带 toggle）没有勾选框，与网格口径一致：不参与多选
  if (selectMode.value && !row.toggle) { toggleSelect(row.book.id); return }
  openBook(row.book.id)
}

function batchStatus(s: string): void { runBatch('set_status', { status: s }) }
function batchRating(n: number): void { runBatch('set_rating', { stars: n }) }
async function batchAddToCollection(): Promise<void> {
  if (batchCollection.value === '') { ui.toast('先选一个收藏夹'); return }
  await runBatch('add_to_collection', { collection_id: batchCollection.value })
}
function statusText(s: string): string {
  return ({ unread: '未读', reading: '在读', finished: '已读完', paused: '搁置', abandoned: '弃读' } as Record<string, string>)[s] ?? s
}

const route = useRoute()
// 顶栏全局搜索会跳到这里并带上 ?q=关键词（原先顶栏只弹提示，没接线）
const keyword = ref(String(route.query.q || ''))
watch(() => route.query.q, (q) => { keyword.value = String(q || '') })
/** 已展开的系列名 */
const expanded = ref<string[]>([])

onMounted(() => library.loadBooks())

const source = computed(() => library.shelfBooks)

function uniq(xs: string[]): string[] {
  return [...new Set(xs.filter(Boolean))].sort((a, b) => a.localeCompare(b, 'zh'))
}

const formatOptions = computed(() => uniq(source.value.map((b) => (b.format || '').toUpperCase())))
const languageOptions = computed(() => uniq(source.value.map((b) => (b.language || '').trim())))
const tagOptions = computed(() => uniq(source.value.flatMap((b) => b.tags || [])))

const fFormat = ref('')
const fLanguage = ref('')
const fTag = ref('')
const fCover = ref<'all' | 'yes' | 'no'>('all')
const fStatus = ref<'all' | 'unread' | 'reading' | 'finished'>('all')

const hasFilter = computed(
  () =>
    Boolean(fFormat.value || fLanguage.value || fTag.value) ||
    fCover.value !== 'all' ||
    fStatus.value !== 'all',
)

function clearFilters(): void {
  fFormat.value = ''
  fLanguage.value = ''
  fTag.value = ''
  fCover.value = 'all'
  fStatus.value = 'all'
}

function statusOf(b: BookCard): 'unread' | 'reading' | 'finished' {
  const p = b.percent ?? 0
  if (p >= 99.5) return 'finished'
  return p > 0 ? 'reading' : 'unread'
}

const searched = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return source.value
  return source.value.filter((b) =>
    [b.title, b.author, b.series, b.name]
      .filter(Boolean)
      .some((v) => String(v).toLowerCase().includes(q)),
  )
})

const filtered = computed(() =>
  searched.value.filter((b) => {
    if (fFormat.value && (b.format || '').toUpperCase() !== fFormat.value) return false
    if (fLanguage.value && (b.language || '').trim() !== fLanguage.value) return false
    if (fTag.value && !(b.tags || []).includes(fTag.value)) return false
    if (fCover.value === 'yes' && !b.has_cover) return false
    if (fCover.value === 'no' && b.has_cover) return false
    if (fStatus.value !== 'all' && statusOf(b) !== fStatus.value) return false
    return true
  }),
)

const sorted = computed(() => {
  const list = [...filtered.value]
  const s = prefs.prefs.sort
  const sign = prefs.prefs.dir === 'asc' ? 1 : -1

  /** 文本比较：空值统一排到最后，否则空书名会挤在最前面 */
  const byText = (a: string, b: string): number => {
    if (!a && !b) return 0
    if (!a) return 1
    if (!b) return -1
    return a.localeCompare(b, 'zh')
  }

  list.sort((x, y) => {
    switch (s) {
      case 'title':
        return sign * byText(x.title || x.name, y.title || y.name)
      case 'author':
        return sign * byText(x.author, y.author)
      case 'series':
        // 系列排序要连序号一起比，否则同一系列内部顺序是随机的
        return (
          sign * (byText(x.series, y.series) || Number(x.series_index || 0) - Number(y.series_index || 0))
        )
      case 'progress':
        return sign * ((x.percent ?? 0) - (y.percent ?? 0))
      case 'pages':
        return sign * ((x.pages ?? 0) - (y.pages ?? 0))
      case 'stars':
        return sign * ((x.stars ?? 0) - (y.stars ?? 0))
      default:
        return sign * ((x.mtime ?? 0) - (y.mtime ?? 0))
    }
  })
  return list
})

/** 折叠后的条目：普通书一条，同系列合成一条 */
type Row = { key: string; book: BookCard; members: BookCard[] }

const rows = computed<Row[]>(() => {
  if (!prefs.prefs.collapseSeries) {
    return sorted.value.map((b) => ({ key: b.id, book: b, members: [b] }))
  }
  const out: Row[] = []
  const groups = new Map<string, BookCard[]>()
  for (const b of sorted.value) {
    const s = (b.series || '').trim()
    if (!s) {
      out.push({ key: b.id, book: b, members: [b] })
      continue
    }
    if (!groups.has(s)) {
      const arr: BookCard[] = []
      groups.set(s, arr)
      // 先占位，保持「首次出现」的排序位置
      out.push({ key: 'series:' + s, book: b, members: arr })
    }
    groups.get(s)!.push(b)
  }
  // 系列内部按序号重排：整理结果继承了外层排序，系列内顺序仍可能是乱的
  return out.map((r) =>
    isSeriesRow(r) && r.members.length > 1 ? { ...r, members: sortBySeriesIndex(r.members) } : r,
  )
})

function isSeriesRow(r: Row): boolean {
  return r.key.startsWith('series:')
}

function seriesName(r: Row): string {
  return r.book.series || ''
}

function isExpanded(r: Row): boolean {
  return expanded.value.includes(seriesName(r))
}

function toggleByName(name: string): void {
  expanded.value = expanded.value.includes(name)
    ? expanded.value.filter((x) => x !== name)
    : [...expanded.value, name]
}

/**
 * 列表视图的扁平展示项。
 *
 * 刻意**预先把层级拍平**，而不是在模板里用 `v-for` + `v-else` 混写 ——
 * 同一个元素上同时出现 `v-else` 与 `v-for` 时 Vue 的优先级行为很绕，
 * 拍平后模板只按 kind 分支，语义明确。
 */
type ListEntry = {
  key: string
  kind: 'book' | 'seriesOpen' | 'seriesClose'
  book?: BookCard
  name?: string
  count?: number
}

const listEntries = computed<ListEntry[]>(() => {
  const out: ListEntry[] = []
  for (const r of rows.value) {
    if (!isSeriesRow(r)) {
      out.push({ key: r.key, kind: 'book', book: r.book })
      continue
    }
    if (!isExpanded(r)) {
      out.push({ key: r.key, kind: 'seriesOpen', book: r.book, name: seriesName(r), count: r.members.length })
      continue
    }
    for (const b of r.members) out.push({ key: b.id, kind: 'book', book: b })
    out.push({ key: 'close:' + r.key, kind: 'seriesClose', name: seriesName(r), count: r.members.length })
  }
  return out
})

/** 表格行：同样拍平（折叠时每组只出首本，展开则全出） */
const tableRows = computed(() => {
  const out: Array<{ key: string; book: BookCard; toggle: { name: string; count: number } | null }> = []
  for (const r of rows.value) {
    const isSeries = isSeriesRow(r)
    const open = isExpanded(r)
    r.members.forEach((b, i) => {
      if (isSeries && !open && i > 0) return // 折叠时只出首本
      out.push({
        key: r.key + ':' + b.id,
        book: b,
        toggle:
          isSeries && r.members.length > 1 && i === 0
            ? { name: seriesName(r), count: r.members.length }
            : null,
      })
    })
  }
  return out
})

function showAuthor(): boolean {
  return prefs.cardInfo !== 'compact'
}

function showMeta(): boolean {
  return prefs.cardInfo === 'detailed'
}

const TABLE_COLS = ['书名', '作者', '系列', '格式', '页数', '进度', '评分']

const filterHint = computed(() => {
  const f = library.shelfFacet
  if (f === 'issues:1') return '存在异常、需要修复的书'
  if (f === 'nocover:1') return '缺少封面的 EPUB'
  if (f.startsWith('fmt:')) return `仅显示 ${f.slice(4).toUpperCase()} 格式`
  switch (library.smartKey) {
    case 'recent':
      return '按入库时间倒序（最多 50 本）'
    case 'unread':
      return '尚未开始阅读的书'
    case 'reading':
      return '已开始但尚未读完的书'
    case 'finished':
      return '已读完的书'
    case 'annotated':
      return '含批注或高亮的书'
    default:
      return ''
  }
})

const isFiltered = computed(() => Boolean(library.shelfFacet) || library.isSmart)

function chip(active: boolean): string {
  return active
    ? 'bg-primary text-primary-foreground'
    : 'bg-muted text-muted-foreground hover:text-foreground'
}

function openBook(id: string): void {
  router.push(`/book/${id}`)
}

const INPUT_CLS =
  'h-8 min-w-0 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring'
</script>

<template>
  <div>
    <PageHead
      :title="library.shelfTitle"
      :desc="`共 ${sorted.length} 本${sorted.length !== source.length ? ` · 已筛掉 ${source.length - sorted.length} 本` : ''}`"
    />
    <!-- 库级控制（最小集：切库 / 扫描 / 管理；重命名与删除仍在「书库管理」页，避免第二处写入口） -->
    <div class="mb-3 flex flex-wrap items-center gap-2 text-[12.5px]">
      <span class="text-muted-foreground">书库</span>
      <select
        v-model="currentLib"
        class="h-8 rounded-md border border-border bg-muted px-2 text-foreground outline-none transition-colors focus:border-ring"
      >
        <option value="">全部书库</option>
        <option v-for="lib in library.libraryEntities" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
      </select>
      <Button size="sm" variant="ghost" @click="scanShelf">立即扫描</Button>
      <Button size="sm" variant="ghost" @click="manageLibs">书库管理</Button>
    </div>
    <p v-if="isFiltered && filterHint" class="-mt-2 mb-3 text-[12px] text-muted-foreground">
      {{ filterHint }}
    </p>

    <!-- 工具栏 -->
    <Card class="mb-3" padding="sm">
      <div class="flex flex-wrap items-center gap-2">
        <div class="relative min-w-[12rem] flex-1">
          <Icon
            name="search"
            class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
          />
          <input
            v-model="keyword"
            type="text"
            placeholder="搜索书名 / 作者 / 系列…"
            aria-label="书架搜索"
            class="h-8 w-full rounded-md border border-border bg-muted pr-2.5 pl-8 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          >
        </div>

        <div class="flex gap-1">
          <button
            v-for="v in SHELF_VIEW_OPTIONS"
            :key="v.value"
            type="button"
            :title="v.label"
            class="cursor-pointer rounded-md px-2.5 py-1.5 text-[12px] font-medium transition-colors"
            :class="chip(prefs.prefs.view === v.value)"
            @click="prefs.patch({ view: v.value })"
          >
            {{ v.label }}
          </button>
        </div>

        <Button size="sm" :variant="selectMode ? 'primary' : 'ghost'" class="ml-2" @click="enterSelect">
          {{ selectMode ? '退出多选' : '多选' }}
        </Button>

        <select
          :value="prefs.prefs.sort"
          aria-label="排序字段"
          :class="[INPUT_CLS, 'shrink-0']"
          @change="prefs.patch({ sort: ($event.target as HTMLSelectElement).value as never })"
        >
          <option v-for="o in SHELF_SORT_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <Button
          size="sm"
          :title="prefs.prefs.dir === 'asc' ? '升序' : '降序'"
          @click="prefs.patch({ dir: prefs.prefs.dir === 'asc' ? 'desc' : 'asc' })"
        >
          {{ prefs.prefs.dir === 'asc' ? '↑' : '↓' }}
        </Button>
        <Button
          size="sm"
          :variant="prefs.prefs.collapseSeries ? 'primary' : 'ghost'"
          title="把同一系列的书合成一条"
          @click="prefs.patch({ collapseSeries: !prefs.prefs.collapseSeries })"
        >
          折叠系列
        </Button>
        <Button
          size="sm"
          :variant="prefs.filtersOpen ? 'primary' : 'ghost'"
          @click="prefs.filtersOpen = !prefs.filtersOpen"
        >
          筛选<span v-if="hasFilter"> ●</span>
        </Button>
      </div>

      <div class="mt-2.5 flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
        <span class="text-[11.5px] text-muted-foreground">书卡信息</span>
        <button
          v-for="o in CARD_INFO_OPTIONS"
          :key="o.value"
          type="button"
          class="cursor-pointer rounded-full px-2.5 py-0.5 text-[11.5px] font-medium transition-colors"
          :class="chip(prefs.cardInfo === o.value)"
          @click="prefs.cardInfo = o.value"
        >
          {{ o.label }}
        </button>
        <Button size="sm" variant="ghost" class="ml-auto" @click="onExport">导出 CSV</Button>
        <Button size="sm" variant="ghost" @click="prefs.reset()">恢复默认</Button>
      </div>
    </Card>

    <!-- 统一筛选面板 -->
    <Card v-if="prefs.filtersOpen" class="mb-3" padding="sm">
      <div class="flex flex-wrap items-end gap-3">
        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">格式</span>
          <select v-model="fFormat" :class="INPUT_CLS">
            <option value="">全部</option>
            <option v-for="f in formatOptions" :key="f" :value="f">{{ f }}</option>
          </select>
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">语言</span>
          <select v-model="fLanguage" :class="INPUT_CLS">
            <option value="">全部</option>
            <option v-for="l in languageOptions" :key="l" :value="l">{{ l }}</option>
          </select>
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">题材（EPUB 元数据）</span>
          <select v-model="fTag" :class="INPUT_CLS">
            <option value="">全部</option>
            <option v-for="t in tagOptions" :key="t" :value="t">{{ t }}</option>
          </select>
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">封面</span>
          <select v-model="fCover" :class="INPUT_CLS">
            <option value="all">全部</option>
            <option value="yes">有封面</option>
            <option value="no">无封面</option>
          </select>
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">阅读状态</span>
          <select v-model="fStatus" :class="INPUT_CLS">
            <option value="all">全部</option>
            <option value="unread">未读</option>
            <option value="reading">在读</option>
            <option value="finished">已读完</option>
          </select>
        </label>

        <Button size="sm" class="ml-auto" :disabled="!hasFilter" @click="clearFilters">清除筛选</Button>
      </div>
    </Card>

    <Card v-if="selectMode" class="mb-3" padding="sm">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[12.5px] text-muted-foreground">已选 <b class="text-foreground">{{ selected.size }}</b> 本</span>
        <Button size="sm" variant="ghost" @click="selectAllVisible">全选 / 取消</Button>
        <span class="h-4 w-px bg-border" />
        <span class="text-[12px] text-muted-foreground">标记：</span>
        <Button v-for="s in ['reading', 'finished', 'paused', 'abandoned', 'unread']" :key="s" size="sm" variant="ghost" @click="batchStatus(s)">
          {{ statusText(s) }}
        </Button>
        <span class="h-4 w-px bg-border" />
        <span class="text-[12px] text-muted-foreground">评分：</span>
        <Button v-for="n in [1, 2, 3, 4, 5]" :key="n" size="sm" variant="ghost" @click="batchRating(n)">{{ n }}★</Button>
        <span class="h-4 w-px bg-border" />
        <select v-model="batchCollection" :class="INPUT_CLS">
          <option value="">加入收藏夹…</option>
          <option v-for="c in collections" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <Button size="sm" :disabled="!batchCollection" @click="batchAddToCollection">加入</Button>
        <Button size="sm" variant="primary" class="ml-auto" @click="enterSelect">完成</Button>
      </div>
    </Card>

    <EmptyState
      v-if="!sorted.length"
      icon="library"
      :title="source.length ? '没有符合条件的书' : '这个书架还是空的'"
      :desc="source.length ? '试试清除搜索词或筛选条件。' : '换个入口看看，或到「探索发现」把书下载进来。'"
    />

    <!-- 网格视图 -->
    <div
      v-else-if="prefs.prefs.view === 'grid'"
      class="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8"
    >
      <button
        v-for="r in rows"
        :key="r.key"
        type="button"
        class="group cursor-pointer text-left"
        @click="onGridClick(r)"
      >
        <div class="relative">
          <input
            v-if="selectMode && r.book && !isSeriesRow(r)"
            type="checkbox"
            class="absolute left-1.5 top-1.5 z-10 h-4 w-4 cursor-pointer accent-primary"
            :checked="selected.has(r.book.id)"
            @click.stop="toggleSelect(r.book.id)"
          />
          <BookCover :book="r.book" :show-title="!showAuthor()" />
          <span
            v-if="isSeriesRow(r)"
            class="absolute right-1.5 bottom-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10.5px] font-medium text-white tabular-nums"
          >
            {{ r.members.length }} 册
          </span>
          <!-- 格式徽章只在单本书上显示：系列行不给格式，因为一个系列可能含多种格式 -->
          <span
            v-else-if="formatLabel(r.book)"
            class="absolute top-1 right-1 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[9.5px] text-white"
          >
            {{ formatLabel(r.book) }}
          </span>
        </div>
        <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">
          <template v-if="isSeriesRow(r)">{{ seriesName(r) }}</template>
          <template v-else>
            {{ r.book.title || r.book.name }}
            <span v-if="seriesIndexLabel(r.book)" class="ml-1 font-mono text-[11px] text-muted-foreground">
              {{ seriesIndexLabel(r.book) }}
            </span>
          </template>
        </div>
        <div v-if="showAuthor()" class="truncate text-[11.5px] text-muted-foreground">
          {{ isSeriesRow(r) ? `${r.members.length} 本` : r.book.author || '未知作者' }}
        </div>
        <div v-if="showMeta() && !isSeriesRow(r)" class="truncate text-[10.5px] text-muted-foreground">
          {{ metaOf(r.book) }}
        </div>
        <div
          v-if="showMeta() && !isSeriesRow(r) && tagsLabel(r.book)"
          class="truncate text-[10.5px] text-muted-foreground/80"
        >
          {{ tagsLabel(r.book) }}
        </div>
        <div
          v-if="!isSeriesRow(r) && (r.book.percent ?? 0) > 0 && prefs.cardInfo !== 'compact'"
          class="mt-1.5 flex items-center gap-1.5"
        >
          <div class="h-1 flex-1 overflow-hidden rounded-full bg-muted">
            <div class="h-full rounded-full bg-primary" :style="{ width: `${r.book.percent}%` }" />
          </div>
          <span class="shrink-0 text-[10.5px] text-muted-foreground tabular-nums">
            {{ Math.round(r.book.percent ?? 0) }}%
          </span>
        </div>
      </button>
    </div>

    <!-- 列表视图 -->
    <div v-else-if="prefs.prefs.view === 'list'" class="flex flex-col gap-2">
      <Card
        v-for="e in listEntries"
        :key="e.key"
        padding="sm"
        :class="e.kind === 'book' ? 'cursor-pointer transition-colors hover:bg-muted/50' : 'border-dashed'"
        @click="onEntryClick(e)"
      >
        <!-- 折叠的系列：一行代表整个系列 -->
        <div v-if="e.kind === 'seriesOpen'" class="flex items-center gap-3">
          <div class="w-9 shrink-0">
            <BookCover v-if="e.book" :book="e.book" :show-title="false" :interactive="false" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[13px] font-medium text-foreground">{{ e.name }}</div>
            <div class="mt-0.5 text-[11.5px] text-muted-foreground">
              {{ e.count }} 本 · {{ e.book?.author || '未知作者' }}
            </div>
          </div>
          <Button size="sm" @click.stop="toggleByName(e.name || '')">展开</Button>
        </div>

        <!-- 展开后的收尾行 -->
        <div
          v-else-if="e.kind === 'seriesClose'"
          class="flex items-center gap-2 text-[11.5px] text-muted-foreground"
        >
          <span>系列「{{ e.name }}」共 {{ e.count }} 本，已展开</span>
          <Button size="sm" variant="ghost" class="ml-auto" @click.stop="toggleByName(e.name || '')">收起</Button>
        </div>

        <!-- 单本书 -->
        <div v-else-if="e.book" class="flex items-center gap-3">
          <input
            v-if="selectMode"
            type="checkbox"
            class="h-4 w-4 shrink-0 cursor-pointer accent-primary"
            :checked="selected.has(e.book.id)"
            @click.stop="toggleSelect(e.book.id)"
          />
          <div class="w-9 shrink-0">
            <BookCover :book="e.book" :show-title="false" :interactive="false" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[13px] font-medium text-foreground">
              {{ e.book.title || e.book.name }}
              <span v-if="seriesIndexLabel(e.book)" class="ml-1 font-mono text-[11px] text-muted-foreground">
                {{ seriesIndexLabel(e.book) }}
              </span>
            </div>
            <div v-if="showAuthor()" class="mt-0.5 truncate text-[11.5px] text-muted-foreground">
              {{ e.book.author || '未知作者' }}
              <span v-if="e.book.series"> · {{ e.book.series }}</span>
            </div>
            <div v-if="showMeta()" class="mt-0.5 truncate text-[10.5px] text-muted-foreground">
              {{ metaOf(e.book) }}
            </div>
          </div>
          <div class="flex shrink-0 flex-col items-end gap-1">
            <span v-if="(e.book.stars ?? 0) > 0" class="text-[11px] text-amber-500">
              {{ '★'.repeat(e.book.stars ?? 0) }}
            </span>
            <span class="text-[11.5px] text-muted-foreground tabular-nums">
              {{ Math.round(e.book.percent ?? 0) }}%
            </span>
          </div>
        </div>
      </Card>
    </div>

    <!-- 表格视图 -->
    <Card v-else padding="none" class="overflow-x-auto">
      <table class="w-full min-w-[44rem] border-collapse text-left">
        <thead>
          <tr class="border-b border-border">
            <th
              v-for="c in TABLE_COLS"
              :key="c"
              class="px-3 py-2 text-[11.5px] font-semibold text-muted-foreground"
            >
              {{ c }}
            </th>
            <th class="w-8 px-3 py-2" />
            <th class="w-20 px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in tableRows"
            :key="row.key"
            class="cursor-pointer border-b border-border/60 transition-colors last:border-b-0 hover:bg-muted/50"
            @click="onTableRowClick(row)"
          >
            <td v-if="selectMode" class="px-3 py-2">
              <input
                v-if="row.book"
                type="checkbox"
                class="h-4 w-4 cursor-pointer accent-primary"
                :checked="selected.has(row.book.id)"
                @click.stop="toggleSelect(row.book.id)"
              />
            </td>
            <td class="max-w-[18rem] truncate px-3 py-2 text-[12.5px] text-foreground">
              {{ row.book.title || row.book.name }}
              <span v-if="seriesIndexLabel(row.book)" class="ml-1 font-mono text-[10.5px] text-muted-foreground">
                {{ seriesIndexLabel(row.book) }}
              </span>
              <span
                v-if="row.toggle"
                class="ml-1.5 rounded bg-muted px-1 text-[10px] text-muted-foreground tabular-nums"
              >
                系列 {{ row.toggle.count }} 册
              </span>
            </td>
            <td class="max-w-[10rem] truncate px-3 py-2 text-[12px] text-muted-foreground">
              {{ row.book.author || '—' }}
            </td>
            <td class="max-w-[10rem] truncate px-3 py-2 text-[12px] text-muted-foreground">
              {{ row.book.series || '—' }}
            </td>
            <td class="px-3 py-2 font-mono text-[11.5px] text-muted-foreground">
              {{ (row.book.format || '').toUpperCase() || '—' }}
            </td>
            <td class="px-3 py-2 text-[12px] text-muted-foreground tabular-nums">
              {{ row.book.pages ? `${row.book.pages}${row.book.pages_source === 'estimate' ? '≈' : ''}` : '—' }}
            </td>
            <td class="px-3 py-2 text-[12px] text-muted-foreground tabular-nums">
              {{ Math.round(row.book.percent ?? 0) }}%
            </td>
            <td class="px-3 py-2 text-[11.5px] text-amber-500">
              {{ (row.book.stars ?? 0) > 0 ? '★'.repeat(row.book.stars ?? 0) : '—' }}
            </td>
            <td class="px-3 py-2 text-right">
              <Button
                v-if="row.toggle"
                size="sm"
                variant="ghost"
                @click.stop="toggleByName(row.toggle.name)"
              >
                {{ expanded.includes(row.toggle.name) ? '收起' : '展开' }}
              </Button>
            </td>
          </tr>
        </tbody>
      </table>
    </Card>
  </div>
</template>
