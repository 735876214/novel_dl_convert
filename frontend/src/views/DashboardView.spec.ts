import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import DashboardView from '@/views/DashboardView.vue'

/**
 * 仪表盘**页级三态**的接线（第 98 期）。
 *
 * 判据本身在 `lib/dashboardPageState.spec.ts` 里穷举；这里钉的是**接线** —— 页面在读哪几条
 * 真实状态，以及「什么时候不许遮住真内容」。接错**不会报错**：只会让首页永远显示骨架
 * （或者永远不显示），而那正是第 82 / 83 期拒绝做页级三态的理由
 * （`docs/bookorbit/bookorbit-dashboard-styles.md` §7.4）。
 */
vi.mock('@/lib/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/lib/api')>()
  return { ...real, api: { ...real.api, stats: vi.fn() } }
})

const m = api as unknown as { stats: Mock }

/** 部件行 / 书架行 / 两个空态都是重组件（各自还要拉数据）⇒ 一律替身，只验页级骨架与错误 */
const STUBS = {
  FirstRunNotice: true,
  DashboardWelcome: true,
  DashboardWidgetRow: true,
  DashboardShelfRow: true,
  DashboardSettingsSheet: true,
}

let router: Router

beforeEach(async () => {
  setActivePinia(createPinia())
  router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
  await router.push('/')
  await router.isReady()
})

async function mountView() {
  const w = mount(DashboardView, { global: { plugins: [router], stubs: STUBS } })
  await flushPromises()
  return w
}

describe('DashboardView：页级三态（第 98 期）', () => {
  it('两条首屏请求都没 settle、书目还在路上 ⇒ 页级骨架，且不渲染部件行', async () => {
    m.stats.mockReturnValue(new Promise(() => {})) // 永远不 settle = 真的还在路上
    useLibraryStore().loading = true

    const w = await mountView()

    expect(w.find('[data-page-skeleton]').exists()).toBe(true)
    expect(w.text()).toContain('正在载入首页')
    // 骨架期不渲染真内容 —— 否则就是「页级骨架 + 13 个部件骨架」两层一起闪
    expect(w.find('dashboard-widget-row-stub').exists()).toBe(false)
    w.unmount()
  })

  it('统计一到手就不再遮（哪怕书目还在路上）—— 有真数据就不许盖住', async () => {
    m.stats.mockResolvedValue({ library_id: '' })
    useLibraryStore().loading = true

    const w = await mountView()

    expect(w.find('[data-page-skeleton]').exists()).toBe(false)
    expect(w.find('dashboard-widget-row-stub').exists()).toBe(true)
    w.unmount()
  })

  it('没有任何请求在路上时**不**显示骨架（不许凭「刚进页面」就遮）', async () => {
    m.stats.mockReturnValue(new Promise(() => {}))
    useLibraryStore().loading = false

    const w = await mountView()

    expect(w.find('[data-page-skeleton]').exists()).toBe(false)
    w.unmount()
  })

  it('两条都失败且什么都没拿到 ⇒ 页级错误，且「重试」把两条一起重拉', async () => {
    m.stats.mockRejectedValue(new Error('统计挂了'))
    const lib = useLibraryStore()
    lib.loading = false
    const reload = vi.spyOn(lib, 'loadBooks').mockResolvedValue(undefined)

    const w = await mountView()
    lib.booksError = '书库挂了'
    await flushPromises()

    expect(w.text()).toContain('首页数据加载失败')
    expect(w.text()).toContain('统计挂了')
    expect(w.text()).toContain('书库挂了')

    m.stats.mockClear()
    const btn = w.findAll('button').find((b) => b.text().trim() === '重试')
    expect(btn, '页级错误要有一个「重试」').toBeTruthy()
    await btn!.trigger('click')

    expect(m.stats).toHaveBeenCalledTimes(1) // 统计那一发
    expect(reload).toHaveBeenCalledWith(true) // …与书目那一发（一起重试）
    w.unmount()
  })
})
