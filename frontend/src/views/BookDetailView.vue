<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AnnotationsTab from '@/components/book/detail/AnnotationsTab.vue'
import ChaptersTab from '@/components/book/detail/ChaptersTab.vue'
import DetailHero from '@/components/book/detail/DetailHero.vue'
import FilesTab from '@/components/book/detail/FilesTab.vue'
import OverviewTab from '@/components/book/detail/OverviewTab.vue'
import ReadingLogTab from '@/components/book/detail/ReadingLogTab.vue'
import MetadataEditor from '@/components/book/MetadataEditor.vue'
import ReadingRecord from '@/components/book/ReadingRecord.vue'
import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import TabBar from '@/components/ui/TabBar.vue'
import { canJumpTo } from '@/lib/annotations'
import { useCollectionsStore } from '@/stores/collections'
import { useCoverPrefsStore } from '@/stores/coverPrefs'
import { useLibraryStore } from '@/stores/library'
import { api, type Annotation, type BookDetail, type ProgressState, type SimilarBook } from '@/lib/api'
import { extractCoverTint, type CoverTint } from '@/lib/coverTint'

/**
 * 单书详情：面包屑 + hero + **七个**标签（概览 / 目录 / 文件 / 批注 / 编辑元数据 /
 * 阅读日志 / 我的记录）。标签清单以文件末尾的 `TABS` 常量为准 —— 这行注释是散文，
 * 加了标签忘了改它不会有任何提示（第 63 期 3/6 加了「阅读日志」才发现上一版写的是
 * 「六个」，且已经漏了整整一期）。
 *
 * 第 63 期把各标签的渲染拆到了 `components/book/detail/`，本文件只留**取数与编排**：
 * `detail` / `progress` / `annotations` / `similar` 四份数据在这里加载一次，
 * 子组件全部收 props（不各自再请求一遍 —— 那样改完元数据 hero 与概览会各自过期）。
 * 例外是 `MetadataEditor` / `ReadingRecord` / `ReadingLogTab`：它们自取数据是既有契约，
 * 靠 `saved` / `changed` 事件通知这里刷新。
 *
 * 数据全部来自后端 /api/books/{id}（真实 EPUB 元数据 + 章节树 + 成品文件）；
 * 阅读进度、批注、我的记录（状态 / 日期 / 评分 / 书评）都是真数据，落 SQLite。
 */
const route = useRoute()
const router = useRouter()
const library = useLibraryStore()
const coverPrefs = useCoverPrefsStore()
/** 收藏夹菜单在 `DetailHero` 里，但 store 要在这里初始化（进页面就拉一次列表） */
const collections = useCollectionsStore()

const bookId = computed(() => String(route.params.id))
const detail = ref<BookDetail | null>(null)
const loading = ref(true)
const book = computed(() => detail.value ?? library.findBook(bookId.value))

/**
 * 封面取色（第 20 期；第 51 期加档位）：从封面图取色相，喂给照搬来的 `.book-detail-cover-tint`。
 * 取不到（无封面 / 加载失败 / 画布不可用）就**不设变量** —— CSS 那条 hsl() 整条失效，
 * 于是不染色，不会留下黑块。**纯装饰，绝不阻塞或报错**。
 *
 * 档位（对齐上游 `Book details cover tint`）：`off` 连取色都跳过；`one` 只写第一套变量 ——
 * CSS 里本就写了 `--cover-tint-hue-2: var(--cover-tint-hue)`，第二角会自动收成同一色；
 * `two`（默认）写两套，与加档位之前逐像素一致。
 */
const tint = ref<CoverTint | null>(null)
const tintOn = computed(() => coverPrefs.prefs.tint !== 'off')
const tintStyle = computed(() => {
  if (!tint.value || !tintOn.value) return undefined
  const first = {
    '--cover-tint-hue': `${tint.value.hue}`,
    '--cover-tint-saturation': `${tint.value.saturation}%`,
  }
  if (coverPrefs.prefs.tint === 'one') return first
  return {
    ...first,
    '--cover-tint-hue-2': `${tint.value.hue2}`,
    '--cover-tint-saturation-2': `${tint.value.saturation2}%`,
  }
})
watch(
  // 档位也进依赖：从「关闭」切回单色 / 双色时要重新取色，否则会一直不染色
  () => [book.value?.id, book.value?.has_cover, coverPrefs.prefs.tint] as const,
  async ([bid, hasCover, tintMode]) => {
    tint.value = null
    if (!bid || !hasCover || tintMode === 'off') return
    const result = await extractCoverTint(api.coverUrl(String(bid)))
    // 竞态：取色是异步的，回来时可能已经切到别的书了
    if (String(book.value?.id ?? '') === String(bid)) tint.value = result
  },
  { immediate: true },
)

