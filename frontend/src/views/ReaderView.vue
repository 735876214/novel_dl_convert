<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Switch from '@/components/ui/Switch.vue'
import PdfReader from '@/components/reader/PdfReader.vue'
import ComicReader from '@/components/reader/ComicReader.vue'
import UnitsReader from '@/components/reader/UnitsReader.vue'
import { HIGHLIGHT_COLORS, highlightHex as hex, HIGHLIGHT_STYLES, DEFAULT_HIGHLIGHT_STYLE, highlightStyleLabel, type HighlightStyle } from '@/data/annotationColors'
import { api, apiErrorMessage, type Annotation, type BookDetail, type Bookmark, type FontItem, type OnlineChapters, type OnlineStatus, type SessionExtra } from '@/lib/api'
import { attachReaderClock, createSessionReporter, type ReaderClock } from '@/lib/readingSession'
import { progressForFile } from '@/lib/readingProgress'
import {
  canTrim,
  chunkGeomOf,
  computeWindow,
  localFractionIn,
  pickVisiblePos,
  scrollCompensation,
  type ChunkGeom,
} from '@/lib/readerFlow'
import { rangeAt, selectionRange } from '@/lib/textAnchor'
import { readComicPrefs, saveComicPrefs } from '@/lib/comicPrefs'
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
import { fontPrefValue, readerFontStack } from '@/lib/fonts'
import { tocGroups } from '@/lib/chapterGroups'
import { useFontsStore } from '@/stores/fonts'
import { useLibraryStore } from '@/stores/library'
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
/**
 * **序号单元合集**（第 73 期）：一棵目录树 = 一本书（`根目录/《书名》/第1卷/第1话.pdf`…）。
 * 它既不是 PDF 也不是漫画 —— 整本书是「若干话」，每话自己是一种媒体（PDF / 漫画 / 音频），
 * 所以分流交给 `UnitsReader`，由它按**当前话**的种类挑阅读器。见 `core/units.py`。
 */
const isUnits = computed(() => fmt.value === 'UNITS')

/**
 * **漫画库里的 PDF 按漫画形态读**（第 61 期；默认开，可在阅读器里一键切回 PDF 视图）。
 *
 * 为什么看库类型而不是看格式：PDF 既可以是电子书也可以是「扫描版漫画」，格式本身说明不了
 * 用户想怎么读 —— **放在漫画库里**才是明确意图，所以按库类型判，且两个阅读器都保留当前页进度。
 */
const pdfAsComic = ref(readComicPrefs().pdfMode !== 'pdf')
const comicPdf = computed(() => isPdf.value && book.value?.library_type === 'comic' && pdfAsComic.value)

/**
 * 本次阅读**正在读哪个文件**（第 63 期 4/6）：库内相对路径，与服务端 `progress.file_rel`
 * 同一套取值约定（`library.detail()` 的 `files[].name` 就是它）。
 *
 * 这是「本书的哪个**成品文件**」（同 stem 的 EPUB + PDF + MOBI 并存），不是「书里的哪一章」——
 * 章节号 / 页码 / 音轨号是各自的坐标系，这一维是**加**上去的，不改任何坐标系。
 *
 * ⚠️ **只在书有多个成品文件时才带**（照 `AudioPlayer` 给阅读时长上报那处的先例）：
 * 单文件书带与不带在库里落的是同一个读点，带了只是把书级那行从 `''` 挪到文件名上 ——
 * 收益为零，却让 KOReader / Komga 同步来的读点与 NF 读的读点分家。不带则与加这一列之前
 * 逐字节相同。判据用 `files.length > 1` 而不是「有没有兄弟」：主文件自己也在 `files` 里
 * （`library.book_detail` 按同 stem 枚举，`f.stem == stem` 对主文件成立）。
 *
 * 三个阅读器（章节流 / PDF / 漫画）读的都是**主文件** —— `/api/books/{id}/file`、
 * `/chapter/*`、`/comic/*` 都固定取 `root_of(b) / b["name"]` —— 所以三者取值相同，
 * 父组件算一次传下去即可（`PdfReader` / `ComicReader` 自己不请求详情）。
 *
 * ⚠️ **诚实边界**：正因如此，四个阅读器**都读不到非主文件** —— `files` 里那些同 stem
 * 的兄弟（EPUB + PDF + MOBI）目前只能**下载**（走 `api.downloadUrl(name)` 那条独立
 * 端点），没有任何接口能把它们的内容取出来读。所以「一本书的 EPUB 与 PDF 各存各的
 * 读点」这件事现在**还没有第二个文件可供阅读**：这一维此刻的作用是**把数据契约与
 * 落点先立住**，等 `/file` 支持选文件时读点已经在正确的键上、不必再迁移一次。
 * 也正因如此，详情页的成品文件列表**不给「继续阅读」入口** —— 那是点不动的假交互。
 */
const fileRel = computed(() =>
  (book.value?.files?.length ?? 0) > 1 ? book.value?.name : undefined,
)

/** 切换「PDF 用哪个阅读器」：落库到漫画偏好，下次打开还是用户选的那个 */
function setPdfMode(mode: 'comic' | 'pdf'): void {
  pdfAsComic.value = mode === 'comic'
  const p = readComicPrefs()
  p.pdfMode = mode
  saveComicPrefs(p)
}

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

// ---------------- 在线阅读（第 93 期）----------------
//
// 同一个组件、两条路由（`/read/:id` 与 `/online/:id`），靠 `route.name` 分模式。
// 这样主题 / 字号 / 版式 / 分页 / 滚动 / 目录抽屉 / 键盘翻章**全部共用同一份实现** ——
// 复制一份 `.reader-content` 与样式计算，改一处漏一处的表现是「在线读的字号不对」
// 这种看不出根因的小毛病。
//
// 与本地阅读的**全部差别**只有三处（都在下面）：
//   ① 取数：`chapterAt` 走 `api.onlineChapter`（服务端已把源站标记压成纯文本）；
//   ② 进度：不写 `/progress`，改由服务端按「线上章 ↔ 本地章」的窗口规则决定写不写；
//   ③ 横幅：常驻一行来源标注（**验收项，不是装饰** —— 读了半天不知道内容来自哪儿，
//      是这个功能最容易让人误判的地方）。
//
// 书签 / 批注在在线模式下一律**隐藏**（不是禁用）：它们的锚是「本地这一章的文本」，
// 而在线正文与本地正文不是同一份文本 —— 存下来的锚指向哪里谁也不确定。
/**
 * 哪两条路由算「阅读器」（同一个组件承载 `/read/:id` 与 `/online/:id`）。
 * ⚠️ vue-router 对**不同记录但同一个组件**是**复用实例**的（实测：`/read/A` → `/online/A`
 * 不重新挂载）⇒ 模式变化必须自己盯。
 */
const READER_ROUTE_NAMES = ['read', 'online']

/**
 * 本次阅读现场的模式。**只由 `load()` 定一次**（+ setup 时的初值）。
 *
 * ⚠️ 为什么不是 `computed(() => route.name === 'online')`：那个写法在**离开**阅读器时
 * 会翻成 `false`，而 `onBeforeUnmount` 正好要用它决定「这一次进度往哪儿写」——
 * 于是从 `/online/A` 退回详情页那一刻，线上章号会被当成**本地章号**写进 `/progress`，
 * 把这本书的本地进度按到源站目录的位置上。这个 bug 不会报错、只在下次打开本地阅读时
 * 表现为「进度跳到不相干的一章」，是本期测试抓出来的。
 *
 * 反过来说，`load()` 覆盖了全部三种模式变化：首次挂载、同记录换书、`/read/A` ↔ `/online/A`。
 */
const onlineMode = ref(route.name === 'online')
const isOnline = computed(() => onlineMode.value)

/** 不可用的原因（空串 = 可用）。非空时整页只渲染一句如实的说明 + 回本地阅读的入口 */
const onlineBlocked = ref('')
/** 来源标注横幅要的四样东西：源站显示名 / 书页地址 / 是哪儿来的 / 抓取时间 */
const onlineInfo = ref<{ display_name: string; url: string; origin: 'cache' | 'network'; stale: boolean; cached_at: number }>(
  { display_name: '', url: '', origin: 'network', stale: false, cached_at: 0 },
)
/** 本机缓存了几章 / 线上共几章（横幅上如实报出来） */
const onlineCache = ref<{ cached: number; total: number }>({ cached: 0, total: 0 })
/**
 * 这一章对没对上本地。
 *   · `undefined` = **还不知道**（还没取过任何一章）—— 此时不许显示那条提示；
 *   · `null` = 对不上（页内如实说「本次不记本地进度」）；
 *   · 数字 = 本地章号（服务端给的，前端不自己算）。
 */
const onlineLocalIndex = ref<number | null | undefined>(undefined)

