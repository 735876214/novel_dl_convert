import { describe, expect, it } from 'vitest'

import type { BookCard } from '@/lib/api'
import { filterByLibraries, libraryScopeLabel } from './shelfScope'

function book(id: string, libraryId?: string): BookCard {
  return { id, name: `${id}.epub`, title: id, author: '', series: '', library_id: libraryId } as BookCard
}

const LIBS = ['lib-a', 'lib-b', 'lib-c']

describe('filterByLibraries（书架行「库范围」）', () => {
  const books = [book('1', 'lib-a'), book('2', 'lib-b'), book('3', 'lib-c'), book('4', 'lib-b')]

  it('空数组或缺省 = 全部书库（原样返回，不筛）', () => {
    expect(filterByLibraries(books, [], LIBS).map((b) => b.id)).toEqual(['1', '2', '3', '4'])
    expect(filterByLibraries(books, undefined, LIBS).map((b) => b.id)).toEqual(['1', '2', '3', '4'])
  })

  it('选一部分书库：只留属于它们的书', () => {
    expect(filterByLibraries(books, ['lib-b'], LIBS).map((b) => b.id)).toEqual(['2', '4'])
    expect(filterByLibraries(books, ['lib-a', 'lib-c'], LIBS).map((b) => b.id)).toEqual(['1', '3'])
  })

  it('选满全部书库 = 与不选等价（不能少给书）', () => {
    expect(filterByLibraries(books, LIBS, LIBS).map((b) => b.id)).toEqual(['1', '2', '3', '4'])
  })

  it('指向已删除书库的 id 一律忽略（否则删库后整行会空掉且无从解释）', () => {
    // lib-gone 不存在 ⇒ 忽略，有效项只剩 lib-a
    expect(filterByLibraries(books, ['lib-a', 'lib-gone'], LIBS).map((b) => b.id)).toEqual(['1'])
  })

  it('有效 id 一个都不剩 ⇒ 退化为「全部书库」（宁可多显示，也不静默清空）', () => {
    expect(filterByLibraries(books, ['lib-gone'], LIBS).map((b) => b.id)).toEqual(['1', '2', '3', '4'])
    // 库列表还没加载回来（knownLibraryIds 为空）时同理
    expect(filterByLibraries(books, ['lib-a'], []).map((b) => b.id)).toEqual(['1', '2', '3', '4'])
  })

  it('书缺 library_id（单库时代旧数据）⇒ 不在任何被选中的库里', () => {
    const legacy = [book('9'), book('1', 'lib-a')]
    expect(filterByLibraries(legacy, ['lib-a'], LIBS).map((b) => b.id)).toEqual(['1'])
  })

  it('不改写入参（返回新数组）', () => {
    const src = [...books]
    const out = filterByLibraries(src, ['lib-b'], LIBS)
    expect(out).not.toBe(src)
    expect(src.map((b) => b.id)).toEqual(['1', '2', '3', '4'])
  })
})

describe('libraryScopeLabel（范围摘要）', () => {
  it('不选 / 选满 ⇒ 都显示「全部书库」', () => {
    expect(libraryScopeLabel(undefined, LIBS)).toBe('全部书库')
    expect(libraryScopeLabel([], LIBS)).toBe('全部书库')
    expect(libraryScopeLabel(LIBS, LIBS)).toBe('全部书库')
  })

  it('部分选中 ⇒ 「N 个书库」（只数有效项）', () => {
    expect(libraryScopeLabel(['lib-a'], LIBS)).toBe('1 个书库')
    expect(libraryScopeLabel(['lib-a', 'lib-gone'], LIBS)).toBe('1 个书库')
  })

  it('全是陈旧 id ⇒ 与「全部书库」一致（不显示 0 个书库）', () => {
    expect(libraryScopeLabel(['lib-gone'], LIBS)).toBe('全部书库')
  })
})
