import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import {
  FALLBACK,
  ensureThresholds,
  isInProgress,
  refreshThresholds,
  statusFromPercent,
  statusLabelOf,
  statusOf,
  thresholdsFor,
} from '@/lib/readingThresholds'

vi.mock('@/lib/api', () => ({
  api: { readingThresholds: vi.fn() },
}))

const mockThresholds = vi.mocked(api.readingThresholds)

/**
 * 每条用例都从**干净的缓存**起步。
 *
 * `clearMocks` 只清调用记录，清不掉 `lib/readingThresholds` 里那个模块级缓存 ——
 * 它是刻意的（阈值要跨组件共享），所以测试得自己负责重置：用 `refreshThresholds`
 * 拿新值覆盖即可（模块只导出这一个改写入口，没有「清空」这种危险 API）。
 */
async function freshThresholds(libraryId: string, started: number, finished: number) {
  mockThresholds.mockResolvedValueOnce({ library_id: libraryId, started, finished })
  await refreshThresholds(libraryId)
}

describe('阅读阈值 · 纯判定 statusFromPercent', () => {
  it('默认阈值下边界含等号：99.5 算已读完，99.49 不算', () => {
    // 「达到」而不是「超过」—— 阅读器按整章推进，末章末尾即 100%，
    // 但中途恰好停在 99.5 的书（进度取整误差）也必须算读完，这是本仓既有口径。
    expect(statusFromPercent(99.5)).toBe('finished')
    expect(statusFromPercent(99.49)).toBe('reading')
  })

  it('默认阈值的下界是 0：有一点进度就算在读', () => {
    expect(statusFromPercent(0)).toBe('unread')
    expect(statusFromPercent(0.01)).toBe('reading')
  })

  it('改阈值后同一进度给出不同结论（这就是本期要可配的东西）', () => {
    const t = { started: 5, finished: 50 }
    expect(statusFromPercent(3, t)).toBe('unread')
    expect(statusFromPercent(5, t)).toBe('unread') // 「高于」下界才算在读
    expect(statusFromPercent(5.01, t)).toBe('reading')
    expect(statusFromPercent(50, t)).toBe('finished')
  })

  it('坏进度一律当未读，不抛', () => {
    expect(statusFromPercent(null)).toBe('unread')
    expect(statusFromPercent(undefined)).toBe('unread')
    expect(statusFromPercent(Number.NaN)).toBe('unread')
  })
})

describe('阅读阈值 · 取值与缓存', () => {
  beforeEach(() => {
    mockThresholds.mockReset()
  })

  it('没取到过时用兜底值，且兜底值与后端默认值一致', () => {
    // ⚠️ 兜底值必须**逐字节等于**后端 config.DEFAULTS；不同就会出现
    // 「首屏按 A 判、拉到数据后跳成 B」的闪烁。这条断言是那个约定的看门人。
    expect(FALLBACK).toEqual({ started: 0, finished: 99.5 })
  })

  it('取到之后按服务端的值判 —— 不是前端自己写死的 99.5', async () => {
    await freshThresholds('', 0, 50)
    expect(thresholdsFor('')).toEqual({ started: 0, finished: 50 })
    // 60% 的书：服务端说阈值 50 ⇒ 已读完。前端若还写死 99.5 这里就是 reading。
    expect(statusFromPercent(60, thresholdsFor(''))).toBe('finished')
  })

  it('库级与全局分开缓存：覆写了某个库不影响全局', async () => {
    await freshThresholds('', 0, 99.5)
    await freshThresholds('lib-a', 0, 50)

    expect(thresholdsFor('lib-a').finished).toBe(50)
    expect(thresholdsFor('').finished).toBe(99.5)
    // 没单独取过的库回落全局，而不是兜底值
    expect(thresholdsFor('lib-b').finished).toBe(99.5)
  })

  it('同一 key 并发只发一个请求，取到之后不再重复拉', async () => {
    mockThresholds.mockResolvedValue({ library_id: '', started: 0, finished: 99.5 })
    await Promise.all([ensureThresholds('lib-c'), ensureThresholds('lib-c')])
    expect(mockThresholds).toHaveBeenCalledTimes(1)
    await ensureThresholds('lib-c')
    expect(mockThresholds).toHaveBeenCalledTimes(1)
  })

  it('拉失败保持兜底值且**允许重试**（不写进「已加载」）', async () => {
    mockThresholds.mockRejectedValueOnce(new Error('offline'))
    await ensureThresholds('lib-d')
    expect(thresholdsFor('lib-d')).toEqual(FALLBACK)

    mockThresholds.mockResolvedValueOnce({ library_id: 'lib-d', started: 0, finished: 30 })
    await ensureThresholds('lib-d')
    expect(thresholdsFor('lib-d').finished).toBe(30)
  })
})

describe('阅读阈值 · 状态优先与兜底', () => {
  it('有真实状态行时以状态为准，阈值只管道进度那半', () => {
    // 20% 却手动标成 finished：显示「已读完」而不是「在读」
    expect(statusOf({ status: 'finished', percent: 20 })).toBe('finished')
    expect(statusLabelOf({ status: 'finished', percent: 20 })).toBe('已读完')
    // 没有状态行才看进度
    expect(statusOf({ status: null, percent: 20 })).toBe('reading')
    expect(statusLabelOf({ status: null, percent: 0 })).toBe('未读')
  })

  it('未知状态回空串（与改造前一致，不凭空造词）', () => {
    expect(statusLabelOf({ status: '什么状态', percent: 50 })).toBe('')
  })
})

describe('阅读阈值 · 在读到没读完', () => {
  it('翻过但没读完才算在读（两端都不含）', () => {
    expect(isInProgress(0)).toBe(false)
    expect(isInProgress(0.01)).toBe(true)
    expect(isInProgress(99.49)).toBe(true)
    expect(isInProgress(99.5)).toBe(false)
    expect(isInProgress(100)).toBe(false)
  })
})
