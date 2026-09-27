import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import {
  api,
  type BookCard,
  type BookDetail,
  type LibraryEntity,
  type SimilarBook,
} from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import BookDetailView from '@/views/BookDetailView.vue'

/**
 * `@/lib/api` 整体替换 —— 详情页与它下面每个子组件（含 `DetailHero` 的收藏夹菜单）
 * 的每一次取数都走它。桩要一次给齐：少一个就在 `onMounted` 里抛，而那个异常会被
 * store 的 `catch` 吞成「加载失败」，用例随后以「找不到元素」的形式报错，**离真正
 * 的原因很远**（这是 `ReaderView.spec.ts` 里记下的同一条教训）。
 */
vi.mock('@/lib/api', () => ({
  api: {
    bookDetail: vi.fn(),
    books: vi.fn(),
    libraries: vi.fn(),
    similarBooks: vi.fn(),
    getProgress: vi.fn(),
    listAnnotations: vi.fn(),
    bookCollections: vi.fn(),
    collections: vi.fn(),
    // `ensureThresholds` 直接 `.then()` 它的返回值 —— 给 undefined 会**同步**抛
    // TypeError（在它自己的 `.catch` 之前），整套用例会以「加载失败」的形式红掉
    readingThresholds: vi.fn().mockResolvedValue({ started: 1, finished: 99 }),
    coverUrl: (id: string) => `/api/books/${id}/cover`,
    downloadUrl: (name: string) => `/api/download/${name}`,

    // ---- 「我的记录」标签（ReadingRecord 自取数据，既有契约）----
    bookStatus: vi.fn(),
    bookReview: vi.fn(),
    // ---- 「阅读日志」标签（第 63 期 3/6；ReadingLogTab 也是自取数据）----
    // 默认 `active: false` 时它一个请求都不发，所以这两个桩目前只在有人点开那个标签时
    // 才用得上。仍然一次给齐：**缺桩的失败不是崩溃，是「阅读记录加载失败」** ——
    // 一个看起来像真故障的假故障，排查起来离真正的原因很远。
    bookReadingStats: vi.fn(),
    readingAttempts: vi.fn(),
  },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const m = {
  bookDetail: vi.mocked(api.bookDetail),
  books: vi.mocked(api.books),
  libraries: vi.mocked(api.libraries),
  similarBooks: vi.mocked(api.similarBooks),
  getProgress: vi.mocked(api.getProgress),
  listAnnotations: vi.mocked(api.listAnnotations),
  bookCollections: vi.mocked(api.bookCollections),
  collections: vi.mocked(api.collections),
  bookStatus: vi.mocked(api.bookStatus),
  bookReview: vi.mocked(api.bookReview),
  bookReadingStats: vi.mocked(api.bookReadingStats),
  readingAttempts: vi.mocked(api.readingAttempts),
}

const BOOK_ID = 'lib$aaa'

/**
 * 面包屑的可见段（去掉了分隔符「/」）。
 * 用段列表而不是 `nav.text()`：后者会把模板缩进产生的空白一起带出来，
 * 断言就得写成对空白敏感的样子（`'书库 /lib/三体'` 那种）。
 */
/** `api.libraries()` 的返回体（`LibrariesResult`）—— 详情页只消费 `items`，其余给空 */
function makeLibraries(items: LibraryEntity[]) {
  return { items, total: items.length, types: [], source_roots: [] }
}

function breadcrumbSegments(w: VueWrapper): string[] {
  return w
    .findAll('nav span')
    .map((s) => s.text())
    .filter((t) => t !== '/')
}

function makeBook(over: Partial<BookCard> = {}): BookCard {
  return {
    id: BOOK_ID,
    name: '三体.epub',
    title: '三体',
    author: '刘慈欣',
    series: '',
    has_cover: false,
    format: 'EPUB',
    size: 1024,
    mtime: 1700000000,
    c1: 'oklch(0.9 0 0)',
    c2: 'oklch(0.8 0 0)',
    tags: [],
    narrators: [],
    year: '2008',
    publisher: '重庆出版社',
    isbn: '9787536692930',
    language: 'zh',
    description: '一句话简介。',
    issues: [],
    library_id: 'lib',
    ...over,
  }
}

function makeDetail(over: Partial<BookDetail> = {}): BookDetail {
  return {
    ...makeBook(),
    chapters: [{ volume: '', chapters: [{ num: 1, index: 0, title: '第一章' }] }],
    files: [{ name: '三体.epub', format: 'EPUB', size: 1024, mtime: 1700000000 }],
    ...over,
  }
}

function makeSimilar(over: Partial<SimilarBook> = {}): SimilarBook {
  return {
    id: 'lib$bbb',
    title: '球状闪电',
    author: '刘慈欣',
    series: '',
    series_index: '',
    cover_url: '',
    has_cover: true,
    score: 0.8,
    reasons: ['同作者'],
    ...over,
  }
}

let router: Router

/** 挂载详情页并等干净（`onMounted` 里是串行 await 的取数） */
async function mountDetail(): Promise<VueWrapper> {
  const wrapper = mount(BookDetailView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

beforeEach(async () => {
  setActivePinia(createPinia())
  // 默认桩：一本书、一个库、无相似书、无进度、无批注、无收藏夹
  m.bookDetail.mockResolvedValue(makeDetail())
  m.books.mockResolvedValue({ items: [makeBook()], total: 1 })
  m.libraries.mockResolvedValue(makeLibraries([{ id: 'lib', name: '我的书库' } as LibraryEntity]))
  m.similarBooks.mockResolvedValue({ items: [] })
  m.getProgress.mockResolvedValue({ locator: 0, percent: 0 })
  m.listAnnotations.mockResolvedValue({ items: [] })
  m.bookCollections.mockResolvedValue({ items: [] })
  m.collections.mockResolvedValue({ items: [] })
  m.bookStatus.mockResolvedValue({
    book_id: BOOK_ID,
    status: 'unread',
    started_at: 0,
    finished_at: 0,
    updated_at: 0,
  })
  m.bookReview.mockResolvedValue({ book_id: BOOK_ID, stars: 0, review: '' })
  // 默认「这本书没读过」：`reading: null` 是服务端对「从没读过」的**明确回答**，
  // 于是「阅读日志」标签渲染的是空态（另两种形态在 `ReadingLogTab.spec.ts` 里逐个盯）
  m.bookReadingStats.mockResolvedValue({
    book_id: BOOK_ID,
    reading: null,
    records: null,
    days: [],
    sessions: [],
  })
  m.readingAttempts.mockResolvedValue({ items: [], total: 0, current: null })

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/book/:id', name: 'book', component: BookDetailView },
      { path: '/shelf', name: 'shelf', component: { template: '<div />' } },
    ],
  })
  await router.push(`/book/${BOOK_ID}`)
  await router.isReady()
})

describe('BookDetailView', () => {
  /**
   * 第 63 期修的 bug：那块 `EmptyState`（「暂无成品文件」）的 `v-else` 挂在了
   * **相似书**的 `v-if` 上，不是挂在文件列表的 `v-if` 上。于是**没有相似书**的书
   * 会在概览右栏多渲染一块「暂无成品文件」—— 而这本书明明有文件。
   *
   * 这条用例钉住「没有相似书时页面上不出现这句话」。
   */
  it('没有相似书时，不渲染「暂无成品文件」那块（v-else 挂错的回归护栏）', async () => {
    const w = await mountDetail()
    // 前置断言：这本书确实有文件，所以「暂无成品文件」无论如何都是假话
    expect(w.text()).toContain('三体.epub')
    expect(w.text()).not.toContain('暂无成品文件')
  })

  it('有相似书时带封面渲染，并显示相似原因', async () => {
    m.similarBooks.mockResolvedValue({ items: [makeSimilar()] })
    const w = await mountDetail()

    expect(w.text()).toContain('球状闪电')
    expect(w.text()).toContain('同作者')
    // 封面：BookCover 在有 has_cover 时渲染 img（第 63 期起相似书才真正用上这个字段）
    const srcs = w.findAll('img').map((i) => i.attributes('src') ?? '')
    expect(srcs.some((s) => s.includes('lib$bbb'))).toBe(true)
  })

  /**
   * 面包屑第二段此前读的是 `library.shelfTitle` —— 那是**全局导航状态**，由上一个
   * 访问的书架页写入。深链进来（新标签页 / 刷新）时它还是上一次的标题。
   *
   * 这条用例故意把 `shelfTitle` 设成「最近阅读」这个脏值，断言面包屑**不受它影响**。
   */
  it('面包屑第二段按书的归属库推导，不读上一次导航留下的 shelfTitle', async () => {
    const store = useLibraryStore()
    store.shelfTitle = '最近阅读'

    const w = await mountDetail()

    // 段 = nav 里的 span 去掉分隔符「/」；改前第二段会是「最近阅读」
    expect(breadcrumbSegments(w)).toEqual(['我的书库', '三体'])
  })

  it('书不属于任何已知书库时，面包屑不留空段，也不显示内部 id', async () => {
    m.libraries.mockResolvedValue(makeLibraries([]))
    const w = await mountDetail()

    // 只掉「我的书库」那一段，不补一个「lib」（内部 id 对用户没有意义）
    expect(breadcrumbSegments(w)).toEqual(['三体'])
  })

  /**
   * 断言收在 `[data-test="hero-progress"]` 那一块里，**不按整页文本判**：
   * 「我的记录」标签的状态选项里有「已读完」，它含子串「已读」—— 按整页断言
   * `not.toContain('已读')` 会被一个与 hero 毫不相干的文案绊倒（这条以前是绿的，
   * 只因为那个标签当时没渲染出来）。
   */
  it('进度 >0 时 hero 显示进度条与百分比，0% 时两样都不显示', async () => {
    m.getProgress.mockResolvedValue({ locator: 12, percent: 53.4 })
    let w = await mountDetail()
    expect(w.find('[data-test="hero-progress"]').text()).toContain('已读 53%')
    expect(w.text()).toContain('继续阅读')

    setActivePinia(createPinia())
    await router.push(`/book/${BOOK_ID}`)
    m.getProgress.mockResolvedValue({ locator: 0, percent: 0 })
    w = await mountDetail()
    expect(w.find('[data-test="hero-progress"]').exists()).toBe(false)
    expect(w.text()).toContain('开始阅读')
  })

  it('标签栏按目录章节数显示条数，切换后显示对应标签的内容', async () => {
    const w = await mountDetail()
    expect(w.text()).toContain('第一章')

    const filesTab = w.findAll('button').find((b) => b.text().startsWith('文件'))
    expect(filesTab).toBeTruthy()
    await filesTab!.trigger('click')
    await flushPromises()

    // 「文件」标签的内容：文件名 + 大小（1 KB）
    expect(w.text()).toContain('三体.epub')
    expect(w.text()).toContain('1 KB')
  })

  /**
   * 「阅读日志」标签是第 63 期 3/6 加的第 7 个标签，它**自取数据**（`bookReadingStats`
   * / `readingAttempts`），不走父级传 props。所以这条用例盯着两件事：
   *
   * 1. 标签真的挂上去了，点得开、有内容；
   * 2. 那两个接口在 `@/lib/api` 的桩里**确实存在**。少了桩不会有崩溃，只会让
   *    `load()` 的 `catch` 把 TypeError 转成「阅读记录加载失败」—— 一个看起来像
   *    真故障的假故障（这正是本文件开头那条「桩要一次给齐」的教训）。
   */
  it('「阅读日志」标签点得开，且自取数据没被漏掉的桩挡住', async () => {
    const w = await mountDetail()
    // `active: false` ⇒ 一个请求都不发（详情页是高频入口，这是刻意的）
    expect(m.bookReadingStats).not.toHaveBeenCalled()

    const btn = w.findAll('button').find((b) => b.text().startsWith('阅读日志'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    expect(m.bookReadingStats).toHaveBeenCalledWith(BOOK_ID)
    expect(w.text()).toContain('还没有阅读记录')   // 默认桩 = 这本书没读过
    expect(w.text()).not.toContain('阅读记录加载失败')
  })

  it('详情拉取失败时给出错误提示，而不是静默渲染成一本空书', async () => {
    m.bookDetail.mockRejectedValue(new Error('后端连不上'))
    const w = await mountDetail()

    // 书架缓存里还有这张卡，所以页面照常渲染 —— 但必须显式说出详情没拿到，
    // 否则「没有简介 / 没有章节 / 没有文件」会被读成「这本书本来就是空的」
    expect(w.text()).toContain('详情加载失败')
    expect(w.text()).toContain('后端连不上')
    expect(w.text()).toContain('重试')
    // 列表里那本书是真的：标题留着，不是整页换成「找不到这本书」
    expect(w.text()).toContain('三体')
    expect(w.text()).not.toContain('找不到这本书')
  })

  it('详情拉取失败且书架列表里也没有这本书时，才说「找不到」', async () => {
    m.bookDetail.mockRejectedValue(new Error('后端连不上'))
    m.books.mockResolvedValue({ items: [], total: 0 })
    const w = await mountDetail()

    // detailError 非空 ⇒ 仍是「加载失败」态（第 49 期的判据：失败与「没有」要分开）
    expect(w.text()).toContain('这本书加载失败')
    expect(w.text()).not.toContain('找不到这本书')
  })
})
