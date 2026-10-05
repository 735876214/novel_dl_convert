import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  api,
  type BookCard,
  type BookDetail,
  type FeaturesResult,
  type LibraryEntity,
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
 *
 * 第 88 期 C 批（修正）：**书架页**改为分页 + 无限滚动（首屏只取第一页，其余页增量拉取），
 * 但分页状态**只属于书架页自己的分页源**（`shelfLoadedBooks`）—— 共享的 `books` 保持
 * **全量**语义，否则读它的其它消费方（侧栏计数 / 仪表盘 / BrowseView / SmartScopesView…）
 * 只会看到已加载的**前缀**（600 本的库被显示成 120 本）。
 * 页大小与续拉上限集中在下面两个常量里。
 */

/**
 * 书库列表的**页大小**（第 88 期 C 批）。
 *
 * 取值 120 的理由：
 *   · 够大 —— 常见中小书库（< 120 本）一次就拉全，体感与改造前**完全一样**（不闪、不续拉）；
 *   · 够小 —— 600 本的库首页约 120 本，响应体积降到全量的约 1/5，首屏渲染的行数也降一个量级；
 *   · 与「骨架屏 12 格」「网格每屏 ≤ 9 列」量级自洽：一页足够铺满若干屏，不会一滚就到底。
 * 换值只改这里一处（store 与 spec / ShelfView 共用）。
 */
export const BOOKS_PAGE_SIZE = 120

/**
 * 「筛选 / 搜索在**已加载**的书里没命中」时的**自动续拉上限**（页）。
 *
 * 为什么要上限：本仓的排序与筛选都在**客户端**做（`ShelfView` 的 computed），服务端按
 * 文件序返回；若用户筛一个「排在很后面」的格式，理论上要拉穿全库才找得到。一次拉穿全库
 * 既慢又费流量，所以自动续拉**最多 5 页**（= 600 本，覆盖绝大多数真实库的命中范围）；
 * 到顶就停下，把「继续加载以查找」的按钮交给用户（见 `ShelfView`）。
 */
