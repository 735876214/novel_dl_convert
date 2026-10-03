import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type BookCard } from '@/lib/api'
import { AUTO_CONTINUE_MAX_PAGES, BOOKS_PAGE_SIZE, useLibraryStore } from '@/stores/library'

/**
 * 书库列表的**分页 / 无限滚动**（第 88 期 C 批；本批修正后）。
 *
 * 修正的起因：C 批把分页状态直接建在**共享的** `books` 上，于是所有读 `library.books`
 * 的其它消费方（侧栏「全部书库」计数、仪表盘书架行 / 部件、BrowseView、SmartScopesView…）
 * 只看得到**已加载的前缀**（600 本的库被显示成 120 本）。既有用例覆盖不到，真实使用却一眼可见。
 *
 * 修正后两条路各归各、互不阻塞：
 *   · `loadBooks()`  —— **全量**（`api.books()` 不带 limit ⇒ 服务端整份返回），共享真值源；
 *   · `loadShelfFirstPage()` / `loadMoreShelfBooks()` —— 书架页**自己**的分页源
 *     （`shelfLoadedBooks` / `shelfTotal` / `shelfHasMore` / `shelfLoadingMore` …）。
 *
 * 这一层的失效方式全是**静默**的，都不会报错、不会崩，只会让用户看到的书少一截或看着乱：
 *   · 累计没做对 ⇒ 翻页后**丢页**（少了中间的几十本，界面上没有任何异常）；
 *   · 去重没做 ⇒ 同一本书出现**两张卡**；
 *   · `shelfHasMore` 边界写错 ⇒ 要么永远显示「加载更多」却拉不到东西，要么没拉完就停；
 *   · 续拉 / 首页失败把 `loaded` / `shelfLoaded` 置真 ⇒ 之后**永远短路不再拉**（B 批已立过的纪律）；
 *   · 分页污染了共享 `books` ⇒ 读它的其它消费方只看到前缀（本批修的就是这条）；
 *   · 排序 / 筛选变化不重置续拉预算 ⇒ 新筛选**永远**找不到排在后面的书。
 * 故逐条钉住。
 *
 * `@/lib/api` 整体替换：只关心 store 对「拉取结果」的反应，不关心 HTTP 细节。
 */
vi.mock('@/lib/api', () => ({
  api: {
    books: vi.fn(),
    readingThresholds: vi.fn().mockResolvedValue({ library_id: '', started: 0, finished: 99.5 }),
  },
}))

const mockBooks = vi.mocked(api.books)

type BooksResp = Awaited<ReturnType<typeof api.books>>

/** 造一本**字段齐全**的卡片（不做 `as` 强转：接口加字段时让 `vue-tsc` 报出来）。 */
function makeBook(id: string): BookCard {
  return {
    id,
    name: `${id}.epub`,
    title: id,
    author: '无名',
    series: '',
    has_cover: false,
    format: 'EPUB',
    size: 1,
    mtime: 0,
    c1: 'oklch(0.9 0 0)',
    c2: 'oklch(0.8 0 0)',
    tags: [],
    narrators: [],
    year: '',
    publisher: '',
    isbn: '',
    language: 'zh',
    issues: [],
    library_id: 'lib1',
  }
}

/** 造一个「按 offset/limit 真切片」的假服务端：共 total 本、顺序稳定（b0000, b0001…）。 */
function fakeServer(total: number) {
  const all = Array.from({ length: total }, (_, i) => makeBook(`b${String(i).padStart(4, '0')}`))
  return (opts?: { limit?: number; offset?: number }): Promise<BooksResp> => {
    const off = opts?.offset ?? 0
    const lim = opts?.limit ?? total
    const items = all.slice(off, off + lim)
    return Promise.resolve({ items, total, has_more: off + items.length < total, scanning: [] })
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  mockBooks.mockReset()
})

