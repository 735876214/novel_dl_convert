import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type LibrariesResult } from '@/lib/api'
import { useLibraryWizardStore } from '@/stores/libraryWizard'
import { useUiStore } from '@/stores/ui'

/**
 * `@/lib/api` 整体替换：本组用例只关心 store 对**拉取结果**的反应
 * （开浮层 / 关浮层 / 失败 toast / 回调触发），不关心 HTTP 细节。
 * `created()` 会经 `library.loadLibraries(true)` 再拉一次 `/api/libraries`，
 * 所以 mock 的是同一个方法，调用次数断言据此推算。
 */
vi.mock('@/lib/api', () => ({
  api: { libraries: vi.fn() },
}))

const mockLibraries = vi.mocked(api.libraries)

function makeResult(over: Partial<LibrariesResult> = {}): LibrariesResult {
  return {
    items: [],
    total: 0,
    types: [{ value: 'ebook', label: '电子书库', exts: ['.epub'] }],
    source_roots: [{ name: 'libraries', path: '/srv/libraries' }],
    ...over,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('libraryWizard store（第 55 期：就地弹窗）', () => {
  it('show 拉取数据成功才开浮层', async () => {
    mockLibraries.mockResolvedValue(makeResult())
    const store = useLibraryWizardStore()

    await store.show()

    expect(store.open).toBe(true)
    expect(store.types).toHaveLength(1)
    expect(store.sourceRoots).toEqual([{ name: 'libraries', path: '/srv/libraries' }])
    expect(store.loading).toBe(false)
  })

  it('show 拉取失败不开浮层，只 toast（不开一个没有类型可选的空壳向导）', async () => {
    mockLibraries.mockRejectedValue(new Error('网络炸了'))
    const store = useLibraryWizardStore()
    const ui = useUiStore()

    await store.show()

    expect(store.open).toBe(false)
    expect(ui.toastMessage).toBe('网络炸了')
    expect(store.loading).toBe(false)
  })

  it('created 关浮层、刷新全局书库实体并触发宿主回调（回调一次性）', async () => {
    mockLibraries.mockResolvedValue(makeResult())
    const store = useLibraryWizardStore()
    const cb = vi.fn()
    await store.show({ onCreated: cb })
    expect(mockLibraries).toHaveBeenCalledTimes(1)

    await store.created('lib9')

    expect(store.open).toBe(false)
    // loadLibraries(true) 会再拉一次 /api/libraries
    expect(mockLibraries).toHaveBeenCalledTimes(2)
    expect(cb).toHaveBeenCalledWith('lib9')

    // 回调用完即弃：再走一次 created 不应重复触发
    await store.created('lib10')
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('close 关浮层并丢弃未触发的宿主回调（取消建库不残留副作用）', async () => {
    mockLibraries.mockResolvedValue(makeResult())
    const store = useLibraryWizardStore()
    const cb = vi.fn()
    await store.show({ onCreated: cb })

    store.close()

    expect(store.open).toBe(false)
    await store.created('lib9')
    expect(cb).not.toHaveBeenCalled()
  })
})
