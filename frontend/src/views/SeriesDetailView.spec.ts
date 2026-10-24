import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api, type BookCard } from '@/lib/api'
import { useShelfPrefsStore } from '@/stores/shelfPrefs'
import SeriesDetailView from '@/views/SeriesDetailView.vue'

/**
 * 系列详情页的**阅读入口**（第 152 期）。
 *
 * 用户原话：「折叠系列后，文件里面只有一本书，点击开始阅读不能从第一册开始读，不能看目录」。
 * 书架上折叠行的点击落点已改成这一页（目录），那这一页就必须真的能「从第一册开始读」——
 * 起点取**系列序号最小的那册**，不是折叠卡的代表本（代表本只决定封面画哪张）。
 *
 * 这一族坏起来也静默：按钮点下去照样进阅读器，只是从第 18 册开始 —— 没人会报错。
 *
 * `SeriesMetaPanel` 桩掉：它是自取数据的区块组件，与本用例要验的落点无关。
 */
vi.mock('@/lib/api', () => ({
  api: {
    seriesDetail: vi.fn(),
    coverUrl: vi.fn((id: string) => `/api/books/${id}/cover`),
  },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const m = { seriesDetail: vi.mocked(api.seriesDetail) }

function makeBook(over: Partial<BookCard> = {}): BookCard {
  return {
    id: 'lib$a',
    name: 'x.cbz',
    title: 'Vol.01',
    author: '作者',
    series: '测试系列',
    series_index: '1',
    has_cover: false,
    format: 'CBZ',
    size: 1024,
    mtime: 1700000000,
    c1: 'oklch(0.9 0 0)',
    c2: 'oklch(0.8 0 0)',
    tags: [],
    narrators: [],
    year: '',
    publisher: '',
    isbn: '',
    language: 'zh',
    description: '',
    issues: [],
    library_id: 'lib',
    ...over,
  }
}

/** 乱序给出：接口不保证顺序，排序是页面的事（`sortBySeriesIndex`） */
const BOOKS: BookCard[] = [
  makeBook({ id: 'lib$3', title: 'Vol.03', series_index: '3' }),
  makeBook({ id: 'lib$1', title: 'Vol.01', series_index: '1' }),
  makeBook({ id: 'lib$2', title: 'Vol.02', series_index: '2' }),
]

let router: Router
const mounted: VueWrapper[] = []

async function mountSeries(): Promise<VueWrapper> {
  setActivePinia(createPinia())
  const w = mount(SeriesDetailView, {
    global: {
      plugins: [router],
      stubs: { SeriesMetaPanel: true },
    },
  })
  mounted.push(w)
  await flushPromises()
  return w
}

function buttonByText(w: VueWrapper, text: string) {
  return w.findAll('button').find((b) => (b.text() || '').includes(text))
}

beforeEach(async () => {
  localStorage.clear()
  vi.clearAllMocks()
  m.seriesDetail.mockResolvedValue({
    name: '测试系列',
    count: BOOKS.length,
    books: BOOKS,
    groups: [],
    meta: null,
    meta_state: null,
    gaps: null,
  } as never)
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/series', component: { template: '<div />' } },
      { path: '/series/:name', component: { template: '<div />' } },
      { path: '/book/:id', component: { template: '<div />' } },
      { path: '/read/:id', component: { template: '<div />' } },
      { path: '/listen/:id', component: { template: '<div />' } },
    ],
  })
  await router.push(`/series/${encodeURIComponent('测试系列')}`)
  await router.isReady()
})

