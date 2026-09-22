<script setup lang="ts">
/**
 * 书库管理（工具页 → 书库管理，第 10 期 D8）。
 *
 * 三块的顺序按**用户遇到的问题**排，而不是按数据结构排：
 *   1. 迁移确认 —— 老部署升级上来第一件要回答的事「我这堆书要不要按格式分家」；
 *   2. 书库列表 —— 建/改/扫/移除；
 *   3. 当前库能力 —— 解释「为什么某些菜单不见了」（否则用户会以为功能丢了）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import ExtChips from '@/components/tools/ExtChips.vue'
import LibraryConflictPanel from '@/components/tools/LibraryConflictPanel.vue'
import LibrarySettingsPanel from '@/components/tools/LibrarySettingsPanel.vue'
import LibraryWizard from '@/components/tools/LibraryWizard.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import {
  api,
  type LibraryEntity,
  type LibraryType,
  type MigrationPreview,
  type MigrationRow,
} from '@/lib/api'
import { ICONS } from '@/lib/icons'
import { isAbsolutePath, pathsOverlap } from '@/lib/paths'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const ui = useUiStore()
const library = useLibraryStore()
const { cfg, setVal, saveSection, saving, loadConfig } = useSettingsConfig()

const libs = ref<LibraryEntity[]>([])
// `exts` = 该库类型的**默认扫描白名单**（后端 `/api/libraries` 下发）。前端不自己抄一份 ——
// 抄了就会与扫描口径走散（第 40 期「允许的格式」chips 的默认勾选集就是它）。
const types = ref<{ value: LibraryType; label: string; exts: string[] }[]>([])
const sourceRoots = ref<{ name: string; path: string }[]>([])
const preview = ref<MigrationPreview | null>(null)
const batches = ref<{ batch_id: string; at: number; done: number; pending: number; failed: number }[]>([])
const loading = ref(false)
const busy = ref('')
const detailBatch = ref<MigrationRow[]>([])
const detailOpen = ref(false)
/** 正在展开「每库设置」的书库 id（空 = 收起）：同时只开一个，免得一屏堆满控件 */
const settingsFor = ref('')
/** 同名冲突面板：迁移 / 改名之后要让它重新拉清单 */
const conflicts = ref<InstanceType<typeof LibraryConflictPanel> | null>(null)

function toggleSettings(id: string): void {
  settingsFor.value = settingsFor.value === id ? '' : id
}

const autoMigrate = computed(() => cfg.value?.libraries?.auto_migrate === true)

async function reload(force = false): Promise<void> {
  loading.value = true
  try {
    const res = await api.libraries()
    libs.value = res.items
    types.value = res.types
    sourceRoots.value = res.source_roots ?? []
    await library.loadLibraries(true)
    preview.value = await api.migrationPreview()
    const b = await api.migrationBatches()
    batches.value = b.items
    if (force) await library.loadBooks(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '加载书库信息失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void reload()
  void loadConfig(false, true)
  // 侧栏「库」组的「新增」按钮带 `?new=1` 进来，直达新建向导（见 AppSidebar.onGroupAction）
  if (route.query.new) openWizard()
})

// ---------------- 迁移 ----------------

/** 逐库创建缺失的类型库（**只登记，不搬文件**）。 */
async function createSuggested(): Promise<void> {
  const specs = preview.value?.suggest_specs ?? []
  if (!specs.length) return
  busy.value = 'create'
  try {
    for (const s of specs) {
      await api.createLibrary({
        name: s.name,
        type: s.type,
        source_dirs: s.source_dirs,
      })
    }
    ui.toast(`已创建 ${specs.length} 个书库`)
    await reload()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '创建失败')
  } finally {
    busy.value = ''
  }
}

async function runMigration(): Promise<void> {
  busy.value = 'migrate'
  try {
    const planned = await api.migrationPlan()
    if (!planned.batch_id) {
      ui.toast(planned.message || '没有可迁移的书')
      await reload()
      return
    }
    const res = await api.migrationApply(planned.batch_id)
    ui.toast(`已迁移 ${res.moved ?? 0} 本${res.failed ? `，失败 ${res.failed} 本` : ''}`)
    detailBatch.value = res.items
    detailOpen.value = res.failed > 0
    await reload(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '迁移失败')
  } finally {
    busy.value = ''
  }
}

async function rollbackLast(): Promise<void> {
  busy.value = 'rollback'
  try {
    const res = await api.migrationRollback()
    ui.toast(`已回滚 ${res.restored ?? 0} 本`)
    await reload(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '回滚失败')
  } finally {
    busy.value = ''
  }
}

async function dismissGate(): Promise<void> {
  busy.value = 'dismiss'
  try {
    await api.migrationDismiss('在书库管理页选择暂不迁移')
    ui.toast('已记下「暂不迁移」，之后不再每次启动提示')
    await reload()
  } finally {
    busy.value = ''
  }
}

async function resetGate(): Promise<void> {
  await api.migrationResetGate()
  ui.toast('已恢复启动提示')
  await reload()
}

async function toggleAutoMigrate(): Promise<void> {
  setVal('libraries.auto_migrate', !autoMigrate.value)
  const ok = await saveSection('libraries')
  if (ok) await reload()
}

// ---------------- 新建 / 编辑 ----------------

