<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type SessionExtra, type UnitPos, type UnitRef } from '@/lib/api'
import {
  PDF_FITS,
  PDF_SCROLL_MODES,
  PDF_SPREADS,
  readPdfPrefs,
  savePdfPrefs,
  type PdfPrefs,
} from '@/lib/pdfPrefs'
import { attachReaderClock, createSessionReporter, type ReaderClock } from '@/lib/readingSession'
import { progressForFile } from '@/lib/readingProgress'
import { useSeriesNext } from '@/lib/seriesNext'
import { toPercent } from '@/lib/unitsProgress'
import { useLibraryStore } from '@/stores/library'

/**
 * PDF 阅读器。
 *
 * **体积策略（关键）**：pdf.js 用动态 `import()` 懒加载 —— 只有真正打开 PDF 才会
 * 下载那两个 chunk（主包 gzip 117KB + worker gzip 291KB），书架/EPUB 阅读器完全不受影响。
 * worker 用 `?url` 由 Vite 打包成独立文件自托管，不走 CDN（NAS 内网无外网）。
 *
 * 渲染策略：滚动模式按 IntersectionObserver 懒渲染每页 canvas（长文档不会一次性画几百页）；
 * 翻页模式只渲染当前页（双页时含下一页）。缩放/适配变化时清空重画。
 */
const props = defineProps<{
  bookId: string
  title: string
  /** 这本书是否属于**漫画库**（第 61 期）：是则给出「漫画视图」入口，两边共用页进度 */
  comicLib?: boolean
  /** 所属系列名（第 61 期）：用于「读完自动进下一册」 */
  series?: string
  /**
   * 正在读的那个文件（第 63 期 4/6）：库内相对路径。**不给 = 书级** —— 单文件的书
   * 由上层算成 `undefined` 传下来，于是进度的读写与加这一列之前逐字节相同。
   * 判据必须是 `!== undefined`（空串是合法取值，与「不给」落点不同），见 `api.getProgress`。
   * 单话模式（给了 `unit`）下不使用：那时读的是合集里的一个文件，进度由上层独占（见下）。
   */
  fileRel?: string
  /**
   * **单话模式**（第 73 期）：正在读「序号单元合集」里的这一话（见 `api.UnitRef`）。
   * 数据源换成 `/units/{index}`、进度**不读不写**（整本书的 percent 由 `UnitsReader`
   * 独占），越过末页时发 `unitEnd` 让上层翻下一话。
   */
  unit?: UnitRef | null
}>()
/** 交回上层切换阅读器（偏好由上层统一落库） */
const emit = defineEmits<{
  pdfMode: ['comic' | 'pdf']
  /** 单话模式：这一话内部的进度 + 位置（页号，0 起）。上层据此拼整本书的 percent */
  unitPos: [UnitPos]
  /** 单话模式：这一话读完了，且**书里还有下一话**（末话的跨册续接不走这里，见 `pastEnd`） */
  unitEnd: []
}>()
const router = useRouter()
const library = useLibraryStore()
/** 自动翻到系列下一册（第 66 期）：实现收敛到 `lib/seriesNext.ts` 单一真值源 */
const { goToNextVolume } = useSeriesNext()

const prefs = ref<PdfPrefs>(readPdfPrefs())
watch(prefs, (v) => savePdfPrefs(v), { deep: true })

const boxRef = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref('')
const total = ref(0)
const page = ref(1)
const boxW = ref(0)
const boxH = ref(0)
/** 第一页的基准尺寸（PDF 单位），用于在没有 canvas 时推算占位高度 */
const base = ref({ w: 612, h: 792 })
const drawn = ref<Set<number>>(new Set())

/** 连续模式滚到底的去抖闩（并发闸已移入 `lib/seriesNext.ts` 单一真值源） */
const autoNextArmed = ref(true)

/** 单话模式：读的是合集里的一个文件，不是「这本书的主文件」 */
const unitMode = computed(() => !!props.unit)