afterEach(() => {
  // Teleport 不在本页，但保持与其它视图 spec 同一条纪律：先卸载再清 body
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('SeriesDetailView：目录与「从第一册开始」', () => {
  it('列出全部册（目录）', async () => {
    const w = await mountSeries()
    expect(w.text()).toContain('共 3 册')
    for (const t of ['Vol.01', 'Vol.02', 'Vol.03']) expect(w.text()).toContain(t)
  })

  it('「开始阅读」从**序号最小**的那册开始（不是接口给的第一条）', async () => {
    const w = await mountSeries()
    const btn = buttonByText(w, '开始阅读')
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/read/lib$1')
  })

  it('按钮的 title 说清起点是哪一册（不是黑箱）', async () => {
    const w = await mountSeries()
    const btn = buttonByText(w, '开始阅读')
    expect(btn?.attributes('title')).toContain('Vol.01')
  })

  it('点某一册 → 那一册的详情（默认「缩略图点击 = 先看详情」）', async () => {
    const w = await mountSeries()
    await buttonByText(w, 'Vol.02')!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/book/lib$2')
  })

  it('缩略图点击 = 直接阅读时，点某一册直接进阅读器（与书架同一偏好口径）', async () => {
    const w = await mountSeries()
    useShelfPrefsStore().patch({ thumbnailClick: 'reader' })
    await flushPromises()
    await buttonByText(w, 'Vol.02')!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/read/lib$2')
  })

  it('一本序号都没有时退回落库顺序的首本（不因为缺序号就藏掉按钮）', async () => {
    m.seriesDetail.mockResolvedValue({
      name: '测试系列',
      count: 2,
      books: [makeBook({ id: 'lib$n1', title: '上册', series_index: '' }), makeBook({ id: 'lib$n2', title: '下册', series_index: '' })],
      groups: [],
      meta: null,
      meta_state: null,
      gaps: null,
    } as never)
    const w = await mountSeries()
    const btn = buttonByText(w, '开始阅读')
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/read/lib$n1')
  })
})

/**
 * 首册**打不开**的情形（第 152 期审计时在真实库里抓到的唯一一例：
 * `青春期笨蛋不做理性小魔女的梦` 的 `Vol.01 (2) (2).zip` 是解析失败的容器）。
 *
 * 只按序号取起点的话，「开始阅读」会跳到一本读不了的书 —— 那不是开始阅读。
 * 目录里也要如实标出来，否则坏册与正常册长得一模一样。
 */
describe('SeriesDetailView：首册打不开时', () => {
  const BAD_FIRST: BookCard[] = [
    makeBook({ id: 'lib$bad', title: 'Vol.01', series_index: '1', format: 'ZIP', pages: 0, issues: ['unparsable'] }),
    makeBook({ id: 'lib$ok', title: 'Vol.02', series_index: '2', format: 'CBZ', pages: 120 }),
  ]

  beforeEach(() => {
    m.seriesDetail.mockResolvedValue({
      name: '测试系列',
      count: BAD_FIRST.length,
      books: BAD_FIRST,
      groups: [],
      meta: null,
      meta_state: null,
      gaps: null,
    } as never)
  })

  it('从**下一本可读的册**开始，而不是跳进死页面', async () => {
    const w = await mountSeries()
    const btn = buttonByText(w, '开始阅读')
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/read/lib$ok')
  })

  it('按钮 title 说出真正的起点（不是「第一册」这种会落空的承诺）', async () => {
    const w = await mountSeries()
    expect(buttonByText(w, '开始阅读')?.attributes('title')).toContain('Vol.02')
  })

  it('目录里把解析失败的那册标出来', async () => {
    const w = await mountSeries()
    expect(w.text()).toContain('解析失败')
  })

  it('全部打不开时退回序号最小的那本（按钮还在，进详情页看原因）', async () => {
    m.seriesDetail.mockResolvedValue({
      name: '测试系列',
      count: 1,
      books: [makeBook({ id: 'lib$bad2', title: 'Vol.01', series_index: '1', format: 'ZIP', pages: 0, issues: ['unparsable'] })],
      groups: [],
      meta: null,
      meta_state: null,
      gaps: null,
    } as never)
    const w = await mountSeries()
    const btn = buttonByText(w, '开始阅读')
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/book/lib$bad2')
  })
})
