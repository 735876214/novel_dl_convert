/**
 * 书架筛选面板的**计数**（第 156 期）—— 筛选选项与每项本数的唯一计算处。
 *
 * ## 为什么单独抽出来
 *
 * 第 88 期起书架首屏只加载**第一页**（`shelfLoadedBooks`），而筛选选项原先是**从已加载页**
 * 里 `uniq` 出来的。于是大库会出现两个说谎的界面：
 *   · 某本书的语言 / 题材在前几页没出现 ⇒ 下拉里根本没有这一项；
 *   · 选项没有本数 ⇒ 用户不知道筛下去还剩几本（往往 1 本）。
 *
 * 这里改成在**全量书目**（`library.books`，侧栏启动时整份拉回）上计数，与分页解耦。
 * 计数**只按当前书库收窄**，不跟随其它筛选项 —— 这是筛选面板的常规语义：
 * 每一项告诉你「选它会有多少本」，不随你已选的那几项忽大忽小。
 *
 * ⚠️ 计数口径必须与书架自己的筛选**同一套**判据：状态走 `readingThresholds.statusBucket`
 * （真实状态优先、阈值兜底），格式统一大写、语言去空白 —— 否则「下拉写 12 本、筛出来 11 本」。
 */
import type { BookCard } from './api'

import { statusBucket, type DerivedStatus } from './readingThresholds'

export interface FacetOption {
  value: string
  count: number
}

/** 文本分面：去空值 → 归一 → 计数 → **按值升序**（中文按 `localeCompare('zh')`）。 */
export function tallyText(
  values: Iterable<string | null | undefined>,
  normalize: (v: string) => string = (v) => v.trim(),
): FacetOption[] {
  const count = new Map<string, number>()
  for (const raw of values) {
    const v = normalize(String(raw ?? ''))
    if (!v) continue
    count.set(v, (count.get(v) || 0) + 1)
  }
  return Array.from(count.entries())
    .sort((a, b) => a[0].localeCompare(b[0], 'zh'))
    .map(([value, n]) => ({ value, count: n }))
}

/** 题材是多值字段：一条书带多个标签时，每个标签各 +1。 */
export function tallyTags(books: Iterable<Pick<BookCard, 'tags'>>): FacetOption[] {
  const values: string[] = []
  for (const b of books) for (const t of b.tags || []) values.push(t)
  return tallyText(values)
}

export type CoverFacet = 'yes' | 'no'

/** 封面两态计数（`has_cover` 是后端算好的真实值）。 */
export function coverCounts(books: Iterable<Pick<BookCard, 'has_cover'>>): Record<CoverFacet, number> {
  let yes = 0
  let no = 0
  for (const b of books) {
    if (b.has_cover) yes += 1
    else no += 1
  }
  return { yes, no }
}

/** 阅读状态三档计数 —— 与书架筛选同源（`statusBucket`，真实状态优先）。 */
export function statusCounts(
  books: Iterable<Pick<BookCard, 'status' | 'percent'>>,
  libraryId = '',
): Record<DerivedStatus, number> {
  const out: Record<DerivedStatus, number> = { unread: 0, reading: 0, finished: 0 }
  for (const b of books) out[statusBucket(b, libraryId) as DerivedStatus] += 1
  return out
}
