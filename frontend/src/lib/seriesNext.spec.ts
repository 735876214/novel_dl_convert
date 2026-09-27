import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { BookCard } from '@/lib/api'
import {
  resetSeriesNextState,
  resolveNextVolume,
  SERIES_NEXT_HINT_MS,
  SERIES_NEXT_MSG,
  useSeriesNext,
} from './seriesNext'

/**
 * 「自动翻到系列下一册」唯一真值源的契约（第 62 期）。
 *
 * `@/lib/api` 一次给齐（缺接口会在调用处抛）；`vue-router` / `@/stores/ui` 用最小 mock，
 * 避免挂载 pinia / 真路由。
 */
const mocks = vi.hoisted(() => ({
  toast: vi.fn(),
  push: vi.fn(),
  seriesDetail: vi.fn(),
}))
vi.mock('@/stores/ui', () => ({ useUiStore: () => ({ toast: mocks.toast }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
vi.mock('@/lib/api', () => ({ api: { seriesDetail: mocks.seriesDetail } }))

/** 造一个够用的 BookCard（只填被续接逻辑读到的字段） */
function book(id: string, index: string): BookCard {
  return {
    id,
    name: id,
    title: id,
    author: '',
    series: 'S',
    series_index: index,
    has_cover: false,
    format: 'EPUB',
    size: 0,
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
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  resetSeriesNextState()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('seriesNext · 文案常量（统一「册」口径）', () => {
  it('三条文案用「册」', () => {
    expect(SERIES_NEXT_MSG.noSeries).toContain('下一册')
    expect(SERIES_NEXT_MSG.lastVolume).toContain('最后一册')
    expect(SERIES_NEXT_MSG.notFound()).toBe('找不到系列下一册')
    expect(SERIES_NEXT_MSG.notFound('网络不可用')).toBe('找不到系列下一册：网络不可用')
  })
})

describe('seriesNext · resolveNextVolume（纯函数，异常不外抛）', () => {
  it('无系列（空 / 未定义）→ no_series，且不请求', async () => {
    const fetchSeries = vi.fn()
    expect((await resolveNextVolume('', 'b1', fetchSeries)).reason).toBe('no_series')
    expect((await resolveNextVolume(undefined, 'b1', fetchSeries)).reason).toBe('no_series')
    expect(fetchSeries).not.toHaveBeenCalled()
  })

  it('命中系列下一册 → ok（按系列序号排序后取下一本）', async () => {
    const fetchSeries = vi.fn().mockResolvedValue({ books: [book('b3', '3'), book('b1', '1'), book('b2', '2')] })
    const r = await resolveNextVolume('S', 'b1', fetchSeries)
    expect(r.reason).toBe('ok')
    expect(r.next?.id).toBe('b2')
  })

  it('已是末册 → last', async () => {
    const fetchSeries = vi.fn().mockResolvedValue({ books: [book('b1', '1'), book('b2', '2')] })
    expect((await resolveNextVolume('S', 'b2', fetchSeries)).reason).toBe('last')
  })

  it('当前书不在系列清单里 → last（沿用既有三处实现口径，不新增第五态）', async () => {
    const fetchSeries = vi.fn().mockResolvedValue({ books: [book('bx', '1')] })
    expect((await resolveNextVolume('S', 'b1', fetchSeries)).reason).toBe('last')
  })

  it('空系列清单 → last', async () => {
    const fetchSeries = vi.fn().mockResolvedValue({ books: [] })
    expect((await resolveNextVolume('S', 'b1', fetchSeries)).reason).toBe('last')
  })

  it('请求抛错 → error 且带原始信息（不外抛）', async () => {
    const fetchSeries = vi.fn().mockRejectedValue(new Error('boom'))
    const r = await resolveNextVolume('S', 'b1', fetchSeries)
    expect(r).toEqual({ next: null, reason: 'error', message: 'boom' })
  })
})

describe('seriesNext · useSeriesNext（enabled 门 / 单飞闸 / 提示节流）', () => {
  it('开关关闭 → 静默返回 false：不请求、不提示、不跳转', async () => {
    const { goToNextVolume } = useSeriesNext()
    const ok = await goToNextVolume({ enabled: false, series: 'S', bookId: 'b1', routeBase: '/read' })
    expect(ok).toBe(false)
    expect(mocks.seriesDetail).not.toHaveBeenCalled()
    expect(mocks.toast).not.toHaveBeenCalled()
    expect(mocks.push).not.toHaveBeenCalled()
  })

  it('无系列 → 提示 noSeries，不跳转', async () => {
    const { goToNextVolume } = useSeriesNext()
    const ok = await goToNextVolume({ enabled: true, series: '', bookId: 'b1', routeBase: '/read' })
    expect(ok).toBe(false)
    expect(mocks.toast).toHaveBeenCalledWith(SERIES_NEXT_MSG.noSeries)
    expect(mocks.push).not.toHaveBeenCalled()
  })

  it('已末册 → 提示 lastVolume，不跳转', async () => {
    mocks.seriesDetail.mockResolvedValue({ books: [book('b1', '1')] })
    const { goToNextVolume } = useSeriesNext()
    const ok = await goToNextVolume({ enabled: true, series: 'S', bookId: 'b1', routeBase: '/read' })
    expect(ok).toBe(false)
    expect(mocks.toast).toHaveBeenCalledWith(SERIES_NEXT_MSG.lastVolume)
    expect(mocks.push).not.toHaveBeenCalled()
  })

  it('命中 → 先落盘再跳转，返回 true（read 路径）', async () => {
    mocks.seriesDetail.mockResolvedValue({ books: [book('b1', '1'), book('b2', '2')] })
    const order: string[] = []
    mocks.push.mockImplementation(() => { order.push('push') })
    const { goToNextVolume } = useSeriesNext()
    const ok = await goToNextVolume({
      enabled: true,
      series: 'S',
      bookId: 'b1',
      routeBase: '/read',
      beforeJump: () => { order.push('save') },
    })
    expect(ok).toBe(true)
    expect(order).toEqual(['save', 'push'])
    expect(mocks.push).toHaveBeenCalledWith('/read/b2')
  })

  it('命中 → listen 路径（有声书）', async () => {
    mocks.seriesDetail.mockResolvedValue({ books: [book('b1', '1'), book('b2', '2')] })
    const { goToNextVolume } = useSeriesNext()
    await goToNextVolume({ enabled: true, series: 'S', bookId: 'b1', routeBase: '/listen' })
    expect(mocks.push).toHaveBeenCalledWith('/listen/b2')
  })

  it('同类提示节流：窗口内连点只弹一次，超窗后恢复', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(1_000_000)
    const { goToNextVolume } = useSeriesNext()
    const opts = { enabled: true, series: '', bookId: 'b1', routeBase: '/read' as const }
    await goToNextVolume(opts)
    await goToNextVolume(opts)
    expect(mocks.toast).toHaveBeenCalledTimes(1)
    vi.setSystemTime(1_000_000 + SERIES_NEXT_HINT_MS + 1)
    await goToNextVolume(opts)
    expect(mocks.toast).toHaveBeenCalledTimes(2)
  })

  it('节流按「原因」区分：跨因立即提示', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(2_000_000)
    const { goToNextVolume } = useSeriesNext()
    await goToNextVolume({ enabled: true, series: '', bookId: 'b1', routeBase: '/read' })
    mocks.seriesDetail.mockResolvedValue({ books: [book('b1', '1')] })
    await goToNextVolume({ enabled: true, series: 'S', bookId: 'b1', routeBase: '/read' })
    expect(mocks.toast).toHaveBeenNthCalledWith(1, SERIES_NEXT_MSG.noSeries)
    expect(mocks.toast).toHaveBeenNthCalledWith(2, SERIES_NEXT_MSG.lastVolume)
  })

  it('单飞闸：并发两次只发一次请求', async () => {
    let resolve!: (v: { books: BookCard[] }) => void
    mocks.seriesDetail.mockReturnValue(new Promise((r) => { resolve = r }))
    const { goToNextVolume } = useSeriesNext()
    const opts = { enabled: true, series: 'S', bookId: 'b1', routeBase: '/read' as const }
    const first = goToNextVolume(opts)
    const second = await goToNextVolume(opts)
    expect(second).toBe(false)
    expect(mocks.seriesDetail).toHaveBeenCalledTimes(1)
    resolve({ books: [book('b1', '1'), book('b2', '2')] })
    expect(await first).toBe(true)
  })
})
