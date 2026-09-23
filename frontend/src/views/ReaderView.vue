<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PdfReader from '@/components/reader/PdfReader.vue'
import ComicReader from '@/components/reader/ComicReader.vue'
import { HIGHLIGHT_COLORS, highlightHex as hex, HIGHLIGHT_STYLES, DEFAULT_HIGHLIGHT_STYLE, highlightStyleLabel, type HighlightStyle } from '@/data/annotationColors'
import { api, apiErrorMessage, type Annotation, type BookDetail, type Bookmark } from '@/lib/api'
import {
  READER_FONTS,
  READER_FONT_STYLES,
  READER_MODES,
  READER_RANGES,
  READER_THEMES,
  readerFontStyle,
  readerThemeStyle,
  readReaderPrefs,
  saveReaderPrefs,
  type ReaderPrefs,
} from '@/lib/readerPrefs'
import { customFontValue, readerFontStack } from '@/lib/fonts'
import { useFontsStore } from '@/stores/fonts'
import { useUiStore } from '@/stores/ui'

/**
 * 在线阅读器（Batch 2）。
 *
 * 章节正文由后端从 EPUB spine 抽取并改写资源 URL（见 library.chapter_html），
 * 这里只负责渲染、章节导航、进度上报与高亮/笔记。
 * 进度与批注落在 SQLite（/api/books/{id}/progress|annotations），多端共享同一持久卷即一致。
 */
const route = useRoute()
const router = useRouter()
const bookId = computed(() => String(route.params.id))

const book = ref<BookDetail | null>(null)
const loading = ref(true)
const error = ref('')

/** 按格式分流：PDF → PdfReader（pdf.js 懒加载）、漫画（CBZ / CBR）→ ComicReader；章节流只服务 EPUB */
const fmt = computed(() => (book.value?.format || '').toUpperCase())
const isPdf = computed(() => fmt.value === 'PDF')
const isComic = computed(() => fmt.value === 'CBZ' || fmt.value === 'CBR')

/** 扁平化章节（按 spine 顺序，带 index） */
const flat = computed(() => {
  const out: { index: number; title: string; volume: string }[] = []
  for (const v of book.value?.chapters ?? []) {
    for (const c of v.chapters) {
      if (c.index === undefined) continue
      out.push({ index: c.index, title: c.title, volume: v.volume })
    }
  }
  return out
})
const total = computed(() => flat.value.length)

const pos = ref(0)
const currentIndex = computed(() => flat.value[pos.value]?.index ?? 0)
const html = ref('')
const chapterTitle = ref('')
const local = ref(0)

// ---------------- 阅读偏好（与设置页共享，见 lib/readerPrefs.ts）----------------

const prefs = ref<ReaderPrefs>(readReaderPrefs())
watch(prefs, (v) => saveReaderPrefs(v), { deep: true })

// 字体库（用户上传的字体）：setup 期就拉取并注入 @font-face —
// 否则「上次选的自定义字体」会先回落内置字体、字体加载完再跳变。
const fonts = useFontsStore()
void fonts.load()

const ui = useUiStore()

// ---------------- 翻页模式 ----------------
// 定高 + CSS 多栏：每栏高度 = 容器高，栏宽 = 一屏宽 / 栏数；翻页 = 按「一屏」横向位移。
// 分栏只在翻页模式下有意义 —— 滚动模式套多栏会变成横向滚动，反而更难读。
const PAGE_GAP = 32 // px，栏间距
const viewportW = ref(0)
const page = ref(0)
const pageCount = ref(1)
const paged = computed(() => prefs.value.mode === 'paged')

const columnWidth = computed(() => {
  const c = Math.max(1, Math.round(prefs.value.columns))
  const w = viewportW.value || 700
  return Math.max(160, (w - (c - 1) * PAGE_GAP) / c)
})

/**
 * 这本书是不是**固定版式**（pre-paginated）。
 *
 * 由后端读 OPF 的 `rendition:layout` 判定（`core/library._fixed_layout_of`），随书目 / 详情下发；
 * 读不到就是 false（默认按可重排处理，见那边的说明）。
 */
const fixedLayout = computed(() => book.value?.fixed_layout === true)

/** 正文的左右内边距：偏好驱动（原先写死 px-6），翻页模式下不额外叠加 */
const gutterStyle = computed(() => {
  const g = `${prefs.value.gutter}rem`
  return { paddingLeft: g, paddingRight: g }
})

const contentStyle = computed(() => {
  const p = prefs.value
  // 固定版式：整页已排好版（常见实现是整页 SVG），页宽由书本身决定 ——
  // 这里**只给容器尺寸**，字号 / 行高 / 缩进 / 字距 / 字体一概不注入：
  // 那些是重排设置，对一页排好的版式没有意义，套上去只会把整页排版揉烂。
  if (fixedLayout.value) {
    // 固定版式「页宽」三档（第 51 期，对齐上游 Fixed-layout page spreads）：
    //   book    = 页宽由书本身决定（**改造前行为**）
    //   single  = 收成一页宽并居中
    //   columns = 按 50% 列宽并排两页（与「分栏」同一套 CSS 多列机制）
    // ⚠️ 这里**仍然只给容器尺寸**，绝不注入字号 / 行高 / 缩进 / 字距 / 字体 ——
    // 那些是重排设置，套到「整页已排好版」的书上只会把版式揉烂。
    const base: Record<string, string> = {
      height: paged.value ? '100%' : 'auto',
      ...gutterStyle.value,
    }
    if (p.fixedLayoutWidth === 'single') {
      return {
        ...base,
        maxWidth: `${p.width}rem`,
        marginInline: 'auto',
        columnWidth: 'auto',
        columnGap: 'normal',
        columnFill: 'auto',
      }
    }
    if (p.fixedLayoutWidth === 'columns') {
      return {
        ...base,
        maxWidth: 'none',
        columnWidth: '50%',
        columnGap: `${p.gutter}rem`,
        columnFill: 'auto',
      }
    }
    return {
      ...base,
      maxWidth: 'none',
      columnWidth: 'auto',
      columnGap: 'normal',
      columnFill: 'auto',
    }
  }
  const fs = readerFontStyle(p.fontStyle)
  return {
    fontSize: `${p.size}px`,
    lineHeight: String(p.lineHeight),
    // 翻页模式铺满一屏，内容宽度交由「分栏」决定
    maxWidth: paged.value ? 'none' : `${p.width}rem`,
    fontFamily: readerFontStack(p.font),
    fontWeight: fs.weight,
    fontStyle: fs.style,
    textAlign: p.justify ? 'justify' : 'start',
    hyphens: p.hyphens ? 'auto' : 'manual',
    letterSpacing: `${p.letterSpacing}em`,
    wordSpacing: `${p.wordSpacing}em`,
    // 这两个值给 scoped 里的 :deep(p) 消费（那里读不到 prefs）
    '--nf-para-gap': `${p.paragraphSpacing}em`,
    '--nf-indent': `${p.indent}em`,
    height: paged.value ? '100%' : 'auto',
    columnWidth: paged.value ? `${columnWidth.value}px` : 'auto',
    columnGap: paged.value ? `${PAGE_GAP}px` : 'normal',
    columnFill: 'auto',
    ...gutterStyle.value,
  } as Record<string, string>
})

