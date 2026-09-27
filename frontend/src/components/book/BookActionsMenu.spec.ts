import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import BookActionsMenu from '@/components/book/BookActionsMenu.vue'
import { api, type BookCard, type BookDetail, type ReadingStatus } from '@/lib/api'
import { useBookMenu } from '@/lib/bookMenu'
import { useUiStore } from '@/stores/ui'

/**
 * 书卡 ⋮ 菜单（第 64 期 2/3）。
 *
 * 这份 spec 真正盯的是**「哪些项出现」**：菜单里多一项 / 少一项都不报错，
 * 只是用户点下去才发现「点了没反应」（进了一个打不开的阅读器）或「本来能下的
 * 书没有下载入口」。所以格式矩阵是这里的头号用例。
 *
 * ⚠️ 面板是 **Teleport 到 body** 的（全仓第一处），`wrapper.find` 找不到它 ——
 * 断言一律走 `document.body` 查询。也因此这里用 `attachTo: document.body`：
 * 挂在文档上才测得到「点别处关掉」这条 document 级的行为。
 */
vi.mock('@/lib/api', () => ({
  api: {
    deleteBook: vi.fn(),
    bookDetail: vi.fn(),
    // 形状与真实现一致（路径在 `/download/` 而非 `/api` 下）。编码细节归
    // `lib/downloadUrl.spec.ts` 管；这里只钉**组件有没有把 library_id 递下去** ——
    // 漏了它在单库实例上照样能用，多库实例上「下载」必 404（第 64 期修的正是这条）
    downloadUrl: vi.fn((name: string, libraryId?: string) =>
      `/download/${name}${libraryId ? `?library_id=${libraryId}` : ''}`,
    ),
    collections: vi.fn(),
    addToCollection: vi.fn(),
    removeFromCollection: vi.fn(),
    setStatus: vi.fn(),
  },
  apiErrorMessage: (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback),
}))

const m = {
  deleteBook: vi.mocked(api.deleteBook),
  bookDetail: vi.mocked(api.bookDetail),
  downloadUrl: vi.mocked(api.downloadUrl),
  collections: vi.mocked(api.collections),
  addToCollection: vi.mocked(api.addToCollection),
  removeFromCollection: vi.mocked(api.removeFromCollection),
  setStatus: vi.mocked(api.setStatus),
}

/** 两个收藏夹；`FIRST` 是用户会点的那个 */
const COLLECTIONS = [
  { id: 7, name: '想读', count: 3, created_at: 0, updated_at: 0, first_book_id: null, first_book_has_cover: false },
  { id: 9, name: '科幻', count: 12, created_at: 0, updated_at: 0, first_book_id: null, first_book_has_cover: false },
]

const BOOK_ID = 'lib$aaa'

function makeCard(over: Partial<BookCard> = {}): BookCard {
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
    description: '',
    issues: [],
    library_id: 'lib',
    ...over,
  }
}

const EPUB = makeCard()

/** 默认：详情里只有主文件本身（= 没有兄弟格式），于是确认文案不出第三行 */
function makeDetail(over: Partial<BookDetail> = {}): BookDetail {
  return {
    ...EPUB,
    chapters: [],
    files: [{ name: '三体.epub', format: 'EPUB', size: 1024, mtime: 1700000000 }],
    ...over,
  }
}

/**
 * `PUT /api/books/{bid}/status` 的返回体。**照 `ReadingStatus` 的真实形状给全** ——
 * 菜单不看这个返回值（写完就 `emit('changed')`，以服务端回声为准），但桩写成一个
 * 形状不对的 `{ ok: true }` 会让 `vue-tsc` 报错，也会让后来的人以为这个接口返回 `ok`。
 */
function makeStatus(status: ReadingStatus['status'] = 'unread'): ReadingStatus {
  return { book_id: BOOK_ID, status, started_at: 0, finished_at: 0, updated_at: 0 }
}

