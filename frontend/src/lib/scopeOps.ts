/**
 * 规则操作的**唯一实现**（书级智能书架 `smartScope.ts` 与播客单集播放列表
 * `episodeScope.ts` 共用）。
 *
 * 为什么抽出来：两边的字段集不同（书有作者/系列，单集有时长/发布天数），
 * 但「包含 / 不包含 / 等于 / 至少 / 至多」的语义必须完全一致 —— 各写一份
 * 迟早会出现「同一个 contains 在两边大小写处理不同」。
 */

export function norm(v: unknown): string {
  return String(v ?? '').trim().toLowerCase()
}

/** 文本字段的单条判定（needle 会先归一化；空 needle 由调用方按「恒真」处理）。 */
export function textHit(hay: unknown, op: string, needle: string): boolean {
  const h = norm(hay)
  const n = norm(needle)
  if (op === 'equals') return h === n
  if (op === 'not_contains') return !h.includes(n)
  return h.includes(n)
}

/** 多值字段（题材 / 分类）：任一值命中即算包含。 */
export function listHit(values: unknown[], op: string, needle: string): boolean {
  const vals = (values || []).map(norm)
  const n = norm(needle)
  if (op === 'not_contains') return !vals.some((v) => v.includes(n))
  if (op === 'equals') return vals.includes(n)
  return vals.some((v) => v.includes(n))
}

/** 数值字段：at_least = 至少，at_most = 至多（其它操作按「至少」处理，与既有口径一致）。 */
export function numHit(value: number, op: string, target: number): boolean {
  return op === 'at_most' ? value <= target : value >= target
}
