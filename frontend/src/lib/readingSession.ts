/**
 * 阅读会话边界（第 63 期）。
 *
 * **一次连续阅读 = 一个 session_uid = 数据库里一行。** 30 秒心跳照旧发，但只更新那一行，
 * 而不是每 30 秒插一行 —— 读两小时从 240 行变成 1 行，而**抗浏览器崩溃的代价一点没变**
 * （崩了最多丢最后 30 秒，与改造之前一致）。
 *
 * 为什么不改成「进阅读器时开一段、离开时写一行」：那样整段阅读押在一条 INSERT 上，
 * 浏览器崩了 / 关标签页 / 网断了，那一两个小时**凭空消失**。心跳的冗余是故意的，
 * 别把它「优化」掉。
 *
 * 这个文件只管**边界与累计**，不直接调 api：
 * - 什么时候算「在读」由调用方决定（阅读器看 `visibilityState`，播放器看 play/pause），
 *   累出来的秒数交给 `accrue()`；
 * - 怎么发由调用方注入（`post`），于是这里可以在单测里完全脱离网络驱动。
 *
 * 底下那个 `attachReaderClock()` 是**唯一的 DOM 接触点**（读 `visibilityState` +
 * 定时器），刻意只此一处 —— 三个阅读器各写一遍的话，切后台那一刻的结算口径
 * 迟早会在其中一处走样。
 */
import type { SessionExtra } from '@/lib/api'

/** 「离开多久算这一次阅读结束了」：切标签页看一眼不算，去干别的三小时算。 */
export const SESSION_GAP_SECONDS = 30 * 60

/** 不足这么多秒不上报 —— 翻两页就走一次写库不值得（既有阈值，别放宽）。 */
export const SESSION_MIN_SECONDS = 5

/** 此刻的位置。字段缺省 = **这次没位置可报**（服务端记「未知」，不是 0%）。 */
export interface SessionSnapshot {
  /** 全书百分比 0–100 */
  percent?: number
  /** 章节 / 音轨序号 */
  locator?: number
}

/** 带时刻的一笔待上报时长（内部结构）。 */
interface SessionState {
  uid: string
  pending: number
  start: SessionSnapshot | null
  /** 离开的时刻（`pause()` 记下）；0 = 当前不在离开状态 */
  idleSince: number
}

export interface SessionReporterOptions {
  /** 发一次上报。抛错 = 这次没送达，时长留待下一次 */
  post: (seconds: number, extra: SessionExtra) => Promise<unknown>
  /** 取**此刻**的位置。开段时也用它抓起点，所以它必须读的是实时位置而非闭包快照 */
  snapshot: () => SessionSnapshot
  /** `web`（阅读器）/ `audio`（播放器） */
  source: string
  /** **书内**相对路径（多轨有声书的当前轨）。空串 = 这本书自己，单文件书不必给 */
  fileRel?: () => string | undefined
  minSeconds?: number
  gapSeconds?: number
}

export interface SessionReporter {
  /** 开新的一段：铸新 uid、抓起点、清零累计。**重复调用 = 丢掉上一段未上报的时长** */
  begin: () => void
  /** 累计一段前台时长（秒）。调用方保证「只有在读的时候」才加 */
  accrue: (seconds: number) => void
  /** 记为「离开」（切后台）。通常紧跟一次 `flush()` */
  pause: () => void
  /** 回来。离开超过阈值 ⇒ 上一段已经结束，开新的一段 */
  resume: () => void
  /** 上报（不足阈值 / 没开段就什么都不做） */
  flush: () => Promise<void>
  /** 结束这一段：先 flush，然后作废 uid */
  stop: () => Promise<void>
  /** 只读：当前段 id（空串 = 没开段） */
  readonly uid: string
  /** 只读：还没上报出去的秒数 */
  readonly pending: number
}

/**
 * 会话 id。
 *
 * ⚠️ **刻意不用 `crypto.randomUUID()`**：它是**安全上下文限定**的，而本应用常以
 * `http://192.168.x.x:8992` 这种局域网明文地址访问 —— 那里 `crypto.randomUUID` 直接
 * 不存在，一调就是 `TypeError`（在 localhost 上开发时永远发现不了）。
 * `getRandomValues` 没有这个限制；再退一步 `Math.random` 也够用 ——
 * 这个 id 只需在**一本书之内**不重复，服务端还按 `(book_id, session_uid)` 建了唯一索引。
 */
