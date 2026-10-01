import type { BookCard } from '@/lib/api'

/**
 * 书架行的「库范围」筛选（第 83 期，对齐 BookOrbit 的 per-shelf 库范围）。
 *
 * ⚠️ 与 `ShelfDef.scope`（智能书架筛选键：未读 / 在读 / 已完成…）是**两个维度**：
 * `scope` 决定「取哪些书」，`library_ids` 决定「取哪些库的书」；两者可叠加。
 *
 * 语义（**空 = 全部书库**，与 `CustomFieldDef.library_ids` 同口径，零新概念）：
 *  · `libraryIds` 为空 / 缺省 ⇒ 原样返回（不筛）；
 *  · `knownLibraryIds` 里不存在的 id **一律忽略** —— 用户删库后偏好里会留下陈旧的 id，
 *    若照它筛，整行封面会变空且界面无从解释；
 *  · 忽略后若一个有效 id 都不剩（库全删了 / 库列表还没加载回来），**退化为「全部书库」**
 *    —— 宁可多显示，也不静默清空（这条写进测试，别改成「筛空」）；
 *  · 书目缺 `library_id`（单库时代的旧数据）视为「不在任何被选中的库里」⇒ 被筛掉。
 */
export function filterByLibraries(
  books: readonly BookCard[],
  libraryIds: readonly string[] | undefined,
  knownLibraryIds: readonly string[],
): BookCard[] {
  const wanted = (libraryIds ?? []).filter((id) => knownLibraryIds.includes(id))
  if (!wanted.length) return [...books]
  const set = new Set(wanted)
  return books.filter((b) => set.has(b.library_id ?? ''))
}

/**
 * 当前范围的中文摘要 —— 面板的「库范围」标题与（将来）行内提示共用一份，
 * 避免两处各写一遍导致对不上。
 *
 * 选满全部书库与「不选（= 全部书库）」显示同一句话：两者**效果确实相同**，
 * 显示成不同数字反而会让人以为筛掉了什么。
 */
export function libraryScopeLabel(
  libraryIds: readonly string[] | undefined,
  knownLibraryIds: readonly string[],
): string {
  const wanted = (libraryIds ?? []).filter((id) => knownLibraryIds.includes(id))
  if (!wanted.length || wanted.length >= knownLibraryIds.length) return '全部书库'
  return `${wanted.length} 个书库`
}
