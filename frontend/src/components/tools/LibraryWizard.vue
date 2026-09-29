<script setup lang="ts">
/**
 * 新建书库向导（第 40/55 期）—— 三页签结构，与编辑弹窗（LibrariesView 的
 * 编辑弹窗）**完全对齐**：内容 / 自动化 / 上次扫描。
 *
 * ## 为什么是三页签而不是五步
 *
 * 编辑弹窗就是这三页签（对齐上游 BookOrbit 的 LIBRARY/CONTENTS/AUTOMATION/
 * LAST SCAN）；新建若用另一套结构，用户得记两套心智模型。两者共用同一组
 * 字段组织，只有「提交语义」不同（新建 POST / 编辑 PATCH）。
 *
 * 三块回答的是三个不同时刻的问题：
 *   内容：这库收什么、放哪（建库时就要定）；
 *   自动化：什么时候扫、要不要刮削出版（建完再调也行）；
 *   上次扫描：只有编辑态才有内容 —— 新建时给一句说明，建完扫描后才有数据。
 *
 * ## 两条硬约束（写在这里免得后来人改坏）
 *
 * 1. **不留假交互**：向导状态只在前端内存里，最后一次 POST 建库；
 *    「创建」必须真的建库（有 spec 钉着）。中途不落库 ⇒ 不会留下「建一半的库」。
 * 2. **刮削出版开关是每库覆盖项**：与全局一致 ⇒ 不写覆盖（保持继承），
 *    不同 ⇒ 建库后单独 PUT（同编辑弹窗的口径）。
 *
 * ⚠️ 阅读阈值是每库覆写项，但编辑弹窗也没有内联入口（走「设置 → 命名规则」），
 *   所以这里同样**不提供**内联阅读阈值 —— 建完在列表里点「设置」即可，与编辑一致。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'

import ExtChips from '@/components/tools/ExtChips.vue'
import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import {
  api,
  type LibraryEntity,
  type LibraryType,
} from '@/lib/api'
import { ICONS } from '@/lib/icons'
import { isAbsolutePath, pathsOverlap } from '@/lib/paths'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{
  /** `/api/libraries` 的 `types`（含 `exts` = 该类型的默认扫描白名单） */
  types: { value: LibraryType; label: string; exts: string[] }[]
  /** 已配置的来源根（向导按这些根浏览 / 下钻，数量不定） */
  sourceRoots: { name: string; path: string }[]
  /** 已有书库（成品目录重叠预检要拿它们的库根） */
  libs: LibraryEntity[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', id: string): void
}>()

const ui = useUiStore()

// ---------------------------------------------------------------------------
// 三页签（对齐编辑弹窗的 DLG_TABS：内容 / 自动化 / 上次扫描）
// ---------------------------------------------------------------------------
type DlgTab = 'contents' | 'automation' | 'last_scan'
const dlgTab = ref<DlgTab>('contents')
const DLG_TABS: Array<{ value: DlgTab; label: string }> = [
  { value: 'contents', label: '内容' },
  { value: 'automation', label: '自动化' },
  { value: 'last_scan', label: '上次扫描' },
]
const activeTabLabel = computed(() => DLG_TABS.find((t) => t.value === dlgTab.value)?.label ?? '')

// ---------------------------------------------------------------------------
// 表单
// ---------------------------------------------------------------------------
const form = reactive({
  // 内容
  name: '',
  type: 'ebook' as LibraryType,
  icon: '',
  rules: '',
  publish_path: '',
  allowed_exts: [] as string[],
  /**
   * 排除图案的**文本框原样**（换行分隔）。
   *
   * ⚠️ 这里刻意不存 `string[]`：glob 里可能有逗号（`*.{epub,mobi}` 这类
   *   brace 扩展），拿逗号当分隔符会把模式切坏。换行不属于 glob 语法，安全。
   *   提交时再拆成数组（见 `submit`）。
   */
  exclude_text: '',
  // 自动化
  watch: true,
  scan_interval: 0,
  scan_cron: '',
  /** 刮削出版开关（**每库覆盖项**，不是库实体列 → 建库后单独 PUT） */
  scrape_enabled: true,
})

/** 全局刮削出版开关（用于判断该库是继承还是覆写） */
const globalScrape = ref(true)

