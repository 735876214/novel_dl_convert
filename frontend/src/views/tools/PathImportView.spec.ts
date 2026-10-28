import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import PathImportView from '@/views/tools/PathImportView.vue'

/**
 * 第 165 期：文件名提取的接线。
 *
 * 坏起来全是「点了没反应」：预览按钮没接 api、应用后没重算预览（用户仍看到「会改写 3 本」）。
 * 规则本身在 `tests/test_path_import_165.py`（后端），这里只钉前后端之间的契约。
 */
vi.mock('@/lib/api', () => ({
  api: {
    libraries: vi.fn(),
    pathImportMeta: vi.fn(),
    pathImportPreview: vi.fn(),
    pathImportApply: vi.fn(),
  },
}))

const m = {
  libraries: vi.mocked(api.libraries),
  meta: vi.mocked(api.pathImportMeta),
  preview: vi.mocked(api.pathImportPreview),
  apply: vi.mocked(api.pathImportApply),
}

const PREVIEW = {
  target: 'stem',
  fields: ['author', 'title'],
  items: [{
    book_id: 'b1',
    name: '[张三] 星际旅行.epub',
    title: '星际旅行',
    matched: true,
    values: { author: '张三', title: '星际旅行' },
    changes: [{ field: 'author', from: '未知', to: '张三' }],
  }],
  total: 2,
  matched: 1,
  unmatched: 1,
  changed: 1,
  truncated: false,
  limit: 200,
}

async function mountView() {
  const pinia = createPinia()
  setActivePinia(pinia)
  m.libraries.mockResolvedValue({ items: [], total: 0, types: [], source_roots: [] })
  m.meta.mockResolvedValue({
    targets: [{ value: 'stem', label: '文件名（不含扩展名）' }],
    fields: ['author', 'title'],
    limit: 200,
  })
  const w = mount(PathImportView, { global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

describe('PathImportView', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('预览：把正则与范围发给后端并渲染计数', async () => {
    const w = await mountView()
    m.preview.mockResolvedValue(PREVIEW)
    await w.find('textarea[aria-label="提取正则"]').setValue('^(?P<author>.+)$')
    const btn = w.findAll('button').find((b) => b.text() === '预览')
    await btn!.trigger('click')
    await flushPromises()

    expect(m.preview).toHaveBeenCalledWith({ pattern: '^(?P<author>.+)$', target: 'stem', library_id: undefined })
    expect(w.text()).toContain('匹配 1 本')
    expect(w.text()).toContain('会改写 1 本')
    expect(w.text()).toContain('作者')
  })

  it('应用：写入后重新预览（「会改写」归零），并显示回执', async () => {
    const w = await mountView()
    m.preview.mockResolvedValueOnce(PREVIEW)
    await w.find('textarea[aria-label="提取正则"]').setValue('^(?P<author>.+)$')
    await w.findAll('button').find((b) => b.text() === '预览')!.trigger('click')
    await flushPromises()

    m.apply.mockResolvedValue({ count: 1, items: [], errors: [], fields: ['author'] })
    m.preview.mockResolvedValueOnce({ ...PREVIEW, changed: 0, items: [] })
    const applyBtn = w.findAll('button').find((b) => b.text().includes('应用到 1 本'))
    expect(applyBtn).toBeTruthy()
    await applyBtn!.trigger('click')
    await flushPromises()

    expect(m.apply).toHaveBeenCalledWith({ pattern: '^(?P<author>.+)$', target: 'stem', library_id: undefined })
    expect(w.text()).toContain('已写入')
    expect(w.text()).toContain('会改写 0 本')
  })
})