export const AUTO_CONTINUE_MAX_PAGES = 5

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

  // ---------------- 书架页的分页 / 无限滚动（第 88 期 C 批；修正版） ----------------
  //
  // ⚠️ 分页状态**只属于书架页自己的分页缓冲**（`shelfLoadedBooks`），与共享的 `books`
  // 彻底分开。起因：C 批把分页直接建在共享的 `books` 上，于是所有读 `library.books` 的
  // 其它消费方（侧栏「全部书库」计数、仪表盘书架行 / 部件、BrowseView、SmartScopesView…）
  // 只看得到**已加载的前缀**，600 本的库显示成 120 本 —— 既有 spec 覆盖不到，真实使用却一眼可见。
  // 现在两条路各归各、互不阻塞：
  //   · `books`             —— **全量**（`loadBooks()` 不带 limit，服务端整份返回），其它消费方照旧；
  //   · `shelfLoadedBooks`  —— 书架页**自己**的分页缓冲（首屏只取第一页，滚到底续拉）。
  // 书架首屏**不**等全量 `loadBooks()`；全量 `books` 由侧栏 / 应用启动那条既有路径（B 批）负责。
  //
  /** 书架已加载的页（服务端顺序；**未**做库 / 分面 / 智能书架裁剪 —— 那些在 `shelfBooks` 里） */
  const shelfLoadedBooks = ref<BookCard[]>([])
  /** 服务端报告的**书目总数**（`/api/books` 的 `total`，始终是「未切片前的总数」）。 */
  const shelfTotal = ref(0)
  /** 服务端是否还有下一页（`has_more`）。为假时不再续拉、隐藏「加载更多」。 */
  const shelfHasMore = ref(false)
  /** 书架**首页**是否正在加载（骨架屏用）。**与续拉 `shelfLoadingMore` 分开**。 */
  const shelfLoading = ref(false)
  /** 是否正在拉下一页。**与首页 `shelfLoading` 分开**：续拉不该盖掉已有列表、也不该触发骨架屏。 */
  const shelfLoadingMore = ref(false)
  /**
   * 书架首页是否**成功**取回过。
   *
   * 与全量的 `loaded` 同一纪律：失败时**保持 false** —— 置真会让之后永远短路、
   * 界面一直显示空书架。`force` 绕过它重取。
   */
  const shelfLoaded = ref(false)
  /**
   * 已从服务端**收到**的条数（= 下一页的 `offset`）。
   * ⚠️ 与 `shelfLoadedBooks.length` 分开：后者是**去重后**的。若某页被整页去重，用去重后的
   * 长度当 offset 会原地打转、永远推进不了。
   */
  const shelfCursor = ref(0)
  /** 自动续拉已用页数（见 `AUTO_CONTINUE_MAX_PAGES`）；排序 / 筛选变化时归零。 */
  const shelfContinuedPages = ref(0)

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

  /**
   * 按阅读状态筛书的**取源版本**：把「按什么筛」与「在哪个数组上筛」分开。
   *
   * 第 88 期 C 批（修正）加：书架页在自己的分页缓冲（`shelfLoadedBooks`）上筛，
   * 其它消费方（仪表盘书架行 `DashboardShelfRow` 等）仍在**全量** `books` 上筛。
   * 判据只有这一份，两处不会各说各话。
   */
  function smartBooksOf(src: BookCard[], key: string): BookCard[] {
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

  /** 按阅读状态筛书（真实状态优先，无状态行的书按进度兜底推导）。**限定在当前库内**（全量源）。 */
  function smartBooks(key: string): BookCard[] {
    return smartBooksOf(scopedBooks.value, key)
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

  /** 按**分面键**筛书的**取源版本**（格式 / 待修复 / 无封面）；取源理由同 `smartBooksOf`。 */
  function facetBooksOf(src: BookCard[], key: string): BookCard[] {
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

  /**
   * **书架页**在分页缓冲上按当前库裁剪（`currentLibraryId` 为空 = 全部，不裁剪）。
   *
   * ⚠️ 与 `scopedBooks`（全量 `books` 的库内投影）分开：书架看的是**已加载的页**，
   * 其它消费方看的是**全量**。这正是首屏快、又不缩小他人视野的关键。
   */
  const shelfScopedBooks = computed(() =>
    currentLibraryId.value
      ? shelfLoadedBooks.value.filter((b) => (b.library_id || '') === currentLibraryId.value)
      : shelfLoadedBooks.value,
  )

  /**
   * 书架页的**基础筛选源**（库 / 分面 / 智能书架）—— 建在书架自己的分页缓冲上。
   *
   * 全仓只有 `ShelfView` 读它；其它库内投影（`scopedBooks` / `continueReading` /
   * `scopeCounts` / `smartBooks`）一律仍走全量 `books`（见上面各自的注释）。
   */
  const shelfBooks = computed(() => {
    const src = shelfScopedBooks.value
    if (shelfFacet.value) return facetBooksOf(src, shelfFacet.value)
    if (smartKey.value) return smartBooksOf(src, smartKey.value)
    return src
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
   *
   * ⚠️ 第 88 期 C 批（修正）：`books` 与书架分页缓冲 `shelfLoadedBooks` 是**两份不同的
   * 数组**（两次不同的响应），所以两处都要就地改 —— 否则从阅读器退回书架时，书架上那本
   * 的百分比会停在旧值（分页把书架从 `books` 里拆出去时最容易漏的一处）。
   */
  function patchProgress(id: string, percent: number, at?: number): void {
    const hits = [books.value.find((b) => b.id === id), shelfLoadedBooks.value.find((b) => b.id === id)]
    if (!hits[0] && !hits[1]) return
    const pct = Math.min(100, Math.max(0, Number(percent) || 0))
    const ts = Number(at) || 0
    for (const b of hits) {
      if (!b) continue
      b.percent = pct
      if (ts > 0) b.updated_at = Math.max(ts, b.updated_at || 0)
    }
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

  /**
   * 加载**全量书目**（第 88 期 C 批修正：语义从「拉第一页」**回到「拉全量」**）。
   *
   * `books` 是**共享的全量真值源**：侧栏「全部书库」计数、仪表盘书架行 / 部件、
   * BrowseView / SmartScopesView 都直接（`books`）或间接（`scopedBooks` / `smartBooks` /
   * `continueReading` / `scopeCounts`）读它。所以这里**不带 `limit`** —— 服务端整份返回，
   * 顺序与字段与改造前一模一样。
   *
   * ⚠️ 书架页的**分页**不在这条路上：那是书架自己的 `shelfLoadedBooks`（见下）。
   * 两条路互不阻塞 —— 书架首屏不等全量，全量由侧栏 / 应用启动那条既有路径负责。
   *
   * `force` 是「绕过 `loaded` 守卫重拉」（数据变更 / 扫描完成 / 手动重试都走这条）。
   */
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
        // 第 88 期 C 批修正：**回到全量**（不传 limit/offset ⇒ 服务端整份返回）。
        // ⚠️ 别在这里加 limit：共享的 `books` 一旦被切片，读它的消费方就会「只见前缀」——
        // 那正是 C 批引入、本批要挡下的副作用。
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

  // ---- 书架页自己的分页源（第 88 期 C 批；修正版）----
  //
  // 下面这一组**只**服务书架页：首屏取第一页，其余页在滚到底 / 点「加载更多」时增量追加。
  // 它们**不碰** `books` / `loaded`：那两条是全量那条路的（见上面的 `loadBooks`）。

  /** 把新到的一页**按 id 去重**后追加到书架缓冲（新数组 ⇒ 以「引用」为键的 memo 自动重算）。 */
  function appendShelfUnique(items: BookCard[]): void {
    if (!items.length) return
    const seen = new Set(shelfLoadedBooks.value.map((b) => b.id))
    const add = items.filter((b) => b.id && !seen.has(b.id))
    if (add.length) shelfLoadedBooks.value = [...shelfLoadedBooks.value, ...add]
  }

  let shelfInflight: Promise<void> | null = null

  /**
   * 加载书架的**首页**（第 88 期 C 批修正后的分页入口，`ShelfView` 挂载时调）。
   *
   * 只写 `shelfLoadedBooks`，**不碰**全量 `books` / `loaded` —— 后者由 `loadBooks()` 负责。
   * `force` 绕过 `shelfLoaded` 守卫重取首页（数据变更 / 手动重试走这条）。
   */
  async function loadShelfFirstPage(force = false): Promise<void> {
    if (shelfLoaded.value && !force) return
    if (shelfInflight) return shelfInflight
    shelfInflight = (async () => {
      shelfLoading.value = true
      booksError.value = ''
      try {
        const res = await api.books({ limit: BOOKS_PAGE_SIZE, offset: 0 })
        shelfLoadedBooks.value = res.items
        shelfCursor.value = res.items.length
        shelfTotal.value = typeof res.total === 'number' ? res.total : res.items.length
        // `has_more` 是后端权威值；拿不到（旧后端未落地）就按「总数 vs 已收到」兜底推。
        shelfHasMore.value = res.has_more ?? shelfCursor.value < shelfTotal.value
        shelfContinuedPages.value = 0
        shelfLoaded.value = true
      } catch (e) {
        // ⚠️ 失败**绝不写 `shelfLoaded`**（也不动全量 `loaded`）：否则之后永远短路、
        // 书架一直显示空。原因写 `booksError` —— 书架与全量共用同一句「书库加载失败」文案。
        booksError.value = e instanceof Error ? e.message : '加载失败'
      } finally {
        shelfLoading.value = false
        shelfInflight = null
      }
    })()
    return shelfInflight
  }

  let shelfMoreInflight: Promise<void> | null = null

  /**
   * 拉书架的**下一页**（第 88 期 C 批）：首屏 `loadShelfFirstPage()` 之后，其余页从这里增量追加。
   *
   * 与首页的分工（纪律，别破坏）：
   *   · `shelfLoading` / `shelfInflight` 只管首页（首页失败要显示错误态、**不置 `shelfLoaded`**）；
   *   · 续拉有自己的单飞闸 `shelfMoreInflight` 与 `shelfLoadingMore`，**不碰 `shelfLoaded`** ——
   *     它已为真，重复置真没有意义；失败只记 `booksError`（不打断、也不清空已有列表）。
   *
   * 去重：服务端顺序稳定，正常不会重复；但翻页期间书库可能被标脏重扫而改变总数 / 顺序，
   * 故**按 id 去重**再追加 —— 宁可少一条诡异的重复，也不要在列表里出现两张一模一样的卡。
   */
  async function loadMoreShelfBooks(): Promise<void> {
    if (shelfMoreInflight) return shelfMoreInflight
    if (!shelfHasMore.value) return
    shelfMoreInflight = (async () => {
      shelfLoadingMore.value = true
      const offset = shelfCursor.value
      try {
        const res = await api.books({ limit: BOOKS_PAGE_SIZE, offset })
        appendShelfUnique(res.items)
        shelfCursor.value += res.items.length
        if (typeof res.total === 'number') shelfTotal.value = res.total
        shelfHasMore.value = res.has_more ?? shelfCursor.value < shelfTotal.value
      } catch (e) {
        // 失败**不改 `shelfLoaded`、不清 `shelfLoadedBooks`**：已有数据比一个错误页有用（B 批纪律）。
        booksError.value = e instanceof Error ? e.message : '加载失败'
      } finally {
        shelfLoadingMore.value = false
        shelfMoreInflight = null
      }
    })()
    return shelfMoreInflight
  }

  /**
   * **预算内**的自动续拉（供「筛选在已加载里没命中、但还有更多」时使用）。
   *
   * 返回是否**真的往前推进了一页** —— 调用方据此决定要不要继续循环：
   * `false` = 没有更多 / 已到 `AUTO_CONTINUE_MAX_PAGES` / 服务端没给新内容（越界或整页去重）。
   */
  async function autoLoadMoreShelf(): Promise<boolean> {
    if (!shelfHasMore.value) return false
    if (shelfContinuedPages.value >= AUTO_CONTINUE_MAX_PAGES) return false
    const before = shelfCursor.value
    shelfContinuedPages.value += 1
    await loadMoreShelfBooks()
    return shelfCursor.value > before
  }

  /**
   * 排序 / 筛选 / 搜索变化时调用（`ShelfView` 用 watch 挂）。
   *
   * 为什么：**把「自动续拉预算」归零**，让新的筛选口径重新拥有整份预算 —— 否则
   * 「上一种筛选已经连拉过 5 页」会把新筛选的名额吃掉，新筛选即使后面真有匹配也永远找不到。
   *
   * 为什么**不**连数据一起丢掉、重拉第一页：本仓的排序与筛选都在**客户端** computed 里做
   * （`ShelfView.sorted` / `filtered`），服务端返回的行与排序无关 ⇒ 重拉只会拿回**同一批行**，
   * 白一次往返；而丢掉已加载页还会把用户滚了半天的位置清空。「真正诚实」的出口是页头 /
   * 页脚的「已显示 N / 共 M」提示 + 自动续拉（见 `ShelfView`）。
   */
  function resetShelfQuery(): void {
    shelfContinuedPages.value = 0
  }

  /**
   * 数据变更后刷新书目（第 88 期 C 批修正）：**两条路一起刷**。
   *
   * 书架页看到的是分页源（`shelfLoadedBooks`），侧栏计数 / 仪表盘等看到的是全量 `books` ——
   * 删书 / 批量改状态 / 移动 / 建库 / 扫描完成之后两处都得回到服务端真值，缺一个就会
   * 「书架首页对了、侧栏计数还是旧的」（或反过来）。收在一个方法里，避免调用点漏刷一处。
   */
  async function refreshBooks(): Promise<void> {
    await Promise.all([
      loadBooks(true),
      // 书架分页源**没用过**（用户没进过书架）就不必刷 —— 别为看不见的页面多发一次请求
      shelfLoaded.value ? loadShelfFirstPage(true) : Promise.resolve(),
    ])
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
    if (refresh && loaded.value) void refreshBooks()
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
    // 书架页的分页 / 无限滚动（第 88 期 C 批；修正版：与全量 `books` 分开）
    shelfLoadedBooks,
    shelfTotal,
    shelfHasMore,
    shelfLoading,
    shelfLoadingMore,
    shelfLoaded,
    shelfContinuedPages,
    loadShelfFirstPage,
    loadMoreShelfBooks,
    autoLoadMoreShelf,
    resetShelfQuery,
    refreshBooks,
    shelfTitle,
    smartKey,
    shelfFacet,
    allTags,
    shelfBooks,
    continueReading,
    patchProgress,
    isSmart,
    smartBooks,
    loadBooks,
    loadLibraries,
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