/**
 * 话内进度 → 0–1 的比例（**单话模式的坐标**）。
 *
 * 用 `(page - 1) / total` 而不是非单话模式的 `page / total`：反解是 `floor(w × total) + 1`，
 * 两边必须严格互逆 —— 第 1 页落在 0、末页落在 `(total-1)/total`（这一话还没读完）。
 * 非单话模式那个 `page / total` 是**书级**百分比的口径（末页正好 100%），
 * 两套坐标不是一回事，别互相套用。
 */
const withinUnit = computed(() => (total.value ? (page.value - 1) / total.value : 0))

/** `within` 的反解：页码（1 起）。与 `withinUnit` 严格互逆 */
function restorePage(): number {
  const w = props.unit?.within ?? 0
  return Math.min(total.value, Math.max(1, Math.floor(w * total.value) + 1))
}

/**
 * 整本书的百分比。
 * - 非单话模式：这一话就是全书（`page / total`，末页 100%）—— 改造前逐字相同；
 * - 单话模式：这一话只是全书的一小段，位置由「第几话 + 话内比例」换算（同一份算式见
 *   `lib/unitsProgress.ts`）。阅读时长的快照用它，阅读日志里的百分比才与书架同源。
 */
const bookPercent = computed(() => (total.value
  ? (unitMode.value
    ? toPercent(props.unit?.index ?? 0, withinUnit.value, props.unit?.total ?? 1)
    : Math.min(100, (page.value / total.value) * 100))
  : 0))

let pdfDoc: any = null
const canvases = new Map<number, HTMLCanvasElement>()
const slots = new Map<number, HTMLElement>()
const busy = new Set<number>()
let io: IntersectionObserver | null = null
let saveTimer: ReturnType<typeof setTimeout> | null = null

const spreadOn = computed(
  () => prefs.value.spread !== 'none' && (prefs.value.spread !== 'auto' || boxW.value > 900),
)

/** 翻页模式下要显示的页号 */
const shown = computed(() => {
  if (prefs.value.scrollMode !== 'page') return [] as number[]
  if (!spreadOn.value) return [page.value]
  // 奇右 / 偶右决定并排的是哪两页：奇右 → [奇数, 下一页]，偶右 → [上一页, 偶数]
  const start = prefs.value.spread === 'even' ? page.value - (page.value % 2 === 1 ? 1 : 0)
    : page.value - (page.value % 2 === 0 ? 1 : 0)
  return [start, start + 1].filter((p) => p >= 1 && p <= total.value)
})

const scale = computed(() => {
  const pad = 40
  const w = Math.max(200, boxW.value - pad)
  const h = Math.max(200, boxH.value - pad)
  if (prefs.value.fit === 'custom') return prefs.value.zoom
  const perPage = spreadOn.value ? 2 : 1
  const fitW = w / perPage / base.value.w
  const fitH = h / base.value.h
  if (prefs.value.fit === 'page') return Math.min(fitW, fitH)
  if (prefs.value.fit === 'auto') return Math.min(fitW, fitH, 1) // 不放大超过 100%
  return fitW
})

/** 占位高度：用基准尺寸 × 缩放（canvas 定型前先撑住版式，避免滚动条跳动） */
function slotStyle(n: number = 1): Record<string, string> {
  void n
  return { width: `${Math.round(base.value.w * scale.value)}px`, minHeight: `${Math.round(base.value.h * scale.value)}px` }
}

function setCanvas(n: number, el: unknown): void {
  if (el instanceof HTMLCanvasElement) canvases.set(n, el)
  else canvases.delete(n)
}

function setSlot(n: number, el: unknown): void {
  if (!(el instanceof HTMLElement)) {
    slots.delete(n)
    return
  }
  slots.set(n, el)
  io?.observe(el)
}