let router: Router
const mounted: VueWrapper[] = []

async function mountMenu(book: BookCard, menuKey = book.id): Promise<VueWrapper> {
  const w = mount(BookActionsMenu, {
    props: { book, menuKey },
    attachTo: document.body,
    global: { plugins: [router] },
  })
  mounted.push(w)
  await flushPromises()
  return w
}

async function openMenu(w: VueWrapper): Promise<void> {
  await w.find('[data-book-menu-trigger]').trigger('click')
  await flushPromises()
}

/** Teleport 到 body 的面板（不在 wrapper 的子树里） */
function panel(): HTMLElement | null {
  return document.body.querySelector<HTMLElement>('[data-book-menu-panel]')
}

function menuItems(): string[] {
  return Array.from(document.body.querySelectorAll<HTMLElement>('[role="menuitem"]')).map((b) =>
    (b.textContent || '').trim(),
  )
}

async function clickItem(label: string): Promise<void> {
  await clickEl(findItem(label))
}

function findItem(label: string): HTMLElement {
  const btn = Array.from(document.body.querySelectorAll<HTMLElement>('[role="menuitem"]')).find(
    (b) => (b.textContent || '').trim() === label,
  )
  if (!btn) throw new Error(`菜单里没有「${label}」：现有 ${JSON.stringify(menuItems())}`)
  return btn
}

/**
 * 子菜单项（收藏夹 / 五个状态）。它们用 `menuitemcheckbox` 而不是 `menuitem` ——
 * 勾选态是 `aria-checked`，语义上就是「可勾的菜单项」。也因此上面那个按
 * `[role="menuitem"]` 找的 `menuItems()` **看不见它们**，两份断言互不干扰。
 */
function subItems(): HTMLElement[] {
  return Array.from(
    document.body.querySelectorAll<HTMLElement>('[role="menuitemcheckbox"]'),
  )
}

async function clickEl(el: HTMLElement): Promise<void> {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await flushPromises()
}

async function clickSub(label: string): Promise<void> {
  const btn = subItems().find((b) => (b.textContent || '').trim().startsWith(label))
  if (!btn) throw new Error(`子菜单里没有「${label}」`)
  await clickEl(btn)
}

/**
 * 子菜单里被勾上的那些项的文案。
 * ⚠️ 收藏夹那一族的文案**带着成员数**（「想读3」）—— 按整串比会永远对不上，
 * 所以配对时一律用 `startsWith`（见下面各用例）。
 */
function checkedSubLabels(): string[] {
  return subItems()
    .filter((b) => b.getAttribute('aria-checked') === 'true')
    .map((b) => (b.textContent || '').trim())
}

/** 某个文案的子项**是否**被勾上（前缀匹配：收藏夹文案尾部带数量） */
function isSubChecked(label: string): boolean {
  return checkedSubLabels().some((t) => t.startsWith(label))
}

/**
 * `window.confirm` 的替身。
 *
 * ⚠️ happy-dom **根本没有实现 `confirm`**（不是「默认返回 true」，是这个函数不存在），
 * 所以在它上面 `vi.spyOn` 会直接抛「不是一个函数」。必须自己装一个。
 */
function setConfirm(answer: boolean): Mock<(message?: string) => boolean> {
  const spy = vi.fn<(message?: string) => boolean>(() => answer)
  window.confirm = spy
  return spy
}

function confirmText(spy: Mock<(message?: string) => boolean>): string {
  return String(spy.mock.calls[0]?.[0] ?? '')
}

