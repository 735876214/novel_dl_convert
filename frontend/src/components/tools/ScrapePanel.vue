<script setup lang="ts">
/**
 * 刮削出版面板（转换日志页 → 「刮削」子标签，第 18 期）。
 *
 * 版面顺序按**用户的疑问顺序**排，而不是按数据结构排：
 *   1. 刮到哪了？   → 概览条（计数 + 进度 + worker 状态）
 *   2. 结果对不对？ → 结果表（源 → 副本、模式、已写字段、失败原因）
 *   3. 出问题怎么办？→ 处置按钮（待确认三选一）/ 整理抽屉（改元数据并重建）
 *   4. 副本叫什么？ → 命名规则区块（第 28 期由「批量重命名」并入：规则 + 预览 + 一键重出版）
 *
 * 三条与后端约定一致的界面规则（不要"优化"掉）：
 *   · 轮询**只在有进行中 / 待刮削条目时**开启（沿用 tasks store 的 2.5s 范式）；
 *   · 「待确认」是**降级状态**：界面只提供按钮，绝不自动删源、绝不自动重建；
 *   · 删除原文件必须二次确认 —— 弹窗里列出**将移入回收站的实际路径**，
 *     并明确它是移动而非抹除（后端走 CACHE_DIR/recycle）。
 */
import { computed, onActivated, onDeactivated, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import Segment from '@/components/ui/Segment.vue'
import ScrapeFixDrawer from '@/components/tools/ScrapeFixDrawer.vue'
import { RENAME_SCOPES, RENAME_TOKENS } from '@/data/settingsFields'
import {
  api,
  type NamingPlan,
  type ScrapeAction,
  type ScrapeItem,
  type ScrapeState,
} from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const library = useLibraryStore()

const POLL_MS = 2500

const data = ref<ScrapeState | null>(null)
const loading = ref(false)
const busy = ref('')
/**
 * 默认「全部书库」而**不**继承侧栏的当前库：刮削是**全局运维视图**
 * （与同页的「日志」标签一致）。继承当前库会出现「明明刮过书，切进来却是空的」
 * ——上一轮实测就踩了这个（继承到有声书库 → 0 条 + 空状态）。
 */
const libId = ref('')
const status = ref('')
const keyword = ref('')
const modeFilter = ref('')
const picked = ref<string[]>([])
const fixFor = ref<ScrapeItem | null>(null)
/** 待确认的「删除原文件」目标（弹窗里的二次确认） */
const confirmDel = ref<ScrapeItem | null>(null)
const confirmAck = ref(false)

// ---------------- 命名规则（第 28 期：批量重命名并入本面板） ----------------
/**
 * 规则只有**一份**（`naming.pattern` / `naming.scope`），生效值 = 每库覆写 ?? 全局。
 * 本面板：选定某个库时可改**该库覆写**；「全部书库」时只读展示全局规则 ——
 * 全局规则只有「设置 → 文件命名」一个写点，两个地方都能改会让「生效值」说不清。
 *
 * 「预览 == 落盘」靠两件事保证：预览与重出版都由服务端算，且**重出版前不允许
 * 有未保存的草稿**（否则预览用草稿、落盘用保存值，两边说的不是一件事）。
 */
const naming = ref({ pattern: '', scope: 'all' })
const namingSaved = ref({ pattern: '', scope: 'all' })
const namingOverridden = ref(false)
/** 该库类型有没有「命名规则」能力（后端 schema 已按能力收窄，缺键即没有） */
const namingEditable = ref(false)
const namingNote = ref('')
const namingLoading = ref(false)
const namingPlan = ref<NamingPlan | null>(null)
const namingBusy = ref('')

const namingDirty = computed(
  () =>
    naming.value.pattern !== namingSaved.value.pattern ||
    naming.value.scope !== namingSaved.value.scope,
)

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'pending,running', label: '待办' },
  { value: 'removed,orphan', label: '待确认' },
  { value: 'failed', label: '失败' },
  { value: 'ok', label: '已出版' },
]

const items = computed(() => {
  const list = data.value?.items ?? []
  if (!modeFilter.value) return list
  return list.filter((i) => (i.link_mode || '') === modeFilter.value)
})

const degraded = computed(() => items.value.filter((i) => i.degraded))
const pickedItems = computed(() => items.value.filter((i) => picked.value.includes(i.book_id)))

function load(silent = false): void {
  if (!silent) loading.value = true
  api
    .scrapeState({ library_id: libId.value, status: status.value, q: keyword.value })
    .then((r) => {
      data.value = r
      // 勾选集合按当前列表收敛，避免翻筛选后带着看不见的选中项去批量操作
      picked.value = picked.value.filter((id) => r.items.some((i) => i.book_id === id))
      syncPoll()
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      loading.value = false
    })
}

