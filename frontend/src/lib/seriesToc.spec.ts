import { describe, expect, it, vi } from 'vitest'
import { ref, nextTick } from 'vue'

import { useSeriesToc } from '@/lib/seriesToc'
import type { BookCard } from '@/lib/api'

/**
 * 系列目录侧栏的数据层（第 152 期）。
 *
 * 背景：折叠系列后，漫画 / PDF 阅读器此前没有目录入口 —— 点开一个 28 册的系列只能
 * 一册一册翻。这个 composable 是两个阅读器**共用**的那份数据；坏起来静默（侧栏空着、
 * 或高亮错行），所以把排序、无系列不请求、失败不清旧值这几条都钉住。
 */

vi.mock('@/lib/api', () => ({
  api: { seriesDetail: vi.fn() },
}))

import { api } from '@/lib/api'
const m = vi.mocked(api.seriesDetail)

function makeBook(over: Partial<BookCard>): BookCard {
  return {
    id: 'x',
    name: 'x.cbz',
    title: 'x',
    author: '',
    series: 'S',
    has_cover: false,
    format: 'CBZ',
    size: 1,
    mtime: 0,
    c1: 'a',
    c2: 'b',
    tags: [],
    narrators: [],
    year: '',
    publisher: '',
    isbn: '',
    language: 'zh',
    description: '',
    issues: [],
    library_id: 'lib',
    ...over,
  }
}

describe('useSeriesToc', () => {
  it('乱序接口数据按序号排序（目录的要点就是顺序）', async () => {
    m.mockResolvedValue({
      books: [makeBook({ id: 'v3', series_index: '3' }), makeBook({ id: 'v1', series_index: '1' })],
    } as never)
    const series = ref<string | undefined>('S')
    const toc = useSeriesToc(series, ref('v1'))
    for (let i = 0; i < 4; i++) await nextTick()
    expect(toc.books.map((b) => b.id)).toEqual(['v1', 'v3'])
    expect(toc.currentIndex).toBe(0)
    expect(toc.loading).toBe(false)
    expect(toc.error).toBe('')
  })

  it('没有系列名 ⇒ 不发请求（侧栏显示「无系列」，不是一直空的列表）', async () => {
    m.mockClear()
    const toc = useSeriesToc(ref<string | undefined>(''), ref('x'))
    await nextTick()
    await nextTick()
    expect(toc.hasSeries).toBe(false)
    expect(m).not.toHaveBeenCalled()
    expect(toc.books).toEqual([])
  })

  it('拉取失败：给 error，books 留空（不显示半份数据装作成功）', async () => {
    m.mockRejectedValue(new Error('网络挂了'))
    const toc = useSeriesToc(ref<string | undefined>('S'), ref('x'))
    for (let i = 0; i < 4; i++) await nextTick()
    expect(toc.error).toBe('网络挂了')
    expect(toc.books).toEqual([])
    expect(toc.loading).toBe(false)
  })

  it('当前书不在清单里 ⇒ currentIndex 为 -1（侧栏不高亮任何一行，不猜）', async () => {
    m.mockResolvedValue({ books: [makeBook({ id: 'v1', series_index: '1' })] } as never)
    const toc = useSeriesToc(ref<string | undefined>('S'), ref('别的书'))
    for (let i = 0; i < 4; i++) await nextTick()
    expect(toc.currentIndex).toBe(-1)
  })

  it('系列名变化（换了一本书）⇒ 重新拉取', async () => {
    m.mockClear().mockResolvedValue({ books: [makeBook({ id: 'a' })] } as never)
    const series = ref<string | undefined>('S1')
    useSeriesToc(series, ref('x'))
    for (let i = 0; i < 4; i++) await nextTick()
    expect(m).toHaveBeenLastCalledWith('S1')

    series.value = 'S2'
    for (let i = 0; i < 4; i++) await nextTick()
    expect(m).toHaveBeenLastCalledWith('S2')
  })
})
