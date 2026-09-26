<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import {
  api,
  type BookDockItem,
  type BookDockResponse,
  type HealthInfo,
  type WatcherStatus,
} from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useLibraryWizardStore } from '@/stores/libraryWizard'
import { useUiStore } from '@/stores/ui'

/**
 * SERVER → Book Dock（`/settings/admin/book-dock`）
 *
 * 真实现：投递目录 = 本项目的 `INPUT_DIR`，与目录监听是同一套东西 ——
 * 把文件丢进去就会被自动处理。本页把「目录 + 监听状态 + 自动处理开关 + 处理计数」
 * 聚合展示（与上游 Book Dock 的「投递目录 + 自动处理」高度同构）。
 *
 * 上游还有两组：METADATA 的「投递后自动抓元数据」本项目**已实现**（`metadata_fetch.auto_on_import`
 * 与 `metadata_fetch.enabled` 双重门控，见 core/watcher.py:84；开关在 设置 → 元数据），
 * AUTO-FINALIZE 的「按置信度无人值守定稿」未做（缺的是上游那组目标库 / 文件夹 / 合并模式配置）。
 *
 * 参数细节（轮询间隔 / 稳定判定 / 忽略规则等）在「本项目扩展 → 监听」，本页不重复。
 */

interface WatcherInfo extends WatcherStatus {
  input?: string
  output?: string
  interval?: number
  processed?: number
  failed?: number
  converted?: number
  added?: number
  scans?: number
}

const ui = useUiStore()
const library = useLibraryStore()
const wizard = useLibraryWizardStore()
const { cfg, val, setVal, loadConfig, saveSection, saving } = useSettingsConfig()

/** 0 库文案里的「新建书库」出口：就地弹窗（第 55 期），不再跳设置页 */
function openWizard(): void {
  void wizard.show()
}

const watcher = ref<WatcherInfo | null>(null)
const health = ref<HealthInfo | null>(null)

const dropDir = computed(() => health.value?.input ?? watcher.value?.input ?? '—')
const running = computed(() => Boolean(watcher.value?.running))
/** 自动处理开关：等价于「丢进去就自动转换 / 导出」 */
const autoProcess = computed(() => Boolean(val('watcher.enabled')))
const dirty = computed(() => cfg.value != null && autoProcess.value !== running.value)

const counters = computed(() => [
  { k: '已转换', v: watcher.value?.converted ?? watcher.value?.processed ?? 0 },
  { k: '已添加', v: watcher.value?.added ?? 0 },
  { k: '失败', v: watcher.value?.failed ?? 0 },
  { k: '扫描轮次', v: watcher.value?.scans ?? 0 },
])

// ---- 五态流水线（B3）：All / Needs review / Pending / Ready / Error ----
const dock = ref<BookDockResponse | null>(null)
const activeTab = ref('all')
const busyId = ref('')
/** 流水线（主数据）加载失败信息：失败不能退化成「投递目录里还没有文件」。 */
const dockError = ref('')
/** 首屏加载标记：避免数据未到时先闪一下空态。 */
const dockLoading = ref(true)
/** 批量选择集合；仅作用于当前 tab 的条目，切 tab / 批量完成后清空。 */
const picked = ref<Set<string>>(new Set())
const batchBusy = ref(false)
const copiedDir = ref(false)

const STATUS_LABEL: Record<string, string> = {
  pending: '待处理',
  ready: '就绪',
  needs_review: '待复核',
  error: '出错',
  ignored: '已忽略',
}
const STATUS_TONE: Record<string, 'neutral' | 'ok' | 'warn' | 'err'> = {
  pending: 'neutral',
  ready: 'ok',
  needs_review: 'warn',
  error: 'err',
  ignored: 'neutral',
}