const dialogOpen = ref(false)
const editingId = ref('')
/**
 * 新建 / 编辑书库的三页签（对齐上游 BookOrbit 的 LIBRARY / CONTENTS / AUTOMATION / LAST SCAN）。
 *
 * 分页签不是为了好看：这三块回答的是**三个不同时刻的问题** ——
 *   内容：这库收什么、放哪（建库时就要定）；
 *   自动化：什么时候扫、要不要刮削（建完再调也行）；
 *   上次扫描：现在健康吗（只有编辑态才有内容）。
 * 一页平铺会像「一次性填 15 个框」，用户根本不知道该看哪。
 */
type DlgTab = 'contents' | 'automation' | 'last_scan'
const dlgTab = ref<DlgTab>('contents')
const DLG_TABS: Array<{ value: DlgTab; label: string }> = [
  { value: 'contents', label: '内容' },
  { value: 'automation', label: '自动化' },
  { value: 'last_scan', label: '上次扫描' },
]

const form = ref({
  name: '',
  type: 'ebook' as LibraryType,
  /** 第 41 期：内容来源 = 多个文件夹的绝对路径（就地引用，跨根合法） */
  source_dirs: [] as string[],
  rules: '',
  /** 刮削出版成品目录（第 18 期）：留空 = 该库不产出硬链接副本 */
  publish_path: '',
  // ---- 自动化（逐库扫描调度，第 17 期 T2 的库实体列）----
  watch: true,
  scan_interval: 0,
  scan_cron: '',
  /** 刮削出版开关（**每库覆盖项**，不是库实体列 → 建库后单独 PUT） */
  scrape_enabled: true,
  // ---- 第 40 期新增的三个库实体列（编辑态用；新建那三个字段在向导里）----
  /** 图标 key（取自 `lib/icons.ts` 的 `ICONS`；空 = 不显示图标） */
  icon: '',
  /** 允许的格式；**空数组 = 继承该库类型的默认白名单**（不是「一个格式都不收」） */
  allowed_exts: [] as string[],
  /**
   * 排除图案的**文本框原样**（换行分隔）。
   *
   * ⚠️ 这里刻意不存 `string[]`：glob 里可能有逗号（`*.{epub,mobi}` 这类
   *   brace 扩展），拿逗号当分隔符会把模式切坏。换行不属于 glob 语法，安全。
   */
  exclude_text: '',
})

/** 用户在编辑弹窗里动过格式勾选没有（同 `ExtChips` 的语义：没动过 = 继承类型默认） */
const fmtTouched = ref(false)
/** 新建向导是否打开（第 40 期；`?new=1` 与「新建书库」按钮都走它） */
const wizardOpen = ref(false)

/** 编辑态：当前正在改的库实体（「上次扫描」页签要读它的历史） */
const editingLib = computed(() => libs.value.find((l) => l.id === editingId.value) || null)

/** 全局的「刮削出版」开关（用于判断该库是继承还是覆写） */
const globalScrape = computed(
  () => ((cfg.value as unknown as { scrape?: { enabled?: boolean } })?.scrape?.enabled) !== false,
)

/** 列表过滤 + 排序（对齐上游工具条的 Filter / Sort） */
const filter = ref('')
const sortBy = ref<'order' | 'name' | 'books' | 'scan'>('order')
const SORTS = [
  { value: 'order', label: '默认顺序' },
  { value: 'name', label: '名称' },
  { value: 'books', label: '书籍数' },
  { value: 'scan', label: '上次扫描' },
]

const visibleLibs = computed(() => {
  const kw = filter.value.trim().toLowerCase()
  const list = libs.value.filter(
    (l) => !kw || `${l.name} ${(l.source_dirs ?? []).join(' ')}`.toLowerCase().includes(kw),
  )
  const by = sortBy.value
  if (by === 'name') return [...list].sort((a, b) => a.name.localeCompare(b.name, 'zh'))
  if (by === 'books') return [...list].sort((a, b) => b.book_count - a.book_count)
  if (by === 'scan') return [...list].sort((a, b) => b.last_scan_at - a.last_scan_at)
  return list
})

/** 时间戳 → 「3 天前」这类相对说法（上游 LAST SCAN 就是这么显示的） */
function ago(ts: number): string {
  if (!ts) return '从未扫描'
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

/** 扫描全部库（上游工具条的 Scan All）：逐库串行，单个失败不打断 */
async function scanAll(): Promise<void> {
  if (!libs.value.length) return
  busy.value = 'scan-all'
  let ok = 0
  try {
    for (const l of libs.value) {
      try {
        await api.scanLibrary(l.id)
        ok += 1
      } catch {
        /* 单库失败继续扫其余，最后统一报数 */
      }
    }
    ui.toast(`已扫描 ${ok} / ${libs.value.length} 个书库，扫描过的书会自动进刮削队列`)
    await reload()
  } finally {
    busy.value = ''
  }
}

function defaultPublish(type: LibraryType): string {
  const base = sourceRoots.value[0]?.path ?? ''
  if (!base) return ''
  const parent = base.replace(/\/[^/]*$/, '')
  return `${parent}/output/${type}-sorted`
}

// ---- 编辑弹窗里的「内容来源」文件夹浏览（复用同一套多来源根下钻）----
const editBrowse = reactive<{
  open: boolean
  loading: boolean
  rootIndex: number
  rootName: string
  rootPath: string
  path: string
  entries: { name: string; path: string; type: 'dir' | 'file' }[]
}>({ open: false, loading: false, rootIndex: -1, rootName: '', rootPath: '', path: '', entries: [] })

const editBrowseAbsPath = computed(() =>
  editBrowse.rootPath ? `${editBrowse.rootPath}${editBrowse.path ? '/' + editBrowse.path : ''}` : '',
)

async function editFetchEntries(): Promise<void> {
  editBrowse.loading = true
  editBrowse.entries = []
  try {
    const res = await api.librarySourceDirs({ root: editBrowse.rootIndex, path: editBrowse.path })
    editBrowse.entries = res.entries ?? []
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '读取服务器目录失败')
  } finally {
    editBrowse.loading = false
  }
}

