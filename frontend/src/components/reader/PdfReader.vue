<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type PdfOutlineItem, type PdfSearchHit, type SessionExtra, type UnitPos, type UnitRef } from '@/lib/api'
import {
  PDF_FITS,
  PDF_SCROLL_MODES,
  PDF_SPREADS,
  readPdfPrefs,
  savePdfPrefs,
  type PdfPrefs,
} from '@/lib/pdfPrefs'
import { attachReaderClock, createSessionReporter, type ReaderClock } from '@/lib/readingSession'
import { buildTextLayer, pagePlainText, type PdfTextSpan } from '@/lib/pdfTextLayer'
import { highlightHex } from '@/data/annotationColors'
import { progressForFile } from '@/lib/readingProgress'
import { useSeriesNext } from '@/lib/seriesNext'
import { useSeriesToc } from '@/lib/seriesToc'
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
  /** 第 222 期：添加了批注 —— 上层据此刷新批注列表（它持有那份数组） */
  annotated: []
}>()
const router = useRouter()
const library = useLibraryStore()
/** 轻提示（第 222 期）：批注保存的结果。**不引 ui store** —— PDF 阅读器不弹浮层，
    用一个就地的小提示条就够了（见模板里的 `annoMsg`）。 */
const annoMsg = ref('')
let annoMsgTimer: ReturnType<typeof setTimeout> | null = null
function toast(text: string): void {
  annoMsg.value = text
  if (annoMsgTimer !== null) clearTimeout(annoMsgTimer)
  annoMsgTimer = setTimeout(() => { annoMsg.value = '' }, 2500)
}
/** 自动翻到系列下一册（第 66 期）：实现收敛到 `lib/seriesNext.ts` 单一真值源 */
const { goToNextVolume } = useSeriesNext()
/** 系列目录侧栏（第 152 期）：与漫画阅读器共用同一份（`lib/seriesToc.ts`） */
const toc = useSeriesToc(computed(() => props.series), computed(() => props.bookId))
const showSeriesToc = ref(false)

function jumpToVolume(id: string): void {
  showSeriesToc.value = false
  router.push(`/read/${id}`)
}

// ---------------- 大纲 / 文内搜索（第 195 期） ----------------
// 两者都是侧栏；同时只开一个。大纲按需拉（加密 / 坏 PDF 会如实报错），搜索只在点按钮时
// 才解析 —— 都是用户显式动作。
const showOutline = ref(false)
const showPdfSearch = ref(false)
const outlineItems = ref<PdfOutlineItem[]>([])
const outlineBusy = ref(false)
const outlineMsg = ref('')
const pdfQuery = ref('')
const pdfHits = ref<PdfSearchHit[]>([])
const pdfSearchBusy = ref(false)
const pdfSearchMsg = ref('')

async function loadOutline(): Promise<void> {
  outlineBusy.value = true
  outlineMsg.value = ''
  try {
    outlineItems.value = (await api.pdfOutline(props.bookId)).items
    if (!outlineItems.value.length) outlineMsg.value = '这本 PDF 没有大纲'
  } catch (e) {
    outlineItems.value = []
    outlineMsg.value = e instanceof Error ? e.message : '大纲读取失败'
  } finally {
    outlineBusy.value = false
  }
}

async function toggleOutline(): Promise<void> {
  showOutline.value = !showOutline.value
  if (showOutline.value) {
    showPdfSearch.value = false
    await loadOutline()
  }
}

async function togglePdfSearch(): Promise<void> {
  showPdfSearch.value = !showPdfSearch.value
  if (showPdfSearch.value) showOutline.value = false
}

async function runPdfSearch(): Promise<void> {
  const q = pdfQuery.value.trim()
  if (!q || pdfSearchBusy.value) return
  pdfSearchBusy.value = true
  pdfSearchMsg.value = ''
  try {
    const r = await api.pdfSearch(props.bookId, q)
    pdfHits.value = r.items
    if (!r.items.length) pdfSearchMsg.value = `没有找到（扫描 ${r.scanned} 页）`
  } catch (e) {
    pdfHits.value = []
    pdfSearchMsg.value = e instanceof Error ? e.message : '搜索失败'
  } finally {
    pdfSearchBusy.value = false
  }
}