function fmtSize(n: number): string {
  const b = Number(n) || 0
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(1)} MB`
}

async function loadDock(): Promise<void> {
  dockLoading.value = true
  dockError.value = ''
  try {
    dock.value = await api.bookDock(activeTab.value)
  } catch (e) {
    // 主数据失败：必须给错误态 + 重试，不得渲染成「投递目录里还没有文件」
    dock.value = null
    dockError.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    dockLoading.value = false
  }
}

async function switchTab(key: string): Promise<void> {
  activeTab.value = key
  picked.value = new Set()
  await loadDock()
}

// ---- 时间维度：入库（created_at）总是显示，处理过才另标更新（updated_at） ----
function fmtTime(ts?: number): string {
  const n = Number(ts) || 0
  if (!n) return ''
  const d = new Date(n * 1000)
  const p = (x: number) => String(x).padStart(2, '0')
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  const md = `${p(d.getMonth() + 1)}-${p(d.getDate())}`
  const now = new Date()
  if (d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()) {
    return `今天 ${hm}`
  }
  return d.getFullYear() === now.getFullYear() ? `${md} ${hm}` : `${d.getFullYear()}-${md}`
}

/** 入库时间总是展示；updated_at 明显晚于 created_at（>60s）才额外标「更新」。 */
function timeText(it: BookDockItem): string {
  const created = fmtTime(it.created_at)
  if (!created) return ''
  const updated = fmtTime(it.updated_at)
  if (updated && Number(it.updated_at) - Number(it.created_at) > 60) {
    return `入库 ${created} · 更新 ${updated}`
  }
  return `入库 ${created}`
}

// ---- 批量操作：无批量端点，按既有单条端点逐条 await，失败逐条汇总 ----
const dockItems = computed<BookDockItem[]>(() => dock.value?.items ?? [])
const pickedIds = computed(() =>
  dockItems.value.filter((i) => picked.value.has(i.id)).map((i) => i.id),
)
const allPicked = computed(
  () => dockItems.value.length > 0 && pickedIds.value.length === dockItems.value.length,
)

function togglePick(id: string): void {
  const s = new Set(picked.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  picked.value = s
}

function toggleAll(): void {
  picked.value = allPicked.value ? new Set() : new Set(dockItems.value.map((i) => i.id))
}

async function batch(fn: (id: string) => Promise<unknown>, okMsg: string): Promise<void> {
  const ids = pickedIds.value
  if (!ids.length) return
  batchBusy.value = true
  let ok = 0
  const errs: string[] = []
  for (const id of ids) {
    try {
      await fn(id)
      ok += 1
    } catch (e) {
      errs.push(e instanceof Error ? e.message : '操作失败')
    }
  }
  batchBusy.value = false
  if (ok) ui.toast(`${okMsg} ${ok} 条`)
  if (errs.length) ui.toast(`${errs.length} 条失败：${errs[0]}`)
  picked.value = new Set()
  await refresh()
}

async function copyDir(): Promise<void> {
  try {
    await navigator.clipboard.writeText(dropDir.value)
    copiedDir.value = true
    setTimeout(() => (copiedDir.value = false), 1500)
  } catch {
    ui.toast('复制失败，请手动选中路径')
  }
}

/** 单项操作统一收尾：提示 + 重载（服务端已把新状态写回条目） */
async function act(fn: () => Promise<{ ok?: boolean }>, okMsg: string): Promise<void> {
  try {
    await fn()
    ui.toast(okMsg)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '操作失败')
  }
  await refresh()
}

async function rescanItem(id: string): Promise<void> {
  busyId.value = id
  await act(() => api.bookDockRescan(id), '已重新处理')
  busyId.value = ''
}

async function ignoreItem(id: string): Promise<void> {
  busyId.value = id
  await act(() => api.bookDockIgnore(id), '已忽略该条目')
  busyId.value = ''
}

async function deleteItem(id: string): Promise<void> {
  if (!window.confirm('把该文件移出收书目录？\n\n文件会移入回收目录（不会真正删除），之后不再自动处理。')) {
    return
  }
  busyId.value = id
  await act(() => api.bookDockDelete(id), '已移出到回收目录')
  busyId.value = ''
}

async function refresh(): Promise<void> {
  try {
    watcher.value = (await api.watcherStatus()) as WatcherInfo
  } catch {
    /* 状态取不到时不阻塞页面 */
  }
  await loadDock()
}

async function toggleWatcher(): Promise<void> {
  try {
    if (running.value) await api.watcherStop()
    else await api.watcherStart()
    ui.toast(running.value ? '收书目录已暂停' : '收书目录已开始监听')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '操作失败')
  }
  await refresh()
}

async function scanNow(): Promise<void> {
  try {
    await api.scanNow()
    ui.toast('已触发一次扫描')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '扫描失败')
  }
  await refresh()
}

async function saveAuto(): Promise<void> {
  const ok = await saveSection('watcher')
  // 开关变了要热更新监听器，后端保存时会一并处理，这里刷新状态即可
  if (ok) await refresh()
}

// ---- AUTO-FINALIZE（第 52 期）：映射到既有 metadata_fetch，不改入库流程 ----
// 开关 → auto_on_import（开启时一并打开 enabled，否则投递即抓不会跑）；
// 阈值界面 0–100 ↔ 内部 0–1；合并预设 → metadata_fetch.fields 整体重写（预设与逐字段互斥呈现）。
const FINALIZE_PRESETS: Array<{ key: string; label: string }> = [
  { key: 'overwrite', label: '覆盖（在线值优先）' },
  { key: 'fill_only', label: '安全合并（仅补空值）' },
  { key: 'embedded_only', label: '仅用内嵌（不下载在线）' },
]
const finalizeOn = computed({
  get: () => Boolean(val('metadata_fetch.auto_on_import')),
  set: (v: boolean) => setVal('metadata_fetch.auto_on_import', v),
})
const finalizeThreshold = computed({
  get: () => Math.round((Number(val('metadata_fetch.threshold') ?? 0.75)) * 100),
  set: (v: number) => setVal('metadata_fetch.threshold', Math.max(0, Math.min(100, Number(v))) / 100),
})
const finalizePreset = ref('fill_only')
const presetTouched = ref(false)

async function saveFinalize(): Promise<void> {
  // 选预设即整体重写 fields；未动预设则不覆盖用户在元数据页的逐字段微调。
  if (presetTouched.value) {
    const mode = finalizePreset.value === 'embedded_only' ? 'skip'
      : finalizePreset.value === 'fill_only' ? 'fill_only'
      : 'overwrite'
    const fields: Record<string, string> = {}
    for (const k of ['title', 'author', 'publisher', 'year', 'language', 'isbn', 'description', 'tags', 'cover']) {
      fields[k] = mode
    }
    setVal('metadata_fetch.fields', fields)
  }
  if (finalizeOn.value) setVal('metadata_fetch.enabled', true)
  await saveSection('metadata')
}

// ---- 整页拖拽投递（A8）：把文件拖进窗口即丢进 INPUT_DIR 处理 ----
const dragDepth = ref(0)
const dragging = computed(() => dragDepth.value > 0)
const dropping = ref(false)

function hasFiles(e: DragEvent): boolean {
  return Boolean(e.dataTransfer && [...e.dataTransfer.types].includes('Files'))
}
function onDragEnter(e: DragEvent): void {
  if (!hasFiles(e)) return
  e.preventDefault()
  dragDepth.value++
}
function onDragOver(e: DragEvent): void {
  if (!hasFiles(e)) return
  e.preventDefault()
}
function onDragLeave(e: DragEvent): void {
  if (!hasFiles(e)) return
  e.preventDefault()
  dragDepth.value = Math.max(0, dragDepth.value - 1)
}
async function onDrop(e: DragEvent): Promise<void> {
  if (!e.dataTransfer) return
  e.preventDefault()
  dragDepth.value = 0
  const files = [...e.dataTransfer.files]
  if (!files.length) return
  // 0 库时提前拦下（第 38 期）：投递链路按「没有可接收的库」拒收，
  // 文件会落在投递目录里被反复扫描却永远不进库 —— 与其留下这种状态，
  // 不如当场说清「先去建库」。（后端仍会兜底拒收，这里只是把话说在前面。）
  if (library.hasNoLibraries) {
    ui.toast('还没有书库：先新建一个书库，投递的文件才有地方归')
    return
  }
  dropping.value = true
  let ok = 0
  for (const file of files) {
    try {
      await api.convertDrop(file)
      ok++
    } catch (err) {
      ui.toast(err instanceof Error ? `${file.name}：${err.message}` : `${file.name} 投递失败`)
    }
  }
  dropping.value = false
  if (ok) {
    ui.toast(`已投递 ${ok} 个文件到收书目录`)
    await refresh()
  }
}

onMounted(async () => {
  window.addEventListener('dragenter', onDragEnter)
  window.addEventListener('dragover', onDragOver)
  window.addEventListener('dragleave', onDragLeave)
  window.addEventListener('drop', onDrop)
  try {
    health.value = await api.health()
  } catch {
    /* ignore */
  }
  await loadConfig()
  await refresh()
})

onBeforeUnmount(() => {
  window.removeEventListener('dragenter', onDragEnter)
  window.removeEventListener('dragover', onDragOver)
  window.removeEventListener('dragleave', onDragLeave)
  window.removeEventListener('drop', onDrop)
})
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">收书目录</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Book Dock</span>
      <span class="text-[11.5px] text-muted-foreground">
        {{ library.hasNoLibraries ? '还没有书库，投递的文件无处归库' : '把文件丢进目录即自动处理' }}
      </span>
      <Button size="sm" class="ml-auto" :disabled="saving" @click="scanNow">立即扫描</Button>
      <Button size="sm" :variant="running ? 'danger' : 'primary'" @click="toggleWatcher">
        {{ running ? '暂停' : '开始监听' }}
      </Button>
    </div>

    <!-- 投递目录 -->
    <Card padding="none" class="mb-4">
      <div class="border-b border-border px-4 py-3.5">
        <div class="flex items-center gap-3">
          <span class="h-2 w-2 shrink-0 rounded-full" :class="running ? 'bg-success' : 'bg-muted-foreground'" />
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-medium text-foreground">投递目录</div>
            <div class="mt-0.5 text-[11.5px] text-muted-foreground">
              {{ running ? '正在监听' : '未监听' }}
              <span v-if="watcher?.interval"> · 轮询 {{ watcher.interval }}s</span>
            </div>
          </div>
          <Badge :tone="running ? 'ok' : 'neutral'">{{ running ? '运行中' : '已暂停' }}</Badge>
        </div>
        <div class="mt-2 flex items-center gap-2">
          <div
            class="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1.5 font-mono text-[11.5px] text-foreground"
            :title="dropDir"
          >
            {{ dropDir }}
          </div>
          <Button size="sm" @click="copyDir">{{ copiedDir ? '已复制' : '复制' }}</Button>
        </div>
        <p class="mt-2 text-[11.5px] leading-relaxed text-muted-foreground">
          <template v-if="library.hasNoLibraries">
            还没有书库：文件放进来会被<strong>拒收</strong>（没有可接收的库）。请先
            <button type="button" class="underline" @click="openWizard">新建一个书库</button>
            并指定它的来源目录。
          </template>
          <template v-else>
            把 <code class="font-mono">.txt</code> 放进该目录会自动转成 EPUB 并归入成品目录；
            其它格式按设置原样导出。子目录是否递归、写入稳定判定等参数见
            <RouterLink to="/settings/ext/watcher" class="underline">本项目扩展 → 监听</RouterLink>。
          </template>
        </p>
      </div>

      <!-- 自动处理开关 -->
      <div class="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">自动处理投递文件</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            关闭后目录不再自动扫描，只能手动「立即扫描」或从工具页逐个处理
          </div>
        </div>
        <button
          type="button"
          role="switch"
          :aria-checked="autoProcess"
          class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors"
          :class="autoProcess ? 'bg-primary' : 'bg-muted'"
          @click="setVal('watcher.enabled', !autoProcess)"
        >
          <span
            class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-card transition-transform duration-200"
            :class="autoProcess ? 'translate-x-[16px]' : 'translate-x-[2px]'"
          />
        </button>
        <Button size="sm" variant="primary" :disabled="saving || !dirty" @click="saveAuto">保存</Button>
      </div>

      <!-- 计数 -->
      <div class="grid grid-cols-2 gap-x-4 gap-y-2 px-4 py-3.5 sm:grid-cols-4">
        <div v-for="c in counters" :key="c.k" class="min-w-0">
          <div class="text-[11px] text-muted-foreground">{{ c.k }}</div>
          <div class="mt-0.5 text-[13px] font-medium text-foreground tabular-nums">{{ c.v }}</div>
        </div>
      </div>
    </Card>

    <p v-if="dirty" class="mb-4 text-[11.5px] text-warning">
      开关已改动但尚未保存 —— 保存后监听器会立即按新配置启停。
    </p>

    <!-- 五态流水线（B3）：All / Needs review / Pending / Ready / Error -->
    <Card padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">投递流水线</h3>
        <span class="text-[11.5px] text-muted-foreground">条目按状态流转，可逐条复核</span>
        <div class="ml-auto flex flex-wrap items-center gap-1.5">
          <button
            v-for="t in dock?.tabs ?? []"
            :key="t.key"
            type="button"
            class="cursor-pointer rounded-full px-3 py-1 text-[12px] transition-colors"
            :class="activeTab === t.key
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted text-muted-foreground hover:text-foreground'"
            @click="switchTab(t.key)"
          >
            {{ t.label }}<span class="ml-1 tabular-nums opacity-70">{{ t.count }}</span>
          </button>
        </div>
      </div>

      <!-- 主数据失败：给错误态 + 重试，不得退化成 EmptyState「投递目录里还没有文件」 -->
      <div v-if="dockError" class="flex flex-wrap items-center gap-2 px-4 py-4 text-[12.5px] text-destructive">
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        <span>投递流水线加载失败：{{ dockError }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="loadDock">重试</Button>
      </div>

      <p v-else-if="dockLoading" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">
        加载中…
      </p>

      <!-- 批量操作条：无批量端点，逐条调用既有单条端点 -->
      <div
        v-else-if="dock && dock.items.length"
        class="flex flex-wrap items-center gap-2 border-b border-border bg-muted/40 px-4 py-2"
      >
        <button
          type="button"
          class="cursor-pointer rounded-md border border-border px-2.5 py-1 text-[12px] text-foreground transition-colors hover:bg-muted"
          @click="toggleAll"
        >
          {{ allPicked ? '清空选择' : '全选本页' }}
        </button>
        <span class="text-[11.5px] tabular-nums text-muted-foreground">
          已选 {{ pickedIds.length }} / {{ dock.items.length }}
        </span>
        <div class="ml-auto flex items-center gap-1.5">
          <Button
            size="sm"
            variant="secondary"
            :disabled="batchBusy || !pickedIds.length"
            @click="batch(api.bookDockRescan, '已重新处理')"
          >
            批量重扫
          </Button>
          <Button
            size="sm"
            variant="secondary"
            :disabled="batchBusy || !pickedIds.length"
            @click="batch(api.bookDockIgnore, '已忽略')"
          >
            批量忽略
          </Button>
        </div>
      </div>

      <div v-else-if="dock && dock.items.length" class="divide-y divide-border">
        <div
          v-for="it in dock.items"
          :key="it.id"
          class="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3"
        >
          <input
            type="checkbox"
            class="h-4 w-4 shrink-0 cursor-pointer accent-primary"
            :checked="picked.has(it.id)"
            :aria-label="`选择 ${it.name}`"
            @change="togglePick(it.id)"
          >
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <Icon name="book" class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span class="truncate text-[12.5px] font-medium text-foreground" :title="it.name">{{ it.name }}</span>
              <Badge :tone="STATUS_TONE[it.status] ?? 'neutral'">
                {{ STATUS_LABEL[it.status] ?? it.status }}
              </Badge>
            </div>
            <div class="mt-1 truncate text-[11.5px] text-muted-foreground" :title="it.output || it.detail">
              {{ it.output ? `成品：${it.output}` : it.detail || '等待自动处理' }}
              <span class="ml-1 opacity-70">{{ fmtSize(it.size) }}</span>
              <span v-if="timeText(it)" class="ml-1 opacity-70">· {{ timeText(it) }}</span>
              <span v-if="it.retries" class="ml-1 text-warning">· 已重试 {{ it.retries }} 次</span>
            </div>
          </div>
          <div class="flex items-center gap-1.5">
            <Button size="sm" :disabled="busyId === it.id || batchBusy" @click="rescanItem(it.id)">重扫</Button>
            <Button size="sm" :disabled="busyId === it.id || batchBusy" @click="ignoreItem(it.id)">忽略</Button>
            <Button size="sm" variant="danger" :disabled="busyId === it.id || batchBusy" @click="deleteItem(it.id)">移出</Button>
          </div>
        </div>
      </div>

      <EmptyState
        v-else
        icon="upload"
        dashed
        class="m-4"
        :title="activeTab === 'all' ? '投递目录里还没有文件' : '该状态下没有条目'"
        :desc="
          library.hasNoLibraries
            ? '还没有书库 —— 现在投递进来的文件会被拒收。先到「设置 → 书库管理」新建一个书库，再往这里放文件。'
            : '把 .txt / EPUB / PDF / CBZ 拖进本页任意位置，或直接放进投递目录，文件会在这里按状态流转。'
        "
      />
    </Card>

    <!-- AUTO-FINALIZE（第 52 期）：映射到既有 metadata_fetch，不改入库流程 -->
    <Card class="mt-4" padding="none">
      <div class="flex items-center justify-between border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">自动定稿（AUTO-FINALIZE）</span>
        <span class="text-[11.5px] text-muted-foreground">投递即抓并按置信度定稿</span>
      </div>

      <div class="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">新书入库即自动抓取并定稿</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            开启后，新书入库会按置信度阈值自动抓取元数据并写回；低于阈值的候选只列在
            <RouterLink to="/settings/metadata/auto-fetch" class="underline">设置 → 元数据 → 书籍自动抓取</RouterLink>
            的预览页。等同于该页的「新书入库自动抓」。
          </div>
        </div>
        <button
          type="button"
          role="switch"
          :aria-checked="finalizeOn"
          class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors"
          :class="finalizeOn ? 'bg-primary' : 'bg-muted'"
          @click="finalizeOn = !finalizeOn"
        >
          <span
            class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-card transition-transform duration-200"
            :class="finalizeOn ? 'translate-x-[16px]' : 'translate-x-[2px]'"
          />
        </button>
      </div>

      <div class="flex flex-wrap items-end gap-4 border-b border-border px-4 py-3.5">
        <label class="text-[12px] text-muted-foreground">
          <span class="mb-1 block text-[12.5px] font-medium text-foreground">置信度阈值（%）</span>
          <input
            v-model.number="finalizeThreshold"
            type="number"
            min="0"
            max="100"
            step="1"
            class="h-8 w-24 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none focus:border-ring"
          >
        </label>
        <label class="text-[12px] text-muted-foreground">
          <span class="mb-1 block text-[12.5px] font-medium text-foreground">合并模式</span>
          <select
            v-model="finalizePreset"
            class="h-8 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none focus:border-ring"
            @change="presetTouched = true"
          >
            <option v-for="p in FINALIZE_PRESETS" :key="p.key" :value="p.key">{{ p.label }}</option>
          </select>
        </label>
      </div>

      <div class="flex items-center gap-3 px-4 py-3.5">
        <p class="flex-1 text-[11.5px] leading-relaxed text-muted-foreground">
          入库目标沿用各库自己的来源目录 —— 本项目没有单点「目标库 / 文件夹」设置。
          合并模式与元数据页的逐字段策略互斥呈现：选预设即整体套用，逐字段微调请到元数据页。
        </p>
        <Button size="sm" variant="primary" :disabled="saving" @click="saveFinalize">保存定稿设置</Button>
      </div>
    </Card>

    <SettingsUnsupportedCard
      label="Book Dock"
      :groups="['目标库 / 文件夹']"
      :items="[
        '上游 auto-finalize 可指定单一目标库与目标文件夹；本项目入库目标 = 各库自己的来源目录（按设计不做单点设置），故该组配置不提供',
      ]"
      note="上游 Book Dock 是「投递目录 + 元数据抓取 + 置信度定稿」的完整流水线。本项目「投递目录 + 自动处理 + 五态复核（待复核 / 待处理 / 就绪 / 出错）」已落地，投递即抓已接线（metadata_fetch.auto_on_import 与 enabled 双门控）；第 52 期起「自动定稿」已落地：开关映射 auto_on_import、阈值界面 0–100 内部换算 0–1、合并模式预设（覆盖 / 安全合并 / 仅用内嵌）映射既有 fields 逐字段策略。"
    />

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        上游对应入口：侧栏 <span class="font-mono">Book Dock</span>。
        相关页：<RouterLink to="/settings/ext/watcher" class="underline">监听</RouterLink>（
        轮询与稳定判定参数）、<RouterLink to="/tools/local" class="underline">工具 → 本地转换</RouterLink>（单文件投递）。
      </div>
    </Card>

    <!-- 整页拖拽投递遮罩（A8）：拖文件进窗口时浮层，松手即投递到收书目录 -->
    <transition
      enter-active-class="transition-opacity duration-150"
      leave-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="dragging"
        class="fixed inset-0 z-[60] flex items-center justify-center bg-black/55 backdrop-blur-sm"
        @dragover.prevent
        @drop.prevent="onDrop"
      >
        <div class="flex flex-col items-center gap-3 rounded-[var(--shell-radius)] border-2 border-dashed border-primary/60 bg-[var(--shell-surface)] px-10 py-9 text-center">
          <Icon name="upload" class="h-9 w-9 text-primary" />
          <div class="text-[15px] font-semibold text-foreground">松开投递到收书目录</div>
          <div class="text-[12px] text-muted-foreground">
            {{
              dropping
                ? '正在处理…'
                : library.hasNoLibraries
                  ? '还没有书库 —— 现在松开会被拒收，请先新建书库'
                  : '.txt 会被转换，其它电子书格式（EPUB/PDF/CBZ 等）直接入库'
            }}
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>
