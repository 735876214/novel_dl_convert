import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import type { AppConfig, MaintenanceInfo, OrphansInfo, RecycleListPayload } from '@/lib/api'
import { api } from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import MaintenancePage from '@/views/settings/pages/MaintenancePage.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * 维护页 UPDATES 分组的对照归置（第 84 期）。
 *
 * 背景：上游 Maintenance 页 `UPDATES` 分组的 «Check for updates»（启动时查 GitHub 新版本、
 * 有更新时侧栏提示）本项目**第 78 期就实现了**，还多做了检查间隔 / 拉取镜像 / 一键更新 /
 * 自动更新。但仓内对照三处（`settingsNav.ts` / 两份 bookorbit 文档）却把它记成
 * 「⬜ 未实现，页内只读列出」—— 这是**对照走样**。
 *
 * 本 spec 钉死纠正后的两个不变量：
 *  1. UPDATES 以「已实现 + 跳转」的说明卡出现，且真的链到 `ext/update` 页；
 *  2. UPDATES / «Check for updates» **不再**出现在「上游还有、本项目未支持」只读卡里
 *     （两处同时漏改 = 又一个新的对照走样）。
 *
 * 另钉住「过滤不过度」：IMPORT / RECOMMENDATIONS 仍应留在未支持卡里。
 */
vi.mock('@/lib/api', () => ({
  api: {
    getConfig: vi.fn(),
    saveConfig: vi.fn(),
    maintenance: vi.fn(),
    orphans: vi.fn(),
    recycleList: vi.fn(),
    // 页面上有按钮但用例不点（照实列出，免得真发请求）
    rebuildLibrary: vi.fn(),
    clearCache: vi.fn(),
    clearRecycle: vi.fn(),
    backfillAchievements: vi.fn(),
    clearOrphans: vi.fn(),
    recycleRestore: vi.fn(),
  },
}))

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      // 页面上两个 RouterLink 的落点：缺席时 vue-router 会往 stderr 泼「No match found」。
      { path: '/tools/duplicates', component: { template: '<div />' } },
      { path: '/settings/ext/update', component: { template: '<div />' } },
    ],
  })
}

const mounted: VueWrapper[] = []

async function mountPage(): Promise<VueWrapper> {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const w = mount(MaintenancePage, { global: { plugins: [router] } })
  mounted.push(w)
  await flushPromises()
  return w
}

const DIR = { path: '/x', files: 0, bytes: 0 }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.getConfig).mockResolvedValue({
    config: { upload: { max_bytes: 10485760, max_source_rules_bytes: 5242880 } } as unknown as AppConfig,
    overrides: {},
    overridden: [],
    config_file: '',
    settings_file: '',
    backup_dir: '',
  })
  vi.mocked(api.maintenance).mockResolvedValue({
    upload: { max_bytes: 10485760, max_source_rules_bytes: 5242880 },
    overridden: [],
    dirs: { input: DIR, output: DIR, cache: DIR, backups: DIR, recycle: DIR },
    library: { books: 3 },
  } as MaintenanceInfo)
  vi.mocked(api.orphans).mockResolvedValue({ tables: {}, total: 0, library_books: 0 } as OrphansInfo)
  vi.mocked(api.recycleList).mockResolvedValue({
    dir: '/x/recycle',
    items: [],
    total: 0,
    orphans: [],
    orphan_total: 0,
  } as RecycleListPayload)
})

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('MaintenancePage UPDATES 对照归置（第 84 期）', () => {
  it('渲染「版本检查与更新」说明卡', async () => {
    const w = await mountPage()
    expect(w.text()).toContain('版本检查与更新')
    expect(w.text()).toContain('Check for updates')
  })

  it('说明卡链到 ext/update 页（而不是放重复开关）', async () => {
    const w = await mountPage()
    const link = w.find('a[href="/settings/ext/update"]')
    expect(link.exists(), '维护页的 UPDATES 说明卡没有指向更新页的链接').toBe(true)
    expect(w.text()).toContain('前往 Updates 页')
  })

  it('UPDATES 不再被列为「未支持」', async () => {
    const w = await mountPage()
    const card = w.findComponent(SettingsUnsupportedCard)
    expect(card.exists()).toBe(true)
    expect(card.props('groups')).not.toContain('UPDATES')
    expect(card.props('items')).not.toContain('Check for updates（查 GitHub 新版本）')
  })

  it('过滤不过度：IMPORT / RECOMMENDATIONS 仍留在未支持卡里', async () => {
    const w = await mountPage()
    const card = w.findComponent(SettingsUnsupportedCard)
    expect(card.props('groups')).toContain('IMPORT')
    expect(card.props('groups')).toContain('RECOMMENDATIONS')
    expect(card.props('items')).toContain('Refresh recommendation index')
  })
})

// ---------------------------------------------------------------------------
// 第 256 期：**删不掉的必须说出来**（后端给了 `failed`，前端**必须读**）
// ---------------------------------------------------------------------------

describe('清理动作要如实回报（第 256 期）', () => {
  /**
   * 点某个「清理」按钮之后，toast 里说了什么。
   *
   * ⚠️ **按点击处理函数定位**，不按按钮文字 —— 「清空缓存」那一条的**标题**
   * 是个独立的 `<div>`（按钮上只写「清空」），按文字找会撞错按钮。
   */
  async function toastAfter(handler: 'clearCache' | 'clearRecycle'): Promise<string> {
    const w = await mountPage()
    // 直接调组件暴露的处理函数（按钮的点击最终落到它）
    const vm = w.vm as unknown as Record<string, () => void>
    vm[handler]()
    await flushPromises()
    await flushPromises()
    return useUiStore().toastMessage
  }

  it('清缓存有没删掉的要说出来（不能只说「已清理 N 项」）', async () => {
    vi.mocked(api.clearCache).mockResolvedValue({
      ok: false, removed: 1, failed: ['删不掉.txt: Permission denied'], preserved: 'C:/recycle',
    })
    const msg = await toastAfter('clearCache')
    expect(msg).toContain('没删掉')
    expect(msg).toContain('删不掉.txt')
  })

  it('清回收站有没删掉的也要说出来', async () => {
    // 清空回收站是**真删** ⇒ 页面上有二次确认
    // ⚠️ happy-dom 里**没有** `window.confirm`（`vi.spyOn` 会报
    // 「can only spy on a function」）⇒ 直接**定义**一个。
    ;(window as unknown as { confirm: () => boolean }).confirm = () => true
    vi.mocked(api.clearRecycle).mockResolvedValue({
      ok: false, removed: 2, freed: 100, ledger_cleared: 0, failed: ['busy.epub: Permission denied'],
    })
    const msg = await toastAfter('clearRecycle')
    expect(msg).toContain('没删掉')
    expect(msg).toContain('busy.epub')
  })

  it('全删得掉时说的是「已清理」（不吓唬用户）', async () => {
    vi.mocked(api.clearCache).mockResolvedValue({
      ok: true, removed: 3, failed: [], preserved: 'C:/recycle',
    })
    const msg = await toastAfter('clearCache')
    expect(msg).toContain('已清理')
    expect(msg).not.toContain('没删掉')
  })
})