const widthStyle = computed(() => ({
  maxWidth: `${prefs.value.width}rem`,
  ...gutterStyle.value,
}))

const scrollStyle = computed(() => {
  const t = readerThemeStyle(prefs.value.theme)
  return { background: t.bg, color: t.fg }
})

/** 量出总栏数与总页数（翻页模式才有意义） */
function measurePages(): void {
  const el = scrollRef.value
  const art = contentRef.value
  if (!el || !art || !paged.value) {
    pageCount.value = 1
    page.value = 0
    return
  }
  viewportW.value = el.clientWidth
  const step = viewportW.value + PAGE_GAP
  const totalCols = Math.max(1, Math.round(art.scrollWidth / step))
  const perPage = Math.max(1, Math.round(prefs.value.columns))
  pageCount.value = Math.max(1, Math.ceil(totalCols / perPage))
  page.value = Math.min(page.value, pageCount.value - 1)
}

const pageShiftStyle = computed(() => ({
  transform: paged.value ? `translateX(-${page.value * (viewportW.value + PAGE_GAP)}px)` : 'none',
  transition: 'transform 180ms ease',
  height: paged.value ? '100%' : 'auto',
}))

/** 翻页；越过首/末页时顺带切章（与「上一章 / 下一章」按钮同向） */
function flip(delta: number): void {
  if (!paged.value) return
  const target = page.value + delta
  if (target < 0) {
    prev()
    return
  }
  if (target >= pageCount.value) {
    next()
    return
  }
  page.value = target
}

/** 点左侧三分之一上一页、右侧三分之一下一页，中间不响应（避免误翻） */
function onReaderClick(e: MouseEvent): void {
  if (!paged.value) return
  // 设置面板打开时，点正文先收面板且**不翻页** —— 面板本身就盖住右侧翻页热区，
  // 顺手翻页会让「想关面板」变成「莫名翻过去一页」。
  if (showSettings.value) {
    showSettings.value = false
    return
  }
  const el = scrollRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const x = e.clientX - rect.left
  if (x < rect.width / 3) flip(-1)
  else if (x > (rect.width * 2) / 3) flip(1)
}

function onKeydown(e: KeyboardEvent): void {
  if (!paged.value) return
  if (e.key === 'ArrowRight' || e.key === 'PageDown') flip(1)
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') flip(-1)
}

let pageObserver: ResizeObserver | null = null

onMounted(() => {
  if (typeof ResizeObserver === 'function' && scrollRef.value) {
    pageObserver = new ResizeObserver(() => {
      // 窗口变化后按比例落回原来的阅读位置，而不是跳回第一页
      const keep = pageCount.value > 1 ? page.value / pageCount.value : 0
      measurePages()
      page.value = Math.min(pageCount.value - 1, Math.round(keep * pageCount.value))
    })
    pageObserver.observe(scrollRef.value)
  }
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  pageObserver?.disconnect()
  pageObserver = null
  window.removeEventListener('keydown', onKeydown)
})

// 影响分页的偏好变动后重新量（等 DOM 更新完再量，否则拿到旧 scrollWidth）
watch(
  [
    () => html.value,
    () => prefs.value.mode,
    () => prefs.value.size,
    () => prefs.value.lineHeight,
    () => prefs.value.columns,
    () => prefs.value.indent,
    () => prefs.value.paragraphSpacing,
    () => prefs.value.width,
    () => prefs.value.font,
    () => prefs.value.fontStyle,
    () => prefs.value.gutter,
    () => fixedLayout.value,
  ],
  () => nextTick(measurePages),
)

// 翻页模式的进度按「已翻页数 / 总页数」；滚动模式由 onScroll 负责
watch([page, pageCount], () => {
  if (!paged.value || pageCount.value <= 1) return
  local.value = page.value / pageCount.value
  void saveProgress()
})

// ---------------- 阅读设置面板 ----------------
// 滑杆统一由配置数组驱动：新增一项只需加一行，不必再抄一遍 label/滑杆结构
type NumPrefKey = keyof typeof READER_RANGES
const SLIDERS = (
  [
    ['size', '字号', 0],
    ['lineHeight', '行高', 1],
    ['paragraphSpacing', '段落间距', 1],
    ['indent', '首行缩进', 1],
    ['letterSpacing', '字距', 2],
    ['wordSpacing', '词距', 2],
    ['width', '内容宽度', 0],
    ['columns', '分栏', 0],
    ['gutter', '文本区左右内边距', 1],
  ] as Array<[NumPrefKey, string, number]>
).map(([key, label, digits]) => ({ key, label, digits, ...READER_RANGES[key] }))

/** 数量设置只接受有限数值（滑杆的 valueAsNumber 在非法输入时是 NaN） */
function setNum(key: NumPrefKey, value: number): void {
  if (!Number.isFinite(value)) return
  ;(prefs.value as unknown as Record<string, number>)[key] = value
}

/**
 * 分栏只在翻页模式下有意义；固定版式下「内容宽度」也无意义（页宽由书本身决定）——
 * 但**照列不隐藏**，只是禁用并给出理由：抹掉会让用户以为设置项丢了。
 */
const showSlider = (key: NumPrefKey): boolean => !(key === 'width' && paged.value) && !(key === 'columns' && !paged.value)

/** 该设置项在当前这本书上是否生效（固定版式只吃主题 / 模式 / 内边距） */
function prefApplies(key: NumPrefKey): boolean {
  return !fixedLayout.value || key === 'gutter'
}

const showSettings = ref(false)
const showToc = ref(false)
const showNotes = ref(false)

const annotations = ref<Annotation[]>([])
const scrollRef = ref<HTMLElement | null>(null)
const contentRef = ref<HTMLElement | null>(null)

// 选中文字浮层
const selText = ref('')
const selPos = ref<{ x: number; y: number } | null>(null)
const noteDraft = ref('')
// 样式类型（高亮/下划线/删除线/纯笔记）单一来源来自 data/annotationColors.ts，与 COLORS 同文件。
const selStyle = ref<HighlightStyle>(DEFAULT_HIGHLIGHT_STYLE)

