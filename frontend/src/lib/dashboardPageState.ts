/**
 * 仪表盘**页级**三态的唯一判据（第 98 期）。
 *
 * 上游首页有一个「整页四分支」（loading / error / empty / ready），本项目此前只做到
 * **部件级**三分支（`composables/useWidgetState.ts`）。第 82 / 83 期没做页级的理由写在
 * `docs/bookorbit/bookorbit-dashboard-styles.md` §7.4：本项目**没有单一的「整页加载」信号**
 * （数据分散在 stats / library / 批注三处），硬造一个页面级 flag 只会是假的。
 *
 * 第 98 期的口径（用户拍板）：判据**只由仪表盘首屏自己真的发出去的那几条请求**聚合而来 ——
 * `stores/stats` 的 `loaded` / `error` 与 `stores/library` 的首次 `loading` / `booksError`。
 * 于是它天生满足两条诚实性要求：
 *
 * 1. **任何一条请求一旦 settle（成功或失败），页级就不再整体遮罩** —— 只对**仍未就绪**的
 *    那一条保留区块级提示（统计失败那张卡片照旧），已经有内容的区块绝不盖住。
 * 2. `empty` 一律**让给既有的两条真空态**（0 库的 `FirstRunNotice`、部件与书架全关的
 *    `DashboardWelcome`），页级不抢它们的活。
 *
 * ⚠️ **不许**改成「首次进入 N 毫秒内没有数据就当 loading」这类超时启发式：那不是任何真实
 * 请求的状态，正是第 80 期「消灭假开关」要挡的东西。
 */

/** 页级四档。`empty` 由既有两个空态组件承担，页级只在 `loading` / `error` 上出力 */
export type DashboardPhase = 'loading' | 'error' | 'empty' | 'ready'

export interface DashboardPageInput {
  /** 0 个书库（`library.hasNoLibraries`）⇒ 首屏引导优先 */
  noLibraries: boolean
  /** 部件与书架全关（`dashboard.isEmpty`）⇒ 空态优先 */
  emptied: boolean
  /** `/api/stats` 是否已经拿到过一份（`stores/stats` 的 `loaded`） */
  statsLoaded: boolean
  /** `/api/stats` 的失败原因（空串 = 没失败） */
  statsError: string
  /** 书目首屏是否还在路上（`stores/library` 的 `loading`） */
  booksLoading: boolean
  /** 书目加载失败原因（空串 = 没失败） */
  booksError: string
}

export function dashboardPageState(i: DashboardPageInput): DashboardPhase {
  // 空态优先：0 库 / 全关时本来就有一整块像模像样的引导，页级再盖一层就是抢戏
  if (i.noLibraries || i.emptied) return 'empty'
  // 两条都失败、且一条都没拿到 ⇒ 页级给一次「一起重试」的机会。
  // 只有一条失败时仍走既有的区块级提示（统计那张卡片），不升级成整页错误 ——
  // 另一条还有真数据，整页报错等于把真数据说成没有。
  if (i.statsError && i.booksError && !i.statsLoaded) return 'error'
  // 统计**既没成功也没失败**、且书目还在路上 ⇒ 首屏骨架。
  // 任一条 settle 就退出 loading：骨架不该继续盖住已经就绪的那一半。
  if (!i.statsLoaded && !i.statsError && i.booksLoading) return 'loading'
  return 'ready'
}
