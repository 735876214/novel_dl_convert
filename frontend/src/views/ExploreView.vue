<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import {
  api,
  apiErrorMessage,
  type SearchHit,
  type SearchSourceState,
  type TaskItem,
} from '@/lib/api'
import {
  appendHits,
  groupHits,
  keepLoadingMore,
  mergeSourceStates,
  rankGroups,
  sourcesOf,
  splitSources,
} from '@/lib/searchResults'
import { useLibraryStore } from '@/stores/library'
import { useTasksStore } from '@/stores/tasks'
import { useUiStore } from '@/stores/ui'

/**
 * 探索发现：跨全部已启用书源聚合检索，结果可预览与下载。
 *
 * 第 71 期把它从「能用」改到「做扎实」，四件事都在这个文件里看得见：
 * 1. **来源字段**：结果行读 `hit.source`（后端第 71 期起真的写它了）—— 之前后端只给
 *    `_source`，于是徽章空白、点「预览」必然 502「未知书源: undefined」；
 * 2. **逐源状态如实显示**：`sources[]` 里的成功数 / 失败原因原文 / 被闸门跳过原因，
 *    顶部一行汇总、展开看逐条（原先后端不返回它，那条警示横幅永远不出现）；
 * 3. **同名合并 + 匹配度排序 + 真分页**：纯逻辑在 `lib/searchResults.ts`（有单测），
 *    这里只负责「取数 → 调它 → 渲染」；「加载更多」是**追加**，不覆盖已加载的结果；
 * 4. **闸门不搞成「点了才报错」**：进页面先读 `/api/sources/status`，下载关着就把搜索与
 *    下载按钮置灰、把后端给的原因原文摆出来并给出口；后端同样真拦（双保险）。
 *
 * 竞态防护：每次**新检索**换一个新的 AbortController，并在发起前 abort 上一次；
 * 序号闸门保证「被 abort 的那次」不会回头改状态（否则 loading/结果会被旧请求写花）。
 */
const ui = useUiStore()
const tasks = useTasksStore()
const library = useLibraryStore()

const keyword = ref('')
const searching = ref(false)
const loadingMore = ref(false)
const searched = ref(false)
/** 已累计的命中（分页**追加**在这里，不是每页替换） */
const hits = ref<SearchHit[]>([])
/** 各源状态（最后一页为准；第 71 期起后端才会返回它） */
const sourceStates = ref<SearchSourceState[]>([])
const page = ref(1)
const hasMore = ref(false)
/** 展开了来源清单的组（`HitGroup.key`） */
const expanded = ref<Set<string>>(new Set())
const showSources = ref(false)

const previewOpen = ref(false)
const previewTitle = ref('')
const previewAuthor = ref('')
const previewToc = ref<string[]>([])
const previewSample = ref('')
const previewError = ref('')
const previewLoading = ref(false)

/** 下载闸门：空串 = 可用；非空 = 后端给的原因原文（**不在前端另写一份措辞**） */
const gateText = ref('')
/** 命中键（`source|url`）→ 本次会话发起的任务 id，用于行内显示真实状态 */
const taskByHit = ref<Record<string, string>>({})
/** 命中键 → 正在发起（防连点） */
const sending = ref<Record<string, boolean>>({})

let inflight: AbortController | null = null
/** 新检索的序号：只有最新一次的响应可以改状态 */
let searchSeq = 0

const HOT_WORDS = ['三体', '诡秘之主', '长安的荔枝', '凡人修仙传', '球状闪电']

const hasResults = computed(() => hits.value.length > 0)
const downloadEnabled = computed(() => !gateText.value)
const srcOk = computed(() => splitSources(sourceStates.value).ok)
const srcFailed = computed(() => splitSources(sourceStates.value).failed)
const srcSkipped = computed(() => splitSources(sourceStates.value).skipped)
/** 合并 + 排序后的展示列表（纯函数，见 lib/searchResults.ts） */
const groups = computed(() => rankGroups(groupHits(hits.value), keyword.value))

const pageDesc = computed(() => {
  if (library.hasNoLibraries) return '跨全部已启用书源聚合检索 —— 但还没有书库，下载前请先新建一个'
  if (!downloadEnabled.value) return '跨全部已启用书源聚合检索 —— 下载功能当前关闭，先打开才能检索'
  return '跨全部已启用书源聚合检索，选中结果可直接下载'
})

