import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api, type BookDetail, type BookVolume, type OnlineChapters } from '@/lib/api'
import ReaderView from '@/views/ReaderView.vue'

/**
 * 第 93 期：在线模式的**边界契约**。
 *
 * 这一整套坏起来**全是静默的** —— 页面照常渲染、请求照常发出，只是：
 *   · 来源标注没显示（读者把源站内容当成本地那本书的新章节）；
 *   · 断网命中缓存时仍写「本页内容来自源站」（把旧内容说成刚取的）；
 *   · 在线位置写进了 `/progress`（跨客户端续读与本地进度互相覆盖）；
 *   · 书签 / 批注按钮还在（存下来的锚指向一段不属于它的文本）。
 *
 * 四条都不会抛异常、不会有任何提示，故逐条钉住。
 *
 * ⚠️ 与 `ReaderView.spec.ts` 分开成两个文件不是洁癖：那个文件 mock 的 `api`
 * **没有** `onlineStatus` / `onlineChapters` / `onlineChapter` / `onlineSetPos` ——
 * 在线模式的取数路径在那边一进去就是 `undefined is not a function`。
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
    setProgress: vi.fn(),
    epubCss: vi.fn(),
    // 第 93 期在线读的四条
    onlineStatus: vi.fn(),
    onlineChapters: vi.fn(),
    onlineChapter: vi.fn(),
    onlineSetPos: vi.fn(),
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
  setProgress: vi.mocked(api.setProgress),
  epubCss: vi.mocked(api.epubCss),
  onlineStatus: vi.mocked(api.onlineStatus),
  onlineChapters: vi.mocked(api.onlineChapters),
  onlineChapter: vi.mocked(api.onlineChapter),
  onlineSetPos: vi.mocked(api.onlineSetPos),
}

function makeBook(): BookDetail {
  const chapters: BookVolume[] = [{
    volume: '',
    chapters: [
      { num: 1, index: 0, title: '第一章 科学边界' },
      { num: 2, index: 1, title: '第二章 台球' },
      { num: 3, index: 2, title: '第三章 射手和农场主' },
    ],
  }]
  return {
    id: 'book-a', name: '三体.epub', title: '三体', author: '刘慈欣', series: '',
    has_cover: false, format: 'EPUB', size: 1024, mtime: 0, c1: '', c2: '',
    tags: [], narrators: [], year: '', publisher: '', isbn: '', language: '',
    description: '', issues: [], chapters, files: [],
  }
}

/** 三章的书页目录，`local_index` 与服务端算出来的一致（前端只读不重算）。 */
function makeChapters(over: Partial<OnlineChapters> = {}): OnlineChapters {
  return {
    source: 'stub-src',
    display_name: '示例书站',
    title: '三体',
    url: 'https://example.test/page/1',
    total: 3,
    entries: [
      { index: 0, title: '第一章 科学边界', local_index: 0 },
      { index: 1, title: '第二章 台球', local_index: 1 },
      { index: 2, title: '第三章 射手和农场主', local_index: 2 },
    ],
    pos: 0,
    local_total: 3,
    single: false,
    origin: 'network',
    stale: false,
    fetched_at: 1_700_000_000,
    error: '',
    ...over,
  }
}