/**
 * 面包屑第二段 = **这本书的归属书库名**。
 *
 * ⚠️ 第 63 期修：此前读的是 `library.shelfTitle`（全局导航状态，由上一个访问的书架页写入）。
 * 深链进来（新标签页打开 / 刷新 / 分享链接）时它还是**上一次导航的标题**，甚至是默认值
 * 「全部书库」—— 面包屑于是显示一本别的书架的名字。归属库名永远对得上这本书，与从哪进来无关。
 *
 * 查不到库实体（库已被删 / 书已不在任何库）就**不渲染这一段** —— 不回落到 `library_id`：
 * 那是个内部 id（形如 `lib`），摆在面包屑里对用户没有意义，还不如少一段。
 */
const libraryName = computed(() => {
  const id = book.value?.library_id
  if (!id) return ''
  return library.libraryEntities.find((l) => l.id === id)?.name || ''
})

const TABS = [
  { id: 'overview', label: '概览' },
  { id: 'chapters', label: '目录' },
  { id: 'files', label: '文件' },
  { id: 'annotations', label: '批注' },
  { id: 'metadata', label: '编辑元数据' },
  { id: 'reading', label: '阅读日志' },
  { id: 'record', label: '我的记录' },
] as const

type TabId = (typeof TABS)[number]['id']

/**
 * 当前标签。初值可以由 `?tab=` 指定（第 64 期）。
 *
 * 起因：书卡 ⋮ 菜单的「编辑元数据」要直接落到第 5 个标签。没有深链就只能再挂第二个
 * `MetadataEditor` 实例 —— 同一个编辑器开两个入口更糟。
 *
 * ⚠️ `?tab=` 只当**初值**，之后标签的切换**不写回 URL**：写回意味着每点一次标签就压一条
 * 历史记录（返回键要按七次才出得去）；也意味着 `/book/x?tab=files` 与 `/book/x` 变成
 * 两个「不同」的地址，分享出去的链接会带着别人的浏览位置。
 *
 * 值不认识就落回概览 —— 不抛错、不留白屏：深链是别人手打的（或旧版本留下的），
 * 打错一个字母不该把详情页变成空白。
 */
function initialTab(): TabId {
  const q = String(route.query.tab || '')
  return (TABS.find((t) => t.id === q)?.id ?? 'overview') as TabId
}

const tab = ref<TabId>(initialTab())

// 阅读进度与批注（来自 SQLite，多端共享）
const progress = ref<ProgressState | null>(null)
const annotations = ref<Annotation[]>([])

const chapterCount = computed(() =>
  (detail.value?.chapters ?? []).reduce((s, v) => s + v.chapters.length, 0),
)

/** 标签定义（目录带条数；0 章是个有意义的数 —— TabBar 只对 `undefined` 不显示数字） */
const tabs = computed(() =>
  TABS.map((t) => (t.id === 'chapters' ? { ...t, count: chapterCount.value } : { ...t })),
)

const files = computed(() => detail.value?.files ?? [])

// 相似书：五路加权打分派生（第 35 期）。至少要有一条实质重合（同作者 / 题材 / 同系列）
// 才会返回，所以无信号时后端给空数组 —— 整块不显示，不摆一个空壳。
// 条数：先要 6 条（详情页的观感），点「查看全部」再按上限 25 拉一次；不满 6 条说明没有更多。
const SIMILAR_PREVIEW = 6
/** 与后端 `core/recommend.MAX_LIMIT` 对齐（改一处要改两处：这是接口上限，不是随便取的数） */
const SIMILAR_ALL = 25
const similar = ref<SimilarBook[]>([])
const similarExpanded = ref(false)
function loadSimilar(id: string): void {
  similar.value = []
  similarExpanded.value = false
  api.similarBooks(id, SIMILAR_PREVIEW).then((r) => (similar.value = r.items)).catch(() => {})
}
/** 展开到上限。拉失败就保持现状 —— 不把 preview 的 6 条清掉假装展开过 */
async function expandSimilar(): Promise<void> {
  try {
    similar.value = (await api.similarBooks(bookId.value, SIMILAR_ALL)).items
    similarExpanded.value = true
  } catch {
    /* 保持现状 */
  }
}
loadSimilar(bookId.value)
watch(bookId, loadSimilar)

