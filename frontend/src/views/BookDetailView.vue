<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import MetadataEditor from '@/components/book/MetadataEditor.vue'
import ReadingRecord from '@/components/book/ReadingRecord.vue'
import { useLibraryStore } from '@/stores/library'
import { useCollectionsStore } from '@/stores/collections'
import { useCoverPrefsStore } from '@/stores/coverPrefs'
import { highlightHex as highlightColor, highlightStyleLabel } from '@/data/annotationColors'
import { api, type Annotation, type BookDetail, type ProgressState, type SimilarBook } from '@/lib/api'
import { extractCoverTint, type CoverTint } from '@/lib/coverTint'

/**
 * 单书详情：面包屑 + hero + 四标签（概览 / 目录 / 文件 / 批注）。
 *
 * 数据全部来自后端 /api/books/{id}（真实 EPUB 元数据 + 章节树 + 同 stem 成品文件）；
 * 阅读进度（:260 `api.getProgress`）、批注（:265 `api.listAnnotations`）、我的记录
 * （状态 / 日期 / 评分 / 书评）都是真数据，落 SQLite。
 */
const route = useRoute()
const router = useRouter()
const library = useLibraryStore()
const coverPrefs = useCoverPrefsStore()

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

/** 日期格式化（秒 → 本地 YYYY/M/D）；供版本信息区「入库」行使用（与文件行 fmtDate 区分）。 */
function fmtDateSlash(sec?: number): string {
  if (!sec) return '未知'
  const d = new Date(sec * 1000)
  if (Number.isNaN(d.getTime())) return '未知'
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

/** 书的归属书库名（library_id → 库实体名）；「全部书库」视图下 book.library_id 仍可能是具体库 */
const libraryName = computed(() => {
  const id = book.value?.library_id
  if (!id) return ''
  return library.libraryEntities.find((l) => l.id === id)?.name || id
})

/**
 * 版本信息区的行（第 30 期补全）：
 * - 书库（归属库，来自 book.library_id）
 * - 入库（与导出 CSV「入库日期」同源：都是文件 mtime）
 * - 页数（非 EPUB 恒 0 → 不展示；带来源标注：估算值 / 归档真实值）
 * 移除原先写死「字数：未知」的假值行（项目约定不做假交互）。
 */
const versionRows = computed<Array<{ k: string; v: string; hint?: string }>>(() => {
  const b = book.value
  if (!b) return []
  const rows: Array<{ k: string; v: string; hint?: string }> = []
  rows.push({ k: '系列', v: b.series || '独立作品' })
  if (libraryName.value) rows.push({ k: '书库', v: libraryName.value })
  if (b.mtime) rows.push({ k: '入库', v: fmtDateSlash(b.mtime) })
  rows.push({ k: '出版年', v: b.year || '未知' })
  rows.push({ k: '出版社', v: b.publisher || '未知' })
  rows.push({ k: '语言', v: b.language || '未知' })
  rows.push({ k: 'ISBN', v: b.isbn || '未知' })
  if (Array.isArray(b.narrators) && b.narrators.length) {
    rows.push({ k: '演播', v: b.narrators.join('、') })
  }
  if (b.pages && b.pages > 0) {
    const src =
      b.pages_source === 'archive'
        ? '归档真实页数'
        : b.pages_source === 'estimate'
          ? 'EPUB 估算页数'
          : ''
    rows.push({ k: '页数', v: String(b.pages), hint: src })
  }
  return rows
})

const TABS = [
  { id: 'overview', label: '概览' },
  { id: 'chapters', label: '目录' },
  { id: 'files', label: '文件' },
  { id: 'annotations', label: '批注' },
  { id: 'metadata', label: '编辑元数据' },
  { id: 'record', label: '我的记录' },
] as const

const tab = ref<(typeof TABS)[number]['id']>('overview')

const descOpen = ref(false)
const chapterQuery = ref('')

// Batch 2：阅读进度与批注（来自 SQLite，多端共享）
const progress = ref<ProgressState | null>(null)
const annotations = ref<Annotation[]>([])

// Batch 3：收藏夹归属（自建收藏夹，持久化于 SQLite）
const collections = useCollectionsStore()
const menuOpen = ref(false)
const inCollections = ref<number[]>([])
const newCollection = ref('')

const chapterCount = computed(() =>
  (detail.value?.chapters ?? []).reduce((s, v) => s + v.chapters.length, 0),
)

/** 章节过滤：输入时只切行显隐，不重建列表 */
const volumes = computed(() => {
  const list = detail.value?.chapters ?? []
  const q = chapterQuery.value.trim().toLowerCase()
  if (!q) return list
  return list
    .map((v) => ({ ...v, chapters: v.chapters.filter((c) => c.title.toLowerCase().includes(q)) }))
    .filter((v) => v.chapters.length > 0)
})

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

const collapsedVolumes = ref<Record<string, boolean>>({})
function toggleVolume(name: string): void {
  collapsedVolumes.value[name] = !collapsedVolumes.value[name]
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

function fmtSize(n: number): string {
  if (!n && n !== 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtDate(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function download(name: string): void {
  const a = document.createElement('a')
  a.href = api.downloadUrl(name)
  a.download = name
  a.click()
}

// 高亮取色统一来自 data/annotationColors.ts（唯一一份）—— 这里此前自己写了一份
// 四色表，扩容时会把新增颜色静默渲染成黄色。


// ---------------- 收藏夹 ----------------

async function loadBookCollections(): Promise<void> {
  try {
    inCollections.value = (await api.bookCollections(bookId.value)).items
  } catch {
    /* ignore */
  }
}

async function toggleCollection(cid: number): Promise<void> {
  const has = inCollections.value.includes(cid)
  try {
    if (has) await api.removeFromCollection(cid, bookId.value)
    else await api.addToCollection(cid, bookId.value)
    inCollections.value = has
      ? inCollections.value.filter((x) => x !== cid)
      : [...inCollections.value, cid]
    await collections.load(true)
  } catch {
    /* ignore */
  }
}

async function createAndAdd(): Promise<void> {
  const name = newCollection.value.trim()
  if (!name) return
  try {
    const cid = await collections.create(name)
    await api.addToCollection(cid, bookId.value)
    inCollections.value = [...inCollections.value, cid]
    newCollection.value = ''
    await collections.load(true)
  } catch {
    /* ignore */
  }
}

onMounted(async () => {
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
    await loadBookCollections()
  }
})
</script>

<template>
  <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

  <div v-else-if="book">
    <!-- 面包屑 -->
    <nav class="mb-4 flex items-center gap-1.5 text-[12px] text-muted-foreground">
      <button type="button" class="cursor-pointer transition-colors hover:text-primary" @click="router.push('/shelf')">
        书库
      </button>
      <span class="opacity-50">/</span>
      <span>{{ library.shelfTitle }}</span>
      <span class="opacity-50">/</span>
      <span class="text-foreground">{{ book.title }}</span>
    </nav>

    <!-- hero：背景取封面主色染色（取不到就不染色，见 tint / coverTint.ts） -->
    <div
      class="mb-6 flex flex-col gap-5 sm:flex-row sm:gap-7"
      :class="tint && tintOn ? 'book-detail-cover-tint' : ''"
      :style="tintStyle"
    >
      <div class="relative w-[140px] shrink-0 sm:w-[176px]">
        <BookCover :book="book" :interactive="false" :show-title="false" />
      </div>

      <div class="min-w-0 flex-1">
        <div class="mb-2 flex flex-wrap items-center gap-1.5">
          <Badge v-if="book.series" tone="accent">{{ book.series }}</Badge>
          <Badge v-for="t in (book.tags || []).slice(0, 3)" :key="t">{{ t }}</Badge>
        </div>

        <h1 class="font-serif text-[26px] leading-tight font-bold tracking-tight text-foreground">
          {{ book.title }}
        </h1>
        <p class="mt-1 text-[13px] text-muted-foreground">
          {{ book.author }} · {{ book.year || '未知' }} 年
        </p>

        <p class="mt-2 text-[12px] text-muted-foreground">
          {{ book.language || '未知' }} · {{ book.publisher || '未知' }}
        </p>

        <div class="mt-4 flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            :disabled="!canStart"
            :title="canStart
              ? (canListen ? '进入播放器' : '进入阅读器')
              : 'EPUB / TXT（含章节）/ PDF / 漫画 / 有声书可在线打开'"
            @click="startReading"
          >
            <Icon name="play" class="h-3.5 w-3.5" />
            {{ progress && progress.percent > 0
              ? (canListen ? '继续播放' : '继续阅读')
              : (canListen ? '开始播放' : '开始阅读') }}
          </Button>
          <Button v-if="files.length" variant="ghost" @click="download(files[0].name)">
            <Icon name="download" class="h-3.5 w-3.5" />下载
          </Button>

          <!-- 加入收藏：勾选加入 / 移除，或就地新建收藏夹 -->
          <div class="relative">
            <Button variant="ghost" @click="menuOpen = !menuOpen">
              <Icon name="star" class="h-3.5 w-3.5" />收藏
              <span v-if="inCollections.length" class="text-[11px] text-muted-foreground tabular-nums">
                {{ inCollections.length }}
              </span>
            </Button>

            <div
              v-if="menuOpen"
              class="absolute left-0 z-20 mt-1 w-60 rounded-lg border border-border bg-card p-2 shadow-lg"
            >
              <p v-if="!collections.items.length" class="px-1.5 py-1 text-[11.5px] text-muted-foreground">
                还没有收藏夹，先在下方新建一个。
              </p>
              <button
                v-for="c in collections.items"
                :key="c.id"
                type="button"
                class="flex w-full cursor-pointer items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-[12.5px] text-foreground transition-colors hover:bg-muted"
                @click="toggleCollection(c.id)"
              >
                <Icon
                  :name="inCollections.includes(c.id) ? 'check' : 'plus'"
                  class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                />
                <span class="min-w-0 flex-1 truncate">{{ c.name }}</span>
                <span class="shrink-0 text-[11px] text-muted-foreground tabular-nums">{{ c.count }}</span>
              </button>

              <div class="mt-1 flex items-center gap-1.5 border-t border-border pt-2">
                <input
                  v-model="newCollection"
                  type="text"
                  placeholder="新建收藏夹…"
                  class="h-7 min-w-0 flex-1 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
                  @keyup.enter="createAndAdd"
                >
                <Button size="sm" :disabled="!newCollection.trim()" @click="createAndAdd">新建</Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 标签栏 -->
    <div class="mb-4 flex items-center gap-1 border-b border-border">
      <button
        v-for="t in TABS"
        :key="t.id"
        type="button"
        :title="t.label"
        class="relative cursor-pointer px-3 py-2 text-[13px] font-medium transition-colors"
        :class="tab === t.id ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'"
        @click="tab = t.id"
      >
        {{ t.label }}
        <span v-if="t.id === 'chapters'" class="ml-1 text-[11px] text-muted-foreground tabular-nums">{{ chapterCount }}</span>
        <span
          v-if="tab === t.id"
          class="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary"
        />
      </button>
    </div>

    <!-- ============ 概览 ============ -->
    <div v-show="tab === 'overview'" class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card class="lg:col-span-2">
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">制版说明</h3>
        <p class="text-[12.5px] leading-relaxed text-muted-foreground" :class="descOpen ? '' : 'line-clamp-4'">
          {{ book.description || '暂无简介。' }}
        </p>
        <button
          v-if="book.description && book.description.length > 80"
          type="button"
          class="mt-1.5 cursor-pointer text-[11.5px] text-primary"
          @click="descOpen = !descOpen"
        >
          {{ descOpen ? '收起' : '展开全文' }}
        </button>

        <h3 class="mt-5 mb-2 text-[13px] font-semibold text-foreground">版本信息</h3>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
          <div v-for="item in versionRows" :key="item.k">
            <dt class="text-[11px] text-muted-foreground">{{ item.k }}</dt>
            <dd class="mt-0.5 truncate text-[12.5px] text-foreground">
              {{ item.v }}<span v-if="item.hint" class="ml-1 text-[10.5px] text-muted-foreground">{{ item.hint }}</span>
            </dd>
          </div>
        </dl>
      </Card>

      <Card>
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">阅读进度</h3>
        <template v-if="progress && progress.percent > 0">
          <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div class="h-full rounded-full bg-primary" :style="{ width: `${progress.percent}%` }" />
          </div>
          <p class="mt-2 text-[12.5px] text-muted-foreground tabular-nums">
            已读 {{ Math.round(progress.percent) }}%
          </p>
          <Button size="sm" class="mt-3" :disabled="!canStart" @click="startReading">
            {{ canListen ? '继续播放' : '继续阅读' }}
          </Button>
        </template>
        <p v-else class="text-[12.5px] leading-relaxed text-muted-foreground">
          尚未开始阅读。点击「开始阅读」进入阅读器，进度与批注会自动多端同步。
        </p>

        <h3 class="mt-5 mb-2 text-[13px] font-semibold text-foreground">成品文件</h3>
        <div v-if="files.length" class="flex flex-col gap-1.5">
          <div
            v-for="f in files"
            :key="f.name"
            class="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5"
          >
            <span class="text-[11px] font-semibold text-foreground">{{ f.format }}</span>
            <span class="text-[11.5px] text-muted-foreground">{{ fmtSize(f.size) }} · {{ fmtDate(f.mtime) }}</span>
            <Button size="sm" class="ml-auto" @click="download(f.name)">下载</Button>
          </div>
        </div>

        <template v-if="similar.length">
          <h3 class="mt-5 mb-2 text-[13px] font-semibold text-foreground">相似书</h3>
          <div class="flex flex-col gap-1.5">
            <button
              v-for="s in similar"
              :key="s.id"
              type="button"
              class="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-left transition-colors hover:bg-muted"
              @click="router.push(`/book/${s.id}`)"
            >
              <span class="min-w-0 flex-1">
                <span class="block truncate text-[12.5px] text-foreground">{{ s.title }}</span>
                <span class="block truncate text-[11px] text-muted-foreground">{{ s.reasons.join(' · ') }}</span>
              </span>
            </button>
            <!-- 满 6 条才可能有更多（不满就是真的只有这些），所以只在满的时候给这个入口 -->
            <button
              v-if="!similarExpanded && similar.length >= SIMILAR_PREVIEW"
              type="button"
              class="mt-0.5 cursor-pointer self-start text-[11.5px] text-primary transition-opacity hover:opacity-80"
              @click="expandSimilar"
            >
              查看全部（最多 {{ SIMILAR_ALL }} 本）
            </button>
          </div>
        </template>
        <EmptyState v-else icon="file" title="暂无成品文件" desc="这本书还没有可下载的文件。" />
      </Card>
    </div>

    <!-- ============ 目录 ============ -->
    <div v-show="tab === 'chapters'">
      <div class="mb-3 flex items-center gap-2.5">
        <div class="relative max-w-[22rem] flex-1">
          <Icon name="search" class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="chapterQuery"
            type="text"
            placeholder="搜索章节…"
            aria-label="搜索章节"
            class="h-8 w-full rounded-md border border-border bg-muted pr-2.5 pl-8 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          >
        </div>
        <span class="text-[11.5px] text-muted-foreground tabular-nums">
          共 {{ volumes.reduce((s, v) => s + v.chapters.length, 0) }} 章
        </span>
      </div>

      <Card v-for="v in volumes" :key="v.volume" padding="none" class="mb-2">
        <button
          type="button"
          class="flex w-full cursor-pointer items-center gap-2.5 px-3.5 py-2.5 text-left"
          @click="toggleVolume(v.volume)"
        >
          <Icon
            name="chev"
            class="h-3.5 w-3.5 text-muted-foreground transition-transform"
            :class="collapsedVolumes[v.volume] ? '-rotate-90' : ''"
          />
          <span class="text-[12.5px] font-semibold text-foreground">{{ v.volume || '目录' }}</span>
          <span class="text-[11px] text-muted-foreground tabular-nums">{{ v.chapters.length }} 章</span>
        </button>

        <div v-show="!collapsedVolumes[v.volume]" class="border-t border-border">
          <div
            v-for="c in v.chapters"
            :key="c.num"
            class="flex items-center gap-2.5 border-b border-border/60 px-3.5 py-1.5 last:border-b-0"
          >
            <span class="w-8 shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ c.num }}</span>
            <span class="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{{ c.title }}</span>
          </div>
        </div>
      </Card>

      <EmptyState v-if="!volumes.length" icon="search" title="没有匹配的章节" desc="换个关键词再试，或这本书还没有可用的目录。" />
    </div>

    <!-- ============ 文件 ============ -->
    <div v-show="tab === 'files'">
      <Card padding="none">
        <div
          v-for="f in files"
          :key="f.name"
          class="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
        >
          <span class="grid h-8 w-11 shrink-0 place-items-center rounded-sm bg-muted text-[11px] font-semibold text-foreground">
            {{ f.format }}
          </span>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[12.5px] font-medium text-foreground">{{ f.name }}</div>
            <div class="text-[11px] text-muted-foreground">{{ fmtSize(f.size) }} · {{ fmtDate(f.mtime) }}</div>
          </div>
          <Button size="sm" @click="download(f.name)">下载</Button>
        </div>
      </Card>
      <EmptyState v-if="!files.length" icon="file" title="这本书还没有文件" desc="转换完成后这里会列出成品文件。" />
    </div>

    <!-- ============ 批注 ============ -->
    <div v-show="tab === 'annotations'">
      <Card v-if="annotations.length" padding="none">
        <div
          v-for="a in annotations"
          :key="a.id"
          class="flex items-start gap-2.5 border-b border-border px-4 py-3 last:border-b-0"
        >
          <span
            class="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
            :style="{ background: highlightColor(a.color) }"
          />
          <span class="mt-1 text-[10.5px] text-muted-foreground">{{ highlightStyleLabel(a.style) }}</span>
          <div class="min-w-0 flex-1">
            <p class="text-[12.5px] leading-relaxed text-foreground">「{{ a.quote }}」</p>
            <p v-if="a.note" class="mt-1 text-[12px] text-muted-foreground">{{ a.note }}</p>
            <p class="mt-1 text-[11px] text-muted-foreground">第 {{ a.chapter + 1 }} 章</p>
          </div>
          <Button size="sm" variant="ghost" @click="startReading">前往</Button>
        </div>
      </Card>
      <EmptyState
        v-else
        icon="pencil"
        title="这本书还没有注释"
        desc="在阅读器里选中文字即可添加高亮与笔记，这里会按章节汇总。"
      />
    </div>

    <!-- ============ 编辑元数据 ============ -->
    <div v-show="tab === 'metadata'">
      <MetadataEditor :book-id="bookId" @saved="onMetaSaved" />
    </div>

    <!-- ============ 我的记录（状态 / 日期 / 评分 / 书评）============ -->
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