// ---------------- 轮询：只在有活干时开 ----------------
let timer: ReturnType<typeof setInterval> | null = null

function syncPoll(): void {
  // ⚠️ 用 busy 而不是 running：worker 线程起来后常驻（running 几乎永远是 true），
  // 拿它当条件会让轮询永远停不下来。
  const active = (data.value?.pending ?? 0) > 0 || !!data.value?.worker.busy
  if (active && !timer) timer = setInterval(() => load(true), POLL_MS)
  else if (!active && timer) {
    clearInterval(timer)
    timer = null
  }
}

/** 概览条右侧的状态文案：空闲 / 排队中 N 本 / 正在刮削《书名》 */
const workerText = computed(() => {
  const w = data.value?.worker
  if (w?.current) return `正在刮削：${w.current}`
  const n = data.value?.pending ?? 0
  return n > 0 ? `队列中 ${n} 本` : '空闲'
})

function stopPoll(): void {
  if (timer) clearInterval(timer)
  timer = null
}

/**
 * ⚠️ 本组件**不是**路由子页，而是被切换的 `v-if` 子组件（比 ToolsLayout 的
 * KeepAlive 深两层），所以**首次挂载时 onActivated 并不可靠**（实测不触发 →
 * 面板停在 0 条）。首次加载一律挂 onMounted。
 */
onMounted(() => {
  void library.loadLibraries(true)
  load()
  loadNaming()
})

/**
 * 工具页被重新激活（切走再切回）时刷新一次 + 恢复轮询。
 * 首次挂载时 data 还是 null（请求在飞），因此这里天然不会重复发请求。
 */
onActivated(() => {
  if (data.value) load(true)
  if (!namingLoading.value) loadNaming()
})

onDeactivated(stopPoll)

// ---------------- 操作 ----------------
async function run(opts: { force?: boolean; only_failed?: boolean } = {}): Promise<void> {
  busy.value = opts.only_failed ? 'retry' : 'run'
  try {
    const res = await api.scrapeRun({
      library_id: libId.value,
      force: !!opts.force,
      only_failed: !!opts.only_failed,
    })
    ui.toast(
      res.queued
        ? `已排队 ${res.queued} / 共 ${res.total} 本，后台串行刮削中`
        : `没有需要处理的条目（共 ${res.total} 本）`,
    )
    load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '启动失败')
  } finally {
    busy.value = ''
  }
}

async function verify(): Promise<void> {
  busy.value = 'verify'
  try {
    const r = await api.scrapeVerify(libId.value)
    if (r.removed.length) {
      ui.toast(`发现 ${r.removed.length} 个副本已被删除，已列为待确认（原文件未动）`)
    } else if (r.orphan.length) {
      ui.toast(`发现 ${r.orphan.length} 本原文件已不在，副本成了孤本`)
    } else {
      ui.toast(`校验完成：${r.checked} 本，副本都在`)
    }
    load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '校验失败')
  } finally {
    busy.value = ''
  }
}

/** 执行某个显式处置。删除类动作必须已在弹窗里确认过。 */
async function resolve(item: ScrapeItem, action: ScrapeAction): Promise<void> {
  busy.value = `resolve:${item.book_id}`
  try {
    const r = await api.scrapeResolve(item.book_id, action)
    const text: Record<string, string> = {
      delete_source: '原文件已移入回收站（可在回收目录找回）',
      keep_source: '已保留原文件，不再提醒',
      rebuild: '副本已重建，外部阅读器可以读到了',
      keep_copy: '已保留副本（原文件已不在）',
      recycle_copy: '副本已移入回收站',
    }
    ui.toast(r.note ? `${text[action] ?? '已处理'} · ${r.note}` : text[action] ?? '已处理')
    load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '处置失败')
  } finally {
    busy.value = ''
  }
}

function askDelete(item: ScrapeItem): void {
  confirmDel.value = item
  confirmAck.value = false
}

async function doDelete(): Promise<void> {
  const item = confirmDel.value
  if (!item || !confirmAck.value) return
  confirmDel.value = null
  await resolve(item, 'delete_source')
}

/** 批量：只允许「保留 / 重建」这类**不破坏数据**的动作，不提供一键删全部原文件。 */
async function batch(action: 'keep_source' | 'rebuild'): Promise<void> {
  const targets = pickedItems.value.filter((i) => i.actions.includes(action))
  if (!targets.length) {
    ui.toast('选中的条目没有可执行该动作的')
    return
  }
  busy.value = `batch:${action}`
  try {
    for (const it of targets) await api.scrapeResolve(it.book_id, action)
    ui.toast(`已处理 ${targets.length} 本`)
    picked.value = []
    load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '批量处理失败')
  } finally {
    busy.value = ''
  }
}

function togglePick(id: string): void {
  const i = picked.value.indexOf(id)
  if (i >= 0) picked.value.splice(i, 1)
  else picked.value.push(id)
}