/** Esc 关闭预览弹窗（无障碍：弹窗应可键盘关闭） */
function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && previewOpen.value) previewOpen.value = false
}
onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  void loadGate()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  inflight?.abort()
})

/**
 * 进页面就读一次闸门状态（第 71 期）。
 *
 * 判据用 `download_enabled` 这个**真字段**，不用「blocked_reason 里有没有某句话」
 * 那种字符串匹配（措辞一变前端就失效）；但**显示**的文案仍然用后端给的原文 ——
 * 这样「界面说的」与「后端拒绝时说的」必然是同一句。
 */
async function loadGate(): Promise<void> {
  try {
    const r = await api.sourcesStatus()
    const items = r.items ?? []
    const enabled = items[0]?.download_enabled ?? true
    gateText.value = enabled ? '' : (items.find((s) => s.blocked_reason)?.blocked_reason ?? '')
  } catch {
    // 读不到就**不拦**：真的被拒时后端会带着原因原文回来，toast 会讲清楚
    gateText.value = ''
  }
}

function runSearch(word?: string): void {
  const q = (word ?? keyword.value).trim()
  if (!q) {
    ui.toast('请输入书名')
    return
  }
  keyword.value = q

  inflight?.abort()
  inflight = new AbortController()
  const seq = ++searchSeq
  const signal = inflight.signal

  searching.value = true
  api
    .search(q, 1, signal)
    .then((r) => {
      if (seq !== searchSeq) return
      hits.value = r.results ?? []
      sourceStates.value = r.sources ?? []
      page.value = r.page ?? 1
      hasMore.value = r.has_more === true
      expanded.value = new Set()
      taskByHit.value = {}
      searched.value = true
    })
    .catch((e: unknown) => {
      if (e instanceof Error && e.name === 'AbortError') return
      if (seq !== searchSeq) return
      ui.toast(apiErrorMessage(e, '检索失败'))
    })
    .finally(() => {
      // 只有最新一次才许改「检索中」：否则被 abort 的旧请求会把新请求的 loading 抹掉
      if (seq === searchSeq) searching.value = false
    })
}

/**
 * 「加载更多」：向各源取下一页并**追加**（不覆盖、不重复）。
 *
 * `has_more` 由后端给（逐源的聚合口径只有它知道）；但**这一页没带来新条目**时按钮照样收起
 * （`keepLoadingMore`）—— 规则源的 `{page}` 只表示「模板支持翻页」，站点不认这个参数时
 * 会不停回吐同一页，那时留着按钮就是一条假交互。
 */
function loadMore(): void {
  const seq = searchSeq
  const next = page.value + 1
  loadingMore.value = true
  api
    .search(keyword.value, next, inflight?.signal)
    .then((r) => {
      if (seq !== searchSeq) return
      const merged = appendHits(hits.value, r.results ?? [])
      hits.value = merged.hits
      sourceStates.value = mergeSourceStates(sourceStates.value, r.sources ?? [])
      page.value = r.page ?? next
      hasMore.value = keepLoadingMore(r.has_more === true, merged.added)
    })
    .catch((e: unknown) => {
      if (e instanceof Error && e.name === 'AbortError') return
      if (seq !== searchSeq) return
      ui.toast(apiErrorMessage(e, '加载更多失败'))
    })
    .finally(() => {
      if (seq === searchSeq) loadingMore.value = false
    })
}

function hitKey(h: SearchHit): string {
  return `${h.source}|${h.url}`
}

/** 源名的展示值：优先后端给的 `source_name`，缺省回落源名本身 */
function sourceLabel(s: string): string {
  const found = hits.value.find((h) => h.source === s)
  return (found?.source_name as string) || s
}

