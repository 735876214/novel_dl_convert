/**
 * 阅读阈值（第 40 期）：`reading.started_threshold` / `reading.finished_threshold`。
 *
 * ## 为什么要有这个文件
 *
 * 改造前「按百分比推阅读状态」这段逻辑在**三个地方各写了一遍**：
 * `lib/bookInfo.ts` 的 `statusLabel`、`stores/library.ts` 的 `derivedStatus`、
 * `lib/smartScope.ts` 的 `statusOf`（外加 ShelfView / BookCover / 两个仪表盘部件
 * 各自写死的 `99.5`）。阈值写死的时候三份拷贝还能勉强同步；阈值一可配，
 * 三份拷贝就是**三个真相源** —— 用户把阈值改成 50%，书架上显示「已读完」、
 * 统计页显示「在读」，谁都不知道该信哪个。
 *
 * 所以这里做两件事：
 * 1. `statusFromPercent` —— **纯函数**，唯一的判定口径；
 * 2. `thresholdsFor` / `ensureThresholds` —— 阈值本身的**前端唯一入口**
 *    （存储与校验都在服务端 `core/lib_settings.reading_thresholds`，这里只取一次 + 缓存）。
 *
 * ⚠️ 别再在界面里写死 `99.5` / `> 0`；`test:unit` 里有一条守卫用例盯着这件事。
 */
import { reactive } from 'vue'

import { api } from './api'

/** 阅读状态三态（与后端 `db.READ_STATUSES` 的前三个对齐，不含 paused/abandoned）。 */
export type DerivedStatus = 'unread' | 'reading' | 'finished'

export interface Thresholds {
  /** 进度**高于**该值即算「在读」（0–100） */
  started: number
  /** 进度**达到**该值即算「已读完」（0–100） */
  finished: number
}

/**
 * 取到服务端值之前的兜底 = 后端 `config.DEFAULTS` 的默认值。
 *
 * ⚠️ 刻意与后端**逐字节相同**：不同就会出现「首屏按 A 判、拉到数据后跳成 B」的闪烁。
 * 后端改了默认值这里也得改 —— 有守卫用例比对两边。
 */
export const FALLBACK: Thresholds = { started: 0, finished: 99.5 }

/**
 * 阈值缓存：`''` 是全局值，其余键是库 id 的**生效值**。
 *
 * 用 `reactive` 而不是普通对象 —— 判定结果要进 `computed`，
 * 阈值异步到达时必须让依赖它的界面自己重算，而不是等用户手动刷新。
 */
const cache = reactive<Record<string, Thresholds>>({ '': { ...FALLBACK } })

/** 已经**真的拉到过**服务端值的 key（与 `cache` 分开：`cache` 里预先放着兜底值）。 */
const loaded = new Set<string>()

/** 正在飞的请求（同一 key 并发调用只发一次）。 */
const inflight: Record<string, Promise<void>> = {}

/** 某库（不传 = 全局）的**当前**阈值；没取到过就是兜底值。 */
export function thresholdsFor(libraryId = ''): Thresholds {
  return cache[libraryId] ?? cache[''] ?? FALLBACK
}

/**
 * 拉一次阈值并缓存（幂等：已取到过就直接返回；同一 key 并发只发一个请求）。
 *
 * `force` 用于「用户刚在设置页改完阈值」的场景 —— 不透传 force 的话，
 * 设置页存完了界面还按旧值判，看起来就像没生效。
 */
export function ensureThresholds(libraryId = '', force = false): Promise<void> {
  const key = libraryId || ''
  if (!force && loaded.has(key)) return Promise.resolve()
  const pending = inflight[key]
  if (!force && pending) return pending

  const p = api
    .readingThresholds(key)
    .then((r) => {
      cache[key] = { started: Number(r.started) || 0, finished: Number(r.finished) || 0 }
      loaded.add(key)
    })
    .catch(() => {
      // 取不到就保持兜底值：口径宁可退回默认，也不能让整个书架渲染不出来。
      // ⚠️ 不写进 `loaded` —— 下次调用要能重试。
    })
    .finally(() => {
      if (inflight[key] === p) delete inflight[key]
    })
  inflight[key] = p
  return p
}