function jumpPdfPage(p: number): void {
  if (!p || p < 1) return
  go(Math.min(total.value, p))
}

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

/** 文字层的容器（第 222 期）：每页一个，与 canvas 同尺寸同位置 */
const textLayers = new Map<number, HTMLElement>()

function setTextLayer(n: number, el: unknown): void {
  if (el instanceof HTMLElement) textLayers.set(n, el)
  else textLayers.delete(n)
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
    // 第 222 期：文字层与 canvas **同一个 viewport** —— 换算错一处，选中的字就偏。
    await renderTextLayer(n, p, vp)
  } catch {
    /* 单页渲染失败不致命，其余页继续 */
  } finally {
    busy.delete(n)
  }
}

// ---------------- 文字层（第 222 期）----------------
//
// canvas 只是图像：没有文字层就**选不了字**、做不了批注。这里把 pdf.js 的文字项
// 叠成一层透明的、绝对定位的文字（坐标换算见 `lib/pdfTextLayer.ts`）。
//
// ⚠️ 文字层**按需**生成（跟 canvas 同一个懒渲染节奏）：一次性给几百页都取文字
// 会把打开时间从秒级拖到分钟级（每页都要跑一遍字体度量）。

/** 每页的文字层片段（换算好的 CSS 坐标） */
const pageSpans = new Map<number, PdfTextSpan[]>()

// ---------------- 选区与批注（第 222 期）----------------
//
// PDF 的「章」= **页**：`chapter` 字段装页码（0 起，与 EPUB 的 spine 序号同一个字段，
// 不同坐标系 —— 见 `docs/user-guide.md` 的说明）。
//
// 锚点是**页内字符偏移**（`start_off` / `end_off`），不是像素坐标：像素随缩放变，
// 字符偏移不会 —— 缩放后重画高亮仍落在同一段字上。

const selText = ref('')
/** 选区所在页（1 起）与页内字符偏移 */
const selAnchor = ref<{ page: number; start: number; end: number } | null>(null)
/** 批注浮层的位置（视口坐标） */
const selPos = ref<{ x: number; y: number } | null>(null)
const noteDraft = ref('')
const annoColor = ref('yellow')
const annoStyle = ref('highlight')
const savingAnno = ref(false)

/**
 * 这一页已有的批注（第 222 期）：画在文字层上。
 *
 * 形状与 EPUB 那边一致：按**页内字符偏移**定位，不是像素 —— 缩放后重画仍落在同一段字上。
 */
const pageAnnos = ref<Record<number, PdfAnno[]>>({})
/** 批注列表（侧栏）：按页排序，用户能看也能删 */
const annoList = ref<PdfAnno[]>([])
const showAnnos = ref(false)

interface PdfAnno {
  id: number
  quote: string
  color: string
  style: string
  note: string
  start_off: number
  end_off: number
  /** 所在页（1 起）。只有侧栏那份列表带 —— 按页分组那份不带。 */
  page?: number
}

/** 取这本书的批注（页码 = `chapter` + 1）。失败**不打断阅读**。 */
async function loadPdfAnnotations(): Promise<void> {
  try {
    const res = await api.listAnnotations(props.bookId)
    const byPage: Record<number, PdfAnno[]> = {}
    for (const a of res.items || []) {
      const ch = Number(a.chapter)
      const s = Number(a.start_off ?? -1)
      const e = Number(a.end_off ?? -1)
      // 没有偏移的（别处导入的）**画不出来** —— 不猜位置，如实不画
      if (!Number.isFinite(ch) || ch < 0 || s < 0 || e <= s) continue
      ;(byPage[ch + 1] ||= []).push({
        id: a.id,
        quote: a.quote,
        color: a.color,
        style: a.style,
        note: a.note,
        start_off: s,
        end_off: e,
      })
    }
    pageAnnos.value = byPage
    annoList.value = Object.entries(byPage)
      .flatMap(([p, list]: [string, PdfAnno[]]) =>
        list.map((a: PdfAnno) => ({ ...a, page: Number(p) })))
      .sort((a: { page: number }, b: { page: number }) => a.page - b.page)
    paintHighlights()
  } catch {
    /* 拉不到批注：只是不显示高亮，不影响读 */
  }
}

