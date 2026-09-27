import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import TaskFlyout from '@/components/TaskFlyout.vue'
import { api, type TaskItem } from '@/lib/api'
import { useTasksStore } from '@/stores/tasks'

/**
 * 任务浮层的哨兵（第 65 期 2/5）。
 *
 * 它取代的是右侧滑出抽屉（`TaskDrawer.vue`，已删）。两处失效方式特别安静：
 *   · 角标改回「全部任务数」—— 数字照样在跳，只是含了已完成，越滚越大没人察觉；
 *   · 打开时不 `refresh()` —— 浮层照样能开，只是显示上一次拉到的旧数据。
 *
 * 「查看全部任务 / Esc / 点外部关闭」是流程口径（用户：「流程也参考通知的样式」）。
 */
vi.mock('@/lib/api', () => ({
  api: { tasks: vi.fn() },
}))

function task(over: Partial<TaskItem>): TaskItem {
  return {
    id: 't1',
    type: 'convert',
    title: '任务',
    detail: '',
    status: 'running',
    progress: 50,
    error: '',
    result: '',
    name: '',
    notice: '',
    actor: '',
    created_at: 0,
    updated_at: 0,
    ...over,
  }
}

const RUNNING = task({ id: 'run-1', title: '转换：三体.epub', status: 'running', progress: 50 })
const QUEUED = task({ id: 'q-1', title: '转换：球状闪电.epub', status: 'queued' })
const DONE = task({ id: 'd-1', title: '转换：超新星纪元.epub', status: 'done', progress: 100 })
const FAILED = task({ id: 'f-1', title: '转换：流浪地球.epub', status: 'failed', error: '源文件损坏' })

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/tasks', component: { template: '<div />' } },
    ],
  })
}

const mounted: VueWrapper[] = []

async function mountFlyout(): Promise<{ w: VueWrapper; router: Router }> {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const w = mount(TaskFlyout, { global: { plugins: [router] } })
  mounted.push(w)
  await flushPromises()
  return { w, router }
}

/** 触发器按钮 */
function trigger(w: VueWrapper) {
  const btn = w.find('[data-icon-button] > button')
  expect(btn.exists(), '找不到任务入口按钮').toBe(true)
  return btn
}

/** 底部「查看全部任务」 */
function allBtn(w: VueWrapper) {
  const btn = w.findAll('button').find((b) => b.text().includes('查看全部任务'))
  expect(btn, '浮层里没有「查看全部任务」').toBeTruthy()
  return btn!
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.tasks).mockResolvedValue({ items: [RUNNING, QUEUED, DONE, FAILED], count: 4 })
})

afterEach(() => {
  // 桩里有 running 任务 ⇒ `syncPolling()` 会起一个 2.5s 轮询；不清掉会跨用例累积
  useTasksStore().stopPolling()
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('TaskFlyout（第 65 期：抽屉改浮层）', () => {
  it('点按钮开浮层，再点关闭', async () => {
    const { w } = await mountFlyout()
    expect(w.text()).not.toContain('任务队列')

    await trigger(w).trigger('click')
    await flushPromises()
    expect(w.text()).toContain('任务队列')

    await trigger(w).trigger('click')
    await flushPromises()
    expect(w.text()).not.toContain('任务队列')
  })

  it('角标 = 运行中 + 排队中，不含已完成', async () => {
    // App.vue 启动时已经拉过一次任务（这里手动走那一步）
    await useTasksStore().refresh()
    const { w } = await mountFlyout()

    expect(trigger(w).text(), '角标把已完成/失败也算进去了').toBe('2')
  })

  it('按状态分组列出任务，失败原因照实显示', async () => {
    const { w } = await mountFlyout()
    await trigger(w).trigger('click')
    await flushPromises()

    const text = w.text()
    for (const t of ['进行中（1）', '排队中（1）', '已完成（1）', '失败（1）']) {
      expect(text, `分组「${t}」不在`).toContain(t)
    }
    expect(text).toContain('转换：三体.epub')
    expect(text).toContain('源文件损坏')
  })

  it('「查看全部任务」进 /tasks，浮层同时关掉', async () => {
    const { w, router } = await mountFlyout()
    await trigger(w).trigger('click')
    await flushPromises()

    await allBtn(w).trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/tasks')
    expect(w.text(), '跳走之后浮层还开着').not.toContain('任务队列')
  })

  it('Esc 关闭、点浮层外部关闭', async () => {
    const { w } = await mountFlyout()
    await trigger(w).trigger('click')
    await flushPromises()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(w.text()).not.toContain('任务队列')

    await trigger(w).trigger('click')
    await flushPromises()
    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(w.text()).not.toContain('任务队列')
  })

  it('没有任务时显示空态（不占位、不假装有）', async () => {
    vi.mocked(api.tasks).mockResolvedValue({ items: [], count: 0 })
    const { w } = await mountFlyout()
    await trigger(w).trigger('click')
    await flushPromises()

    expect(w.text()).toContain('暂无任务')
  })
})
