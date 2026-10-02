import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  api,
  type BookCard,
  type BookDetail,
  type FeaturesResult,
  type LibraryEntity,
  type LibraryFacet,
  type LibraryScanState,
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
  /**
   * 最近一次 `loadBooks` 的失败原因（空 = 无失败）。第 88 期加。
   *
   * 起因：失败时 `books` 仍是初值 `[]`，视图只看到「空」——于是「网络挂了」被渲染成
   * 「这个书架还是空的」，用户完全不知道发生了什么。书架据此显示「加载失败 + 重试」。
   */
  const booksError = ref('')
  /**
   * 书目数据的**原地变更计数**（`patchProgress` 每次都 ++）。
   *
   * `scopeCounts` 的 memo 以「数组引用」为键，而 `patchProgress` 是**就地改**某一本的
   * 进度（引用不变）—— 没有这个计数，按进度判定的智能书架徽标会停在旧数字上。
   */
  const booksRevision = ref(0)

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

  /**
   * 全部标签去重（书库页筛选 chips 用）。
   *
   * 第 88 期：用 `Set` 而不是 `array.includes` —— 后者对每个标签都要线性扫一遍已收集的，
   * 近似 O(标签数²)。几百本书 × 几十个标签时这是实打实的卡顿来源；Set 是 O(1) 摊还，
   * 且**保持插入顺序**（与原来的去重次序完全一致，chips 顺序不变）。
   */
  const allTags = computed(() => {
    const seen = new Set<string>()
    scopedBooks.value.forEach((b) => {
      ;(b.tags || []).forEach((t) => seen.add(t))
    })
    return [...seen]
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
    // 就地改了数据 ⇒ 让以「引用」为键的 memo（scopeCounts）知道该重算
    booksRevision.value += 1
  }

  /**
   * 进行中的书目请求（第 67 期「单飞闸」）。
   *
   * ⚠️ 只有 `loaded` 守卫是**不够**的：`loaded` 要等响应回来才置真，在那之前的窗口里
   * 首屏上「侧栏 + 书架 + 若干仪表盘部件」会在同一批微任务里各调一次，全都通过守卫，
   * 于是同一份书目被并发拉了多次。实测 600 本的库：**一次页面加载打了 7 次 `/api/books`**
   * （2.8 MB、累计 3.6 s）。
   * 现在并发调用共享同一个 Promise；`force` 期间若已有在飞的请求，也复用它
   * （它拿回来的就是最新数据，再发一次没有意义）。
   *
   * （第 88 期把「先 await 阈值再发书目」的串行瀑布拿掉了，但**这个闸不能拆**：
   *  `loaded` 的窗口依然存在，闸拦的正是那个窗口里的并发调用。）
   */
  let booksInflight: Promise<void> | null = null

  async function loadBooks(force = false): Promise<void> {
    if (loaded.value && !force) return
    if (booksInflight) return booksInflight
    booksInflight = (async () => {
      loading.value = true
      booksError.value = ''
      // 第 88 期：阈值与书目**并行**取 —— 此前是「先 await 阈值、再发书目」的串行瀑布，
      // 两个小请求把那个几百 KB 的大请求硬生生挡在后面（实测「导入后第一次打开特别慢」）。
      // 阈值有 `FALLBACK` 兜底，且缓存是 `reactive` 的：晚到会让依赖它的 computed 自己
      // 重算，所以**不必**等它 —— 先用兜底值渲染，真值到了再自动修正。
      void Promise.all([ensureThresholds(), ensureThresholds(currentLibraryId.value)])
      try {
        const res = await api.books()
        books.value = res.items
        // 第 88 期：响应可选带上「正在刷新索引的库」——拿不到（后端未落地）就当空数组
        scanningLibraryIds.value = Array.isArray(res.scanning) ? res.scanning.filter(Boolean) : []
        loaded.value = true
        // 有库在扫 ⇒ 起轮询看进度（扫完自停）；不在扫就什么都不做
        syncScanPolling()
      } catch (e) {
        // ⚠️ 失败**绝不写 `loaded`**：否则之后永远短路不再拉，界面会一直显示空书架。
        // 保存原因供视图显示「加载失败 + 重试」；**不再向下抛**（调用方多是 `void`，
        // 抛出会变成无人 catch 的 unhandled rejection，而那对用户没有任何帮助）。
        booksError.value = e instanceof Error ? e.message : '加载失败'
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

  // ---------------- 扫描 / 建索引进度（第 88 期） ----------------
  //
  // 用户症状：「导入后第一次打开特别慢、显示空的很久才有书」。
  // 一部分时间是后端正在**建索引** —— 那时列表天然是旧的/空的，界面得说清楚在干什么，
  // 并给一个进度感，而不是干等。后端并行开发中，字段/接口都按**可选**容错。

  /** 正在刷新索引的库 id（来自 `/api/books` 的可选 `scanning`；拿不到 = 空 = 不显示） */
  const scanningLibraryIds = ref<string[]>([])
  /** 每库扫描状态（来自 `/api/libraries/scan-state`），键 = library_id */
  const scanStates = ref<Record<string, LibraryScanState>>({})

  /** 轮询间隔（需求给定 2 秒；扫完就停，非常驻） */
  const SCAN_POLL_MS = 2000
  let scanTimer: ReturnType<typeof setInterval> | null = null

  /**
   * 停止扫描轮询。`refresh=true` 时顺带重拉一次书目 ——
   * 索引刚建完，列表多半多了/少了书，用户正等它出现。
   */
  function stopScanPolling(refresh = false): void {
    if (scanTimer !== null) {
      clearInterval(scanTimer)
      scanTimer = null
    }
    if (refresh && loaded.value) void loadBooks(true)
  }

  /** 拉一次扫描状态并合并；若已无库在扫则**停止轮询**（并刷新一次书目）。 */
  async function fetchScanState(): Promise<void> {
    try {
      const r = await api.librariesScanState()
      const map: Record<string, LibraryScanState> = {}
      for (const it of r?.items ?? []) {
        if (it && it.library_id) map[it.library_id] = it
      }
      scanStates.value = map
      const still = Object.values(map)
        .filter((s) => s.scanning)
        .map((s) => s.library_id)
      if (!still.length) {
        // 扫完了：清掉标记并停（refresh 让新建索引出来的书立刻可见）
        scanningLibraryIds.value = []
        stopScanPolling(true)
      }
    } catch {
      // 接口未落地 / 读失败：停轮询，别拿错误刷屏，也别影响书架本身
      stopScanPolling()
    }
  }

  /** 按当前 `scanningLibraryIds` 决定开不开轮询（重复调用安全：已在轮询就不重开）。 */
  function syncScanPolling(): void {
    if (!scanningLibraryIds.value.length) {
      stopScanPolling()
      return
    }
    if (scanTimer === null) {
      void fetchScanState()
      scanTimer = setInterval(() => void fetchScanState(), SCAN_POLL_MS)
    }
  }

  /** 是否**有库**在建立索引 */
  const isScanning = computed(() => scanningLibraryIds.value.length > 0)

  /**
   * 当前上下文（当前库 / 全部书库）的扫描进度汇总；`null` = 不显示。
   * 只统计与当前库相关的在扫库 —— 在别的库建索引不该在当前库的书架上弹条。
   */
  const scanProgress = computed<{ libs: number; scanned: number; added: number } | null>(() => {
    const current = currentLibraryId.value
    const ids = scanningLibraryIds.value.filter((id) => !current || id === current)
    if (!ids.length) return null
    let scanned = 0
    let added = 0
    for (const id of ids) {
      const s = scanStates.value[id]
      if (!s) continue
      scanned += Number(s.scanned) || 0
      added += Number(s.added) || 0
    }
    return { libs: ids.length, scanned, added }
  })

  /**
   * 自定义书架计数：`scope:{id}` → 数量（侧栏徽标用，与内置 smartCounts 同一模式）。
   *
   * 第 88 期加 memo：`evaluateScope` 对每个智能书架都要**全量扫一遍书**，而侧栏每渲染
   * 一组都会读一遍这张表。以「书目数组引用 + scopes 引用 + 原地变更计数」为键 ——
   * 三者都没变时直接复用上次结果，不做重复的全量求值。
   */
  let scopeCountsCache: {
    books: BookCard[]
    scopes: SmartScope[]
    rev: number
    out: Record<string, number>
  } | null = null

  const scopeCounts = computed<Record<string, number>>(() => {
    const src = scopedBooks.value
    const scs = scopes.value
    const rev = booksRevision.value
    const c = scopeCountsCache
    if (c && c.books === src && c.scopes === scs && c.rev === rev) return c.out
    const out: Record<string, number> = {}
    for (const s of scs) {
      out[`scope:${s.id}`] = evaluateScope(src, s.rules, s.match).length
    }
    scopeCountsCache = { books: src, scopes: scs, rev, out }
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
    booksError,
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
    // 扫描 / 建索引进度（第 88 期）
    scanningLibraryIds,
    scanStates,
    isScanning,
    scanProgress,
    fetchScanState,
    // 侧栏三组条目（静态导航）
    libraries: LIBRARIES,
    smartShelves: SMART_SHELVES,
    collections: COLLECTIONS,
  }
})