/** 删一条批注（**软删除**：服务端把行标成已删，可从批注页的垃圾桶恢复）。 */
async function removePdfAnno(id: number): Promise<void> {
  try {
    await api.deleteAnnotation(props.bookId, id)
    annoList.value = annoList.value.filter((a) => a.id !== id)
    // ⚠️ `Object.keys` 给的是 **string** 键 ⇒ 索引要用 `Number(k)`（否则 TS 报索引类型不对）
    const next: Record<number, PdfAnno[]> = {}
    for (const [k, list] of Object.entries(pageAnnos.value)) {
      next[Number(k)] = (list || []).filter((a: PdfAnno) => a.id !== id)
    }
    pageAnnos.value = next
    paintHighlights()
    emit('annotated')
  } catch (e) {
    toast(e instanceof Error ? e.message : '删除失败')
  }
}

/**
 * 把这一页的批注画成**覆盖层**（半透明色块 / 下划线）。
 *
 * ⚠️ 覆盖层**只画形状、不带文字**（文字仍在下面的透明文字层里）—— 否则选中时
 * 会拿到两份字（覆盖层那份不可选）。
 */
function paintHighlights(): void {
  for (const [n, host] of textLayers) {
    host.querySelectorAll('[data-hl]').forEach((el) => el.remove())
    for (const a of pageAnnos.value[n] || []) {
      const box = highlightRect(n, a)
      if (!box) continue
      const el = document.createElement('div')
      el.setAttribute('data-hl', String(a.id))
      el.style.position = 'absolute'
      el.style.left = `${box.left}px`
      el.style.top = `${box.top}px`
      el.style.width = `${box.width}px`
      el.style.height = `${box.height}px`
      el.style.pointerEvents = 'none'
      const c = highlightHex(a.color)
      if (a.style === 'underline') {
        el.style.borderBottom = `2px solid ${c}`
      } else if (a.style === 'strikethrough') {
        el.style.borderBottom = `2px solid ${c}`
        el.style.opacity = '0.75'
      } else if (a.style === 'note') {
        el.style.borderBottom = `2px dotted ${c}`
      } else {
        el.style.background = c
        el.style.opacity = '0.4'
      }
      host.appendChild(el)
    }
  }
}

/**
 * 字符偏移 → 页面上的矩形。
 *
 * 做法：按文字层片段的顺序累加字符数，找到覆盖该区间的那些片段，取它们的
 * 并集矩形（同一行内的多个片段合起来）。
 */
function highlightRect(n: number, a: PdfAnno): { left: number; top: number; width: number; height: number } | null {
  const spans = pageSpans.get(n)
  if (!spans || !spans.length) return null
  let pos = 0
  let left = Infinity
  let right = -Infinity
  let top = Infinity
  let bottom = -Infinity
  let hit = false
  for (const s of spans) {
    const start = pos
    const end = pos + s.text.length
    pos = end
    if (end <= a.start_off || start >= a.end_off) continue
    hit = true
    // ⚠️ 宽度要用**拉伸后**的（`s.width` 已是拉伸前的自然位置 + PDF 写死的宽）——
    // 高亮框与文字层用同一套坐标，两者才对得上。
    left = Math.min(left, s.left)
    right = Math.max(right, s.left + s.width)
    top = Math.min(top, s.top)
    bottom = Math.max(bottom, s.top + s.height)
  }
  if (!hit) return null
  return { left, top, width: Math.max(2, right - left), height: Math.max(2, bottom - top) }
}

/** 选区落在哪一页（靠最近的文字层容器反查，不靠坐标推算） */
function pageOfNode(node: Node | null): number {
  const el = node instanceof HTMLElement ? node : node?.parentElement
  const layer = el?.closest('[data-text-page]')
  if (!layer) return 0
  return Number(layer.getAttribute('data-text-page') || 0) || 0
}