/**
 * 已选内容来源文件夹（跨多个来源根多选）。每个条目前端持有「根名 / 相对子目录」用于
 * 展示，**不落库**——落库只存绝对路径（`source_dirs`）。相对子目录由下钻选择时算出。
 */
const selectedDirs = ref<{ path: string; rootName: string; relSubdir: string }[]>([])

/** 用户在「允许的格式」里动过勾选没有（同 `ExtChips` 语义：没动过 = 继承类型默认） */
const fmtTouched = ref(false)

const typeExLabel = computed(() => props.types.find((t) => t.value === form.type)?.label ?? form.type)
/** 当前类型的默认白名单（选完类型就带出来当勾选集） */
const typeExts = computed(() => props.types.find((t) => t.value === form.type)?.exts ?? [])

/**
 * 换类型 ⇒ 勾选集回到新类型的默认。
 *
 * ⚠️ 必须把 `fmtTouched` 也清掉：否则「先选电子书、改了格式、又切成漫画」会把
 * 电子书那个自定义集合带过去，用户看到的勾选与发出去的 payload 还不是一回事。
 */
watch(() => form.type, () => {
  fmtTouched.value = false
  form.allowed_exts = []
})

// ---------------------------------------------------------------------------
// 「建议值」（成品目录）
// ---------------------------------------------------------------------------
/**
 * 用户**手改过**没有。改过的字段从此不再自动重算 —— 否则用户填了一半再回去换类型，
 * 前面填的会被悄悄冲掉。
 */
const touched = reactive({ publish: false })

/**
 * 把没被手改过的建议值重算一遍。
 *
 * 来源根到位（或换类型）后重算成品目录默认位置 —— ⚠️ 向导挂载时父组件的 `reload()`
 * 还没回来，这时 `sourceRoots` 是空，算出来的默认值会丢掉来源根前缀，
 * 所以**必须**等它到位后重算一次。
 */
function resyncDefaults(): void {
  if (!touched.publish) form.publish_path = defaultPublish(form.type)
}

watch(
  [() => props.sourceRoots, () => form.type],
  () => resyncDefaults(),
  { immediate: true },
)

function defaultPublish(type: LibraryType): string {
  const base = props.sourceRoots[0]?.path ?? ''
  if (!base) return ''
  const parent = base.replace(/\/[^/]*$/, '')
  return `${parent}/output/${type}-sorted`
}

// ---------------------------------------------------------------------------
// 服务器目录浏览（第 41 期）—— 多来源根下钻 + 跨根多选文件夹
// ---------------------------------------------------------------------------
const browse = reactive<{
  open: boolean
  loading: boolean
  rootIndex: number
  rootName: string
  rootPath: string
  path: string
  entries: { name: string; path: string; type: 'dir' | 'file' }[]
}>({ open: false, loading: false, rootIndex: -1, rootName: '', rootPath: '', path: '', entries: [] })

/** 当前正在浏览的文件夹的绝对路径（添加此文件夹用） */
const browseAbsPath = computed(() =>
  browse.rootPath ? `${browse.rootPath}${browse.path ? '/' + browse.path : ''}` : '',
)

async function fetchEntries(): Promise<void> {
  browse.loading = true
  browse.entries = []
  try {
    const res = await api.librarySourceDirs({ root: browse.rootIndex, path: browse.path })
    browse.entries = res.entries ?? []
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '读取服务器目录失败')
  } finally {
    browse.loading = false
  }
}

/** 点来源根卡片 ⇒ 从该根顶层开始下钻。 */
function openBrowseRoot(i: number): void {
  const r = props.sourceRoots[i]
  if (!r) return
  browse.rootIndex = i
  browse.rootName = r.name
  browse.rootPath = r.path
  browse.path = ''
  browse.open = true
  void fetchEntries()
}

/** 点目录项 ⇒ 下钻一层（文件不可下钻）。 */
function drillInto(d: { name: string; path: string; type: 'dir' | 'file' }): void {
  if (d.type !== 'dir') return
  browse.path = browse.path ? `${browse.path}/${d.name}` : d.name
  void fetchEntries()
}

/** 返回上一层（已到根则关掉弹层）。 */
function browseUp(): void {
  if (!browse.path) {
    browse.open = false
    return
  }
  const parts = browse.path.split('/')
  parts.pop()
  browse.path = parts.join('/')
  void fetchEntries()
}