/**
 * 阈值被改过 ⇒ 重新拉一次（**全局配置或每库覆写存盘之后必须调**）。
 *
 * 刻意**不先清缓存**：清掉会让界面在请求返回前退回兜底值（99.5）再跳回来，
 * 用户会看到一次假闪烁。旧值多留一瞬，比跳一下好。
 */
export function refreshThresholds(libraryId = ''): Promise<void> {
  return ensureThresholds(libraryId, true)
}

/** 纯判定：进度百分比 → 三态。**全前端唯一的这一段逻辑。** */
export function statusFromPercent(p: number | null | undefined, t: Thresholds = FALLBACK): DerivedStatus {
  const pct = Number(p ?? 0)
  if (!Number.isFinite(pct)) return 'unread'
  if (pct >= t.finished) return 'finished'
  return pct > t.started ? 'reading' : 'unread'
}

/**
 * 一本书的状态：**真实状态行优先**，没有状态行（`status` 为 null / 空）才按进度兜底。
 *
 * 这条优先级是后端 `stats.overview` 的同一条（有状态行时状态是权威，阈值只管兜底）；
 * 两边不一致就会出现「统计说已读完、书架说在读」。
 */
export function statusOf(
  b: { status?: string | null; percent?: number | null },
  libraryId = '',
): DerivedStatus | string {
  if (b.status) return b.status
  return statusFromPercent(b.percent, thresholdsFor(libraryId))
}

/**
 * 把一本书收敛到**筛选三档**（未读 / 在读 / 已读完），**真实状态优先**。
 *
 * 与 `statusOf` 同源（`status` 有值即以它为权威），但把 5 状态压成 3 档：
 * `finished` → 已读完；`reading` / `paused` / `abandoned` → 在读
 *（过滤器 UI 仅三档，已开始的都进「在读」桶）；没有状态行时按进度阈值兜底
 *（percent 够高也判「已读完」）。
 *
 * 第 41 期新增：`ShelfView` 的「阅读状态」筛选与 `BookCover` 角标改用它，
 * 与书卡文案（`statusLabelOf`）口径统一 —— 手动标「已读完」后筛选与角标都认。
 */
export function statusBucket(
  b: { status?: string | null; percent?: number | null },
  libraryId = '',
): DerivedStatus {
  const s = b.status
  if (s) {
    if (s === 'finished') return 'finished'
    // reading / paused / abandoned：已开始的都进「在读」桶
    return 'reading'
  }
  return statusFromPercent(b.percent, thresholdsFor(libraryId))
}

/** 中文文案（`lib/bookInfo.ts` 的 `statusLabel` 与它同源）。 */
const LABELS: Record<string, string> = {
  unread: '未读',
  reading: '在读',
  finished: '已读完',
  paused: '搁置',
  abandoned: '弃读',
}

/** 状态 → 中文文案（未知状态回空串，与改造前的行为一致）。 */
export function statusLabelOf(
  b: { status?: string | null; percent?: number | null },
  libraryId = '',
): string {
  return LABELS[statusOf(b, libraryId)] ?? ''
}

/**
 * **只看进度**的文案（不看 `b.status`）—— 给拿不到库上下文的通用组件用（如 `BookCover`）。
 *
 * 与 `statusLabelOf` 的差别是真实存在的历史事实（见文件头「三份拷贝」）：
 * 封面角标一直只看进度。本期只收敛阈值，**不顺手改判据**。
 * 默认按**全局**阈值判（拿不到库上下文的跨库组件，全局值是唯一说得通的口径）。
 */
export function percentLabel(p: number | null | undefined, libraryId = ''): string {
  return LABELS[statusFromPercent(p, thresholdsFor(libraryId))] ?? ''
}

/** 在读书的判据：翻过、但还没读完（`stores/library.ts` 的「继续阅读」用它）。 */
export function isInProgress(p: number | null | undefined, libraryId = ''): boolean {
  const t = thresholdsFor(libraryId)
  const pct = Number(p ?? 0)
  return Number.isFinite(pct) && pct > t.started && pct < t.finished
}