function stubApi(over: {
  status?: Record<string, unknown>
  chapters?: OnlineChapters
  chapter?: Record<string, unknown>
} = {}): void {
  m.bookDetail.mockResolvedValue(makeBook())
  m.listAnnotations.mockResolvedValue({ items: [] })
  m.listBookmarks.mockResolvedValue({ items: [], total: 0, trashed: [] })
  m.getProgress.mockResolvedValue({ locator: 0, percent: 0 })
  m.chapter.mockResolvedValue({ index: 0, total: 3, title: '第一章', html: '<p>本地正文</p>' })
  m.recordSession.mockResolvedValue({ ok: true, session_uid: 'stub-uid' })
  m.fonts.mockResolvedValue({ items: [], max_bytes: 0, max_count: 0 })
  m.setProgress.mockResolvedValue({ ok: true, updated_at: 1000 })
  m.epubCss.mockResolvedValue({ css: '', sheets: [], fixed_layout: false })

  m.onlineStatus.mockResolvedValue({
    bound: true,
    source: 'stub-src',
    display_name: '示例书站',
    url: 'https://example.test/page/1',
    title: '三体',
    pos: 0,
    seen: 0,
    cache: { total: 3, cached: 1, single: false, fetched_at: 1_700_000_000 },
    available: true,
    reason: '',
    ...(over.status ?? {}),
  } as never)
  m.onlineChapters.mockResolvedValue(over.chapters ?? makeChapters())
  m.onlineChapter.mockResolvedValue({
    index: 0,
    total: 3,
    title: '第一章 科学边界',
    // ⚠️ 服务端已经把源站标记压成纯文本：这里只可能有 `<p>`，不会有源站的标签
    html: '<p>甲&amp;乙</p>\n<p>丙</p>',
    text_encoding: null,
    origin: 'network',
    stale: false,
    cached_at: 1_700_000_000,
    error: '',
    raw_len: 42,
    local_index: 0,
    local_total: 3,
    pos: 0,
    source: 'stub-src',
    display_name: '示例书站',
    url: 'https://example.test/page/1',
    ...(over.chapter ?? {}),
  } as never)
  m.onlineSetPos.mockResolvedValue({ ok: true, pos: 0, local_index: 0, local_total: 3 })
}

