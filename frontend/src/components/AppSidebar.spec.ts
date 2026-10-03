import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import AppSidebar from '@/components/AppSidebar.vue'
import { api } from '@/lib/api'

/**
 * 侧栏的**接线**哨兵（第 65 期 1/5）。
 *
 * 本期在侧栏上动了三处，每一处的失效方式都不会报错：
 *   · 删七项 —— 少删一项就是「同一页两个入口」（顶栏一个、侧栏一个），
 *     用户按哪条都能走，于是没人会发现多了一条；
 *   · 加「收书目录」—— 路由指错（比如指到 `/settings/admin/book-dock`）时，
 *     页面**照样打得开**，只是整个左栏换成了设置侧栏；
 *   · 浏览组计数 —— `navCount()` 里删 `'running'` 分支时手一抖删多了，
 *     胶囊会静默消失（不报错、不占位，只是数字没了）。
 */
vi.mock('@/lib/api', () => ({
  api: {
    browseCounts: vi.fn(),
    // 侧栏 `onMounted` 会顺带拉起四个 store 的加载（书 / 库 / 书架 / 收藏夹）——
    // 这些桩只为「不炸」，它们的正确性归各自的 spec 管。
    collections: vi.fn(),
    books: vi.fn(),
    libraries: vi.fn(),
    smartScopes: vi.fn(),
    features: vi.fn(),
    // ⚠️ `ensureThresholds`（lib/readingThresholds）**直接 `.then()` 它的返回值** ——
    // 给 `undefined` 会在它自己的 `.catch` 之前**同步**抛 TypeError，
    // 整套用例会以「加载失败」的形式红掉（第 63 期 BookDetailView.spec 记过这一条）。
    readingThresholds: vi.fn().mockResolvedValue({ started: 1, finished: 99 }),
  },
  apiErrorMessage: (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback),
}))

const browseCounts = vi.mocked(api.browseCounts)

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/explore', component: { template: '<div />' } },
      { path: '/book-dock', component: { template: '<div />' } },
      { path: '/shelf', component: { template: '<div />' } },
      { path: '/browse', component: { template: '<div />' } },
      { path: '/series', component: { template: '<div />' } },
      { path: '/authors', component: { template: '<div />' } },
      { path: '/annotations', component: { template: '<div />' } },
      { path: '/docs', component: { template: '<div />' } },
      { path: '/whats-new', component: { template: '<div />' } },
      { path: '/settings/ext/about', component: { template: '<div />' } },
      { path: '/settings/libraries', component: { template: '<div />' } },
    ],
  })
}

const mounted: VueWrapper[] = []

async function mountSidebar(router: Router): Promise<VueWrapper> {
  await router.push('/')
  await router.isReady()
  const w = mount(AppSidebar, { global: { plugins: [router] } })
  mounted.push(w)
  await flushPromises()
  return w
}

beforeEach(() => {
  setActivePinia(createPinia())
  browseCounts.mockResolvedValue({
    library_id: '',
    authors: 3,
    series: 5,
    annotations: 2,
    books: 12,
    computed_at: 0,
    cached: false,
  })
  vi.mocked(api.collections).mockResolvedValue({ items: [] })
  vi.mocked(api.books).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(api.libraries).mockResolvedValue({ items: [], total: 0, types: [], source_roots: [] })
  vi.mocked(api.smartScopes).mockResolvedValue({ items: [] })
  vi.mocked(api.features).mockResolvedValue({
    library_id: '',
    library_type: '',
    features: [],
    matrix: { types: {}, all: [], labels: {} },
  })
})

afterEach(() => {
  // ⚠️ 必须先 unmount 再清 body：Teleport 出去的内容不随组件卸载消失，
  // 直接清 body 会让后续用例的报错指向上一个用例（第 64 期的教训）。
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('AppSidebar（第 65 期导航改造）', () => {
  it('点「收书目录」进顶层路由 /book-dock', async () => {
    const router = makeRouter()
    const w = await mountSidebar(router)

    // 第 90 期：导航行从「可点 `<div>`」换成上游的 `SidebarMenuButton`，并且是
    // **真 `<button>`** —— 按旧选择器找 `<div>` 会找不到，而找不到时这个用例只会
    // 在 `toBeTruthy` 上红，看不出是「行换了标签」还是「项被删了」。所以按数据属性找。
    //
    // ⚠️ 认 `data-sidebar="menu-button"`，**不要认 `data-slot="sidebar-menu-button"`**：
    // 带 tooltip 时 `SidebarMenuButton` 把行塞进 `TooltipTrigger as-child`，触发器
    // 自己的 `data-slot="tooltip-trigger"` 会把行上的同名属性**顶掉**（上游同样如此）。
    const item = w
      .findAll('[data-sidebar="menu-button"]')
      .find((b) => b.text().trim() === '收书目录')
    expect(item, '侧栏里找不到「收书目录」这一项').toBeTruthy()
    await item!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/book-dock')
  })

  it('七个搬走的入口在 DOM 里一个都不剩', async () => {
    const w = await mountSidebar(makeRouter())
    const text = w.text()
    for (const label of ['任务中心', '工具', '数据统计', '阅读记录', '阅读活动', '通知中心', '成就']) {
      expect(text, `侧栏还在渲染「${label}」`).not.toContain(label)
    }
  })

  it('保留下来的入口照旧（浏览组 / 帮助组）', async () => {
    // 反向哨兵：改侧栏时删多了会在这里红。本期只搬用户点名的那七项。
    const w = await mountSidebar(makeRouter())
    const text = w.text()
    for (const label of ['仪表盘', '探索发现', '实体总览', '作者', '系列', '批注', '说明书']) {
      expect(text, `侧栏少了「${label}」`).toContain(label)
    }
  })

  /**
   * 取某一项的**整行文本**（「作者」有计数时是 `作者3`，没计数时就是 `作者`）。
   *
   * 用 `startsWith` 而不是 `includes`：祖先容器的 text 也包含这些字，
   * 而按 DOM 顺序第一个以组标题开头的祖先不会误中（所以只取最内层那一行）。
   *
   * 第 90 期改按 `data-sidebar="menu-button"` 取行：行已从 `<div>` 换成 `<button>`
   * （见上一条用例的说明：`data-slot` 会被 tooltip 触发器顶掉，只有 `data-sidebar`
   * 是稳的），而按标签名捞会先捞到 `<li>` 等外层容器。
   */
  function rowOf(w: VueWrapper, label: string): string {
    const hit = w
      .findAll('[data-sidebar="menu-button"]')
      .find((b) => b.text().trim().startsWith(label))
    return hit?.text().trim() ?? ''
  }

  it('浏览组三项仍然显示真实计数胶囊', async () => {
    // 删 `'running'` 分支时手一抖删多了（比如整段 return null），胶囊会静默消失
    const w = await mountSidebar(makeRouter())
    expect(rowOf(w, '作者')).toBe('作者3')
    expect(rowOf(w, '系列')).toBe('系列5')
    expect(rowOf(w, '批注')).toBe('批注2')
  })

  it('计数读失败时胶囊不渲染（不拿 0 冒充）', async () => {
    // 显示 0 是个具体的数字，会与「真的没有」混淆 —— 宁可什么都不显示
    browseCounts.mockRejectedValue(new Error('boom'))
    const w = await mountSidebar(makeRouter())
    expect(rowOf(w, '作者')).toBe('作者')
    expect(rowOf(w, '系列')).toBe('系列')
  })
})
