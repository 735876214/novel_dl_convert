import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api } from '@/lib/api'
import AdvancedPage from '@/views/settings/pages/AdvancedPage.vue'

/**
 * 「直接编辑 config.yaml 原文」的**不认识键**提示（第 263 期）。
 *
 * 这个端点让用户**手写整个配置文件** ⇒ 最容易打错键名 ⇒ 而那个键
 * **不会被任何读点消费**（写了等于没写）⇒ 回执必须**当场**说出来。
 *
 * 坏起来是**静默**的：界面只说「已保存」，用户以为配好了 ⇒ 那个设置
 * 永远不生效 ⇒ 他会一直查「为什么改了没用」。
 */
vi.mock('@/lib/api', () => ({
  api: {
    getConfig: vi.fn(),
    saveConfig: vi.fn(),
    clearOverrides: vi.fn(),
    getRawConfig: vi.fn(),
    saveRawConfig: vi.fn(),
    listBackups: vi.fn(),
    restoreBackup: vi.fn(),
    resetConfig: vi.fn(),
  },
}))

const mounted: VueWrapper[] = []

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
}

async function mountPage(): Promise<VueWrapper> {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const w = mount(AdvancedPage, { global: { plugins: [router] } })
  mounted.push(w)
  await flushPromises()
  return w
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  vi.mocked(api.getConfig).mockResolvedValue({
    config: {}, overrides: {}, overridden: [], config_file: '', settings_file: '', backup_dir: '',
  } as never)
  vi.mocked(api.getRawConfig).mockResolvedValue({
    exists: true, text: 'watcher:\n  enabled: false\n', path: 'c.yaml', mtime: 1, size: 10,
  } as never)
  vi.mocked(api.listBackups).mockResolvedValue({ items: [] } as never)
})

describe('原文编辑：不认识的键要当场说出来（第 263 期）', () => {
  it('回执带 unknown_keys 时，页面上明说那些键没人读', async () => {
    vi.mocked(api.saveRawConfig).mockResolvedValue({
      ok: true, backup: 'config-1.yaml', unknown_keys: ['watcher.interva'],
    } as never)
    const w = await mountPage()
    const ta = w.find('textarea')
    await ta.setValue('watcher:\n  interva: 999\n')
    const btn = w.findAll('button').find((b) => b.text().includes('保存'))
    await btn!.trigger('click')
    await flushPromises()
    await flushPromises()
    expect(w.text()).toContain('watcher.interva')
    expect(w.text()).toContain('没人读')
  })

  it('没有不认识键时，不出那条提示', async () => {
    vi.mocked(api.saveRawConfig).mockResolvedValue({
      ok: true, backup: 'config-1.yaml', unknown_keys: [],
    } as never)
    const w = await mountPage()
    const btn = w.findAll('button').find((b) => b.text().includes('保存'))
    await btn!.trigger('click')
    await flushPromises()
    await flushPromises()
    expect(w.text()).not.toContain('没人读')
  })
})
