import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DashboardSettingsSheet from '@/components/dashboard/DashboardSettingsSheet.vue'
import { useDashboardStore } from '@/stores/dashboard'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 自定义面板的「库范围」勾选区（第 83 期）。
 *
 * 测的是一条**静默**交互：面板的 checkbox 是受控的（`:checked` 绑定 + `@change`），
 * 而「取消最后一个勾选」这条路径**故意不改 store**（拒绝）。⇒ Vue 不重渲染，
 * 浏览器已经翻过去的原生勾选态会留在原地：用户看到「未勾选」，标题却还写着
 * 「1 个书库」，而且再点一下会变成**选中**（方向反了）。
 *
 * ⇒ 拒绝时必须把 `input.checked` 手动翻回去。这条不测就会静默回归。
 */

vi.mock('@/lib/api', () => ({
  api: {
    libraries: vi.fn(async () => ({
      items: [
        { id: 'lib-a', name: '科幻', type: 'ebook', book_count: 3 },
        { id: 'lib-b', name: '历史', type: 'ebook', book_count: 5 },
      ],
      source_roots: [],
    })),
  },
}))

function mountSheet() {
  return mount(DashboardSettingsSheet, {
    props: { open: true },
    global: { stubs: { Teleport: true } },
  })
}

/** 切到「书架」页并展开第一行的库范围面板 */
async function openFirstScope() {
  const w = mountSheet()
  const tabs = w.findAll('button')
  const shelvesTab = tabs.find((b) => b.text() === '书架')
  expect(shelvesTab).toBeTruthy()
  await shelvesTab!.trigger('click')
  const scopeBtn = w.findAll('button').find((b) => b.text().includes('库范围'))
  expect(scopeBtn).toBeTruthy()
  await scopeBtn!.trigger('click')
  return w
}

describe('库范围勾选（第 83 期）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('勾一个库 ⇒ 标题从「全部书库」变成「1 个书库」，且只留那一个', async () => {
    const w = await openFirstScope()
    const boxes = w.findAll('input[type="checkbox"]')
    expect(boxes.length).toBe(2)

    await boxes[0].setValue(true)

    const dash = useDashboardStore()
    const target = dash.shelves[0]
    expect(target.library_ids).toEqual(['lib-a'])
    expect(w.text()).toContain('1 个书库')
  })

  it('取消最后一个勾选被拒绝 ⇒ 勾选态翻回「仍选中」且偏好不变（受控 checkbox 的坑）', async () => {
    const w = await openFirstScope()
    const boxes = w.findAll('input[type="checkbox"]')
    await boxes[0].setValue(true)
    await w.vm.$nextTick()

    // 取消那唯一的一个：handler 会拒绝并把原生态翻回去
    await boxes[0].setValue(false)
    await w.vm.$nextTick()

    const dash = useDashboardStore()
    expect(dash.shelves[0].library_ids).toEqual(['lib-a'])
    // 关键断言：DOM 勾选态必须与 store 一致（不是浏览器留下的假象）
    const after = w.findAll('input[type="checkbox"]')
    expect((after[0].element as HTMLInputElement).checked).toBe(true)
    expect(w.text()).toContain('1 个书库')
  })

  it('取消非最后一个勾选正常生效', async () => {
    const w = await openFirstScope()
    const boxes = w.findAll('input[type="checkbox"]')
    await boxes[0].setValue(true)
    await boxes[1].setValue(true)
    await w.vm.$nextTick()
    expect(useDashboardStore().shelves[0].library_ids).toEqual(['lib-a', 'lib-b'])

    await boxes[0].setValue(false)
    await w.vm.$nextTick()

    expect(useDashboardStore().shelves[0].library_ids).toEqual(['lib-b'])
    const after = w.findAll('input[type="checkbox"]')
    expect((after[0].element as HTMLInputElement).checked).toBe(false)
    expect((after[1].element as HTMLInputElement).checked).toBe(true)
  })

  it('点「全部书库」清空数组（= 全部），不是另设一个 magic id', async () => {
    const w = await openFirstScope()
    const boxes = w.findAll('input[type="checkbox"]')
    await boxes[0].setValue(true)
    await w.vm.$nextTick()

    const allBtn = w.findAll('button').find((b) => b.text() === '全部书库')
    expect(allBtn).toBeTruthy()
    await allBtn!.trigger('click')

    expect(useDashboardStore().shelves[0].library_ids).toEqual([])
  })

  it('拒绝时给出提示（而不是静默不动）', async () => {
    const w = await openFirstScope()
    const boxes = w.findAll('input[type="checkbox"]')
    await boxes[0].setValue(true)
    await w.vm.$nextTick()

    const ui = useUiStore()
    const spy = vi.spyOn(ui, 'toast')
    await boxes[0].setValue(false)

    expect(spy).toHaveBeenCalledWith(expect.stringContaining('至少选一个书库'))
  })
})
