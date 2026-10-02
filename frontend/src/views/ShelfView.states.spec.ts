import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api, type BookCard } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import ShelfView from '@/views/ShelfView.vue'

/**
 * 书库落地页**加载 / 失败 / 空 三态**（第 88 期）。
 *
 * 这一页此前在加载期**没有任何反馈**：数据还在路上时 `sorted.length` 就是 0，
 * 页面直接落进 `EmptyState`「这个书架还是空的 / 换个入口看看…」——**数据在路上，
 * 却告诉用户没有书**（用户症状：「一直显示空 / 等很久」）。而且加载**失败**也被
 * 同一段空态吞掉，用户完全不知道是网络挂了。
 *
 * 两种都是**谎报数据状态**，且都不会报错、不会崩，只是把人往错的方向引，
 * 所以用 spec 把「三态互斥」钉死：
 *   · 加载中 ⇒ 骨架（且**不**显示空态）；
 *   · 失败   ⇒ 错误态 + 重试（且**不**显示空态、`loaded` 保持 false）；
 *   · 真的没数据 ⇒ 才显示空态。
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
    collections: vi.fn(),
    librariesScanState: vi.fn(),
  },
  // 用「真实语义」的简易版：有 message 就回 message（好断言「原因显示出来了」）
  apiErrorMessage: (e: unknown, fallback: string) =>
    e instanceof Error && e.message ? e.message : fallback,
}))

const m = {
  books: vi.mocked(api.books),
  readingThresholds: vi.mocked(api.readingThresholds),
}

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
    issues: [],
    library_id: 'lib',
    ...over,
  }
}

let router: Router
const mounted: VueWrapper[] = []

async function mountShelf(): Promise<VueWrapper> {
  setActivePinia(createPinia())
  const w = mount(ShelfView, { global: { plugins: [router] } })
  mounted.push(w)
  await flushPromises()
  return w
}

beforeEach(async () => {
  localStorage.clear()
  m.readingThresholds.mockResolvedValue({ library_id: '', started: 0, finished: 99.5 })
  vi.mocked(api.bookMoveBatches).mockResolvedValue({ items: [] })
  vi.mocked(api.collections).mockResolvedValue({ items: [] })
  vi.mocked(api.librariesScanState).mockResolvedValue({ items: [] })

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'shelf', component: { template: '<div />' } },
      { path: '/book/:id', name: 'book', component: { template: '<div />' } },
      { path: '/read/:id', name: 'read', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
})

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('ShelfView · 加载 / 失败 / 空 三态（第 88 期）', () => {
  it('数据未到时显示骨架，且**不**显示「这个书架还是空的」', async () => {
    m.books.mockReturnValue(new Promise(() => {})) // 永不 resolve：停在加载中
    const w = await mountShelf()

    expect(w.find('[data-shelf-skeleton]').exists()).toBe(true)
    expect(w.text()).not.toContain('这个书架还是空的')
  })

  it('加载成功 → 骨架消失、书出现', async () => {
    m.books.mockResolvedValue({ items: [makeBook()], total: 1 })
    const w = await mountShelf()

    expect(w.find('[data-shelf-skeleton]').exists()).toBe(false)
    expect(w.text()).toContain('三体')
  })

  it('加载失败 → 显示错误态（含原因），而不是空书架；且 loaded 保持 false', async () => {
    m.books.mockRejectedValue(new Error('网络错误：无法连接到服务器'))
    const w = await mountShelf()

    expect(w.text()).toContain('书库加载失败')
    expect(w.text()).toContain('网络错误：无法连接到服务器')
    expect(w.text()).not.toContain('这个书架还是空的')
    // ⚠️ 失败绝不能把 loaded 置真，否则之后永远短路、再也不重拉
    expect(useLibraryStore().loaded).toBe(false)
  })

  it('错误态点「重试」→ 重新拉取，成功后就地恢复成书架', async () => {
    m.books.mockRejectedValueOnce(new Error('boom'))
    const w = await mountShelf()
    expect(w.text()).toContain('书库加载失败')

    m.books.mockResolvedValue({ items: [makeBook()], total: 1 })
    const retry = w.findAll('button').find((b) => b.text().trim() === '重试')
    expect(retry, '错误态里找不到「重试」按钮').toBeTruthy()
    await retry!.trigger('click')
    await flushPromises()

    expect(w.text()).not.toContain('书库加载失败')
    expect(w.text()).toContain('三体')
    expect(m.books).toHaveBeenCalledTimes(2)
  })

  it('真的一本书都没有时，才显示空态', async () => {
    m.books.mockResolvedValue({ items: [], total: 0 })
    const w = await mountShelf()

    expect(w.find('[data-shelf-skeleton]').exists()).toBe(false)
    expect(w.text()).not.toContain('书库加载失败')
    expect(w.text()).toContain('这个书架还是空的')
  })
})