/** 把当前浏览的文件夹加进已选（跨根合法；同一路径不重复添加）。 */
function addCurrentFolder(): void {
  const abs = browseAbsPath.value
  if (!abs) return
  if (selectedDirs.value.some((d) => d.path === abs)) {
    ui.toast('该文件夹已在列表中')
    return
  }
  selectedDirs.value.push({ path: abs, rootName: browse.rootName, relSubdir: browse.path })
}

/** 从已选里移除某个文件夹。 */
function removeDir(p: string): void {
  selectedDirs.value = selectedDirs.value.filter((d) => d.path !== p)
}

// ---- 定时扫描预设（**只是 `scan_cron` 的选择器，不新增调度能力**）----
const CRON_PRESETS = [
  { label: '从不', value: '' },
  { label: '每小时', value: '0 * * * *' },
  { label: '每 6 小时', value: '0 */6 * * *' },
  { label: '每 12 小时', value: '0 */12 * * *' },
  { label: '每天', value: '0 4 * * *' },
  { label: '每周', value: '0 4 * * 0' },
] as const

/**
 * 成品目录重叠预检（与后端 `_publish_path_allowed` 同口径，只为即时反馈）。
 *
 * ⚠️ 判据走 `@/lib/paths`，**不在这里写 `startsWith('/')`** —— 那是把后端的
 * `pathlib.Path.resolve()` 抄成了 POSIX 版，Windows 上 `C:\…` 会被判非法：
 * 红字常亮、向导卡在内容页（本机实测过）。编辑弹窗那边用的是同一份。
 */
const publishIssue = computed(() => {
  const raw = form.publish_path.trim()
  if (!raw) return ''
  if (!isAbsolutePath(raw)) return '请输入绝对路径'
  for (const l of props.libs) {
    for (const g of l.source_dirs ?? []) {
      if (pathsOverlap(raw, g)) {
        return `与书库「${l.name}」的内容来源文件夹（${g}）重叠：副本会被扫描回来变成重复书`
      }
    }
  }
  return ''
})

/** 拦停原因（空 = 可创建）。必填只有两步：名称 + 至少一个内容来源文件夹。 */
const blockReason = computed(() => {
  if (!form.name.trim()) return '请填写库名称'
  if (!selectedDirs.value.length) return '请至少选择一个内容来源文件夹'
  if (publishIssue.value) return publishIssue.value
  return ''
})

const busy = ref(false)

/**
 * 建库。三页签下没有「步骤」概念，「创建」始终可点（受 `blockReason` 禁用）；
 * 校验失败不放行（与编辑弹窗一致：不 alert，红字在内容页 + 侧栏提示）。
 */
async function submit(): Promise<void> {
  if (blockReason.value) {
    ui.toast(blockReason.value)
    return
  }
  busy.value = true
  try {
    const res = await api.createLibrary({
      name: form.name.trim(),
      type: form.type,
      // 第 41 期：内容来源 = 多个文件夹的绝对路径（就地引用，跨根合法）。
      source_dirs: selectedDirs.value.map((d) => d.path),
      rules: form.rules,
      publish_path: form.publish_path.trim(),
      watch: form.watch ? 1 : 0,
      scan_interval: Number(form.scan_interval) || 0,
      scan_cron: form.scan_cron.trim(),
      icon: form.icon,
      // ⚠️ 空数组 = **继承类型默认**（不是「一个格式都不收」）——
      //    后端把 `''` 哨兵读成「没设过」，见 core/library.py 的读时回落规则。
      allowed_exts: fmtTouched.value ? form.allowed_exts : [],
      // 排除图案：文本框 → 数组（换行分隔，去空）。
      exclude: form.exclude_text
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
    })
    const lid = res.library.id

    // 刮削出版是**每库覆盖项**，只能建库之后再写：
    // 与全局一致 → 不写覆盖，保持继承（以后全局改了它跟着变）；
    // 与全局不同 → 写死覆盖（这正是「这个库单独关掉」的表达）。
    if (form.scrape_enabled !== globalScrape.value) {
      await api.librarySettingsUpdate(lid, { 'scrape.enabled': form.scrape_enabled })
    }

    ui.toast(`已创建书库「${form.name.trim()}」`)
    emit('created', lid)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '创建失败')
  } finally {
    busy.value = false
  }
}