// 调色板与取色统一来自 data/annotationColors.ts（唯一一份）：
// 这里此前自己写了一份四色表，扩容时与另外三处（批注总览 / 图书详情 / 每日划线）
// 各自为政，漏改的地方会把新颜色静默渲染成黄色。
const COLORS = HIGHLIGHT_COLORS

const overallPercent = computed(() =>
  total.value ? Math.min(100, ((pos.value + local.value) / total.value) * 100) : 0,
)

const chapterAnnotations = computed(() =>
  annotations.value.filter((a) => a.chapter === currentIndex.value),
)

function titleOf(idx: number): string {
  return flat.value.find((f) => f.index === idx)?.title ?? `第 ${idx + 1} 章`
}

function localFraction(): number {
  const el = scrollRef.value
  if (!el) return 0
  const max = el.scrollHeight - el.clientHeight
  return max > 0 ? Math.min(1, Math.max(0, el.scrollTop / max)) : 0
}

// ---------------- 章节加载 ----------------

async function loadChapter(p: number, restore?: number): Promise<void> {
  if (!total.value) return
  p = Math.min(Math.max(0, p), total.value - 1)
  pos.value = p
  const ch = flat.value[p]
  try {
    const data = await api.chapter(bookId.value, ch.index)
    html.value = data.html
    chapterTitle.value = ch.title || data.title
  } catch (e) {
    error.value = e instanceof Error ? e.message : '章节加载失败'
    return
  }
  await nextTick()
  applyHighlights()
  const el = scrollRef.value
  if (el) {
    el.scrollTop = restore !== undefined ? Math.max(0, restore * (el.scrollHeight - el.clientHeight)) : 0
  }
  local.value = localFraction()
}

function prev(): void {
  if (pos.value > 0) loadChapter(pos.value - 1)
}

function next(): void {
  if (pos.value < total.value - 1) loadChapter(pos.value + 1)
}

function goto(index: number): void {
  const p = flat.value.findIndex((f) => f.index === index)
  if (p >= 0) {
    loadChapter(p)
    showToc.value = false
  }
}

// ---------------- 进度 ----------------

let saveTimer: ReturnType<typeof setTimeout> | null = null

function onScroll(): void {
  local.value = localFraction()
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(saveProgress, 800)
}

async function saveProgress(): Promise<void> {
  if (!book.value || !total.value) return
  try {
    await api.setProgress(bookId.value, currentIndex.value, overallPercent.value)
  } catch {
    /* 离线或未登录时静默 */
  }
}

// ---------------- 高亮 / 批注 ----------------

function onSelect(): void {
  const sel = window.getSelection()
  const content = contentRef.value
  if (!sel || sel.isCollapsed || !content) {
    selPos.value = null
    return
  }
  const text = sel.toString().trim()
  if (!text || text.length > 500) {
    selPos.value = null
    return
  }
  const anchor = sel.anchorNode
  if (!anchor || !content.contains(anchor)) {
    selPos.value = null
    return
  }
  const rect = sel.getRangeAt(0).getBoundingClientRect()
  selText.value = text
  selPos.value = { x: rect.left + rect.width / 2, y: rect.top }
}

function applyAnnoStyle(span: HTMLElement, color: string, style: string): void {
  const c = hex(color)
  if (style === 'underline') {
    span.style.textDecoration = 'underline'
    span.style.textDecorationColor = c
    span.style.textDecorationThickness = '2px'
  } else if (style === 'strikethrough') {
    span.style.textDecoration = 'line-through'
    span.style.textDecorationColor = c
    span.style.textDecorationThickness = '2px'
  } else if (style === 'note') {
    // 纯笔记：不铺底色，仅用虚线下沿锚定，与「下划线」实线区分
    span.style.borderBottom = `2px dotted ${c}`
  } else {
    span.style.background = c
  }
}

function wrapQuote(root: HTMLElement, quote: string, color: string, style: string, id: number): boolean {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  let n: Node | null
  while ((n = walker.nextNode())) nodes.push(n as Text)
  for (const node of nodes) {
    const idx = node.data.indexOf(quote)
    if (idx < 0) continue
    const range = document.createRange()
    range.setStart(node, idx)
    range.setEnd(node, idx + quote.length)
    const span = document.createElement('span')
    span.className = 'nf-hl'
    span.dataset.annoId = String(id)
    applyAnnoStyle(span, color, style)
    try {
      range.surroundContents(span)
      return true
    } catch {
      return false
    }
  }
  return false
}

function applyHighlights(): void {
  const root = contentRef.value
  if (!root) return
  for (const a of chapterAnnotations.value) wrapQuote(root, a.quote, a.color, a.style, a.id)
}

async function addHighlight(color: string): Promise<void> {
  const quote = selText.value
  if (!quote) return
  const note = noteDraft.value.trim()
  const style = selStyle.value
  selPos.value = null
  noteDraft.value = ''
  selText.value = ''
  window.getSelection()?.removeAllRanges()
  try {
    const r = await api.addAnnotation(bookId.value, {
      chapter: currentIndex.value,
      quote,
      color,
      note,
      style,
    })
    annotations.value.push({
      id: r.id,
      chapter: currentIndex.value,
      quote,
      color,
      note,
      style,
      created_at: Date.now() / 1000,
    })
    // 只包裹**新增的这条**：整章重扫会对已包裹文本重复包裹（span 套 span）。
    await nextTick()
    const root = contentRef.value
    if (root) wrapQuote(root, quote, color, style, r.id)
  } catch (e) {
    ui.toast(apiErrorMessage(e, '添加批注失败'))
  }
}

/** 只解包目标批注的 span，**不重建正文 DOM** —— 保住滚动位置 / 选区 / 阅读进度。 */
function unwrapAnnotation(id: number): void {
  const root = contentRef.value
  if (!root) return
  root.querySelectorAll(`[data-anno-id="${id}"]`).forEach((el) => {
    const parent = el.parentNode
    if (!parent) return
    while (el.firstChild) parent.insertBefore(el.firstChild, el)
    parent.removeChild(el)
    if (parent instanceof HTMLElement) parent.normalize()
  })
}

async function removeAnnotation(id: number): Promise<void> {
  try {
    await api.deleteAnnotation(bookId.value, id)
  } catch (e) {
    ui.toast(apiErrorMessage(e, '移入垃圾桶失败'))
    return
  }
  annotations.value = annotations.value.filter((a) => a.id !== id)
  unwrapAnnotation(id)
}