async function renderPage(n: number): Promise<void> {
  const canvas = canvases.get(n)
  if (!pdfDoc || !canvas || busy.has(n) || drawn.value.has(n)) return
  busy.add(n)
  try {
    const p = await pdfDoc.getPage(n)
    const vp = p.getViewport({ scale: scale.value })
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = Math.floor(vp.width * dpr)
    canvas.height = Math.floor(vp.height * dpr)
    canvas.style.width = `${Math.floor(vp.width)}px`
    canvas.style.height = `${Math.floor(vp.height)}px`
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    await p.render({
      canvasContext: ctx,
      viewport: vp,
      transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0],
    }).promise
    drawn.value = new Set(drawn.value).add(n)
    const slot = slots.get(n)
    if (slot && n === 1) base.value = { w: vp.width / scale.value || base.value.w, h: vp.height / scale.value || base.value.h }
  } catch {
    /* 单页渲染失败不致命，其余页继续 */
  } finally {
    busy.delete(n)
  }
}

/** 缩放/适配变化后必须重画（canvas 的像素尺寸已变） */
function redraw(): void {
  drawn.value = new Set()
  const targets = prefs.value.scrollMode === 'page' ? shown.value : visibleSlots()
  for (const n of targets) void renderPage(n)
}

/** 滚动模式下「当前在视口里的页」——用于懒渲染与进度 */
function visibleSlots(): number[] {
  const box = boxRef.value
  if (!box) return []
  const out: number[] = []
  for (const [n, el] of slots) {
    const r = el.getBoundingClientRect()
    const br = box.getBoundingClientRect()
    if (r.bottom > br.top - 200 && r.top < br.bottom + 200) out.push(n)
  }
  return out
}

/**
 * 尺寸稳定前不许滚动改写页码。
 * 原因：初次打开时 slot 高度按「还没量到容器宽度」的 scale 算，`scrollIntoView`
 * 触发的 scroll 事件会据此把页码判成第 1 页 —— 表现就是「重新打开后进度丢失」。
 */
let settled = false

function onScroll(): void {
  if (!settled) return
  if (prefs.value.scrollMode === 'page') return
  const box = boxRef.value
  if (!box) return
  const br = box.getBoundingClientRect()
  // 当前页 = **视口顶部所在的页**（用户正在看的第一页）。
  // 不用视口中线：一屏约一页时中线会落到下一页，进度会莫名多一页。
  const line = br.top + 8
  let cur = 1
  for (const [n, el] of slots) {
    if (el.getBoundingClientRect().top <= line) cur = Math.max(cur, n)
  }
  if (cur !== page.value) {
    page.value = cur
    scheduleSave()
  }
  // 滚到底且已是末页：尝试自动换册
  maybeAutoNextAtBottom()
}

function scheduleSave(): void {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => void save(), 600)
}

async function save(): Promise<void> {
  if (!total.value) return
  // 单话模式：**不写进度**，把「话内读到哪」上报给上层（见 `api.UnitRef`）。
  // 整本书只有一行 percent，写它需要「第几话 + 话内多少」两个数，上层手里才有完整的那份；
  // 子组件各写一半必然互相覆盖（换话时旧话的卸载钩子会把进度写回旧话）。
  if (unitMode.value) {
    emit('unitPos', { index: props.unit?.index ?? 0, within: withinUnit.value, locator: page.value - 1 })
    return
  }
  const percent = Math.min(100, (page.value / total.value) * 100)
  try {
    const r = await api.setProgress(props.bookId, page.value - 1, percent, undefined, props.fileRel)
    // 第 61 期：进度就地回写 store —— 首页「继续阅读」不必等一次整库重拉
    library.patchProgress(props.bookId, percent, r?.updated_at)
  } catch {
    /* 静默：离线或未登录时不打断阅读 */
  }
}

// ---------------- 阅读时长（会话上报）----------------

/**
 * 第 63 期：PDF 也计入阅读时长了。此前 `ReaderView` 在 PDF / 漫画分支直接 `return`，
 * 两者**一秒都不记** —— 读了两个小时 PDF，日志里还是空的。
 *
 * 位置快照用**页码**（`locator` = 0 起页号，与 `save()` 写进 `progress` 的是同一个数），
 * 不是章节号：在这里页就是位置本身。计时口径与章节流共用 `attachReaderClock`
 * （前台可见才累计，30 秒心跳），边界规则不存在第二份实现。
 */
