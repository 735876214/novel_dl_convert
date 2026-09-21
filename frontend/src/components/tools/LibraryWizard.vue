<script setup lang="ts">
/**
 * 新建书库向导（第 40 期）—— 按上游 BookOrbit「Create a library」的**信息结构**重排。
 *
 * ## 为什么另起一个组件，而不是把弹窗改成多步
 *
 * 上游那份向导就叫 *Create a library*，它解决的是**建库那一刻该回答哪些问题**；
 * 而编辑一个已有库要回答的问题不一样（「上次扫描健康吗」只在编辑态才有内容）。
 * 两者共用一套表单会互相将就，所以：**向导只管新建**，编辑沿用三页签弹窗。
 *
 * ## 五步
 *
 * ① 基本信息（名称 / 类型 / 图标，必填）② 内容来源（存放方式 / 库根 / 来源子目录 / 归类关键词 /
 * 成品目录，必填）③ 扫描（允许的格式 / 排除图案）④ 阅读（阅读阈值）⑤ 自动化（监听 / 间隔 / 定时）。
 *
 * 上游的 Step 4 Metadata（源优先级 / 格式优先级）与 Step 7 File updates **整步不做**
 * —— 本项目不写回文件（只落服务端 DB），留一个点进去空白的步骤比少一步更糟。
 *
 * ## 两条硬约束（写在这里免得后来人改坏）
 *
 * 1. **不留假交互**：向导状态只在前端内存里，最后一次 POST 建库；
 *    「立即创建」必须真的建库（有 spec 钉着）。中途不落库 ⇒ 不会留下「建一半的库」。
 * 2. **阅读阈值是每库覆写项，不是库表列** ⇒ 必须先有库才能写。
 *    所以第 ④ 步的值跟编辑弹窗的「刮削出版」一样，是**建完库之后再 PUT**。
 *    与全局一致时**不写覆盖**（保持继承）—— 这样以后改全局它跟着变。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'

import ExtChips from '@/components/tools/ExtChips.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import {
  api,
  type LibraryEntity,
  type LibraryMode,
  type LibraryType,
} from '@/lib/api'
import { ICONS } from '@/lib/icons'
import { isAbsolutePath, pathsOverlap } from '@/lib/paths'
import { ensureThresholds, thresholdsFor } from '@/lib/readingThresholds'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{
  /** `/api/libraries` 的 `types`（含 `exts` = 该类型的默认扫描白名单） */
  types: { value: LibraryType; label: string; exts: string[] }[]
  modes: { value: LibraryMode; label: string }[]
  /** `LIBRARY_SOURCE_DIR` */
  sourceDir: string
  /** 已有书库（成品目录重叠预检要拿它们的库根） */
  libs: LibraryEntity[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', id: string): void
}>()

const ui = useUiStore()

// ---------------------------------------------------------------------------
// 步骤骨架
// ---------------------------------------------------------------------------

/**
 * 步骤条。`required` 的两步是上游标了必填的（Details / Folders）——
 * 其余步骤**全部可跳过**，一路「继续」到底也能建出库（用默认值）。
 */
const STEPS = [
  { id: 'details', label: '基本信息', required: true, hint: '叫什么、是哪一类' },
  { id: 'folders', label: '内容来源', required: true, hint: '从哪儿收、放哪儿' },
  { id: 'scanning', label: '扫描', required: false, hint: '收哪些格式、跳过什么' },
  { id: 'reading', label: '阅读', required: false, hint: '进度到多少算读完' },
  { id: 'automation', label: '自动化', required: false, hint: '什么时候自动扫' },
] as const

type StepId = (typeof STEPS)[number]['id']

const stepIndex = ref(0)
const step = computed<StepId>(() => STEPS[stepIndex.value].id)

/** 前 i 步是否都填完了（步骤条上的勾） */
const done = computed(() => (i: number) => {
  if (i === 0) return Boolean(form.name.trim())
  if (i === 1) return Boolean(form.root_path.trim())
  return i < stepIndex.value
})

// ---------------------------------------------------------------------------
// 表单
// ---------------------------------------------------------------------------