function editOpenRoot(i: number): void {
  const r = sourceRoots.value[i]
  if (!r) return
  editBrowse.rootIndex = i
  editBrowse.rootName = r.name
  editBrowse.rootPath = r.path
  editBrowse.path = ''
  editBrowse.open = true
  void editFetchEntries()
}

function editDrill(d: { name: string; path: string; type: 'dir' | 'file' }): void {
  if (d.type !== 'dir') return
  editBrowse.path = editBrowse.path ? `${editBrowse.path}/${d.name}` : d.name
  void editFetchEntries()
}

function editBrowseUp(): void {
  if (!editBrowse.path) {
    editBrowse.open = false
    return
  }
  const parts = editBrowse.path.split('/')
  parts.pop()
  editBrowse.path = parts.join('/')
  void editFetchEntries()
}

function editAddFolder(): void {
  const abs = editBrowseAbsPath.value
  if (!abs) return
  if (!form.value.source_dirs.includes(abs)) form.value.source_dirs.push(abs)
}

function editRemoveDir(p: string): void {
  form.value.source_dirs = form.value.source_dirs.filter((d) => d !== p)
}

/** 图标 key 的**唯一真相源**在前端（`lib/icons.ts`）；后端只存 key，不维护白名单。 */
const ICON_NAMES = Object.keys(ICONS)

/** 某库类型的**默认扫描白名单**（来自 `/api/libraries` 的 `types[].exts`，不在前端抄一份） */
function extsOf(type: LibraryType): string[] {
  return types.value.find((t) => t.value === type)?.exts ?? []
}

/**
 * 成品目录的**本地预检**（后端仍会再校验一次，这里只为即时反馈）。
 * 与后端 `_publish_path_allowed` 同口径：不得与任何库根 / 扫描源目录相交 ——
 * 相交意味着副本会被扫描回来变成重复书，改名 / 回收也会误伤副本。
 */
const publishIssue = computed(() => {
  const raw = form.value.publish_path.trim()
  if (!raw) return ''
  // 判据与归一化都在 `@/lib/paths`（与向导共用一份）—— 原来这里写死 `startsWith('/')`、
  // 比较时只认 `/`，Windows 上既会把 `C:\…` 判成非法、又让重叠检测恒为假。
  if (!isAbsolutePath(raw)) return '请输入绝对路径'
  for (const l of libs.value) {
    for (const g of l.source_dirs ?? []) {
      if (pathsOverlap(raw, g)) {
        return `与书库「${l.name}」的内容来源文件夹（${g}）重叠：副本会被扫描回来变成重复书`
      }
    }
  }
  return ''
})

/**
 * 第 40 期：**新建走向导**（`LibraryWizard`），编辑仍走下面这个三页签弹窗。
 *
 * 上游那份向导就叫 *Create a library* —— 它回答的是「建库那一刻该回答哪些问题」；
 * 编辑要回答的是另一组问题（「上次扫描健康吗」只在编辑态才有内容）。共用一套表单
 * 会互相将就，所以分成两条路。
 */
function openWizard(): void {
  wizardOpen.value = true
}

/** 向导建库成功：关掉浮层并把列表 / 迁移预览整体刷一遍（新库会影响它们）。 */
async function onWizardCreated(): Promise<void> {
  wizardOpen.value = false
  await reload()
}

async function openEdit(l: LibraryEntity): Promise<void> {
  editingId.value = l.id
  dlgTab.value = 'contents'
  fmtTouched.value = l.allowed_exts.length > 0
  form.value = {
    name: l.name,
    type: l.type,
    source_dirs: [...(l.source_dirs ?? [])],
    rules: l.rules,
    publish_path: l.publish_path ?? '',
    watch: l.watch !== 0,
    scan_interval: l.scan_interval ?? 0,
    scan_cron: l.scan_cron ?? '',
    scrape_enabled: true,
    icon: l.icon ?? '',
    allowed_exts: [...(l.allowed_exts ?? [])],
    // 排除图案在编辑弹窗里用**换行分隔的文本框**（见模板注释），这里做一次往返转换
    exclude_text: (l.exclude ?? []).join('\n'),
  }
  dialogOpen.value = true
  // 刮削出版开关是**每库覆盖项**（不是库实体列），单独取一次生效值
  try {
    const s = await api.librarySettings(l.id)
    form.value.scrape_enabled = s.values['scrape.enabled'] !== false
  } catch {
    /* 取不到就按默认「开」显示；保存时只在用户真的改过才写覆盖 */
  }
}

