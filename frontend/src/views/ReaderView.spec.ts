import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api, type BookDetail, type Bookmark, type BookVolume } from '@/lib/api'
import { READER_PREFS_KEY } from '@/lib/readerPrefs'
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
    // 第 61 期：进度写入（`setProgress`）与就地回写 store 的用例需要它
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
    narrators: [],
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
  m.setProgress.mockResolvedValue({ ok: true, updated_at: 1000 })
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

describe('ReaderView · 同路由换书（第 36 期观察项 2）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Element.prototype.scrollIntoView = vi.fn()
    stubApi(makeBook())
  })

  /**
   * 第 36 期记录原文：「SPA 内直接改 hash 从一本书的阅读页跳到另一本，正文与 `nf-fixed`
   * 会更新，但**头部书名停在上一本**；整页刷新正常。应用自身导航不走这条，故只记下待复现。」
   * —— 这条用例就是那次的「待复现」。
   *
   * 机制：两条路由都是同一个记录 `/read/:id`，而 `App.vue:138` 是裸 `<RouterView />`
   * （**没有 `:key`**）⇒ 组件**不重新挂载**。而组件里
   * `bookId`（`:37`）是 computed、跟着路由走，
   * `book`（`:39`）却**只在 `onMounted` 里赋值** —— 于是 :857 的 `{{ book.title }}`
   * 停在上一本。正文侧因为 `loadChapter` 直接读 `bookId.value`（`:344`），所以是新的，
   * 这正好解释了原文「正文会更新、书名不更新」那个自相矛盾的现象。
   */
  it('换书后头部书名跟着换，不能停在上一本', async () => {
    m.bookDetail.mockImplementation(async (id: string) =>
      id === 'book-b'
        ? makeBook({ id: 'book-b', title: '第二本' })
        : makeBook({ id: 'book-a', title: '第一本' }),
    )

    const { wrapper, router } = await mountReader('book-a')
    expect(wrapper.text()).toContain('第一本')

    // 同一条路由记录，只换参数 —— 不是重新挂载
    await router.push('/read/book-b')
    await flushPromises()

    expect(wrapper.text()).toContain('第二本')
    expect(wrapper.text()).not.toContain('第一本')
  })

  /**
   * 换书时那一段阅读时长必须结给**上一本**。
   *
   * 这是上面那个 `watch` 里最容易搞反的一处：`flushSession` 读的是 `book.value.id`，
   * 只要把 `stopSession()` 挪到 `await load()` **之后**，这段时长就会记到新书头上 ——
   * 而「书 A 读了 12 秒」被记成「书 B 读了 12 秒」是个**不会报错、也没有任何界面提示**
   * 的错误，事后只能靠人翻阅读统计才看得出来。所以它值得一条专门的用例。
   */
  it('换书时把上一本的时长结给上一本，不记到新书头上', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-21T10:00:00Z'))
    try {
      m.bookDetail.mockImplementation(async (id: string) =>
        id === 'book-b'
          ? makeBook({ id: 'book-b', title: '第二本' })
          : makeBook({ id: 'book-a', title: '第一本' }),
      )

      const { router } = await mountReader('book-a')
      vi.setSystemTime(new Date('2026-09-21T10:00:12Z'))   // 在这本书上读了 12 秒

      await router.push('/read/book-b')
      await flushPromises()

      expect(m.recordSession).toHaveBeenCalledTimes(1)
      const [bid, secs] = m.recordSession.mock.calls[0]
      expect(bid).toBe('book-a')
      expect(secs).toBe(12)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('ReaderView · 目录跳转与滚轮翻页（第 61 期）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Element.prototype.scrollIntoView = vi.fn()
    localStorage.removeItem(READER_PREFS_KEY)
    stubApi(makeBook())
  })

  afterEach(() => {
    localStorage.removeItem(READER_PREFS_KEY)
  })

  /**
   * 滚动容器 = `.reader-content`（article）→ 位移层 → 滚动容器。
   *
   * 滚轮监听是**手动**注册在滚动容器上的（要 `passive: false` 才能 preventDefault），
   * 所以用例必须把事件派发到**那个元素**上；派发到 wrapper 根节点不会冒泡过去。
   */
  function scrollerOf(wrapper: VueWrapper): HTMLElement {
    const art = wrapper.find('.reader-content').element
    return art.parentElement!.parentElement as HTMLElement
  }

  /**
   * 目录跳转必须按 **`flat` 里的位置**走，而不是回查后端 `index`。
   *
   * 后端结构里可能出现没有 `index` 的条目（此处模拟）：`flat` 会跳过它、目录面板的
   * `findIndex(c => c.index === idx)` 却可能因此落空 —— 表现就是「点了没反应」。
   * 位置是同序遍历出来的，天然对齐；无序号条目**不渲染**（而不是渲染一个点了没反应的死项）。
   */
  it('目录按位置跳转：后端 index 有跳号时也不会点不动', async () => {
    stubApi(makeBook({
      chapters: [
        {
          volume: '第一卷',
          chapters: [{ num: 1, index: 0, title: '第一章' }, { num: 2, title: '无序号页' }],
        },
        { volume: '第二卷', chapters: [{ num: 1, index: 7, title: '第七章' }] },
      ],
    }))
    const { wrapper } = await mountReader()

    await wrapper.find('button[title="目录"]').trigger('click')
    expect(wrapper.text()).toContain('第一卷')
    expect(wrapper.text()).not.toContain('无序号页')       // 死项不渲染

    const target = wrapper.findAll('aside button').find((b) => b.text() === '第七章')
    expect(target, '目录里应能找到「第七章」').toBeTruthy()
    await target!.trigger('click')
    await flushPromises()

    expect(m.chapter).toHaveBeenLastCalledWith('book-a', 7)
  })

  /**
   * **慢响应后到不能覆盖后跳的那一章**（第 61 期「目录点了跳错位置」的真实成因之一）。
   *
   * 场景：连点两个目录项，先发的那次响应更慢。没有请求序号守卫时，慢响应落地后会把画面
   * 覆盖回旧章节 —— 界面显示 A、高亮与进度却在 B，而且**没有任何报错**。
   */
  it('连点目录：慢响应后到也不会覆盖后跳的那一章', async () => {
    stubApi(makeBook())
    // 第 0 章永远慢（1.5s 后才有结果），第 1 章立刻返回
    m.chapter.mockImplementation(async (_bid: string, index: number) => {
      if (index === 0) {
        await new Promise((r) => setTimeout(r, 1500))
        return { index: 0, total: 2, title: '第一章', html: '<h1>第一章</h1>' }
      }
      return { index, total: 2, title: '第二章', html: '<h1>第二章</h1>' }
    })
    const { wrapper } = await mountReader()

    await wrapper.find('button[title="目录"]').trigger('click')
    const items = wrapper.findAll('aside button')
    // 第 0 章（慢）+ 第 1 章（快）：先点慢的，再点快的
    await items[0].trigger('click')
    await items[1].trigger('click')
    await vi.waitFor(() => expect(m.chapter).toHaveBeenCalledTimes(3))   // 首屏 + 两次点击
    await new Promise((r) => setTimeout(r, 1700))                        // 等慢响应真的回来
    await flushPromises()

    expect(wrapper.find('.reader-content h1').exists()).toBe(true)
    expect(wrapper.find('.reader-content h1').text()).toBe('第二章')
  })

  /**
   * 进度写完要**就地**回写书库 store（第 61 期「进度实时」）。
   *
   * 这守的是首页「继续阅读」的新鲜度：不重拉整库（几百本一次往返），
   * 只改内存里那一条 —— 用户读完一段切回首页，百分比与排序立刻是新的。
   */
  it('进度写完就地回写书库 store', async () => {
    const lib = useLibraryStore()
    lib.$patch({ books: [makeBook({ id: 'book-a', percent: 12, updated_at: 1 })] })
    localStorage.setItem(READER_PREFS_KEY, JSON.stringify({ mode: 'paged' }))

    const { wrapper } = await mountReader()
    // 翻页模式翻一页 → 越过末页判定 → 切到第 2 章（2 章书 = 50%）
    scrollerOf(wrapper).dispatchEvent(new WheelEvent('wheel', { deltaY: 160, cancelable: true }))
    await flushPromises()
    // 滚动 → onScroll 800ms 去抖后写进度
    scrollerOf(wrapper).dispatchEvent(new Event('scroll'))
    await new Promise((r) => setTimeout(r, 900))
    await flushPromises()

    expect(m.setProgress).toHaveBeenCalled()
    expect(lib.books[0].percent).toBe(50)
    expect(lib.books[0].updated_at).toBe(1000)      // 服务端回传的时间戳
  })

  /**
   * 滚动读到一章末尾 → **自动接上下一章**（第 61 期，用户选的 A）。
   *
   * 「无缝」的全部内容都在这一条里：**下一章必须先已在缓存里**，切换时才不会再发一次请求
   * （不发请求 ⇒ 没有往返等待、没有空白、没有「加载章节…」一闪）。
   * 所以断言的落点是取数次数：首屏那次 + 预取那次 = 2，滚到底**不新增**请求。
   */
  it('滚动到底自动接上下一章，且切换时不再发请求（预取在先）', async () => {
    localStorage.removeItem(READER_PREFS_KEY)     // 默认就是滚动模式
    const { wrapper } = await mountReader()

    expect(m.chapter).toHaveBeenCalledTimes(2)    // 首屏(0) + 预取下一章(1)

    // happy-dom 没有布局：直接给出「已滚到底」的尺寸
    const el = scrollerOf(wrapper)
    Object.defineProperty(el, 'scrollHeight', { value: 2000, configurable: true })
    Object.defineProperty(el, 'clientHeight', { value: 500, configurable: true })
    Object.defineProperty(el, 'scrollTop', { value: 1500, configurable: true })
    el.dispatchEvent(new Event('scroll'))
    await flushPromises()

    expect(m.chapter).toHaveBeenCalledTimes(2)    // 已在缓存 ⇒ 不多一次请求
    expect(m.chapter).toHaveBeenLastCalledWith('book-a', 1)
    expect(wrapper.text()).toContain('2 / 2')
  })

  /** 关掉开关后，滚到底就停在原地（不替用户做决定）。 */
  it('关掉自动续章后滚到底不自动跳', async () => {
    localStorage.setItem(READER_PREFS_KEY, JSON.stringify({ autoNextChapter: false }))
    const { wrapper } = await mountReader()
    const el = scrollerOf(wrapper)
    Object.defineProperty(el, 'scrollHeight', { value: 2000, configurable: true })
    Object.defineProperty(el, 'clientHeight', { value: 500, configurable: true })
    Object.defineProperty(el, 'scrollTop', { value: 1500, configurable: true })

    el.dispatchEvent(new Event('scroll'))
    await flushPromises()
    expect(wrapper.text()).toContain('1 / 2')
  })

  /** 边界：书不在列表里就**别**凭空插一条；更旧的时间戳也别把新的覆盖回去。 */
  it('进度回写的两条边界：未知书忽略、旧时间戳不倒退', () => {
    const lib = useLibraryStore()
    lib.$patch({ books: [makeBook({ id: 'book-a', percent: 10, updated_at: 500 })] })

    lib.patchProgress('不存在的书', 50, 999)
    expect(lib.books).toHaveLength(1)

    lib.patchProgress('book-a', 999, 100)           // 越界百分比 + 更旧的时间戳
    expect(lib.books[0].percent).toBe(100)
    expect(lib.books[0].updated_at).toBe(500)
  })

  /**
   * 滚轮翻页：**只在翻页模式**生效，滚动模式绝不抢滚轮。
   *
   * happy-dom 没有真实布局 ⇒ `pageCount` 恒为 1，于是「向后翻一页」会走到末页判定并切章。
   * 这正好让断言落在**可观测的取数**上：滚动模式不产生第二次 `chapter` 调用，
   * 翻页模式切到下一章（index 1）。
   */
  it('翻页模式滚轮翻页；滚动模式不抢滚轮', async () => {
    const scrollMode = await mountReader()
    // 首屏 + 预取下一章 = 2（第 61 期：滚动模式会先把下一章取好，见「自动续章」用例）
    expect(m.chapter).toHaveBeenCalledTimes(2)
    scrollerOf(scrollMode.wrapper).dispatchEvent(
      new WheelEvent('wheel', { deltaY: 120, cancelable: true }))
    await flushPromises()
    expect(m.chapter).toHaveBeenCalledTimes(2)             // 滚动模式：滚轮不触发取数

    localStorage.setItem(READER_PREFS_KEY, JSON.stringify({ mode: 'paged' }))
    m.chapter.mockClear()
    const pagedMode = await mountReader()
    scrollerOf(pagedMode.wrapper).dispatchEvent(
      new WheelEvent('wheel', { deltaY: 120, cancelable: true }))
    await flushPromises()
    expect(m.chapter).toHaveBeenLastCalledWith('book-a', 1)  // 翻页模式：向后翻 = 下一章
  })
})