// ---------------- 命名规则：读 / 存 / 预览 / 重出版 ----------------

/** 读该库的生效规则（或「全部书库」时的全局值）。换库后旧预览不再成立，一并作废。 */
function loadNaming(): void {
  namingPlan.value = null
  const setValues = (pattern: unknown, scope: unknown) => {
    naming.value = { pattern: String(pattern ?? ''), scope: String(scope ?? 'all') }
    namingSaved.value = { ...naming.value }
  }

  if (!libId.value) {
    namingEditable.value = false
    namingOverridden.value = false
    namingNote.value =
      '「全部书库」范围下只读展示全局规则。选定一个书库后，可在此改该库的覆写并一键重出版。'
    namingLoading.value = true
    api
      .getConfig()
      .then((r) => setValues(r.config.naming?.pattern, r.config.naming?.scope))
      .catch((e: Error) => ui.toast(e.message))
      .finally(() => {
        namingLoading.value = false
      })
    return
  }

  namingLoading.value = true
  api
    .librarySettings(libId.value)
    .then((r) => {
      // schema 已按该库类型的能力收窄：没有 naming.pattern 就是这类库没有命名规则能力
      namingEditable.value = r.schema.some((s) => s.key === 'naming.pattern')
      namingNote.value = namingEditable.value
        ? ''
        : '该库类型没有「命名规则」能力（成品副本只对电子书 / 漫画库有意义），这里只展示生效值。'
      namingOverridden.value = !!r.overridden['naming.pattern'] || !!r.overridden['naming.scope']
      setValues(r.values['naming.pattern'], r.values['naming.scope'])
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      namingLoading.value = false
    })
}

function onLibChange(): void {
  loadNaming()
  load()
}

async function saveNaming(): Promise<void> {
  if (!libId.value || !namingEditable.value) return
  if (!naming.value.pattern.trim()) {
    ui.toast('命名规则不能为空')
    return
  }
  namingBusy.value = 'save'
  try {
    // 复用每库覆写的**唯一写入口**（与「书库管理 → 设置」同一路径），不新开写点
    await api.librarySettingsUpdate(libId.value, {
      'naming.pattern': naming.value.pattern.trim(),
      'naming.scope': naming.value.scope,
    })
    ui.toast('已保存到该库（只影响这个库的副本名）')
    loadNaming()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    namingBusy.value = ''
  }
}

async function resetNaming(): Promise<void> {
  if (!libId.value) return
  namingBusy.value = 'reset'
  try {
    await api.librarySettingsReset(libId.value, ['naming.pattern', 'naming.scope'])
    ui.toast('已改回跟随全局规则')
    loadNaming()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '恢复失败')
  } finally {
    namingBusy.value = ''
  }
}

/** 预览「当前副本名 → 新副本名」。传草稿而非保存值：所见即所得（保不保存由用户定）。 */
async function previewNaming(): Promise<void> {
  if (!libId.value) {
    ui.toast('先在上面选一个书库')
    return
  }
  namingBusy.value = 'preview'
  try {
    namingPlan.value = await api.namingPreview({
      libraryId: libId.value,
      pattern: naming.value.pattern,
      scope: naming.value.scope,
    })
    if (!namingPlan.value.items.length) ui.toast('该库还没有已出版的副本')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '预览失败')
  } finally {
    namingBusy.value = ''
  }
}

/**
 * 按规则重出版。后端用**已保存**的规则重算目标，所以这里拒绝在有草稿时执行
 * （否则「预览按草稿、落盘按保存值」，正是本期要消灭的那种不一致）。
 */
async function applyNaming(): Promise<void> {
  if (!namingPlan.value) return
  if (namingDirty.value) {
    ui.toast('规则有未保存的改动：先「保存到本库」再重出版')
    return
  }
  namingBusy.value = 'apply'
  try {
    const r = await api.namingApply({ libraryId: libId.value })
    ui.toast(
      r.failed
        ? `重出版完成：成功 ${r.done} / 共 ${r.total}，${r.failed} 本失败`
        : `已按规则重出版 ${r.done} 本${r.skipped ? `，跳过 ${r.skipped} 本（名字未变或落点冲突）` : ''}`,
    )
    loadNaming()
    load(true) // 结果表的「副本」列也跟着变了，静默刷新一次
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '重出版失败')
  } finally {
    namingBusy.value = ''
  }
}

function toggleAll(): void {
  picked.value = picked.value.length === degraded.value.length
    ? []
    : degraded.value.map((i) => i.book_id)
}

// ---------------- 展示辅助 ----------------
function tone(st: string): 'ok' | 'warn' | 'err' | 'accent' | 'neutral' {
  if (st === 'ok') return 'ok'
  if (st === 'failed') return 'err'
  if (st === 'removed' || st === 'orphan') return 'warn'
  if (st === 'running') return 'accent'
  return 'neutral'
}