beforeEach(async () => {
  setActivePinia(createPinia())
  // `openKey` 是**模块级**单例，会跨用例残留（`document.body` 扫干净了也还在）⇒
  // 上一个用例把菜单开着退出，下一个用例的第一个断言就会看见一个凭空打开的面板
  useBookMenu().close()
  m.deleteBook.mockResolvedValue({
    ok: true,
    id: BOOK_ID,
    name: '三体.epub',
    recycled: '20260927-120000_三体.epub',
    siblings: [],
  })
  m.bookDetail.mockResolvedValue(makeDetail())
  m.collections.mockResolvedValue({ items: COLLECTIONS })
  m.addToCollection.mockResolvedValue({ ok: true })
  m.removeFromCollection.mockResolvedValue({ ok: true })
  m.setStatus.mockResolvedValue(makeStatus())

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/book/:id', name: 'book', component: { template: '<div />' } },
      { path: '/read/:id', name: 'read', component: { template: '<div />' } },
      { path: '/listen/:id', name: 'listen', component: { template: '<div />' } },
      { path: '/', name: 'home', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
})

afterEach(() => {
  // ⚠️ **必须先 unmount 再扫 body**。反过来（直接 `document.body.innerHTML = ''`）会
  // 把一个还活着的组件实例的 DOM 连根拔掉，而它仍被 Vue 的响应式系统引用着 ——
  // 下次任何一次 patch（下一个用例里都行）都会在「insertBefore of null」上炸，
  // 症状是**后续每一个用例都红**、而报错指向的却是上一个用例，非常难判。
  // `unmount()` 会把自己的 Teleport 内容一起摘掉，扫 body 只是为了兜底。
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('BookActionsMenu：哪些项出现', () => {
  const CASES: { format: string; has: string[]; lacks: string[] }[] = [
    { format: 'EPUB', has: ['阅读', '下载'], lacks: ['收听'] },
    // TXT 与 EPUB 一样可读（自第 55 期起走派生 EPUB / 原生分章）
    { format: 'TXT', has: ['阅读', '下载'], lacks: ['收听'] },
    // 有声书整本是一个目录，`files[]` 为空 ⇒ 没有可下的单个文件。
    // 「下载」整条不出现（属**少给**，不是错给 —— 点下去 404 才是错给）
    { format: 'AUDIO', has: ['收听'], lacks: ['阅读', '下载'] },
    // MOBI 在线读不了：点了只会得到一句「点不了」，所以两项都不给，只留下载与详情
    { format: 'MOBI', has: ['下载', '书籍详细信息'], lacks: ['阅读', '收听'] },
  ]

  for (const c of CASES) {
    it(`${c.format}：给出 ${c.has.join(' / ')}，不给 ${c.lacks.join(' / ')}`, async () => {
      const w = await mountMenu(makeCard({ format: c.format }))
      await openMenu(w)

      const items = menuItems()
      for (const label of c.has) expect(items).toContain(label)
      for (const label of c.lacks) expect(items).not.toContain(label)
    })
  }

  it('顶层八项逐条对上（多一项少一项都要在这里过一遍），且「通过电子邮件发送」不在', async () => {
    const w = await mountMenu(EPUB)
    await openMenu(w)

    expect(menuItems()).toEqual([
      '阅读',
      '快速预览',
      '下载',
      '添加到收藏',
      '设置状态',
      '编辑元数据',
      '书籍详细信息',
      '删除',
    ])
    // 不灰置、不占位：「灰置」等于承认「本该有但不给你」，比没有更糟
    expect(panel()?.textContent).not.toContain('邮件')
  })

  it('两个 ⋮ 同时只开一个，且各自认自己的 key', async () => {
    const a = makeCard({ id: 'lib$a', name: '甲.epub', title: '甲' })
    const b = makeCard({ id: 'lib$b', name: '乙.epub', title: '乙' })
    await mountMenu(a, 'key-a')
    await mountMenu(b, 'key-b')

    const triggers = Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-book-menu-trigger]'),
    )
    expect(triggers).toHaveLength(2)

    triggers[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(document.body.querySelectorAll('[data-book-menu-panel]')).toHaveLength(1)

    triggers[1].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    // 还是**一个**：开第二个把第一个关掉了（状态只有一个 key，不是一条互斥规则）
    expect(document.body.querySelectorAll('[data-book-menu-panel]')).toHaveLength(1)
    expect(triggers[0].getAttribute('aria-expanded')).toBe('false')
    expect(triggers[1].getAttribute('aria-expanded')).toBe('true')
  })

  it('按 Escape 与点别处都关掉面板', async () => {
    const w = await mountMenu(EPUB)
    await openMenu(w)
    expect(panel()).not.toBeNull()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(panel()).toBeNull()

    await openMenu(w)
    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(panel()).toBeNull()
  })
})

describe('BookActionsMenu：动作', () => {
  it('「快速预览」把书交回父组件（不在菜单里自己开浮层）', async () => {
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('快速预览')

    expect(w.emitted('preview')?.[0]).toEqual([EPUB])
    // 面板同时关掉：留着的话它会在浮层上面再叠一层
    expect(panel()).toBeNull()
  })

  it('「编辑元数据」跳到详情页的元数据标签（深链，不是第二个编辑器实例）', async () => {
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('编辑元数据')

    expect(router.currentRoute.value.fullPath).toBe(`/book/${BOOK_ID}?tab=metadata`)
    expect(panel()).toBeNull()
  })

  it('「书籍详细信息」跳详情页', async () => {
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('书籍详细信息')

    expect(router.currentRoute.value.fullPath).toBe(`/book/${BOOK_ID}`)
    expect(panel()).toBeNull()
  })

  it('「阅读 / 收听」跳对应的阅读器 / 播放器，且关掉面板', async () => {
    const w = await mountMenu(makeCard({ format: 'EPUB' }))
    await openMenu(w)
    await clickItem('阅读')
    expect(router.currentRoute.value.fullPath).toBe(`/read/${BOOK_ID}`)

    const w2 = await mountMenu(makeCard({ id: 'lib$b', format: 'AUDIO' }), 'key-b')
    await openMenu(w2)
    await clickItem('收听')
    expect(router.currentRoute.value.fullPath).toBe('/listen/lib$b')
  })

  it('「下载」指到 /download/，文件名取路径最后一段', async () => {
    const clicked: string[] = []
    const spy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(`${this.getAttribute('href')}|${this.getAttribute('download')}`)
      })

    const w = await mountMenu(makeCard({ name: '三体/三体 #1.epub', library_id: 'lib-b' }))
    await openMenu(w)
    await clickItem('下载')

    // 库 id 必须递下去：多书库实例上服务端靠它决定去哪棵根下找文件（单库上漏了看不出来）
    expect(m.downloadUrl).toHaveBeenCalledWith('三体/三体 #1.epub', 'lib-b')
    // `/` 在 `download` 属性里会被浏览器当成路径，所以文件名只取最后一段
    expect(clicked).toEqual(['/download/三体/三体 #1.epub?library_id=lib-b|三体 #1.epub'])
    spy.mockRestore()
  })
})