// ---------------------------------------------------------------------------
// 图标选择器
// ---------------------------------------------------------------------------
/** 图标表**唯一真相源**在前端（`lib/icons.ts`）—— 后端只存 key，不维护白名单。 */
const ICON_NAMES = Object.keys(ICONS)
const iconQuery = ref('')

const iconChoices = computed(() => {
  const q = iconQuery.value.trim().toLowerCase()
  return q ? ICON_NAMES.filter((n) => n.toLowerCase().includes(q)) : ICON_NAMES
})

onMounted(async () => {
  // 取全局配置以决定刮削出版开关的默认值（与全局一致 ⇒ 不写覆盖）。
  // 失败静默（只想知道开关状态，弹「配置加载失败」会误导用户以为功能坏了）。
  try {
    const r = await api.getConfig()
    const c = r.config as unknown as { scrape?: { enabled?: boolean } }
    globalScrape.value = c.scrape?.enabled !== false
  } catch {
    /* 静默：globalScrape 退化为 true（默认开），建库时不会写多余的覆盖 */
  }
  form.scrape_enabled = globalScrape.value
})
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4">
    <div
      class="flex h-[min(38rem,92vh)] w-[min(58rem,96vw)] overflow-hidden rounded-lg border border-border bg-card shadow-2xl"
    >
      <!-- 左：三页签 -->
      <aside class="w-52 shrink-0 border-r border-border bg-muted/40 p-4">
        <div class="mb-3 font-serif text-[15px] font-semibold text-foreground">新建书库</div>
        <ol class="space-y-1">
          <li
            v-for="(t, i) in DLG_TABS"
            :key="t.value"
            class="rounded-md"
            :class="dlgTab === t.value ? 'bg-card shadow-sm' : ''"
          >
            <button
              type="button"
              class="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left"
              :data-test="`wizard-tab-${t.value}`"
              @click="dlgTab = t.value"
            >
              <span
                class="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border text-[10px]"
                :class="
                  dlgTab === t.value
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-border text-muted-foreground'
                "
              >
                {{ i + 1 }}
              </span>
              <span class="min-w-0">
                <span
                  class="block text-[12.5px]"
                  :class="dlgTab === t.value ? 'font-medium text-foreground' : 'text-muted-foreground'"
                >
                  {{ t.label }}
                  <span v-if="(t.value === 'contents')" class="text-destructive" title="必填">*</span>
                </span>
                <span class="block text-[11px] text-muted-foreground">
                  {{
                    t.value === 'contents'
                      ? '收什么、放哪'
                      : t.value === 'automation'
                        ? '何时扫、刮不刮'
                        : '健康与否'
                  }}
                </span>
              </span>
            </button>
          </li>
        </ol>
        <div
          v-if="blockReason"
          class="mt-3 rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-[11px] leading-relaxed text-destructive"
        >
          {{ blockReason }}
        </div>
      </aside>

      <!-- 右：内容 -->
      <section class="flex min-w-0 flex-1 flex-col">
        <div class="min-h-0 flex-1 overflow-y-auto p-5">
          <!-- ① 内容 -->
          <div v-if="dlgTab === 'contents'" class="space-y-4">
            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">库名称 *</div>
              <input
                v-model="form.name"
                data-test="wizard-name"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
                placeholder="如：漫画库"
              />
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">库类型（决定功能显隐与默认格式）</div>
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
                图标（可选）—— 建完会显示在书库列表与侧栏的库项上
              </div>
              <input
                v-model="iconQuery"
                class="mb-2 w-40 rounded-md border border-border bg-transparent px-2.5 py-1 text-[12px] text-foreground outline-none focus:border-primary"
                placeholder="筛选图标名"
              />
              <div class="grid max-h-40 grid-cols-8 gap-1 overflow-y-auto pr-1">
                <button
                  type="button"
                  data-test="wizard-icon-none"
                  class="grid h-8 place-items-center rounded-md border text-[10px]"
                  :class="form.icon === '' ? 'border-primary text-foreground' : 'border-border text-muted-foreground'"
                  title="不显示图标"
                  @click="form.icon = ''"
                >
                  无
                </button>
                <button
                  v-for="n in iconChoices"
                  :key="n"
                  type="button"
                  :data-test="`wizard-icon-${n}`"
                  class="grid h-8 place-items-center rounded-md border"
                  :class="
                    form.icon === n
                      ? 'border-primary bg-primary/10 text-foreground'
                      : 'border-border text-muted-foreground hover:text-foreground'
                  "
                  :title="n"
                  @click="form.icon = n"
                >
                  <Icon :name="n" class="h-4 w-4" />
                </button>
              </div>
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                内容来源（就地引用，不搬文件）—— 可从多个来源根选多个文件夹，一个库对应多个文件夹
              </div>
              <div class="grid grid-cols-2 gap-2">
                <button
                  v-for="(r, i) in sourceRoots"
                  :key="r.path"
                  type="button"
                  data-test="wizard-root-card"
                  class="flex flex-col items-start gap-0.5 rounded-md border border-border bg-transparent px-3 py-2 text-left transition-colors hover:border-primary hover:bg-muted"
                  @click="openBrowseRoot(i)"
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

            <!-- 下钻浏览面板 -->
            <div v-if="browse.open" class="rounded-md border border-border">
              <div class="flex items-center gap-2 border-b border-border px-3 py-2">
                <button
                  type="button"
                  data-test="wizard-browse-up"
                  class="rounded px-1.5 py-0.5 text-[11.5px] text-muted-foreground hover:bg-muted hover:text-foreground"
                  @click="browseUp"
                >
                  ↑ 返回
                </button>
                <span class="min-w-0 flex-1 truncate text-[11.5px] text-foreground">
                  {{ browse.rootName }} / {{ browse.path || '（根）' }}
                </span>
              </div>
              <div class="max-h-56 overflow-y-auto p-1">
                <div v-if="browse.loading" class="px-2 py-2 text-[11.5px] text-muted-foreground">加载中…</div>
                <template v-else-if="browse.entries.length">
                  <button
                    v-for="d in browse.entries"
                    :key="d.path"
                    type="button"
                    :data-test="`wizard-browse-${d.type}`"
                    class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px]"
                    :class="d.type === 'dir' ? 'cursor-pointer text-foreground hover:bg-muted' : 'cursor-default text-muted-foreground'"
                    @click="drillInto(d)"
                  >
                    <Icon :name="d.type === 'dir' ? 'folder' : 'file'" class="h-3.5 w-3.5 shrink-0" />
                    <span class="min-w-0 flex-1 truncate">{{ d.name }}</span>
                  </button>
                </template>
                <div v-else class="px-2.5 py-2 text-[11.5px] text-muted-foreground">（此目录下没有子项）</div>
              </div>
              <div class="border-t border-border px-3 py-2">
                <Button size="sm" variant="primary" data-test="wizard-pick-folder" :disabled="!browseAbsPath" @click="addCurrentFolder">
                  添加此文件夹{{ browseAbsPath ? `（${browseAbsPath}）` : '' }}
                </Button>
              </div>
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                已选内容来源（跨根合计 {{ selectedDirs.length }} 个）
              </div>
              <div v-if="selectedDirs.length" class="flex flex-wrap gap-1.5">
                <span
                  v-for="d in selectedDirs"
                  :key="d.path"
                  data-test="wizard-selected-item"
                  class="flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-[11.5px] text-foreground"
                >
                  <Icon name="folder" class="h-3 w-3 shrink-0 text-muted-foreground" />
                  <span class="font-medium">{{ d.rootName }}</span>
                  <span class="text-muted-foreground">/ {{ d.relSubdir || '（根）' }}</span>
                  <button
                    type="button"
                    data-test="wizard-selected-del"
                    class="ml-0.5 text-muted-foreground hover:text-destructive"
                    @click="removeDir(d.path)"
                  >
                    ✕
                  </button>
                </span>
              </div>
              <div v-else class="text-[11px] text-muted-foreground">
                尚未选择任何文件夹。点击上方来源根浏览并「添加此文件夹」。
              </div>
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                归类关键词（可选，逗号或顿号分隔；格式判不出类型时才生效）
              </div>
              <input
                v-model="form.rules"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
                placeholder="如：科幻、太空"
              />
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                成品目录（可选；空 = 该库不产出副本 —— 它是副本，**不改原书**）
              </div>
              <input
                v-model="form.publish_path"
                data-test="wizard-publish"
                :placeholder="defaultPublish(form.type)"
                class="w-full rounded-md border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
                :class="publishIssue ? 'border-destructive' : 'border-border'"
                @input="touched.publish = true"
              />
              <div v-if="publishIssue" class="mt-1 text-[11px] text-destructive">{{ publishIssue }}</div>
              <div v-else class="mt-1 text-[11px] text-muted-foreground">
                刮削出的元数据写进这里的<strong>硬链接副本</strong>（原书文件永远不改），外部阅读器
                （Komga 等）挂载此目录即可读到整理完成的书。<strong>不得</strong>与库根或扫描源目录重叠
                —— 副本会被扫回来变成重复书。
              </div>
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">允许的格式</div>
              <ExtChips
                v-model="form.allowed_exts"
                v-model:touched="fmtTouched"
                :defaults="typeExts"
                :type-label="typeExLabel"
              />
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                排除图案（每行一条 glob；含 / 时匹库内相对路径，否则只匹文件名；大小写敏感）
              </div>
              <textarea
                v-model="form.exclude_text"
                data-test="wizard-exclude"
                rows="3"
                :placeholder="'如：\n*.draft.epub\n备份/*'"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              />
              <div class="mt-1 text-[11px] text-muted-foreground">
                排除只影响<strong>扫描</strong>：被排除的文件不进书目，文件本身一个字节都不动。
              </div>
            </div>
          </div>

          <!-- ② 自动化 -->
          <div v-else-if="dlgTab === 'automation'" class="space-y-4">
            <label class="flex items-center gap-2 text-[12.5px] text-foreground">
              <input v-model="form.watch" type="checkbox" data-test="wizard-watch" />
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

            <div class="flex flex-wrap gap-1">
              <Button
                v-for="p in CRON_PRESETS"
                :key="p.value"
                size="sm"
                :variant="form.scan_cron === p.value ? 'primary' : 'ghost'"
                :data-test="`wizard-cron-${p.label}`"
                @click="form.scan_cron = p.value"
              >
                {{ p.label }}
              </Button>
            </div>
            <input
              v-model="form.scan_cron"
              class="mt-2 w-56 rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              placeholder="自定义 cron（5 段）"
            />

            <label class="flex items-start gap-2 text-[12.5px] text-foreground">
              <input v-model="form.scrape_enabled" type="checkbox" class="mt-0.5" data-test="wizard-scrape" />
              <span>
                刮削出版（扫描入库后自动抓元数据并写进成品目录的硬链接副本）
                <span class="mt-0.5 block text-[11px] text-muted-foreground">
                  默认跟随全局（当前全局：{{ globalScrape ? '开' : '关' }}）；
                  与全局不同时才会为该库单独记一条覆盖。没配成品目录的库不会刮削。
                </span>
              </span>
            </label>
          </div>

          <!-- ③ 上次扫描：新建态没有内容，给一句说明 -->
          <div v-else class="space-y-3">
            <div class="rounded-md border border-border bg-muted px-3 py-2 text-[12px] text-foreground">
              这是新建书库，还没有扫描记录。
            </div>
            <div class="text-[11.5px] leading-relaxed text-muted-foreground">
              建库并点「扫描」后，这里会显示上次扫描时间、备注与书目数量；开了自动刮削的库，
              扫描后新书会自动进刮削队列（进度看「工具 → 转换日志 → 刮削」）。
            </div>
          </div>
        </div>

        <!-- 底部固定栏 -->
        <footer class="flex items-center gap-2 border-t border-border px-5 py-3">
          <Button size="sm" variant="ghost" data-test="wizard-cancel" :disabled="busy" @click="emit('close')">
            取消
          </Button>
          <span class="mx-auto text-[11.5px] text-muted-foreground">{{ activeTabLabel }}</span>
          <Button
            size="sm"
            variant="primary"
            data-test="wizard-create"
            :disabled="busy || !!blockReason"
            @click="submit"
          >
            创建
          </Button>
        </footer>
      </section>
    </div>
  </div>
</template>
