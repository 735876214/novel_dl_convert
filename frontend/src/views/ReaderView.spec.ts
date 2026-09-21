import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api, type BookDetail, type Bookmark, type BookVolume } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import ReaderView from '@/views/ReaderView.vue'

/**
 * `@/lib/api` 整体替换。阅读器的每一次取数都走它，桩要一次给齐 ——
 * 少一个就会在 `onMounted` 里抛，而那个异常会被当成「书籍加载失败」渲染成空态，
 * 用例随后会以「找不到按钮」的形式报错，**离真正的原因很远**。所以宁可多给。
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
    saveProgress: vi.fn(),
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
}

/** 两章的一卷 EPUB —— `total.value` 非空，`startSession()` 才会被调用。 */
function makeChapters(): BookVolume[] {
  return [
    {
      volume: '',
      chapters: [
        { num: 1, index: 0, title: '第一章' },
        { num: 2, index: 1, title: '第二章' },
      ],
    },
  ]
}

function makeBook(over: Partial<BookDetail> = {}): BookDetail {
  return {
    id: 'book-a',
    name: '测试书.epub',
    title: '测试书',
    author: '某人',
    series: '',
    has_cover: false,
    format: 'EPUB',
    size: 1024,
    mtime: 0,
    c1: '',
    c2: '',
    tags: [],
    year: '',
    publisher: '',
    isbn: '',
    language: '',
    description: '',
    issues: [],
    chapters: makeChapters(),
    files: [],
    ...over,
  }
}

function stubApi(book: BookDetail): void {
  m.bookDetail.mockResolvedValue(book)
  m.listAnnotations.mockResolvedValue({ items: [] })
  m.listBookmarks.mockResolvedValue({ items: [], total: 0, trashed: [] })
  m.getProgress.mockResolvedValue({ locator: 0, percent: 0 })
  m.chapter.mockResolvedValue({ index: 0, total: 2, title: '第一章', html: '<p>正文</p>' })
  m.recordSession.mockResolvedValue({ ok: true })
  m.fonts.mockResolvedValue({ items: [], max_bytes: 0, max_count: 0 })
}

/**
 * 挂载阅读器并等它把首屏那串取数走完。
 *
 * `onMounted` 依次 await 了 5 个接口，少 await 一轮就会拿到「加载中」的 DOM。
 */
async function mountReader(bookId = 'book-a'): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/read/:id', name: 'read', component: ReaderView }],
  })
  await router.push(`/read/${bookId}`)
  await router.isReady()

  const wrapper = mount(ReaderView, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('ReaderView · 阅读时长上报（flushSession）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // 只伪造 `Date`，**不**碰 setTimeout/setInterval：
    // 全套假时钟会让 `flushPromises()` 自己挂住（它内部就靠一个 setTimeout 落地）。
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-21T10:00:00Z'))
    // happy-dom 没实现 scrollIntoView；不禁用它会在滚动到章节时抛
    Element.prototype.scrollIntoView = vi.fn()
    stubApi(makeBook())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  /**
   * 这条守的是本仓库**修过两次**的那个 bug。
   *
   * 原实现用 `String(route.params.id)` 取 id：离开阅读器时路由参数**先变空**，
   * 那一刻取到的是 `undefined`，于是发出 `POST /api/books/undefined/session`（404），
   * 而这段时长又被 catch 塞回一个没人再上报的变量 ⇒ **悄悄丢掉**。
   *
   * 驱动面选 `unmount()` 是刻意的：`onBeforeUnmount` → `stopSession()` → `flushSession()`
   * 正是「离开阅读器」这条路本身，不是绕开它去戳内部函数。
   */
  it('离开阅读器时用**已加载那本书**的 id 上报，不发 undefined', async () => {
    const { wrapper } = await mountReader('book-a')
    // 跨过 5 秒门槛（`flushSession` 里 `pendingSeconds < 5` 直接 return）
    vi.setSystemTime(new Date('2026-09-21T10:00:06Z'))

    wrapper.unmount()
    await flushPromises()

    expect(m.recordSession).toHaveBeenCalledTimes(1)
    const [bid, secs] = m.recordSession.mock.calls[0]
    expect(bid).toBe('book-a')
    expect(bid).not.toBe('undefined')
    expect(secs).toBe(6)
  })

  /** 不足 5 秒不上报 —— 阈值是**故意的**，别让翻两页就走一次写库。 */
  it('不足 5 秒不上报', async () => {
    const { wrapper } = await mountReader('book-a')
    vi.setSystemTime(new Date('2026-09-21T10:00:03Z'))

    wrapper.unmount()
    await flushPromises()

    expect(m.recordSession).not.toHaveBeenCalled()
  })

  /** 书还没加载出来就离开 ⇒ 没有 id 可用，宁可**不上报**也不能报一个错的。 */
  it('书未加载成功时不上报（宁可不报，也不报错的）', async () => {
    m.bookDetail.mockRejectedValue(new Error('书籍不存在'))
    const { wrapper } = await mountReader('book-a')
    vi.setSystemTime(new Date('2026-09-21T10:00:30Z'))

    wrapper.unmount()
    await flushPromises()

    expect(m.recordSession).not.toHaveBeenCalled()
  })
})

