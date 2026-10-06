import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import DashboardShelfRow from '@/components/dashboard/DashboardShelfRow.vue'
import type { BookCard } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'

/**
 * 仪表盘点封面 = **直接读**（第 108 期，用户口径）。
 *
 * 第 83 期这里是「先弹一层快速预览浮层」，要多点一次才进得去正文。撤掉浮层之后
 * 最怕的不是「少了个功能」，而是**点上去没反应** —— 读不了的格式（MOBI / AZW3）
 * 必须落到详情页，不能静默什么都不做。所以三条用例按格式把三条去路钉死：
 * 能读的进阅读器、有声书进听书器、其余的进详情页。
 *
 * ⚠️ 浮层里那四个管理动作（收藏 / 编辑元数据 / 移动书库 / 删除）**刻意**从仪表盘退场
 * （仪表盘只做快速启动器，书架页与详情页各自都有），所以这里也断言「点了不再有 dialog」——
 * 谁要是把浮层请回来，这条会红。
 */
function book(over: Partial<BookCard>): BookCard {
  return {
    id: 'b1',
    title: '某本书',
    author: '某个人',
    format: 'EPUB',
    has_cover: false,
    percent: 0,
    ...over,
  } as BookCard
}

let router: Router

async function mountRow(books: BookCard[]) {
  const lib = useLibraryStore()
  lib.books = books
  lib.loaded = true
  // 组件 onMounted 会拉书目与书库列表：这一层不是本 spec 的判据，替掉免得真发请求
  vi.spyOn(lib, 'loadBooks').mockResolvedValue(undefined)
  vi.spyOn(lib, 'loadLibraries').mockResolvedValue(undefined)

  const w = mount(DashboardShelfRow, {
    props: { shelf: { id: 'recent', type: 'recent', title: '最近添加', rows: 1, enabled: true } },
    global: { plugins: [router] },
  })
  await flushPromises()
  return w
}

beforeEach(async () => {
  setActivePinia(createPinia())
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/read/:id', name: 'read', component: { template: '<div />' } },
      { path: '/listen/:id', name: 'listen', component: { template: '<div />' } },
      { path: '/book/:id', name: 'book', component: { template: '<div />' } },
      { path: '/shelf', name: 'shelf', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
})

describe('DashboardShelfRow：点封面直接读（第 108 期）', () => {
  it('EPUB ⇒ 一次点击直接进阅读器 /read/:id，且不再有弹窗', async () => {
    const w = await mountRow([book({ id: 'ep-1', format: 'EPUB' })])

    await w.get('button.shelf-cover-enter').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/read/ep-1')
    // 旧浮层是 `role="dialog"` 且 Teleport 到 body ⇒ 要查 document 而不能只查 wrapper
    expect(document.body.querySelector('[role="dialog"]')).toBeNull()
    // 只有封面这一个入口：不存在「第二次点击才进去」的第二层
    w.unmount()
  })

  it('AUDIO ⇒ 进听书器 /listen/:id', async () => {
    const w = await mountRow([book({ id: 'au-1', format: 'AUDIO' })])

    await w.get('button.shelf-cover-enter').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/listen/au-1')
    w.unmount()
  })

  it('MOBI（读不了）⇒ 落到详情页 /book/:id，不许点了没反应', async () => {
    const w = await mountRow([book({ id: 'mobi-1', format: 'MOBI' })])

    await w.get('button.shelf-cover-enter').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/book/mobi-1')
    w.unmount()
  })

  it('每本书各点各的（判据按被点的那本取值，不是「第一本」）', async () => {
    const w = await mountRow([
      book({ id: 'a-1', format: 'EPUB' }),
      book({ id: 'a-2', format: 'MOBI' }),
    ])

    const covers = w.findAll('button.shelf-cover-enter')
    expect(covers).toHaveLength(2)
    await covers[1]!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/book/a-2')
    w.unmount()
  })

  it('「查看全部」仍在：继续阅读行跳「在读」智能书架，其余进书库页', async () => {
    const w = await mountRow([book({ id: 'ep-1' })])

    const all = w.findAll('button').find((b) => b.text().includes('查看全部'))
    expect(all, '表头要保留「查看全部」').toBeTruthy()
    await all!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/shelf')
    w.unmount()
  })
})