describe('BookActionsMenu：添加到收藏（子菜单）', () => {
  it('展开是**行内**的：不产生第二个浮层，面板也不关', async () => {
    const w = await mountMenu(EPUB)
    await openMenu(w)
    expect(subItems()).toHaveLength(0)

    await clickItem('添加到收藏')

    expect(subItems()).toHaveLength(2)
    // 只有 body 里那**一个**面板（Teleport 的根），没有第二层浮层
    expect(document.body.querySelectorAll('[data-book-menu-panel]')).toHaveLength(1)
    expect(panel()).not.toBeNull()
    // 展开的子菜单在同一块面板里，不是新开的窗
    expect(panel()?.contains(subItems()[0])).toBe(true)
  })

  it('已加入的打勾，未加入的空着（勾选态取自书卡自带的 collection_ids，零请求）', async () => {
    const w = await mountMenu(makeCard({ collection_ids: [9] }))
    await openMenu(w)
    await clickItem('添加到收藏')

    expect(isSubChecked('科幻')).toBe(true)
    expect(isSubChecked('想读')).toBe(false)
    expect(m.collections).toHaveBeenCalled()
  })

  it('点未加入的 → addToCollection(收藏夹在前, 书在后)，并请父组件刷新', async () => {
    m.addToCollection.mockResolvedValue({ ok: true })
    const card = makeCard({ collection_ids: [] })
    const w = await mountMenu(card)
    await openMenu(w)
    await clickItem('添加到收藏')
    await clickSub('想读')

    // ⚠️ 实参顺序反了**不会报错**，只会往一个错的收藏夹里塞书 —— 所以在这里钉死
    expect(m.addToCollection).toHaveBeenCalledWith(7, BOOK_ID)
    expect(m.removeFromCollection).not.toHaveBeenCalled()
    // 点完立刻打勾：书卡上的 collection_ids 要等整库重拉才更新，
    // 中间这段时间不打勾用户会以为没点上，于是再点一次（变成移出）
    expect(isSubChecked('想读')).toBe(true)
    expect(w.emitted('changed')?.[0]).toEqual([card, 'collection'])
  })

  it('点已加入的 → 移出（而不是再加一次）', async () => {
    m.removeFromCollection.mockResolvedValue({ ok: true })
    const w = await mountMenu(makeCard({ collection_ids: [7] }))
    await openMenu(w)
    await clickItem('添加到收藏')
    await clickSub('想读')

    expect(m.removeFromCollection).toHaveBeenCalledWith(7, BOOK_ID)
    expect(m.addToCollection).not.toHaveBeenCalled()
    expect(isSubChecked('想读')).toBe(false)
  })

  it('一个收藏夹都没有时说清「还没有」，不编一个空列表', async () => {
    m.collections.mockResolvedValue({ items: [] })
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('添加到收藏')

    expect(subItems()).toHaveLength(0)
    expect(panel()?.textContent).toContain('还没有收藏夹')
  })

  it('写失败：不请父组件刷新，勾保持原样，给一条 toast', async () => {
    m.addToCollection.mockRejectedValue(new Error('后端连不上'))
    const w = await mountMenu(makeCard({ collection_ids: [] }))
    await openMenu(w)
    await clickItem('添加到收藏')
    await clickSub('想读')

    expect(w.emitted('changed')).toBeUndefined()
    expect(checkedSubLabels()).toEqual([])
    expect(useUiStore().toastMessage).toContain('后端连不上')
  })

  it('关掉面板再打开，子菜单是收起的（不闪一眼上次展开的那段）', async () => {
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('添加到收藏')
    expect(subItems()).toHaveLength(2)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    await openMenu(w)
    expect(subItems()).toHaveLength(0)
  })
})

