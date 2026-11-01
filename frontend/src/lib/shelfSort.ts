import type { BookCard } from './api'
import type { ShelfSort, SortDir } from '@/stores/shelfPrefs'

/**
 * 书架排序（第 212 期）：主排序 + 可选次级排序。
 *
 * 抽成纯函数是为了让「多级排序」有可执行判据（挂载整个书架太重，且排序规则不该藏在
 * 模板旁）。空文本统一排最后 —— 否则空书名会挤在最前面。
 */

function byText(a: string, b: string): number {
  if (!a && !b) return 0
  if (!a) return 1
  if (!b) return -1
  return a.localeCompare(b, 'zh')
}

export function compareBy(key: ShelfSort, dir: SortDir, x: BookCard, y: BookCard): number {
  const sign = dir === 'asc' ? 1 : -1
  switch (key) {
    case 'title':
      return sign * byText(x.title || x.name, y.title || y.name)
    case 'author':
      return sign * byText(x.author, y.author)
    case 'series':
      // 系列排序要连序号一起比，否则同一系列内部顺序是随机的
      return sign * (byText(x.series, y.series)
        || Number(x.series_index || 0) - Number(y.series_index || 0))
    case 'progress':
      return sign * ((x.percent ?? 0) - (y.percent ?? 0))
    case 'pages':
      return sign * ((x.pages ?? 0) - (y.pages ?? 0))
    case 'stars':
      return sign * ((x.stars ?? 0) - (y.stars ?? 0))
    default:
      return sign * ((x.mtime ?? 0) - (y.mtime ?? 0))
  }
}

/** 返回新数组；`sort2` 为空或与主键相同则不启用次级排序。 */
export function sortBooks(
  books: BookCard[],
  sort: ShelfSort,
  dir: SortDir,
  sort2: ShelfSort | '',
  dir2: SortDir,
): BookCard[] {
  const list = [...books]
  const second = sort2 && sort2 !== sort ? sort2 : ''
  list.sort((x, y) => {
    const primary = compareBy(sort, dir, x, y)
    if (primary || !second) return primary
    return compareBy(second, dir2, x, y)
  })
  return list
}
