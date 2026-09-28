<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import Switch from '@/components/ui/Switch.vue'
import { POLICY_FIELDS } from '@/lib/metadataFields'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import {
  api,
  apiErrorMessage,
  type BookDockItem,
  type BookDockResponse,
  type HealthInfo,
  type LibraryEntity,
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
 * 上游还有两组，本项目**都已落地**：METADATA 的「投递后自动抓元数据」（`metadata_fetch.auto_on_import`
 * 与 `metadata_fetch.enabled` 双重门控，见 core/watcher.py:84；开关在 设置 → 元数据）与
 * AUTO-FINALIZE 的「按置信度无人值守定稿」（第 52 期，同样映射到 `metadata_fetch`，见下方卡片）。
 *
 * 第 65 期加了两个**条目级**动作（本页首次出现行内交互）：
 *   · **重命名** —— 只改投递目录里的文件名，只对**未入库**的条目显示（`就绪` 没有这个按钮）；
 *   · **入库到…** —— 入库前当场指定目标库与目标文件夹（默认该库第一个），选完即弃、**不落库**。
 * ⚠️ 本页原先写着「本项目没有单点目标库 / 文件夹设置」，并据此把该组配置归入「不支持」。
 * 那句话现在仍然成立（**设置项**确实没有），变的是多了这个**按次指定**的动作 —— 两者不矛盾，
 * 别再把「按次指定」当成「没有」。
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
    const r = await api.bookDock(activeTab.value)
    dock.value = r
    // 摘掉已不在列表里的选择（第 65 期）：改名会换 id，旧 id 若一直躺在选择集里，
    // 那个条目**改名后又变回来**（id 撞回原值）时会莫名被勾上 —— `pickedIds` 是按
    // id 过滤的，拦不住这种「复活」。
    if (picked.value.size) {
      const alive = new Set((r.items ?? []).map((i) => i.id))
      picked.value = new Set([...picked.value].filter((id) => alive.has(id)))
    }
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

/** 行内动作的共用禁用判据：本行在忙 / 批量在忙 / 有别的行正在改名。 */
function rowBusy(id: string): boolean {
  return busyId.value === id || batchBusy.value || renameBusy.value
}

// ---- 重命名（第 65 期）：只改投递目录里的**文件名**，扩展名不许换 ----
// 只对**未入库**的条目开放（`就绪` 不显示）：就绪条目的成品已经在书库里了，改投递目录里
// 的源文件既改不到那本书、又让两者对不上；「改已入库的书名」是书架「编辑元数据」的地盘。
// 后端另有一道同样的拒绝 —— 两边都拦，是为了「界面不出现假交互」且「直接打接口也拦得住」。
const editingId = ref('')
const editName = ref('')
const renameBusy = ref(false)

function startRename(it: BookDockItem): void {
  editingId.value = it.id
  // 预填**含扩展名的完整文件名**：所见即所得，改什么就是什么（扩展名后端会拦）
  editName.value = it.name
}

function cancelRename(): void {
  editingId.value = ''
  editName.value = ''
}

async function commitRename(it: BookDockItem): Promise<void> {
  const next = editName.value.trim()
  if (!next) {
    // 空名字不发请求，但**也不能静默关掉编辑框** —— 按了 Enter 什么都没发生
    // 与「点了没反应」是同一种假交互。说清原因，编辑态留着。
    ui.toast('名字不能为空')
    return
  }
  if (next === it.name) {
    cancelRename()                 // 没改（含只多了空白）：等同取消
    return
  }
  renameBusy.value = true
  let ok = false
  try {
    await api.bookDockRename(it.id, next)
    ok = true
    ui.toast('已重命名')
  } catch (e) {
    // 失败**保持编辑态**：用户改一个字符再试即可，不必把名字重敲一遍
    ui.toast(e instanceof Error ? e.message : '重命名失败')
  } finally {
    renameBusy.value = false
  }
  if (ok) cancelRename()
  // 条目 id **就是文件名** ⇒ 成功之后 id 变了，必须重载列表（否则旧行还挂在旧 id 上）
  await refresh()
}

// ---- 入库到…（第 65 期）：入库前当场指定目标库与目标文件夹 ----
// 数据取自库 store 现成的 `libraryEntities`（`source_dirs` = 该库的多个文件夹，
// 口径：默认第一个）。**不落库、不记忆** —— 这是这一次动作的输入，不是条目的属性
// （下一次扫描仍按各库自己的来源目录路由）。
const ingestItem = ref<BookDockItem | null>(null)
const ingestLibId = ref('')
const ingestRoot = ref('')
const ingestBusy = ref(false)

/** 待入库条目的扩展名（判「这个库收不收得了它」用）。 */
const ingestExt = computed(() => {
  const n = ingestItem.value?.name ?? ''
  const i = n.lastIndexOf('.')
  return i > 0 ? n.slice(i).toLowerCase() : ''
})

/**
 * 该库收不收得了这个格式 —— 与后端 `library.accepts_ext` 同口径（真值源是库的
 * **生效**白名单 `exts_effective`）。**没有扩展名的放行**：后端也放行，
 * 那种形态（有声书「一章一文件」的目录）在这里判不了，误拒比漏判更烦人。
 */
function libAccepts(l: LibraryEntity): boolean {
  const ext = ingestExt.value
  if (!ext) return true
  return (l.exts_effective ?? []).includes(ext)
}

const ingestLib = computed(
  () => library.libraryEntities.find((l) => l.id === ingestLibId.value) ?? null,
)
const ingestDirs = computed(() => ingestLib.value?.source_dirs ?? [])
/** 能否提交：选了库、库收得了这个格式、且该库有落点文件夹。 */
const ingestReady = computed(
  () => Boolean(ingestLib.value) && libAccepts(ingestLib.value as LibraryEntity)
    && Boolean(ingestRoot.value) && !ingestBusy.value,
)

async function openIngest(it: BookDockItem): Promise<void> {
  ingestItem.value = it
  // 现拉一次而不是吃缓存：目标文件夹取自 `source_dirs`，别拿一个已经被改过的库来选
  await library.loadLibraries(true)
  const libs = library.libraryEntities
  // 默认选**第一个收得了这个格式的**库（都收不了才退到第一个，好在弹窗里当场看到原因）
  const pick = libs.find(libAccepts) ?? libs[0]
  ingestLibId.value = pick?.id ?? ''
  ingestRoot.value = pick?.source_dirs?.[0] ?? ''
}

function closeIngest(): void {
  ingestItem.value = null
  ingestLibId.value = ''
  ingestRoot.value = ''
}

function chooseIngestLib(l: LibraryEntity): void {
  ingestLibId.value = l.id
  // 换库就换文件夹：默认仍是该库的第一个（口径 7）
  ingestRoot.value = l.source_dirs?.[0] ?? ''
}

async function confirmIngest(): Promise<void> {
  const it = ingestItem.value
  if (!it || !ingestReady.value) return
  ingestBusy.value = true
  try {
    await api.bookDockRescan(it.id, { library_id: ingestLibId.value, root: ingestRoot.value })
    ui.toast('已入库')
    closeIngest()
  } catch (e) {
    // 失败**不关弹窗**：库管理里刚把格式加进去、或换个库，就地重试即可
    ui.toast(e instanceof Error ? e.message : '入库失败')
  } finally {
    ingestBusy.value = false
  }
  await refresh()
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
    // ⚠️ 字段清单取自 `lib/metadataFields.ts`（= 后端 `metafetch._FINALIZE_FIELDS`）。
    // 这里原先是**手抄的 9 个键**，且把出版年抄成了 `year`（引擎按 `date` 查策略）——
    // 于是「选预设」这一动作对出版年从来没生效过。写少一个键同样是静默的：
    // 漏掉的那个字段会保留原策略，预设说的和做的对不上。
    const fields: Record<string, string> = {}
    for (const k of POLICY_FIELDS) {
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
/** 工具栏「上传」正在投递（第 70 期）：与拖拽共用同一个投递函数，只是入口不同 */
const uploading = ref(false)

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
/**
 * 0 库时提前拦下（第 38 期）：投递链路按「没有可接收的库」拒收，
 * 文件会落在投递目录里被反复扫描却永远不进库 —— 与其留下这种状态，
 * 不如当场说清「先去建库」。（后端仍会兜底拒收，这里只是把话说在前面。）
 */
function blockedByNoLibrary(): boolean {
  if (!library.hasNoLibraries) return false
  ui.toast('还没有书库：先新建一个书库，投递的文件才有地方归')
  return true
}

/**
 * 投递一批文件到收书目录（第 70 期从 `onDrop` 里抽出来）。
 *
 * 拖拽入口（N 个文件）与工具栏「上传」按钮（1 个文件）**共用这一份**守卫 / 反馈 / 刷新 ——
 * 同一件事两套实现迟早走样（一个给明确原因、另一个静默，就是最常见的走样方式）。
 */
async function deliverToDock(files: File[]): Promise<number> {
  let ok = 0
  for (const file of files) {
    try {
      await api.convertDrop(file)
      ok++
    } catch (err) {
      // 用 `apiErrorMessage` 而不是 `err.message`：后者是后端响应原文（`{"detail":"…"}`），
      // 原样塞进 toast 会把花括号和键名一起露给用户。
      ui.toast(`${file.name}：${apiErrorMessage(err, '投递失败')}`)
    }
  }
  if (ok) {
    ui.toast(`已投递 ${ok} 个文件到收书目录`)
    await refresh()
  }
  return ok
}

async function onDrop(e: DragEvent): Promise<void> {
  if (!e.dataTransfer) return
  e.preventDefault()
  dragDepth.value = 0
  const files = [...e.dataTransfer.files]
  if (!files.length) return
  if (blockedByNoLibrary()) return
  dropping.value = true
  try {
    await deliverToDock(files)
  } finally {
    dropping.value = false
  }
}

// ---- 工具栏「上传」（第 70 期）：与拖拽同一条投递链路，只是把「选文件」交给系统选择器 ----

const fileInput = ref<HTMLInputElement | null>(null)

function pickFile(): void {
  if (uploading.value) return
  fileInput.value?.click()
}

async function onPickedFile(e: Event): Promise<void> {
  const el = e.target as HTMLInputElement
  const file = el.files?.[0]
  // 先清空 input 的值：不清空的话「连续两次选同一个文件」第二次不会触发 `change`
  //（`change` 只在值变化时发）。清空不会让上面取到的 `File` 句柄失效。
  el.value = ''
  if (!file) return
  if (blockedByNoLibrary()) return
  uploading.value = true
  try {
    await deliverToDock([file])
  } finally {
    uploading.value = false
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
  // 本页多处按 `library.hasNoLibraries` 分岔文案，而那个判据要 `librariesLoaded`
  // （拉取失败时保持 false ⇒ 一律按「有库」说）。App.vue 启动时已拉过，此处只是
  // 兜住「直接进本页 / 上一步拉失败」两种情形：有数据就立刻返回，不额外发请求。
  void library.loadLibraries()
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
      <!-- 第 70 期：单文件投递入口。走的是与整页拖拽**同一个**接口（`convertDrop` → `POST /convert`），
           只是把「选文件」交给系统选择器；`multiple` 刻意不加（只允许单个文件），也不加 `accept`
           （与拖拽口径一致：格式由后端判，判不了会明确说明原因，不静默）。 -->
      <Button
        size="sm"
        variant="primary"
        :disabled="uploading"
        title="上传"
        aria-label="上传"
        @click="pickFile"
      >
        {{ uploading ? '上传中…' : '上传' }}
      </Button>
      <input ref="fileInput" type="file" class="hidden" @change="onPickedFile">
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
        <Switch :model-value="autoProcess" @update:model-value="setVal('watcher.enabled', $event)" />
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

      <!-- ⚠️ 这两块必须在**同一个** `v-else-if` 分支里（第 65 期修）：原先批量条与
           条目行各自写了一遍 `v-else-if="dock && dock.items.length"`，条件逐字相同
           ⇒ 后一个分支**永不渲染** ⇒ 条目行一条都不显示；而复选框长在条目行里，
           于是「批量重扫 / 批量忽略」永远禁用、单条的三个按钮点不到。
           页面上看不出异常，只像「投递目录里还没有文件」。
           `<template>` 不产生 DOM 节点；内层缩进沿用原样，好让 diff 只动这几行。 -->
      <template v-else-if="dock && dock.items.length">
      <!-- 批量操作条：无批量端点，逐条调用既有单条端点 -->
      <div
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

      <div class="divide-y divide-border">
        <!-- `data-dock-row` 供 spec 计数（照 `[data-icon-button]` 的先例）：条目行
             曾经因为两个 `v-else-if` 条件逐字相同而**永不渲染**，而那种失效方式
             页面上只是「一条都不显示」—— 看起来与「投递目录里还没有文件」一模一样。 -->
        <div
          v-for="it in dock.items"
          :key="it.id"
          data-dock-row
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
              <!-- 行内重命名（第 65 期）：预填**含扩展名**的完整文件名 —— 所见即所得。
                   只认 Enter / Esc 与两个按钮，**不做失焦提交**：点一下别处就把名字改掉
                   的误伤，比「多点一下」贵得多。 -->
              <template v-if="editingId === it.id">
                <input
                  v-model="editName"
                  data-dock-rename-input
                  :aria-label="`重命名 ${it.name}`"
                  class="h-7 min-w-0 flex-1 rounded-md border border-border bg-muted px-2 font-mono text-[12px] text-foreground outline-none focus:border-ring"
                  @keydown.enter.prevent="commitRename(it)"
                  @keydown.esc.prevent="cancelRename()"
                >
                <button
                  type="button"
                  data-dock-act="rename-ok"
                  aria-label="确认重命名"
                  :disabled="renameBusy"
                  class="shrink-0 cursor-pointer rounded-md border border-border px-1.5 py-0.5 text-[12px] text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-55"
                  @click="commitRename(it)"
                >✓</button>
                <button
                  type="button"
                  data-dock-act="rename-cancel"
                  aria-label="取消重命名"
                  :disabled="renameBusy"
                  class="shrink-0 cursor-pointer rounded-md border border-border px-1.5 py-0.5 text-[12px] text-muted-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-55"
                  @click="cancelRename()"
                >✗</button>
              </template>
              <template v-else>
                <span class="truncate text-[12.5px] font-medium text-foreground" :title="it.name">{{ it.name }}</span>
                <Badge :tone="STATUS_TONE[it.status] ?? 'neutral'">
                  {{ STATUS_LABEL[it.status] ?? it.status }}
                </Badge>
              </template>
            </div>
            <div class="mt-1 truncate text-[11.5px] text-muted-foreground" :title="it.output || it.detail">
              {{ it.output ? `成品：${it.output}` : it.detail || '等待自动处理' }}
              <span class="ml-1 opacity-70">{{ fmtSize(it.size) }}</span>
              <span v-if="timeText(it)" class="ml-1 opacity-70">· {{ timeText(it) }}</span>
              <span v-if="it.retries" class="ml-1 text-warning">· 已重试 {{ it.retries }} 次</span>
            </div>
          </div>
          <div class="flex items-center gap-1.5">
            <!-- 两个只对**未入库**条目开放的动作（口径 5/6）：`就绪` 一律不显示 ——
                 「不出现、不灰置、不占位」；已入库的改名去书架「编辑元数据」，
                 改投它库是 migrate 的地盘。 -->
            <template v-if="it.status !== 'ready'">
              <Button size="sm" data-dock-act="rename" :disabled="rowBusy(it.id)" @click="startRename(it)">重命名</Button>
              <Button size="sm" data-dock-act="ingest" :disabled="rowBusy(it.id)" @click="openIngest(it)">入库到…</Button>
            </template>
            <Button size="sm" data-dock-act="rescan" :disabled="rowBusy(it.id)" @click="rescanItem(it.id)">重扫</Button>
            <Button size="sm" data-dock-act="ignore" :disabled="rowBusy(it.id)" @click="ignoreItem(it.id)">忽略</Button>
            <Button size="sm" variant="danger" data-dock-act="delete" :disabled="rowBusy(it.id)" @click="deleteItem(it.id)">移出</Button>
          </div>
        </div>
      </div>
      </template>

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
        <Switch v-model="finalizeOn" />
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
          <!-- 复核头（第 65 期）：这里原先写「入库目标沿用各库自己的来源目录 —— 本项目
               没有单点「目标库 / 文件夹」设置」。**设置项仍然没有**（那句话本身没错），
               但条目行现在有了「入库到…」这个**按次指定**的动作 —— 目标在那一刻由用户选、
               随该次入库透传，不落库也不记忆，下一次扫描照旧按各库自己的来源目录路由。 -->
          入库目标：默认沿用各库自己的来源目录；需要一次性改投时，用条目行的「入库到…」
          当场指定目标库与文件夹（不保存、不影响后续扫描）。本项目仍然<strong>没有</strong>单点的
          「目标库 / 文件夹」设置项。合并模式与元数据页的逐字段策略互斥呈现：选预设即整体套用，
          逐字段微调请到元数据页。
        </p>
        <Button size="sm" variant="primary" :disabled="saving" @click="saveFinalize">保存定稿设置</Button>
      </div>
    </Card>

    <!-- 复核头（第 65 期）：这里原先挂着 `SettingsUnsupportedCard label="Book Dock"
         :groups="['目标库 / 文件夹']"`，把它归入「不支持」。那个功能已经做了
         （条目行的「入库到…」，只是**按次**指定而不是设置项）⇒ 整块删掉 ——
         做了就不是「不支持」。 -->

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        上游对应入口：侧栏 <span class="font-mono">Book Dock</span>（本项目自第 65 期起
        同样是侧栏一级项「收书目录」<span class="font-mono">/book-dock</span>，设置里这一条保留）。
        相关页：<RouterLink to="/settings/ext/watcher" class="underline">监听</RouterLink>（
        轮询与稳定判定参数）、<RouterLink to="/tools/local" class="underline">工具 → 本地导入</RouterLink>（单文件投递）。
      </div>
    </Card>

    <!-- 入库到…（第 65 期）：居中弹窗，骨架照 BookMoveDialog 的范式
         （fixed inset-0 z-50 grid place-items-center bg-black/35 + @click.self）。
         一次性的**按次指定**：选完即透传给后端那次入库，不落库、不记忆。 -->
    <div
      v-if="ingestItem"
      class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4"
      @click.self="closeIngest"
    >
      <div class="max-h-[88vh] w-[min(34rem,94vw)] overflow-y-auto rounded-lg border border-border bg-card p-5 shadow-2xl">
        <h3 class="font-serif text-[17px] font-semibold text-foreground">入库到…</h3>
        <p class="mt-1 text-[12px] leading-relaxed text-muted-foreground">
          把「<span class="font-medium text-foreground">{{ ingestItem.name }}</span>」放进指定书库的文件夹。
          文件名与扩展名都不会变。目标库的「允许的格式」收不了它时不能选 —— 收进去也扫不到，
          书会变成看不见的<strong>隐形文件</strong>。
        </p>

        <div class="mt-4 text-[12.5px] font-medium text-foreground">目标书库</div>
        <p v-if="!library.libraryEntities.length" class="mt-1 text-[11.5px] text-muted-foreground">
          还没有书库：先到
          <RouterLink :to="{ name: 'settings-libraries' }" class="underline">设置 → 书库管理</RouterLink>
          新建一个。
        </p>
        <div v-else class="mt-2 flex flex-wrap gap-2">
          <button
            v-for="l in library.libraryEntities"
            :key="l.id"
            type="button"
            :data-dock-ingest-lib="l.id"
            :disabled="!libAccepts(l) || ingestBusy"
            class="rounded-md border px-2.5 py-1.5 text-left text-[12px] transition-colors disabled:cursor-not-allowed disabled:opacity-55"
            :class="ingestLibId === l.id
              ? 'border-primary bg-primary/10 text-foreground'
              : 'border-border text-muted-foreground hover:border-primary/60'"
            @click="chooseIngestLib(l)"
          >
            <span class="font-medium">{{ l.name }}</span>
            <span class="ml-1 opacity-70">{{ l.type_label }}</span>
            <!-- 收不了的**照列 + 写明原因**（抹掉的话用户会以为书库没建好 / 建错了） -->
            <span v-if="!libAccepts(l)" class="ml-1 text-[11px] opacity-70">
              · 不收 {{ ingestExt || '这个格式' }}（先到书库管理把它加进「允许的格式」）
            </span>
          </button>
        </div>

        <template v-if="ingestLib">
          <div class="mt-4 text-[12.5px] font-medium text-foreground">目标文件夹</div>
          <select
            v-if="ingestDirs.length"
            v-model="ingestRoot"
            data-dock-ingest-root
            aria-label="目标文件夹"
            class="mt-2 h-8 w-full rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none focus:border-ring"
          >
            <option v-for="d in ingestDirs" :key="d" :value="d">{{ d }}</option>
          </select>
          <p v-else class="mt-1 text-[11.5px] text-warning">
            「{{ ingestLib.name }}」还没有文件夹：先到书库管理给它加一个来源目录。
          </p>
        </template>

        <div class="mt-5 flex flex-wrap items-center gap-2">
          <span class="text-[11.5px] text-muted-foreground">
            {{ ingestRoot ? `将放进：${ingestRoot}` : '先选一个书库与文件夹' }}
          </span>
          <Button size="sm" variant="ghost" class="ml-auto" :disabled="ingestBusy" @click="closeIngest">取消</Button>
          <Button
            size="sm"
            variant="primary"
            data-dock-ingest-ok
            :disabled="!ingestReady"
            @click="confirmIngest"
          >
            {{ ingestBusy ? '入库中…' : '入库' }}
          </Button>
        </div>
      </div>
    </div>

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