/** 编辑保存（第 40 期起这里**只管编辑** —— 新建在 `LibraryWizard` 里）。 */
async function submitDialog(): Promise<void> {
  const lid = editingId.value
  if (!lid) {
    // 弹窗只在编辑态打开；真走到这里说明打开了空弹窗 —— 宁可什么都不做也不许建出半个库
    ui.toast('没有正在编辑的书库')
    return
  }
  busy.value = 'save'
  try {
    const payload = {
      name: form.value.name.trim(),
      type: form.value.type,
      source_dirs: form.value.source_dirs,
      rules: form.value.rules,
      publish_path: form.value.publish_path.trim(),
      watch: form.value.watch ? 1 : 0,
      scan_interval: Number(form.value.scan_interval) || 0,
      scan_cron: form.value.scan_cron.trim(),
      icon: form.value.icon,
      // 没动过勾选 ⇒ 发空数组 = 恢复「继承类型默认」（同 `ExtChips` 的语义）
      allowed_exts: fmtTouched.value ? form.value.allowed_exts : [],
      exclude: form.value.exclude_text
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
    }
    await api.updateLibrary(lid, payload)
    // 「刮削出版」是**每库覆盖项**，只能建库之后再写：
    // 与全局一致 → 恢复继承（不留覆盖，以后全局改了它跟着变）；
    // 与全局不同 → 写死覆盖（这正是「这个库单独关掉」的表达）。
    if (form.value.scrape_enabled !== globalScrape.value) {
      await api.librarySettingsUpdate(lid, { 'scrape.enabled': form.value.scrape_enabled })
    } else {
      await api.librarySettingsReset(lid, ['scrape.enabled'])
    }
    ui.toast('书库已更新')
    dialogOpen.value = false
    await reload()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    busy.value = ''
  }
}

async function scan(l: LibraryEntity): Promise<void> {
  busy.value = `scan:${l.id}`
  try {
    const res = await api.scanLibrary(l.id)
    ui.toast(`「${l.name}」扫描完成：${res.count} 本`)
    await reload()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '扫描失败')
  } finally {
    busy.value = ''
  }
}

async function remove(l: LibraryEntity): Promise<void> {
  if (l.book_count > 0) {
    ui.toast(`「${l.name}」还有 ${l.book_count} 本书：请先迁移走（移除登记不会动文件）`)
    return
  }
  if (!window.confirm(`移除书库「${l.name}」的登记？（**不会删除任何文件**）`)) return
  busy.value = `del:${l.id}`
  try {
    await api.deleteLibrary(l.id)
    ui.toast('已移除登记')
    await reload()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '移除失败')
  } finally {
    busy.value = ''
  }
}

</script>

