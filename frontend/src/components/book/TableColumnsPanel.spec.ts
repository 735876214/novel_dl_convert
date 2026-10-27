import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import TableColumnsPanel from '@/components/book/TableColumnsPanel.vue'
import { useTablePrefsStore } from '@/stores/tablePrefs'

/**
 * 第 158 期：列面板的接线。
 *
 * 组件坏掉的形态都是「点了没反应」：勾选框没接 store、保存按钮没落盘。
 * 这里只钉接线，规则本身在 `stores/tablePrefs.spec.ts`。
 */
describe('TableColumnsPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('取消勾选一列 ⇒ store 里真的少了这一列；书名不在可勾选集合里', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const s = useTablePrefsStore()
    const w = mount(TableColumnsPanel, { props: { open: true }, global: { plugins: [pinia] } })
    const boxes = w.findAll('input[type="checkbox"]')
    expect(boxes).toHaveLength(6)
    const labels = boxes.map((b) => b.element.closest('label')?.textContent || '')
    expect(labels.some((x) => x.includes('书名'))).toBe(false)
    await boxes[0].setValue(false)
    expect(s.prefs.columns).not.toContain('author')
    await boxes[0].setValue(true)
    expect(s.prefs.columns).toContain('author')
  })

  it('保存当前视图：输入名字点保存后出现在列表里', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const s = useTablePrefsStore()
    s.patch({ columns: ['format'], density: 'compact' })
    const w = mount(TableColumnsPanel, { props: { open: true }, global: { plugins: [pinia] } })
    await w.find('input[aria-label="视图名"]').setValue('漫画')
    const save = w.findAll('button').find((b) => b.text().includes('保存当前'))
    await save!.trigger('click')
    await flushPromises()
    expect(s.views.map((v) => v.name)).toContain('漫画')
    expect(w.text()).toContain('漫画')
  })
})