/**
 * 能否进「整理抽屉」（改元数据 → 重建副本）。
 *
 * 排除三类：降级待确认（要先在上面的三按钮里拿定主意）、进行中、
 * 以及**原文件已被确认回收**（没有源可出版，进去只会白跑一趟）。
 */
function canFix(it: ScrapeItem): boolean {
  return !it.degraded && it.status !== 'running' && it.status !== 'source_removed'
}

function when(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

const done = computed(() => {
  const c = data.value?.counts ?? {}
  return (c.ok ?? 0) + (c.failed ?? 0) + (c.skipped ?? 0)
})
const percent = computed(() =>
  data.value?.total ? Math.round((done.value / data.value.total) * 100) : 0,
)

const chip = computed(() => {
  const c = data.value?.counts ?? {}
  return [
    { key: 'pending', label: '待刮削', n: c.pending ?? 0, cls: 'text-muted-foreground' },
    { key: 'running', label: '进行中', n: c.running ?? 0, cls: 'text-info' },
    { key: 'ok', label: '已出版', n: c.ok ?? 0, cls: 'text-success' },
    { key: 'failed', label: '失败', n: c.failed ?? 0, cls: 'text-destructive' },
    { key: 'confirm', label: '待确认', n: data.value?.needs_confirm ?? 0, cls: 'text-warning' },
    { key: 'skipped', label: '跳过', n: c.skipped ?? 0, cls: 'text-muted-foreground' },
  ]
})

function pickConfirm(): void {
  status.value = 'removed,orphan'
  load()
}
</script>

<template>
  <div>
    <!-- ① 概览条 -->
    <Card class="mb-3" padding="sm">
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div class="flex flex-wrap items-center gap-2.5">
          <button
            v-for="c in chip"
            :key="c.key"
            type="button"
            class="flex cursor-pointer items-baseline gap-1 rounded-md px-1.5 py-0.5 transition-colors hover:bg-muted"
            :class="c.key === 'confirm' && c.n ? 'ring-1 ring-warning/40' : ''"
            :title="c.key === 'confirm' ? '点击只看待确认' : c.label"
            @click="c.key === 'confirm' ? pickConfirm() : (status = '', load())"
          >
            <span class="text-[15px] font-semibold tabular-nums" :class="c.cls">{{ c.n }}</span>
            <span class="text-[11.5px] text-muted-foreground">{{ c.label }}</span>
          </button>
        </div>

        <div class="ml-auto flex flex-wrap items-center gap-1.5">
          <div class="mr-1 hidden items-center gap-1.5 sm:flex">
            <span
              class="h-1.5 w-1.5 rounded-full"
              :class="data?.worker.busy ? 'animate-pulse bg-info' : 'bg-border'"
            />
            <span class="max-w-[14rem] truncate text-[11px] text-muted-foreground">
              {{ workerText }}
            </span>
          </div>
          <Button size="sm" variant="primary" :disabled="!!busy" @click="run()">
            {{ busy === 'run' ? '排队中…' : '开始刮削' }}
          </Button>
          <Button size="sm" :disabled="!!busy" @click="run({ only_failed: true })">
            {{ busy === 'retry' ? '排队中…' : '重试失败' }}
          </Button>
          <Button
            size="sm"
            :disabled="!!busy"
            title="忽略「已是最新」判断，重新抓取并重建副本"
            @click="run({ force: true })"
          >
            强制重刮
          </Button>
          <Button size="sm" :disabled="!!busy" @click="verify">
            {{ busy === 'verify' ? '校验中…' : '刷新状态' }}
          </Button>
        </div>
      </div>

      <!-- 进度：只反映「已处理 / 总数」，进行中用脉冲条表示不确定进度（不伪造百分比） -->
      <div class="mt-3 flex items-center gap-2">
        <div class="h-1 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            class="h-full rounded-full bg-primary/70 transition-[width] duration-500"
            :class="data?.worker.running ? 'animate-pulse' : ''"
            :style="{ width: `${percent}%` }"
          />
        </div>
        <span class="text-[11px] text-muted-foreground tabular-nums">
          {{ done }} / {{ data?.total ?? 0 }}
        </span>
      </div>

      <div
        v-if="data && !data.auto_enabled"
        class="mt-2 flex items-center gap-1 text-[11px] text-muted-foreground"
      >
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        该库的「刮削出版」开关是关的：新书入库不会自动刮，只能在这里手动跑。
      </div>
    </Card>

    <!-- ② 筛选行 -->
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <select
        v-model="libId"
        aria-label="按书库筛选"
        class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
        @change="onLibChange()"
      >
        <option value="">全部书库</option>
        <option v-for="l in library.libraryEntities" :key="l.id" :value="l.id">
          {{ l.name }}
        </option>
      </select>

      <Segment v-model="status" :options="STATUS_OPTIONS" />
      <Button size="sm" :disabled="loading" @click="load()">刷新</Button>

      <select
        v-model="modeFilter"
        aria-label="按副本模式筛选"
        class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
      >
        <option value="">全部模式</option>
        <option value="hardlink">硬链接</option>
        <option value="copy">复制</option>
      </select>

      <input
        v-model="keyword"
        type="text"
        placeholder="按书名 / 作者筛选…"
        aria-label="刮削关键词"
        class="h-8 w-56 rounded-md border border-border bg-muted px-3 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        @keydown.enter="load()"
      />
    </div>

    <!-- ②′ 命名规则：改名只剩「按规则重出版副本」这一条路（第 28 期并入本面板） -->
    <Card class="mb-3">
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="text-[13px] font-semibold text-foreground">命名规则（副本名）</h3>
        <Badge v-if="namingOverridden" tone="accent">本库已覆盖</Badge>
        <span class="text-[11.5px] text-muted-foreground">
          只改成品目录里的<strong>副本名</strong>，源文件名与书库数据永不改动
        </span>
        <span v-if="namingLoading" class="ml-auto text-[11px] text-muted-foreground">读取中…</span>
      </div>

      <p v-if="namingNote" class="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        {{ namingNote }}
        <RouterLink
          v-if="!libId"
          to="/settings/library/file-naming"
          class="underline"
        >
          去「设置 → 文件命名」修改全局规则
        </RouterLink>
      </p>

      <div class="mt-2.5 flex flex-wrap items-center gap-2">
        <input
          v-model="naming.pattern"
          type="text"
          :disabled="!namingEditable"
          placeholder="{index}. {author} - {title}"
          aria-label="命名规则"
          class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-3 font-mono text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card disabled:opacity-60"
          @input="namingPlan = null"
          @keydown.enter="previewNaming"
        >
        <select
          v-model="naming.scope"
          :disabled="!namingEditable"
          aria-label="格式筛选"
          class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring disabled:opacity-60"
          @change="namingPlan = null"
        >
          <option v-for="s in RENAME_SCOPES" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
        <Button
          v-if="namingEditable"
          size="sm"
          variant="primary"
          :disabled="!!namingBusy || !namingDirty"
          @click="saveNaming"
        >
          {{ namingBusy === 'save' ? '保存中…' : '保存到本库' }}
        </Button>
        <Button
          v-if="namingEditable && namingOverridden"
          size="sm"
          :disabled="!!namingBusy"
          @click="resetNaming"
        >
          跟随全局
        </Button>
        <Button v-if="libId" size="sm" :disabled="!!namingBusy" @click="previewNaming">
          {{ namingBusy === 'preview' ? '预览中…' : '预览效果' }}
        </Button>
      </div>

      <p class="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        占位符：
        <code
          v-for="t in RENAME_TOKENS"
          :key="t.token"
          class="mr-1.5 font-mono text-foreground"
          :title="t.desc"
        >{{ t.token }}</code>
        （扩展名自动保留在末尾）
      </p>

      <!-- 预览：现名 → 新名。冲突项单独标出且**不进批量**（不让服务端的「(2)」兜底改掉结论） -->
      <div v-if="namingPlan" class="mt-3 rounded-md border border-border">
        <div
          class="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border px-3 py-2 text-[11.5px] text-muted-foreground"
        >
          <span>
            已出版 <span class="tabular-nums">{{ namingPlan.stats.total }}</span> 本 · 会改名
            <span class="font-semibold text-foreground tabular-nums">{{ namingPlan.stats.changed }}</span> 本
          </span>
          <span v-if="namingPlan.stats.conflict" class="text-destructive">
            {{ namingPlan.stats.conflict }} 本落点冲突，需人工处理
          </span>
          <span class="ml-auto max-w-[18rem] truncate font-mono text-[11px]" :title="namingPlan.pattern">
            {{ namingPlan.pattern }}
          </span>
        </div>

        <div v-if="namingPlan.items.length" class="max-h-64 overflow-y-auto">
          <div
            v-for="p in namingPlan.items"
            :key="p.book_id"
            class="flex flex-wrap items-center gap-2 border-b border-border/60 px-3 py-1.5 text-[12px] last:border-b-0"
            :class="p.conflict || !p.changed ? 'opacity-55' : ''"
          >
            <span class="min-w-0 flex-1 truncate text-muted-foreground" :title="p.old_rel">
              {{ p.old_rel }}
            </span>
            <Icon name="arrowRight" class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span
              class="min-w-0 flex-1 truncate font-medium"
              :class="p.conflict ? 'text-destructive' : 'text-foreground'"
              :title="p.new_rel"
            >
              {{ p.new_rel }}
            </span>
            <Badge v-if="p.conflict" tone="err">冲突</Badge>
            <Badge v-else-if="!p.changed" tone="neutral">不变</Badge>
            <span v-if="p.conflict" class="w-full text-[10.5px] text-destructive">
              {{ p.reason }}
            </span>
          </div>
        </div>
        <p v-else class="px-3 py-4 text-[11.5px] text-muted-foreground">
          该库还没有已出版的副本。先在上面「开始刮削」出版一次，再回来按规则重出版。
        </p>

        <div class="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
          <Button
            size="sm"
            variant="primary"
            :disabled="!!namingBusy || !namingPlan.stats.ready || namingDirty"
            @click="applyNaming"
          >
            {{
              namingBusy === 'apply'
                ? '重出版中…'
                : `按此规则重出版（${namingPlan.stats.ready} 本）`
            }}
          </Button>
          <span class="text-[11px] leading-relaxed text-muted-foreground">
            <template v-if="namingDirty">
              规则有未保存的改动：先「保存到本库」，预览与落盘才是同一份规则。
            </template>
            <template v-else>
              旧副本会移入回收目录（不留双份），源文件不受影响；整个过程不外呼。
            </template>
          </span>
        </div>
      </div>
    </Card>

    <!-- 批量条：只给「不破坏数据」的动作 -->
    <div
      v-if="picked.length"
      class="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted px-3 py-2"
    >
      <span class="text-[12px] text-foreground">已选 {{ picked.length }} 本</span>
      <Button size="sm" :disabled="!!busy" @click="batch('keep_source')">批量保留原文件</Button>
      <Button size="sm" :disabled="!!busy" @click="batch('rebuild')">批量重新生成副本</Button>
      <span class="text-[11px] text-muted-foreground">
        删除原文件不提供批量（避免一次误删一片），请逐本确认。
      </span>
      <Button size="sm" variant="ghost" class="ml-auto" @click="picked = []">取消选择</Button>
    </div>

    <Card v-if="loading && !items.length" class="py-10 text-center text-[12.5px] text-muted-foreground">
      加载中…
    </Card>

    <Card v-else-if="items.length" padding="none">
      <div class="hidden overflow-x-auto md:block">
        <table class="w-full min-w-[58rem] border-collapse text-left">
          <thead>
            <tr class="border-b border-border">
              <th class="w-8 px-3 py-2.5">
                <input
                  v-if="degraded.length"
                  type="checkbox"
                  aria-label="全选待确认"
                  :checked="picked.length > 0 && picked.length === degraded.length"
                  @change="toggleAll"
                />
              </th>
              <th class="px-3 py-2.5 text-[11px] font-semibold text-muted-foreground">书名 / 作者</th>
              <th class="px-3 py-2.5 text-[11px] font-semibold text-muted-foreground">状态</th>
              <th class="px-3 py-2.5 text-[11px] font-semibold text-muted-foreground">副本</th>
              <th class="hidden px-3 py-2.5 text-[11px] font-semibold text-muted-foreground lg:table-cell">
                已写字段
              </th>
              <th class="hidden px-3 py-2.5 text-[11px] font-semibold text-muted-foreground xl:table-cell">
                时间
              </th>
              <th class="px-3 py-2.5 text-right text-[11px] font-semibold text-muted-foreground">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="it in items"
              :key="it.book_id"
              class="border-b border-border/60 align-top transition-colors last:border-b-0 hover:bg-muted/50"
              :class="
                it.degraded
                  ? 'bg-warning/5'
                  : it.status === 'failed'
                    ? 'bg-destructive/5'
                    : ''
              "
            >
              <td class="px-3 py-2.5">
                <input
                  v-if="it.degraded"
                  type="checkbox"
                  :aria-label="`选择 ${it.title}`"
                  :checked="picked.includes(it.book_id)"
                  @change="togglePick(it.book_id)"
                />
              </td>
              <td class="max-w-[20rem] px-3 py-2.5">
                <div class="truncate text-[12.5px] text-foreground" :title="it.title">
                  <!-- 进行中的行左侧三点脉冲：表达「在做，但不知道还要多久」 -->
                  <span
                    v-if="it.status === 'running'"
                    class="mr-1.5 inline-flex align-middle gap-0.5"
                    aria-hidden="true"
                  >
                    <span class="h-1 w-1 animate-pulse rounded-full bg-info" />
                    <span class="h-1 w-1 animate-pulse rounded-full bg-info [animation-delay:150ms]" />
                    <span class="h-1 w-1 animate-pulse rounded-full bg-info [animation-delay:300ms]" />
                  </span>
                  {{ it.title }}
                </div>
                <div class="truncate text-[11px] text-muted-foreground">
                  {{ it.author || '未知作者' }}
                  <span v-if="it.library_name"> · {{ it.library_name }}</span>
                </div>
                <!-- 源 → 副本：这一行的存在意义就是让用户看清「改的是副本，不是原文件」 -->
                <div class="mt-1 flex items-start gap-1 text-[10.5px] text-muted-foreground/80">
                  <Icon name="book" class="mt-0.5 h-3 w-3 shrink-0" />
                  <span class="min-w-0 flex-1 truncate" :title="it.source_path">{{ it.name }}</span>
                  <Icon name="arrowRight" class="mt-0.5 h-3 w-3 shrink-0" />
                  <span class="min-w-0 flex-1 truncate" :title="it.copy_path">
                    {{ it.link_rel || '（未产出副本）' }}
                  </span>
                </div>
              </td>
              <td class="px-3 py-2.5">
                <Badge :tone="tone(it.status)">{{ it.status_label }}</Badge>
                <div v-if="it.error" class="mt-1 max-w-[16rem] text-[10.5px] text-destructive">
                  {{ it.error }}
                </div>
              </td>
              <td class="px-3 py-2.5">
                <div v-if="it.link_mode" class="flex flex-wrap items-center gap-1">
                  <Badge>{{ it.link_mode === 'hardlink' ? '硬链接' : '复制' }}</Badge>
                  <!-- 写入元数据必须替换目录项，副本因此不再与源共享数据块：如实标注 -->
                  <Badge v-if="it.link_mode === 'hardlink' && !it.shared" tone="warn">独立占用</Badge>
                  <Badge v-if="it.has_cover" tone="ok">封面</Badge>
                  <span v-if="it.attempts > 1" class="text-[10.5px] text-muted-foreground">
                    第 {{ it.attempts }} 次
                  </span>
                </div>
                <span v-else class="text-[11.5px] text-muted-foreground">—</span>
              </td>
              <td class="hidden max-w-[14rem] px-3 py-2.5 lg:table-cell">
                <div class="flex flex-wrap gap-1">
                  <Badge v-for="f in it.embedded" :key="f">{{ f }}</Badge>
                  <span v-if="!it.embedded.length" class="text-[11.5px] text-muted-foreground">—</span>
                </div>
              </td>
              <td class="hidden px-3 py-2.5 text-[11px] whitespace-nowrap text-muted-foreground tabular-nums xl:table-cell">
                {{ when(it.status === 'removed' ? it.removed_at : it.updated_at) }}
              </td>
              <td class="px-3 py-2.5">
                <div class="flex flex-wrap justify-end gap-1">
                  <template v-if="it.status === 'removed'">
                    <Button size="sm" :disabled="!!busy" @click="resolve(it, 'keep_source')">
                      保留原文件
                    </Button>
                    <Button size="sm" variant="danger" :disabled="!!busy" @click="askDelete(it)">
                      删除原文件
                    </Button>
                  </template>
                  <template v-else-if="it.status === 'orphan'">
                    <Button size="sm" :disabled="!!busy" @click="resolve(it, 'keep_copy')">
                      保留副本
                    </Button>
                    <Button size="sm" variant="danger" :disabled="!!busy" @click="resolve(it, 'recycle_copy')">
                      清理副本
                    </Button>
                  </template>
                  <Button
                    v-if="it.actions.includes('rebuild')"
                    size="sm"
                    :disabled="!!busy"
                    title="按当前服务端元数据重写副本（不外呼）"
                    @click="resolve(it, 'rebuild')"
                  >
                    重新生成副本
                  </Button>
                  <!-- 源文件已按确认移入回收站的书**不给整理入口**：没有源就没法出版，
                       点进去只会白跑一趟（publish 会以「源不是普通文件」跳过） -->
                  <Button
                    v-if="canFix(it)"
                    size="sm"
                    variant="ghost"
                    @click="fixFor = it"
                  >
                    整理
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 窄屏：七列表格横向滚动会读不出来，退化成卡片流（信息不裁剪，只换排布） -->
      <ul class="divide-y divide-border md:hidden">
        <li
          v-for="it in items"
          :key="`m-${it.book_id}`"
          class="px-3 py-3"
          :class="it.degraded ? 'bg-warning/5' : it.status === 'failed' ? 'bg-destructive/5' : ''"
        >
          <div class="flex items-start gap-2">
            <input
              v-if="it.degraded"
              type="checkbox"
              class="mt-1"
              :aria-label="`选择 ${it.title}`"
              :checked="picked.includes(it.book_id)"
              @change="togglePick(it.book_id)"
            >
            <div class="min-w-0 flex-1">
              <div class="truncate text-[12.5px] text-foreground">{{ it.title }}</div>
              <div class="truncate text-[11px] text-muted-foreground">
                {{ it.author || '未知作者' }} · {{ it.library_name }}
              </div>
            </div>
            <Badge :tone="tone(it.status)">{{ it.status_label }}</Badge>
          </div>

          <div class="mt-1.5 flex flex-wrap items-center gap-1">
            <Badge v-if="it.link_mode">{{ it.link_mode === 'hardlink' ? '硬链接' : '复制' }}</Badge>
            <Badge v-if="it.link_mode === 'hardlink' && !it.shared" tone="warn">独立占用</Badge>
            <Badge v-if="it.has_cover" tone="ok">封面</Badge>
            <Badge v-for="f in it.embedded" :key="`m-${it.book_id}-${f}`">{{ f }}</Badge>
            <span class="text-[10.5px] text-muted-foreground">{{ when(it.updated_at) }}</span>
          </div>

          <div class="mt-1 truncate text-[10.5px] text-muted-foreground" :title="it.copy_path">
            {{ it.name }} → {{ it.link_rel || '（未产出副本）' }}
          </div>
          <div v-if="it.error" class="mt-1 text-[10.5px] text-destructive">{{ it.error }}</div>

          <div class="mt-2 flex flex-wrap gap-1">
            <template v-if="it.status === 'removed'">
              <Button size="sm" :disabled="!!busy" @click="resolve(it, 'keep_source')">保留原文件</Button>
              <Button size="sm" variant="danger" :disabled="!!busy" @click="askDelete(it)">删除原文件</Button>
            </template>
            <template v-else-if="it.status === 'orphan'">
              <Button size="sm" :disabled="!!busy" @click="resolve(it, 'keep_copy')">保留副本</Button>
              <Button size="sm" variant="danger" :disabled="!!busy" @click="resolve(it, 'recycle_copy')">
                清理副本
              </Button>
            </template>
            <Button
              v-if="it.actions.includes('rebuild')"
              size="sm"
              :disabled="!!busy"
              @click="resolve(it, 'rebuild')"
            >
              重新生成副本
            </Button>
            <Button v-if="canFix(it)" size="sm" variant="ghost" @click="fixFor = it">整理</Button>
          </div>
        </li>
      </ul>
    </Card>

    <!-- 空状态分两种：没配成品目录（要先去做配置） vs 配了但还没刮（点一下就行） -->
    <EmptyState
      v-else-if="data && !data.publish_configured"
      icon="alert"
      title="还没设置成品目录"
      desc="刮削会把抓到的元数据写进成品目录里的硬链接副本（原书文件保持原样），外部阅读器挂载该目录即可读到整理完成的书。请先到「书库管理」为该库设置成品目录。"
    />

    <EmptyState
      v-else
      icon="layers"
      title="暂无刮削记录"
      desc="成品目录已就绪，但还没有刮削记录。点上方「开始刮削」把书目排进队列（或点「强制重刮」忽略「已是最新」判断重跑一遍）。"
    />

    <!-- ③ 整理抽屉：改元数据 → 应用并重建副本 -->
    <ScrapeFixDrawer
      v-if="fixFor"
      :item="fixFor"
      @close="fixFor = null"
      @applied="fixFor = null; load()"
    />

    <!-- ④ 删除原文件：二次确认（列出将移入回收站的路径） -->
    <div
      v-if="confirmDel"
      class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4"
      @click.self="confirmDel = null"
    >
      <div class="w-[min(32rem,94vw)] rounded-lg border border-border bg-card p-5 shadow-2xl">
        <h3 class="flex items-center gap-1.5 text-[15px] font-semibold text-foreground">
          <Icon name="alert" class="h-4 w-4 text-destructive" />
          删除原文件？
        </h3>
        <p class="mt-2 text-[12.5px] text-muted-foreground">
          副本已被删除，你要连<strong>原文件</strong>一起处理吗？确认后原文件会<strong>移入回收目录</strong>
          （不是抹除，可在回收目录找回），已出版的副本不受影响。
        </p>
        <div class="mt-3 rounded-md border border-border bg-muted px-3 py-2">
          <div class="text-[11px] text-muted-foreground">将移入回收站：</div>
          <div class="mt-0.5 text-[12px] break-all text-foreground">{{ confirmDel.source_path }}</div>
          <div class="mt-2 text-[11px] text-muted-foreground">已删除的副本：</div>
          <div class="mt-0.5 text-[12px] break-all text-muted-foreground">
            {{ confirmDel.removed_path || confirmDel.copy_path }}
          </div>
        </div>
        <label class="mt-3 flex items-center gap-2 text-[12px] text-foreground">
          <input v-model="confirmAck" type="checkbox" />
          我已知晓原文件将被移入回收站
        </label>
        <div class="mt-4 flex justify-end gap-2">
          <Button size="sm" variant="ghost" @click="confirmDel = null">取消</Button>
          <Button size="sm" variant="danger" :disabled="!confirmAck" @click="doDelete">
            移入回收站
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
