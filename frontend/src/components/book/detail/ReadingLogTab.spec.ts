import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReadingLogTab from '@/components/book/detail/ReadingLogTab.vue'
import { api, type BookReadingStats, type ReadingAttempt, type ReadingSessionRow } from '@/lib/api'

/**
 * 「阅读日志」标签。三条纪律在这个页面上最容易破，所以每条都有一条用例盯着：
 *
 * 1. **不造假数据** —— 老会话的 `change` 是 `null`（进度快照补不回来），
 *    必须显示「—」；显示 0% 会被读成「这一段没往前走」。同理「页数不可信时不显示
 *    速度」「没有连续记录时不显示那一格」。
 * 2. **每块自己判空** —— 重读轮次与阅读会话是两回事：一本从没在网页上打开过的书
 *    （纸质书 / 别的设备读的）没有会话，却可以有轮次。
 * 3. **不点开就不拉** —— 详情页是高频入口，那个 ECharts chunk 800 kB 量级。
 */
vi.mock('@/lib/api', () => ({
  api: {
    bookReadingStats: vi.fn(),
    readingAttempts: vi.fn(),
    startReadingAttempt: vi.fn(),
    finishReadingAttempt: vi.fn(),
    backfillReadingAttempts: vi.fn(),
  },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const m = {
  stats: vi.mocked(api.bookReadingStats),
  attempts: vi.mocked(api.readingAttempts),
}

const BOOK_ID = 'lib$aaa'

function makeSession(over: Partial<ReadingSessionRow> = {}): ReadingSessionRow {
  return {
    id: 1,
    seconds: 1800,
    started_at: Date.parse('2026-09-20T21:00:00') / 1000,
    ended_at: Date.parse('2026-09-20T21:30:00') / 1000,
    start_percent: 10,
    end_percent: 22,
    change: 12,
    start_locator: 3,
    end_locator: 5,
    file_rel: '',
    source: 'web',
    ...over,
  }
}

function makeStats(over: Partial<BookReadingStats> = {}): BookReadingStats {
  return {
    book_id: BOOK_ID,
    reading: {
      seconds: 7200,
      sessions: 4,
      avg_seconds: 1800,
      active_days: 3,
      first_started: Date.parse('2026-09-18T20:00:00') / 1000,
      last_ended: Date.parse('2026-09-20T21:30:00') / 1000,
    },
    records: {
      longest_session: { seconds: 3600, ended_at: 0, date: '2026-09-19' },
      best_day: { date: '2026-09-19', seconds: 3600, sessions: 2, end_percent: 60 },
      busiest_day: { date: '2026-09-20', seconds: 1800, sessions: 3, end_percent: 22 },
      longest_streak: { days: 3, start: '2026-09-18', end: '2026-09-20' },
    },
    days: [{ date: '2026-09-20', seconds: 1800, sessions: 1, end_percent: 22 }],
    sessions: [makeSession()],
    ...over,
  }
}

function makeAttempt(over: Partial<ReadingAttempt> = {}): ReadingAttempt {
  return {
    id: 1,
    book_id: BOOK_ID,
    round: 1,
    started_at: Date.parse('2026-09-18T20:00:00') / 1000,
    finished_at: 0,
    ...over,
  }
}

async function mountTab(props: Record<string, unknown> = {}): Promise<VueWrapper> {
  const w = mount(ReadingLogTab, {
    props: { bookId: BOOK_ID, active: true, ...props },
    global: { plugins: [createPinia()] },
  })
  await flushPromises()
  return w
}

/** 渲染出来的每个统计格的标签（`StatTile` 的 label 是每个格子里唯一稳定的一段文字） */
function has(w: VueWrapper, text: string): boolean {
  return w.text().includes(text)
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  m.stats.mockResolvedValue(makeStats())
  m.attempts.mockResolvedValue({ items: [makeAttempt()], total: 1, current: 1 })
})

describe('阅读日志 · 不点开就不拉', () => {
  it('active 为 false 时一个请求都不发（ECharts chunk 同理不下载）', async () => {
    await mountTab({ active: false })
    expect(m.stats).not.toHaveBeenCalled()
    expect(m.attempts).not.toHaveBeenCalled()
  })

  it('active 变 true 才拉，且只拉一次', async () => {
    const w = mountTab({ active: false })
    const v = await w
    expect(m.stats).not.toHaveBeenCalled()

    await v.setProps({ active: true })
    await flushPromises()
    expect(m.stats).toHaveBeenCalledTimes(1)
    expect(m.stats).toHaveBeenCalledWith(BOOK_ID)
  })
})

describe('阅读日志 · 没有会话不等于没有这一页', () => {
  /** `reading: null` 是服务端对「这本书从没读过」的**明确回答**，不是加载失败 */
  it('从没读过 → 空态文案，且不渲染任何统计格', async () => {
    m.stats.mockResolvedValue(makeStats({ reading: null, records: null, days: [], sessions: [] }))
    const w = await mountTab()

    expect(has(w, '还没有阅读记录')).toBe(true)
    expect(has(w, '累计时长')).toBe(false)
    expect(has(w, '阅读之最')).toBe(false)
  })

  /**
   * 这条盯的是「拿会话去闸轮次」那个错误：标记「在读」会开一轮，而用户可能压根没在
   * 网页上打开过这本书（纸质书 / 别的设备）。两块的数据源不同，闸在一起就会凭空少一块。
   */
  it('没有会话但**有轮次**时，重读面板照常渲染', async () => {
    m.stats.mockResolvedValue(makeStats({ reading: null, records: null, days: [], sessions: [] }))
    const w = await mountTab()

    expect(has(w, '还没有阅读记录')).toBe(true)
    expect(has(w, '阅读尝试 / 重读')).toBe(true)
    expect(has(w, '第 1 轮')).toBe(true)
  })

  it('没有轮次时给出空态与「从历史补录」出口', async () => {
    m.attempts.mockResolvedValue({ items: [], total: 0, current: 0 })
    const w = await mountTab()
    expect(has(w, '还没有轮次记录')).toBe(true)
    expect(has(w, '从历史补录')).toBe(true)
  })

  /**
   * 空态是一句**断言**（「这本书没有轮次」），只有拿到答案才配说。
   * `attemptsLoaded` 若在发请求**之前**就置位，这里会先闪一句「还没有轮次记录」，
   * 再被真的列表顶掉 —— 与 `loading` 初值为 `true` 是同一条纪律的两处。
   */
  it('轮次还没拉到时不说「还没有轮次记录」（空态要等请求落地）', async () => {
    let release!: (v: { items: ReadingAttempt[]; total: number; current: number }) => void
    m.attempts.mockReturnValue(new Promise((r) => (release = r)))

    const w = await mountTab()
    // 统计已经回来了、轮次还挂着：面试题就是这一刻
    expect(has(w, '阅读尝试 / 重读')).toBe(true)
    expect(has(w, '还没有轮次记录')).toBe(false)

    release({ items: [], total: 0, current: 0 })
    await flushPromises()
    expect(has(w, '还没有轮次记录')).toBe(true)
  })
})

describe('阅读日志 · 未知不写成 0', () => {
  /**
   * 第 63 期之前的会话没有进度快照，`change` 是 `null`。显示 0% 会被读成
   * 「这一段读回原处了」—— 与「没记过」是两个结论（见 `db._session_row`）。
   */
  it('change 为 null 的行显示「—」，且不出现伪造的 0%', async () => {
    m.stats.mockResolvedValue(
      makeStats({
        // start_percent 未知 ⇒ 服务端 change 也是 null；end_percent 已知 ⇒ 位置列有值，
        // 于是「—」只可能来自 CHANGE 那一列
        sessions: [makeSession({ start_percent: null, change: null, end_percent: 40 })],
      }),
    )

    // 断言收在**这一格**里。两个坑都踩过了：按全文数「—」的个数会被说明文字里的
    // 「——」搅乱；按整行断言 `不含 '0%'` 则被同一行的位置列 `40%` 绊倒（它含子串 `0%`）
    const w = await mountTab()
    expect(w.find('[data-test="session-change"]').text()).toBe('—')
    expect(w.find('[data-test="session-row"]').text()).toContain('40%')
  })

  it('已知 change 如实带符号显示', async () => {
    m.stats.mockResolvedValue(makeStats({ sessions: [makeSession({ change: 12.5 })] }))
    const w = await mountTab()
    expect(w.find('[data-test="session-change"]').text()).toBe('+12.5%')
  })

  it('没有连续记录（longest_streak 为 null）时那一格不渲染', async () => {
    const s = makeStats()
    m.stats.mockResolvedValue(
      makeStats({ records: { ...s.records!, longest_streak: null } }),
    )
    const w = await mountTab()

    expect(has(w, '阅读之最')).toBe(true)
    expect(has(w, '最长的一次')).toBe(true)
    expect(has(w, '最长连续')).toBe(false)
  })

  /** PDF / 有声书的 `pages` 恒 0（「不知道」不是「0 页」），照算会得出 0 或无穷页/小时 */
  it('页数不可信时「阅读速度」那一格不渲染', async () => {
    const w = await mountTab({ pages: 0, pagesSource: '' })
    expect(has(w, '阅读速度')).toBe(false)

    const w2 = await mountTab({ pages: 300, pagesSource: 'estimate' })
    expect(has(w2, '阅读速度')).toBe(true)
    expect(has(w2, '估算页数')).toBe(true)
  })
})

describe('阅读日志 · 失败与空态分开', () => {
  it('接口失败 → 给重试，而不是「还没有阅读记录」', async () => {
    m.stats.mockRejectedValue(new Error('后端挂了'))
    const w = await mountTab()

    expect(has(w, '阅读记录加载失败')).toBe(true)
    expect(has(w, '重试')).toBe(true)
    expect(has(w, '还没有阅读记录')).toBe(false)
  })

  it('重试按钮真的会再拉一次', async () => {
    m.stats.mockRejectedValueOnce(new Error('后端挂了'))
    m.stats.mockResolvedValue(makeStats())
    const w = await mountTab()
    expect(has(w, '阅读记录加载失败')).toBe(true)

    await w.findAll('button').find((b) => b.text() === '重试')!.trigger('click')
    await flushPromises()
    expect(has(w, '累计时长')).toBe(true)
  })
})
