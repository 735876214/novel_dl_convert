import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import type { RuleSchema, SmartScope } from '@/lib/smartScope'
import SmartScopesView from '@/views/SmartScopesView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

vi.mock('@/lib/api', () => ({
  api: {
    ruleSchema: vi.fn(),
    smartScopes: vi.fn(),
    previewSmartScope: vi.fn(),
    createSmartScope: vi.fn(),
    updateSmartScope: vi.fn(),
    deleteSmartScope: vi.fn(),
    reorderSmartScopes: vi.fn(),
  },
}))

const m = {
  schema: vi.mocked(api.ruleSchema),
  scopes: vi.mocked(api.smartScopes),
  preview: vi.mocked(api.previewSmartScope),
}

const SCHEMA: RuleSchema = {
  fields: [
    { key: 'author', label: '作者', kind: 'text', ops: ['contains', 'equals', 'is_empty'] },
    { key: 'tag', label: '题材', kind: 'list', ops: ['contains', 'is_empty'] },
    { key: 'status', label: '阅读状态', kind: 'enum', ops: ['equals', 'not_equals'],
      values: [{ value: 'finished', label: '已读完' }] },
    { key: 'isbn', label: 'ISBN', kind: 'text', ops: ['is_empty', 'contains'] },
  ],
  ops: [
    { key: 'contains', label: '包含', needs_value: true },
    { key: 'equals', label: '等于', needs_value: true },
    { key: 'not_equals', label: '不等于', needs_value: true },
    { key: 'is_empty', label: '为空', needs_value: false },
  ],
}

const SCOPE: SmartScope = {
  id: 3, name: '科幻', match: 'all',
  rules: [{ field: 'tag', op: 'contains', value: '科幻' }],
  created_at: 1, count: 2,
}

describe('SmartScopesView（第 218 期：规则清单 / 预览都走服务端）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    m.schema.mockResolvedValue(SCHEMA)
    m.scopes.mockResolvedValue({ items: [SCOPE] })
    m.preview.mockResolvedValue({ count: 1, total: 10 })
  })

  it('字段清单与命中数来自接口，不在前端写死', async () => {
    const w = mount(SmartScopesView)
    await flushPromises()

    expect(m.schema).toHaveBeenCalled()
    expect(m.scopes).toHaveBeenCalledWith('')
    expect(w.text()).toContain('科幻')
    expect(w.text()).toContain('题材 包含 科幻')
    expect(w.text()).toContain('2 本')
  })

  it('新建时预览调用服务端；「为空」操作不要求填值', async () => {
    const w = mount(SmartScopesView)
    await flushPromises()

    await w.findAll('button').find((b) => b.text() === '新建')!.trigger('click')
    await w.find('input[aria-label="智能书架名称"]').setValue('新书架')
    // 字段下拉选项来自接口（作者 / 题材 / 阅读状态 / ISBN）
    const fieldOptions = w.find('select[aria-label="规则字段"]').findAll('option').map((o) => o.text())
    expect(fieldOptions).toEqual(['作者', '题材', '阅读状态', 'ISBN'])

    // 把操作切到「为空」：值输入框应当消失（needs_value=false）
    await w.find('select[aria-label="规则操作符"]').setValue('is_empty')
    await flushPromises()
    expect(w.find('input[aria-label="规则值"]').exists()).toBe(false)

    await vi.waitFor(() => expect(m.preview).toHaveBeenCalled(), { timeout: 2000 })
    await flushPromises()
    expect(w.text()).toContain('命中 1 本')
  })

  it('预览失败如实显示，而不是显示 0 本', async () => {
    m.preview.mockRejectedValue(new Error('书库不存在'))
    const w = mount(SmartScopesView)
    await flushPromises()

    await w.findAll('button').find((b) => b.text() === '新建')!.trigger('click')
    await w.find('input[aria-label="智能书架名称"]').setValue('新书架')
    await w.find('input[aria-label="规则值"]').setValue('科幻')

    await vi.waitFor(() => expect(w.text()).toContain('预览失败'), { timeout: 2000 })
    expect(w.text()).not.toContain('命中 0 本')
  })
})