function toggle(key: string): void {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

/** 该命中对应的任务行（本次会话发起过的才有） */
function taskOf(h: SearchHit): TaskItem | undefined {
  const id = taskByHit.value[hitKey(h)]
  return id ? tasks.tasks.find((t) => t.id === id) : undefined
}

const TASK_TEXT: Record<string, string> = {
  queued: '已入队',
  running: '下载中',
  done: '已完成',
  failed: '失败',
}

/** 行内状态文案：失败时**直接把后端的原因原文带上**（不自己编一句） */
function taskText(h: SearchHit): string {
  const t = taskOf(h)
  if (!t) return ''
  const label = TASK_TEXT[t.status] ?? t.status
  return t.status === 'failed' && t.error ? `${label}：${t.error}` : label
}

function taskTone(h: SearchHit): 'neutral' | 'warn' | 'ok' | 'err' {
  const t = taskOf(h)
  if (!t) return 'neutral'
  if (t.status === 'failed') return 'err'
  if (t.status === 'done') return 'ok'
  return 'warn'
}

function openPreview(hit: SearchHit): void {
  previewOpen.value = true
  previewTitle.value = hit.title || '（无书名）'
  previewAuthor.value = ''
  previewToc.value = []
  previewSample.value = ''
  previewError.value = ''
  previewLoading.value = true
  api
    .preview(hit.source, hit.url)
    .then((data) => {
      // 后端两个分支（适配器自带 `preview` / 通用兜底）回的**都是** `{toc, sample}`：
      // 目录标题列表 + 首段样本（≤1500 字）。第 71 期之前这里读的是 `chapters` / `intro`
      // —— 两个都不存在，于是预览弹窗即使请求成功也是空的。
      const d = data as Record<string, unknown>
      previewAuthor.value = typeof d.author === 'string' ? d.author : ''
      previewToc.value = Array.isArray(d.toc) ? d.toc.map((t) => String(t)) : []
      previewSample.value = typeof d.sample === 'string' ? d.sample : ''
    })
    .catch((e: unknown) => {
      previewError.value = apiErrorMessage(e, '预览失败')
    })
    .finally(() => {
      previewLoading.value = false
    })
}

/** 发起下载：交给后端，然后让任务 store 从服务端刷新真实状态 */
async function startDownload(hit: SearchHit): Promise<void> {
  // 0 库时**提前拦下**（第 38 期）：后端此时会收下任务再在后台失败
  //（`_run_download` 里 `no_library_reason()` ⇒ 任务标 failed），用户看到的是
  //「已加入下载队列」，失败却要跑到任务中心才发现 —— 一次注定失败的往返没必要发。
  if (library.hasNoLibraries) {
    ui.toast('还没有书库：先新建一个书库，下载才有地方落')
    return
  }
  const key = hitKey(hit)
  if (sending.value[key]) return
  sending.value = { ...sending.value, [key]: true }
  try {
    const r = await api.download({ ...hit })
    taskByHit.value = { ...taskByHit.value, [key]: r.task_id }
    ui.toast(`已加入下载队列：${hit.title}`)
    // 任务状态统一由 store 从 /api/tasks 拉取并按需轮询（本页不维护第二套轮询）。
    void tasks.track()
  } catch (e) {
    ui.toast(apiErrorMessage(e, '发起下载失败'))
  } finally {
    const next = { ...sending.value }
    delete next[key]
    sending.value = next
  }
}
</script>

<template>
  <div>
    <PageHead title="探索发现" :desc="pageDesc" />

    <!-- 闸门：下载关着时**先说清楚**，按钮同时置灰 —— 不允许「点了才吃一个 400」（第 71 期）。
         文案是后端 `gate_reason()` 的原文，与「书源管理」页显示的是同一句。 -->
    <Card v-if="gateText" class="mb-4">
      <div class="flex items-start gap-2">
        <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
        <div class="min-w-0 flex-1 text-[12px] leading-relaxed text-foreground">
          {{ gateText }}
          <RouterLink to="/settings/ext/network" class="ml-1 underline">去打开</RouterLink>
        </div>
      </div>
    </Card>

    <Card class="mb-4">
      <div class="flex items-center gap-2">
        <div class="relative min-w-0 flex-1">
          <Icon name="search" class="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="keyword"
            type="text"
            placeholder="输入书名，例如「三体」"
            aria-label="搜索书名"
            :disabled="!downloadEnabled"
            class="h-9 w-full rounded-md border border-border bg-muted pr-3 pl-9 text-[13px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card disabled:cursor-not-allowed disabled:opacity-60"
            @keydown.enter="runSearch()"
          >
        </div>
        <Button
          variant="primary"
          size="md"
          :disabled="searching || !downloadEnabled"
          @click="runSearch()"
        >
          {{ searching ? '检索中…' : '检索' }}
        </Button>
      </div>

      <div class="mt-2.5 flex flex-wrap items-center gap-1.5">
        <span class="text-[11.5px] text-muted-foreground">热词</span>
        <button
          v-for="w in HOT_WORDS"
          :key="w"
          type="button"
          :disabled="!downloadEnabled"
          class="cursor-pointer rounded-full bg-muted px-2.5 py-0.5 text-[11.5px] text-muted-foreground transition-colors hover:bg-[var(--shell-accent-tint)] hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          @click="runSearch(w)"
        >
          {{ w }}
        </button>
      </div>
    </Card>

    <!-- 逐源状态（第 71 期）：一行汇总，展开看每个源的真实原因。
         「失败」与「被闸门跳过」刻意分开 —— 一个要去看源，一个要去改设置。 -->
    <Card v-if="searched && sourceStates.length" class="mb-3" padding="none">
      <button
        type="button"
        class="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-left"
        @click="showSources = !showSources"
      >
        <span class="text-[12px] text-muted-foreground">
          已查 {{ sourceStates.length }} 个源 ·
          <span class="text-foreground">成功 {{ srcOk.length }}</span>
          <template v-if="srcFailed.length">
            · <span class="text-warning">失败 {{ srcFailed.length }}</span>
          </template>
          <template v-if="srcSkipped.length">
            · <span class="text-warning">被跳过 {{ srcSkipped.length }}</span>
          </template>
        </span>
        <span class="ml-auto text-[11.5px] text-muted-foreground">{{ showSources ? '收起' : '详情' }}</span>
      </button>
      <ul v-if="showSources" class="border-t border-border px-4 py-2">
        <li
          v-for="s in sourceStates"
          :key="s.name"
          class="flex items-start gap-2 py-1 text-[11.5px]"
        >
          <Badge :tone="s.skipped ? 'warn' : s.ok ? 'ok' : 'err'">
            {{ s.ok ? `${s.count} 条` : (s.skipped ? '跳过' : '失败') }}
          </Badge>
          <span class="shrink-0 text-foreground">{{ s.display_name || s.name }}</span>
          <span class="min-w-0 flex-1 text-muted-foreground">{{ s.reason || s.error }}</span>
        </li>
      </ul>
    </Card>

    <p v-if="!searching && hasResults" class="mb-2 text-[11.5px] text-muted-foreground">
      共 {{ hits.length }} 条命中 · {{ groups.length }} 本
      <span v-if="hasMore">（还能继续加载）</span>
    </p>

    <Card v-if="searching" class="py-10 text-center text-[12.5px] text-muted-foreground">
      正在并发检索各书源…
    </Card>

    <!-- 结果：**一书一行**，多来源时展开逐个预览 / 下载（第 71 期） -->
    <Card v-else-if="hasResults" padding="none">
      <div v-for="g in groups" :key="g.key" class="border-b border-border last:border-b-0">
        <div class="flex items-center gap-3 px-4 py-3">
          <div class="min-w-0 flex-1">
            <div class="truncate text-[13px] font-medium text-foreground">
              {{ g.title || '（无书名）' }}
            </div>
            <div class="mt-0.5 flex flex-wrap items-center gap-1.5">
              <Badge v-for="s in sourcesOf(g)" :key="s" tone="accent">{{ sourceLabel(s) }}</Badge>
              <span v-if="g.author" class="truncate text-[11.5px] text-muted-foreground">{{ g.author }}</span>
            </div>
            <p v-if="taskText(g.hits[0])" class="mt-1 flex items-center gap-1.5">
              <Badge :tone="taskTone(g.hits[0])">{{ taskText(g.hits[0]) }}</Badge>
            </p>
          </div>
          <Button v-if="g.hits.length > 1" size="sm" variant="ghost" @click="toggle(g.key)">
            {{ expanded.has(g.key) ? '收起' : `${g.hits.length} 条来源` }}
          </Button>
          <!-- 展开后由每个来源行各带一对「预览 / 下载」：组行再摆一份就成了两个看起来
               一模一样的按钮（用户分不清点哪个），所以展开时收起组行这一对。 -->
          <template v-if="!expanded.has(g.key)">
            <Button size="sm" :disabled="!downloadEnabled" @click="openPreview(g.hits[0])">预览</Button>
            <Button
              size="sm"
              variant="primary"
              :disabled="!downloadEnabled || !!sending[hitKey(g.hits[0])]"
              :title="`从 ${sourceLabel(g.hits[0].source)} 下载`"
              @click="startDownload(g.hits[0])"
            >
              下载
            </Button>
          </template>
        </div>

        <div v-if="expanded.has(g.key)" class="bg-muted/40 px-4 py-2">
          <div
            v-for="h in g.hits"
            :key="hitKey(h)"
            class="flex items-center gap-3 py-1.5"
          >
            <Badge tone="neutral">{{ sourceLabel(h.source) }}</Badge>
            <span class="min-w-0 flex-1 truncate text-[11.5px] text-muted-foreground">{{ h.title }}</span>
            <Badge v-if="taskText(h)" :tone="taskTone(h)">{{ taskText(h) }}</Badge>
            <Button size="sm" variant="ghost" :disabled="!downloadEnabled" @click="openPreview(h)">预览</Button>
            <Button
              size="sm"
              variant="primary"
              :disabled="!downloadEnabled || !!sending[hitKey(h)]"
              @click="startDownload(h)"
            >
              下载
            </Button>
          </div>
        </div>
      </div>
    </Card>

    <div v-if="!searching && hasResults && hasMore" class="mt-3 text-center">
      <Button size="sm" :disabled="loadingMore" @click="loadMore()">
        {{ loadingMore ? '加载中…' : '加载更多' }}
      </Button>
      <p class="mt-1 text-[11px] text-muted-foreground">
        继续向各源取下一页（只追加，不覆盖已加载的结果）
      </p>
    </div>

    <EmptyState
      v-else-if="searched && !sourceStates.length"
      icon="alert"
      title="没有可用的书源"
      desc="书源表是空的，检索无从下手。到「设置 → 书源管理」添加一条规则书源，或启用内置的公版源。"
    />

    <EmptyState
      v-else-if="searched"
      icon="search"
      title="没有找到结果"
      :desc="
        srcFailed.length || srcSkipped.length
          ? '换个书名再试。上方逐源状态里有每个源的真实原因（失败原因 / 被跳过的原因），先看一眼是不是源本身的问题。'
          : '换个书名再试，或到「书源管理」确认书源是否已启用。'
      "
    />

    <EmptyState
      v-else
      icon="globe"
      title="开始检索"
      desc="输入书名后会并发查询全部已启用书源；同一本书在多个源命中时会合并成一行，可展开逐个来源下载。"
    />

    <!-- 预览弹窗 -->
    <div
      v-if="previewOpen"
      class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="explore-preview-title"
      @click.self="previewOpen = false"
    >
      <div class="w-[min(32rem,92vw)] rounded-lg border border-border bg-card p-5 shadow-2xl">
        <div class="mb-3 flex items-start gap-2">
          <h3 id="explore-preview-title" class="min-w-0 flex-1 font-serif text-[16px] font-semibold text-foreground">{{ previewTitle }}</h3>
          <button
            type="button"
            class="grid h-6 w-6 cursor-pointer place-items-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="关闭预览"
            @click="previewOpen = false"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" class="h-3.5 w-3.5">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div class="max-h-[55vh] overflow-y-auto text-[12.5px] leading-relaxed text-muted-foreground">
          <p v-if="previewLoading">加载中…</p>
          <p v-else-if="previewError" class="text-warning">{{ previewError }}</p>
          <template v-else>
            <p v-if="previewAuthor">作者：{{ previewAuthor }}</p>
            <p v-if="previewToc.length" :class="previewAuthor ? 'mt-1' : ''">共 {{ previewToc.length }} 章</p>
            <ol v-if="previewToc.length" class="mt-2 list-decimal pl-5">
              <li v-for="(t, i) in previewToc.slice(0, 20)" :key="i" class="truncate">{{ t }}</li>
            </ol>
            <p v-if="previewToc.length > 20" class="mt-1 text-[11px]">（目录只列前 20 章）</p>
            <p v-if="previewSample" class="mt-3 whitespace-pre-wrap border-t border-border pt-3">{{ previewSample }}</p>
            <p v-if="!previewToc.length && !previewSample">
              这个源没有给出可预览的内容（目录与首段都是空的），可以下载后直接在阅读器里看。
            </p>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
