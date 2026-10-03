import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import AppMoreMenu from '@/components/AppMoreMenu.vue'
import { api, type TaskItem } from '@/lib/api'
import { useTasksStore } from '@/stores/tasks'

/**
 * 窄屏「更多」菜单的哨兵（第 91 期）。
 *
 * 这一块坏起来**一声不响**：
 *   · 少挂一项 → 那一页在窄屏**彻底没有入口**（它第 65 期已从侧栏撤掉），用户只会以为功能没了；
 *   · 路径写错 → 点了跳 404 白页；
 *   · 成就门控写反 → 关掉开关反而出现，或读不到配置就整块消失；
 *   · 忘了「先关面板再跳」→ 面板 Teleport 在 body 上，会浮在新页面上不消失。
 *
 * 所以断言全部落在**行为**上：点了真的跳、面板真的关、七项一个不少。
 */
vi.mock('@/lib/api', () => ({
  api: { tasks: vi.fn() },
  apiErrorMessage: (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback),
}))

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/stats', component: { template: '<div />' } },
      { path: '/tasks', component: { template: '<div />' } },
      { path: '/tools', component: { template: '<div />' } },
      { path: '/log', component: { template: '<div />' } },
      { path: '/reading-activity', component: { template: '<div />' } },
      { path: '/achievements', component: { template: '<div />' } },
      { path: '/settings', component: { template: '<div />' } },
    ],
  })
}

const mounted: VueWrapper[] = []

async function mountMenu(achievementsEnabled = true) {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const w = mount(AppMoreMenu, {
    props: { achievementsEnabled },
    global: { plugins: [router] },
    // ⚠️ 必须挂进 `document.body`：本组件自己查 `document`（面板被 Teleport 走了），
    // 不 attachTo 的话连触发器都不在 document 里，`querySelector` 全是 null。
    attachTo: document.body,
  })
  mounted.push(w)
  await flushPromises()
  return { w, router }
}

/**
 * 触发器与面板**都在 `document.body` 的查询范围里**（面板被 `DropdownMenu` Teleport 走了），
 * 所以这里查 `document` 而不是 `wrapper.find` —— 后者找不到面板。
 */
function trigger(): HTMLButtonElement | null {
  return document.body.querySelector('[data-more-menu-trigger] button')
}

function panelItems(): HTMLButtonElement[] {
  return Array.from(document.body.querySelectorAll('[data-book-menu-panel] [role="menuitem"]'))
}

/** 条目文案（去掉角标里的数字与多余空白，只留标签） */
function itemLabels(): string[] {
  return panelItems().map((b) => (b.textContent ?? '').trim().split(/\s+/)[0] ?? '')
}

async function openMenu(w: VueWrapper): Promise<void> {
  await w.find('[data-more-menu-trigger]').trigger('click')
  await flushPromises()
}

function task(id: string, status: string): TaskItem {
  return {
    id, type: 'scrape', title: id, detail: '', status, progress: 0,
    error: '', result: '', name: '', notice: '', actor: '',
    created_at: 0, updated_at: 0,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.tasks).mockResolvedValue({ items: [], count: 0 })
})

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('AppMoreMenu（第 91 期窄屏「更多」）', () => {
  it('触发器有 aria-label 与测试钩子，且默认不渲染面板', async () => {
    await mountMenu()
    const btn = trigger()
    expect(btn, '找不到「更多」触发器').toBeTruthy()
    expect(btn!.getAttribute('aria-label')).toBe('更多')
    expect(panelItems(), '没点就渲染出面板了').toHaveLength(0)
  })

  it('七个入口一个不少（成就开启时）', async () => {
    const { w } = await mountMenu(true)
    await openMenu(w)

    expect(itemLabels()).toEqual([
      '数据统计',
      '任务',
      '工具',
      '阅读记录',
      '阅读活动',
      '成就',
      '设置',
    ])
  })

  it('每个入口都真的跳到对应路由，且跳完面板自行关闭', async () => {
    const { w, router } = await mountMenu(true)
    const cases = [
      ['数据统计', '/stats'],
      ['任务', '/tasks'],
      ['工具', '/tools'],
      ['阅读记录', '/log'],
      ['阅读活动', '/reading-activity'],
      ['成就', '/achievements'],
      ['设置', '/settings'],
    ] as const

    for (const [label, path] of cases) {
      await openMenu(w)
      const btn = panelItems().find((b) => (b.textContent ?? '').includes(label))
      expect(btn, `面板里找不到「${label}」`).toBeTruthy()
      btn!.click()
      await flushPromises()
      expect(router.currentRoute.value.path, `「${label}」跳错了`).toBe(path)
      // ⚠️ 关键：Teleport 到 body 的面板不关就会浮在新页面上。
      expect(panelItems(), `点了「${label}」后面板还开着`).toHaveLength(0)
    }
  })

  it('成就开关关掉时整项不出现（不是灰置、不是占位）', async () => {
    const { w } = await mountMenu(false)
    await openMenu(w)

    expect(itemLabels()).toEqual(['数据统计', '任务', '工具', '阅读记录', '阅读活动', '设置'])
    expect(itemLabels()).not.toContain('成就')
  })

  it('任务「运行中 + 排队中」的角标同时透到菜单项与触发器上', async () => {
    useTasksStore().tasks = [
      task('跑步中', 'running'),
      task('排队中', 'queued'),
      task('已完成', 'done'), // 不含已完成：那个数只会越来越大
    ]
    const { w } = await mountMenu()
    await openMenu(w)

    const taskItem = panelItems().find((b) => (b.textContent ?? '').includes('任务'))
    expect(taskItem!.textContent).toContain('2')

    // 触发器上的角标 = 同一份 `runningCount`：窄屏若不在触发器上显示，
    // 「有任务在跑」就只剩「点开菜单才知道」这一个信号了。
    expect(document.body.querySelector('[data-more-menu-trigger]')?.textContent).toContain('2')
  })
})
