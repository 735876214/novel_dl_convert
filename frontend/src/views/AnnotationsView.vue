<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { HIGHLIGHT_COLORS, highlightHex, highlightStyleLabel } from '@/data/annotationColors'
import { canJumpTo, chapterLabel, ORIGIN_LABELS, originLabel } from '@/lib/annotations'
import { api, type AllAnnotation, type AnnotationOverview, type KoreaderImportResult } from '@/lib/api'
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
/** 加载失败信息：失败不能退化成「还没有批注」。 */
const error = ref('')
const view = ref<'active' | 'trashed'>('active')

type GroupMode = 'month' | 'book' | 'color' | 'source'
const groupBy = ref<GroupMode>('book')
const GROUP_MODES: { key: GroupMode; label: string }[] = [
  { key: 'month', label: '按月份' },
  { key: 'book', label: '按书籍' },
  { key: 'color', label: '按颜色' },
  { key: 'source', label: '按来源' },
]

// 章节的显示口径走 `lib/annotations`（唯一一份）。**别在这里写 `chapter + 1`**：
// 设备回传的批注章节**序号未知**（后端记 -1），照 +1 渲染就是编造一个「第 1 章」。

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
    if (groupBy.value === 'source') return originLabel(k)
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

// ---------- 从 KOReader 导入（第 63 期 6/6）----------
//
// ⚠️ **这不是 kosync**。官方 kosync 只有 4 个端点、全是阅读进度，**没有批注接口**
// （客户端 `plugins/kosync.koplugin/api.json` 与服务端 `routes.lua` 都查过）。
// KOReader 的批注跨设备同步走的是**文件**：关书时导出 `<书名>.annotations.lua`。
// 所以这里是「去书库里找那个文件」，而不是「连一个不存在的协议」。
//
// 两步走是刻意的：先 dry-run 让用户看到「会导多少条」，确认了再落库 ——
// 这个动作会往用户的批注库里写东西，不该点一下就直接写。

const importing = ref(false)
/** 最近一次 dry-run 的结果；有它就显示确认条 */
const importPreview = ref<KoreaderImportResult | null>(null)

/** 预览里的「可导入条数」：dry-run 不落库，`totals` 因此全是 0，要从每个文件的 `items` 累。 */
const previewItems = computed(() =>
  (importPreview.value?.files || []).reduce((n, f) => n + (f.items || 0), 0),
)
/** 整份没读成的文件数 —— 不能因为「找到了文件」就说「导得进来」。 */
const scannedErrors = computed(() =>
  (importPreview.value?.files || []).filter((f) => f.error).length,
)

async function dryRunImport(): Promise<void> {
  importing.value = true
  try {
    const r = await api.importKoreaderAnnotations(false)
    importPreview.value = r
    if (!r.scanned) ui.toast('没找到 KOReader 的导出文件')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '扫描失败')
  } finally {
    importing.value = false
  }
}

async function confirmImport(): Promise<void> {
  importing.value = true
  try {
    const r = await api.importKoreaderAnnotations(true)
    importPreview.value = null
    ui.toast(`已导入 ${r.totals.added} 条（更新 ${r.totals.updated} 条）`)
    await load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '导入失败')
  } finally {
    importing.value = false
  }
}

// ---------- 操作 ----------

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    // 一次把垃圾桶也取回来：两个视图共用一份数据，切视图不必再打请求
    const [list, ov] = await Promise.all([api.allAnnotations(true), api.annotationOverview()])
    items.value = list.items
    overview.value = ov
  } catch (e) {
    items.value = []
    overview.value = null
    error.value = e instanceof Error ? e.message : '加载失败'
  }
  loading.value = false
}

onMounted(load)