/** 选区在页内的字符偏移（按文字层片段的顺序累加） */
function offsetsInPage(page: number, range: Range): { start: number; end: number } | null {
  const spans = pageSpans.get(page)
  const host = textLayers.get(page)
  if (!spans || !host) return null
  // 选区起止在文字层里的位置 ⇒ 换算成字符偏移。
  // ⚠️ 用 `Range.toString()` 的长度当偏移：它与 `pagePlainText` 的口径**一致**
  // （都是「文字层里的字符序列」），所以偏移能直接回放成高亮。
  const pre = document.createRange()
  pre.selectNodeContents(host)
  // ⚠️ 变量声明在 try **外面**：声明在 try 里的话，catch 之后（以及 try 之外的
  // return）就看不到它 —— TypeScript 会直接报「no value exists in scope」。
  let start = -1
  let end = -1
  try {
    pre.setEnd(range.startContainer, range.startOffset)
    start = pre.toString().length
    pre.setEnd(range.endContainer, range.endOffset)
    end = pre.toString().length
  } catch {
    return null
  }
  return { start, end }
}

function onPdfSelect(): void {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed) {
    selAnchor.value = null
    selPos.value = null
    return
  }
  const range = sel.getRangeAt(0)
  const p = pageOfNode(range.startContainer)
  if (!p) {
    selAnchor.value = null
    selPos.value = null
    return
  }
  const text = sel.toString().trim()
  // 与 EPUB 同一上限（500 字）—— 太长的选区多半是「拖了一下」，不是有意选中
  if (!text || text.length > 500) {
    selAnchor.value = null
    selPos.value = null
    return
  }
  const offs = offsetsInPage(p, range)
  if (!offs || offs.end <= offs.start) {
    selAnchor.value = null
    selPos.value = null
    return
  }
  const rect = range.getBoundingClientRect()
  selText.value = text
  selAnchor.value = { page: p, start: offs.start, end: offs.end }
  selPos.value = { x: rect.left + rect.width / 2, y: rect.top }
  noteDraft.value = ''
}

function cancelPdfAnno(): void {
  selAnchor.value = null
  selPos.value = null
  selText.value = ''
  noteDraft.value = ''
  window.getSelection()?.removeAllRanges()
}