/**
 * 阅读器支持的格式：EPUB / TXT 需抽到章节（TXT 走派生 EPUB 或原生分章，见后端 txtcache）；
 * PDF / 漫画（CBZ·CBR）由各自阅读器就地处理。
 */
const canRead = computed(() => {
  if (!detail.value) return false
  const f = (detail.value.format || '').toUpperCase()
  if (f === 'EPUB' || f === 'TXT') return chapterCount.value > 0
  return f === 'PDF' || f === 'CBZ' || f === 'CBR'
})

/** 有声书走播放器而非阅读器 */
const canListen = computed(() => (detail.value?.format || '').toUpperCase() === 'AUDIO')

/** 能否「打开」（阅读或收听） */
const canStart = computed(() => canRead.value || canListen.value)

function startReading(): void {
  if (canListen.value) {
    router.push(`/listen/${bookId.value}`)
    return
  }
  if (!canRead.value) return
  router.push(`/read/${bookId.value}`)
}

/**
 * 从批注列表「前往」：章节序号已知就直接落到那一章，否则回落到「打开这本书」。
 *
 * **不猜章节** —— 设备回传的批注序号是 -1（未知，见 `lib/annotations`），
 * 拿它拼 `?chapter=-1` 会落到章首，用户以为去到的是那条批注的位置。
 */
function goToAnnotation(a: Annotation): void {
  if (canListen.value || !canRead.value || !canJumpTo(a)) {
    startReading()
    return
  }
  router.push(`/read/${bookId.value}?chapter=${a.chapter}`)
}

/**
 * 下载一个成品文件（第 64 期：带上库维度，`files[].name` 是**库内相对路径**）。
 *
 * ⚠️ 路径与文件名都取**最后一段**：`files[].name` 在 Komga 布局下是 `三体/三体 #1.epub`，
 * 而 `download` 属性里带 `/` 会被浏览器当成路径处理（文件名变成一串怪东西）。
 * 服务端侧同一个名字是合法入参（`fileops.safe_path` 专门支持「系列/文件」）。
 */
function download(name: string): void {
  const a = document.createElement('a')
  a.href = api.downloadUrl(name, detail.value?.library_id)
  a.download = name.split('/').pop() || name
  a.click()
}

/** hero 的下载按钮：没有文件就点不动（按钮本身也据此禁用） */
function downloadFirst(): void {
  const first = files.value[0]
  if (first) download(first.name)
}

/** 元数据保存后强制重取详情与书单缓存，否则概览仍显示旧的标题 / 作者 / 简介 */
async function onMetaSaved(): Promise<void> {
  detail.value = await library.getBookDetail(bookId.value, true)
  await library.loadBooks(true)
}

/** 「加载失败」态的重试：强制重取详情（失败与「找不到这本书」在模板里分开渲染） */
async function retryDetail(): Promise<void> {
  loading.value = true
  detail.value = await library.getBookDetail(bookId.value, true)
  loading.value = false
}

onMounted(async () => {
  // 库实体是面包屑与版本信息「书库」行的数据源；深链进来时它还没加载过
  // （只有去过书库页 / 设置页才会加载），所以这里补一次（幂等，已加载就直接返回）
  library.loadLibraries()
  await library.loadBooks()
  collections.load()
  detail.value = await library.getBookDetail(bookId.value)
  loading.value = false
  if (detail.value) {
    try {
      progress.value = await api.getProgress(bookId.value)
    } catch {
      /* 未登录或后端不可用时静默降级 */
    }
    try {
      annotations.value = (await api.listAnnotations(bookId.value)).items
    } catch {
      /* ignore */
    }
  }
})
</script>

