/**
 * 「话 / 轨 ↔ 百分比」的进度换算（第 73 期）—— **唯一真值源**。
 *
 * 序号单元合集（`format === 'UNITS'`）没有新库表、也没有新列：它的进度仍然只落
 * `progress` 那一行 `percent`（0–100），与有声书逐字相同。所以「第几话、话内多少」
 * 只能由 percent 反推 —— 这份算式必须只有一处，两处各写一遍就会出现
 * 「书架说读到第 3 话、点进去从第 1 话开始」。
 *
 * 口径（与改造前的 `AudioPlayer` 逐字相同，只是搬到这里）：
 *
 *     percent = (index + within) / total × 100
 *
 * - `index`：第几话 / 第几轨，**0 起**；
 * - `within`：这一话内部读到哪（0–1）。音频 = `currentTime / duration`；
 *   漫画 / PDF 话 = `页 / 总页数`；拿不到时长或页数时按 0 处理（= 这一话的开头）；
 * - `total`：话数 / 轨数。
 *
 * ⚠️ 边界：`toPercent(i, 1, total)` 与 `toPercent(i + 1, 0, total)` 是**同一个数**
 * （「这一话读完」与「下一话没开始」本就是同一个位置），反解一律给后者。而**最后一话**
 * 读到 100% 时 `floor` 的结果是 `total`，被夹回 `total - 1` —— 不会越界到不存在的一话：
 * 读完整本再打开，停在最后一话的末尾而不是报错。
 */

/** 话 / 轨 → 全书百分比（0–100）。`within` 夹在 [0,1]，`index` 夹在 [0, total-1]。 */
export function toPercent(index: number, within: number, total: number): number {
  if (!Number.isFinite(total) || total < 1) return 0
  const i = Math.min(Math.max(Math.floor(index) || 0, 0), total - 1)
  const w = Number.isFinite(within) ? Math.min(Math.max(within, 0), 1) : 0
  return ((i + w) / total) * 100
}

/**
 * 边界容差（见 `fromPercent`）：远大于浮点噪声（`total` 上千时也只有 ~1e-12），
 * 又远小于任何真实的「话内位置差」（最小的一步是 1 / 页数）。
 */
const BOUNDARY_EPS = 1e-9

/** 全书百分比 → 「第几话 + 话内多少」。`index` 一定落在 [0, total-1]。 */
export function fromPercent(percent: number, total: number): { index: number; within: number } {
  if (!Number.isFinite(total) || total < 1) return { index: 0, within: 0 }
  const p = Number.isFinite(percent) ? Math.min(Math.max(percent, 0), 100) : 0
  const pos = (p / 100) * total
  // ⚠️ `BOUNDARY_EPS` 不是装饰：`toPercent(i, 0, total)` 写出去的是 `i / total × 100`，
  // 再乘回来在二进制浮点下**不严格互逆** —— 43 话的书里第 16 话的开头反解成
  // `15.999999999999998`，floor 之后落到**第 15 话的末尾**：界面显示「第 16 话」的位置，
  // 重新打开却回到第 15 话的最后一页。加容差把这种「差一点正好落在整数上」归位。
  const index = Math.min(total - 1, Math.max(0, Math.floor(pos + BOUNDARY_EPS)))
  // 100% 时 pos 恰好等于 total ⇒ within 会是 1；夹到 0.999 让它仍属于**这一话的末尾**
  const within = Math.min(0.999, Math.max(0, pos - index))
  return { index, within }
}