async function jumpTo(a: Annotation): Promise<void> {
  const p = flat.value.findIndex((f) => f.index === a.chapter)
  if (p < 0) return
  if (p !== pos.value) await loadChapter(p)
  await nextTick()
  const el = contentRef.value?.querySelector(`[data-anno-id="${a.id}"]`)
  el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

// ---------------- 书签（第 34 期）----------------
// 与批注**同构**的软删除（删除 = 移入垃圾桶 → 可恢复 → 可彻底删除），
// 但书签另有两处只属于它的性质，都是服务端口径，前端照用即可：
//   · **位置去重**：位置锚 = 「章序号 + 章内归一化位置」，同一位置反复点也只有一条；
//   · **可跳回**：点列表项按锚里的章内位置落回原处（批注靠 quote 重新包 span，书签靠坐标）。
// 锚的小数位固定 —— 否则同一处会因浮点尾数差异算出两个不同的锚，去重就失效了。
//
// ⚠️ **这里刻意不做能力闸门**（浏览器冒烟实测踩到）：本组 UI 只长在**章节流阅读器**里，
// 而漫画 / PDF / 有声书在模板里各走各的分支（`ComicReader` / `PdfReader` / 播放器），
// 根本到不了这里。若按「**当前库**的能力清单」判显隐，就会出现
// 「当前库选着漫画库、却打开一本电子书的阅读器 ⇒ 书签按钮消失」这种错判 ——
// 判隐显的轴应该是「这本书属于什么库」，而不是「侧栏当前选着哪个库」。
// 后端 `features` 里的 `bookmarks` 键仍然有用：它是书库管理页**能力矩阵**的一行
// （说明哪类库支持书签），只是不该用来藏这个按钮。
const ANCHOR_PRECISION = 4

const bookmarks = ref<Bookmark[]>([])
const bookmarkTrash = ref<Bookmark[]>([])
const panelTab = ref<'notes' | 'bookmarks'>('notes')
const bookmarkView = ref<'active' | 'trashed'>('active')
const bookmarkDraft = ref('')

/** 当前阅读位置的锚（与 `saveProgress` 用的是同一套坐标：章序号 + 章内比例） */
const currentAnchor = computed(
  () => `${currentIndex.value}:${local.value.toFixed(ANCHOR_PRECISION)}`,
)

/** 当前位置已有的书签：有 ⇒ 工具条图标变实心，再点就是移入垃圾桶 */
const bookmarkHere = computed(() => bookmarks.value.find((b) => b.anchor === currentAnchor.value))

const bookmarkList = computed(() =>
  bookmarkView.value === 'trashed' ? bookmarkTrash.value : bookmarks.value,
)

function anchorChapter(anchor: string): number {
  return Number(String(anchor).split(':')[0])
}

function anchorFraction(anchor: string): number {
  const f = Number(String(anchor).split(':')[1])
  return Number.isFinite(f) ? Math.min(1, Math.max(0, f)) : 0
}

function bookmarkPlace(b: Bookmark): string {
  return titleOf(anchorChapter(b.anchor))
}

async function reloadBookmarks(): Promise<void> {
  try {
    const r = await api.listBookmarks(bookId.value, true)
    bookmarks.value = r.items
    bookmarkTrash.value = r.trashed ?? []
  } catch {
    /* 离线或未登录时保持现状 */
  }
}

/** 备注输入框跟随「当前位置那条书签」：
 *   · 走到一条已有书签上 → 填入它的备注（好改）；
 *   · 离开它 → 清空（否则会把上一条的备注顺手贴到新位置的书签上）。
 * 只在**书签身份变化**时动手 —— 每次重载都会换对象引用，不加这道判据就会边滚动边丢草稿。 */
let syncedBookmarkId = 0
watch(bookmarkHere, (b) => {
  const id = b?.id ?? 0
  if (!id) {
    if (syncedBookmarkId) {
      syncedBookmarkId = 0
      bookmarkDraft.value = ''
    }
    return
  }
  if (id !== syncedBookmarkId) {
    syncedBookmarkId = id
    bookmarkDraft.value = b?.label ?? ''
  }
})

/** 加书签 / 保存备注（同位置已有则是改备注，走 PATCH 的并发合并口径） */
async function submitBookmark(): Promise<void> {
  const here = bookmarkHere.value
  const label = bookmarkDraft.value.trim()
  try {
    if (here) {
      if (label === here.label) return
      const r = await api.updateBookmark(bookId.value, here.id, {
        label,
        updated_at: here.updated_at,
      })
      // `applied=false` ⇒ 这条书签在别处刚被改过：服务端胜，界面跟着取最新版本
      if (r.applied === false && r.server) {
        const srv = r.server
        bookmarks.value = bookmarks.value.map((x) => (x.id === srv.id ? srv : x))
        ui.toast('这条书签在别处刚改过，已采用较新的版本')
      } else {
        ui.toast('备注已保存')
      }
    } else {
      const r = await api.addBookmark(bookId.value, {
        anchor: currentAnchor.value,
        chapter: currentIndex.value,
        percent: overallPercent.value,
        label,
      })
      ui.toast(r.revived ? '已恢复该位置的书签' : r.created ? '已加入书签' : '该位置已有书签')
    }
    bookmarkDraft.value = ''
  } catch (e) {
    ui.toast(apiErrorMessage(e, '书签操作失败'))
    return
  }
  await reloadBookmarks()
}

/** 工具条上的快捷开关：当前位置有 ⇒ 移入垃圾桶；没有 ⇒ 加一个（备注留空） */
async function toggleBookmark(): Promise<void> {
  const here = bookmarkHere.value
  if (!here) {
    await submitBookmark()
    return
  }
  try {
    await api.deleteBookmark(bookId.value, here.id)
    ui.toast('书签已移入垃圾桶')
  } catch (e) {
    ui.toast(apiErrorMessage(e, '移入垃圾桶失败'))
    return
  }
  await reloadBookmarks()
}

async function jumpToBookmark(b: Bookmark): Promise<void> {
  const p = flat.value.findIndex((f) => f.index === anchorChapter(b.anchor))
  if (p < 0) return
  await loadChapter(p, anchorFraction(b.anchor))
}

function onBookmarkClick(b: Bookmark): void {
  if (bookmarkView.value === 'active') void jumpToBookmark(b)
}

async function trashBookmark(b: Bookmark): Promise<void> {
  try {
    await api.deleteBookmark(bookId.value, b.id)
  } catch {
    /* ignore */
  }
  await reloadBookmarks()
}

async function restoreBookmark(b: Bookmark): Promise<void> {
  try {
    await api.restoreBookmark(bookId.value, b.id)
  } catch {
    /* ignore */
  }
  await reloadBookmarks()
}

async function purgeBookmark(b: Bookmark): Promise<void> {
  try {
    await api.purgeBookmark(bookId.value, b.id)
  } catch {
    /* ignore */
  }
  await reloadBookmarks()
}

// ---------------- 批注导出 ----------------

function exportMarkdown(): void {
  if (!annotations.value.length) return
  const groups = new Map<number, Annotation[]>()
  for (const a of annotations.value) {
    const list = groups.get(a.chapter) ?? []
    list.push(a)
    groups.set(a.chapter, list)
  }
  const lines: string[] = [
    `# ${book.value?.title ?? '批注'}`,
    '',
    `> 共 ${annotations.value.length} 条批注 · 导出于 ${new Date().toLocaleString()}`,
    '',
  ]
  for (const ch of [...groups.keys()].sort((a, b) => a - b)) {
    lines.push(`## ${titleOf(ch)}`, '')
    for (const a of groups.get(ch) ?? []) {
      lines.push(`> ${a.quote}`)
      if (a.note) lines.push('', a.note)
      lines.push('')
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const el = document.createElement('a')
  el.href = url
  el.download = `${(book.value?.title ?? 'book').replace(/[\\/:*?"<>|]/g, '_')}-批注.md`
  el.click()
  URL.revokeObjectURL(url)
}

// ---------------- 阅读时长（会话上报）----------------

let lastTick = Date.now()
let pendingSeconds = 0
let sessionTimer: ReturnType<typeof setInterval> | null = null

/** 仅在前台可见时累计阅读时长 */
function accrueSession(): void {
  const now = Date.now()
  if (document.visibilityState === 'visible') pendingSeconds += (now - lastTick) / 1000
  lastTick = now
}

async function flushSession(): Promise<void> {
  // 用**已加载的那本书**的 id，不用 route.params.id：离开阅读器时路由参数先变空，
  // 那一刻 `String(undefined)` 会发出 POST /api/books/undefined/session（404），
  // 这段时长又被 catch 塞回一个已经没人再上报的变量 ⇒ 悄悄丢掉。
  const bid = book.value?.id
  if (pendingSeconds < 5 || !bid) return
  const secs = Math.round(pendingSeconds)
  pendingSeconds = 0
  try {
    await api.recordSession(bid, secs)
  } catch {
    pendingSeconds += secs // 上报失败留待下次
  }
}

function onVisibilityChange(): void {
  accrueSession()
  if (document.visibilityState === 'hidden') void flushSession()
}

function startSession(): void {
  lastTick = Date.now()
  sessionTimer = setInterval(() => {
    accrueSession()
    void flushSession()
  }, 30000)
  document.addEventListener('visibilitychange', onVisibilityChange)
}

function stopSession(): void {
  accrueSession()
  void flushSession()
  if (sessionTimer) clearInterval(sessionTimer)
  sessionTimer = null
  document.removeEventListener('visibilitychange', onVisibilityChange)
}

// ---------------- 生命周期 ----------------

/** 取数并铺好**这一本**书的阅读现场。抽成函数是为了让首次挂载与同路由换书共用同一条路。 */
async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    book.value = await api.bookDetail(bookId.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '书籍加载失败'
    loading.value = false
    return
  }
  try {
    // 批注与书签一次取回（书签连垃圾桶一起 —— 两个档共用一份数据，切档不必再打请求）
    const [annos, bms] = await Promise.all([
      api.listAnnotations(bookId.value),
      api.listBookmarks(bookId.value, true),
    ])
    annotations.value = annos.items
    bookmarks.value = bms.items
    bookmarkTrash.value = bms.trashed ?? []
  } catch {
    /* ignore */
  }
  loading.value = false

  // 有声书不属于阅读器：直接转去播放器（详情页按钮已分流，这里是深链兜底）
  if (fmt.value === 'AUDIO') {
    router.replace(`/listen/${bookId.value}`)
    return
  }

  // PDF / 漫画不进章节流：书目已就绪，渲染与进度交给各自的阅读器。
  // （两者都不计阅读时长会话——章节流的计时基于章节位置，套上去会得出错误的时长）
  if (isPdf.value || isComic.value) return

  if (!total.value) {
    error.value = '这本书没有可阅读的章节'
    return
  }

  startSession()

  let start = 0
  let restore: number | undefined
  try {
    const p = await api.getProgress(bookId.value)
    const t = flat.value.findIndex((f) => f.index === p.locator)
    if (t >= 0) {
      start = t
      restore = Math.min(1, Math.max(0, (p.percent / 100) * total.value - t))
    }
  } catch {
    /* ignore */
  }

  // 支持 ?chapter=<spine index> 直接跳到指定章节（批注总览「前往」用）
  const q = Number(route.query.chapter)
  if (Number.isFinite(q)) {
    const t = flat.value.findIndex((f) => f.index === q)
    if (t >= 0) {
      await loadChapter(t)
      return
    }
  }
  await loadChapter(start, restore)
}

/**
 * 同一条路由记录内换参数（`/read/A` → `/read/B`）时**重新取数**。
 *
 * 原实现只在 `onMounted` 里赋值 `book`，而 `App.vue:138` 是裸 `<RouterView />`
 * （**没有 `:key`**）⇒ 同记录内换参数组件**不重新挂载**，`book` 停在上一本，
 * 于是头部书名（`:857` 的 `{{ book.title }}`）**停在上一本**；
 * 正文却因为 `loadChapter` 直接读路由驱动的 `bookId`（`:344`）而是新的 ——
 * 第 36 期记下的那个「正文会更新、书名不更新」的自相矛盾现象，根因就在这里。
 *
 * ⚠️ 刻意**不**给 `RouterView` 加 `:key`：那会连整棵 DOM 一起重建（丢滚动位置、
 * 重建滚动/分页观察器），与本项目「局部更新不重建」的既有做法冲突。这里只重跑取数。
 */
watch(bookId, async () => {
  // 先把上一本的阅读时长结清：`flushSession` 读的是 `book.value.id`，
  // 必须在 `load()` 换掉它**之前**调，否则这段时长会记到新书头上。
  stopSession()
  // 清掉上一本的现场 —— 否则新书取数期间会露着上一本的书签 / 批注 / 正文
  annotations.value = []
  bookmarks.value = []
  bookmarkTrash.value = []
  pos.value = 0
  html.value = ''
  chapterTitle.value = ''
  local.value = 0
  await load()
})

onMounted(() => {
  void load()
})

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  void saveProgress()
  stopSession()
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <EmptyState
      v-else-if="error || !book"
      icon="alert"
      :title="error || '找不到这本书'"
      desc="它可能已被移除，或不是可在线阅读的 EPUB。"
    >
      <template #action>
        <Button variant="primary" @click="router.push(`/book/${bookId}`)">返回详情</Button>
      </template>
    </EmptyState>

    <template v-else>
      <!-- PDF：独立阅读器（pdf.js 懒加载）。
           用嵌套 template 包裹 EPUB 分支：template 渲染时透明，不会破坏根 div 的
           flex 高度链（换成 div 会让 h-full 失效）。为免整块重排缩进，内部保持原缩进。 -->
      <PdfReader v-if="isPdf" :book-id="bookId" :title="book.title" />
      <ComicReader v-else-if="isComic" :book-id="bookId" :title="book.title" :series="book.series" />

      <template v-else>
      <!-- 工具栏 -->
      <div class="flex items-center gap-2 border-b border-border pb-2">
        <Button size="sm" variant="ghost" title="返回详情" @click="router.push(`/book/${bookId}`)">
          <Icon name="arrowLeft" class="h-4 w-4" />
        </Button>
        <Button size="sm" variant="ghost" title="目录" @click="showToc = !showToc">
          <Icon name="book" class="h-4 w-4" />
        </Button>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[12px] text-muted-foreground">{{ book.title }}</div>
          <div class="truncate text-[13px] font-medium text-foreground">{{ chapterTitle }}</div>
        </div>
        <div class="relative">
          <Button size="sm" variant="ghost" title="阅读设置" @click="showSettings = !showSettings">
            <Icon name="settings" class="h-4 w-4" />
          </Button>

          <div
            v-if="showSettings"
            class="absolute right-0 z-30 mt-1 max-h-[75vh] w-72 overflow-y-auto rounded-lg border border-border bg-card p-3 shadow-lg"
          >
            <!-- 固定版式：重排设置对这本书没有意义，如实说清并把它们禁用（不装作能调） -->
            <div
              v-if="fixedLayout"
              class="mb-3 flex gap-1.5 rounded-md border border-border p-2 text-[10.5px] leading-snug text-muted-foreground"
            >
              <Icon name="alert" class="mt-0.5 h-3 w-3 shrink-0" />
              <span>
                这本是<strong class="text-foreground/80">固定版式</strong>（整页已排好版）：
                页宽由书本身决定，字号 / 行高 / 缩进 / 分栏等重排设置对它不适用，只有主题、
                阅读模式与左右内边距会生效。
              </span>
            </div>

            <div class="mb-3">
              <div class="mb-1.5 text-[11px] text-muted-foreground">阅读模式</div>
              <div class="flex gap-1.5">
                <button
                  v-for="m in READER_MODES"
                  :key="m.key"
                  type="button"
                  class="flex-1 cursor-pointer rounded-md border px-2 py-1 text-[12px] transition-colors"
                  :class="prefs.mode === m.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
                  @click="prefs.mode = m.key"
                >
                  {{ m.label }}
                </button>
              </div>
              <p v-if="paged" class="mt-1 text-[10.5px] leading-snug text-muted-foreground">
                点正文左右两侧或按 ← → 翻页，翻到底自动跳下一章。
              </p>
            </div>

            <div class="mb-3">
              <div class="mb-1.5 text-[11px] text-muted-foreground">主题 · {{ READER_THEMES.length }} 档</div>
              <div class="grid grid-cols-4 gap-1.5">
                <button
                  v-for="t in READER_THEMES"
                  :key="t.key"
                  type="button"
                  class="cursor-pointer rounded-md border px-1 py-1.5 text-[10.5px] leading-tight transition-colors"
                  :class="prefs.theme === t.key ? 'border-ring font-medium' : 'border-border/70'"
                  :style="{ background: t.bg, color: t.fg }"
                  :title="t.label"
                  @click="prefs.theme = t.key"
                >
                  {{ t.label }}
                </button>
              </div>
            </div>

            <div class="mb-3">
              <div class="mb-1.5 text-[11px] text-muted-foreground">字体</div>
              <div class="flex gap-1.5">
                <button
                  v-for="f in READER_FONTS"
                  :key="f.key"
                  type="button"
                  class="flex-1 cursor-pointer rounded-md border px-2 py-1 text-[12px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                  :class="prefs.font === f.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
                  :disabled="fixedLayout"
                  @click="prefs.font = f.key"
                >
                  {{ f.label }}
                </button>
              </div>

              <!-- 字重样式：四档，按钮自身按该档渲染（所见即所得） -->
              <div class="mt-1.5 flex gap-1.5">
                <button
                  v-for="s in READER_FONT_STYLES"
                  :key="s.key"
                  type="button"
                  class="flex-1 cursor-pointer rounded-md border px-1 py-1 text-[12px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                  :class="prefs.fontStyle === s.key ? 'border-ring text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
                  :style="{ fontWeight: s.weight, fontStyle: s.style }"
                  :disabled="fixedLayout"
                  @click="prefs.fontStyle = s.key"
                >
                  {{ s.label }}
                </button>
              </div>

              <!-- 上传的字体（后端 /api/fonts）：用字体自身的族名渲染按钮，所见即所得 -->
              <div v-if="fonts.items.length" class="mt-1.5 flex flex-col gap-1">
                <button
                  v-for="f in fonts.items"
                  :key="f.id"
                  type="button"
                  class="flex cursor-pointer items-center justify-between rounded-md border px-2 py-1 text-[12px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                  :class="prefs.font === customFontValue(f.id) ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
                  :title="f.style"
                  :disabled="fixedLayout"
                  @click="prefs.font = customFontValue(f.id)"
                >
                  <span class="truncate" :style="{ fontFamily: `'NF-${f.id}', serif` }">{{ f.name }}</span>
                </button>
              </div>
              <p v-else class="mt-1.5 text-[10.5px] leading-snug text-muted-foreground">
                还没有上传字体。到「设置 → 阅读器 → 字体」上传 TTF / OTF 后会出现在这里。
              </p>
            </div>

            <label v-for="s in SLIDERS" v-show="showSlider(s.key)" :key="s.key" class="mb-2 block">
              <span class="mb-1 flex justify-between text-[11px] text-muted-foreground">
                <span>{{ s.label }}</span>
                <span class="tabular-nums">
                  {{ s.key === 'columns' ? `${prefs.columns} 栏` : `${prefs[s.key].toFixed(s.digits)}${s.unit}` }}
                </span>
              </span>
              <input
                type="range"
                class="w-full disabled:cursor-not-allowed disabled:opacity-50"
                :min="s.min"
                :max="s.max"
                :step="s.step"
                :value="prefs[s.key]"
                :disabled="!prefApplies(s.key)"
                @input="setNum(s.key, ($event.target as HTMLInputElement).valueAsNumber)"
              >
            </label>

            <div class="mt-2 flex flex-col gap-1.5 border-t border-border pt-2.5">
              <label class="flex cursor-pointer items-center justify-between text-[12px] text-muted-foreground">
                <span>两端对齐</span>
                <input v-model="prefs.justify" type="checkbox" class="accent-[var(--primary)]" :disabled="fixedLayout">
              </label>
              <label class="flex cursor-pointer items-center justify-between text-[12px] text-muted-foreground">
                <span>断词（西文长词换行）</span>
                <input v-model="prefs.hyphens" type="checkbox" class="accent-[var(--primary)]" :disabled="fixedLayout">
              </label>
            </div>
          </div>
        </div>

        <span v-if="paged" class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">
          {{ page + 1 }} / {{ pageCount }}
        </span>

        <Button
          size="sm"
          variant="ghost"
          :title="paged ? '切换到滚动模式' : '切换到翻页模式'"
          @click="prefs.mode = paged ? 'scroll' : 'paged'"
        >
          <Icon name="layers" class="h-4 w-4" />
        </Button>

        <Button
          size="sm"
          variant="ghost"
          :title="bookmarkHere ? '移除当前位置的书签' : '在当前位置加书签'"
          @click="toggleBookmark"
        >
          <!-- 已加书签时给 svg 上加 fill：path 是闭合形状，实心/描边一眼可辨 -->
          <Icon
            name="bookmark"
            class="h-4 w-4"
            :class="bookmarkHere ? 'text-primary' : ''"
            :style="bookmarkHere ? { fill: 'currentColor' } : undefined"
          />
        </Button>

        <Button size="sm" variant="ghost" title="笔记" @click="showNotes = !showNotes">
          <Icon name="note" class="h-4 w-4" />
        </Button>
      </div>

      <!-- 进度条 -->
      <div class="h-0.5 w-full bg-muted">
        <div class="h-full bg-primary transition-[width] duration-300" :style="{ width: `${overallPercent}%` }" />
      </div>

      <div class="relative flex min-h-0 flex-1">
        <!-- 目录 -->
        <aside
          v-if="showToc"
          class="w-60 shrink-0 overflow-y-auto border-r border-border pr-2 py-2"
        >
          <div v-for="v in book.chapters" :key="v.volume" class="mb-2">
            <div v-if="v.volume" class="px-2 py-1 text-[11px] font-semibold text-muted-foreground">
              {{ v.volume }}
            </div>
            <button
              v-for="c in v.chapters"
              :key="c.index"
              type="button"
              class="block w-full cursor-pointer truncate rounded-md px-2 py-1 text-left text-[12.5px] transition-colors"
              :class="c.index === currentIndex ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'"
              @click="c.index !== undefined && goto(c.index)"
            >
              {{ c.title }}
            </button>
          </div>
        </aside>

        <!-- 正文 -->
        <div
          ref="scrollRef"
          class="min-w-0 flex-1"
          :class="paged ? 'overflow-hidden' : 'overflow-y-auto'"
          :style="scrollStyle"
          @scroll="onScroll"
          @mouseup="onSelect"
          @click="onReaderClick"
        >
          <!-- 翻页模式：外层按「一屏」横向位移，内层 article 用 CSS 多栏切分 -->
          <div :style="pageShiftStyle">
            <!-- 左右内边距由偏好驱动（见 contentStyle）；固定版式另有 nf-fixed 中和重排样式 -->
            <article
              ref="contentRef"
              class="reader-content py-8"
              :class="[paged ? '' : 'mx-auto', fixedLayout ? 'nf-fixed' : '']"
              :style="contentStyle"
              v-html="html"
            />
          </div>

          <div v-if="!paged" class="mx-auto flex items-center justify-between gap-3 pb-12" :style="widthStyle">
            <Button size="sm" :disabled="pos <= 0" @click="prev">
              <Icon name="arrowLeft" class="h-3.5 w-3.5" />上一章
            </Button>
            <span class="text-[11.5px] text-muted-foreground tabular-nums">
              {{ pos + 1 }} / {{ total }}
            </span>
            <Button size="sm" :disabled="pos >= total - 1" @click="next">
              下一章<Icon name="arrowRight" class="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        <!-- 笔记 / 书签面板：两者都是「阅读时留下的记号」，共用一个侧栏（不新增导航项） -->
        <aside
          v-if="showNotes"
          class="w-72 shrink-0 overflow-y-auto border-l border-border py-3 pl-3"
        >
          <div class="mb-3 flex items-center gap-1 rounded-md border border-border p-0.5">
            <button
              type="button"
              class="flex-1 cursor-pointer rounded px-2 py-1 text-[12px] transition-colors"
              :class="panelTab === 'notes' ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'"
              @click="panelTab = 'notes'"
            >
              笔记 · 高亮 {{ annotations.length }}
            </button>
            <button
              type="button"
              class="flex-1 cursor-pointer rounded px-2 py-1 text-[12px] transition-colors"
              :class="panelTab === 'bookmarks' ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'"
              @click="panelTab = 'bookmarks'"
            >
              书签 {{ bookmarks.length }}
            </button>
          </div>

          <template v-if="panelTab === 'notes'">
            <div class="mb-2 flex items-center gap-2">
              <h3 class="text-[12px] font-semibold text-foreground">
                笔记 · 高亮 <span class="text-muted-foreground tabular-nums">{{ annotations.length }}</span>
              </h3>
              <button
                v-if="annotations.length"
                type="button"
                class="ml-auto cursor-pointer text-[11px] text-primary transition-opacity hover:opacity-80"
                title="导出为 Markdown"
                @click="exportMarkdown"
              >
                导出
              </button>
            </div>
            <p v-if="!annotations.length" class="text-[12px] text-muted-foreground">
              在正文里选中文字即可添加高亮与笔记。
            </p>
            <div
              v-for="a in annotations"
              :key="a.id"
              class="group mb-2 cursor-pointer rounded-lg border border-border px-2.5 py-2 transition-colors hover:bg-muted"
              @click="jumpTo(a)"
            >
              <div class="flex items-start gap-2">
                <span class="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" :style="{ background: hex(a.color) }" />
                <span class="mt-1 text-[10.5px] text-muted-foreground">{{ highlightStyleLabel(a.style) }}</span>
                <div class="min-w-0 flex-1">
                  <p class="line-clamp-3 text-[12px] leading-relaxed text-foreground">「{{ a.quote }}」</p>
                  <p v-if="a.note" class="mt-1 text-[11.5px] text-muted-foreground">{{ a.note }}</p>
                  <p class="mt-1 text-[10.5px] text-muted-foreground">{{ titleOf(a.chapter) }}</p>
                </div>
                <button
                  type="button"
                  class="shrink-0 cursor-pointer text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground"
                  title="移入垃圾桶（可在「批注」页的垃圾桶里恢复）"
                  @click.stop="removeAnnotation(a.id)"
                >
                  <Icon name="trash" class="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </template>

          <template v-else>
            <!-- 活跃 / 垃圾桶：与批注总览同一套两段式（垃圾桶里才能彻底删） -->
            <div class="mb-2 flex items-center gap-1 rounded-md border border-border p-0.5">
              <button
                type="button"
                class="flex-1 cursor-pointer rounded px-2 py-0.5 text-[11.5px] transition-colors"
                :class="bookmarkView === 'active' ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'"
                @click="bookmarkView = 'active'"
              >
                活跃 {{ bookmarks.length }}
              </button>
              <button
                type="button"
                class="flex-1 cursor-pointer rounded px-2 py-0.5 text-[11.5px] transition-colors"
                :class="bookmarkView === 'trashed' ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'"
                @click="bookmarkView = 'trashed'"
              >
                垃圾桶 {{ bookmarkTrash.length }}
              </button>
            </div>

            <!-- 当前位置的书签：没有则加（备注可选），已有则改备注 -->
            <div v-if="bookmarkView === 'active'" class="mb-2 flex items-center gap-1.5">
              <input
                v-model="bookmarkDraft"
                type="text"
                :placeholder="bookmarkHere ? '改这条书签的备注…' : '备注（可空）…'"
                class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
                @keyup.enter="submitBookmark"
              >
              <Button size="sm" @click="submitBookmark">
                {{ bookmarkHere ? '保存备注' : '加书签' }}
              </Button>
            </div>

            <p v-if="!bookmarkList.length" class="text-[12px] text-muted-foreground">
              {{ bookmarkView === 'trashed'
                ? '垃圾桶是空的。删除的书签会先放到这里，可以恢复，也可以彻底删除。'
                : '还没有书签。滚动或翻页到想记住的位置，点工具条上的书签图标即可。' }}
            </p>
            <div
              v-for="b in bookmarkList"
              :key="b.id"
              class="group mb-2 rounded-lg border border-border px-2.5 py-2 transition-colors"
              :class="bookmarkView === 'active' ? 'cursor-pointer hover:bg-muted' : ''"
              @click="onBookmarkClick(b)"
            >
              <div class="flex items-start gap-2">
                <Icon
                  name="bookmark"
                  class="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary"
                  :style="{ fill: 'currentColor' }"
                />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-[12px] text-foreground">{{ bookmarkPlace(b) }}</p>
                  <p v-if="b.label" class="mt-1 text-[11.5px] text-muted-foreground">{{ b.label }}</p>
                  <p class="mt-1 text-[10.5px] text-muted-foreground tabular-nums">
                    全书 {{ b.percent.toFixed(1) }}%
                  </p>
                </div>

                <div v-if="bookmarkView === 'trashed'" class="flex shrink-0 items-center gap-0.5">
                  <button
                    type="button"
                    class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    title="恢复这条书签"
                    @click.stop="restoreBookmark(b)"
                  >
                    <Icon name="undo" class="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
                    title="彻底删除（不可恢复）"
                    @click.stop="purgeBookmark(b)"
                  >
                    <Icon name="trash" class="h-3.5 w-3.5" />
                  </button>
                </div>
                <button
                  v-else
                  type="button"
                  class="shrink-0 cursor-pointer text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive"
                  title="移入垃圾桶（可在垃圾桶里恢复）"
                  @click.stop="trashBookmark(b)"
                >
                  <Icon name="trash" class="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </template>
        </aside>
      </div>

      <!-- 选中文字浮层 -->
      <div
        v-if="selPos"
        class="fixed z-50 -translate-x-1/2 -translate-y-full pb-2"
        :style="{ left: `${selPos.x}px`, top: `${selPos.y}px` }"
      >
        <div class="flex flex-col gap-1.5 rounded-lg border border-border bg-card px-2 py-1.5 shadow-lg">
          <div class="flex items-center gap-1">
            <button
              v-for="s in HIGHLIGHT_STYLES"
              :key="s.key"
              type="button"
              class="rounded px-1.5 py-0.5 text-[11px] transition-colors"
              :class="selStyle === s.key ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'"
              @click="selStyle = s.key"
            >{{ s.label }}</button>
          </div>
          <div class="flex items-center gap-1.5">
            <button
              v-for="c in COLORS"
              :key="c.key"
              type="button"
              class="h-5 w-5 cursor-pointer rounded-full border border-black/10 transition-transform hover:scale-110"
              :style="{ background: hex(c.key) }"
              :title="c.label"
              @click="addHighlight(c.key)"
            />
            <span class="mx-1 h-4 w-px bg-border" />
            <input
              v-model="noteDraft"
              type="text"
              placeholder="写点笔记…"
              class="w-28 bg-transparent text-[12px] text-foreground outline-none placeholder:text-muted-foreground"
              @keyup.enter="addHighlight('yellow')"
            />
          </div>
        </div>
      </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.reader-content {
  color: inherit;
  word-break: break-word;
}
/* 段落间距与首行缩进来自偏好（contentStyle 注入 CSS 变量），不再写死在样式里 */
.reader-content :deep(p) {
  margin: 0 0 var(--nf-para-gap, 1em);
  text-indent: var(--nf-indent, 2em);
}
.reader-content :deep(h1),
.reader-content :deep(h2),
.reader-content :deep(h3) {
  margin: 1.2em 0 0.6em;
  font-weight: 700;
  line-height: 1.4;
  text-indent: 0;
  /* 分栏模式下标题不要孤立在栏尾 */
  break-after: avoid;
}
.reader-content :deep(img),
.reader-content :deep(svg) {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 1em auto;
  /* 分栏时不要把图劈成两半 */
  break-inside: avoid;
}
.reader-content :deep(a) {
  color: var(--primary);
  text-decoration: underline;
}
.reader-content :deep(blockquote) {
  margin: 1em 0;
  padding-left: 0.8em;
  border-left: 3px solid var(--border);
  color: var(--muted-foreground);
}
.reader-content :deep(.nf-hl) {
  border-radius: 2px;
  padding: 0 1px;
}

/* 固定版式（pre-paginated）：整页已排好版，这里把**上面那套重排样式全部中和掉** ——
   页面里的元素本来就按绝对坐标排好，再加缩进 / 段距 / 图片外边距会把排版揉烂。
   页宽同理由书本身决定（contentStyle 在该分支不设 maxWidth / 分栏）。 */
.reader-content.nf-fixed :deep(p),
.reader-content.nf-fixed :deep(img),
.reader-content.nf-fixed :deep(svg) {
  margin: 0;
  text-indent: 0;
}
.reader-content.nf-fixed :deep(img),
.reader-content.nf-fixed :deep(svg) {
  margin-left: auto;
  margin-right: auto;
}
</style>