/** 抓取时间的 `HH:MM`（没抓到过就是空串 ⇒ 横幅不显示那半句） */
const onlineFetchTime = computed(() => {
  const t = onlineInfo.value.cached_at
  if (!t) return ''
  const d = new Date(t * 1000)
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${d.getHours()}:${mm}`
})

/**
 * 横幅那句人话。
 *
 * ⚠️ 命中缓存时**必须**改口成「选自本机缓存」—— 否则读者以为屏幕上这段字是**刚**从
 * 源站取的。断网时更要写清「网络不可用」（这是本期「网络差也能继续读」的可见证据，
 * 不写出来用户只会以为书源更新到这儿了）。
 */
const onlineOriginText = computed(() => {
  const i = onlineInfo.value
  const who = i.display_name || '源站'
  const at = onlineFetchTime.value ? `，抓取于 ${onlineFetchTime.value}` : ''
  if (i.stale) return `网络不可用，本节选自本机缓存（${who}${at}）`
  if (i.origin === 'cache') return `本节选自本机缓存（${who}${at}）`
  return `本页内容来自 ${who} 的在线页面`
})

const pos = ref(0)
const currentIndex = computed(() => flat.value[pos.value]?.index ?? 0)
const html = ref('')
const chapterTitle = ref('')
const local = ref(0)
/** 章节加载中（第 61 期）：连点目录时必须有反馈，否则「点了没反应」 */
const chapterLoading = ref(false)

/**
 * TXT 书**本次解码用的编码与坏字节数**（第 89 期）：随章节响应带回（`text_encoding`）。
 *
 * 编码探测是**启发式**（除 BOM 外都是按字符分布猜的），且「解不出的字节以 U+FFFD 呈现」
 * 这件事本身就该让用户看见 —— 本仓纪律是「识别结果对用户可见，不静默猜测 / 不静默丢弃」。
 * EPUB / PDF 等格式不带这个字段（`null` ⇒ 不显示任何提示）。
 */
const textEncoding = ref<{ encoding: string; undecodable: number } | null>(null)

/** 只在**确有解不出的字节**时提示（低调）：全部解出时没什么要说的，不必打扰。 */
const decodeHint = computed(() => {
  const e = textEncoding.value
  if (!e || !e.undecodable) return ''
  return `按 ${e.encoding} 解码，${e.undecodable} 个字节无法解码（已用「�」占位）`
})

// ---------------- 阅读偏好（与设置页共享，见 lib/readerPrefs.ts）----------------

const prefs = ref<ReaderPrefs>(readReaderPrefs())
watch(prefs, (v) => saveReaderPrefs(v), { deep: true })

// 字体库（用户上传的字体）：setup 期就拉取并注入 @font-face —
// 否则「上次选的自定义字体」会先回落内置字体、字体加载完再跳变。
const fonts = useFontsStore()
void fonts.load()

const ui = useUiStore()
// ⚠️ 这里用 store **只为了进度回写**（`patchProgress`）：不拿书库能力清单做任何门控 ——
// 阅读是「这本书已经打开了」之后的事，再拿能力拦一次只会造成「明明能读却不能用」。
const library = useLibraryStore()

// 上传字体按族分组：同一 family_key 的变体（Regular / Bold…）合并为一个可选项 ——
// 选族后阅读器套用「加粗 / 斜体」时，浏览器会在同一 family 下挑中真实变体文件。
// 解析不出族名（family_key 为空）时各文件独立，回落改造前单文件行为。
const fontFamilies = computed(() => {
  const map = new Map<string, { value: string; name: string; variants: FontItem[] }>()
  for (const f of fonts.items) {
    const value = fontPrefValue(f)
    const cur = map.get(value)
    if (cur) cur.variants.push(f)
    else map.set(value, { value, name: f.name, variants: [f] })
  }
  return [...map.values()]
})

// ---------------- 翻页模式 ----------------
// 定高 + CSS 多栏：每栏高度 = 容器高，栏宽 = 一屏宽 / 栏数；翻页 = 按「一屏」横向位移。
// 分栏只在翻页模式下有意义 —— 滚动模式套多栏会变成横向滚动，反而更难读。
const PAGE_GAP = 32 // px，栏间距
const viewportW = ref(0)
const page = ref(0)
const pageCount = ref(1)
const paged = computed(() => prefs.value.mode === 'paged')

/**
 * 正文左右内边距的**像素值**（偏好里是 rem）。
 *
 * 第 61 期修「翻页右缘露出下一页」时用到的关键量：CSS 多栏的**可用宽**必须先扣掉内边距，
 * 否则算出的栏宽与浏览器实际排出来的不一致 —— 位移步长一歪，右缘就露下一栏。
 */
const rootRem = (() => {
  const v = typeof window !== 'undefined'
    ? parseFloat(getComputedStyle(document.documentElement).fontSize)
    : NaN
  return Number.isFinite(v) && v > 0 ? v : 16
})()
const gutterPx = computed(() => Math.max(0, prefs.value.gutter * rootRem))
/** 一屏总宽减去左右内边距 = 多栏真正可用的宽度 */
const availW = computed(() => Math.max(0, (viewportW.value || 700) - 2 * gutterPx.value))

const columnWidth = computed(() => {
  const c = Math.max(1, Math.round(prefs.value.columns))
  return Math.max(160, (availW.value - (c - 1) * PAGE_GAP) / c)
})

/**
 * 每翻一页横向位移的距离 = **栏宽 + 栏距**（实测口径）。
 *
 * 修之前用的是「容器宽 + 栏距」—— 容器宽包含内边距，且浏览器会把 `column-width` 这个
 * **提示值**拉伸到填满内容盒，两个偏差叠起来就表现为「翻一页后右侧露出下一栏」。
 * 现在正文宽度被定死、栏宽恰好铺满（见 contentStyle），步长因此是确定的。
 * 固定版式（pre-paginated）页宽由书本身决定，仍按一屏位移。
 */
const pageStep = computed(() => (fixedLayout.value
  ? (viewportW.value || 700) + PAGE_GAP
  : columnWidth.value + PAGE_GAP))

/**
 * 这本书是不是**固定版式**（pre-paginated）。
 *
 * 由后端读 OPF 的 `rendition:layout` 判定（`core/library._fixed_layout_of`），随书目 / 详情下发；
 * 读不到就是 false（默认按可重排处理，见那边的说明）。
 */
const fixedLayout = computed(() => !isOnline.value && book.value?.fixed_layout === true)

// ---------------- 书内排版（第 76 期）----------------

/** 注入书内 CSS 用的 `<style>` 的 id。挂 `document.head`，写法照 `stores/fonts.ts` 的 `injectFontFaces`。 */
const BOOK_CSS_ID = 'nf-book-css'

/** 书内样式（`GET /api/books/{id}/epub-css`）；取不到就是空串 = 回落应用排版。 */
const bookCss = ref('')

/**
 * `@scope` 的探测结果（**懒求值 + 缓存**：探测要 `new` 一个 CSSStyleSheet，
 * 不该每次重算都跑；放在模块加载时算又会早于测试的桩）。
 */
let scopeOkCache: boolean | null = null

/**
 * `@scope` 在本浏览器上是否可用。
 *
 * ⚠️ 这个判据不是可选的：不支持的浏览器会把 `@scope` 当**未知 at-rule 整块忽略**，
 * 书内样式一个字节都不生效 —— 那时若照常让应用排版「让位」（`.nf-bookcss`），
 * 就会**既没有书内排版、又丢了应用自己的排版**，比什么都不做更糟。
 * 用 `replaceSync` 能否解析出规则来问，比猜 UA 可靠（直接问「解析器认不认」）。
 */
function scopeSupported(): boolean {
  if (scopeOkCache !== null) return scopeOkCache
  try {
    const ss = new CSSStyleSheet()
    ss.replaceSync('@scope (.nf-probe) { .nf-probe { color: red } }')
    scopeOkCache = ss.cssRules.length > 0
  } catch {
    scopeOkCache = false
  }
  return scopeOkCache
}

/**
 * 书内排版此刻是否生效（决定要不要给正文挂 `.nf-bookcss` 让应用规则让位）。
 *
 * 固定版式**强制生效**：那种书的整页版式就是靠书内 CSS 的绝对定位摆出来的，
 * 关掉等于把整本书拆了 —— 设置里那个开关对它们禁用并说明理由（不做假交互）。
 */
const bookLayoutOn = computed(() => !!bookCss.value
  && (fixedLayout.value || prefs.value.useBookLayout)
  && scopeSupported())

/**
 * 把书内 CSS 注入 head（空串 = 移除）。
 *
 * ⚠️ **为什么必须挂在 head、绝不能放进 `v-html` 或正文容器里**：正文容器的
 * `textContent.length` 是进度与批注共用的那把尺子（后端 `core/epub_cfi` 按同一口径
 * 数文本节点长度），而 CSS 文本本身就是文本节点 —— 注入进容器会把长度顶长，
 * 让所有位置偏移**静默错位**（进度跳错、批注落到别处）。
 *
 * ⚠️ `@scope (.reader-content)` 是**作用域方案**：书内样式只作用在正文容器内，
 * 不会漏到工具栏 / 侧栏 / 弹窗。选它是因为**零解析** —— 想给选择器逐个加前缀就得
 * 自己写一个 CSS 分词器（要正确处理 `@media` / `@font-face` / 选择器列表），
 * 而本项目不引第三方依赖。
 */
function applyBookCss(css: string): void {
  const el = document.getElementById(BOOK_CSS_ID) as HTMLStyleElement | null
  if (!css || !scopeSupported()) {
    el?.remove()
    return
  }
  const node = el ?? document.createElement('style')
  if (!el) {
    node.id = BOOK_CSS_ID
    document.head.appendChild(node)
  }
  node.textContent = `@scope (.reader-content) {\n${css}\n}`
}

/** 取这本书的书内样式；**失败不是错误**（非 EPUB / 坏书 / 老服务端都回落应用排版）。 */
async function loadBookCss(): Promise<void> {
  bookCss.value = ''
  const id = bookId.value
  // 在线模式一律不套书内 CSS（第 93 期）：正文是源站那一页压出来的纯文本，
  // 而 `nf-book-css` 是**这本书本地文件**的样式 —— 套上去只会把不相关的排版规则
  // 作用到一段不属于它的正文上。（横幅底下读的是源站内容，这份样式没有立足点。）
  if (isOnline.value) return
  if (!id || !scopeSupported()) return
  if (!prefs.value.useBookLayout && !fixedLayout.value) return
  try {
    const res = await api.epubCss(id)
    if (bookId.value === id) bookCss.value = res.css || ''
  } catch {
    bookCss.value = ''
  }
}

watch(bookLayoutOn, (on) => applyBookCss(on ? bookCss.value : ''), { immediate: true })
// 书一变（或开关打开 / 关掉时再打开）就重新取；`book` 是异步填的，所以盯它而不是盯路由
watch([bookId, () => book.value?.fixed_layout, () => prefs.value.useBookLayout],
  () => { void loadBookCss() }, { immediate: true })
// 离开阅读器就把书内样式摘掉：它是**全局** `<style>`，留着会作用到下一个阅读器实例
onBeforeUnmount(() => applyBookCss(''))

/**
 * 滚动模式「跨章连续流」的章块（第 69 期）。
 *
 * 窗口只有 2–3 项（`lib/readerFlow.computeWindow`），所以一个数组 + 一张 `pos → 元素`
 * 表就够，不需要虚拟列表。
 */
interface FlowChunk {
  /** 在 `flat` 里的位置（章块窗口、目录高亮、底栏页码都用它） */
  pos: number
  /** 后端章节序号（进度与批注上报的 `chapter` 用它，不是 `pos`） */
  index: number
  title: string
  html: string
}

const chunks = ref<FlowChunk[]>([])

/**
 * `pos → 该章块的 `<section>` 元素`。
 *
 * 用**普通 Map** 而非响应式对象：这里只在 `nextTick` 之后**命令式**取值
 * （量几何 / 定位 / 挂批注），不参与渲染，做成响应式只会白白触发依赖收集。
 */
const chunkEls = new Map<number, HTMLElement>()

/** 章块挂载/卸载时同步元素表（`v-for` 的函数式 ref 在卸载时会以 `null` 回调） */
function setChunkEl(pos: number, el: unknown): void {
  if (el instanceof HTMLElement) chunkEls.set(pos, el)
  else chunkEls.delete(pos)
}

/**
 * 是否走「跨章连续流」（第 69 期）。
 *
 * 只在 **EPUB + 滚动模式 + 可重排** 时启用。固定版式（pre-paginated）的页尺寸由书本身
 * 决定、与 `nf-fixed` 的中和样式耦合，把「整页排好的版」纵向拼接风险高 ⇒
 * 保守沿用旧的单章路径（取舍记在 `docs/roadmap-gaps-remaining.md`）。
 */
const flowMode = computed(() => (
  !paged.value
  && !isPdf.value
  && !isComic.value
  && !fixedLayout.value
  && !!book.value
  && total.value > 0
))

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
    // 翻页模式把正文宽度**定死**：注意口径 —— 宽度是 border-box（含内边距），
    // 所以这里要给**整屏宽**，内容盒才恰好等于 `availW`（含内边距地写 availW 会让内容盒再窄掉
    // 两个内边距，栏宽随之被浏览器压小，步长与实际栏距又差开 —— 实测栽在这上面一次）。
    // 定死之后 cols*栏宽+(cols-1)*栏距 恰好铺满内容盒，浏览器不会再拉伸栏宽。
    width: paged.value && !fixedLayout.value ? `${viewportW.value || 700}px` : 'auto',
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
  // 栏距用**实测步长**（见 pageStep）：`scrollWidth` 不含最后一栏之后的栏距，
  // 所以补一个 PAGE_GAP 再除才对得上「总栏数」。固定版式的栏宽由书本身决定，维持原式。
  const step = pageStep.value
  const raw = fixedLayout.value ? art.scrollWidth / step : (art.scrollWidth + PAGE_GAP) / step
  const totalCols = Math.max(1, Math.round(raw))
  const perPage = Math.max(1, Math.round(prefs.value.columns))
  pageCount.value = Math.max(1, Math.ceil(totalCols / perPage))
  page.value = Math.min(page.value, pageCount.value - 1)
}

const pageShiftStyle = computed(() => ({
  transform: paged.value ? `translateX(-${page.value * pageStep.value}px)` : 'none',
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
  // ⚠️ 第 108 期起「点面板以外就收面板」还有一条 document 级监听（`onDocumentClick`）；
  // 这条早退仍然必要：它管的是**这一次点击不翻页**，而那条只管收面板。
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
  // Esc 收起打开的面板，并把焦点还给打开它的按钮（第 93 期）。
  // ⚠️ 必须在 `paged` 之前判：滚动模式下没有翻页键，但面板一样得能关。
  // 一次只关一层（自下而上），且**不吞**没有面板时的 Esc —— 那是别的组件的（如弹窗）。
  if (e.key === 'Escape') {
    if (showSettings.value) {
      showSettings.value = false
      restoreFocus(settingsBtn.value)
    } else if (showNotes.value) {
      showNotes.value = false
      restoreFocus(notesBtn.value)
    } else if (showToc.value) {
      showToc.value = false
      restoreFocus(tocBtn.value)
    }
    return
  }
  if (!paged.value) return
  if (e.key === 'ArrowRight' || e.key === 'PageDown') flip(1)
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') flip(-1)
}

// ---------------- 滚轮翻页（第 61 期）----------------
// 只在**翻页模式**生效；滚动模式原样交给浏览器滚动，绝不抢。
// 触控板会连发小 delta 且带惯性，所以累计到阈值才算一次「翻页意图」，并在翻完后加一道
// 时间锁 —— 否则轻轻一划会连翻好几页。
const WHEEL_STEP = 24        // 累计到这么多像素才翻一页
const WHEEL_LOCK_MS = 220    // 翻页后的锁：惯性余量在锁内一律忽略
let wheelAcc = 0
let wheelLockUntil = 0

function onWheel(e: WheelEvent): void {
  if (!paged.value || chapterLoading.value) return
  if (showSettings.value) return            // 面板开着时不翻页（与点击热区同一纪律）
  e.preventDefault()
  const now = Date.now()
  wheelAcc += e.deltaY
  if (now < wheelLockUntil) return
  if (Math.abs(wheelAcc) < WHEEL_STEP) return
  const dir = wheelAcc > 0 ? 1 : -1
  wheelAcc = 0
  wheelLockUntil = now + WHEEL_LOCK_MS
  flip(dir)
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
  // 第 108 期：点面板以外就收面板（含滚动模式点正文、点工具栏其它按钮）
  document.addEventListener('click', onDocumentClick)
})

onBeforeUnmount(() => {
  pageObserver?.disconnect()
  pageObserver = null
  window.removeEventListener('keydown', onKeydown)
  document.removeEventListener('click', onDocumentClick)
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

/**
 * 打开面板的那三个按钮。只为「Esc 收面板后把焦点还回去」而存在 ——
 * 不还的话焦点掉到 `body`，键盘用户得从侧栏第一项重新 Tab 几十下。
 * 面板本身不是模态框（没有焦点陷阱），所以这里用最轻的一招：
 * 记下触发者，关掉后 `focus()` 回去。`Button` 是单根组件 ⇒ 模板 ref 拿到的是实例，按钮在 `$el`。
 */
const tocBtn = ref<ComponentPublicInstance | null>(null)
const settingsBtn = ref<ComponentPublicInstance | null>(null)
const notesBtn = ref<ComponentPublicInstance | null>(null)

function restoreFocus(btn: ComponentPublicInstance | null): void {
  const el = btn?.$el
  if (el instanceof HTMLElement) el.focus()
}

/** 设置面板本体（第 108 期）：判「点的是不是面板里面」用，见 `onDocumentClick` */
const settingsPanel = ref<HTMLElement | null>(null)

/**
 * 点面板以外的地方就收面板（第 108 期，用户口径）。
 *
 * 只在 `onReaderClick` 里收是不够的：那条路第一行就是 `if (!paged.value) return`，
 * 于是**滚动模式**下点正文、以及点工具栏其它按钮，都不会经过它 —— 面板会一直挂着
 * 挡住正文（它 `absolute` 盖在右侧翻页热区上）。
 *
 * 这里挂在 `document` 上按**包含关系**判：点在面板里、或点在打开它的那颗按钮上都不收，
 * 其余任何位置（正文、工具栏、横幅、留白）一律收。
 *
 * ⚠️ 用 `click`（冒泡到 document）而不是 `pointerdown`：组件自己的 `@click` 先跑完才轮到
 * 这里，于是翻页模式下「点正文关面板」那一下仍会先被 `onReaderClick` 的早退吃掉
 * （收面板、**不翻页**）。换成 `pointerdown` 会先关面板，让同一下点击顺势翻过去一页 ——
 * 用户想关面板却翻了一页，正是那条早退当初要避免的。
 *
 * ⚠️ 面板里**不放** `action` / `pointerdown` 类关闭判据的浮层（Select / Popover 这类
 * Teleport 到 body 的控件）：它们的下拉内容不在 `settingsPanel` 里，点一下会被这里
 * 当成「点到了外面」。要加这类控件，得先把它排除掉（`lib/viewport` 那种收口不算）。
 */
function onDocumentClick(e: MouseEvent): void {
  if (!showSettings.value) return
  const target = e.target
  if (!(target instanceof Node)) return
  if (settingsPanel.value?.contains(target)) return
  const trigger = settingsBtn.value?.$el
  if (trigger instanceof Node && trigger.contains(target)) return
  showSettings.value = false
}

const annotations = ref<Annotation[]>([])
const scrollRef = ref<HTMLElement | null>(null)
const contentRef = ref<HTMLElement | null>(null)

// 滚轮翻页的监听必须**手动**注册在滚动容器上（且 non-passive）：
// 浏览器对 wheel 的默认被动策略会让 `preventDefault()` 静默失效，页面便会同时滚动。
// 容器是条件渲染的（书加载完才出现）→ 用 watch 挂/摘，别在 onMounted 里抢时间点。
watch(scrollRef, (el, old) => {
  old?.removeEventListener('wheel', onWheel)
  el?.addEventListener('wheel', onWheel, { passive: false })
})

/**
 * 滚动 ↔ 翻页 切换：两条路径维护的是**两份不同的正文状态**。
 *
 * 连续流只维护 `chunks`，单章路径只维护 `html` —— 切过去时另一份是空的，必须按当前章
 * 重新取一次（已预取的章命中缓存，不会真的发请求），否则会露一屏空白。
 * 顺手把另一份清干净：留着既占内存，也会让「切回来时先用旧内容闪一下」。
 */
watch(paged, async () => {
  if (!total.value || !book.value || isPdf.value || isComic.value) return
  if (paged.value) {
    chunks.value = []
    chunkEls.clear()
  } else {
    html.value = ''
  }
  await loadChapter(pos.value, local.value)
})

/**
 * 开关一改就立刻按当前可见章校一趟窗口（第 69 期）。
 *
 * 少了这一步会有个很别扭的边角：用户正停在窗口末尾（读到底、没得再滚），此时打开「连续读」
 * 不会补章 —— 补章只挂在滚动事件上，而那一刻**没有滚动事件**，用户只会觉得「开关没反应」。
 */
watch(() => prefs.value.autoNextChapter, () => {
  if (flowMode.value) void maintainFlowWindow(pos.value)
})

// 选中文字浮层
const selText = ref('')
const selPos = ref<{ x: number; y: number } | null>(null)
/**
 * 选区在**本章正文**里的字符偏移 `[start, end)`（第 63 期 6/6）。
 *
 * 它解决的是「同一章里同一句话出现两次 ⇒ 高亮画错那一处」—— 按文本搜索只能找到
 * 第一个匹配，偏移没有二义性。取不到就是 `null`（回落按文本搜索）。
 * 坐标定义与还原逻辑都在 `lib/textAnchor.ts`，**不要在这里另算一套**。
 */
const selRange = ref<{ start: number; end: number } | null>(null)
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

/**
 * 章节正文缓存（键 = 它在 `flat` 里的位置；容量很小）。
 *
 * 它只为**一件事**服务：滚动读到一章末尾时能**立刻接上**下一章。下一章先取好，
 * 到底部时就地切换，中间不再有「请求往返 → 空白 → 新正文」那一段 ——
 * 这正是「无缝」的全部内容（也正是不预取时最容易被说成「卡一下」的地方）。
 */
const chapterCache = new Map<number, { html: string; title: string }>()
/** 正在飞的章节请求（键 = `flat` 位置）：同一章的并发合成一次（见 `chapterAt`） */
const chapterInflight = new Map<number, Promise<{ html: string; title: string }>>()
// 第 69 期：4 → 6。连续流的窗口是 3 章，且「向上前插」与「向下后补」会同时发生 ——
// 4 太紧，补一章就把正要用的邻章挤掉，于是滚回边界时又得重新请求（表现就是「卡一下」）。
// 仍然是有界缓存，不随书长增长。
const CACHE_MAX = 6

async function chapterAt(p: number): Promise<{ html: string; title: string }> {
  const cached = chapterCache.get(p)
  if (cached) return cached
  // 同一章的**并发**只发一次请求（第 69 期）：连续流里「补齐窗口」与「滚动补章」会同时
  // 想要同一章，没有这道去重就会白发一次请求，两个结果回来还会互相覆盖。
  const running = chapterInflight.get(p)
  if (running) return running
  const ch = flat.value[p]
  const job = (async () => {
    // 第 93 期：在线模式**唯一的取数裂缝** —— 其余（渲染 / 版式 / 滚动 / 分页 / 目录）
    // 与本地逐字共用。服务端已经把源站标记压成纯文本，这里的 `html` 只含 `<p>`。
    //
    // ⚠️ 两条分支**各自**取数、各自处理自己的附带字段，不要写成
    // `const data = isOnline ? await A : await B` 再靠 `'origin' in data` 收窄 ——
    // `OnlineChapter` 是 `ChapterContent` 的子类型，那个 `in` 判据收窄不出干净的类型
    // （实测得到 `ChapterContent & Record<'origin', unknown>`），字段全变成 `unknown`。
    let bodyHtml = ''
    let bodyTitle = ''
    if (isOnline.value) {
      const data = await api.onlineChapter(bookId.value, ch.index)
      // 横幅的四个字段随**每一章**更新：断网时只有某几章命中缓存，标注必须跟着变，
      // 不能只在打开时定一次（那样读者会把缓存章当成刚取回来的）
      onlineInfo.value = {
        display_name: data.display_name, url: data.url,
        origin: data.origin, stale: data.stale, cached_at: data.cached_at,
      }
      onlineLocalIndex.value = data.local_index
      bodyHtml = data.html
      bodyTitle = ch.title || data.title
    } else {
      const data = await api.chapter(bookId.value, ch.index)
      // 第 89 期：TXT 书的解码报告随章节带回（EPUB 等格式不带 ⇒ 保持 null）。
      if (data.text_encoding) textEncoding.value = data.text_encoding
      bodyHtml = data.html
      bodyTitle = ch.title || data.title
    }
    const item = { html: bodyHtml, title: bodyTitle }
    chapterCache.set(p, item)
    // 只留最近几章：缓存的是整章 HTML，留太多是真金白银的内存
    while (chapterCache.size > CACHE_MAX) {
      const oldest = chapterCache.keys().next().value
      if (oldest === undefined) break
      chapterCache.delete(oldest)
    }
    return item
  })()
  chapterInflight.set(p, job)
  try {
    return await job
  } finally {
    chapterInflight.delete(p)
  }
}

/**
 * 章节加载的**请求序号**：只有最后一次发起的请求才允许落地。
 *
 * 这是「目录点了跳错位置」的一个真实成因：连点两个条目时，先发的慢响应可能后到，
 * 把后发的那一章覆盖掉 —— 界面显示 A、高亮与进度却在 B。
 */
let loadSeq = 0

// ---------------- 滚动模式：跨章连续流（第 69 期）----------------
//
// 与单章路径的分工：**滚动模式不替换正文**，而是把「可见章 + 前后各一章」挂在同一滚动
// 容器里首尾相接。于是「读到底自动接下一章」不再是「换一章 + 滚回顶部」，而是**下方本来
// 就有**；往上滚也能接着读上一章。可调参数的唯一真值源在 `lib/readerFlow.ts`（有单测）。

/** 章块容器元素（量几何、定位用） */
function chunkEl(p: number): HTMLElement | null {
  return chunkEls.get(p) ?? null
}

/**
 * 章块的**正文**元素（`.reader-content`）。
 *
 * 必须与量几何的容器分开：容器里还挂着我们加的章标题，`textContent` 会把标题也算进去 ——
 * 而进度的 `offset` 与批注的 `start_off` 必须与**后端单章正文**同一把尺子量（见 `epub_cfi.py`）。
 */
function chunkArt(p: number): HTMLElement | null {
  return chunkEl(p)?.querySelector<HTMLElement>('.reader-content') ?? null
}

/** 当前章的正文 root：单章路径是 `contentRef`，连续流是**可见章**那一块 */
function currentChapterRoot(): HTMLElement | null {
  return flowMode.value ? chunkArt(pos.value) : contentRef.value
}

/** 窗口内所有章块的正文 root（「不知道在哪一章」的操作扫这个，如按 id 解包批注） */
function allChapterRoots(): HTMLElement[] {
  if (!flowMode.value) {
    const root = contentRef.value
    return root ? [root] : []
  }
  const out: HTMLElement[] = []
  for (const c of chunks.value) {
    const el = chunkArt(c.pos)
    if (el) out.push(el)
  }
  return out
}

/**
 * 量出窗口内章块的几何（坐标系 = 滚动容器**内容坐标**，与 `scrollTop` 同一把尺子）。
 *
 * 每次现量、不缓存：章块里的图片是异步解码的，缓存下来的高度会过期 ——
 * 而过期的高度会直接变成「跳一屏」。O(章块数=3) 的测量本身很便宜。
 */
function measureChunks(): ChunkGeom[] {
  const box = scrollRef.value
  if (!box) return []
  const boxRect = box.getBoundingClientRect()
  const out: ChunkGeom[] = []
  for (const c of chunks.value) {
    const el = chunkEl(c.pos)
    if (!el) continue
    const r = el.getBoundingClientRect()
    out.push({ pos: c.pos, top: r.top - boxRect.top + box.scrollTop, height: r.height })
  }
  return out
}

/** 把话题滚到「第 `p` 章的章内 `frac` 处」 */
function scrollToChunk(p: number, frac: number): void {
  const box = scrollRef.value
  const geom = chunkGeomOf(measureChunks(), p)
  if (!box || !geom) return
  box.scrollTop = Math.max(0, geom.top + frac * geom.height)
}

/** 该章正文是否**自带标题**（`chapter_html` 抽的是 body，多数书的 body 里就有 `<h1>`） */
function bodyHasHeading(html: string): boolean {
  return /^\s*<h[1-6][\s>]/i.test(html)
}

/** 由「位置 + 已取到的正文」造一个章块（标题优先用目录里的，与单章路径同一口径） */
function flowChunkOf(p: number, item: { html: string; title: string }): FlowChunk {
  const f = flat.value[p]
  return { pos: p, index: f?.index ?? 0, title: f?.title || item.title, html: item.html }
}

/** 章块落地的串行链（见 `applyChunks`：并发补/裁会让锚点补偿互相穿插） */
let chunkWriteChain: Promise<void> = Promise.resolve()

/**
 * 章块列表的规范化：按 `pos` 去重（后者胜）并升序。
 *
 * 去重不是洁癖而是**渲染层的硬要求**：`v-for` 的 `:key` 是 `pos`，一旦重复，Vue 的
 * patch 行为就没有定义了 —— 实测会渲染出「上一章排在中间」这种错序 DOM。
 * 补章有两条并发路径（`fillFlowWindow` 与 `maintainFlowWindow`），谁先谁后不由我们决定，
 * 所以「绝不允许重复」必须在这里兜住，不能只指望调用方不撞车。
 */
function normalizeChunks(list: FlowChunk[]): FlowChunk[] {
  const byPos = new Map<number, FlowChunk>()
  for (const c of list) byPos.set(c.pos, c)
  return [...byPos.values()].sort((a, b) => a.pos - b.pos)
}

/**
 * 落章块并**保持视觉位置** —— 这就是「无缝」的物理实现。
 *
 * 向下**追加**不移动上方内容 ⇒ 锚块实测位移为 0 ⇒ 同一份代码天然覆盖「追加不补偿」；
 * 向上**前插**会把锚块整体推下 ⇒ 同量加大 `scrollTop`；**裁掉上方**则反号回补。
 *
 * 为什么用**锚元素实测位移**而不是 `scrollHeight` 差值：标题留白、图片占位都会被一起算进去，
 * 而算高度差需要事先知道「插了多少」，漏一项就会跳。`scrollCompensation` 收的是
 * 「上方净增高度」，这里的 `delta` 正是它的实测值（负数 = 上方净减）。
 *
 * ⚠️ 两笔补/裁**不能并发**：补偿是「量一次 → 改 DOM → 再量一次」，穿插执行会让后一笔量到的
 * 位移里含了前一笔的改动 ⇒ 补偿量算重。所有落地都排在同一条串行链上（`chunkWriteChain`）。
 *
 * 也因为这个排队：`next` 是**调用时**的快照，轮到它执行时窗口里可能已经多了别的章
 * （另一条路径刚补的）。所以这里按语义合并 —— `replace` 表示「这就是全部」（跳转重建窗口），
 * 否则默认**并入**（只丢掉 `drop` 明确指出要裁的那几块），不会拿旧快照覆盖掉新补的章。
 */
function applyChunks(
  next: FlowChunk[],
  anchorPos: number | null,
  opts: { drop?: number[]; replace?: boolean } = {},
): Promise<void> {
  const run = async (): Promise<void> => {
    const box = scrollRef.value
    // 锚取**正文 article** 而不是外层 `<section>`：章节块的上下留白（`mt-10` / `pt-6`）会随
    // 「是不是第一块」（`first:` 变体）变化，`<section>` 的 border-box 顶边量不到它自己的
    // 内边距 —— 实测会漏掉 24px，读起来就是前插时正文被轻轻推了一下。article 的顶边把
    // 外层 margin、边框与内边距**一起**算在内，正好是读者眼里「正文的位置」。
    const anchorEl = anchorPos === null ? null : chunkArt(anchorPos)
    const beforeTop = box?.scrollTop ?? 0
    const beforeRect = anchorEl?.getBoundingClientRect().top ?? 0
    const drop = new Set(opts.drop ?? [])
    const base = opts.replace ? [] : chunks.value.filter((c) => !drop.has(c.pos))
    chunks.value = normalizeChunks([...base, ...next])
    await nextTick()
    if (!box || !anchorEl || !anchorEl.isConnected) return
    const delta = anchorEl.getBoundingClientRect().top - beforeRect
    // `delta` 就是「上方净增高度」的实测值（负数 = 上方净减），与 `scrollCompensation` 同一口径。
    // ⚠️ 必须写成**绝对值** `beforeTop + 补偿量`，不能 `scrollTop += 补偿量`：
    // 浏览器自带的滚动锚定（scroll anchoring）很可能已经替我们把 scrollTop 调好了，那时
    // `delta` 已≈0 —— 绝对写入是幂等的，相对累加会把同一段位移**补两次**，反倒跳得更凶。
    if (Math.abs(delta) >= 1) box.scrollTop = Math.max(0, beforeTop + scrollCompensation(delta, 0))
  }
  chunkWriteChain = chunkWriteChain.then(run, run)
  return chunkWriteChain
}

/** 续接单飞闸：一次只跑一趟补/裁，避免滚动连发把窗口搅乱 */
let flowBusy = false

/**
 * 把窗口里**还缺的**那几章补齐（异步、静默）。
 *
 * 失败只当「少一块」：当前章已经能读了，邻章晚点会在滚动时由 `maintainFlowWindow` 再补一次。
 */
async function fillFlowWindow(p: number, seq: number): Promise<void> {
  const want = computeWindow(p, total.value, prefs.value.autoNextChapter)
  const have = new Set(chunks.value.map((c) => c.pos))
  const missing = want.filter((q) => !have.has(q))
  if (!missing.length) return
  const got = await Promise.all(missing.map(async (q) => {
    try { return flowChunkOf(q, await chapterAt(q)) } catch { return null }
  }))
  // 期间又跳了别处 ⇒ 这批结果作废（与单章路径同一套「请求序号」纪律）
  if (seq !== loadSeq) return
  // ⚠️ 必须**在 await 之后**重新看一眼窗口里已有什么：取数期间用户可能已经滚过，
  // `maintainFlowWindow` 很可能把同一章补了进来 —— 沿用取数前那份 `have` 就会并入重复项。
  const now = new Set(chunks.value.map((c) => c.pos))
  const added = got.filter((c): c is FlowChunk => c !== null && !now.has(c.pos))
  if (!added.length) return
  await applyChunks(added, p)
  applyHighlights()
}

/**
 * 连续流：以 `p` 为中心重建章块窗口，并把阅读位置落到 `p`（第 69 期）。
 *
 * 「无缝」不在这里 —— 这里的每一次跳转都是**用户显式发起**的（目录 / 书签 / 批注 /
 * 恢复位置 / 上一章下一章），落点就该是目标章（章内精确偏移由 `restoreOffset` 给）。
 * 滚动过程中的相邻章补/裁见 `maintainFlowWindow`。
 *
 * 两段式渲染：**先只挂当前章**（首屏立刻可读，不被邻章的请求拖住），邻章到了再合并 ——
 * 合并走 `applyChunks` 的锚点补偿，所以视觉上不会跳。
 */
async function loadFlowAt(p: number, restore?: number, restoreOffset?: number): Promise<void> {
  const seq = ++loadSeq
  chapterLoading.value = !chapterCache.has(p)
  let item: { html: string; title: string }
  try {
    item = await chapterAt(p)
  } catch (e) {
    if (seq !== loadSeq) return
    chapterLoading.value = false
    error.value = e instanceof Error ? e.message : '章节加载失败'
    return
  }
  if (seq !== loadSeq) return
  chapterLoading.value = false
  error.value = ''
  pos.value = p
  chapterTitle.value = flowChunkOf(p, item).title
  await applyChunks([flowChunkOf(p, item)], null, { replace: true })
  // 定位：优先用精确偏移（第 54 期 CFI 反解的**章内**字符偏移，与 `saveProgress` 同一
  // 坐标系）；换算不了（正文未挂载 / 长度为 0）再回落 `restore`（全书百分比反推的章内比例）。
  let frac = restore ?? 0
  const len = chunkArt(p)?.textContent?.length ?? 0
  if (restoreOffset !== undefined && len > 0) {
    frac = Math.min(1, Math.max(0, restoreOffset / len))
  }
  scrollToChunk(p, frac)
  local.value = frac
  applyHighlights()
  // 邻章与「静默预取」共用一条路：补齐窗口 = 顺带把下一章取进 `chapterCache`
  void fillFlowWindow(p, seq)
}

/**
 * 滚动中按可见章维护窗口：需要就补一章、离得够远就裁一章（第 69 期）。
 *
 * 两条边界纪律：
 * 1. **向后（未来章）的自动扩展受开关管**，向前（历史章）始终补 ——「向上滚能读回上一章」
 *    与开关无关，开关只管「要不要自动往后接」；
 * 2. 裁剪必须过 `canTrim`（完全离开视口且上下各留一屏），不满足就留着 ——
 *    惯性滚动甩出空白比「多挂一章」糟得多。
 */
async function maintainFlowWindow(v: number): Promise<void> {
  if (flowBusy || !flowMode.value) return
  const box = scrollRef.value
  if (!box) return
  flowBusy = true
  try {
    const want = computeWindow(v, total.value, prefs.value.autoNextChapter)
    const have = new Set(chunks.value.map((c) => c.pos))
    const toAdd = want.filter((q) => !have.has(q) && (q < v || prefs.value.autoNextChapter))
    const geoms = measureChunks()
    const toDrop = chunks.value
      .filter((c) => !want.includes(c.pos))
      .filter((c) => {
        const g = chunkGeomOf(geoms, c.pos)
        return !!g && canTrim(g, box.scrollTop, box.clientHeight)
      })
      .map((c) => c.pos)
    if (!toAdd.length && !toDrop.length) return
    const added: FlowChunk[] = []
    for (const q of toAdd) {
      try { added.push(flowChunkOf(q, await chapterAt(q))) } catch { /* 补章失败保持现状 */ }
    }
    const drop = new Set(toDrop)
    if (!added.length && !toDrop.length) return
    // 锚块 = 「补/裁之前就挂着、裁完之后仍在」的最靠上那一块（`chunks` 恒为升序）。
    // ⚠️ 不能用「补完之后」里最靠上的一块：**新补进来的章块此刻还没有 DOM**，`chunkArt`
    // 返回 `null` ⇒ 补偿量根本算不出来 ⇒ 前插时正文会被整体按下，看起来就是「向上跳了一屏」。
    const anchorPos = chunks.value.find((c) => !drop.has(c.pos))?.pos ?? null
    await applyChunks(added, anchorPos, { drop: toDrop })
    applyHighlights()
  } finally {
    flowBusy = false
  }
  // 补章是异步的，期间可见章可能又往前走了（用户还在滚）⇒ 立刻按最新位置再校一趟。
  // 少了这一步会卡在「窗口边界 + 没有新内容」：底部到头后滚动事件不再发，窗口也就不再补，
  // 用户必须自己往上滚一下再滚下来才能继续读 —— 这正是「自由滚动」最不该有的那种别扭。
  if (flowMode.value && pos.value !== v) void maintainFlowWindow(pos.value)
}

/**
 * 连续流的滚动热路径：只做 O(章块数=3) 的测量与比较，**不写布局**。
 * 会动 DOM 的补/裁交给 `maintainFlowWindow`（异步 + 单飞闸）。
 */
function onFlowScroll(): void {
  const box = scrollRef.value
  if (!box) return
  const geoms = measureChunks()
  const v = pickVisiblePos(geoms, box.scrollTop, box.clientHeight)
  if (v !== pos.value) {
    pos.value = v
    chapterTitle.value = chunks.value.find((c) => c.pos === v)?.title ?? ''
  }
  local.value = localFractionIn(chunkGeomOf(geoms, v), box.scrollTop)
  scheduleSave()
  void maintainFlowWindow(v)
}

/**
 * 跳/翻到第 `p` 章（上一章 / 下一章按钮）。
 *
 * 连续流下如果这一章**已经在窗口里**就地滚过去就好：不重建、不取数、不闪「加载中」——
 * 用户点「下一章」的预期是「翻过去」，不是「重新加载一次」。
 */
function goToChunk(p: number): void {
  if (p < 0 || p >= total.value) return
  if (flowMode.value && chunkEl(p)) {
    pos.value = p
    chapterTitle.value = chunks.value.find((c) => c.pos === p)?.title ?? ''
    local.value = 0
    scrollToChunk(p, 0)
    scheduleSave()
    void maintainFlowWindow(p)
    return
  }
  void loadChapter(p)
}

async function loadChapter(p: number, restore?: number, restoreOffset?: number): Promise<void> {
  if (!total.value) return
  p = Math.min(Math.max(0, p), total.value - 1)
  const ch = flat.value[p]
  if (!ch || ch.index === undefined) {
    error.value = '目录里的这一条没有可定位的章节序号'
    return
  }
  // 滚动模式：不替换正文，改走「以 p 为中心重建章块窗口 + 章块内定位」
  if (flowMode.value) {
    await loadFlowAt(p, restore, restoreOffset)
    return
  }
  pos.value = p
  const seq = ++loadSeq
  // 已预取的章节**不再闪「加载中」**：那一刻并没有在等网络
  chapterLoading.value = !chapterCache.has(p)
  try {
    const item = await chapterAt(p)
    if (seq !== loadSeq) return              // 过期响应：丢弃，绝不覆盖后发的那一章
    html.value = item.html
    chapterTitle.value = ch.title || item.title
    error.value = ''
    // 预取下一章（静默）：滚到底时才接得上（失败不影响当前章）
    if (p + 1 < total.value) void chapterAt(p + 1).catch(() => {})
  } catch (e) {
    if (seq !== loadSeq) return
    error.value = e instanceof Error ? e.message : '章节加载失败'
    return
  } finally {
    if (seq === loadSeq) chapterLoading.value = false
  }
  await nextTick()
  applyHighlights()
  const el = scrollRef.value
  if (el) {
    // 第 54 期：优先用精确偏移（CFI 反解的章内字符偏移，与保存时同一 textContent
    // 坐标系）；换算不了（正文未挂载 / 长度为 0）再回落「全书百分比反推」的章内
    // 比例 —— 后者与改造前行为逐字一致。
    let frac = restore
    if (restoreOffset !== undefined) {
      const len = contentRef.value?.textContent?.length ?? 0
      if (len > 0) frac = Math.min(1, Math.max(0, restoreOffset / len))
    }
    el.scrollTop = frac !== undefined ? Math.max(0, frac * (el.scrollHeight - el.clientHeight)) : 0
  }
  local.value = localFraction()
}

function prev(): void {
  if (pos.value > 0) goToChunk(pos.value - 1)
}

function next(): void {
  if (pos.value < total.value - 1) goToChunk(pos.value + 1)
}

/**
 * 目录视图模型（第 61 期修「点了不跳 / 跳错位置」）：**每项自带它在 `flat` 里的位置**，
 * 点击只按位置跳，不再回查后端的章节序号。
 *
 * 为什么不按后端 `index` 找：`flat` 会跳过 `index === undefined` 的条目，而目录面板用的是
 * 后端原始结构 —— 两边一旦不同步，`findIndex` 就找不到（⇐ 表现为「点了没反应」），
 * 或命中同序号的另一条（⇐ 表现为「跳错位置」）。位置是同序遍历出来的，天然对齐。
 *
 * 第 85 期：分组与段名收敛到 `lib/chapterGroups.ts`（与详情页「目录」标签**共用一份规则**，
 * 免得两处各写一遍「无名段叫什么」）。
 */
const tocView = computed(() => tocGroups(book.value?.chapters))

/** 目录里折叠起来的段（按 `TocGroup.key` 记）。**只存组件内**：不落盘、不加偏好项 */
const collapsedToc = ref<Record<string, boolean>>({})

function toggleTocGroup(key: string): void {
  collapsedToc.value[key] = !collapsedToc.value[key]
}

/** 跳转（按 `flat` 位置）：越界即忽略并给出反馈，不做静默无事发生 */
function gotoPos(p: number): void {
  if (p < 0 || p >= total.value) {
    ui.toast('该目录项无法定位（章节序号缺失）')
    return
  }
  showToc.value = false
  void loadChapter(p)
}

// ---------------- 进度 ----------------

let saveTimer: ReturnType<typeof setTimeout> | null = null

/** 进度写入的去抖：滚动会连发，必须合并成一次写 */
function scheduleSave(): void {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(saveProgress, 800)
}

function onScroll(): void {
  // 滚动模式：正文是「章块窗口」，位置口径变成**可见章 + 章内比例**（见 `onFlowScroll`）
  if (flowMode.value) {
    onFlowScroll()
    return
  }
  local.value = localFraction()
  scheduleSave()
  void maybeAutoNext()
}

/** 距底部多少像素就算「读到了这一章的末尾」（留一点余量，别要求滚到最后一像素） */
const AUTO_NEXT_PX = 160
let advancing = false

function atChapterEnd(): boolean {
  const el = scrollRef.value
  if (!el) return false
  return el.scrollTop + el.clientHeight >= el.scrollHeight - AUTO_NEXT_PX
}

/**
 * 滚动读到一章末尾 → 自动接上下一章（第 61 期；**第 69 期起连续流不再走这里**）。
 *
 * 两条纪律：
 * 1. **先确保下一章已在缓存里，再切换** —— 反过来写就退化成「自动点了一下下一章」，
 *    该有的加载空档一个不少，那就不是无缝；
 * 2. **翻页模式不在这里处理** —— 它走 `flip()` 的末页判定，用户明确没要改那条路径。
 *
 * ⚠️ 可重排 EPUB 的滚动模式改由「章块窗口」接续（下一章本来就挂在下方，不存在「切换」；
 * 见 `maintainFlowWindow`），所以这里只剩**固定版式**那条旧路径在走。守卫里保留
 * `flowMode` 判断是必须的：否则固定版式之外的路径还会再「换一次章」，把连续流打断。
 */
async function maybeAutoNext(): Promise<void> {
  if (advancing || paged.value || isPdf.value || isComic.value || flowMode.value) return
  if (!prefs.value.autoNextChapter || !total.value) return
  if (pos.value >= total.value - 1 || !atChapterEnd()) return
  advancing = true
  try {
    const next = pos.value + 1
    await chapterAt(next)
    if (pos.value < total.value - 1) await loadChapter(next)
  } catch {
    /* 预取失败就保持现状：用户滚到底时还能看到「下一章」按钮，不会卡死在读了一半的地方 */
  } finally {
    advancing = false
  }
}

/** 去抖里还没发出的那一次，立刻补发（切后台 / 关页面 / 离开阅读器时用） */
function flushPendingProgress(): void {
  if (!saveTimer) return
  clearTimeout(saveTimer)
  saveTimer = null
  void saveProgress()
}

async function saveProgress(): Promise<void> {
  if (!book.value || !total.value) return
  if (isOnline.value) {
    // 在线模式**不写 `/progress`**：本地进度由服务端按「线上章 ↔ 本地章」的窗口规则
    // 决定写不写（对不上就一个字都不写）。前端只报「当前可见的是线上第几章」——
    // 两份位置并存、不互相覆盖，这是跨客户端续读能对上的前提。
    try {
      const r = await api.onlineSetPos(bookId.value, currentIndex.value)
      onlineLocalIndex.value = r.local_index
      if (r.local_index !== null && r.local_total > 0) {
        // 不带时间戳：我们手上没有服务端那次写入的 `updated_at`，编一个会让
        // 「其他设备更新了进度」那条提示拿它当基准（第 56 期的 ownWriteAt 语义）。
        library.patchProgress(bookId.value, (r.local_index * 100) / r.local_total)
      }
    } catch {
      /* 离线或未登录时静默：位置本身已经记在服务端 */
    }
    return
  }
  try {
    // 第 54 期：EPUB 附带章内字符偏移（textContent 坐标），服务端据此生成 CFI；
    // 算不出（正文未挂载）就不带 —— 进度本身照常保存，恢复侧回落百分比。
    // 第 69 期：连续流下「本章长度」= **可见章**那一块的长度，不是整条流的长度 ——
    // `local` 与 `currentIndex` 也都是可见章口径，三者必须同一把尺子，否则 CFI 偏移会落错位置。
    const len = currentChapterRoot()?.textContent?.length ?? 0
    const offset = len > 0 ? Math.round(local.value * len) : undefined
    const r = await api.setProgress(
      bookId.value, currentIndex.value, overallPercent.value, offset, fileRel.value,
    )
    // 第 56 期：记下本机这次写入的时间戳 —— 轮询时只有比它更新的写入才可能是别的设备
    if (typeof r?.updated_at === 'number') ownWriteAt.value = r.updated_at
    // 第 61 期：把刚写下的进度**就地**同步给书库 store —— 返回首页时「继续阅读」立刻是新值
    library.patchProgress(bookId.value, overallPercent.value, r?.updated_at)
  } catch {
    /* 离线或未登录时静默 */
  }
}

// ---------------- 多设备进度提示（第 56 期）----------------
// 语义：**只提示、绝不静默挪阅读位置**。轮询到「别的设备写过、且位置确实不同」时
// 只渲染一条可点提示；用户点「跳过去」才跳，点「忽略」则本机位置原样不动。

/** 本机已知的最新写入时间（载入时读到的 / 每次 PUT 回来的） */
const ownWriteAt = ref(0)
/** 待处理的「别的设备进度」；null = 没有提示 */
const remoteNote = ref<{ locator: number; percent: number; offset?: number } | null>(null)
/** 轮询间隔：8s（本地单用户场景，够快又不至于打扰服务端） */
const PROGRESS_POLL_MS = 8000
let progressTimer: ReturnType<typeof setInterval> | null = null

/** 提示条里的目标位置文案 */
const remoteLabel = computed(() => {
  const n = remoteNote.value
  if (!n) return ''
  const pct = Math.max(0, Math.min(100, n.percent || 0))
  return `${titleOf(n.locator)} · ${pct.toFixed(1)}%`
})

async function checkRemoteProgress(): Promise<void> {
  // 后台标签页不轮询：看不见就没有必要打扰服务端（与阅读时长 accrual 同一条纪律）
  if (document.visibilityState !== 'visible' || !book.value || !total.value) return
  try {
    // ⚠️ 轮询**必须按本机正在读的那个文件**问（第 63 期 4/6），不能用书级：
    // 提示条上那个「跳过去」按钮只能落在**本机的坐标系**里 —— 别处把 PDF 读到了
    // 第 90 页，而本机是 EPUB 的章节流，拿那个 locator 去 `flat` 里找会跳到一个
    // 毫不相干的章节（页码与 spine 序号是两套坐标系）。所以提示的语义是
    // 「**这个文件**在别处被读到别的位置了」，不是「这本书在别处被读过」。
    // 书级（不给 file_rel）只用于书架百分比 / Komga / KOReader 那些不需要跳转的地方。
    const p = await api.getProgress(bookId.value, fileRel.value)
    const at = typeof p.updated_at === 'number' ? p.updated_at : 0
    if (!at || at <= ownWriteAt.value + 1) {
      remoteNote.value = null
      return
    }
    // 位置其实一样（别的设备只是路过同一处）⇒ 不打扰
    const sameChapter = p.locator === currentIndex.value
    const drift = Math.abs((p.percent || 0) - overallPercent.value)
    if (sameChapter && drift < 0.5) {
      remoteNote.value = null
      return
    }
    remoteNote.value = { locator: p.locator, percent: p.percent || 0, offset: p.offset }
  } catch {
    /* 离线 / 未登录：静默，下一轮再试 */
  }
}

function startProgressWatch(): void {
  stopProgressWatch()
  progressTimer = setInterval(() => void checkRemoteProgress(), PROGRESS_POLL_MS)
}

function stopProgressWatch(): void {
  if (progressTimer) clearInterval(progressTimer)
  progressTimer = null
}

/** 采纳别的设备的进度（**只有用户显式点击才走这里**） */
async function applyRemoteProgress(): Promise<void> {
  const n = remoteNote.value
  if (!n) return
  const t = flat.value.findIndex((f) => f.index === n.locator)
  if (t >= 0) {
    const restore = n.offset === undefined
      ? Math.min(1, Math.max(0, (n.percent / 100) * total.value - t))
      : undefined
    await loadChapter(t, restore, n.offset)
    // 立刻把本机位置写回去：下一轮轮询若还比对本机旧时间戳，会重复提示同一件事
    void saveProgress()
  }
  remoteNote.value = null
}

// ---------------- 高亮 / 批注 ----------------

/**
 * 某个节点落在窗口里的哪一章块（找不到返回 `null`；非连续流恒为 `null`）。
 *
 * 靠 `.nf-chunk` 往上找容器，再回查元素表 —— **不靠 `pos` 推算**：章块位置会随窗口
 * 滑动整体变化，而 DOM 归属不会。
 */
function chunkPosOfNode(node: Node | null): number | null {
  if (!flowMode.value || !node) return null
  const el = node instanceof HTMLElement ? node : node.parentElement
  const sect = el?.closest('.nf-chunk')
  if (!sect) return null
  for (const [p, e] of chunkEls) if (e === sect) return p
  return null
}

/**
 * 选区所在的章块位置（连续流）。
 *
 * 必须记下来：`selRange` 的字符偏移是**相对该章正文**算的，而选区完全可能落在
 * 「可见章之外」的那一块（用户往上拖过章界），那时 `pos` 指的不是这一章。
 */
const selChunkPos = ref<number | null>(null)

function onSelect(): void {
  // 在线模式不批注（见 `isOnline` 那段注释：锚指向的文本两边不是同一份）。
  // 这里拦一道、UI 再隐藏一道 —— 双保险：UI 漏改了也不会存下一个指不清位置的锚。
  if (isOnline.value) return
  const sel = window.getSelection()
  const anchor = sel?.anchorNode ?? null
  // 连续流下正文有 2–3 个 root，必须按**选区自己**落在哪一块来选 root：
  // 继续用「全局唯一的 `contentRef`」会让往上拖过章界的选区直接判成无效。
  const chunkPos = chunkPosOfNode(anchor)
  const content = flowMode.value
    ? (chunkPos === null ? null : chunkArt(chunkPos))
    : contentRef.value
  if (!sel || sel.isCollapsed || !content) {
    selPos.value = null
    selRange.value = null
    selChunkPos.value = null
    return
  }
  const text = sel.toString().trim()
  if (!text || text.length > 500) {
    selPos.value = null
    selRange.value = null
    selChunkPos.value = null
    return
  }
  if (!anchor || !content.contains(anchor)) {
    selPos.value = null
    selRange.value = null
    selChunkPos.value = null
    return
  }
  const rect = sel.getRangeAt(0).getBoundingClientRect()
  selText.value = text
  // 章内字符偏移锚（第 63 期 6/6）：**现在算**，等 DOM 被 `v-html` 重渲染过再算就晚了
  //（选区锚点会随着 DOM 替换失效）。取不到就算了 —— 那只是回落成按文本搜索，
  // 与加锚之前的行为一样，不是错误。
  selRange.value = selectionRange(content)
  selChunkPos.value = chunkPos
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

function wrapRange(range: Range, color: string, style: string, id: number): boolean {
  const span = document.createElement('span')
  span.className = 'nf-hl'
  span.dataset.annoId = String(id)
  applyAnnoStyle(span, color, style)
  try {
    range.surroundContents(span)
    return true
  } catch {
    // 区间跨到了元素边界（`surroundContents` 不接受部分选中的非文本节点）——
    // 与「找不到」同样处理：交给下一种定位方式。
    return false
  }
}

/** 定位方式②：按引文搜索，用**第一个**匹配（第 63 期之前的唯一方式，现为回落）。 */
function wrapByText(root: HTMLElement, quote: string, color: string, style: string, id: number): boolean {
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
    return wrapRange(range, color, style, id)
  }
  return false
}

/**
 * 定位一条批注：**先按字符偏移锚，验不过再退回按文本搜索**。
 *
 * 顺序不能反。偏移锚能解决「同一章里同一句话出现两次 ⇒ 高亮错一处」，而文本搜索
 * 正是那个会错的判据 —— 只有在锚不可用/对不上时才该用它兜底。
 *
 * ⚠️ **锚对不上就不画，绝不硬画**：书文件换了（重新制版 / 换译本 / 章节切分变了）之后，
 * 老偏移仍是个合法下标，但会指到一段**无关的文字**上。照偏移直接画＝把用户的批注
 * 悄悄挪到别处，比不画更糟。所以这里核对锚点处取出的文字**必须包含引文**才算数。
 * 用 `includes` 而不是 `===`：`Range.toString()` 会把跨节点的空白原样拼出来，
 * 而 `quote` 是 `sel.toString().trim()` 过的，两者未必逐字相等。
 */
function wrapQuote(root: HTMLElement, quote: string, color: string, style: string, id: number,
                   startOff = -1, endOff = -1): boolean {
  if (startOff >= 0 && endOff > startOff) {
    const hit = rangeAt(root, startOff, endOff)
    if (hit && hit.text.replace(/\s+/g, ' ').includes(quote.replace(/\s+/g, ' '))) {
      if (wrapRange(hit.range, color, style, id)) return true
    }
  }
  return wrapByText(root, quote, color, style, id)
}

/**
 * 把批注画到正文上。
 *
 * 第 69 期两处调整，都因为「正文不再只有一个 root」：
 * 1. **按章块 root 分别画**（每块只画属于自己那一章的批注）—— 画错 root 会在别的章里
 *    按文本搜到同一句话，把高亮画到不相干的位置；
 * 2. 画之前**先解包该 root 里已有的批注 span**：窗口滑动时 Vue 会复用同一块 DOM
 *    （`v-html` 内容没变就不重建），重复包裹会变成 span 套 span，颜色与选区都会坏掉。
 */
function applyHighlights(): void {
  if (!flowMode.value) {
    const root = contentRef.value
    if (!root) return
    unwrapAll(root)
    for (const a of chapterAnnotations.value) {
      wrapQuote(root, a.quote, a.color, a.style, a.id, a.start_off, a.end_off)
    }
    return
  }
  // 批注按章号索引一次：否则每块都要把全部批注筛一遍，章多时是无谓的开销
  const byChapter = new Map<number, Annotation[]>()
  for (const a of annotations.value) {
    const list = byChapter.get(a.chapter)
    if (list) list.push(a)
    else byChapter.set(a.chapter, [a])
  }
  for (const c of chunks.value) {
    const root = chunkArt(c.pos)
    if (!root) continue
    unwrapAll(root)
    for (const a of byChapter.get(c.index) ?? []) {
      wrapQuote(root, a.quote, a.color, a.style, a.id, a.start_off, a.end_off)
    }
  }
}

async function addHighlight(color: string): Promise<void> {
  // 在线模式不写批注（入口已隐藏，这里是双保险）：锚是本地文本偏移，
  // 存下来的话换成本地阅读器去跳会指到别处。
  if (isOnline.value) return
  const quote = selText.value
  if (!quote) return
  const note = noteDraft.value.trim()
  const style = selStyle.value
  const span = selRange.value
  // 第 69 期：批注落在**选区所在的那一章**，而不是「此刻的可见章」——
  // 往上拖过章界的选区，可见章可能已经不是它了（偏移则会落错章）。
  const selChapterPos = selChunkPos.value
  const selChunk = flowMode.value && selChapterPos !== null
    ? chunks.value.find((c) => c.pos === selChapterPos)
    : undefined
  const chapterIdx = selChunk?.index ?? currentIndex.value
  selPos.value = null
  selRange.value = null
  selChunkPos.value = null
  noteDraft.value = ''
  selText.value = ''
  window.getSelection()?.removeAllRanges()
  try {
    const r = await api.addAnnotation(bookId.value, {
      chapter: chapterIdx,
      quote,
      color,
      note,
      style,
      start_off: span ? span.start : -1,
      end_off: span ? span.end : -1,
    })
    annotations.value.push({
      id: r.id,
      chapter: chapterIdx,
      quote,
      color,
      note,
      style,
      created_at: Date.now() / 1000,
      anchor: '',
      start_off: span ? span.start : -1,
      end_off: span ? span.end : -1,
    })
    // 只包裹**新增的这条**：整章重扫会对已包裹文本重复包裹（span 套 span）。
    await nextTick()
    const root = selChunk === undefined ? contentRef.value : chunkArt(selChunk.pos)
    if (root) {
      wrapQuote(root, quote, color, style, r.id, span ? span.start : -1, span ? span.end : -1)
    }
  } catch (e) {
    ui.toast(apiErrorMessage(e, '添加批注失败'))
  }
}

/**
 * 解包一个批注 span，**不重建正文 DOM** —— 保住滚动位置 / 选区 / 阅读进度。
 *（`normalize()` 把拆开后相邻的文本节点并回去，否则同一段文字会碎成一堆文本节点，
 * 之后按偏移定位就会差出几段。）
 */
function unwrapSpan(el: Element): void {
  const parent = el.parentNode
  if (!parent) return
  while (el.firstChild) parent.insertBefore(el.firstChild, el)
  parent.removeChild(el)
  if (parent instanceof HTMLElement) parent.normalize()
}

/** 解包某条批注的 span；连续流下它可能落在窗口里任意一块，故扫全部章块 root */
function unwrapAnnotation(id: number): void {
  for (const root of allChapterRoots()) {
    root.querySelectorAll(`[data-anno-id="${id}"]`).forEach(unwrapSpan)
  }
}

/** 清掉某个 root 里**全部**批注 span（重画前的清场，幂等的前提，见 `applyHighlights`） */
function unwrapAll(root: HTMLElement): void {
  root.querySelectorAll('[data-anno-id]').forEach(unwrapSpan)
}

async function removeAnnotation(id: number): Promise<void> {
  if (isOnline.value) return
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
  // 第 69 期：连续流下「正文只此一个 root」不再成立 —— 目标章不在窗口里就先重建窗口
  // 把它带进来，再在**它自己那一块**里找 span。
  if (flowMode.value) {
    if (!chunkEl(p)) await loadChapter(p)
    await nextTick()
    chunkArt(p)?.querySelector(`[data-anno-id="${a.id}"]`)
      ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    return
  }
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
  // 在线模式不展示书签：锚是本地偏移，指不回源站正文（见 `isOnline` 那段注释）。
  if (isOnline.value) return
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
  // 书签锚是本地文本偏移 / 章号，在线模式（入口已隐藏）一律不写 —— 双保险。
  if (isOnline.value) return
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
  if (isOnline.value) return
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
  if (isOnline.value) return
  try {
    await api.deleteBookmark(bookId.value, b.id)
  } catch {
    /* ignore */
  }
  await reloadBookmarks()
}

async function restoreBookmark(b: Bookmark): Promise<void> {
  if (isOnline.value) return
  try {
    await api.restoreBookmark(bookId.value, b.id)
  } catch {
    /* ignore */
  }
  await reloadBookmarks()
}

async function purgeBookmark(b: Bookmark): Promise<void> {
  if (isOnline.value) return
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

/**
 * **一次连续阅读 = 一段 = 数据库里一行**（第 63 期）。边界规则、起点快照、失败重试
 * 全在 `lib/readingSession.ts`（纯逻辑、有单测）；这里只负责一件事：
 * **什么时候算「在读」** —— 前台且页面可见。
 *
 * 心跳仍是 30 秒：它的冗余是**故意的**（浏览器崩了最多丢最后 30 秒），
 * 别为了「少发几个请求」把它改掉。
 */
const session = createSessionReporter({
  source: 'web',
  snapshot: () => ({ percent: overallPercent.value, locator: currentIndex.value }),
  post: (secs, extra: SessionExtra) => {
    // 用**已加载的那本书**的 id，不用 route.params.id：离开阅读器时路由参数先变空，
    // 那一刻 `String(undefined)` 会发出 POST /api/books/undefined/session（404），
    // 这段时长又被 catch 塞回一个已经没人再上报的变量 ⇒ 悄悄丢掉。
    const bid = book.value?.id
    // 没有 id 就**不报**（宁可丢掉这几秒，也不报一个错的）；拒绝 = 上报失败，
    // 时长由 reporter 留着，下一段还开着的话会再试
    if (!bid) return Promise.reject(new Error('书未加载'))
    return api.recordSession(bid, secs, extra)
  },
})

/**
 * 计时管线（前台可见才累计 + 30 秒心跳 + 切后台结算）在 `lib/readingSession.ts` 里，
 * PDF / 漫画两个阅读器共用同一份 —— 边界口径只写一遍，就没有「某一处走样」的余地。
 */
let clock: ReaderClock | null = null

function startSession(): void {
  session.begin()
  clock = attachReaderClock(session, {
    // 第 61 期：进度也要**当场**落库 —— 800ms 去抖里被打断（切后台/关页面）就会白丢一段位置
    onHidden: flushPendingProgress,
  })
}

function stopSession(): void {
  clock?.accrue()      // 收尾前把最后这几秒结掉，别丢
  clock?.detach()
  clock = null
  void session.stop()
}

// ---------------- 生命周期 ----------------

/**
 * 在线模式的取数：状态 → 目录 → 把线上目录铺成与本地阅读器**同形**的 `book`。
 *
 * 铺成同形是这一整块的关键取舍：`flat` / `tocView` / `total` / 翻章 / 滚动窗口全都
 * 从 `book.chapters` 派生，换一份数据源就能整套复用 —— 于是「在线读的翻页坏掉、
 * 本地是好的」这类问题根本不存在（同一份代码）。
 *
 * ⚠️ **本地文件取不到不影响在线阅读**：它读的是源站那一页，不是本地文件
 * （这正是「本地读不了的书也要能在线读」的含义）。详情取不到就退到一个只带书名的壳。
 */
async function loadOnline(): Promise<void> {
  loading.value = true
  onlineBlocked.value = ''
  try {
    const st = await api.onlineStatus(bookId.value)
    if (!st.available) {
      // 如实说清为什么不可用，并给出回本地阅读的入口 —— 不假装能读（不做假交互）
      onlineBlocked.value = st.reason
        || (st.bound ? '在线阅读当前不可用' : '这本书还没有绑定书源')
      loading.value = false
      return
    }
    let shell: BookDetail | null = null
    try {
      shell = await api.bookDetail(bookId.value)
    } catch {
      shell = null
    }
    const toc = await api.onlineChapters(bookId.value)
    if (!toc.entries.length) {
      onlineBlocked.value = '这个书页里没有解析出章节（书源规则可能已过期）'
      loading.value = false
      return
    }
    const base = (shell ?? {
      id: bookId.value, title: toc.title || bookId.value, format: 'ONLINE',
      name: '', library_id: '', library_type: '', series: '',
    }) as unknown as BookDetail
    book.value = {
      ...base,
      // 格式钉成 `ONLINE`：在线正文一律走**可重排**那条渲染路（`fmt` 只用来选分支，
      // 见 `isPdf` / `isComic` / `isUnits`）。不钉的话「绑了一本漫画书」会去渲染
      // ComicReader —— 而它要的是本地压缩包，在线模式根本没有。
      format: 'ONLINE',
      fixed_layout: false,
      // 线上目录 → 阅读器认的那一份（`num` 给目录里的序号，`index` 就是线上章序号）
      chapters: [{
        volume: '',
        chapters: toc.entries.map((e) => ({ num: e.index + 1, title: e.title, index: e.index })),
      }],
      files: [],
    }
    onlineInfo.value = {
      display_name: toc.display_name || st.display_name,
      url: toc.url || st.url,
      origin: toc.origin, stale: toc.stale, cached_at: toc.fetched_at,
    }
    onlineCache.value = { cached: st.cache.cached, total: st.cache.total }
    loading.value = false
    startSession()
    // ⚠️ 在线模式**不轮询**「其他设备是否更新了进度」（见下面 startProgressWatch 的注释）。
    // 初始位置 = **服务端记的在线位置**：任何客户端打开都从同一处续读。
    let start = Math.min(Math.max(0, toc.pos || 0), total.value - 1)
    const q = Number(route.query.chapter)
    if (Number.isFinite(q)) {
      const t = flat.value.findIndex((f) => f.index === q)
      if (t >= 0) start = t
    }
    await loadChapter(start)
  } catch (e) {
    error.value = apiErrorMessage(e, '在线阅读加载失败')
    loading.value = false
  }
}

/** 取数并铺好**这一本**书的阅读现场。抽成函数是为了让首次挂载与同路由换书共用同一条路。 */
async function load(): Promise<void> {
  const name = String(route.name || '')
  // 不是阅读器路由（已经在往别的页走了）⇒ 一个字都别动：现场要留给 `onBeforeUnmount`
  // 收尾（结阅读时长、把待写的进度补上），而它判模式读的就是 `onlineMode` ——
  // 这里若跟着路由把它改成 false，收尾那一刻就会把线上章号写成本地进度。
  if (!READER_ROUTE_NAMES.includes(name)) return
  onlineMode.value = name === 'online'
  loading.value = true
  error.value = ''
  if (isOnline.value) {
    await loadOnline()
    return
  }
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

  // PDF / 漫画 / 序号单元合集不进章节流：书目已就绪，渲染、进度、**阅读时长**全交给各自的
  // 阅读器组件。（第 63 期起 PDF / 漫画也计时了：各自挂一个 reporter，位置快照是页码而不是
  // 章节号 —— 这里的 `currentIndex` 对它们是空的，接了也没意义。单元合集同理：`chapters` 为
  // 空，「章」这个坐标不存在，跨话进度由 `UnitsReader` 用话号表达）
  if (isPdf.value || isComic.value || isUnits.value) return

  if (!total.value) {
    error.value = '这本书没有可阅读的章节'
    return
  }

  startSession()
  // 第 56 期：起「其他设备是否更新了进度」的轮询（只提示、不自动跳）
  startProgressWatch()

  let start = 0
  let restore: number | undefined
  let restoreOffset: number | undefined
  try {
    // 恢复位置按**本机正在读的那个文件**问，本文件还没有读点时保守回落到书级 ——
    // 为什么、以及「只认不是别的文件的回落」，见 `lib/readingProgress.ts`（三个阅读器
    // 共用那一份，别在这里另写一套）
    const p = await progressForFile(bookId.value, fileRel.value)
    // 恢复的这一刻本机就认账了：把它记成「本机已知的最新写入」，之后只有更新的才算别人的
    ownWriteAt.value = typeof p.updated_at === 'number' ? p.updated_at : 0
    const t = flat.value.findIndex((f) => f.index === p.locator)
    if (t >= 0) {
      start = t
      restore = Math.min(1, Math.max(0, (p.percent / 100) * total.value - t))
      // 第 54 期：有 CFI 反解出的精确偏移就用它（loadChapter 内换算滚动位置）
      if (typeof p.offset === 'number' && p.offset >= 0) restoreOffset = p.offset
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
  await loadChapter(start, restore, restoreOffset)
}

/**
 * 换书 / 换模式时**重新取数**。
 *
 * 原实现只在 `onMounted` 里赋值 `book`，而 `App.vue:138` 是裸 `<RouterView />`
 * （**没有 `:key`**）⇒ 同记录内换参数组件**不重新挂载**，`book` 停在上一本，
 * 于是头部书名（`:857` 的 `{{ book.title }}`）**停在上一本**；
 * 正文却因为 `loadChapter` 直接读路由驱动的 `bookId`（`:344`）而是新的 ——
 * 第 36 期记下的那个「正文会更新、书名不更新」的自相矛盾现象，根因就在这里。
 *
 * ⚠️ 刻意**不**给 `RouterView` 加 `:key`：那会连整棵 DOM 一起重建（丢滚动位置、
 * 重建滚动/分页观察器），与本项目「局部更新不重建」的既有做法冲突。这里只重跑取数。
 *
 * ⚠️ 盯的是 `[路由名, 参数]` 而**不只是** `bookId`（第 93 期）：vue-router 对
 * 「换记录但组件相同」是**复用实例**的，`/read/A` → `/online/A` 时 `bookId` 一个字没变，
 * 只盯它就会一直放着上一份（本地）数据源，而 URL 已经是在线读。
 */
watch([() => route.name, () => route.params.id], async () => {
  // 已经在往非阅读器页面走了（离开阅读器）⇒ 现场一个字都别动，留给 `onBeforeUnmount` 收尾。
  // 见 `onlineMode` 那段注释：这里多清一次现场，收尾那一次就会用错模式 / 写错书。
  if (!READER_ROUTE_NAMES.includes(String(route.name || ''))) return
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
  textEncoding.value = null
  // 第 69 期：章块窗口也要清 —— 留着会露着上一本的正文，而 `chunkEls` 里的元素
  // 随后会被卸载成死引用（量几何量出 0，可见章判定就全靠猜了）
  chunks.value = []
  chunkEls.clear()
  await load()
})

onMounted(() => {
  void load()
  // 第 61 期「进度要实时/不丢」：页面切后台或关闭时，把 800ms 去抖里还没发出的那一次立刻补上 ——
  // 否则「滚到底 → 直接关标签页」这类最自然的收尾动作会把最后一段位置白白丢掉。
  // 页面关闭（含 bfcache 前）也要把待写的进度补上：`visibilitychange` 在关标签页时不一定来得及
  window.addEventListener('pagehide', flushPendingProgress)
})

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  void saveProgress()
  stopProgressWatch()
  stopSession()
  chunkEls.clear()
  window.removeEventListener('pagehide', flushPendingProgress)
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <!-- 在线读不可用（第 93 期）：一页**如实的说明** + 回本地阅读的入口。
         为什么单开一页而不是复用下面的 EmptyState：那个的文案是「找不到这本书」——
         而这里书是好的、只是这本书**当前没法**在线读（没绑源 / 下载开关关着 /
         源不支持逐章），原因由服务端 `gate_reason` / `online_support` 逐字给出。
         把「为什么」换成一句凭空写的通用话，等于让用户自己去猜。 -->
    <EmptyState
      v-else-if="isOnline && onlineBlocked"
      icon="alert"
      title="这本书现在没法在线读"
      :desc="onlineBlocked"
    >
      <template #action>
        <div class="flex flex-wrap items-center justify-center gap-2">
          <Button variant="primary" @click="router.push(`/read/${bookId}`)">改读本地</Button>
          <Button variant="ghost" @click="router.push(`/book/${bookId}`)">返回详情</Button>
        </div>
      </template>
    </EmptyState>

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
      <ComicReader
        v-if="isComic || comicPdf"
        :book-id="bookId"
        :title="book.title"
        :series="book.series"
        :source="isComic ? 'archive' : 'pdf'"
        :file-rel="fileRel"
        @pdf-mode="setPdfMode"
      />
      <PdfReader
        v-else-if="isPdf"
        :book-id="bookId"
        :title="book.title"
        :comic-lib="book.library_type === 'comic'"
        :series="book.series"
        :file-rel="fileRel"
        @pdf-mode="setPdfMode"
      />
      <!-- 序号单元合集（第 73 期）：一棵树 = 一本书，逐话连续读。
           话清单随详情下发（`book.units`），首屏不必再请求一次 -->
      <UnitsReader
        v-else-if="isUnits"
        :book-id="bookId"
        :title="book.title"
        :series="book.series"
        :units="book.units ?? []"
      />

      <template v-else>
      <!-- 来源标注横幅（第 93 期 · **验收项，不是装饰**）。
           常驻、不折叠、不随滚动消失 —— 读了半天不知道屏幕上这段字来自哪儿，
           是这个功能最容易让人误判的地方（「这是本地那本书的新章节吗？」）。
           目录抽屉顶部有**同一条**（两处都要有，别只留一处）。
           断网 / 命中缓存时 `onlineOriginText` 会改口，见那段注释。 -->
      <div
        v-if="isOnline"
        data-testid="online-banner"
        class="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-border bg-card px-2.5 py-1.5 text-[11px] leading-snug text-muted-foreground"
      >
        <Icon name="globe" class="h-3 w-3 shrink-0" />
        <span class="min-w-0 flex-1">{{ onlineOriginText }}</span>
        <span class="shrink-0">本机已缓存 {{ onlineCache.cached }} / {{ onlineCache.total }} 章</span>
        <!-- `rel="noopener"`：新开的源站页面不该拿到本页的 `window.opener`
             （源站是第三方，能拿到就等于把本站当成它的跳板）。 -->
        <a
          v-if="onlineInfo.url"
          :href="onlineInfo.url"
          target="_blank"
          rel="noopener"
          class="shrink-0 underline decoration-dotted underline-offset-2 hover:text-foreground"
        >打开源站页面</a>
      </div>

      <!-- 进度：源站目录与本地对不上时如实说一句（不写本地进度，见 `saveProgress`）。
           不静默 —— 用户会以为「进度怎么不涨了」是坏了。 -->
      <div
        v-if="isOnline && onlineLocalIndex === null"
        class="mb-2 flex gap-1.5 rounded-md border border-border p-2 text-[10.5px] leading-snug text-muted-foreground"
      >
        <Icon name="alert" class="mt-0.5 h-3 w-3 shrink-0" />
        <span>
          源站目录与本地的章节对不上（这一章前后 5 章里不足 3 章同名）：
          本次不记本地进度，在线位置照记 —— 换个客户端打开这本书，仍从这一处续读。
        </span>
      </div>

      <!-- 工具栏。
           ⚠️ 这里的 `relative` 是「阅读设置」面板的**定位父节点**（第 108 期从按钮外层挪上来的）：
           面板是 `absolute right-0 w-72`（288px 固定宽），若定位父节点是那**一颗按钮**
           （宽 38px，且它右侧还有「切换模式 / 书签 / 笔记」几颗按钮 ≈138px），面板右边缘就落在
           视口右侧约 150px 处 ⇒ 288px 的面板向左跑出视口：320px 视口实测面板 x=-118
           （左半边被 `overflow-hidden` 裁掉，用户看不到、也滚不回来）。
           挂到整行上才是「右边缘＝内容区右边缘」，再配面板自己的 `max-w-full` 兜极窄屏。
           别把 `relative` 挪回那颗按钮的外层。 -->
      <div class="relative flex items-center gap-2 border-b border-border pb-2">
        <Button size="sm" variant="ghost" title="返回详情" @click="router.push(`/book/${bookId}`)">
          <Icon name="arrowLeft" class="h-4 w-4" />
        </Button>
        <Button ref="tocBtn" size="sm" variant="ghost" title="目录" @click="showToc = !showToc">
          <Icon name="book" class="h-4 w-4" />
        </Button>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[12px] text-muted-foreground">{{ book.title }}</div>
          <div class="truncate text-[13px] font-medium text-foreground">{{ chapterTitle }}</div>
        </div>
        <!-- ⚠️ 这个 div **不能**加 `relative`：设置面板的定位父节点是上面整行（见那段注释）。
             加回这里 = 把面板重新钉到只有 38px 宽的按钮上 ⇒ 窄屏下它又会跑出视口左边。 -->
        <div>
          <Button ref="settingsBtn" size="sm" variant="ghost" title="阅读设置" @click="showSettings = !showSettings">
            <Icon name="settings" class="h-4 w-4" />
          </Button>

          <div
            v-if="showSettings"
            ref="settingsPanel"
            class="absolute right-0 z-30 mt-1 max-h-[75vh] w-72 max-w-full overflow-y-auto rounded-lg border border-border bg-card p-3 shadow-lg"
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
              <!-- 第 61 期：滚动模式的自动续章开关（翻页模式的末页判定不归它管）。
                   第 69 期改「跨章连续流」后语义变成「要不要自动往后接」，文案随之改写；
                   固定版式仍走旧的「预取 + 替换」路径，故那里保留原文案（不能写成连续读）。 -->
              <label
                v-if="!isPdf && !isComic"
                class="mt-2 flex cursor-pointer items-start gap-2 text-[11px] leading-snug text-muted-foreground"
              >
                <Switch v-model="prefs.autoNextChapter" class="mt-0.5" />
                <span v-if="flowMode">
                  滚动模式<strong class="text-foreground/80">连续读（跨章无缝）</strong>
                  （相邻章接在一起，读到底自然进下一章、向上滚可回上一章；
                  关掉则读到底停下并显示「下一章」按钮）
                </span>
                <span v-else>
                  滚动读到底时<strong class="text-foreground/80">自动接上下一章</strong>
                  （下一章已预先取好，切换不留加载空档；只作用于滚动模式）
                </span>
              </label>
              <p v-if="paged" class="mt-1 text-[10.5px] leading-snug text-muted-foreground">
                点正文左右两侧、滚动鼠标滚轮或按 ← → 翻页，翻到底自动跳下一章。
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

              <!-- 上传的字体（后端 /api/fonts）：按族分组，族名即所见即所得的按钮；选族后加粗/斜体命中真实变体 -->
              <div v-if="fontFamilies.length" class="mt-1.5 flex flex-col gap-1">
                <button
                  v-for="fam in fontFamilies"
                  :key="fam.value"
                  type="button"
                  class="flex cursor-pointer items-center justify-between gap-2 rounded-md border px-2 py-1 text-[12px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                  :class="prefs.font === fam.value ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
                  :title="fam.variants.map((v) => v.style).filter(Boolean).join(' / ')"
                  :disabled="fixedLayout"
                  @click="prefs.font = fam.value"
                >
                  <span class="truncate" :style="{ fontFamily: `'NF-${fam.variants[0].family_key || fam.variants[0].id}', serif` }">{{ fam.name }}</span>
                  <span v-if="fam.variants.length > 1" class="shrink-0 text-[10.5px] text-muted-foreground">{{ fam.variants.length }} 变体</span>
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
                <Switch v-model="prefs.justify" :disabled="fixedLayout" />
              </label>
              <label class="flex cursor-pointer items-center justify-between text-[12px] text-muted-foreground">
                <span>断词（西文长词换行）</span>
                <Switch v-model="prefs.hyphens" :disabled="fixedLayout" />
              </label>
              <!-- 第 76 期：书内排版开关。固定版式**强制开启**（整页版式全靠书内 CSS 的
                   绝对定位摆出来，关掉等于拆书）⇒ 那里禁用并写明理由。 -->
              <label
                class="flex cursor-pointer items-center justify-between gap-2 text-[12px] text-muted-foreground"
                :title="fixedLayout
                  ? '固定版式的整页版式由书内 CSS 决定，必须开启'
                  : '开启后使用书自身的字体 / 缩进 / 图文混排；关掉则回到应用自己的排版口径'"
              >
                <span>使用书内排版<template v-if="fixedLayout">（固定版式必开）</template></span>
                <Switch v-model="prefs.useBookLayout" :disabled="fixedLayout" />
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

        <!-- 书签 / 笔记在**在线模式下一律隐藏**（不是灰掉）：
             它们的锚是「本地这一章的文本」—— 在线正文与本地正文不是同一份文本，
             存下来的锚指向哪里谁也不确定。留着按钮＝给一个存不下东西的假交互。 -->
        <Button
          v-if="!isOnline"
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

        <Button v-if="!isOnline" ref="notesBtn" size="sm" variant="ghost" title="笔记" @click="showNotes = !showNotes">
          <Icon name="note" class="h-4 w-4" />
        </Button>
      </div>

      <!-- 进度条 -->
      <div class="h-0.5 w-full bg-muted">
        <div class="h-full bg-primary transition-[width] duration-300" :style="{ width: `${overallPercent}%` }" />
      </div>

      <!-- TXT 解码提示（第 89 期）：只在**确有字节解不出**时出现，低调但明确 ——
           编码是猜的、且坏字节被 U+FFFD 顶替，这两件事实用户有权知道。 -->
      <div
        v-if="decodeHint"
        class="mb-2 flex items-center gap-2 rounded-md border border-border bg-muted/60 px-3 py-1.5 text-[11.5px] text-muted-foreground"
      >
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        <span class="min-w-0 flex-1 truncate">{{ decodeHint }}</span>
      </div>

      <!-- 其他设备更新过进度：**只提示、绝不静默挪位置**（第 56 期）。
           点「跳过去」才采纳；「忽略」保持本机位置不动。 -->
      <div
        v-if="remoteNote"
        class="mb-2 flex items-center gap-2 rounded-md border border-border bg-muted/60 px-3 py-1.5 text-[11.5px]"
      >
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0 text-primary" />
        <span class="min-w-0 flex-1 truncate">其他设备更新了进度：{{ remoteLabel }}</span>
        <Button size="sm" variant="primary" @click="applyRemoteProgress">跳过去</Button>
        <button
          type="button"
          class="cursor-pointer text-muted-foreground transition-colors hover:text-foreground"
          @click="remoteNote = null"
        >
          忽略
        </button>
      </div>

      <div class="relative flex min-h-0 flex-1">
        <!-- 目录 -->
        <aside
          v-if="showToc"
          class="w-60 shrink-0 overflow-y-auto border-r border-border pr-2 py-2"
        >
          <!-- 目录抽屉顶部的**同一条**来源标注（第 93 期验收项）：
               正文那里的横幅会被滚动带走，而这里是「从目录直接跳进来」的人
               第一眼看到的地方 —— 两处都要有，别只留一处。 -->
          <div
            v-if="isOnline"
            data-testid="online-banner-toc"
            class="mb-2 rounded-md border border-border bg-card px-2 py-1.5 text-[10.5px] leading-snug text-muted-foreground"
          >
            <div>{{ onlineOriginText }}</div>
            <div class="mt-0.5">本机已缓存 {{ onlineCache.cached }} / {{ onlineCache.total }} 章</div>
          </div>

          <div v-for="g in tocView" :key="g.key" class="mb-2">
            <!-- 只有**有名卷**出段头（无名段只在缩进上区别于卷内章节 —— 整本平铺的书
                 外观与改造前一致）；点段头折叠。第 85 期 -->
            <button
              v-if="g.headered"
              type="button"
              class="flex w-full cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-left transition-colors hover:bg-muted"
              :aria-expanded="!collapsedToc[g.key]"
              @click="toggleTocGroup(g.key)"
            >
              <Icon
                name="chev"
                class="h-3 w-3 shrink-0 text-muted-foreground transition-transform"
                :class="collapsedToc[g.key] ? '-rotate-90' : ''"
              />
              <span class="truncate text-[11px] font-semibold text-muted-foreground">{{ g.label }}</span>
            </button>
            <template v-if="!g.headered || !collapsedToc[g.key]">
              <button
                v-for="c in g.items"
                :key="c.pos"
                type="button"
                class="block w-full cursor-pointer truncate rounded-md px-2 py-1 text-left text-[12.5px] transition-colors"
                :class="[
                  c.pos === pos ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground',
                  g.headered ? 'pl-5' : '',
                ]"
                @click="gotoPos(c.pos)"
              >
                {{ c.title }}
              </button>
            </template>
          </div>
          <div v-if="!tocView.length" class="px-2 py-3 text-[11.5px] text-muted-foreground">
            这本书没有可用目录
          </div>
        </aside>

        <!-- 章节加载中（第 61 期）：连点目录/翻到边界时给出反馈，避免「点了没反应」的错觉 -->
        <div
          v-if="chapterLoading"
          class="pointer-events-none absolute top-3 right-4 z-10 rounded-full bg-muted/90 px-2.5 py-1 text-[11px] text-muted-foreground"
        >
          加载章节…
        </div>

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
          <template v-if="paged">
            <div :style="pageShiftStyle">
              <!-- 左右内边距由偏好驱动（见 contentStyle）；固定版式另有 nf-fixed 中和重排样式 -->
              <article
                ref="contentRef"
                class="reader-content py-8"
                :class="[fixedLayout ? 'nf-fixed' : '', bookLayoutOn ? 'nf-bookcss' : '']"
                :style="contentStyle"
                v-html="html"
              />
            </div>
          </template>

          <!-- 滚动模式：跨章连续流（第 69 期）。相邻章首尾相接挂在同一个滚动容器里 ——
               滚到底就是下一章的正文，不再「换一章 + 滚回顶部」；向上滚也能接着读上一章。
               章节位置随窗口滑动而变，脚本一律用 `chunkEls` 取元素（`data-pos` 只为人读）。 -->
          <template v-else-if="flowMode">
            <section
              v-for="c in chunks"
              :key="c.pos"
              :ref="(el) => setChunkEl(c.pos, el)"
              class="nf-chunk mt-10 border-t border-border/60 pt-6 first:mt-0 first:border-t-0 first:pt-0"
              :data-pos="c.pos"
            >
              <!-- 章标题：正文自带的（多数书的 body 里就有 `<h1>`）不再叠一个，只留分隔留白 -->
              <h2
                v-if="!bodyHasHeading(c.html)"
                class="mx-auto mb-5 text-center text-[13px] font-medium tracking-wide text-muted-foreground"
                :style="widthStyle"
              >
                {{ c.title }}
              </h2>
              <article
                class="reader-content py-8 mx-auto"
                :class="bookLayoutOn ? 'nf-bookcss' : ''"
                :style="contentStyle"
                v-html="c.html"
              />
            </section>
          </template>

          <!-- 滚动模式但**固定版式**：页尺寸由书本身决定、与 nf-fixed 的中和样式耦合，
               纵向拼接风险高 ⇒ 保守沿用单章路径（第 69 期的取舍，记在 roadmap） -->
          <template v-else>
            <article
              ref="contentRef"
              class="reader-content py-8 mx-auto nf-fixed"
              :class="bookLayoutOn ? 'nf-bookcss' : ''"
              :style="contentStyle"
              v-html="html"
            />
          </template>

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
          v-if="showNotes && !isOnline"
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
/* 第 76 期：书内排版生效时正文挂 `.nf-bookcss`，下面这套「应用重排」整组**让位** ——
   书自己的字体 / 缩进 / 图文混排说了算。
   ⚠️ 为什么要显式让位、而不是让特异性自然分胜负：scoped 样式编译后会带上 `[data-v-x]`
   属性选择器，`.reader-content[data-v-x] p` 永远赢过书里那条裸 `p{…}`
   —— 不这么做，书内排版一项都生效不了。
   ⚠️ 图片的「不许溢出」与「分栏不许劈开」是**安全网**，任何情况下都保留（见下）。 */
.reader-content :deep(img),
.reader-content :deep(svg) {
  max-width: 100%;
  /* 分栏时不要把图劈成两半 */
  break-inside: avoid;
}
.reader-content:not(.nf-bookcss) :deep(img),
.reader-content:not(.nf-bookcss) :deep(svg) {
  display: block;
  height: auto;
  margin: 1em auto;
}
/* 段落间距与首行缩进来自偏好（contentStyle 注入 CSS 变量），不再写死在样式里 */
.reader-content:not(.nf-bookcss) :deep(p) {
  margin: 0 0 var(--nf-para-gap, 1em);
  text-indent: var(--nf-indent, 2em);
}
.reader-content:not(.nf-bookcss) :deep(h1),
.reader-content:not(.nf-bookcss) :deep(h2),
.reader-content:not(.nf-bookcss) :deep(h3) {
  margin: 1.2em 0 0.6em;
  font-weight: 700;
  line-height: 1.4;
  text-indent: 0;
  /* 分栏模式下标题不要孤立在栏尾 */
  break-after: avoid;
}
/* 链接配色**刻意不随书内排版让位**：阅读主题（含 9 档深色）才是底色的权威 ——
   书里写死的深色链接色在深色主题上会直接看不见。 */
.reader-content :deep(a) {
  color: var(--primary);
  text-decoration: underline;
}
.reader-content:not(.nf-bookcss) :deep(blockquote) {
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
   页宽同理由书本身决定（contentStyle 在该分支不设 maxWidth / 分栏）。
   第 76 期：书内排版生效（`.nf-bookcss`）时上面那套本来就没应用，不必再中和。 */
.reader-content.nf-fixed:not(.nf-bookcss) :deep(p),
.reader-content.nf-fixed:not(.nf-bookcss) :deep(img),
.reader-content.nf-fixed:not(.nf-bookcss) :deep(svg) {
  margin: 0;
  text-indent: 0;
}
.reader-content.nf-fixed:not(.nf-bookcss) :deep(img),
.reader-content.nf-fixed:not(.nf-bookcss) :deep(svg) {
  margin-left: auto;
  margin-right: auto;
}
</style>
