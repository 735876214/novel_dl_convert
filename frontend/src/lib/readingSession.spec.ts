import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SessionExtra } from '@/lib/api'
import {
  attachReaderClock,
  createSessionReporter,
  SESSION_GAP_SECONDS,
  SESSION_HEARTBEAT_MS,
  SESSION_MIN_SECONDS,
  type SessionSnapshot,
} from '@/lib/readingSession'

/**
 * 会话边界是「一次连续阅读 = 数据库里一行」这条契约的**唯一**执行处。
 *
 * 这里刻意不 mock 定时器去驱动：`accrue()` 由调用方喂秒数，`Date.now()` 只被
 * `pause/resume` 的间隔判定用到 —— 于是绝大多数用例是纯同步的，只有跨段判定要假时钟。
 */

/** 位置可以被用例任意改写，用来验证「起点只抓一次」 */
let here: SessionSnapshot = { percent: 10, locator: 2 }

function makeReporter(over: Partial<Parameters<typeof createSessionReporter>[0]> = {}) {
  const post = over.post ?? vi.fn().mockResolvedValue({})
  const reporter = createSessionReporter({
    snapshot: () => ({ ...here }),
    source: 'web',
    post,
    ...over,
  })
  return { reporter, post: post as ReturnType<typeof vi.fn> }
}

beforeEach(() => {
  here = { percent: 10, locator: 2 }
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()      // 可见性 spy（见下面 setVis）
})

describe('阅读会话边界 · 上报阈值', () => {
  it('不到阈值不上报，时长攒着', async () => {
    const { reporter, post } = makeReporter()
    reporter.begin()
    reporter.accrue(SESSION_MIN_SECONDS - 1)
    await reporter.flush()
    expect(post).not.toHaveBeenCalled()
    expect(reporter.pending).toBe(SESSION_MIN_SECONDS - 1)
  })

  it('到阈值就上报一次，带上 uid / 来源 / 两端位置', async () => {
    const { reporter, post } = makeReporter()
    reporter.begin()
    reporter.accrue(30)
    here = { percent: 25, locator: 4 }
    await reporter.flush()

    expect(post).toHaveBeenCalledTimes(1)
    const [secs, extra] = post.mock.calls[0] as [number, SessionExtra]
    expect(secs).toBe(30)
    expect(extra.session_uid).toBe(reporter.uid)
    expect(extra.session_uid).not.toBe('')
    expect(extra.source).toBe('web')
    expect(extra.start_percent).toBe(10)
    expect(extra.start_locator).toBe(2)
    expect(extra.end_percent).toBe(25)
    expect(extra.end_locator).toBe(4)
    expect(reporter.pending).toBe(0)
  })

  it('非正数 / NaN 不计入', () => {
    const { reporter } = makeReporter()
    reporter.begin()
    reporter.accrue(0)
    reporter.accrue(-5)
    reporter.accrue(Number.NaN)
    reporter.accrue(Number.POSITIVE_INFINITY)
    expect(reporter.pending).toBe(0)
  })

  it('没开段时什么都不发', async () => {
    const { reporter, post } = makeReporter()
    reporter.accrue(60)
    await reporter.flush()
    expect(post).not.toHaveBeenCalled()
    expect(reporter.uid).toBe('')
  })
})

describe('阅读会话边界 · 起点只抓一次', () => {
  it('第二次心跳报的是**开段时**的起点，不是上一次的终点', async () => {
    const { reporter, post } = makeReporter()
    reporter.begin()                       // 起点抓在 10%
    reporter.accrue(30)
    here = { percent: 25, locator: 4 }
    await reporter.flush()
    reporter.accrue(30)
    here = { percent: 40, locator: 6 }
    await reporter.flush()

    const second = post.mock.calls[1][1] as SessionExtra
    expect(second.start_percent).toBe(10)
    expect(second.end_percent).toBe(40)
    expect(second.session_uid).toBe((post.mock.calls[0][1] as SessionExtra).session_uid)
  })
})