<template>
  <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

  <div v-else-if="book">
    <!-- 面包屑 -->
    <nav class="mb-4 flex items-center gap-1.5 text-[12px] text-muted-foreground">
      <button
        type="button"
        class="cursor-pointer transition-colors hover:text-primary"
        @click="router.push('/shelf')"
      >
        书库
      </button>
      <template v-if="libraryName">
        <span class="opacity-50">/</span>
        <span class="truncate">{{ libraryName }}</span>
      </template>
      <span class="opacity-50">/</span>
      <span class="truncate text-foreground">{{ book.title }}</span>
    </nav>

    <!--
      详情拉失败、但书架缓存里还有这张书卡时：**必须报错**。
      此时 `book` 命中列表兜底，页面会照常渲染成一本「没有简介 / 没有章节 / 没有文件」的
      空壳 —— 看起来就像「这本书本来就是空的」。这与「不造假数据」冲突，所以显式提示。
      整页替换成错误态是不对的：列表缓存里的标题作者是真的，扔掉它们反而更差。
    -->
    <div
      v-if="library.detailError && !detail"
      class="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3.5 py-2.5 text-[12.5px] text-destructive"
    >
      <span class="min-w-0 flex-1">详情加载失败：{{ library.detailError }}（下方是书架缓存里的基本信息）</span>
      <Button size="sm" variant="ghost" @click="retryDetail">重试</Button>
    </div>

    <DetailHero
      :book="book"
      :progress="progress"
      :can-start="canStart"
      :can-listen="canListen"
      :has-files="files.length > 0"
      :tint-style="tintStyle"
      :tinted="Boolean(tint && tintOn)"
      @start="startReading"
      @download="downloadFirst"
    />

    <TabBar v-model="tab" :tabs="tabs" />

    <!-- 标签用 v-show 而非 v-if：切回来不重建，目录的搜索词与折叠状态得以保留 -->
    <OverviewTab
      v-show="tab === 'overview'"
      :book="book"
      :files="files"
      :similar="similar"
      :similar-expanded="similarExpanded"
      :similar-max="SIMILAR_ALL"
      @download="download"
      @expand-similar="expandSimilar"
      @open-book="(id) => router.push(`/book/${id}`)"
    />

    <ChaptersTab v-show="tab === 'chapters'" :chapters="detail?.chapters ?? []" />

    <!--
      文件标签：`active` 是**必须传的** —— 它要单独问一次 `/local-paths`（那个响应
      取决于请求者，拿不到就整块不显示路径），没必要在每次进详情页时都问。
      `main-name` / `main-format` 告诉它这一页说的是哪一份（同 stem 的成品各有各的页面）。
    -->
    <FilesTab
      v-show="tab === 'files'"
      :files="files"
      :main-name="book.name"
      :main-format="book.format"
      :book-id="bookId"
      :active="tab === 'files'"
      @download="download"
    />

    <AnnotationsTab v-show="tab === 'annotations'" :annotations="annotations" @go="goToAnnotation" />

    <div v-show="tab === 'metadata'">
      <MetadataEditor :book-id="bookId" @saved="onMetaSaved" />
    </div>

    <!--
      阅读日志（这本书的阅读行为：多久 / 几次 / 读到哪 / 读过几遍）。
      `active` 是**必须传的**：这一页的数据与那张 ECharts 图都等到第一次点开才加载
      （见 `ReadingLogTab` 的文件头）。标签用 `v-show` 而不是 `v-if`，所以「挂载了」
      不等于「用户打开了」—— 光靠 `v-if` 是拦不住那个 800 kB 量级的 ECharts chunk 的。
      `pages` / `pages-source` 用来算阅读速度，判据在 `lib/readingPace.ts`。
    -->
    <ReadingLogTab
      v-show="tab === 'reading'"
      :book-id="bookId"
      :active="tab === 'reading'"
      :pages="detail?.pages"
      :pages-source="detail?.pages_source"
      @changed="onMetaSaved"
    />

    <!-- 我的记录（状态 / 日期 / 评分 / 书评） -->
    <div v-show="tab === 'record'">
      <ReadingRecord :book-id="bookId" @changed="onMetaSaved" />
    </div>
  </div>

  <!-- 区分「拉取失败」与「真的没有这本书」：前者给重试，后者才说「找不到」（第 49 期） -->
  <EmptyState
    v-else
    icon="alert"
    :title="library.detailError ? '这本书加载失败' : '找不到这本书'"
    :desc="library.detailError || '它可能已被移除，或链接有误。'"
  >
    <template #action>
      <Button v-if="library.detailError" variant="primary" @click="retryDetail">重试</Button>
      <Button v-else variant="primary" @click="router.push('/shelf')">回到书库</Button>
    </template>
  </EmptyState>
</template>
