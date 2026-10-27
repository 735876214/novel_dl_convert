/**
 * 书架跳转分桶（第 43 期；第 156 期起**跟随当前排序维度**）—— 书架顶部跳转条的**唯一判据源**。
 *
 * 口径（刻意简单、不做假精确）：
 *   · 文本轴（书名 / 作者 / 系列）按**首字**分桶，拉丁字母 A–Z 各自成桶；
 *   · 其余一律归 `#` 桶 —— 中日韩、数字、符号、空值都算。
 *     ⚠️ **不做拼音首字母**：那要先有拼音表（新增依赖），且多音字会算错；
 *     宁可把它们老实归到 `#`，也不给一个会跳错的分桶。
 *   · 入库时间轴按**年份**分桶；没有日期（`added_at` 与 mtime 都取不到）归 `未知` 桶，
 *     **不隐藏**（隐藏会让「跳转条上没有这一年」被读成「库里没有这一年的书」）。
 *
 * ⚠️ 桶的**键集合必须与排序字段绑定**：按作者排序时还按书名分桶，跳过去永远是错的桶。
 * 键的提取只在本文件一处；`ShelfView` 的三套渲染（网格 / 列表 / 表格）都调 `bucketKeyOfSort`。
 */

export const HASH_BUCKET = '#'
/** 日期轴的空值桶（与上游 unknownDate 同语义：显示出来，不吞掉） */
export const UNKNOWN_BUCKET = '未知'

/** 书名 → 桶键：A–Z 之一，或 `#`（其它）。 */
export function bucketKeyOf(title: string | undefined | null): string {
  const s = String(title ?? '').trim()
  if (!s) return HASH_BUCKET
  const ch = s[0].toUpperCase()
  return ch >= 'A' && ch <= 'Z' ? ch : HASH_BUCKET
}

/**
 * 入库时间（秒）→ 年份桶键；取不到日期归 `未知`。
 *
 * 输入口径与「入库时间」那一列一致：**`added_at` 覆盖值优先，其次文件 mtime**（由调用方合成）。
 * 只认 1900 年以后的年份 —— 秒/毫秒混用或脏数据会算出 1970 之类，宁可不猜。
 */
export function yearBucketKeyOf(ts: number | null | undefined): string {
  const n = Number(ts ?? 0)
  if (!Number.isFinite(n) || n <= 0) return UNKNOWN_BUCKET
  const d = new Date(n * 1000)
  const y = d.getFullYear()
  if (!Number.isFinite(y) || y < 1900) return UNKNOWN_BUCKET
  return String(y)
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

/** 排序维度 → 该维度是否有可用的跳转分桶。数值轴（进度 / 页数 / 评分）不造假桶。 */
export type BucketSort = 'title' | 'author' | 'series' | 'added'

/**
 * 把条目按渲染顺序分桶：`[{key, label, count}]`。
 *
 * 桶序固定为 **键升序、空值桶垫底** —— 不跟随当前排序方向（降序时若按出现顺序排桶，
 * 跳转条会毫无规律）。字母键自然 A–Z，4 位年份键自然按年升序。
 * `undefined` 的条目（如系列折叠余项）跳过、不计入。
 */
export function buildBuckets<T>(
  items: T[],
  keyOf: (item: T) => string = bucketKeyOf as (item: T) => string,
  unknownKey: string = HASH_BUCKET,
): ShelfBucket[] {
  const count = new Map<string, number>()
  for (const it of items) {
    if (it === undefined) continue
    const k = keyOf(it)
    count.set(k, (count.get(k) || 0) + 1)
  }
  const keys = Array.from(count.keys())
    .filter((k) => k !== unknownKey)
    .sort()
  if (count.has(unknownKey)) keys.push(unknownKey)
  return keys.map((k) => ({ key: k, label: bucketLabelOf(k), count: count.get(k) || 0 }))
}

/**
 * 给定排序维度，取出**该行**的桶键（三套渲染共用）。
 *
 * `title` 是这一行的显示标题（系列折叠行 = 系列名，单本 = 书名，见 `ShelfView.rowTitle`）；
 * `book` 是代表本，用于取作者 / 系列 / 入库时间。
 */
export function bucketKeyOfSort(
  sort: BucketSort,
  title: string,
  book?: { author?: string | null; series?: string | null; added_at?: number | null; mtime?: number | null } | null,
): string {
  switch (sort) {
    case 'author':
      return bucketKeyOf(book?.author)
    case 'series':
      return bucketKeyOf(book?.series)
    case 'added':
      return yearBucketKeyOf(book?.added_at || book?.mtime)
    default:
      return bucketKeyOf(title)
  }
}