describe('阅读会话边界 · 失败与分段', () => {
  it('上报失败时长留到下一次，且仍是同一段（同一行）', async () => {
    const post = vi.fn()
      .mockRejectedValueOnce(new Error('离线'))
      .mockResolvedValue({})
    const { reporter } = makeReporter({ post })
    reporter.begin()
    reporter.accrue(30)
    await reporter.flush()
    expect(reporter.pending).toBe(30)

    const uid = reporter.uid
    reporter.accrue(30)
    await reporter.flush()
    expect(post).toHaveBeenCalledTimes(2)
    expect(post.mock.calls[1][0]).toBe(60)         // 失败那次没丢
    expect((post.mock.calls[1][1] as SessionExtra).session_uid).toBe(uid)
    expect(reporter.pending).toBe(0)
  })

  /**
   * 换书那条路是 `void stop(); load() → begin()` —— `stop()` 的收尾还没跑完，新段就已经开了。
   * 收尾若在 await 之后才清 uid，就会把新段的 uid 一起抹掉：新书从此**一秒都不上报**，
   * 而且没有任何报错（只是日志页永远少一段，没人查得出来）。
   */
  it('stop() 不 await 就紧接着 begin()：新段的 uid 不被收尾抹掉', async () => {
    const { reporter, post } = makeReporter()
    reporter.begin()
    reporter.accrue(30)
    void reporter.stop()              // 故意不等
    reporter.begin()
    const uid = reporter.uid
    expect(uid).not.toBe('')
    // 等 stop 的收尾（await 之后那几句）跑完再看 —— 它若清了新段的 uid，下面的 flush 会发不出去
    await new Promise((r) => setTimeout(r, 0))
    expect(reporter.uid).toBe(uid)

    reporter.accrue(30)
    await reporter.flush()
    expect((post.mock.calls.at(-1)![1] as SessionExtra).session_uid).toBe(uid)
    expect(post.mock.calls.at(-1)![0]).toBe(30)
  })

  it('stop() 之后是新的一段：uid 换新，两段互不覆盖', async () => {
    const { reporter, post } = makeReporter()
    reporter.begin()
    const first = reporter.uid
    reporter.accrue(30)
    await reporter.stop()
    expect(post).toHaveBeenCalledTimes(1)

    reporter.begin()
    expect(reporter.uid).not.toBe(first)
    reporter.accrue(30)
    await reporter.flush()
    expect((post.mock.calls[1][1] as SessionExtra).session_uid).not.toBe(first)
  })

  /**
   * 换书那条路是 `void flush()`（不等）→ `begin()`，于是**请求还在路上时段就换了**。
   * 这时失败回调里的「留到下次」必须判定「这一段还开着吗」—— 判漏了，上一本书的时长
   * 会记到下一本头上（一处静默错账，界面上永远看不出来）。
   */
  it('上报还在路上时换了段：失败的那几秒不回灌到新段', async () => {
    let fail!: (e: Error) => void
    const post = vi.fn()
      // 只有第一次挂住（模拟「还在路上」）；后续照常成功，别让用例干等超时
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject }))
      .mockResolvedValue({})
    const { reporter } = makeReporter({ post })
    reporter.begin()
    reporter.accrue(30)
    const inFlight = reporter.flush()      // 请求发出去，还没回来
    reporter.begin()                       // 段已经换了
    expect(reporter.pending).toBe(0)
    fail(new Error('离线'))
    await inFlight
    expect(reporter.pending).toBe(0)       // 上一段的 30 秒不能落到新段

    reporter.accrue(30)
    await reporter.flush()
    expect(post.mock.calls.at(-1)![0]).toBe(30)
  })
})

describe('阅读会话边界 · 切后台的间隔判定', () => {
  it('短切（看眼别的标签页）仍是同一段', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-27T10:00:00Z'))
    const { reporter } = makeReporter()
    reporter.begin()
    const uid = reporter.uid

    reporter.pause()
    vi.setSystemTime(new Date(Date.now() + 60 * 1000))
    reporter.resume()
    expect(reporter.uid).toBe(uid)
  })

  it('离开超过阈值就是两段了', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-27T10:00:00Z'))
    const { reporter } = makeReporter()
    reporter.begin()
    const uid = reporter.uid

    reporter.pause()
    vi.setSystemTime(new Date(Date.now() + (SESSION_GAP_SECONDS + 1) * 1000))
    reporter.resume()
    expect(reporter.uid).not.toBe(uid)
    expect(reporter.uid).not.toBe('')
  })

  it('没 pause 过的 resume 不会平白分段', () => {
    const { reporter } = makeReporter()
    reporter.begin()
    const uid = reporter.uid
    reporter.resume()
    expect(reporter.uid).toBe(uid)
  })
})

