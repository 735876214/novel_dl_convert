import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api } from '@/lib/api'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import SettingsLayout from '@/views/settings/SettingsLayout.vue'

/**
 * 设置页的**「段被写坏」红条**（第 252 期）。
 *
 * 背景：config.yaml 里某个**顶层段**被写成别的类型（`watcher: "abc"`，
 * 或者更常见的 `watcher:` 少写子键 ⇒ 解析出来是 `None`）时，那一段会
 * **降级回默认值**运行 ⇒ 用户在设置页看到的也是默认值 —— 不说出来，
 * 他会以为自己的设置还在（而实际上那一段的设置**根本没生效**）。
 *
 * 这与「config.yaml 整个读不出来」是**两件事** ⇒ **两条独立的红条**：
 *   · `configFileError` = 整个文件读不出来（第 141 期）；
 *   · `badSections`     = 文件读得出来，但某些段被写坏（第 252 期）。
 *
 * 这里钉两条：坏段**要**出红条（且点名是哪些段）；好配置**不**出红条。
 */
vi.mock('@/lib/api', () => ({
  api: {
    getConfig: vi.fn(),
    saveConfig: vi.fn(),
    clearOverrides: vi.fn(),
  },
}))

vi.mock('@/components/ui/PageHead.vue', () => ({
  default: { template: '<div />' },
}))
vi.mock('@/components/settings/SettingsSearchPanel.vue', () => ({
  default: { template: '<div />' },
}))
vi.mock('@/data/settingsNav', () => ({
  findSettingsGroup: () => ({ label: '分组', path: '' }),
  findSettingsPage: () => ({ label: '页面', path: '', group: '' }),
}))

const BASE_CONFIG = {
  chapter_detection: {},
  traditionalize: false,
  output: {},
  naming: {},
  llm: { api_key: '', base_url: '', model: '', has_key: false },
  watcher: {},
  network: {},
  download: {},
  logging: {},
  upload: {},
  achievements: {},
  libraries: {},
}

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/settings/:page(.*)', component: { template: '<div />' } },
    ],
  })
}

async function mountLayout(configExtra: Record<string, unknown>): Promise<string> {
  ;(api.getConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
    config: { ...BASE_CONFIG, ...configExtra },
    overridden: [],
    env_overridden: [],
    config_file: 'config.yaml',
    settings_file: 'settings.json',
    backup_dir: 'backups',
  })
  // ⚠️ `useSettingsConfig` 是**模块级单例**（配置草稿跨页共享）⇒ 必须**先**
  // 把配置拉进来，外壳才拿得到 `badSections`；而且单例会跨用例留着上一例的状态
  // ⇒ 每次都 `loadConfig(true)` 强制重取。
  await useSettingsConfig().loadConfig(true)
  const router = makeRouter()
  await router.push('/settings/logs')
  await router.isReady()
  const wrapper = mount(SettingsLayout, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper.text()
}

describe('设置页的「段被写坏」红条', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('有坏段时出红条并点名是哪些段', async () => {
    const text = await mountLayout({ _bad_sections: ['watcher', 'logging'] })
    expect(text).toContain('配置里有段被写坏了')
    expect(text).toContain('watcher')
    expect(text).toContain('logging')
  })

  it('好配置时不出红条', async () => {
    const text = await mountLayout({ _bad_sections: [] })
    expect(text).not.toContain('配置里有段被写坏了')
  })

  it('后端没给这个字段时也不出红条（向后兼容的读法）', async () => {
    const text = await mountLayout({})
    expect(text).not.toContain('配置里有段被写坏了')
  })
})