const session = createSessionReporter({
  source: 'web',
  // 页数未知时**不给位置**（服务端记「未知」），不编一个 0%
  snapshot: () => (total.value
    ? { percent: bookPercent.value, locator: page.value - 1 }
    : {}),
  post: (secs, extra: SessionExtra) => api.recordSession(props.bookId, secs, extra),
})
let clock: ReaderClock | null = null

function go(n: number): void {
  // 越过末页 = 想继续往后：单话模式先看**书里还有没有下一话**，没有才交给「自动翻下一册」
  // （未开启则原地不动，不再 clamp 成同一页空转）。
  // ⚠️ 这一判断必须放在 `go()` 里 —— 键盘（ArrowRight / PageDown）走的是 `go()` 而**不是** `next()`，
  // 只在 `next()` 里挂钩会让最常用的翻页方式静默失效。
  if (n > total.value) {
    pastEnd()
    return
  }
  const step = spreadOn.value ? 2 : 1
  page.value = Math.min(Math.max(1, n), total.value)
  void save()
  if (prefs.value.scrollMode === 'page') {
    void renderPage(page.value)
    if (spreadOn.value) void renderPage(page.value + step - 1)
  } else {
    slots.get(page.value)?.scrollIntoView({ block: 'start' })
  }
}

function next(): void {
  go(page.value + (spreadOn.value ? 2 : 1))
}
function prev(): void {
  go(page.value - (spreadOn.value ? 2 : 1))
}

/**
 * 读到末页后自动翻到系列下一册（第 61 期；第 66 期收敛到 `lib/seriesNext.ts` 单一真值源）。
 *
 * 数据用既有 `GET /api/series/{name}`（`api.seriesDetail`），**不新增后端接口**；
 * 无系列 / 已是末册 / 请求失败都明确提示且**不跳转**（失败不得静默）；
 * 先把当前进度落盘（`beforeJump: save`）再跳。
 */
function advanceToNextVolume(): Promise<boolean> {
  return goToNextVolume({
    enabled: prefs.value.autoNext,
    series: props.series,
    bookId: props.bookId,
    routeBase: '/read',
    beforeJump: save,
  })
}

/**
 * 读到这一「话」之外（单话模式）。
 *
 * 书里还有下一话 ⇒ 上报末尾位置后发 `unitEnd`，由 `UnitsReader` 换话 ——
 * **必须先把这一话的位置上报掉**：换话会卸载本组件，而上层那行 percent 正是靠
 * 这次上报才落到「第 3 话读完」上（少了它，退出时书架上停在第 3 话的开头）。
 *
 * 已经是最后一话 ⇒ 回到「读完自动翻下一册」那套（开关 / 系列提示 / 跳转都不变）。
 * 非单话模式恒为后者 —— 那时「下一话」这个概念不存在。
 */
function pastEnd(): void {
  const u = props.unit
  if (unitMode.value && u && u.index + 1 < u.total) {
    void save()
    emit('unitEnd')
    return
  }
  void advanceToNextVolume()
}

/**
 * 连续滚动模式滚到底且已到末页时换册（单话模式下：换**下一话**）；用闩避免同一次触底反复触发。
 *
 * 单话模式仍受这个开关管：它管的是「读到末尾要不要自动往后走」——书内换话与跨册续接
 * 在这一点上是同一件事（`pastEnd` 里的跨册那一半也受同一个开关管）。
 */
function maybeAutoNextAtBottom(): void {
  if (!prefs.value.autoNext) return
  const box = boxRef.value
  if (!box) return
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 8
  if (atBottom && page.value >= total.value) {
    if (!autoNextArmed.value) return
    autoNextArmed.value = false
    pastEnd()
  } else if (!atBottom) {
    autoNextArmed.value = true
  }
}

function zoomBy(d: number): void {
  prefs.value.fit = 'custom'
  prefs.value.zoom = Math.min(3, Math.max(0.5, Math.round((prefs.value.zoom + d) * 4) / 4))
}