const form = reactive({
  // ① 基本信息
  name: '',
  type: 'ebook' as LibraryType,
  icon: '',
  // ② 内容来源
  mode: 'inplace' as LibraryMode,
  root_path: '',
  source_subdir: '',
  rules: '',
  publish_path: '',
  // ③ 扫描
  allowed_exts: [] as string[],
  exclude: [] as string[],
  // ④ 阅读（`reading_override` 为假 = 继承全局，不写覆盖）
  reading_override: false,
  started: 0,
  finished: 99.5,
  // ⑤ 自动化
  watch: true,
  scan_interval: 0,
  scan_cron: '',
})

/** 用户在第三步**动过**格式勾选没有。没动过就发空数组 = 继承类型默认。 */
const fmtTouched = ref(false)
/** 排除图案的输入框（加一条才进 `form.exclude`） */
const excludeDraft = ref('')

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
// 三个「建议值」（库根 / 来源子目录 / 成品目录）
// ---------------------------------------------------------------------------

/**
 * 用户**手改过**没有。改过的字段从此不再自动重算 —— 否则用户填了一半再回去换类型，
 * 前面填的会被悄悄冲掉。
 *
 * ⚠️ 别用「当前值等不等于默认值」来判断用户动没动过：那样一旦默认值自己变了
 * （换类型 / `sourceDir` 后到），判断的基准就跟着变，结果既留不住用户输入、
 * 也跟不上下拉变化。**记一个显式的 touched 才是唯一稳的**。
 */
const touched = reactive({ root: false, sub: false, publish: false })

/**
 * 把没被手改过的建议值重算一遍。
 *
 * 三件事都会触发它：
 *   · 用户换了库类型 / 存放方式；
 *   · `sourceDir` 从空变成真实值 —— ⚠️ 向导挂载时父组件的 `reload()` 还没回来，
 *     这时算出来的默认值会丢掉来源目录前缀（实测得到一个 `/ebooks` 这种根路径），
 *     所以**必须**等它到位后重算一次。
 */
function resyncDefaults(): void {
  if (!touched.root) form.root_path = defaultRoot(form.mode, form.type)
  if (!touched.sub) form.source_subdir = defaultSourceSubdir()
  if (!touched.publish) form.publish_path = defaultPublish(form.type)
}

watch(
  [() => props.sourceDir, () => form.type],
  () => resyncDefaults(),
  { immediate: true },
)

function defaultSourceSubdir(): string {
  return `${form.type}s`
}

function defaultRoot(mode: LibraryMode, type: LibraryType): string {
  return mode === 'inplace'
    ? `${props.sourceDir}/${type}s`
    : `${props.sourceDir}/../data/libraries/${type}`
}

function defaultPublish(type: LibraryType): string {
  return `${props.sourceDir}/../output/${type}-sorted`
}

/**
 * 切「存放方式」⇒ 库根必须跟着重算（两种模式的库根不是同一个概念）。
 *
 * 这一点与编辑弹窗既有行为一致：**换存放方式不保留旧库根**。
 * 来源子目录 / 成品目录则不受影响（它们与模式无关）。
 */
function pickMode(m: LibraryMode): void {
  form.mode = m
  touched.root = false
  resyncDefaults()
}

function addExclude(): void {
  const v = excludeDraft.value.trim()
  if (!v) return
  if (!form.exclude.includes(v)) form.exclude.push(v)
  excludeDraft.value = ''
}

