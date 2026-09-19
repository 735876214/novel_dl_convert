<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PdfReader from '@/components/reader/PdfReader.vue'
import ComicReader from '@/components/reader/ComicReader.vue'
import { HIGHLIGHT_COLORS, highlightHex as hex } from '@/data/annotationColors'
import { api, type Annotation, type BookDetail } from '@/lib/api'
import {
  READER_FONTS,
  READER_MODES,
  READER_RANGES,
  READER_THEMES,
  readerThemeStyle,
  readReaderPrefs,
  saveReaderPrefs,
  type ReaderPrefs,
} from '@/lib/readerPrefs'
import { customFontValue, readerFontStack } from '@/lib/fonts'
import { useFontsStore } from '@/stores/fonts'

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

const contentStyle = computed(() => {
  const p = prefs.value
  return {
    fontSize: `${p.size}px`,
    lineHeight: String(p.lineHeight),
    // 翻页模式铺满一屏，内容宽度交由「分栏」决定
    maxWidth: paged.value ? 'none' : `${p.width}rem`,
    fontFamily: readerFontStack(p.font),
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
  } as Record<string, string>
})

const widthStyle = computed(() => ({ maxWidth: `${prefs.value.width}rem` }))

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
  ] as Array<[NumPrefKey, string, number]>
).map(([key, label, digits]) => ({ key, label, digits, ...READER_RANGES[key] }))

/** 数量设置只接受有限数值（滑杆的 valueAsNumber 在非法输入时是 NaN） */
function setNum(key: NumPrefKey, value: number): void {
  if (!Number.isFinite(value)) return
  ;(prefs.value as unknown as Record<string, number>)[key] = value
}

/** 分栏只在翻页模式下有意义 */
const showSlider = (key: NumPrefKey): boolean => !(key === 'width' && paged.value) && !(key === 'columns' && !paged.value)

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

function wrapQuote(root: HTMLElement, quote: string, color: string, id: number): boolean {
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
    span.style.background = hex(color)
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
  for (const a of chapterAnnotations.value) wrapQuote(root, a.quote, a.color, a.id)
}

async function addHighlight(color: string): Promise<void> {
  const quote = selText.value
  if (!quote) return
  const note = noteDraft.value.trim()
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
    })
    annotations.value.push({
      id: r.id,
      chapter: currentIndex.value,
      quote,
      color,
      note,
      created_at: Date.now() / 1000,
    })
  } catch {
    /* ignore */
  }
  await nextTick()
  applyHighlights()
}

async function removeAnnotation(id: number): Promise<void> {
  try {
    await api.deleteAnnotation(bookId.value, id)
  } catch {
    /* ignore */
  }
  annotations.value = annotations.value.filter((a) => a.id !== id)
  // v-html 已渲染的高亮 span 无法精确回滚，直接按源 HTML 重绘再套用剩余高亮
  if (contentRef.value) contentRef.value.innerHTML = html.value
  await nextTick()
  applyHighlights()
}

async function jumpTo(a: Annotation): Promise<void> {
  const p = flat.value.findIndex((f) => f.index === a.chapter)
  if (p < 0) return
  if (p !== pos.value) await loadChapter(p)
  await nextTick()
  const el = contentRef.value?.querySelector(`[data-anno-id="${a.id}"]`)
  el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
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
  if (pendingSeconds < 5 || !book.value) return
  const secs = Math.round(pendingSeconds)
  pendingSeconds = 0
  try {
    await api.recordSession(bookId.value, secs)
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

onMounted(async () => {
  try {
    book.value = await api.bookDetail(bookId.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '书籍加载失败'
    loading.value = false
    return
  }
  try {
    annotations.value = (await api.listAnnotations(bookId.value)).items
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
      <ComicReader v-else-if="isComic" :book-id="bookId" :title="book.title" />

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
                  class="flex-1 cursor-pointer rounded-md border px-2 py-1 text-[12px] transition-colors"
                  :class="prefs.font === f.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
                  @click="prefs.font = f.key"
                >
                  {{ f.label }}
                </button>
              </div>

              <!-- 上传的字体（后端 /api/fonts）：用字体自身的族名渲染按钮，所见即所得 -->
              <div v-if="fonts.items.length" class="mt-1.5 flex flex-col gap-1">
                <button
                  v-for="f in fonts.items"
                  :key="f.id"
                  type="button"
                  class="flex cursor-pointer items-center justify-between rounded-md border px-2 py-1 text-[12px] transition-colors"
                  :class="prefs.font === customFontValue(f.id) ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
                  :title="f.style"
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
                class="w-full"
                :min="s.min"
                :max="s.max"
                :step="s.step"
                :value="prefs[s.key]"
                @input="setNum(s.key, ($event.target as HTMLInputElement).valueAsNumber)"
              >
            </label>

            <div class="mt-2 flex flex-col gap-1.5 border-t border-border pt-2.5">
              <label class="flex cursor-pointer items-center justify-between text-[12px] text-muted-foreground">
                <span>两端对齐</span>
                <input v-model="prefs.justify" type="checkbox" class="accent-[var(--primary)]">
              </label>
              <label class="flex cursor-pointer items-center justify-between text-[12px] text-muted-foreground">
                <span>断词（西文长词换行）</span>
                <input v-model="prefs.hyphens" type="checkbox" class="accent-[var(--primary)]">
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
            <article
              ref="contentRef"
              class="reader-content px-6 py-8"
              :class="paged ? '' : 'mx-auto'"
              :style="contentStyle"
              v-html="html"
            />
          </div>

          <div v-if="!paged" class="mx-auto flex items-center justify-between gap-3 px-6 pb-12" :style="widthStyle">
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

        <!-- 笔记面板 -->
        <aside
          v-if="showNotes"
          class="w-72 shrink-0 overflow-y-auto border-l border-border py-3 pl-3"
        >
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
        </aside>
      </div>

      <!-- 选中文字浮层 -->
      <div
        v-if="selPos"
        class="fixed z-50 -translate-x-1/2 -translate-y-full pb-2"
        :style="{ left: `${selPos.x}px`, top: `${selPos.y}px` }"
      >
        <div class="flex items-center gap-1.5 rounded-lg border border-border bg-card px-2 py-1.5 shadow-lg">
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
</style>
