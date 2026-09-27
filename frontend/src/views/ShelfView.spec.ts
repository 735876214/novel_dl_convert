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
  m.bookDetail.mockImplementation(async (id: string) => makeDetail(SHELF.find((b) => b.id === id) as BookCard))

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'shelf', component: { template: '<div />' } },
      { path: '/book/:id', name: 'book', component: { template: '<div />' } },
      { path: '/read/:id', name: 'read', component: { template: '<div />' } },
      { path: '/listen/:id', name: 'listen', component: { template: '<div />' } },
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
