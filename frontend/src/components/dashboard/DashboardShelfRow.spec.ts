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
 * 最怕的不是「少了个功能」，而是**点上去没反应** —— 读不了的格式必须落到详情页，
 * 不能静默什么都不做。所以用例按格式把三条去路钉死：
 * 能读的进阅读器、有声书进听书器、其余的进详情页。
 *
 * ⚠️ 第 110 期起 **MOBI / AZW3 / AZW 属于「能读的」**（后端直读解包，见
 * `core/mobicache.py`），此前它们在这里是「读不了 ⇒ 详情页」的样例 —— 那条例子的
 * 判据改由**没归一成书的容器**（`ZIP`）承担（它仍读不了）。
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

async function mountRow(books: BookCard[], shelf?: Record<string, unknown>) {
  const lib = useLibraryStore()
  lib.books = books
  lib.loaded = true
  // 组件 onMounted 会拉书目与书库列表：这一层不是本 spec 的判据，替掉免得真发请求
  vi.spyOn(lib, 'loadBooks').mockResolvedValue(undefined)
  vi.spyOn(lib, 'loadLibraries').mockResolvedValue(undefined)

  const w = mount(DashboardShelfRow, {
    props: {
      shelf: shelf
        ? (shelf as never)
        : { id: 'recent', type: 'recent', title: '最近添加', rows: 1, enabled: true },
    },
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

  it('MOBI ⇒ 一次点击直接进阅读器 /read/:id（第 110 期直读落地后不再是「读不了」）', async () => {
    const w = await mountRow([book({ id: 'mobi-1', format: 'MOBI' })])

    await w.get('button.shelf-cover-enter').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/read/mobi-1')
    w.unmount()
  })

  it('AZW3 / AZW 与 MOBI 同一套直读 ⇒ 也进阅读器', async () => {
    const w = await mountRow([book({ id: 'azw3-1', format: 'AZW3' })])

    await w.get('button.shelf-cover-enter').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/read/azw3-1')
    w.unmount()
  })

  it('读不了的（ZIP 容器没归一成 CBZ）⇒ 落到详情页 /book/:id，不许点了没反应', async () => {
    const w = await mountRow([book({ id: 'zip-1', format: 'ZIP' })])

    await w.get('button.shelf-cover-enter').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/book/zip-1')
    w.unmount()
  })

  it('每本书各点各的（判据按被点的那本取值，不是「第一本」）', async () => {
    const w = await mountRow([
      book({ id: 'a-1', format: 'EPUB' }),
      book({ id: 'a-2', format: 'ZIP' }),
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

describe('DashboardShelfRow：继续收听（第 171 期）', () => {
  const listenShelf = { id: 'shelf-listen', type: 'listen', title: '继续收听', rows: 1, enabled: true }

  it('只显示有声书（与「继续阅读」同一份进度阈值，再按格式过滤）', async () => {
    const w = await mountRow(
      [
        book({ id: 'aud-1', title: '有声书一', format: 'AUDIO', percent: 30 }),
        book({ id: 'ep-1', title: '电子书一', format: 'EPUB', percent: 50 }),
      ],
      listenShelf,
    )
    expect(w.findAll('button.shelf-cover-enter')).toHaveLength(1)
    expect(w.text()).toContain('有声书一')
    expect(w.text()).not.toContain('电子书一')
  })

  it('没有在听的有声书时整行不渲染（不听书的用户界面零变化）', async () => {
    const w = await mountRow([book({ id: 'ep-1', format: 'EPUB', percent: 50 })], listenShelf)
    expect(w.find('section').exists()).toBe(false)
  })

  it('「查看全部」带着 ?fmt=AUDIO 进书架（不混进电子书）', async () => {
    const w = await mountRow([book({ id: 'aud-1', format: 'AUDIO', percent: 30 })], listenShelf)
    const all = w.findAll('button').find((b) => b.text().includes('查看全部'))!
    await all.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/shelf')
    expect(router.currentRoute.value.query.fmt).toBe('AUDIO')
  })
})