function onKeydown(e: KeyboardEvent): void {
  const step = spreadOn.value ? 2 : 1
  if (e.key === 'ArrowRight' || e.key === 'PageDown') go(page.value + step)
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(page.value - step)
}

let ro: ResizeObserver | null = null

onMounted(async () => {
  try {
    const pdfjs: any = await import('pdfjs-dist')
    const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
    let token = ''
    try {
      token = localStorage.getItem('nf_token') || ''
    } catch {
      /* 隐私模式 */
    }
    pdfDoc = await pdfjs.getDocument({
      // 单话模式取**这一话**的字节（`/file` 发的始终是这本书的主文件，对合集没有意义）；
      // 那条 URL 自带 `?token=`，与 httpHeaders 里的 Bearer 并存不会互相干扰
      url: unitMode.value && props.unit
        ? api.unitFileUrl(props.bookId, props.unit.index)
        : `/api/books/${encodeURIComponent(props.bookId)}/file`,
      // 走 /api/ 必须带 Bearer；pdf.js 支持自定义头，所以不需要 ?token= 口子
      httpHeaders: token ? { Authorization: `Bearer ${token}` } : {},
    }).promise
    total.value = pdfDoc.numPages
    const first = await pdfDoc.getPage(1)
    const vp = first.getViewport({ scale: 1 })
    base.value = { w: vp.width, h: vp.height }
    // 恢复进度
    try {
      // 单话模式：恢复到哪由上层从跨话 percent 反推后给下来（`within`）；
      // 书级 / 多文件那套（`progressForFile`）在这里用不上 —— 合集的行是**整本书**的。
      if (unitMode.value) {
        page.value = restorePage()
      } else {
        const p = await progressForFile(props.bookId, props.fileRel)
        const n = Math.min(total.value, Math.max(1, (p.locator || 0) + 1))
        page.value = n
      }
    } catch {
      /* 无进度则从第 1 页开始 */
    }
    loading.value = false
    await new Promise((r) => requestAnimationFrame(r))
    measure()
    if (prefs.value.scrollMode !== 'page') {
      // 滚动模式：先滚到目标页，再渲染可见页
      slots.get(page.value)?.scrollIntoView({ block: 'start' })
    }
    redraw()
    // 等一帧让 ResizeObserver 完成首轮测量（scale 会变），再对准一次目标页，
    // 然后才允许滚动事件改写页码 —— 否则恢复的进度会被首帧的错位滚动覆盖
    await new Promise((r) => setTimeout(r, 150))
    if (prefs.value.scrollMode !== 'page') slots.get(page.value)?.scrollIntoView({ block: 'start' })
    settled = true
    // 文档真的打开了、能读了才开始计时（打不开的书不该留下零散会话）
    session.begin()
    clock = attachReaderClock(session)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'PDF 打开失败'
    loading.value = false
  }

  if (typeof ResizeObserver === 'function' && boxRef.value) {
    ro = new ResizeObserver(() => {
      const keep = page.value
      measure()
      redraw()
      // 尺寸变化会改变 slot 高度 → 滚动位置漂移，按当前页重新对准
      if (settled && prefs.value.scrollMode !== 'page') slots.get(keep)?.scrollIntoView({ block: 'start' })
    })
    ro.observe(boxRef.value)
  }
  if (typeof IntersectionObserver === 'function') {
    io = new IntersectionObserver(
      (entries) => {
        for (const en of entries) {
          if (!en.isIntersecting) continue
          const n = Number((en.target as HTMLElement).dataset.page || 0)
          if (n) void renderPage(n)
        }
      },
      { root: boxRef.value, rootMargin: '300px' },
    )
  }
  window.addEventListener('keydown', onKeydown)
})

function measure(): void {
  const el = boxRef.value
  if (!el) return
  boxW.value = el.clientWidth
  boxH.value = el.clientHeight
}

onBeforeUnmount(() => {
  clock?.accrue()          // 先把最后这几秒结掉，再拆管线
  clock?.detach()
  clock = null
  void session.stop()
  if (saveTimer) clearTimeout(saveTimer)
  void save()
  window.removeEventListener('keydown', onKeydown)
  io?.disconnect()
  ro?.disconnect()
  try {
    pdfDoc?.destroy?.()
  } catch {
    /* ignore */
  }
})

