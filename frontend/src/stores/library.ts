import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  api,
  type BookCard,
  type BookDetail,
  type FeaturesResult,
  type LibraryEntity,
  type LibraryFacet,
} from '@/lib/api'
import { COLLECTIONS, LIBRARIES, SMART_SHELVES } from '@/data/collections'
import { evaluateScope, type SmartScope } from '@/lib/smartScope'
import {
  ensureThresholds,
  isInProgress,
  statusFromPercent,
  thresholdsFor,
} from '@/lib/readingThresholds'

/**
 * 书库 store：组合真实书目数据与书库页的筛选状态。
 *
 * 数据来自后端 /api/books（扫描 OUTPUT_DIR 的成品），挂载时按需拉取并缓存；
 * 详情页的章节/文件由 /api/books/{id} 按 id 记忆化获取。
 * 阅读进度等持久化字段将在引入数据库后（Batch 2）接入。
 */
export const useLibraryStore = defineStore('library', () => {
  const books = ref<BookCard[]>([])
  const details = ref<Record<string, BookDetail>>({})
  const loaded = ref(false)
  const loading = ref(false)

  // ---------------- 书库（第 10 期多书库） ----------------

  /** 书库**实体**（`/api/libraries` 第 10 期起的语义） */
  const libraryEntities = ref<LibraryEntity[]>([])
  /**
   * `/api/libraries` 是否**成功**取回过。
   *
   * 第 38 期加：`libraryEntities` 初值是 `[]`、拉取失败也被 `catch` 吞掉，
   * 所以单看 `.length === 0` **分不清**「一个书库都没有」和「还没拉到 / 拉失败」。
   * 首屏引导必须只认前者 —— 否则每次进页面都会先闪一下「还没有书库」，
   * 而后端明明是通的。失败时**保持 false**（不知道就是不知道，不猜成 0）。
   */
  const librariesLoaded = ref(false)
  /** 格式分面（`/api/library-facets`）：侧栏已不再用它，保留给需要按格式筛选的页面 */
  const libraryFacets = ref<LibraryFacet[]>([])
  /** 已配置的来源根（compose 的 `LIBRARY_SOURCE_DIRS1..N`，向导按这些根浏览 / 下钻） */
  const sourceRoots = ref<{ name: string; path: string }[]>([])

  const LIB_KEY = 'nf_current_library'

  function readLibKey(): string {
    try {
      return localStorage.getItem(LIB_KEY) || ''
    } catch {
      return ''
    }
  }

  /**
   * 当前库：**空串 = 全部书库**（默认态，不做任何裁剪）。
   *
   * 持久化到 localStorage —— 选库是「我平时怎么用它」，不是「这一次怎么看」；
   * 刷新后悄悄退回「全部书库」会让人以为书丢了。
   */
  const currentLibraryId = ref<string>(readLibKey())

  /** 当前库的能力清单（后端 `core/features.py` 是真值源）；空数组 = 不裁剪 */
  const features = ref<string[]>([])
  const featureLabels = ref<Record<string, string>>({})

  /**
   * **确实一个书库都没有**（第 37 期起这是全新部署的初始态）。
   *
   * 首屏引导 / 空态文案 / 摄入前置拦截**一律只认这一个判据**：它把「拉取失败」
   * 与「真的是 0 库」分开了，也把「0 库」与「有库但没书」分开了 ——
   * 第 38 期修的就是这两件事被混成一句话的病。
   */
  const hasNoLibraries = computed(() => librariesLoaded.value && libraryEntities.value.length === 0)

  /** 当前库实体（「全部书库」时为 null） */
  const currentLibrary = computed(
    () => libraryEntities.value.find((l) => l.id === currentLibraryId.value) ?? null,
  )
  const currentLibraryName = computed(() => currentLibrary.value?.name || '全部书库')

  /** **当前库**的书目（`currentLibraryId` 为空 = 全部，不裁剪） */
  const scopedBooks = computed(() =>
    currentLibraryId.value
      ? books.value.filter((b) => (b.library_id || '') === currentLibraryId.value)
      : books.value,
  )

  /** 能力判定：清单为空（未加载 / 已选「全部书库」）时一律**可见**，宁多不漏 */
  function hasFeature(key: string): boolean {
    return features.value.length === 0 || features.value.includes(key)
  }

  /** 书库页标题（对应 v2 的 state.libTitle） */
  const shelfTitle = ref('全部书库')
  /** 智能书架筛选键（非空时优先于标签筛选） */
  const smartKey = ref('')
  /** 「库」分组筛选键（如 fmt:EPUB / issues:1），优先级最高 */
  const shelfFacet = ref('')

  /** 全部标签去重（书库页筛选 chips 用） */
  const allTags = computed(() => {
    const seen: string[] = []
    scopedBooks.value.forEach((b) => {
      ;(b.tags || []).forEach((t) => {
        if (!seen.includes(t)) seen.push(t)
      })
    })
    return seen
  })

  /** 按阅读状态筛书（真实状态优先，无状态行的书按进度兜底推导）。**限定在当前库内**。 */
  function smartBooks(key: string): BookCard[] {
    const src = scopedBooks.value
    const byStatus = (s: string) => (b: BookCard) => (b.status ?? derivedStatus(b)) === s
    switch (key) {
      case 'recent':
        return [...src].sort((a, b) => (b.mtime || 0) - (a.mtime || 0)).slice(0, 50)
      case 'unread':
        return src.filter(byStatus('unread'))
      case 'reading':
        // 搁置/弃读都「翻过」，与在读同属「未读完」的浏览心智
        return src.filter((b) => ['reading', 'paused', 'abandoned'].includes(b.status ?? derivedStatus(b)))
      case 'finished':
        return src.filter(byStatus('finished'))
      case 'annotated':
        return src.filter((b) => (b.annotation_count ?? 0) > 0)
      default:
        // 自定义智能书架：smartKey 形如 scope:{id}，按存储规则在前端求值
        if (key.startsWith('scope:')) {
          const sc = scopes.value.find((s) => `scope:${s.id}` === key)
          return sc ? evaluateScope(src, sc.rules, sc.match) : src
        }
        return src
    }
  }

  /**
   * 进度推导（第 40 期起阈值可配，判定收敛到 `lib/readingThresholds.ts`）。
   *
   * ⚠️ 语义与前身一致：**只看进度**（不看 `b.status`）—— 这个函数的下游是书架的
   * 分面计数，历史上就这么定的，本期不顺手改判据。要看真实状态优先用 `statusLabelOf`。
   */
  function derivedStatus(b: BookCard): 'unread' | 'reading' | 'finished' {
    return statusFromPercent(b.percent, thresholdsFor(currentLibraryId.value))
  }

  const isSmart = computed(() => Boolean(smartKey.value))

  /** 按**分面键**筛书（格式 / 待修复 / 无封面）。限定在当前库内。 */
  function facetBooks(key: string): BookCard[] {
    const src = scopedBooks.value
    if (key.startsWith('fmt:')) {
      const f = key.slice(4).toUpperCase()
      return src.filter((b) => (b.format || '').toUpperCase() === f)
    }
    if (key === 'issues:1') return src.filter((b) => (b.issues || []).length > 0)
    if (key === 'nocover:1') {
      // ⚠️ 判据是「**没有封面**」，与格式无关（第 87 期修）：服务端抓取的封面
      // （`db.get_cover`）对任何格式都生效，后端也已据此置 `has_cover`。
      // 此前这里只算 EPUB ⇒ 抓过封面的 PDF/TXT/MOBI/AZW3 不进这个分面，
      // 而卡片上明明显示着封面，分面与卡片**各说各话**。
      return src.filter((b) => !b.has_cover)
    }
    return src
  }

  const shelfBooks = computed(() => {
    if (shelfFacet.value) return facetBooks(shelfFacet.value)
    if (smartKey.value) return smartBooks(smartKey.value)
    return scopedBooks.value
  })

  /** 继续阅读：翻过但还没读完，按最近阅读倒序（限定在当前库内） */
  const continueReading = computed(() =>
    scopedBooks.value
      .filter((b) => isInProgress(b.percent, currentLibraryId.value))
      .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0)),
  )

  /**
   * 就地更新某本书的阅读进度（第 61 期「进度要实时」）。
   *
   * 阅读器每成功写一次进度就调它：**不重拉整库**（那是几百本的往返），只改内存里那一条 ——
   * 于是读着书切回首页时，「继续阅读」的百分比与排序立刻是新的，不必等一次 `loadBooks`。
   *
   * 边界：书不在当前列表里（换了库 / 列表还没加载）⇒ **静默忽略**，不新建条目 ——
   * 凭空插一条没有封面/元数据的残书比不显示更糟；下次 `loadBooks` 自会带上服务端真值。
   */
  function patchProgress(id: string, percent: number, at?: number): void {
    const hit = books.value.find((b) => b.id === id)
    if (!hit) return
    hit.percent = Math.min(100, Math.max(0, Number(percent) || 0))
    const ts = Number(at) || 0
    if (ts > 0) hit.updated_at = Math.max(ts, hit.updated_at || 0)
  }

  /**
   * 进行中的书目请求（第 67 期「单飞闸」）。
   *
   * ⚠️ 只有 `loaded` 守卫是**不够**的：`loadBooks` 在真正发请求前先 `await` 了阈值，
   * 这是个让步点 —— 首屏上「侧栏 + 若干仪表盘部件」在同一批微任务里各调一次，
   * 全都在任何人把 `loaded` 置真**之前**通过了守卫，于是同一份书目被并发拉了多次。
   * 实测 600 本的库：**一次页面加载打了 7 次 `/api/books`**（2.8 MB、累计 3.6 s）。
   * 现在并发调用共享同一个 Promise；`force` 期间若已有在飞的请求，也复用它
   * （它拿回来的就是最新数据，再发一次没有意义）。
   */
  let booksInflight: Promise<void> | null = null

  async function loadBooks(force = false): Promise<void> {
    if (loaded.value && !force) return
    if (booksInflight) return booksInflight
    booksInflight = (async () => {
      loading.value = true
      // 第 40 期：阈值是判「读没读完」的依据，**先拿到再判**。
      // 不 await 也能跑（有兜底值），但那是「先按默认值渲染一帧再跳」，不如等一下。
      await Promise.all([ensureThresholds(), ensureThresholds(currentLibraryId.value)])
      try {
        const res = await api.books()
        books.value = res.items
        loaded.value = true
      } finally {
        loading.value = false
        booksInflight = null
      }
    })()
    return booksInflight
  }

  /** 书库实体 + 来源父目录（空则拉取）。同 `loadBooks`，并发调用共享同一次请求（第 67 期）。 */
  let libsInflight: Promise<void> | null = null

  async function loadLibraries(force = false): Promise<void> {
    if (libraryEntities.value.length && !force) return
    if (libsInflight) return libsInflight
    libsInflight = (async () => {
      try {
        const res = await api.libraries()
        libraryEntities.value = res.items
        sourceRoots.value = res.source_roots ?? []
        librariesLoaded.value = true
      } catch {
        // 拉失败 ⇒ `librariesLoaded` 保持 false，`hasNoLibraries` 跟着为假：
        // 不知道有几个库时**不说**「还没有书库」，也不假装是 0。
      } finally {
        libsInflight = null
      }
    })()
    return libsInflight
  }

  /** 格式分面（第 10 期改址到 `/api/library-facets`）。同上，并发共享一次请求（第 67 期）。 */
  let facetsInflight: Promise<void> | null = null

  async function loadLibraryFacets(force = false): Promise<void> {
    if (libraryFacets.value.length && !force) return
    if (facetsInflight) return facetsInflight
    facetsInflight = (async () => {
      try {
        libraryFacets.value = (await api.libraryFacets()).items
      } catch {
        /* ignore */
      } finally {
        facetsInflight = null
      }
    })()
    return facetsInflight
  }

  /**
   * 拉当前库的能力清单（切库后必须重取）。
   * 失败时清空 = **不裁剪**：宁可多显示几项，也不要把功能藏起来让人找不到。
   */
  async function loadFeatures(): Promise<void> {
    try {
      const res: FeaturesResult = await api.features(currentLibraryId.value)
      features.value = res.features || []
      featureLabels.value = res.matrix?.labels || {}
    } catch {
      features.value = []
      featureLabels.value = {}
    }
  }

  /** 切换当前库（`id` 为空 = 全部书库），并刷新能力清单。 */
  async function setCurrentLibrary(id: string): Promise<void> {
    currentLibraryId.value = id || ''
    try {
      if (currentLibraryId.value) localStorage.setItem(LIB_KEY, currentLibraryId.value)
      else localStorage.removeItem(LIB_KEY)
    } catch {
      /* 隐私模式下 localStorage 可能不可用，不影响本次会话 */
    }
    // 切库 ⇒ 判定口径也跟着切（每库可覆写）。全局值不重取（切库不改全局）。
    await Promise.all([loadFeatures(), ensureThresholds(currentLibraryId.value)])
  }

  /** 自定义智能书架（smart_scopes 表）：规则存后端、求值在前端 */
  const scopes = ref<SmartScope[]>([])

  async function loadScopes(force = false): Promise<void> {
    if (scopes.value.length && !force) return
    try {
      scopes.value = (await api.smartScopes()).items
    } catch {
      /* ignore */
    }
  }

  /** 自定义书架计数：`scope:{id}` → 数量（侧栏徽标用，与内置 smartCounts 同一模式） */
  const scopeCounts = computed<Record<string, number>>(() => {
    const out: Record<string, number> = {}
    for (const s of scopes.value) {
      out[`scope:${s.id}`] = evaluateScope(scopedBooks.value, s.rules, s.match).length
    }
    return out
  })

  function findBook(id: string): BookCard | null {
    return books.value.find((b) => b.id === id) ?? null
  }

  /** 最近一次 `getBookDetail` 的失败原因（空 = 无失败）。详情页据此区分「加载失败」与「找不到」。 */
  const detailError = ref('')

  async function getBookDetail(id: string, force = false): Promise<BookDetail | null> {
    // force：元数据编辑后必须重取 —— 否则概览标签仍显示改之前的标题/作者/简介
    if (!force && details.value[id]) return details.value[id]
    detailError.value = ''
    try {
      const d = await api.bookDetail(id)
      details.value[id] = d
      return d
    } catch (e) {
      // 失败与「真的没有这本书」必须可区分：详情页据此显示「加载失败 + 重试」而非「找不到」
      detailError.value = e instanceof Error ? e.message : '加载失败'
      return null
    }
  }

  /**
   * 丢掉某本书的详情缓存（第 64 期）。
   *
   * 起因是「删书」：`details` 是按 id 缓存且**没有失效机制**的，删完之后
   * 从浏览器历史退回这本书的详情页，`getBookDetail` 会命中缓存、把一本
   * 已经不存在的书照常渲染出来（读进度、开阅读器全都会再失败一次）。
   *
   * 只删这一条，**不整表清空** —— 清空会让其它书的详情页在返回时重拉一遍。
   */
  function forgetDetail(id: string): void {
    delete details.value[id]
  }

  /** 进入书库页（题材筛选已由书架筛选面板承担；不再有按标签筛选的入口） */
  function openShelf(title: string): void {
    shelfTitle.value = title || '全部书库'
    smartKey.value = ''
    shelfFacet.value = ''
  }

  /** 进入智能书架（按阅读状态筛选） */
  function openSmart(title: string, key: string): void {
    shelfTitle.value = title || '智能书架'
    smartKey.value = key
    shelfFacet.value = ''
  }

  /** 进入「库」分组（按分面键 fmt: / issues: / nocover: 筛选；侧栏已不再用它） */
  function openLibrary(title: string, key: string): void {
    shelfTitle.value = title || '书库'
    shelfFacet.value = key
    smartKey.value = ''
  }

  /** 切到某书库并进入书库页（侧栏「库」组点击的语义：**切库 + 进书架**） */
  async function openLibraryById(id: string, title = ''): Promise<void> {
    await setCurrentLibrary(id)
    openShelf(title || currentLibraryName.value)
  }

  return {
    books,
    details,
    loaded,
    loading,
    shelfTitle,
    smartKey,
    shelfFacet,
    libraryFacets,
    allTags,
    shelfBooks,
    continueReading,
    patchProgress,
    isSmart,
    smartBooks,
    loadBooks,
    loadLibraries,
    loadLibraryFacets,
    scopes,
    loadScopes,
    scopeCounts,
    findBook,
    getBookDetail,
    forgetDetail,
    detailError,
    openShelf,
    openSmart,
    openLibrary,
    openLibraryById,
    // 多书库（第 10 期）
    libraryEntities,
    librariesLoaded,
    hasNoLibraries,
    sourceRoots,
    currentLibraryId,
    currentLibrary,
    currentLibraryName,
    scopedBooks,
    features,
    featureLabels,
    hasFeature,
    loadFeatures,
    setCurrentLibrary,
    // 侧栏三组条目（静态导航）
    libraries: LIBRARIES,
    smartShelves: SMART_SHELVES,
    collections: COLLECTIONS,
  }
})
