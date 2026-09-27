import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import AppHeader from '@/components/AppHeader.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type AppConfig, type PrefDevice } from '@/lib/api'
import type { PrefsPayload } from '@/lib/prefsPayload'

/**
 * 顶栏图标行的**接线**哨兵（第 65 期 2/5）。
 *
 * 该组件在本次改动前**零 spec**，而这一行恰恰是「看得出坏了、但不会报错」的那类：
 *   · 少挂一个入口 —— 那个页面从顶栏消失了，用户只会以为「功能没了」；
 *   · 路径写错（比如「阅读记录」写成 `/reading-log`）—— 点了跳 404 白页；
 *   · 成就门控判据写反 —— 关掉开关反而显示、或读不到配置就整块消失；
 *   · 绕回抽屉 —— 抽屉那套状态已被删掉，退回旧写法会与浮层叠成两层。
 *
 * 子组件（通知 / 任务 / 外观 / 账户）各自有 spec，这里只为「接线」断言。
 */
vi.mock('@/lib/api', () => ({
  api: {
    // AppHeader 自己：`onMounted` 拉一次配置（成就门控）+ `sync.init()` 启动偏好同步
    getConfig: vi.fn(),
    prefProfiles: vi.fn(),
    prefDevices: vi.fn(),
    prefDeviceUpsert: vi.fn(),
    // 子组件（它们的正确性归各自的 spec）
    notifications: vi.fn(),
    markNotificationsRead: vi.fn(),
    tasks: vi.fn(),
  },
  apiErrorMessage: (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback),
}))

/** 只给门控用得上的那一个键；`AppConfig` 其余部分是设置页的事，这里不造完整桩 */
function configPayload(achievements: { enabled: boolean } | null) {
  return {
    config: (achievements ? { achievements } : {}) as unknown as AppConfig,
    overrides: {},
    overridden: [],
    config_file: '',
    settings_file: '',
    backup_dir: '',
  }
}

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/shelf', component: { template: '<div />' } },
      { path: '/stats', component: { template: '<div />' } },
      { path: '/tools', component: { template: '<div />' } },
      { path: '/log', component: { template: '<div />' } },
      { path: '/reading-activity', component: { template: '<div />' } },
      { path: '/achievements', component: { template: '<div />' } },
      { path: '/tasks', component: { template: '<div />' } },
      { path: '/notify', component: { template: '<div />' } },
      { path: '/settings', component: { template: '<div />' } },
      { path: '/settings/reader/general', component: { template: '<div />' } },
      { path: '/settings/account/profile', component: { template: '<div />' } },
    ],
  })
}

const mounted: VueWrapper[] = []

async function mountHeader(): Promise<{ w: VueWrapper; router: Router }> {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const w = mount(AppHeader, { global: { plugins: [router] } })
  mounted.push(w)
  await flushPromises()
  return { w, router }
}

/** 图标行里的按钮（`IconButton` 渲染出来的那些；头像不在其中） */
function iconButtons(w: VueWrapper) {
  return w.findAll('[data-icon-button] > button')
}

function labels(w: VueWrapper): string[] {
  return iconButtons(w).map((b) => b.attributes('aria-label') ?? '')
}

function buttonByLabel(w: VueWrapper, label: string) {
  return iconButtons(w).find((b) => b.attributes('aria-label') === label)
}

beforeEach(() => {
  setActivePinia(createPinia())
  // `cfg` 是**模块级**单例：`loadConfig(false, …)` 见到非空就直接返回 ——
  // 不重置的话，本文件第二个用例起全都沿用第一个用例的配置，门控用例会假绿。
  useSettingsConfig().cfg.value = null

  vi.mocked(api.getConfig).mockResolvedValue(configPayload({ enabled: true }))
  vi.mocked(api.prefProfiles).mockResolvedValue({ items: [] })
  vi.mocked(api.prefDevices).mockResolvedValue({ items: [] })
  vi.mocked(api.prefDeviceUpsert).mockResolvedValue({
    id: 'dev-spec',
    name: '测试机',
    payload: {} as PrefsPayload,
    active_profile_id: null,
    created_at: 0,
    last_seen: 0,
  } satisfies PrefDevice)
  vi.mocked(api.notifications).mockResolvedValue({ items: [], count: 0, unread: 0, unread_total: 0 })
  vi.mocked(api.tasks).mockResolvedValue({ items: [], count: 0 })
})

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('AppHeader（第 65 期顶栏入口行）', () => {
  it('图标行 = 9 个圆形按钮，加上本来就是圆形的头像', async () => {
    const { w } = await mountHeader()

    expect(labels(w)).toEqual([
      '通知',
      '数据统计',
      '任务',
      '工具',
      '阅读记录',
      '阅读活动',
      '成就',
      '外观',
      '设置',
    ])
    for (const b of iconButtons(w)) {
      expect(b.classes(), `「${b.attributes('aria-label')}」不是圆形`).toContain('rounded-full')
    }

    const avatar = w.find('button[aria-label="账户菜单"]')
    expect(avatar.exists(), '头像丢了').toBe(true)
    expect(avatar.classes()).toContain('rounded-full')
  })

  it('工具 / 阅读记录 / 阅读活动 各自跳到正确的路由', async () => {
    const { w, router } = await mountHeader()

    const cases = [
      ['工具', '/tools'],
      ['阅读记录', '/log'],
      ['阅读活动', '/reading-activity'],
    ] as const
    for (const [label, path] of cases) {
      const btn = buttonByLabel(w, label)
      expect(btn, `顶栏找不到「${label}」`).toBeTruthy()
      await btn!.trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.path, `「${label}」跳错了`).toBe(path)
    }
  })

  it('成就入口：开关关掉时整块不渲染，读不到配置时按启用显示', async () => {
    vi.mocked(api.getConfig).mockResolvedValue(configPayload({ enabled: false }))
    const a = await mountHeader()
    expect(buttonByLabel(a.w, '成就'), '成就开关已关，入口却还在').toBeUndefined()
    expect(iconButtons(a.w)).toHaveLength(8)

    // 反向哨兵：读配置失败时**不静默隐藏** —— 读不到就把入口藏起来，
    // 用户会以为功能没了，比多显示一个入口更糟（与侧栏原来的口径逐字一致）。
    useSettingsConfig().cfg.value = null
    vi.mocked(api.getConfig).mockRejectedValue(new Error('boom'))
    const b = await mountHeader()
    expect(buttonByLabel(b.w, '成就'), '配置读不到时不该把入口藏起来').toBeTruthy()
  })

  it('任务入口开的是浮层，不是右侧抽屉', async () => {
    const { w } = await mountHeader()
    expect(w.text(), '没点就渲染出任务面板了').not.toContain('查看全部任务')

    const btn = buttonByLabel(w, '任务')
    expect(btn, '顶栏找不到任务入口').toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    // 抽屉那套（`ui.drawerOpen` + `App.vue` 的遮罩）本期已删；
    // 判据落在「就地展开一块面板」上。
    expect(w.text()).toContain('任务队列')
    expect(w.text()).toContain('查看全部任务')
    expect(w.find('div.fixed.inset-0').exists(), '又出现了全屏遮罩（抽屉的老写法）').toBe(false)
  })

  it('去重：通知与数据统计各只有一个入口', async () => {
    // 用户口径 2：七项搬过来后，原本就在顶栏的这几项**不许变成两个按钮**。
    const { w } = await mountHeader()
    expect(labels(w).filter((l) => l === '通知')).toHaveLength(1)
    expect(labels(w).filter((l) => l === '数据统计')).toHaveLength(1)
  })
})