describe('BookActionsMenu：设置状态（子菜单）', () => {
  it('从没设过状态 ⇒ 五项一项都不打勾，另给一行不可点的「未设置」', async () => {
    // `status` 缺省 = null（`BookCard.status` 的注释明写：null 不是 unread）
    const w = await mountMenu(makeCard({ percent: 0 }))
    await openMenu(w)
    await clickItem('设置状态')

    expect(subItems().map((b) => (b.textContent || '').trim())).toEqual([
      '未读',
      '在读',
      '已读完',
      '搁置',
      '弃读',
    ])
    // 最要命的一条：按进度兜底推导会把「什么都没标」显示成「他标了未读」
    expect(checkedSubLabels()).toEqual([])

    // 「未设置」是说明文字，不是可点的项 —— 点它没有语义
    const note = Array.from(panel()!.querySelectorAll('*')).find(
      (el) => (el.textContent || '').trim() === '未设置',
    )
    expect(note).toBeTruthy()
    expect(note!.closest('[role^="menuitem"]')).toBeNull()
  })

  it('有状态时只有那一项打勾，文案取自共享清单', async () => {
    const w = await mountMenu(makeCard({ status: 'reading' }))
    await openMenu(w)
    await clickItem('设置状态')

    expect(checkedSubLabels()).toEqual(['在读'])
    // 「未设置」那行不该出现
    expect(panel()?.textContent).not.toContain('未设置')
  })

  it('点一项 → 写库、关面板、请父组件刷新', async () => {
    m.setStatus.mockResolvedValue(makeStatus())
    const card = makeCard({ status: 'reading' })
    const w = await mountMenu(card)
    await openMenu(w)
    await clickItem('设置状态')
    await clickSub('已读完')

    expect(m.setStatus).toHaveBeenCalledWith(BOOK_ID, { status: 'finished' })
    expect(useUiStore().toastMessage).toContain('已读完')
    expect(panel()).toBeNull()
    expect(w.emitted('changed')?.[0]).toEqual([card, 'status'])
  })

  it('写失败：面板留着（好让人重选），不请父组件刷新', async () => {
    m.setStatus.mockRejectedValue(new Error('后端连不上'))
    const w = await mountMenu(makeCard({ status: 'reading' }))
    await openMenu(w)
    await clickItem('设置状态')
    await clickSub('已读完')

    expect(w.emitted('changed')).toBeUndefined()
    expect(panel()).not.toBeNull()
    expect(useUiStore().toastMessage).toContain('后端连不上')
  })
})

