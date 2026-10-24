import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api, type BookCard, type BookDetail } from '@/lib/api'
import { useBookMenu } from '@/lib/bookMenu'
import { useShelfPrefsStore, type ShelfView as ViewKind } from '@/stores/shelfPrefs'
import ShelfView from '@/views/ShelfView.vue'

/**
 * 书架的**接线**哨兵（第 64 期 2/3）。
 *
 * 这一页直到本期才有 spec，而本期在它身上动了三处（网格卡结构重构 + 三个视图各接一个 ⋮），
 * 都属于「坏了在功能上几乎看不出来」的那一类：
 *
 * - 漏接一个视图 ⇒ 那个视图里**没有 ⋮ 入口**，用户只会以为「这个视图不支持」，不会报错；
 * - 系列折叠行误接上 ⋮ ⇒ 菜单里每一项都是单本书的动词（删除 / 状态 / 收藏），
 *   挂到系列行上点下去会删掉整个系列，比没有入口危险得多。
 *
 * 所以这里的核心断言是**触发器数量**：`[data-book-menu-trigger]` 必须正好等于
 * 「该视图里出现的单本书行数」，三视图各验一遍。数量比外观更能钉住这两件事。
 *
 * `@/lib/api` 整体替换（同 `AnnotationsView.spec.ts` 的理由：桩要一次给齐，
 * 少一个会在 `onMounted` 里被 `catch` 吞掉，用例最后以「找不到元素」的形式报错，
 * 离真正的原因很远）。这里少一个**不会**报错、只会渲染得少一点，更难判 —— 更要给齐。
 */