function open(a: AllAnnotation): void {
  // 序号未知（设备回传的批注）就没有可跳的目标：`?chapter=-1` 会落到章首，
  // 用户以为「点进去就到那条批注」，实际到的是第一章开头。按钮那边也不渲染它可点。
  if (!canJumpTo(a)) return
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

      <div class="ml-auto flex shrink-0 items-center gap-2">
        <!--
          导入按钮**没有** `v-if` 包着「已有批注」：恰恰是「一条都没有」的时候最需要它。
          文案不写「同步」也不写「连接 KOReader」—— 它做的是去书库里找文件，不是连设备。
        -->
        <Button
          size="sm"
          variant="ghost"
          :disabled="importing"
          title="去各书库里找 KOReader 关书时导出的 <书名>.annotations.lua，先预览再导入"
          @click="dryRunImport"
        >
          <Icon name="download" class="h-3.5 w-3.5" />
          {{ importing ? '扫描中…' : '从 KOReader 导入' }}
        </Button>

        <template v-if="view === 'active' && overview?.active">
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
        </template>
      </div>
    </div>

    <!--
      dry-run 确认条：先给数字、再落库。**只在看过预览之后才出现**，
      不会因为误点「导入」就直接往批注库里写东西。
    -->
    <Card v-if="importPreview" padding="sm" class="mb-3">
      <div class="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[12px] text-foreground">
        <Icon name="download" class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span v-if="!importPreview.scanned">没找到 KOReader 的导出文件。</span>
        <span v-else>
          找到 <b class="tabular-nums">{{ importPreview.scanned }}</b> 个导出文件，
          共 <b class="tabular-nums">{{ previewItems }}</b> 条批注可导入
          <template v-if="importPreview.totals.skipped">
            （另有 <b class="tabular-nums">{{ importPreview.totals.skipped }}</b> 条读不懂位置或没有引文，会跳过）
          </template>。
        </span>
        <span v-if="scannedErrors" class="text-destructive">
          <b class="tabular-nums">{{ scannedErrors }}</b> 个文件没能解析（文件头不是本项目能读的格式），已整份跳过。
        </span>
        <div class="ml-auto flex items-center gap-2">
          <Button size="sm" variant="ghost" :disabled="importing" @click="importPreview = null">取消</Button>
          <Button
            v-if="previewItems"
            size="sm"
            variant="primary"
            :disabled="importing"
            @click="confirmImport"
          >
            {{ importing ? '导入中…' : '确认导入' }}
          </Button>
        </div>
      </div>
      <p class="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        导入是幂等的（同一条不会变两份），但「只增不删」—— 导出文件里没有删除标记，
        你在设备上删掉的那条仍会留在这里。
      </p>
    </Card>

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

    <p v-if="showSourceNote" class="mb-3 text-[11.5px] leading-relaxed text-muted-foreground">
      来源按批注是从哪来的分：<span class="text-foreground">{{ ORIGIN_LABELS.web }}</span> 是这里划的，
      <span class="text-foreground">{{ ORIGIN_LABELS.koreader }}</span> 是从 KOReader 的导出文件读进来的。
      <br>
      Kobo 的批注本项目还没有接入路径（它的位置格式与 KOReader 不同），所以不会出现在这一组里 ——
      这不是「同步失败」，是「没有实现」。
    </p>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <!-- 加载失败：可重试的错误态（不与「还没有批注」空态混淆） -->
    <Card v-else-if="error" padding="sm">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        <span>批注加载失败：{{ error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="load">重试</Button>
      </div>
    </Card>

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
              <span class="mt-1 text-[10.5px] text-muted-foreground">{{ highlightStyleLabel(a.style) }}</span>
              <div class="min-w-0 flex-1">
                <p class="text-[12.5px] leading-relaxed text-foreground" :class="view === 'trashed' ? 'opacity-70' : ''">「{{ a.quote }}」</p>
                <p v-if="a.note" class="mt-1 text-[12px] text-muted-foreground">{{ a.note }}</p>
                <!--
                  能跳的渲染成按钮，不能跳的（章节序号未知：设备回传的批注）渲染成纯文本 ——
                  「点了没反应」比「一看就知道点不了」更让人困惑。
                -->
                <component
                  :is="canJumpTo(a) ? 'button' : 'p'"
                  :type="canJumpTo(a) ? 'button' : undefined"
                  class="mt-1.5 text-left text-[11px]"
                  :class="canJumpTo(a)
                    ? 'cursor-pointer text-primary transition-opacity hover:opacity-80'
                    : 'text-muted-foreground'"
                  :title="canJumpTo(a) ? '在阅读器里打开这一章' : '这条批注没有章节序号，跳不过去'"
                  @click="open(a)"
                >
                  <span :class="canJumpTo(a) ? '' : 'text-foreground'">{{ a.book_title }}</span>
                  <span v-if="a.book_author" class="text-muted-foreground"> · {{ a.book_author }}</span>
                  <!-- 序号未知时显示设备给的章节**标题**；连标题都没有就整段不渲染 -->
                  <span v-if="chapterLabel(a)" class="text-muted-foreground"> · {{ chapterLabel(a) }}</span>
                  <span v-if="a.created_at" class="text-muted-foreground"> · {{ fmtDate(a.created_at) }}</span>
                </component>
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
      v-else-if="query"
      icon="search"
      title="没有匹配的批注"
      desc="换个关键词再试。"
    />

    <EmptyState
      v-else-if="view === 'trashed'"
      icon="trash"
      title="垃圾桶是空的"
      desc="删掉的批注会先放到这里，可以恢复，也可以彻底删除。"
    />

    <!--
      空态只摆**真的能走通**的两条路：本机阅读器（写了就有）与 KOReader（有导入按钮）。
      **不摆 Kobo 卡片** —— 那个来源没有接入路径（位置格式不同），摆上去就是个假承诺。
    -->
    <div v-else class="grid gap-3 sm:grid-cols-2">
      <Card padding="md">
        <div class="flex items-start gap-3">
          <div class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
            <Icon name="pencil" class="h-4 w-4" />
          </div>
          <div class="min-w-0">
            <h3 class="text-[13px] font-semibold text-foreground">{{ ORIGIN_LABELS.web }}</h3>
            <p class="mt-1 text-[12px] leading-relaxed text-muted-foreground">
              在阅读器里选中文字就能加高亮与笔记，这里会汇总全部摘录。
            </p>
          </div>
        </div>
      </Card>

      <Card padding="md">
        <div class="flex items-start gap-3">
          <div class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
            <Icon name="book" class="h-4 w-4" />
          </div>
          <div class="min-w-0">
            <h3 class="text-[13px] font-semibold text-foreground">{{ ORIGIN_LABELS.koreader }}</h3>
            <p class="mt-1 text-[12px] leading-relaxed text-muted-foreground">
              在 KOReader 里开「关书时导出批注」（<code class="text-[11px]">annotations_export_on_closing</code>），
              导出文件留在书旁边，回到这里点「从 KOReader 导入」。
            </p>
            <Button size="sm" variant="ghost" class="mt-2.5" :disabled="importing" @click="dryRunImport">
              <Icon name="download" class="h-3.5 w-3.5" />
              {{ importing ? '扫描中…' : '从 KOReader 导入' }}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  </div>
</template>