async function savePdfAnno(): Promise<void> {
  const a = selAnchor.value
  if (!a || savingAnno.value) return
  savingAnno.value = true
  try {
    await api.addAnnotation(props.bookId, {
      chapter: a.page - 1,          // 页码 1 起 ⇒ chapter 0 起
      quote: selText.value,
      color: annoColor.value,
      note: noteDraft.value.trim(),
      style: annoStyle.value,
      start_off: a.start,
      end_off: a.end,
    })
    toast('已添加批注')
    cancelPdfAnno()
    emit('annotated')
  } catch (e) {
    toast(e instanceof Error ? e.message : '添加批注失败')
  } finally {
    savingAnno.value = false
  }
}
async function renderTextLayer(n: number, pdfPage: any, viewport: any): Promise<void> {
  const host = textLayers.get(n)
  if (!host) return
  let spans: PdfTextSpan[] | null = null
  try {
    const tc = await pdfPage.getTextContent()
    spans = buildTextLayer(tc.items || [], viewport)
  } catch {
    // 这一页没有文字层（扫描件 / 加密 / 字体异常）——**如实留空**，不编造
    spans = []
  }
  pageSpans.set(n, spans)
  host.textContent = ''
  for (const s of spans) {
    const el = document.createElement('span')
    el.textContent = s.text
    el.style.left = `${s.left}px`
    el.style.top = `${s.top}px`
    el.style.fontSize = `${s.height}px`
    el.style.fontFamily = 'sans-serif'
    // 透明但**可选**：颜色透明（字仍然可选、能被选中）
    el.style.color = 'transparent'
    el.style.position = 'absolute'
    el.style.whiteSpace = 'pre'
    el.style.transformOrigin = '0 0'
    // ⚠️ 横向拉伸（pdf.js 自己的文字层也这么做，见 pdf_viewer.css 的 `.textLayer`）：
    // PDF 里的字宽是写死的值，与字体自然宽无关 —— 不拉伸的话选区框与看到的字对不齐。
    el.style.transform = `scaleX(${s.scaleX})`
    host.appendChild(el)
  }
  // 高亮覆盖层画在**文字层片段之后**（同一容器里，靠 DOM 顺序决定层叠）
  paintHighlights()
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
    // 第 222 期：取这本书已有的批注（画成高亮）。失败不影响读。
    void loadPdfAnnotations()
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
      <!-- 系列目录（第 152 期）：有系列才显示；单话模式不给 —— 那时跳册是合集层的事 -->
      <Button
        v-if="toc.hasSeries && !unitMode"
        size="sm"
        variant="ghost"
        title="系列目录"
        :class="showSeriesToc ? 'bg-muted text-foreground' : ''"
        @click="showSeriesToc = !showSeriesToc"
      >
        <Icon name="book" class="h-4 w-4" />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        title="PDF 大纲"
        :class="showOutline ? 'bg-muted text-foreground' : ''"
        @click="toggleOutline"
      >
        <Icon name="task" class="h-4 w-4" />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        title="PDF 文内搜索"
        :class="showPdfSearch ? 'bg-muted text-foreground' : ''"
        @click="togglePdfSearch"
      >
        <Icon name="search" class="h-4 w-4" />
      </Button>
      <!-- 第 222 期：批注侧栏（PDF 的批注在本阅读器里，EPUB 的在主阅读器那边） -->
      <Button
        size="sm"
        variant="ghost"
        title="批注"
        :class="showAnnos ? 'bg-muted text-foreground' : ''"
        @click="showAnnos = !showAnnos"
      >
        <Icon name="star" class="h-4 w-4" />
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

    <div v-else class="relative flex min-h-0 flex-1">
      <!-- 系列目录侧栏（第 152 期）：与漫画阅读器同形（`lib/seriesToc.ts` 共用一份） -->
      <aside
        v-if="showSeriesToc"
        class="w-60 shrink-0 overflow-y-auto border-r border-border py-2 pr-2"
      >
        <div class="mb-1.5 truncate px-2 text-[11px] text-muted-foreground" :title="toc.name">
          系列「{{ toc.name }}」共 {{ toc.books.length }} 册
        </div>
        <div v-if="toc.loading" class="px-2 py-3 text-[11.5px] text-muted-foreground">加载中…</div>
        <div v-else-if="toc.error" class="px-2 py-3 text-[11.5px] text-destructive">
          系列目录加载失败：{{ toc.error }}
        </div>
        <template v-else>
          <button
            v-for="(b, i) in toc.books"
            :key="b.id"
            type="button"
            class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-left text-[12.5px] transition-colors"
            :class="i === toc.currentIndex ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'"
            :title="b.title || b.name"
            @click="jumpToVolume(b.id)"
          >
            <span class="w-7 shrink-0 text-center text-[10.5px] tabular-nums">
              {{ b.series_index ? `#${b.series_index}` : '—' }}
            </span>
            <span class="truncate">{{ b.title || b.name }}</span>
          </button>
          <div v-if="!toc.books.length" class="px-2 py-3 text-[11.5px] text-muted-foreground">
            这个系列没有可显示的册
          </div>
        </template>
      </aside>

      <!-- PDF 大纲（第 195 期）：与系列目录同形；page=0 的条目没有页码目标，只展示不跳 -->
      <aside
        v-if="showOutline"
        class="w-60 shrink-0 overflow-y-auto border-r border-border py-2 pr-2"
      >
        <div class="mb-1.5 px-2 text-[11px] text-muted-foreground">大纲{{ outlineItems.length ? `（${outlineItems.length} 条）` : '' }}</div>
        <div v-if="outlineBusy" class="px-2 py-3 text-[11.5px] text-muted-foreground">读取中…</div>
        <div v-else-if="outlineMsg" class="px-2 py-3 text-[11.5px] text-muted-foreground">{{ outlineMsg }}</div>
        <button
          v-for="(it, i) in outlineItems"
          :key="`${i}:${it.title}`"
          type="button"
          class="block w-full cursor-pointer truncate rounded-md px-2 py-1 text-left text-[12.5px] transition-colors"
          :class="it.page ? 'text-muted-foreground hover:bg-muted hover:text-foreground' : 'text-muted-foreground/60'"
          :style="{ paddingLeft: `${8 + it.level * 12}px` }"
          :title="it.title"
          :disabled="!it.page"
          @click="jumpPdfPage(it.page)"
        >
          {{ it.title }}<span v-if="it.page" class="ml-1 text-[10px] tabular-nums">P{{ it.page }}</span>
        </button>
      </aside>

      <!-- 批注侧栏（第 222 期）：按页列出；点一条跳到那一页 -->
      <aside
        v-if="showAnnos"
        class="w-64 shrink-0 overflow-y-auto border-r border-border py-2 pr-2"
      >
        <div class="px-2 text-[11px] text-muted-foreground">批注{{ annoList.length ? `（${annoList.length} 条）` : '' }}</div>
        <p v-if="!annoList.length" class="px-2 py-3 text-[11.5px] text-muted-foreground">
          在页面上选中文字即可添加高亮与笔记。
        </p>
        <div
          v-for="a in annoList"
          :key="a.id"
          class="group mb-1.5 cursor-pointer rounded-md border border-border px-2 py-1.5 transition-colors hover:bg-muted"
          @click="a.page && jumpPdfPage(a.page)"
        >
          <div class="flex items-start gap-1.5">
            <span class="mt-1 h-2 w-2 shrink-0 rounded-full" :style="{ background: highlightHex(a.color) }" />
            <div class="min-w-0 flex-1">
              <p class="line-clamp-3 text-[11.5px] leading-snug text-foreground">「{{ a.quote }}」</p>
              <p v-if="a.note" class="mt-0.5 text-[11px] text-muted-foreground">{{ a.note }}</p>
              <p class="mt-0.5 text-[10px] text-muted-foreground">第 {{ a.page ?? 1 }} 页</p>
            </div>
            <button
              type="button"
              class="shrink-0 cursor-pointer text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground"
              title="移入垃圾桶（可在「批注」页的垃圾桶里恢复）"
              @click.stop="removePdfAnno(a.id)"
            >
              <Icon name="trash" class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </aside>

      <!-- PDF 文内搜索（第 195 期）：按页返回第一条命中；点结果跳页 -->
      <aside
        v-if="showPdfSearch"
        class="w-64 shrink-0 overflow-y-auto border-r border-border py-2 pr-2"
      >
        <div class="flex gap-1 px-2">
          <input
            v-model="pdfQuery"
            type="search"
            aria-label="PDF 文内搜索"
            placeholder="搜索正文…"
            class="h-7 min-w-0 flex-1 rounded-md border border-border bg-card px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
            @keyup.enter="runPdfSearch"
          >
          <Button size="sm" variant="ghost" :disabled="pdfSearchBusy || !pdfQuery.trim()" @click="runPdfSearch">
            {{ pdfSearchBusy ? '…' : '搜索' }}
          </Button>
        </div>
        <p v-if="pdfSearchMsg" class="mt-1 px-2 text-[11px] text-muted-foreground">{{ pdfSearchMsg }}</p>
        <div v-if="pdfHits.length" class="mt-1 px-2 text-[11px] text-muted-foreground">命中 {{ pdfHits.length }} 页</div>
        <button
          v-for="h in pdfHits"
          :key="`${h.page}:${h.offset}`"
          type="button"
          class="block w-full cursor-pointer rounded-md px-2 py-1 text-left text-[11.5px] text-muted-foreground hover:bg-muted hover:text-foreground"
          @click="jumpPdfPage(h.page)"
        >
          <span class="font-medium text-foreground">第 {{ h.page }} 页</span>
          <span class="mt-0.5 block leading-snug">{{ h.snippet }}</span>
        </button>
      </aside>

    <!-- 画布区 -->
    <div
      v-show="true"
      ref="boxRef"
      class="min-h-0 flex-1 overflow-auto bg-neutral-200/70 dark:bg-neutral-900/60"
      @scroll="onScroll"
      @mouseup="onPdfSelect"
    >
      <div
        class="flex min-h-full items-start justify-center gap-3 p-5"
        :class="prefs.scrollMode === 'horizontal' ? 'flex-row' : 'flex-col items-center'"
      >
        <template v-if="prefs.scrollMode === 'page'">
          <div v-for="n in shown" :key="n" :data-page="n" :ref="(el) => setSlot(n, el)" class="relative bg-white shadow-sm" :style="slotStyle(n)">
            <canvas :ref="(el) => setCanvas(n, el)" />
            <!-- 第 222 期：文字层（透明但可选）—— 没有它就选不了字 -->
            <div
              :ref="(el) => setTextLayer(n, el)"
              :data-text-page="n"
              class="absolute inset-0 overflow-hidden"
              style="line-height: 1"
            />
          </div>
        </template>
        <template v-else>
          <div
            v-for="n in total"
            :key="n"
            :data-page="n"
            :ref="(el) => setSlot(n, el)"
            class="relative shrink-0 bg-white shadow-sm"
            :style="slotStyle(n)"
          >
            <canvas :ref="(el) => setCanvas(n, el)" />
            <!-- 第 222 期：文字层（透明但可选）—— 没有它就选不了字 -->
            <div
              :ref="(el) => setTextLayer(n, el)"
              :data-text-page="n"
              class="absolute inset-0 overflow-hidden"
              style="line-height: 1"
            />
          </div>
        </template>
      </div>

      <!-- 批注浮层（第 222 期）：选中文字后出现在选区上方 -->
      <div
        v-if="selPos && selAnchor"
        class="fixed z-50 w-64 rounded-lg border border-border bg-card p-2.5 shadow-lg"
        :style="{ left: `${Math.max(8, selPos.x - 128)}px`, top: `${Math.max(8, selPos.y - 96)}px` }"
      >
        <p class="line-clamp-2 text-[11.5px] leading-snug text-muted-foreground">「{{ selText }}」</p>
        <input
          v-model="noteDraft"
          type="text"
          aria-label="批注内容"
          placeholder="写点什么（可空）"
          class="mt-2 h-7 w-full rounded-md border border-border bg-muted px-2 text-[11.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
          @keyup.enter="savePdfAnno"
        >
        <div class="mt-2 flex items-center gap-1.5">
          <select
            v-model="annoColor"
            aria-label="批注颜色"
            class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11px] text-foreground outline-none focus:border-ring"
          >
            <option value="yellow">黄</option>
            <option value="green">绿</option>
            <option value="blue">蓝</option>
            <option value="pink">粉</option>
          </select>
          <select
            v-model="annoStyle"
            aria-label="批注样式"
            class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11px] text-foreground outline-none focus:border-ring"
          >
            <option value="highlight">高亮</option>
            <option value="underline">下划线</option>
            <option value="strikethrough">删除线</option>
            <option value="note">纯笔记</option>
          </select>
          <Button size="sm" variant="primary" class="ml-auto" :disabled="savingAnno" @click="savePdfAnno">
            {{ savingAnno ? '保存中…' : '保存' }}
          </Button>
          <Button size="sm" variant="ghost" @click="cancelPdfAnno">取消</Button>
        </div>
      </div>

      <!-- 轻提示（第 222 期）：批注保存结果 -->
      <p
        v-if="annoMsg"
        class="pointer-events-none absolute bottom-3 left-1/2 z-50 -translate-x-1/2 rounded-full bg-card px-3 py-1.5 text-[11.5px] text-foreground shadow"
      >
        {{ annoMsg }}
      </p>
    </div>
    </div>
  </div>
</template>
