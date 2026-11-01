import { describe, expect, it } from 'vitest'

import type { BookCard } from '@/lib/api'
import { sortBooks } from '@/lib/shelfSort'

/** 第 212 期：书架主排序 + 次级排序。空文本排最后、同键次级排序不生效。 */
function b(over: Partial<BookCard>): BookCard {
  return {
    id: String(over.title ?? 'x'), name: 'x.epub', title: 'x', author: '', series: '',
    series_index: '', format: 'EPUB', size: 1, mtime: 0, c1: '', c2: '', tags: [],
    has_cover: false, ...over,
  } as BookCard
}

describe('shelfSort', () => {
  it('主排序相同才用次级排序（作者升序 → 评分降序）', () => {
    const books = [
      b({ title: '低分', author: 'A', stars: 1 }),
      b({ title: '高分', author: 'A', stars: 5 }),
      b({ title: '无作者', author: '', stars: 9 }),
    ]
    const out = sortBooks(books, 'author', 'asc', 'stars', 'desc')
    expect(out.map((x) => x.title)).toEqual(['高分', '低分', '无作者'])
  })

  it('次级键与主键相同 ⇒ 不启用；系列排序带序号', () => {
    const books = [
      b({ title: 'b', series: 'S', series_index: '2' }),
      b({ title: 'a', series: 'S', series_index: '1' }),
    ]
    expect(sortBooks(books, 'series', 'asc', 'series', 'desc').map((x) => x.title))
      .toEqual(['a', 'b'])
    expect(sortBooks(books, 'title', 'asc', 'title', 'desc').map((x) => x.title))
      .toEqual(['a', 'b'])
  })
})