<template>
  <div class="space-y-4">
    <!-- 1) 迁移确认 -->
    <Card v-if="preview && preview.total > 0" padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-medium text-foreground">按格式归库</span>
          <Badge tone="accent">待迁移 {{ preview.total }}</Badge>
          <Badge v-if="preview.conflict">同名冲突 {{ preview.conflict }}</Badge>
          <Badge v-if="preview.no_library">缺目标库 {{ preview.no_library }}</Badge>
          <span class="ml-auto text-[11.5px] text-muted-foreground">
            迁移只<strong>挪库不改名</strong>，进度与批注不会断链
          </span>
        </div>
        <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          电子书 / 漫画 / 有声书按<strong>格式</strong>分到各自的库；同名文件一律拒绝覆盖并给出建议名
          （改名会换 book_id，所以只建议、不自动改）。
        </div>
      </div>

      <!-- 缺失的类型库：列出默认内容来源（就地引用，多文件夹） -->
      <div v-if="preview.suggest_specs.length" class="border-b border-border px-4 py-3">
        <div class="text-[12.5px] text-foreground">
          还缺 {{ preview.suggest_specs.length }} 个类型库（{{ preview.missing_labels.join('、') }}）——
          默认内容来源已给出，确认后一并创建（建完可在书库管理里调整）
        </div>
        <div
          v-for="s in preview.suggest_specs"
          :key="s.id"
          class="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-2"
        >
          <Badge>{{ s.name }}</Badge>
          <code class="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
            {{ s.source_dirs.join('、') || '（未给出内容来源）' }}
          </code>
        </div>
        <div class="mt-2">
          <Button size="sm" :disabled="busy === 'create'" @click="createSuggested">
            {{ busy === 'create' ? '创建中…' : `创建这 ${preview.suggest_specs.length} 个书库` }}
          </Button>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2 px-4 py-3">
        <Button
          size="sm"
          :disabled="!!busy || preview.movable === 0"
          @click="runMigration"
        >
          {{ busy === 'migrate' ? '迁移中…' : `执行迁移（${preview.movable} 本）` }}
        </Button>
        <Button size="sm" variant="ghost" :disabled="!!busy" @click="rollbackLast">
          回滚上次迁移
        </Button>
        <Button v-if="!preview.gate.dismissed" size="sm" variant="ghost" :disabled="!!busy" @click="dismissGate">
          暂不迁移
        </Button>
        <Button v-else size="sm" variant="ghost" @click="resetGate">恢复启动提示</Button>
        <label class="ml-auto flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <input type="checkbox" :checked="autoMigrate" :disabled="saving" @change="toggleAutoMigrate" />
          以后自动执行（不再确认）
        </label>
      </div>

      <div v-if="preview.blocked" class="border-t border-border px-4 py-2 text-[11.5px] text-muted-foreground">
        有 {{ preview.blocked }} 条被拦下（同名冲突 / 需指定目标库），它们不会被迁移 ——
        处理后可再次点「执行迁移」。
      </div>
    </Card>

    <!-- 2) 书库列表 -->
    <Card padding="none">
      <!-- 工具条：对齐上游（Scan All / Add Library / Filter / Sort） -->
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-medium text-foreground">书库</span>
          <Badge>{{ visibleLibs.length }} / {{ libs.length }}</Badge>
          <div class="ml-auto flex flex-wrap items-center gap-2">
            <input
              v-model="filter"
              type="text"
              placeholder="过滤书库…"
              aria-label="过滤书库"
              class="h-8 w-40 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
            />
            <select
              v-model="sortBy"
              aria-label="排序方式"
              class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
            >
              <option v-for="s in SORTS" :key="s.value" :value="s.value">{{ s.label }}</option>
            </select>
            <Button size="sm" :disabled="!!busy" @click="scanAll">
              {{ busy === 'scan-all' ? '扫描中…' : '全部扫描' }}
            </Button>
            <Button size="sm" variant="primary" @click="openWizard">新建书库</Button>
          </div>
        </div>
        <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          内容来源父目录（已配置的来源根，就地引用直接引用其下级子目录，不搬文件）：<code>{{ sourceRoots.length ? sourceRoots.map(r => r.name).join('、') : '—' }}</code>
        </div>
      </div>

      <div v-if="loading && !libs.length" class="px-4 py-6 text-[12.5px] text-muted-foreground">加载中…</div>
      <!-- 0 库是**全新部署的正常初始态**（第 37 期起不设默认库），所以这里不是
           「出错了」而是「第一步在这」：说清建库要填什么、点哪里（第 38 期）。 -->
      <div v-else-if="!libs.length" class="px-4 py-6">
        <div class="text-[12.5px] font-medium text-foreground">还没有书库</div>
        <p class="mt-1 max-w-[62ch] text-[12.5px] leading-relaxed text-muted-foreground">
          书要落进书库才有位置：新建一个书库、选好它的来源目录，之后从「探索发现」下载、
          在「本地转换」上传、或往投递目录里放文件才会被接收 —— 在此之前它们一律会被拒收。
          点右上角「新建书库」开始。
        </p>
      </div>
      <div
        v-else-if="!visibleLibs.length"
        class="px-4 py-6 text-[12.5px] text-muted-foreground"
      >
        没有匹配「{{ filter }}」的书库。
      </div>

      <!--
        每库一块，四栏对齐上游 BookOrbit 的 LIBRARY / CONTENTS / AUTOMATION / LAST SCAN：
        这样「这个库怎么建的」「它现在健康吗」不用点开就能看全。
      -->
      <div
        v-for="l in visibleLibs"
        :key="l.id"
        class="border-b border-border px-4 py-3 last:border-b-0"
      >
        <div class="flex flex-wrap items-center gap-2">
          <!-- 第 40 期：建库时选的图标要在**这里**看得见，否则那个选择器就是假交互 -->
          <Icon
            v-if="l.icon"
            :name="l.icon"
            class="h-4 w-4 shrink-0 text-muted-foreground"
            :title="l.icon"
          />
          <span class="text-[12.5px] font-medium text-foreground">{{ l.name }}</span>
          <Badge v-if="l.publish_path" tone="ok">刮削出版</Badge>
          <div class="ml-auto flex shrink-0 gap-1">
            <Button size="sm" variant="ghost" @click="toggleSettings(l.id)">
              {{ settingsFor === l.id ? '收起设置' : '设置' }}
            </Button>
            <Button size="sm" variant="ghost" :disabled="!!busy" @click="scan(l)">
              {{ busy === `scan:${l.id}` ? '扫描中…' : '扫描' }}
            </Button>
            <Button size="sm" variant="ghost" @click="openEdit(l)">编辑</Button>
            <Button
              size="sm"
              variant="ghost"
              :disabled="!!busy"
              @click="remove(l)"
            >
              移除
            </Button>
          </div>
        </div>

        <div class="mt-2 grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <div class="text-[10.5px] font-semibold tracking-[0.06em] text-muted-foreground">书库</div>
            <div class="mt-1 flex flex-wrap items-center gap-1">
              <Badge tone="accent">{{ l.type_label }}</Badge>
              <Badge v-if="!(l.source_dirs ?? []).length">未设内容来源</Badge>
              <Badge v-else-if="!l.exists">内容来源不存在</Badge>
              <Badge v-else-if="!l.writable">只读</Badge>
            </div>
          </div>

          <div class="min-w-0">
            <div class="text-[10.5px] font-semibold tracking-[0.06em] text-muted-foreground">内容来源</div>
            <div class="mt-1 text-[11.5px] text-foreground">{{ l.book_count }} 本</div>
            <div v-if="(l.source_dirs ?? []).length" class="mt-0.5 flex flex-col gap-0.5">
              <div
                v-for="d in l.source_dirs"
                :key="d"
                class="truncate text-[11px] text-muted-foreground"
                :title="d"
              >{{ d }}</div>
            </div>
            <div v-else class="mt-0.5 text-[11px] text-muted-foreground">（未设内容来源）</div>
            <div
              v-if="l.publish_path"
              class="truncate text-[11px] text-muted-foreground"
              :title="l.publish_path"
            >
              成品目录 {{ l.publish_path }}
              <span v-if="!l.publish_exists" class="text-destructive">（尚不存在）</span>
              <span v-else-if="!l.publish_writable" class="text-destructive">（不可写）</span>
            </div>
          </div>

          <div>
            <div class="text-[10.5px] font-semibold tracking-[0.06em] text-muted-foreground">自动化</div>
            <div class="mt-1 text-[11.5px] text-muted-foreground">
              {{ l.watch !== 0 ? '监听中' : '未监听' }} ·
              {{ l.scan_cron ? `定时 ${l.scan_cron}` : l.scan_interval ? `每 ${l.scan_interval}s` : '按全局间隔' }}
            </div>
            <div class="text-[11px] text-muted-foreground">
              刮削出版：{{ l.publish_path ? '已配成品目录' : '未配成品目录' }}
            </div>
          </div>

          <div class="min-w-0">
            <div class="text-[10.5px] font-semibold tracking-[0.06em] text-muted-foreground">上次扫描</div>
            <div class="mt-1 text-[11.5px] text-foreground">{{ ago(l.last_scan_at) }}</div>
            <div
              v-if="l.last_scan_note"
              class="truncate text-[11px] text-muted-foreground"
              :title="l.last_scan_note"
            >
              {{ l.last_scan_note }}
            </div>
          </div>
        </div>
      </div>
    </Card>

    <!-- 2.5) 逐库设置：把投递 / 元数据 / 命名按库分开（未设的项继承全局） -->
    <Card v-if="settingsFor" padding="none">
      <LibrarySettingsPanel :library-id="settingsFor" @changed="reload(true)" />
    </Card>

    <!-- 3) 当前库能力（解释「为什么某些菜单不见了」） -->
    <Card padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-medium text-foreground">当前库：{{ library.currentLibraryName }}</span>
          <Badge v-if="!library.currentLibraryId" tone="accent">不裁剪</Badge>
        </div>
        <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          侧栏导航 / 工具标签 / 设置项 / 仪表盘部件按<strong>当前库的能力</strong>裁剪；
          选「全部书库」时不做任何裁剪。
        </div>
      </div>
      <div class="flex flex-wrap gap-1.5 px-4 py-3">
        <Badge v-for="f in library.features" :key="f" tone="accent">
          {{ library.featureLabels[f] || f }}
        </Badge>
        <span v-if="!library.features.length" class="text-[11.5px] text-muted-foreground">
          （全部书库：不裁剪）
        </span>
      </div>
    </Card>

    <!-- 3.5) 同名冲突：book_id 由文件名派生，跨库同名会撞同一个 id -->
    <Card padding="none">
      <LibraryConflictPanel ref="conflicts" @changed="reload(true)" />
    </Card>

    <!-- 迁移台账 -->
    <Card v-if="batches.length" padding="none">
      <div class="border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">迁移台账</span>
        <span class="ml-2 text-[11.5px] text-muted-foreground">最近 {{ batches.length }} 个批次</span>
      </div>
      <div
        v-for="b in batches"
        :key="b.batch_id"
        class="flex items-center gap-3 border-b border-border px-4 py-2 text-[11.5px] last:border-b-0"
      >
        <code class="text-foreground">{{ b.batch_id }}</code>
        <span class="text-muted-foreground">成功 {{ b.done }}</span>
        <span v-if="b.pending" class="text-muted-foreground">待处理 {{ b.pending }}</span>
        <span v-if="b.failed" class="text-destructive">失败 {{ b.failed }}</span>
      </div>
    </Card>

    <!-- 明细（迁移后失败项） -->
    <Card v-if="detailOpen && detailBatch.length" padding="none">
      <div class="border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">本次明细</span>
        <Button size="sm" variant="ghost" class="ml-2" @click="detailOpen = false">收起</Button>
      </div>
      <div
        v-for="r in detailBatch"
        :key="r.id"
        class="flex items-center gap-3 border-b border-border px-4 py-2 text-[11.5px] last:border-b-0"
      >
        <Badge :tone="r.status === 'done' ? 'accent' : undefined">{{ r.status }}</Badge>
        <span class="min-w-0 flex-1 truncate" :title="r.src">{{ r.src }}</span>
        <span v-if="r.error" class="text-destructive">{{ r.error }}</span>
      </div>
    </Card>

    <!--
      新建向导（第 40 期）。与下面那个编辑弹窗**互斥**：同一个时刻只该有一层浮层，
      否则两个 z-50 叠在一起，用户按 Esc 或点空白关掉上面那个之后会以为「关不掉」。
    -->
    <LibraryWizard
      v-if="wizardOpen"
      :types="types"
      :source-roots="sourceRoots"
      :libs="libs"
      @close="wizardOpen = false"
      @created="onWizardCreated"
    />

    <!-- 编辑弹窗（第 40 期起**只管编辑** —— 新建一律走向导） -->
    <div
      v-if="dialogOpen"
      class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4"
      @click.self="dialogOpen = false"
    >
      <div class="w-[min(34rem,94vw)] rounded-lg border border-border bg-card p-5 shadow-2xl">
        <h3 class="font-serif text-[16px] font-semibold text-foreground">
          编辑书库
        </h3>

        <!-- 三页签：内容 / 自动化 / 上次扫描（对齐上游的 LIBRARY-CONTENTS / AUTOMATION / LAST SCAN） -->
        <div class="mt-3 mb-3 flex gap-4 border-b border-border" role="tablist">
          <button
            v-for="t in DLG_TABS"
            :key="t.value"
            type="button"
            role="tab"
            :aria-selected="dlgTab === t.value"
            class="-mb-px cursor-pointer border-b-2 px-0.5 pb-2 text-[12.5px] font-medium transition-colors"
            :class="
              dlgTab === t.value
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            "
            @click="dlgTab = t.value"
          >
            {{ t.label }}
          </button>
        </div>

        <div v-if="dlgTab === 'contents'" class="space-y-3">
          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">名称</div>
            <input
              v-model="form.name"
              class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              placeholder="如：漫画库"
            />
          </div>

          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">类型（决定功能显隐）</div>
            <div class="flex flex-wrap gap-1">
              <Button
                v-for="t in types"
                :key="t.value"
                size="sm"
                :variant="form.type === t.value ? 'primary' : 'ghost'"
                @click="form.type = t.value"
              >
                {{ t.label }}
              </Button>
            </div>
          </div>

          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">
              内容来源（就地引用，可从多个来源根选多个文件夹）
            </div>
            <div class="grid grid-cols-2 gap-2">
              <button
                v-for="(r, i) in sourceRoots"
                :key="r.path"
                type="button"
                class="flex flex-col items-start gap-0.5 rounded-md border border-border bg-transparent px-3 py-2 text-left transition-colors hover:border-primary hover:bg-muted"
                @click="editOpenRoot(i)"
              >
                <span class="text-[12.5px] font-medium text-foreground">{{ r.name }}</span>
                <span class="truncate text-[11px] text-muted-foreground">{{ r.path }}</span>
                <span class="mt-0.5 text-[10.5px] text-primary">浏览…</span>
              </button>
            </div>
            <div v-if="!sourceRoots.length" class="mt-1 text-[11px] text-muted-foreground">
              未检测到已配置的来源根，请在 compose 中配置 LIBRARY_SOURCE_DIRS1..N 后重试。
            </div>
          </div>

          <div v-if="editBrowse.open" class="rounded-md border border-border">
            <div class="flex items-center gap-2 border-b border-border px-3 py-2">
              <button
                type="button"
                class="rounded px-1.5 py-0.5 text-[11.5px] text-muted-foreground hover:bg-muted hover:text-foreground"
                @click="editBrowseUp"
              >
                ↑ 返回
              </button>
              <span class="min-w-0 flex-1 truncate text-[11.5px] text-foreground">
                {{ editBrowse.rootName }} / {{ editBrowse.path || '（根）' }}
              </span>
            </div>
            <div class="max-h-48 overflow-y-auto p-1">
              <div v-if="editBrowse.loading" class="px-2 py-2 text-[11.5px] text-muted-foreground">加载中…</div>
              <template v-else-if="editBrowse.entries.length">
                <button
                  v-for="d in editBrowse.entries"
                  :key="d.path"
                  type="button"
                  class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px]"
                  :class="d.type === 'dir' ? 'cursor-pointer text-foreground hover:bg-muted' : 'cursor-default text-muted-foreground'"
                  @click="editDrill(d)"
                >
                  <Icon :name="d.type === 'dir' ? 'folder' : 'file'" class="h-3.5 w-3.5 shrink-0" />
                  <span class="min-w-0 flex-1 truncate">{{ d.name }}</span>
                </button>
              </template>
              <div v-else class="px-2.5 py-2 text-[11.5px] text-muted-foreground">（此目录下没有子项）</div>
            </div>
            <div class="border-t border-border px-3 py-2">
              <Button size="sm" variant="primary" :disabled="!editBrowseAbsPath" @click="editAddFolder">
                添加此文件夹{{ editBrowseAbsPath ? `（${editBrowseAbsPath}）` : '' }}
              </Button>
            </div>
          </div>

          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">
              已选内容来源（{{ form.source_dirs.length }} 个）
            </div>
            <div v-if="form.source_dirs.length" class="flex flex-wrap gap-1.5">
              <span
                v-for="d in form.source_dirs"
                :key="d"
                class="flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-[11.5px] text-foreground"
              >
                <Icon name="folder" class="h-3 w-3 shrink-0 text-muted-foreground" />
                <span class="min-w-0 flex-1 truncate">{{ d }}</span>
                <button
                  type="button"
                  class="ml-0.5 text-muted-foreground hover:text-destructive"
                  @click="editRemoveDir(d)"
                >
                  ✕
                </button>
              </span>
            </div>
            <div v-else class="text-[11px] text-muted-foreground">尚未选择任何文件夹。</div>
          </div>

          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">归类关键词（逗号分隔）</div>
            <input
              v-model="form.rules"
              placeholder="如：科幻, 太空"
              class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
            />
          </div>

          <!-- 成品目录（第 18 期）：刮削后的硬链接副本落点，供外部阅读器挂载 -->
          <div>
            <div class="mb-1 flex items-center gap-2 text-[11.5px] text-muted-foreground">
              成品目录（刮削出版）
              <Button
                size="sm"
                variant="ghost"
                class="ml-auto"
                @click="form.publish_path = defaultPublish(form.type)"
              >
                用建议路径
              </Button>
            </div>
            <input
              v-model="form.publish_path"
              :placeholder="`留空 = 不产出副本（建议 ${defaultPublish(form.type)}）`"
              class="w-full rounded-md border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              :class="publishIssue ? 'border-destructive' : 'border-border'"
            />
            <div v-if="publishIssue" class="mt-1 text-[11px] text-destructive">{{ publishIssue }}</div>
            <div v-else class="mt-1 text-[11px] text-muted-foreground">
              刮削出的元数据写进这里的<strong>硬链接副本</strong>（原书文件永远不改），外部阅读器
              （Komga 等）挂载此目录即可读到整理完成的书。<strong>不得</strong>与库根或扫描源目录重叠
              —— 副本会被扫回来变成重复书。
            </div>
            <div class="mt-1 text-[11px] text-muted-foreground">
              副本文件名沿用命名规则 + 系列布局；想为本库单独指定规则，保存后在列表里点
              「设置 → 命名规则」。
            </div>
          </div>

          <!-- 第 40 期新增的三个库实体列：图标 / 允许的格式 / 排除图案。
               ⚠️ 这三个字段**只在编辑态有**（新建走 `LibraryWizard`），所以这里不必有默认值逻辑。 -->
          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">图标（书库列表与侧栏的库项上显示）</div>
            <select
              v-model="form.icon"
              class="w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
            >
              <option value="">不显示图标</option>
              <option v-for="n in ICON_NAMES" :key="n" :value="n">{{ n }}</option>
            </select>
          </div>

          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">允许的格式</div>
            <ExtChips
              v-model="form.allowed_exts"
              v-model:touched="fmtTouched"
              :defaults="extsOf(form.type)"
              :type-label="types.find((t) => t.value === form.type)?.label ?? ''"
            />
          </div>

          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">
              排除图案（每行一条 glob；含 / 时匹库内相对路径，否则只匹文件名；大小写敏感）
            </div>
            <!--
              这里用**换行分隔的文本框**而不是向导里那种「添加 → 列表」：
              弹窗已经挤了 9 个字段，而编辑时通常是微调一两条。
              ⚠️ 分隔符必须是换行，不是逗号 —— glob 的 brace 扩展里就有逗号
              （`*.{epub,mobi}`），拿逗号切会把模式切坏。
            -->
            <textarea
              v-model="form.exclude_text"
              rows="3"
              :placeholder="'如：\n*.draft.epub\n备份/*'"
              class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
            />
            <div class="mt-1 text-[11px] text-muted-foreground">
              排除只影响<strong>扫描</strong>：被排除的文件不进书目，文件本身一个字节都不动。
            </div>
          </div>
        </div>

        <!-- ② 自动化：什么时候扫、要不要刮削出版 -->
        <div v-else-if="dlgTab === 'automation'" class="space-y-3">
          <label class="flex items-center gap-2 text-[12.5px] text-foreground">
            <input v-model="form.watch" type="checkbox" />
            监听该库的来源子目录（关掉后只能手动「扫描」）
          </label>

          <div class="flex flex-wrap gap-3">
            <div class="min-w-[9rem] flex-1">
              <div class="mb-1 text-[11.5px] text-muted-foreground">扫描间隔（秒，0 = 跟随全局）</div>
              <input
                v-model.number="form.scan_interval"
                type="number"
                min="0"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              />
            </div>
            <div class="min-w-[9rem] flex-1">
              <div class="mb-1 text-[11.5px] text-muted-foreground">定时扫描（cron，可留空）</div>
              <input
                v-model="form.scan_cron"
                placeholder="如 0 3 * * *"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              />
            </div>
          </div>
          <div class="text-[11px] text-muted-foreground">
            cron 写错了不会让监听整个坏掉 —— 会退化成按间隔扫描（错误只记在扫描备注里）。
          </div>

          <label class="flex items-start gap-2 text-[12.5px] text-foreground">
            <input v-model="form.scrape_enabled" type="checkbox" class="mt-0.5" />
            <span>
              刮削出版（扫描入库后自动抓元数据并写进成品目录的硬链接副本）
              <span class="mt-0.5 block text-[11px] text-muted-foreground">
                默认跟随全局（当前全局：{{ globalScrape ? '开' : '关' }}）；
                与全局不同时才会为该库单独记一条覆盖。没配成品目录的库不会刮削。
              </span>
            </span>
          </label>
        </div>

        <!-- ③ 上次扫描：只有编辑态才有内容 -->
        <div v-else class="space-y-3">
          <template v-if="editingLib">
            <div class="rounded-md border border-border bg-muted px-3 py-2">
              <div class="text-[12px] text-foreground">
                上次扫描：{{ ago(editingLib.last_scan_at) }}（{{ editingLib.book_count }} 本）
              </div>
              <div v-if="editingLib.last_scan_note" class="mt-0.5 text-[11.5px] text-muted-foreground">
                {{ editingLib.last_scan_note }}
              </div>
              <div v-else class="mt-0.5 text-[11.5px] text-muted-foreground">没有备注</div>
            </div>
            <div class="text-[11.5px] leading-relaxed text-muted-foreground">
              扫描 = 重新读一遍库根目录：新文件会被收进书目，被移走的书会从书目里消失。
              开了自动刮削的库，扫描后新书会自动进刮削队列（进度看「工具 → 转换日志 → 刮削」）。
            </div>
            <Button size="sm" :disabled="!!busy" @click="scan(editingLib)">
              {{ busy === `scan:${editingLib.id}` ? '扫描中…' : '立即扫描' }}
            </Button>
          </template>
          <div v-else class="text-[11.5px] leading-relaxed text-muted-foreground">
            这是新书库，还没有扫描记录。保存后到列表里点「扫描」，这里会显示上次扫描时间、
            备注与书目数量。
          </div>
        </div>

        <div class="mt-4 flex justify-end gap-2">
          <Button size="sm" variant="ghost" @click="dialogOpen = false">取消</Button>
          <Button
            size="sm"
            :disabled="busy === 'save' || !form.name.trim() || !!publishIssue"
            @click="submitDialog"
          >
            {{ busy === 'save' ? '保存中…' : '保存' }}
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
