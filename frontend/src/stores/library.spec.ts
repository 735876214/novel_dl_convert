import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type LibrariesResult, type LibraryEntity } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'

/**
 * `@/lib/api` 整体替换：这组用例只关心 store 对**拉取结果**的反应，
 * 不关心 HTTP 细节（那由后端的接口用例负责）。
 */
vi.mock('@/lib/api', () => ({
  // `readingThresholds` 是第 40 期加的：store 的 `loadBooks` / `setCurrentLibrary`
  // 会先取阈值（见 `lib/readingThresholds.ensureThresholds`）。本组用例没走到那两条路径，
  // 但 mock 缺了它，将来谁加一条就会炸在「不是函数」上，所以一并给出可用的桩。
  api: {
    libraries: vi.fn(),
    readingThresholds: vi.fn().mockResolvedValue({ library_id: '', started: 0, finished: 99.5 }),
  },
}))

const mockLibraries = vi.mocked(api.libraries)

/**
 * 造一个**字段齐全**的 `LibraryEntity`。
 *
 * 刻意不做 `as LibraryEntity` 强转：本期刚立的规矩是 spec 也在 `vue-tsc --build`
 * 的检查范围内（`src/**`），强转会把「接口加了新字段」这件事藏起来 ——
 * 而我要的恰恰是它报出来。
 */
function makeLibrary(over: Partial<LibraryEntity> = {}): LibraryEntity {
  return {
    id: 'lib1',
    name: '主库',
    type: 'ebook',
    type_label: '电子书',
    source_dirs: ['/srv/library/main'],
    rules: '',
    sort_order: 0,
    publish_path: '',
    publish_exists: false,
    publish_writable: false,
    watch: 0,
    scan_interval: 0,
    scan_cron: '',
    // 第 40 期新库向导三列
    icon: '',
    allowed_exts: [],
    exts_effective: ['.epub'],
    exclude: [],
    book_count: 0,
    exists: true,
    writable: true,
    last_scan_at: 0,
    last_scan_note: '',
    ...over,
  }
}

function makeResult(items: LibraryEntity[]): LibrariesResult {
  return {
    items,
    total: items.length,
    // 第 41 期：已配置的来源根（向导按这些根浏览 / 下钻）
    source_roots: [{ name: '来源根', path: '/srv/library' }],
    // `exts` = 该类型的默认扫描白名单（第 40 期「允许的格式」chips 的默认勾选集）
    types: [{ value: 'ebook', label: '电子书', exts: ['.epub', '.mobi'] }],
  }
}

describe('library store · hasNoLibraries（第 38 期契约）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockLibraries.mockReset()
  })

  /**
   * 三态里最容易写错的一态：**没拉到** ≠ **一个都没有**。
   *
   * `libraryEntities` 初值就是 `[]`，所以单看 `.length === 0` 分不清这两件事。
   * 首屏引导只看 `hasNoLibraries` —— 它一旦在这种时候为真，每次进页面都会先闪一下
   * 「还没有书库」，而后端明明是通的。
   */
  it('未加载时不说「还没有书库」——「不知道」不是「0 个」', () => {
    const lib = useLibraryStore()

    expect(lib.librariesLoaded).toBe(false)
    expect(lib.hasNoLibraries).toBe(false)
  })

  it('拉取成功且确实一个都没有 —— 这才叫 hasNoLibraries', async () => {
    mockLibraries.mockResolvedValue(makeResult([]))
    const lib = useLibraryStore()

    await lib.loadLibraries()

    expect(lib.librariesLoaded).toBe(true)
    expect(lib.hasNoLibraries).toBe(true)
  })

  it('拉取成功且库非空时 hasNoLibraries 为假（0 库 ≠ 有库但没书）', async () => {
    mockLibraries.mockResolvedValue(makeResult([makeLibrary({ book_count: 0 })]))
    const lib = useLibraryStore()

    await lib.loadLibraries()

    expect(lib.librariesLoaded).toBe(true)
    expect(lib.hasNoLibraries).toBe(false)
  })

  /**
   * 这一条是这组用例里**最值钱**的：拉失败时保持 false。
   *
   * 后端明明是通的、只是这一次请求挂了，若此时 `hasNoLibraries` 为真，
   * 用户会看到「还没有书库」的引导页 —— 那是在**谎报数据状态**。
   */
  it('拉取失败时仍不说「还没有书库」，且 librariesLoaded 保持 false', async () => {
    mockLibraries.mockRejectedValue(new Error('network down'))
    const lib = useLibraryStore()

    await lib.loadLibraries()

    expect(lib.librariesLoaded).toBe(false)
    expect(lib.hasNoLibraries).toBe(false)
  })

  /** 已有数据时的短路：非 force 不重复拉取（侧边栏计数那个 bug 的另一半）。 */
  it('已有数据时不重复拉取；force=true 才重新拉', async () => {
    mockLibraries.mockResolvedValue(makeResult([makeLibrary({ book_count: 3 })]))
    const lib = useLibraryStore()

    await lib.loadLibraries()
    expect(mockLibraries).toHaveBeenCalledTimes(1)

    await lib.loadLibraries()
    expect(mockLibraries).toHaveBeenCalledTimes(1)

    await lib.loadLibraries(true)
    expect(mockLibraries).toHaveBeenCalledTimes(2)
  })
})