describe('ReaderView · 工具条书签按钮', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Element.prototype.scrollIntoView = vi.fn()
    stubApi(makeBook())
  })

  const BTN_ADD = 'button[title="在当前位置加书签"]'
  const BTN_REMOVE = 'button[title="移除当前位置的书签"]'

  /**
   * 书签按钮**不受书库能力清单门控**。
   *
   * ⚠️ 这个用例的**前提必须摆对**，否则它是个假绿：`hasFeature()` 的口径是
   * 「清单为空 ⇒ 一律可见，宁多不漏」（`stores/library.ts`），所以**不加载**能力清单时，
   * 就算谁真加了 `v-if="hasFeature('bookmarks')"`，按钮照样渲染，用例照样绿。
   * 必须把清单**加载好、且里面确实没有 `bookmarks`**，这条断言才有分辨力。
   *
   * 而 ReaderView 眼下压根不 import library store —— 阅读是「这本书已经打开了」之后的事，
   * 再拿书库能力拦一次只会造成「明明能读却加不了书签」。这条钉住现状：谁加门控，先红。
   */
  it('书库能力清单里没有 bookmarks 时，书签按钮照常渲染', async () => {
    const lib = useLibraryStore()
    // 已加载、且**不含** bookmarks 的清单 —— 正是「有分辨力」的那个前提
    lib.features = ['annotations']
    lib.librariesLoaded = true

    const { wrapper } = await mountReader()

    expect(wrapper.find(BTN_ADD).exists()).toBe(true)
    // 反向确认：没有退化成「书签不可用」的兜底文案
    expect(wrapper.text()).not.toContain('书签不可用')
  })

  /**
   * 按钮是**开关**：点一下加书签，同一位置再点就是移入垃圾桶，标题跟着状态走。
   *
   * 这里刻意**不硬编锚字符串**：锚是 `章序号:章内比例`（`currentAnchor`），
   * 比例位数由 `ANCHOR_PRECISION` 决定 —— 写死在用例里，改一次精度就假红一次。
   * 改成让 mock 像真服务端那样**把这次传进来的锚存下来**，下一轮列表就取回它，
   * 于是用例验的是「存了再读回来还认得」这条真实往返。
   */
  it('点击加书签后，同一位置再点变成移除（标题随状态切换）', async () => {
    const { wrapper } = await mountReader()
    let saved: Bookmark | null = null
    m.addBookmark.mockImplementation(async (bookId: string, b) => {
      saved = {
        id: 1,
        book_id: bookId,
        anchor: b.anchor,
        chapter: b.chapter,
        percent: b.percent,
        label: b.label ?? '',
        created_at: 0,
        updated_at: 0,
      }
      // 加完之后同一位置已有书签 ⇒ `reloadBookmarks` 取回这一条
      m.listBookmarks.mockResolvedValue({ items: [saved], total: 1, trashed: [] })
      return { ok: true, id: saved.id, created: true, revived: false, applied: true, server: saved }
    })

    await wrapper.find(BTN_ADD).trigger('click')
    await flushPromises()

    expect(m.addBookmark).toHaveBeenCalledTimes(1)
    expect(m.addBookmark.mock.calls[0][0]).toBe('book-a')
    expect(saved).not.toBeNull()

    // 标题随之变成「移除」—— 说明按钮读的是实时状态，不是写死的
    expect(wrapper.find(BTN_REMOVE).exists()).toBe(true)
  })
})