describe('BookActionsMenu：删除', () => {
  it('点「取消」⇒ 一个请求都不发', async () => {
    const spy = setConfirm(false)
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('删除')

    expect(confirmText(spy)).toContain('确定删除《三体》？')
    // 双向哨兵：既没删，也没白问一次后端
    expect(m.deleteBook).not.toHaveBeenCalled()
    expect(w.emitted('changed')).toBeUndefined()
  })

  it('确认文案说清「回收而不是真删」与「关联数据保留」', async () => {
    const spy = setConfirm(false)
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('删除')

    const text = confirmText(spy)
    expect(text).toContain('回收站')
    expect(text).toContain('不是真删')
    expect(text).toContain('批注')
    // 没有同 stem 的兄弟格式时**不出**第三行 —— 写了会让人以为还有别的格式存在
    expect(text).not.toContain('其它格式')
  })

  it('有同名的其它格式时，确认文案点名它（不然用户以为两个格式一起没了）', async () => {
    m.bookDetail.mockResolvedValue(
      makeDetail({
        files: [
          { name: '三体.epub', format: 'EPUB', size: 1024, mtime: 1 },
          { name: '三体.mobi', format: 'MOBI', size: 2048, mtime: 1 },
          { name: '球状闪电.epub', format: 'EPUB', size: 10, mtime: 1 },
        ],
      }),
    )
    const spy = setConfirm(false)
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('删除')

    const text = confirmText(spy)
    expect(text).toContain('三体.mobi')
    // 同目录但不同 stem 的邻居**不在**名单里
    expect(text).not.toContain('球状闪电')
  })

  it('确认后真的删：调一次接口并请父组件刷新', async () => {
    setConfirm(true)
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('删除')

    expect(m.deleteBook).toHaveBeenCalledTimes(1)
    expect(m.deleteBook).toHaveBeenCalledWith(BOOK_ID)
    expect(w.emitted('changed')?.[0]).toEqual([EPUB, 'deleted'])
  })

  it('删除失败：不请父组件刷新，只给一条 toast', async () => {
    setConfirm(true)
    m.deleteBook.mockRejectedValue(new Error('后端连不上'))
    const w = await mountMenu(EPUB)
    await openMenu(w)
    await clickItem('删除')

    // 文件没动成就什么都不动，所以列表不该为一次无效操作重拉一遍
    expect(w.emitted('changed')).toBeUndefined()
    expect(useUiStore().toastMessage).toContain('后端连不上')
  })
})
