import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * 「同一份数据被并发拉多次」的回归契约（第 67 期）。
 *
 * 背景（实测，600 本的库）：一次页面加载打了 **7 次** `/api/books`（2.8 MB、累计 3.6 s）、
 * 3 次 `/api/stats`、2 次 `/api/collections` —— 因为各 store 的守卫是
 * `if (loaded) return`，而它在**发请求之前就 `await` 了别的东西**（阈值等），
 * 于是同一批微任务里的多个调用者全都通过了守卫。
 *
 * 这里只关心**调用次数与最终数据**，不关心 HTTP/字段细节（那由后端用例负责）。
 */
const A = vi.hoisted(() => ({
  books: vi.fn(),
  libraries: vi.fn(),
  libraryFacets: vi.fn(),
  readingThresholds: vi.fn(),
  stats: vi.fn(),
  collections: vi.fn(),
  createCollection: vi.fn(),
}))
vi.mock('@/lib/api', () => ({ api: A }))

import { useCollectionsStore } from '@/stores/collections'
import { useLibraryStore } from '@/stores/library'
import { useStatsStore } from '@/stores/stats'

beforeEach(() => {
  setActivePinia(createPinia())
  for (const f of Object.values(A)) f.mockReset()
  A.readingThresholds.mockResolvedValue({ library_id: '', started: 0, finished: 99.5 })
})

describe('并发拉取去重（单飞闸）', () => {
  it('loadBooks 并发 3 次 → 只打 1 次 /api/books', async () => {
    A.books.mockResolvedValue({ items: [], total: 0 })
    const lib = useLibraryStore()
    await Promise.all([lib.loadBooks(), lib.loadBooks(), lib.loadBooks()])
    expect(A.books).toHaveBeenCalledTimes(1)
  })

  it('loadLibraries 并发 3 次 → 只打 1 次 /api/libraries', async () => {
    A.libraries.mockResolvedValue({ items: [], total: 0, source_roots: [], types: [] })
    const lib = useLibraryStore()
    await Promise.all([lib.loadLibraries(), lib.loadLibraries(), lib.loadLibraries()])
    expect(A.libraries).toHaveBeenCalledTimes(1)
  })

  it('stats.load 并发 3 次 → 只打 1 次 /api/stats', async () => {
    A.stats.mockResolvedValue({ library_id: '' })
    const s = useStatsStore()
    await Promise.all([s.load(), s.load(), s.load()])
    expect(A.stats).toHaveBeenCalledTimes(1)
  })

  it('collections.load 并发 2 次 → 只打 1 次 /api/collections', async () => {
    A.collections.mockResolvedValue({ items: [] })
    const c = useCollectionsStore()
    await Promise.all([c.load(), c.load()])
    expect(A.collections).toHaveBeenCalledTimes(1)
  })

  it('已有数据时仍短路不重拉（既有行为不变）', async () => {
    A.books.mockResolvedValue({ items: [], total: 0 })
    const lib = useLibraryStore()
    await lib.loadBooks()
    await lib.loadBooks()
    expect(A.books).toHaveBeenCalledTimes(1)
  })
})

describe('collections 的 force 语义（刚改完必须拿新数据）', () => {
  /**
   * ⚠️ 这条最值钱：`create` 之后调 `load(true)`，若此刻恰好有一次「页面加载时发出的」
   * 旧请求在飞，**复用**它会把新收藏夹吞掉。所以 force 必须「等前一次落地，再跑一次」。
   */
  it('force 会等前一次落地后**再拉一次**，最终拿到新数据', async () => {
    let doneFirst: (v: unknown) => void = () => {}
    A.collections
      .mockReturnValueOnce(new Promise((r) => { doneFirst = r }))
      .mockResolvedValue({ items: [{ id: 9, name: '新收藏夹' }] })

    const c = useCollectionsStore()
    const p1 = c.load()             // 在飞（模拟页面加载时那一次）
    const p2 = c.load(true)         // 刚 create 完的强制刷新
    doneFirst({ items: [] })        // 让旧请求落地
    await Promise.all([p1, p2])

    expect(A.collections).toHaveBeenCalledTimes(2)
    expect(c.items.map((i) => i.id)).toEqual([9])
  })
})