describe('阅读会话边界 · 可选字段', () => {
  it('file_rel 只在给得出来的时候才带（单文件书不带）', async () => {
    const { reporter, post } = makeReporter()
    reporter.begin()
    reporter.accrue(30)
    await reporter.flush()
    expect('file_rel' in (post.mock.calls[0][1] as SessionExtra)).toBe(false)

    const withRel = makeReporter({ fileRel: () => '有声书/第 3 轨.mp3' })
    withRel.reporter.begin()
    withRel.reporter.accrue(30)
    await withRel.reporter.flush()
    expect((withRel.post.mock.calls[0][1] as SessionExtra).file_rel).toBe('有声书/第 3 轨.mp3')
  })

  it('fileRel 返回 undefined 时不带该字段（不是空串）', async () => {
    const { reporter, post } = makeReporter({ fileRel: () => undefined })
    reporter.begin()
    reporter.accrue(30)
    await reporter.flush()
    expect('file_rel' in (post.mock.calls[0][1] as SessionExtra)).toBe(false)
  })

  it('uid 不用 crypto.randomUUID（局域网明文访问下它不存在）', () => {
    const original = globalThis.crypto
    // 模拟安全上下文之外的浏览器：只有 getRandomValues，没有 randomUUID
    vi.stubGlobal('crypto', { getRandomValues: original.getRandomValues.bind(original) })
    try {
      const { reporter } = makeReporter()
      reporter.begin()
      expect(reporter.uid).toMatch(/^[0-9a-f]{16}$/)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('连 getRandomValues 都没有时仍有可用的 uid', () => {
    vi.stubGlobal('crypto', undefined)
    try {
      const { reporter } = makeReporter()
      reporter.begin()
      expect(reporter.uid.length).toBeGreaterThan(8)
    } finally {
      vi.unstubAllGlobals()
    }
  })
})

/**
 * 这一组是**整个会话链路上唯一的 DOM 接触点**（`visibilityState` + 定时器）。
 * 三个阅读器（EPUB/TXT、PDF、漫画）都靠它，所以口径在这里钉死。
 */
describe('阅读器计时管线 · attachReaderClock', () => {
  /** 模拟浏览器可见性。happy-dom 的 `visibilityState` 是只读 getter，只能这样改 */
  function setVis(v: 'visible' | 'hidden'): void {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue(v)
    document.dispatchEvent(new Event('visibilitychange'))
  }

  it('心跳间隔是 30 秒 —— 它是「浏览器崩了最多丢多少」的上界，别改小', () => {
    expect(SESSION_HEARTBEAT_MS).toBe(30_000)
  })

  it('前台每 30 秒报一次，秒数如实累计', () => {
    vi.useFakeTimers()
    const { reporter, post } = makeReporter()
    reporter.begin()
    const clock = attachReaderClock(reporter)

    vi.advanceTimersByTime(30_000)
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][0]).toBe(30)
    vi.advanceTimersByTime(60_000)
    expect(post).toHaveBeenCalledTimes(3)
    expect(post.mock.calls[2][0]).toBe(30)
    clock.detach()
  })

  /**
   * 这条盯的是一个真实发生过的少算：`visibilitychange` 是在状态**已经变了之后**才派发的，
   * 所以「切后台」那次回调里读 `document.visibilityState` 拿到的已经是 `hidden`。
   * 若按「当前可见性」结算，从上次心跳到切后台之间的这 20 秒会被判成 0 秒 ——
   * 每次切标签页静默吞掉一段，而且因为数偏小，没有任何症状能让人发现。
   */
  it('切后台那一刻，把距上次心跳的这段（不足 30 秒）也算进去', () => {
    vi.useFakeTimers()
    const { reporter, post } = makeReporter()
    reporter.begin()
    const clock = attachReaderClock(reporter)

    vi.advanceTimersByTime(20_000)
    expect(post).not.toHaveBeenCalled()        // 还不到心跳点
    setVis('hidden')                            // 事件派发时状态**已经**是 hidden 了
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][0]).toBe(20)      // ← 按「当前可见性」结算的话这里是 0，一次上报都不会发生
    clock.detach()
  })

  it('后台待着不算时长（心跳照发但只结算可见的那部分）', () => {
    vi.useFakeTimers()
    const { reporter, post } = makeReporter()
    reporter.begin()
    const clock = attachReaderClock(reporter)

    setVis('hidden')
    vi.advanceTimersByTime(600_000)             // 后台待 10 分钟
    expect(post).not.toHaveBeenCalled()
    setVis('visible')
    vi.advanceTimersByTime(30_000)
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][0]).toBe(30)      // 后台那 10 分钟一秒都没算进来
    clock.detach()
  })

  it('onHidden 只在切到后台时调一次，回到前台不再调', () => {
    vi.useFakeTimers()
    const onHidden = vi.fn()
    const { reporter } = makeReporter()
    reporter.begin()
    const clock = attachReaderClock(reporter, { onHidden })

    setVis('hidden')
    expect(onHidden).toHaveBeenCalledTimes(1)
    setVis('visible')
    setVis('hidden')
    expect(onHidden).toHaveBeenCalledTimes(2)
    clock.detach()
  })

  it('accrue() 手动结账：收尾时最后这几秒不丢', () => {
    vi.useFakeTimers()
    const { reporter, post } = makeReporter()
    reporter.begin()
    const clock = attachReaderClock(reporter)

    vi.advanceTimersByTime(12_000)
    expect(post).not.toHaveBeenCalled()          // 12 秒还不到心跳点
    clock.accrue()                               // stopSession 收尾前那一句
    void reporter.flush()
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][0]).toBe(12)
    clock.detach()
  })

  it('detach 之后心跳与可见性监听都不再动弹（否则离开阅读器还在偷偷计时）', () => {
    vi.useFakeTimers()
    const { reporter, post } = makeReporter()
    reporter.begin()
    const clock = attachReaderClock(reporter)

    vi.advanceTimersByTime(30_000)
    expect(post).toHaveBeenCalledTimes(1)
    clock.detach()

    vi.advanceTimersByTime(180_000)
    setVis('hidden')
    setVis('visible')
    expect(post).toHaveBeenCalledTimes(1)
  })
})