/** 挂在线读（`/online/book-a`）；`read` 路由也要有 —— 「改读本地」按钮会 push 它。 */
async function mountOnline(): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/read/:id', name: 'read', component: ReaderView },
      { path: '/online/:id', name: 'online', component: ReaderView },
      { path: '/book/:id', name: 'book', component: ReaderView },
    ],
  })
  await router.push('/online/book-a')
  await router.isReady()
  const wrapper = mount(ReaderView, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

function buttonByText(w: VueWrapper, text: string) {
  return w.findAll('button').find((b) => b.text() === text)
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  stubApi()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ReaderView · 在线读的来源标注（第 93 期）', () => {
  /**
   * 这是本期的**验收项**：读了半天不知道屏幕上这段字来自哪儿，是这个功能最容易
   * 让人误判的地方。正文上方一条、目录抽屉顶部一条，**两处都要有**。
   */
  it('正文上方常驻一条来源标注，带源站名与「打开源站页面」', async () => {
    const { wrapper } = await mountOnline()
    const banner = wrapper.find('[data-testid="online-banner"]')

    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('示例书站')
    expect(banner.text()).toContain('本机已缓存 1 / 3 章')

    const link = banner.find('a')
    expect(link.attributes('href')).toBe('https://example.test/page/1')
    // 新开的源站页面是第三方，不该拿到本页的 `window.opener`
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toBe('noopener')
    wrapper.unmount()
  })

  it('目录抽屉顶部有同一条标注', async () => {
    const { wrapper } = await mountOnline()
    // 目录默认关着（`showToc` 初始 false）；点工具栏那个「目录」按钮把它打开
    const tocBtn = wrapper.findAll('button').find((b) => b.attributes('title') === '目录')
    expect(tocBtn).toBeTruthy()
    await tocBtn!.trigger('click')

    const tocBanner = wrapper.find('[data-testid="online-banner-toc"]')
    expect(tocBanner.exists()).toBe(true)
    expect(tocBanner.text()).toContain('示例书站')
    wrapper.unmount()
  })

  /**
   * 「网络不可用，本节选自本机缓存」这句是本期「网络差也能继续读」的**唯一可见证据**。
   * 不写出来，用户只会以为书源更新到这儿了 —— 把一份旧内容当成新内容。
   */
  it('断网命中缓存时横幅改口，不再说「来自源站在线页面」', async () => {
    stubApi({
      chapter: { origin: 'cache', stale: true, cached_at: 1_700_000_000 },
    })
    const { wrapper } = await mountOnline()
    const text = wrapper.find('[data-testid="online-banner"]').text()

    expect(text).toContain('网络不可用')
    expect(text).toContain('本机缓存')
    expect(text).not.toContain('本页内容来自')
    wrapper.unmount()
  })

  it('在线模式取数只走 onlineChapter，不碰本地章节接口', async () => {
    const { wrapper } = await mountOnline()

    expect(m.onlineChapter).toHaveBeenCalled()
    expect(m.chapter).not.toHaveBeenCalled()
    // 服务端给的纯文本原样进正文（第三方标记永不进 `v-html`，这条由后端保证）
    expect(wrapper.find('.reader-content').html()).toContain('甲&amp;乙')
    wrapper.unmount()
  })

  /**
   * 两份位置**故意不合并**（见 `saveProgress` 那段注释）：
   * `online_bind.pos`（在线位置，落服务端 ⇒ 任何客户端都从同一处续读）与
   * `progress`（本地位置，只在窗口规则对得上时才写）。
   * 前端越俎代庖写 `/progress` 就会让两边互相覆盖 —— 而且**不会报错**。
   */
  it('在线模式的进度只报 onlineSetPos，绝不写 /progress', async () => {
    const { wrapper } = await mountOnline()
    wrapper.unmount()
    await flushPromises()

    expect(m.onlineSetPos).toHaveBeenCalled()
    expect(m.setProgress).not.toHaveBeenCalled()
  })

  /**
   * ⚠️ 这条是**实测抓出来的真缺陷**的回归钉。
   *
   * 原实现把模式写成 `computed(() => route.name === 'online')`，而离开阅读器时路由**先**变成
   * 目标页、组件**后**卸载 —— 于是 `onBeforeUnmount` 里那次收尾保存读到的模式是「本地」，
   * 把**线上章号当成本地章号**写进 `/progress`。不报错、不告警，只在下次打开本地阅读时
   * 表现为「进度跳到不相干的一章」。
   *
   * 这里连**路由都没换**就直接卸载，同样是「模式不再由路由实时推导」的检验：
   * 路由一旦失效（`route.name` 变 `undefined`），从路由推导的写法会翻成 false。
   */
  it('离开在线读时收尾保存仍按在线口径走，不把线上章号写成本地进度', async () => {
    const { wrapper, router } = await mountOnline()
    m.onlineSetPos.mockClear()
    m.setProgress.mockClear()

    // 先跳到详情页（真实路径：点「返回详情」就是这个动作），再卸载
    await router.push('/book/book-a')
    await flushPromises()
    wrapper.unmount()
    await flushPromises()

    expect(m.setProgress).not.toHaveBeenCalled()
    expect(m.onlineSetPos).toHaveBeenCalled()
  })

  it('初始位置取服务端的在线位置（跨客户端续读的依据）', async () => {
    stubApi({ chapters: makeChapters({ pos: 2 }) })
    const { wrapper } = await mountOnline()

    // pos=2 ⇒ 直接落到线上第 3 章
    expect(m.onlineChapter).toHaveBeenCalledWith('book-a', 2)
    wrapper.unmount()
  })

  /**
   * 书签 / 批注的锚是「本地这一章的文本偏移」，而在线正文是**另一份文本**。
   * 留着按钮 = 给一个存不下东西的假交互，故一律隐藏（不是灰掉）。
   */
  it('在线模式隐藏书签与笔记入口', async () => {
    const { wrapper } = await mountOnline()
    const titles = wrapper.findAll('button').map((b) => b.attributes('title') ?? '')

    expect(titles.some((t) => t.includes('书签'))).toBe(false)
    expect(wrapper.findAll('button').some((b) => b.text() === '笔记')).toBe(false)
    wrapper.unmount()
  })

  it('源不可用时给一页如实说明 + 回本地阅读的入口', async () => {
    stubApi({ status: { available: false, reason: '下载开关关着（设置 → 外部服务 → 下载）' } })
    const { wrapper } = await mountOnline()

    const text = wrapper.text()
    expect(text).toContain('这本书现在没法在线读')
    // 原因**原文**照抄，不许换成一句自编的通用话
    expect(text).toContain('下载开关关着')
    expect(buttonByText(wrapper, '改读本地')).toBeTruthy()
    // 不可用时一个章节请求都不该发出去
    expect(m.onlineChapter).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

/**
 * 第 93 期 · 键盘可达：`Esc` 收面板 + 焦点归位。
 *
 * 面板（目录 / 阅读设置 / 笔记）都不是模态框、没有焦点陷阱，所以「关掉」之后
 * **焦点必须回到打开它的那个按钮** —— 否则焦点掉到 `body`，键盘用户要重新从侧栏
 * 第一项 Tab 几十下才回得来（真机走查里 Tab 数到第 38 下才进正文区）。
 *
 * ⚠️ 断言必须挂在 `document.body` 上：`focus()` 对**不在文档里**的节点无效，
 * 不 `attachTo` 的话 `document.activeElement` 永远是 `body`，这里会全假绿。
 */
describe('ReaderView · 键盘：Esc 收面板并把焦点还回去（第 93 期）', () => {
  function btn(w: VueWrapper, title: string) {
    const b = w.findAll('button').find((x) => x.attributes('title') === title)
    expect(b, `没找到标题为「${title}」的按钮`).toBeTruthy()
    return b!.element as HTMLElement
  }

  async function mountAttached(): Promise<VueWrapper> {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/read/:id', name: 'read', component: ReaderView },
        { path: '/online/:id', name: 'online', component: ReaderView },
      ],
    })
    await router.push('/online/book-a')
    await router.isReady()
    const wrapper = mount(ReaderView, { attachTo: document.body, global: { plugins: [router] } })
    await flushPromises()
    return wrapper
  }

  /** 面板开着的判据用**真实渲染物**（在线模式的目录抽屉带 `online-banner-toc`）。 */
  const tocOpen = () => !!document.querySelector('[data-testid="online-banner-toc"]')

  it('Esc 收起目录抽屉，焦点还给「目录」按钮', async () => {
    const wrapper = await mountAttached()
    const toc = btn(wrapper, '目录')
    toc.click()
    await flushPromises()
    expect(tocOpen()).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(tocOpen()).toBe(false)
    expect(document.activeElement).toBe(toc)
    wrapper.unmount()
  })

  it('Esc 收起阅读设置面板，焦点还给「阅读设置」按钮', async () => {
    const wrapper = await mountAttached()
    const gear = btn(wrapper, '阅读设置')
    gear.click()
    await flushPromises()
    // 面板开着的旁证：字号那一栏出来了
    expect(wrapper.text()).toContain('字号')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(wrapper.find('button[title="阅读设置"]').exists()).toBe(true)
    expect(document.activeElement).toBe(gear)
    wrapper.unmount()
  })

  /**
   * 没有面板时的 `Esc` **什么也不做**：阅读器把它吃掉，别的组件（弹窗 / 抽屉）
   * 就再也收不到这个键了 —— 那是很难查的「按 Esc 没反应」。
   */
  it('没有面板时 Esc 不动焦点、不吞按键', async () => {
    const wrapper = await mountAttached()
    const gear = btn(wrapper, '阅读设置')
    gear.focus()
    expect(document.activeElement).toBe(gear)

    const ev = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true, bubbles: true })
    window.dispatchEvent(ev)
    await flushPromises()

    expect(ev.defaultPrevented).toBe(false)
    expect(document.activeElement).toBe(gear)
    wrapper.unmount()
  })
})
