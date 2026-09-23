/**
 * 书架首字母分桶（第 43 期）—— 书架顶部 A–Z / # 跳转条的**唯一判据源**。
 *
 * 口径（刻意简单、不做假精确）：
 *   · 按**书名首字**分桶，拉丁字母 A–Z 各自成桶；
 *   · 其余一律归 `#` 桶 —— 中日韩、数字、符号、空书名都算。
 *     ⚠️ **不做拼音首字母**：那要先有拼音表（新增依赖），且多音字会算错；
 *     宁可把它们老实归到 `#`，也不给一个会跳错的分桶。
 */

export const HASH_BUCKET = '#'

/** 书名 → 桶键：A–Z 之一，或 `#`（其它）。 */
export function bucketKeyOf(title: string | undefined | null): string {
  const s = String(title ?? '').trim()
  if (!s) return HASH_BUCKET
  const ch = s[0].toUpperCase()
  return ch >= 'A' && ch <= 'Z' ? ch : HASH_BUCKET
}

/** 桶的展示标签（`#` 即「其它」） */
export function bucketLabelOf(key: string): string {
  return key
}

export interface ShelfBucket {
  key: string
  label: string
  count: number
}

/**
 * 把条目按渲染顺序分桶：`[{key, label, count}]`。
 *
 * 桶序固定为 **A–Z 升序、`#` 垫底** —— 不跟随当前排序（按入库时间排序时若按出现顺序
 * 排桶，跳转条会毫无规律）。`#` 是「其它」，混在字母中间会找不到。
 * 传入 `undefined` 的条目（如系列折叠余项）跳过、不计入。
 */
export function buildBuckets(titles: (string | undefined)[]): ShelfBucket[] {
  const count = new Map<string, number>()
  for (const t of titles) {
    if (t === undefined) continue
    const k = bucketKeyOf(t)
    count.set(k, (count.get(k) || 0) + 1)
  }
  const keys = Array.from(count.keys())
    .filter((k) => k !== HASH_BUCKET)
    .sort()
  if (count.has(HASH_BUCKET)) keys.push(HASH_BUCKET)
  return keys.map((k) => ({ key: k, label: bucketLabelOf(k), count: count.get(k) || 0 }))
}
