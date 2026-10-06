import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import App from '@/App.vue'

/**
 * 外壳与「阅读整屏沉浸」的互斥（第 108 期，用户口径）。
 *
 * 用户要的是「阅读时除正文外其他栏都隐藏」。这里判的不是「藏起来了」而是
 * **根本不渲染**：`v-if / v-else-if` 两条互斥的渲染路径。差别很实在 —— 藏起来那一版
 * 仍然会拉数据、仍然占 DOM，还留着一条 ⌘B 能掀开的缝。
 *
 * ⚠️ 判据走 `route.name`（`read` / `online`）而不是路径前缀：两条路由共用同一个
 * `ReaderView` 组件，名字才是它们的公共点；`/listen/:id`（听书器）**刻意不在内**，
 * 那是播放器不是阅读界面 —— 下面有一条专门钉这个决定。
 */
vi.mock('@/lib/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/lib/api')>()
  const ok = (v: unknown) => vi.fn().mockResolvedValue(v)
  return {
    ...real,
    api: {
      ...real.api,
      me: ok({ user: 'admin' }),
      getProfile: ok({}),
      tasks: ok({ items: [], total: 0 }),
      libraries: ok({ items: [] }),
    },
  }
})

let router: Router

/** 重组件一律替身：本 spec 只判「外壳渲染了没有」，真组件各自有 spec */
const STUBS = {
  LoginGate: true,
  AppSidebar: true,
  SettingsSidebar: true,
  AppHeader: true,
  AppToast: true,
  GuidedTourModal: true,
  LibraryWizard: true,
  // 探针替代路由视图：真 ReaderView 会去拉一整本书，这里不需要
  RouterView: { template: '<div data-slot="route-view" />' },
}

async function mountAt(path: string) {
  await router.push(path)
  await router.isReady()
  const w = mount(App, { global: { plugins: [router], stubs: STUBS } })
  await flushPromises()
  return w
}

beforeEach(() => {
  setActivePinia(createPinia())
  // 有 token ⇒ showLogin 初值就是 false（同步读 localStorage），不必走一遍登录流程
  localStorage.setItem('nf_token', 'tok')
  localStorage.setItem('nf_tour_seen', '1')
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: { template: '<div />' } },
      { path: '/read/:id', name: 'read', component: { template: '<div />' } },
      { path: '/online/:id', name: 'online', component: { template: '<div />' } },
      { path: '/listen/:id', name: 'listen', component: { template: '<div />' } },
      { path: '/shelf', name: 'shelf', component: { template: '<div />' } },
    ],
  })
})

afterEach(() => {
  localStorage.clear()
})

describe('App：阅读路由整屏沉浸（第 108 期）', () => {
  it('/read/:id ⇒ 不渲染顶栏与侧栏，只有路由视图躺在沉浸容器里', async () => {
    const w = await mountAt('/read/book-a')

    expect(w.find('app-header-stub').exists()).toBe(false)
    expect(w.find('app-sidebar-stub').exists()).toBe(false)
    // 外壳根节点的标记：SidebarProvider 那一层整块不在
    expect(w.find('[data-slot="sidebar-wrapper"]').exists()).toBe(false)

    const rv = w.find('[data-slot="route-view"]')
    expect(rv.exists()).toBe(true)
    // 它必须挂在沉浸容器下（而不是外壳的 <main> 里）
    expect(rv.element.parentElement?.className).toContain('h-[100dvh]')
    w.unmount()
  })

  it('/online/:id（同一个 ReaderView 的另一条路由）⇒ 同样沉浸', async () => {
    const w = await mountAt('/online/src-1')

    expect(w.find('app-header-stub').exists()).toBe(false)
    expect(w.find('[data-slot="sidebar-wrapper"]').exists()).toBe(false)
    expect(w.find('[data-slot="route-view"]').exists()).toBe(true)
    w.unmount()
  })

  it('普通页面 ⇒ 外壳照旧（顶栏 + 侧栏都在）', async () => {
    const w = await mountAt('/')

    expect(w.find('app-header-stub').exists()).toBe(true)
    expect(w.find('app-sidebar-stub').exists()).toBe(true)
    expect(w.find('[data-slot="sidebar-wrapper"]').exists()).toBe(true)
    w.unmount()
  })

  it('/listen/:id **刻意**不沉浸 —— 那是播放器不是阅读界面', async () => {
    // 要收进去只需在这个名字集合里加一个 `listen`；这里钉的是「当时决定不收」，
    // 免得日后有人看到「阅读器沉浸了、播放器没有」就当漏改顺手补上。
    const w = await mountAt('/listen/book-a')

    expect(w.find('[data-slot="sidebar-wrapper"]').exists()).toBe(true)
    expect(w.find('app-header-stub').exists()).toBe(true)
    w.unmount()
  })
})
