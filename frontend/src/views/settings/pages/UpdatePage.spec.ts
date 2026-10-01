import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import type { AppConfig, UpdateStatus } from '@/lib/api'
import { api } from '@/lib/api'
import UpdatePage from '@/views/settings/pages/UpdatePage.vue'

/**
 * 更新页「自动更新状态卡」的哨兵（第 84 期）。
 *
 * 为什么必须有这一份：默认**不挂** docker.sock ⇒ NAS 上「发现新版自动更新」这个开关
 * 默认**根本不生效**，而页面上此前只有一个孤零零的开关 —— 用户会以为开了就会自动升级，
 * 结果一直停在旧版，只能对着「有新版本」的标记猜。第 84 期改「先记已尝试再执行」为
 * 「退避重试」（失败不再永久放弃）后，失败原因与下次重试时间必须如实显示，否则用户
 * 依然不知道「为什么没升上去、还会不会再试」。
 *
 * 本 spec 钉死三件事（都是**静默走样**）：
 *  1. 可用 / 不可用的判据 = 开关开 **且** socket 挂着，两者缺一不可；
 *  2. 未挂载时如实说「当前未挂载」并给出开启步骤（不做假交互）；
 *  3. 失败时显示原因 + 下次重试时间（不是只甩一个「有更新」）。
 */
vi.mock('@/lib/api', () => ({
  api: {
    getConfig: vi.fn(),
    saveConfig: vi.fn(),
    updateStatus: vi.fn(),
    // 页面上有按钮但用例不点（照实列出，免得真发请求）
    updateCheck: vi.fn(),
    updateApply: vi.fn(),
  },
}))

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      // 页面上有这个 RouterLink；缺席时 vue-router 会往 stderr 泼「No match found」，
      // 把真正的失败信息淹掉。
      { path: '/whats-new', component: { template: '<div />' } },
    ],
  })
}

const mounted: VueWrapper[] = []

async function mountPage(): Promise<VueWrapper> {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const w = mount(UpdatePage, { global: { plugins: [router] } })
  mounted.push(w)
  await flushPromises()
  return w
}

/** 造一份**字段齐全**的 update.status（不写 `as UpdateStatus` 强转 —— 接口加字段要能报出来）。 */
function status(over: Partial<UpdateStatus> = {}): UpdateStatus {
  return {
    current: '0.83.0',
    latest: '0.84.0',
    has_update: true,
    checked_at: 1_700_000_000,
    url: 'https://x/rel',
    updater_available: false,
    error: '',
    check_enabled: true,
    auto_apply: false,
    auto_failures: 0,
    auto_retry_at: 0,
    last_auto_result: '',
    auto_message: '',
    ...over,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.getConfig).mockResolvedValue({
    config: {
      update: {
        check_enabled: true,
        interval_hours: 6,
        auto_apply: false,
        image: '',
      },
    } as unknown as AppConfig,
    overrides: {},
    overridden: [],
    config_file: '',
    settings_file: 'settings.json',
    backup_dir: '',
  })
  vi.mocked(api.updateStatus).mockResolvedValue(status())
})

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('UpdatePage 自动更新状态卡（第 84 期）', () => {
  it('开关开且挂了 socket ⇒ 显示「可用」', async () => {
    vi.mocked(api.updateStatus).mockResolvedValue(
      status({ auto_apply: true, updater_available: true }),
    )
    const w = await mountPage()
    expect(w.text()).toContain('可用')
    expect(w.text()).toContain('自动更新已开启')
    expect(w.text()).not.toContain('不可用')
  })

  it('没挂 socket ⇒ 显示「不可用」并如实说「当前未挂载」+ 开启步骤', async () => {
    vi.mocked(api.updateStatus).mockResolvedValue(
      status({ auto_apply: true, updater_available: false }),
    )
    const w = await mountPage()
    expect(w.text()).toContain('不可用')
    // 这是本 spec 的核心：默认不挂 socket 时，页面上必须说清「开关不生效」以及怎么才能用
    expect(w.text()).toContain('当前未挂载，下方「自动更新」开关不会生效')
    expect(w.text()).toContain('docker-compose.yml')
    expect(w.text()).toContain('取消注释')
  })

  it('开关关时说明「自动更新开关当前是关的」', async () => {
    vi.mocked(api.updateStatus).mockResolvedValue(
      status({ auto_apply: false, updater_available: true }),
    )
    const w = await mountPage()
    expect(w.text()).toContain('自动更新开关当前是关的')
  })

  it('失败时显示原因 + 下次重试时间（不是只甩「有更新」）', async () => {
    vi.mocked(api.updateStatus).mockResolvedValue(
      status({
        auto_apply: true,
        updater_available: true,
        auto_failures: 2,
        last_auto_result: 'pull_failed',
        auto_message: '镜像拉取失败（HTTP 500）',
        auto_retry_at: 1_700_003_600,
      }),
    )
    const w = await mountPage()
    expect(w.text()).toContain('自动更新失败')
    expect(w.text()).toContain('（已连续 2 次）')
    expect(w.text()).toContain('镜像拉取失败（HTTP 500）')
    // 失败不再永久放弃 ⇒ 必须给出下次重试时间
    expect(w.text()).toContain('自动重试')
  })

  it('成功过的不算失败（退避计数清零后不再显示红色失败块）', async () => {
    vi.mocked(api.updateStatus).mockResolvedValue(
      status({ auto_apply: true, updater_available: true, auto_failures: 0, last_auto_result: 'restarting' }),
    )
    const w = await mountPage()
    expect(w.text()).not.toContain('自动更新失败')
    expect(w.text()).toContain('自动更新已开启')
  })

  it('更新前自动备份的口径在页面上写清（失败即中止）', async () => {
    const w = await mountPage()
    expect(w.text()).toContain('自动备份业务数据')
    expect(w.text()).toContain('备份失败即中止本次更新')
  })
})
