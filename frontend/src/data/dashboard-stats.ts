/**
 * 仪表盘部件的演示数据。
 *
 * 关键约束：**全部为确定性常量，不使用 Math.random()**。
 * （参考页的热力图是在 render 里现生成随机数，导致每次重渲染图形都变，
 *   制造视觉噪声 —— 这里从源头避免。）
 */

/** 年度入库目标（本） */
export const YEAR_GOAL_TARGET = 60

/** 今年已完成入库（本） */
export const YEAR_GOAL_DONE = 38

/** 书库总占用（字节）——演示值 */
export const LIBRARY_BYTES = 12_884_901_888 // ≈ 12 GB

/**
 * 最近 28 天的每日入库数量。
 * 索引 0 = 27 天前，索引 27 = 今天。数值偏小且真实（有 0 值表示当天无入库）。
 */
export const RHYTHM_28D: number[] = [
  1, 0, 3, 2, 0, 1, 4, 2, 1, 0, 2, 5, 3, 1, 0, 2, 2, 4, 1, 3, 0, 1, 2, 6, 3, 2, 1, 4,
]

/** 连续有入库记录的天数（演示值，需与 RHYTHM_28D 尾部非零段一致） */
export const CURRENT_STREAK = 6

/** 历史最佳连续天数 */
export const BEST_STREAK = 17

/** 最近 7 天是否有入库记录（true = 实心点），对应上面数组的末 7 位 */
export const STREAK_7D: boolean[] = RHYTHM_28D.slice(-7).map((n) => n > 0)