describe('library store · 分页（第 88 期 C 批；修正后）', () => {
  it('loadBooks 拉**全量**（不带 limit/offset ⇒ 服务端整份返回），共享 `books` 不再被切片', async () => {
    mockBooks.mockImplementation(fakeServer(1000))
    const lib = useLibraryStore()

    await lib.loadBooks()

    expect(lib.books.length).toBe(1000)
    expect(lib.loaded).toBe(true)
    // ⚠️ 关键回归点：**一个分页参数都不能带** —— 带上就会让读 `books` 的其它消费方只见前缀。
    expect(mockBooks.mock.calls[0]).toEqual([])
  })

  it('loadShelfFirstPage 只拉**第一页**，记录 shelfTotal / shelfHasMore，偏移量为 0；且**不碰**共享 `books`/`loaded`', async () => {
    mockBooks.mockImplementation(fakeServer(1000))
    const lib = useLibraryStore()

    await lib.loadShelfFirstPage()

    expect(lib.shelfLoadedBooks.length).toBe(BOOKS_PAGE_SIZE)
    expect(lib.shelfTotal).toBe(1000)
    expect(lib.shelfHasMore).toBe(true)
    expect(lib.shelfLoaded).toBe(true)
    // 书架首页加载是**另一条路**：不许顺手把全量 `books` / `loaded` 也改掉
    expect(lib.books.length).toBe(0)
    expect(lib.loaded).toBe(false)
    expect(mockBooks).toHaveBeenNthCalledWith(1, { limit: BOOKS_PAGE_SIZE, offset: 0 })
  })

  it('loadMoreShelfBooks 追加下一页：顺序保持、无重复、偏移量按已收到条数推进', async () => {
    mockBooks.mockImplementation(fakeServer(BOOKS_PAGE_SIZE * 2 + 5))
    const lib = useLibraryStore()

    await lib.loadShelfFirstPage()
    await lib.loadMoreShelfBooks()
    expect(lib.shelfLoadedBooks.length).toBe(BOOKS_PAGE_SIZE * 2)
    expect(mockBooks).toHaveBeenNthCalledWith(2, { limit: BOOKS_PAGE_SIZE, offset: BOOKS_PAGE_SIZE })

    await lib.loadMoreShelfBooks()
    expect(lib.shelfLoadedBooks.length).toBe(BOOKS_PAGE_SIZE * 2 + 5)
    expect(lib.shelfHasMore).toBe(false)

    // 顺序 = 服务端顺序；且没有重复 id（去重 / 累计都对了）
    expect(lib.shelfLoadedBooks[0].id).toBe('b0000')
    expect(lib.shelfLoadedBooks[1].id).toBe('b0001')
    expect(lib.shelfLoadedBooks[lib.shelfLoadedBooks.length - 1].id).toBe(
      `b${String(BOOKS_PAGE_SIZE * 2 + 4).padStart(4, '0')}`,
    )
    expect(new Set(lib.shelfLoadedBooks.map((b) => b.id)).size).toBe(lib.shelfLoadedBooks.length)
  })

  it('shelfHasMore 边界：正好读完 ⇒ false，且**不再多发请求**', async () => {
    mockBooks.mockImplementation(fakeServer(BOOKS_PAGE_SIZE))
    const lib = useLibraryStore()

    await lib.loadShelfFirstPage()
    expect(lib.shelfLoadedBooks.length).toBe(BOOKS_PAGE_SIZE)
    expect(lib.shelfTotal).toBe(BOOKS_PAGE_SIZE)
    expect(lib.shelfHasMore).toBe(false)

    const calls = mockBooks.mock.calls.length
    await lib.loadMoreShelfBooks()
    expect(mockBooks.mock.calls.length).toBe(calls) // 没有更多就不该再打请求
  })

  it('服务端若给了重叠页，按 id 去重（列表里不出现两张同样的卡）', async () => {
    mockBooks
      .mockResolvedValueOnce({ items: [makeBook('b0'), makeBook('b1')], total: 4, has_more: true, scanning: [] })
      // 第二页**故意**把 b1 又给一遍（模拟翻页期间书库被重扫）
      .mockResolvedValueOnce({ items: [makeBook('b1'), makeBook('b2'), makeBook('b3')], total: 4, has_more: false, scanning: [] })
    const lib = useLibraryStore()

    await lib.loadShelfFirstPage()
    await lib.loadMoreShelfBooks()

    expect(lib.shelfLoadedBooks.map((b) => b.id)).toEqual(['b0', 'b1', 'b2', 'b3'])
  })

  it('旧后端不带 has_more 时，用「总数 vs 已收到」兜底推导', async () => {
    mockBooks.mockResolvedValueOnce({ items: [makeBook('b0')], total: 3, scanning: [] })
    const lib = useLibraryStore()

    await lib.loadShelfFirstPage()

    expect(lib.shelfHasMore).toBe(true) // 1 < 3 ⇒ 还有
  })

  it('loadMoreShelfBooks 失败：写入 booksError，但**不清空已加载页、不改 shelfLoaded / loaded**', async () => {
    mockBooks.mockResolvedValueOnce({ items: [makeBook('b0')], total: 3, has_more: true, scanning: [] })
    const lib = useLibraryStore()
    await lib.loadShelfFirstPage()
    expect(lib.shelfLoaded).toBe(true)

    mockBooks.mockRejectedValueOnce(new Error('boom'))
    await lib.loadMoreShelfBooks()

    expect(lib.booksError).toBe('boom')
    expect(lib.shelfLoaded).toBe(true) // ⚠️ 不因续拉失败而回退
    expect(lib.loaded).toBe(false) // 全量那条路没被误置
    expect(lib.shelfLoadingMore).toBe(false) // 单飞闸 / 加载态都复位了
    expect(lib.shelfLoadedBooks.map((b) => b.id)).toEqual(['b0']) // 已有数据不丢
  })

  it('loadShelfFirstPage 失败：写入 booksError，且 **shelfLoaded / loaded 都保持 false**（B 批纪律）', async () => {
    mockBooks.mockRejectedValueOnce(new Error('网络错误：无法连接到服务器'))
    const lib = useLibraryStore()

    await lib.loadShelfFirstPage()

    expect(lib.booksError).toBe('网络错误：无法连接到服务器')
    expect(lib.shelfLoaded).toBe(false) // 失败绝不置真，否则之后永远短路
    expect(lib.loaded).toBe(false) // 也不许顺手把全量那条路置真
  })

  it('自动续拉受上限约束；排序 / 筛选变化（resetShelfQuery）把预算归零', async () => {
    mockBooks.mockImplementation(fakeServer(1000))
    const lib = useLibraryStore()
    await lib.loadShelfFirstPage()

    // 连拉直到上限：正好 AUTO_CONTINUE_MAX_PAGES 页
    let advanced = 0
    while (await lib.autoLoadMoreShelf()) advanced += 1
    expect(advanced).toBe(AUTO_CONTINUE_MAX_PAGES)
    expect(lib.shelfContinuedPages).toBe(AUTO_CONTINUE_MAX_PAGES)
    expect(await lib.autoLoadMoreShelf()).toBe(false) // 到顶后不再自动拉

    // 排序 / 筛选一变 ⇒ 预算归零 ⇒ 新口径又能自动续拉
    lib.resetShelfQuery()
    expect(lib.shelfContinuedPages).toBe(0)
    expect(await lib.autoLoadMoreShelf()).toBe(true)
  })
})
