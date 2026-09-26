import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { api, type BookDetail, type BookVolume } from '@/lib/api'
import ReaderView from '@/views/ReaderView.vue'

/**
 * 第 56 期：多设备进度提示的契约 —— **只提示、绝不静默挪阅读位置**。
 *
 * 判定靠服务端写入时间戳：载入时读到的 `updated_at` 记成本机基准，轮询发现更新的
 * 写入且位置确实不同 ⇒ 渲染一条可点提示；用户点「跳过去」才跳，点「忽略」则不动。
 */
vi.mock('@/lib/api', () => ({
  api: {
    bookDetail: vi.fn(),
    listAnnotations: vi.fn(),
    listBookmarks: vi.fn(),
    getProgress: vi.fn(),
    chapter: vi.fn(),
    recordSession: vi.fn(),
    fonts: vi.fn(),
    addBookmark: vi.fn(),
    deleteBookmark: vi.fn(),
    updateBookmark: vi.fn(),
    setProgress: vi.fn(),
  },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const m = {
  bookDetail: vi.mocked(api.bookDetail),
  listAnnotations: vi.mocked(api.listAnnotations),
  listBookmarks: vi.mocked(api.listBookmarks),
  getProgress: vi.mocked(api.getProgress),
  chapter: vi.mocked(api.chapter),
  recordSession: vi.mocked(api.recordSession),
  fonts: vi.mocked(api.fonts),
  addBookmark: vi.mocked(api.addBookmark),
  setProgress: vi.mocked(api.setProgress),
}

function makeChapters(): BookVolume[] {
  return [{
    volume: '',
    chapters: [
      { num: 1, index: 0, title: '第一章' },
      { num: 2, index: 1, title: '第二章' },
    ],
  }]
}

function makeBook(): BookDetail {
  return {
    id: 'book-a', name: '测试书.epub', title: '测试书', author: '某人', series: '',
    has_cover: false, format: 'EPUB', size: 1024, mtime: 0, c1: '', c2: '',
    tags: [], narrators: [], year: '', publisher: '', isbn: '', language: '',
    description: '', issues: [], chapters: makeChapters(), files: [],
  }
}

async function mountReader(): Promise<VueWrapper> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/read/:id', name: 'read', component: ReaderView }],
  })
  await router.push('/read/book-a')
  await router.isReady()
  const w = mount(ReaderView, { global: { plugins: [router] } })
  await flushPromises()
  return w
}

function buttonByText(w: VueWrapper, text: string) {
  return w.findAll('button').find((b) => b.text() === text)
}

describe('ReaderView · 其他设备进度提示（第 56 期）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // 只伪造 interval（轮询）与 Date：**保留真 setTimeout** —— `flushPromises()` 内部
    // 就靠一个 setTimeout 落地，全套假时钟会让它自己挂住。
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    Element.prototype.scrollIntoView = vi.fn()
    m.bookDetail.mockResolvedValue(makeBook())
    m.listAnnotations.mockResolvedValue({ items: [] })
    m.listBookmarks.mockResolvedValue({ items: [], total: 0, trashed: [] })
    m.chapter.mockResolvedValue({ index: 0, total: 2, title: '第一章', html: '<p>正文</p>' })
    m.recordSession.mockResolvedValue({ ok: true })
    m.fonts.mockResolvedValue({ items: [], max_bytes: 0, max_count: 0 })
    m.setProgress.mockResolvedValue({ ok: true, updated_at: 100 })
    // 载入时读到的进度 = 本机基准（updated_at = 100）
    m.getProgress.mockResolvedValue({ locator: 0, percent: 0, updated_at: 100 })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('轮询发现别的设备写了更新的进度 ⇒ 只提示，绝不自动跳', async () => {
    const w = await mountReader()

    // 别的设备读到第 2 章 50%，时间戳更新
    m.getProgress.mockResolvedValue({ locator: 1, percent: 50, updated_at: 200 })
    vi.advanceTimersByTime(8000)
    await flushPromises()

    expect(w.text()).toContain('其他设备更新了进度')
    expect(w.text()).toContain('第二章')
    // 不自动跳：正文仍停在第 1 章
    expect(m.chapter).toHaveBeenLastCalledWith('book-a', 0)
  })

  it('点「跳过去」才真的跳，并立刻把本机位置写回', async () => {
    const w = await mountReader()
    m.getProgress.mockResolvedValue({ locator: 1, percent: 50, updated_at: 200 })
    vi.advanceTimersByTime(8000)
    await flushPromises()

    await buttonByText(w, '跳过去')!.trigger('click')
    await flushPromises()

    expect(m.chapter).toHaveBeenLastCalledWith('book-a', 1)
    expect(m.setProgress).toHaveBeenCalled()
    expect(w.text()).not.toContain('其他设备更新了进度')
  })

  it('点「忽略」保持本机位置，提示消失', async () => {
    const w = await mountReader()
    m.getProgress.mockResolvedValue({ locator: 1, percent: 50, updated_at: 200 })
    vi.advanceTimersByTime(8000)
    await flushPromises()

    await buttonByText(w, '忽略')!.trigger('click')
    await flushPromises()

    expect(w.text()).not.toContain('其他设备更新了进度')
    expect(m.chapter).toHaveBeenLastCalledWith('book-a', 0)
  })

  it('时间戳没有更新（只是路过同一处）⇒ 不打扰', async () => {
    const w = await mountReader()

    // 同一时间戳、位置也没变
    m.getProgress.mockResolvedValue({ locator: 0, percent: 0, updated_at: 100 })
    vi.advanceTimersByTime(8000)
    await flushPromises()

    expect(w.text()).not.toContain('其他设备更新了进度')
  })
})