function removeExclude(i: number): void {
  form.exclude.splice(i, 1)
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
 * 红字常亮、向导卡在第 2 步（本机实测过）。编辑弹窗那边用的是同一份。
 */
const publishIssue = computed(() => {
  const raw = form.publish_path.trim()
  if (!raw) return ''
  if (!isAbsolutePath(raw)) return '请输入绝对路径'
  for (const l of props.libs) {
    const guards: Array<{ label: string; path: string }> = []
    if (l.root_path) guards.push({ label: `书库「${l.name}」的库根`, path: l.root_path })
    if (l.source_subdir) {
      guards.push({
        label: `书库「${l.name}」的扫描源目录`,
        path: `${props.sourceDir}/${l.source_subdir}`,
      })
    }
    for (const g of guards) {
      if (pathsOverlap(raw, g.path)) {
        return `与${g.label}重叠（${g.path}）：副本会被扫描回来变成重复书`
      }
    }
  }
  return ''
})

/** 当前步的**拦停原因**（空 = 放行）。校验失败停在当前步，不 alert。 */
const blocked = computed(() => {
  if (step.value === 'details') {
    if (!form.name.trim()) return '请填写库名称'
    return ''
  }
  if (step.value === 'folders') {
    if (!form.root_path.trim()) return '请填写库根目录'
    if (publishIssue.value) return publishIssue.value
    return ''
  }
  if (step.value === 'reading') {
    if (form.reading_override && form.started >= form.finished) {
      return `「在读下界」必须小于「已读完阈值」（当前 ${form.started}% / ${form.finished}%）`
    }
    return ''
  }
  return ''
})

// ---------------------------------------------------------------------------
// 导航 / 提交
// ---------------------------------------------------------------------------

const maxStep = STEPS.length - 1

function next(): void {
  if (blocked.value) {
    ui.toast(blocked.value)
    return
  }
  if (stepIndex.value < maxStep) stepIndex.value += 1
}

function back(): void {
  if (stepIndex.value > 0) stepIndex.value -= 1
}

const busy = ref(false)

/**
 * 建库。`createNow` 为真 = 「立即创建」：**跳过后续步骤，用当前值直接建**
 * （上游 Any step 的 *Create now*）。
 *
 * 两步必填仍然要过 —— 「立即创建」是「不用再往后点了」，不是「可以不填名字」。
 */
async function submit(createNow = false): Promise<void> {
  if (createNow && stepIndex.value < maxStep) {
    // 只校验必填的两步，不看当前步之后的东西（用户还没看到它们）
    if (!form.name.trim()) {
      stepIndex.value = 0
      ui.toast('请填写库名称')
      return
    }
    if (!form.root_path.trim()) {
      stepIndex.value = 1
      ui.toast('请填写库根目录')
      return
    }
  }
  if (blocked.value) {
    ui.toast(blocked.value)
    return
  }

  busy.value = true
  try {
    const res = await api.createLibrary({
      name: form.name.trim(),
      type: form.type,
      mode: form.mode,
      root_path: form.root_path.trim() || defaultRoot(form.mode, form.type),
      source_subdir: form.source_subdir.trim(),
      rules: form.rules,
      publish_path: form.publish_path.trim(),
      watch: form.watch ? 1 : 0,
      scan_interval: Number(form.scan_interval) || 0,
      scan_cron: form.scan_cron.trim(),
      icon: form.icon,
      // ⚠️ 空数组 = **继承类型默认**（不是「一个格式都不收」）——
      //    后端把 `''` 哨兵读成「没设过」，见 core/library.py 的读时回落规则。
      allowed_exts: fmtTouched.value ? form.allowed_exts : [],
      exclude: form.exclude,
    })
    const lid = res.library.id

    // 阅读阈值是**每库覆写项**，只能建库之后再写（同编辑弹窗的「刮削出版」）。
    // 与全局一致 ⇒ 不写覆盖，保持继承。
    if (form.reading_override) {
      const g = thresholdsFor('')
      const changed = form.started !== g.started || form.finished !== g.finished
      if (changed) {
        await api.librarySettingsUpdate(lid, {
          'reading.started_threshold': form.started,
          'reading.finished_threshold': form.finished,
        })
      }
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

// ---------------------------------------------------------------------------

onMounted(async () => {
  // 三个建议值不在这里设 —— 那会在 `sourceDir` 还没到位时算出一个丢掉前缀的路径。
  // 交给上面那个盯 `props.sourceDir` 的 watch（它带 `immediate`，且来源目录到位后会再跑一次）。
  //
  // 第 ④ 步要显示「继承全局」的实际值，所以先把全局阈值取回来
  await ensureThresholds()
  const g = thresholdsFor('')
  form.started = g.started
  form.finished = g.finished
})
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4">
    <div
      class="flex h-[min(38rem,92vh)] w-[min(58rem,96vw)] overflow-hidden rounded-lg border border-border bg-card shadow-2xl"
    >
      <!-- 左：步骤条 -->
      <aside class="w-52 shrink-0 border-r border-border bg-muted/40 p-4">
        <div class="mb-3 font-serif text-[15px] font-semibold text-foreground">新建书库</div>
        <ol class="space-y-1">
          <li
            v-for="(s, i) in STEPS"
            :key="s.id"
            class="flex items-start gap-2 rounded-md px-2 py-1.5"
            :class="i === stepIndex ? 'bg-card shadow-sm' : ''"
          >
            <span
              class="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border text-[10px]"
              :class="
                done(i) && i !== stepIndex
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border text-muted-foreground'
              "
            >
              <Icon v-if="done(i) && i !== stepIndex" name="check" class="h-3 w-3" />
              <template v-else>{{ i + 1 }}</template>
            </span>
            <span class="min-w-0">
              <span
                class="block text-[12.5px]"
                :class="i === stepIndex ? 'font-medium text-foreground' : 'text-muted-foreground'"
              >
                {{ s.label }}
                <span v-if="s.required" class="text-destructive" title="必填">*</span>
              </span>
              <span class="block text-[11px] text-muted-foreground">{{ s.hint }}</span>
            </span>
          </li>
        </ol>
      </aside>

      <!-- 右：内容 -->
      <section class="flex min-w-0 flex-1 flex-col">
        <div class="min-h-0 flex-1 overflow-y-auto p-5">
          <!-- ① 基本信息 -->
          <div v-if="step === 'details'" class="space-y-4">
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
          </div>

          <!-- ② 内容来源 -->
          <div v-else-if="step === 'folders'" class="space-y-4">
            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">存放方式</div>
              <div class="flex flex-wrap gap-1">
                <Button
                  v-for="m in modes"
                  :key="m.value"
                  size="sm"
                  :variant="form.mode === m.value ? 'primary' : 'ghost'"
                  @click="pickMode(m.value)"
                >
                  {{ m.label }}
                </Button>
              </div>
              <div class="mt-1 text-[11px] text-muted-foreground">
                就地引用 = 直接引用来源子目录（不搬文件）；独立存储 = 库有自己的存储目录，来源目录的文件会导入进来。
              </div>
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">库根目录 *</div>
              <input
                v-model="form.root_path"
                data-test="wizard-root"
                :placeholder="defaultRoot(form.mode, form.type)"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
                @input="touched.root = true"
              />
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                来源子目录（相对 {{ sourceDir }}；放在它里面的文件会自动归入本库）
              </div>
              <input
                v-model="form.source_subdir"
                data-test="wizard-sub"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
                :placeholder="defaultSourceSubdir()"
                @input="touched.sub = true"
              />
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
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
                @input="touched.publish = true"
              />
              <div v-if="publishIssue" class="mt-1 text-[11px] text-destructive">{{ publishIssue }}</div>
            </div>
          </div>

          <!-- ③ 扫描 -->
          <div v-else-if="step === 'scanning'" class="space-y-4">
            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                允许的格式（{{ typeExLabel }} 库）—— 收不了的格式**直接拒收**，
                不会落盘后从书目里消失
              </div>
              <ExtChips
                v-model="form.allowed_exts"
                v-model:touched="fmtTouched"
                :defaults="typeExts"
                :type-label="typeExLabel"
              />
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                排除图案（glob；含 / 时按库内相对路径匹，否则只匹文件名；大小写敏感）
              </div>
              <div class="flex gap-1">
                <input
                  v-model="excludeDraft"
                  data-test="wizard-exclude-input"
                  class="min-w-0 flex-1 rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
                  placeholder="如：*.draft.epub 或 备份/*"
                  @keydown.enter.prevent="addExclude"
                />
                <Button size="sm" data-test="wizard-exclude-add" @click="addExclude">添加</Button>
              </div>
              <ul v-if="form.exclude.length" class="mt-2 space-y-1">
                <li
                  v-for="(p, i) in form.exclude"
                  :key="p"
                  class="flex items-center gap-2 rounded-md border border-border px-2 py-1 text-[11.5px]"
                >
                  <code class="min-w-0 flex-1 truncate">{{ p }}</code>
                  <button
                    type="button"
                    class="text-muted-foreground hover:text-destructive"
                    :data-test="`wizard-exclude-del-${i}`"
                    @click="removeExclude(i)"
                  >
                    删除
                  </button>
                </li>
              </ul>
              <div class="mt-1 text-[11px] text-muted-foreground">
                排除只影响**扫描**：被排除的文件不进书目，文件本身一个字节都不动。
              </div>
            </div>
          </div>

          <!-- ④ 阅读 -->
          <div v-else-if="step === 'reading'" class="space-y-4">
            <div class="text-[11.5px] leading-relaxed text-muted-foreground">
              这两项决定「在读 / 已读完」的判定，统计、书架、成就、Komga 客户端同源。
              默认与全局一致（{{ thresholdsFor('').started }}% / {{ thresholdsFor('').finished }}%）。
            </div>

            <label class="flex items-center gap-2 text-[12.5px] text-foreground">
              <input type="checkbox" v-model="form.reading_override" data-test="wizard-reading-override" />
              本库单独设定（不勾就跟着全局走，以后改全局它跟着变）
            </label>

            <div :class="form.reading_override ? '' : 'pointer-events-none opacity-50'">
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                在读下界：进度高于 {{ form.started }}% 算「在读」
              </div>
              <input
                v-model.number="form.started"
                data-test="wizard-started"
                type="range"
                min="0"
                max="100"
                step="0.05"
                class="w-full"
              />
              <div class="mb-3 mt-1 text-[11.5px] text-muted-foreground">
                已读完阈值：进度达到 {{ form.finished }}% 算「已读完」
              </div>
              <input
                v-model.number="form.finished"
                data-test="wizard-finished"
                type="range"
                min="0"
                max="100"
                step="0.05"
                class="w-full"
              />
            </div>
          </div>

          <!-- ⑤ 自动化 -->
          <div v-else class="space-y-4">
            <label class="flex items-center gap-2 text-[12.5px] text-foreground">
              <input type="checkbox" v-model="form.watch" data-test="wizard-watch" />
              监听该库的来源目录（有新文件就自动归库）
            </label>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                轮询间隔秒（0 = 继承全局）
              </div>
              <input
                v-model.number="form.scan_interval"
                type="number"
                min="0"
                class="w-40 rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              />
            </div>

            <div>
              <div class="mb-1 text-[11.5px] text-muted-foreground">
                自动扫描计划（只是定时表达式的选择器，不新增调度能力）
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
            </div>
          </div>

          <Card v-if="blocked" padding="sm" class="mt-4">
            <span class="text-[11.5px] text-destructive">{{ blocked }}</span>
          </Card>
        </div>

        <!-- 底部固定栏 -->
        <footer class="flex items-center gap-2 border-t border-border px-5 py-3">
          <Button size="sm" variant="ghost" data-test="wizard-cancel" :disabled="busy" @click="emit('close')">
            取消
          </Button>
          <Button size="sm" variant="ghost" data-test="wizard-back" :disabled="stepIndex === 0 || busy" @click="back">
            上一步
          </Button>
          <span class="mx-auto text-[11.5px] text-muted-foreground">
            第 {{ stepIndex + 1 }} 步，共 {{ STEPS.length }} 步
          </span>
          <Button
            size="sm"
            variant="secondary"
            data-test="wizard-create-now"
            :disabled="busy"
            @click="submit(true)"
          >
            立即创建
          </Button>
          <Button
            v-if="stepIndex < maxStep"
            size="sm"
            variant="primary"
            data-test="wizard-next"
            :disabled="busy"
            @click="next"
          >
            继续
          </Button>
          <Button
            v-else
            size="sm"
            variant="primary"
            data-test="wizard-create"
            :disabled="busy"
            @click="submit(false)"
          >
            创建
          </Button>
        </footer>
      </section>
    </div>
  </div>
</template>