function newUid(): string {
  const c = globalThis.crypto
  if (c && typeof c.getRandomValues === 'function') {
    const b = new Uint8Array(8)
    c.getRandomValues(b)
    return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  }
  return `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

export interface ReaderClock {
  /** 立刻按当前可见性结一次账（收尾前调一次，别把最后几秒丢掉） */
  accrue: () => void
  /** 清掉定时器与监听 */
  detach: () => void
}

/** 阅读器的心跳间隔（既有值，别改小 —— 它是「浏览器崩了最多丢多少」的上界） */
export const SESSION_HEARTBEAT_MS = 30000

/**
 * 给「阅读器型」界面接上计时：**前台可见才累计**，每 30 秒心跳一次。
 *
 * 三个阅读器（EPUB/TXT、PDF、漫画）是同一套口径，共用这一份实现。分开写三遍的话，
 * 下面 `wasVisible` 那条极易在某一处走样 —— 那是一种只在「频繁切标签页」时才显形的
 * 少算，没人会去查。
 *
 * **播放器不用它**：音频切到后台照常在放，那就是在听（见 `AudioPlayer.vue`），
 * 判据是「音频在不在播」而不是「页面可不可见」。
 */
export function attachReaderClock(
  session: SessionReporter,
  o: { onHidden?: () => void; intervalMs?: number } = {},
): ReaderClock {
  let lastTick = Date.now()
  /**
   * 上一次已知的可见性。
   *
   * ⚠️ **不能直接读 `document.visibilityState` 来判断刚过去的这段时间算不算阅读**：
   * `visibilitychange` 是在状态**已经变了之后**才派发的，所以「切后台」那一次回调里
   * 读到的已经是 `hidden` —— 从上次心跳到切后台之间的这段时间（最多 30 秒）明明是可见的，
   * 却被判成 0 秒。每次切标签页静默吞掉一段，而且因为数偏小，没人查得出来。
   */
  let wasVisible = document.visibilityState === 'visible'

  const accrue = (): void => {
    const now = Date.now()
    if (wasVisible) session.accrue((now - lastTick) / 1000)
    lastTick = now
  }

  const onVisibility = (): void => {
    accrue()                                              // 先按旧状态把这笔账结掉
    wasVisible = document.visibilityState === 'visible'
    if (wasVisible) {
      session.resume()
      return
    }
    o.onHidden?.()
    // 切后台算「离开」但不算「走人」：短切回来仍是同一段（见 `resume()` 的间隔判定）
    session.pause()
    void session.flush()
  }

  const timer = window.setInterval(() => {
    accrue()
    void session.flush()
  }, o.intervalMs ?? SESSION_HEARTBEAT_MS)
  document.addEventListener('visibilitychange', onVisibility)

  return {
    accrue,
    detach: () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    },
  }
}

export function createSessionReporter(o: SessionReporterOptions): SessionReporter {
  const minSeconds = o.minSeconds ?? SESSION_MIN_SECONDS
  const gapSeconds = o.gapSeconds ?? SESSION_GAP_SECONDS
  const st: SessionState = { uid: '', pending: 0, start: null, idleSince: 0 }

  function begin(): void {
    st.uid = newUid()
    st.start = o.snapshot()
    st.pending = 0
    st.idleSince = 0
  }

  function accrue(seconds: number): void {
    if (Number.isFinite(seconds) && seconds > 0) st.pending += seconds
  }

  function pause(): void {
    st.idleSince = Date.now()
  }

  function resume(): void {
    // 短切（去别的标签页看一眼）仍算同一次阅读；离开够久就是两段了 ——
    // 上一段在 `pause()` 那次 flush 里已经落库，这里只是开一段新的接上
    if (st.idleSince && (Date.now() - st.idleSince) / 1000 >= gapSeconds) begin()
    else st.idleSince = 0
  }

  async function flush(): Promise<void> {
    if (!st.uid || st.pending < minSeconds) return
    const secs = Math.round(st.pending)
    if (secs <= 0) return
    const here = o.snapshot()
    const extra: SessionExtra = {
      session_uid: st.uid,
      // 起点**只在开段时抓的那一次**：它是「本次读了多少」的被减数。
      // 服务端也不会用后续心跳覆盖它（见 db.upsert_session）。
      start_percent: st.start?.percent,
      start_locator: st.start?.locator,
      end_percent: here.percent,
      end_locator: here.locator,
      source: o.source,
    }
    const rel = o.fileRel?.()
    if (rel) extra.file_rel = rel

    const uid = st.uid
    st.pending = 0
    try {
      await o.post(secs, extra)
    } catch {
      // 没送达就留到下一次 —— 但**只在这一段还开着的时候**：段已经换了（stop / 离开太久）
      // 就把这几秒丢掉，否则上一段（甚至上一本书）的时长会记到新段头上
      if (st.uid === uid) st.pending += secs
    }
  }

  async function stop(): Promise<void> {
    // ⚠️ 顺序要紧：先把这一段（uid + 秒数）同步交出去，**再**清空，最后才等上报回来。
    // 反过来写成 `await flush(); 清空` 的话 —— 换书那条路是 `void stop()` 紧跟
    // `begin()`，等回来的这一句会把**新段**的 uid 一起抹掉，新书从此一秒都不上报，
    // 而且悄无声息（没报错、没日志，只是日志页永远少一段）。
    const sent = flush()
    st.uid = ''
    st.pending = 0
    st.start = null
    st.idleSince = 0
    await sent
  }

  return {
    begin,
    accrue,
    pause,
    resume,
    flush,
    stop,
    get uid() {
      return st.uid
    },
    get pending() {
      return st.pending
    },
  }
}