vi.mock('@/lib/api', () => ({
  api: {
    books: vi.fn(),
    readingThresholds: vi.fn(),
    bookMoveBatches: vi.fn(),
    bookDetail: vi.fn(),
    deleteBook: vi.fn(),
    collections: vi.fn(),
    downloadUrl: vi.fn((name: string) => `/download/${name}`),
    coverUrl: vi.fn((id: string) => `/api/books/${id}/cover`),
  },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const m = {
  books: vi.mocked(api.books),
  readingThresholds: vi.mocked(api.readingThresholds),
  bookMoveBatches: vi.mocked(api.bookMoveBatches),
  bookDetail: vi.mocked(api.bookDetail),
  collections: vi.mocked(api.collections),
}

// ---------------- 夹具 ----------------

function makeBook(over: Partial<BookCard> = {}): BookCard {
  return {
    id: 'lib$a',
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
    publisher: '',
    isbn: '',
    language: 'zh',
    description: '',
    issues: [],
    library_id: 'lib',
    ...over,
  }
}

/**
 * 三本书：**同系列两本 + 无系列一本**。
 * 这个形状同时喂到两个判据上：折叠时「2 本 → 1 行」，不折叠时「3 行」。
 */
const SHELF: BookCard[] = [
  makeBook({ id: 'lib$a', title: '三体', name: '三体/三体 #1.epub', series: '三体', series_index: '1' }),
  makeBook({ id: 'lib$b', title: '三体Ⅱ 黑暗森林', name: '三体/三体 #2.epub', series: '三体', series_index: '2' }),
  makeBook({ id: 'lib$c', title: '球状闪电', name: '球状闪电.epub' }),
]

const STANDALONE = '球状闪电'

function makeDetail(b: BookCard): BookDetail {
  return { ...b, chapters: [], files: [{ name: b.name, format: b.format, size: b.size, mtime: b.mtime }] }
}

// ---------------- 挂载 ----------------

let router: Router
const mounted: VueWrapper[] = []

async function mountShelf(view: ViewKind, collapseSeries: boolean): Promise<VueWrapper> {
  setActivePinia(createPinia())
  // 偏好落 localStorage（同一文件内跨用例残留）⇒ 每次挂载都**显式**写一遍，
  // 不依赖上一轮的残值
  useShelfPrefsStore().patch({ view, collapseSeries })
  useBookMenu().close()

  const w = mount(ShelfView, { global: { plugins: [router] } })
  mounted.push(w)
  await flushPromises()
  return w
}

function triggerCount(w: VueWrapper): number {
  return w.findAll('[data-book-menu-trigger]').length
}

beforeEach(async () => {
  localStorage.clear()
  m.books.mockResolvedValue({ items: SHELF, total: SHELF.length })
  m.readingThresholds.mockResolvedValue({ library_id: '', started: 0, finished: 99.5 })
  m.bookMoveBatches.mockResolvedValue({ items: [] })
  m.collections.mockResolvedValue({ items: [] })
  m.bookDetail.mockImplementation(async (id: string) => makeDetail(SHELF.find((b) => b.id === id) as BookCard))

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'shelf', component: { template: '<div />' } },
      { path: '/book/:id', name: 'book', component: { template: '<div />' } },
      { path: '/read/:id', name: 'read', component: { template: '<div />' } },
      { path: '/listen/:id', name: 'listen', component: { template: '<div />' } },
      { path: '/series/:name', name: 'series-detail', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
})

afterEach(() => {
  // ⚠️ 先 unmount 再扫 body。`DropdownMenu` 的 Teleport 目标就是 body，
  // 直接清空 body 会把还活着的实例的 DOM 连根拔掉，之后任何一次 patch 都会在
  // 「insertBefore of null」上炸 —— 症状是**后续每个用例都红**、报错却指向别的用例。
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

// ---------------- 用例 ----------------

const VIEWS: ViewKind[] = ['grid', 'list', 'table']

describe('ShelfView：三个视图的 ⋮ 入口', () => {
  for (const view of VIEWS) {
    it(`${view}：不折叠时 3 本各一个 ⋮，折叠后系列行不给 ⋮（只剩 1 个）`, async () => {
      const expanded = await mountShelf(view, false)
      expect(triggerCount(expanded)).toBe(3)
      expanded.unmount()

      const collapsed = await mountShelf(view, true)
      // 2 本同系列合成一行 + 1 本独立 = 两行，其中系列行**不给**菜单
      expect(triggerCount(collapsed)).toBe(1)
      // 留下的那个必须是那本独立的书，不是系列行的代表本
      expect(collapsed.text()).toContain(STANDALONE)
    })
  }

  it('折叠开关一改，入口数立刻跟着变（少接一个视图时这条会露馅）', async () => {
    const w = await mountShelf('grid', false)
    const prefs = useShelfPrefsStore()
    expect(triggerCount(w)).toBe(3)

    prefs.patch({ collapseSeries: true })
    await flushPromises()
    expect(triggerCount(w)).toBe(1)

    prefs.patch({ collapseSeries: false })
    await flushPromises()
    expect(triggerCount(w)).toBe(3)
  })
})

describe('ShelfView：⋮ 与快速预览的接线', () => {
  it('点 ⋮ 里的「快速预览」打开浮层，浮层里是这本书', async () => {
    const w = await mountShelf('grid', true) // 只留一个 ⋮，定位无歧义
    expect(w.find('[role="dialog"]').exists()).toBe(false)

    await w.find('[data-book-menu-trigger]').trigger('click')
    await flushPromises()
    // 面板 Teleport 到了 body，不在 wrapper 子树里
    expect(document.body.querySelector('[data-book-menu-panel]')).not.toBeNull()

    const item = Array.from(document.body.querySelectorAll<HTMLElement>('[role="menuitem"]')).find(
      (b) => (b.textContent || '').trim() === '快速预览',
    )
    item?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()

    const dialog = w.find('[role="dialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain(STANDALONE)
    // 浮层一开，面板就该收了 —— 不然它压在浮层上面
    expect(document.body.querySelector('[data-book-menu-panel]')).toBeNull()
  })

  it('浮层能关掉（关掉后回到没有浮层的书架）', async () => {
    const w = await mountShelf('grid', true)
    await w.find('[data-book-menu-trigger]').trigger('click')
    await flushPromises()
    const item = Array.from(document.body.querySelectorAll<HTMLElement>('[role="menuitem"]')).find(
      (b) => (b.textContent || '').trim() === '快速预览',
    )
    item?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(w.find('[role="dialog"]').exists()).toBe(true)

    await w.find('[aria-label="关闭预览"]').trigger('click')
    await flushPromises()
    expect(w.find('[role="dialog"]').exists()).toBe(false)
  })
})

/**
 * 系列折叠行的**标题口径**（第 152 期）。
 *
 * 这一族坏起来完全静默：`Row.book` 是**代表本**（决定封面画哪一张），它的 `title`
 * 只代表那一册。表格视图曾经直接拿它当书名列，于是同一行在网格里叫系列名、
 * 在表格里叫 `Vol.04` —— 用户看到的是一堆「Vol.04 没合并」，而数据库里 series 是对的
 * （实测那 42 本 `Vol.NN` 全都带正确的系列名与册号）。
 *
 * 所以三个视图 + 首字母分桶都要钉同一句话：**折叠行显示的是系列名，不是某一册的文件名**。
 */
const SERIES = 'Angel Beats! -The Last Operation-'
/** 代表本（按入库时间倒序首次出现的那本）文件名就是纯卷号 —— 用户库里真实存在 */
const VOL_SHELF: BookCard[] = [
  makeBook({
    id: 'lib$v4',
    title: 'Vol.04',
    name: `${SERIES}/Vol.04.zip`,
    series: SERIES,
    series_index: '4',
    format: 'CBZ',
    pages: 190,
    mtime: 1700000400,
  }),
  makeBook({
    id: 'lib$v3',
    title: 'Vol.03',
    name: `${SERIES}/Vol.03.zip`,
    series: SERIES,
    series_index: '3',
    format: 'CBZ',
    pages: 180,
    mtime: 1700000300,
  }),
]

describe('ShelfView：折叠行显示系列名（不是代表本的 Vol.NN）', () => {
  for (const view of ['grid', 'list', 'table'] as ViewKind[]) {
    it(`${view}：标题是系列名，且不出现代表本的文件名 Vol.04`, async () => {
      m.books.mockResolvedValue({ items: VOL_SHELF, total: VOL_SHELF.length })
      const w = await mountShelf(view, true)
      expect(w.text()).toContain(SERIES)
      expect(w.text()).not.toContain('Vol.04')
      expect(w.text()).not.toContain('Vol.03')
    })
  }

  it('首字母分桶跟着系列名走（A，而不是代表本的 V）', async () => {
    m.books.mockResolvedValue({ items: VOL_SHELF, total: VOL_SHELF.length })
    const w = await mountShelf('grid', true)
    const buckets = w.findAll('[data-bucket]').map((el) => el.attributes('data-bucket'))
    expect(buckets).toContain('A')
    expect(buckets).not.toContain('V')
  })

  it('表格的系列头行：格式 / 页数 / 进度 / 评分四列留空（不拿代表本的数冒充整组）', async () => {
    m.books.mockResolvedValue({ items: VOL_SHELF, total: VOL_SHELF.length })
    const w = await mountShelf('table', true)
    const cells = w.findAll('tbody tr').at(0)?.findAll('td') ?? []
    const text = cells.map((c) => (c.text() || '').trim())
    // 列序：书名 / 作者 / 系列 / 格式 / 页数 / 进度 / 评分 / 操作
    expect(text[3]).toBe('—')
    expect(text[4]).toBe('—')
    expect(text[5]).toBe('—')
    expect(text[6]).toBe('—')
  })

  it('展开系列后成员行仍是各自的册名（系列名只属于折叠行）', async () => {
    m.books.mockResolvedValue({ items: VOL_SHELF, total: VOL_SHELF.length })
    const w = await mountShelf('table', true)
    await w.findAll('tbody tr').at(0)?.findAll('button')[0].trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Vol.03')
    expect(w.text()).toContain('Vol.04')
  })
})

/**
 * 折叠行的**点击落点**（第 152 期）。
 *
 * 用户原话：「折叠系列后，文件里面只有一本书，点击开始阅读不能从第一册开始读，不能看目录」。
 * 真因是折叠行点了之后打开的是**代表本**（`rows` 里挑来画封面的那一册，常常是 `Vol.04`）的
 * 详情页 —— 那页只有一本书、没有目录、也没有「从第一册开始」。
 *
 * 所以这里钉的是三条落点：折叠行 → **系列详情**（目录 + 开始阅读）；展开后的成员行 →
 * 那一册自己；系列名当路径参数必须编码（`：` `☆` `/` 都在真实系列名里出现过）。
 */
describe('ShelfView：折叠行点进去是系列详情，成员行点进去是那一册', () => {
  const seriesUrl = `/series/${encodeURIComponent(SERIES)}`

  async function clickSeriesRow(view: ViewKind): Promise<VueWrapper> {
    m.books.mockResolvedValue({ items: VOL_SHELF, total: VOL_SHELF.length })
    const w = await mountShelf(view, true)
    const target =
      view === 'grid'
        ? w.find('[data-bucket] button')
        : view === 'list'
          ? w.find('[data-bucket]')
          : w.find('tbody tr')
    await target.trigger('click')
    await flushPromises()
    return w
  }

  for (const view of ['grid', 'list', 'table'] as ViewKind[]) {
    it(`${view}：点折叠行 → 系列详情（不是某一册的详情）`, async () => {
      await clickSeriesRow(view)
      expect(router.currentRoute.value.path).toBe(seriesUrl)
    })
  }

  it('展开后点成员行 → 那一册的详情（不是系列）', async () => {
    m.books.mockResolvedValue({ items: VOL_SHELF, total: VOL_SHELF.length })
    const w = await mountShelf('table', true)
    await w.findAll('tbody tr').at(0)?.findAll('button')[0].trigger('click') // 展开
    await flushPromises()
    // 成员行按系列序号升序：Vol.03 在前
    await w.findAll('tbody tr').at(0)!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/book/lib$v3')
  })

  it('缩略图点击 = 直接阅读时，折叠行**仍然**进系列详情（没有「一册」可读）', async () => {
    m.books.mockResolvedValue({ items: VOL_SHELF, total: VOL_SHELF.length })
    const w = await mountShelf('grid', true)
    useShelfPrefsStore().patch({ thumbnailClick: 'reader' })
    await flushPromises()
    await w.find('[data-bucket] button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(seriesUrl)
  })
})

/**
 * 表格视图的系列行**多选口径** + 折叠卡的**册数**（第 152 期审计抓出来的两处）。
 *
 * 两处都坏得静默：
 * - 头行带勾选框 ⇒ 勾上只选中代表本那一册（用户以为选中了整个系列），而「全选」又把它排除；
 *   展开后首册行带 toggle ⇒ 那本书丢掉 ⋮、多出一枚「系列 N 册」角标，「全选」每系列再漏 1 本。
 * - 折叠后「N 册」只数**已加载**的分页（首屏 120 本）⇒ 4 册的系列显示成「3 册」，
 *   滑到底才补齐 —— 卡片上的数字在那之前就是错的。
 */
describe('ShelfView：表格多选口径与折叠卡的册数', () => {
  async function enterSelect(w: VueWrapper): Promise<void> {
    const btn = w.findAll('button').find((b) => (b.text() || '').trim() === '多选')
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()
  }

  async function mountTableCollapsed(): Promise<VueWrapper> {
    m.books.mockResolvedValue({ items: VOL_SHELF, total: VOL_SHELF.length })
    return mountShelf('table', true)
  }

  it('多选态自动展开系列（表格同样）：每一册都能勾选，且不会去勾「系列头」', async () => {
    const w = await mountTableCollapsed()
    // 折叠 + 非多选：勾选列整列都不渲染
    expect(w.findAll('tbody input[type="checkbox"]').length).toBe(0)

    await enterSelect(w)
    // 第 152 期审计：多选态不折叠 —— 否则「全选」只覆盖没有系列的那几本
    expect(w.findAll('tbody input[type="checkbox"]').length).toBe(VOL_SHELF.length)
    expect(w.findAll('tbody tr').length).toBe(VOL_SHELF.length)
  })

  it('展开后首册行仍有 ⋮ 与「收起」，且不再挂「系列 N 册」角标', async () => {
    const w = await mountTableCollapsed()
    await w.findAll('tbody tr').at(0)!.findAll('button')
      .find((b) => (b.text() || '').includes('展开'))!.trigger('click')
    await flushPromises()

    const first = w.findAll('tbody tr').at(0)!
    expect(first.find('[data-book-menu-trigger]').exists()).toBe(true)
    expect(first.text()).toContain('收起')
    expect(first.text()).not.toContain(`系列 ${VOL_SHELF.length} 册`)
  })

  it('折叠开启时把分页续拉到底 —— 「N 册」不能只数首屏（120 本）', async () => {
    // 122 本：前 120 本没有系列，同系列的两本落在第二页
    const many: BookCard[] = Array.from({ length: 120 }, (_, i) =>
      makeBook({ id: `lib$p${i}`, title: `书${i}`, name: `书${i}.epub`, mtime: 1700000000 - i }))
    many.push(makeBook({ id: 'lib$s1', title: 'Vol.01', name: 'S/Vol.01.zip', series: 'S', series_index: '1', mtime: 2 }))
    many.push(makeBook({ id: 'lib$s2', title: 'Vol.02', name: 'S/Vol.02.zip', series: 'S', series_index: '2', mtime: 1 }))
    m.books.mockImplementation(async (opts?: { limit?: number; offset?: number }) => {
      const off = opts?.offset ?? 0
      const lim = opts?.limit ?? many.length
      const items = many.slice(off, off + lim)
      return { items, total: many.length, has_more: off + items.length < many.length }
    })

    const w = await mountShelf('grid', true)
    for (let i = 0; i < 6; i++) await flushPromises()
    expect(w.text()).toContain(`${VOL_SHELF.length} 册`)
  })

  it('进入多选后自动展开系列 —— 否则「全选」只能选中没有系列的那几本', async () => {
    m.books.mockResolvedValue({ items: VOL_SHELF, total: VOL_SHELF.length })
    const w = await mountShelf('grid', true)
    expect(w.findAll('[data-bucket]').length).toBe(1) // 折叠：一张系列卡

    await enterSelect(w)
    expect(w.findAll('[data-bucket]').length).toBe(VOL_SHELF.length) // 多选：一册一张，都能勾
    expect(w.findAll('input[type="checkbox"]').length).toBe(VOL_SHELF.length)
  })

  it('只有一册的「系列」当普通书行：有 ⋮、显示自己的书名、没有「1 册」角标', async () => {
    // 真实库里有 25 个单本系列；其中有的系列名本身就是错抽的 `Vol.01` / 作者名
    const SOLO: BookCard[] = [
      makeBook({ id: 'lib$solo', title: '孤单的一本', name: 'Solo/Vol.01.zip', series: 'Solo', series_index: '1', format: 'CBZ' }),
    ]
    m.books.mockResolvedValue({ items: SOLO, total: SOLO.length })
    const w = await mountShelf('grid', true)
    expect(w.text()).toContain('孤单的一本')
    expect(w.text()).not.toContain('1 册')
    expect(w.find('[data-book-menu-trigger]').exists()).toBe(true)
  })
})