// 布局相关偏好变化 → 重画（页展可能改变并排页数，缩放必然变）
watch([scale, () => prefs.value.scrollMode, () => prefs.value.spread], () => {
  if (total.value) redraw()
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 工具栏 -->
    <div class="flex flex-wrap items-center gap-2 border-b border-border pb-2">
      <Button size="sm" variant="ghost" title="返回详情" @click="router.push(`/book/${props.bookId}`)">
        <Icon name="arrowLeft" class="h-4 w-4" />
      </Button>
      <div class="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">{{ props.title }}</div>

      <!-- 第 61 期：漫画库里的 PDF 可以切回「漫画形态」读（单/双页、右到左、无间隙连续）。
           单话模式不给这个入口：那一套要按「话」取字节流，两处切换器会各写一份话的坐标 -->
      <Button
        v-if="props.comicLib && !unitMode"
        size="sm"
        variant="ghost"
        title="按漫画形态打开（单/双页、右到左、无间隙连续；当前页进度保留）"
        @click="emit('pdfMode', 'comic')"
      >
        漫画视图
      </Button>

      <Button size="sm" variant="ghost" title="上一页" :disabled="page <= 1" @click="prev">
        <Icon name="arrowLeft" class="h-3.5 w-3.5" />
      </Button>
      <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ page }} / {{ total }}</span>
      <Button size="sm" variant="ghost" title="下一页" :disabled="page >= total" @click="next">
        <Icon name="arrowRight" class="h-3.5 w-3.5" />
      </Button>

      <span class="mx-1 h-4 w-px bg-border" />
      <button type="button" class="cursor-pointer px-1.5 text-[13px] text-muted-foreground hover:text-foreground" @click="zoomBy(-0.25)">−</button>
      <span class="text-[11.5px] text-muted-foreground tabular-nums">{{ Math.round(scale * 100) }}%</span>
      <button type="button" class="cursor-pointer px-1.5 text-[13px] text-muted-foreground hover:text-foreground" @click="zoomBy(0.25)">＋</button>

      <select
        v-model="prefs.fit"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="适配方式"
      >
        <option v-for="f in PDF_FITS" :key="f.key" :value="f.key">{{ f.label }}</option>
      </select>
      <select
        v-model="prefs.scrollMode"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="滚动模式"
      >
        <option v-for="m in PDF_SCROLL_MODES" :key="m.key" :value="m.key">{{ m.label }}</option>
      </select>
      <select
        v-model="prefs.spread"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="页展"
      >
        <option v-for="s in PDF_SPREADS" :key="s.key" :value="s.key">{{ s.label }}</option>
      </select>
    </div>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">
      正在加载 PDF（首次打开需下载渲染器）…
    </div>
    <div v-else-if="error" class="py-20 text-center text-[13px] text-destructive">{{ error }}</div>

    <!-- 画布区 -->
    <div
      v-show="!loading && !error"
      ref="boxRef"
      class="min-h-0 flex-1 overflow-auto bg-neutral-200/70 dark:bg-neutral-900/60"
      @scroll="onScroll"
    >
      <div
        class="flex min-h-full items-start justify-center gap-3 p-5"
        :class="prefs.scrollMode === 'horizontal' ? 'flex-row' : 'flex-col items-center'"
      >
        <template v-if="prefs.scrollMode === 'page'">
          <div v-for="n in shown" :key="n" :data-page="n" :ref="(el) => setSlot(n, el)" class="bg-white shadow-sm" :style="slotStyle(n)">
            <canvas :ref="(el) => setCanvas(n, el)" />
          </div>
        </template>
        <template v-else>
          <div
            v-for="n in total"
            :key="n"
            :data-page="n"
            :ref="(el) => setSlot(n, el)"
            class="shrink-0 bg-white shadow-sm"
            :style="slotStyle(n)"
          >
            <canvas :ref="(el) => setCanvas(n, el)" />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
