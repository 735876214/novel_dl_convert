import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import type { AppConfig, BookDockItem, BookDockResponse, LibraryEntity } from '@/lib/api'
import { api } from '@/lib/api'
import BookDockPage from '@/views/settings/pages/BookDockPage.vue'

/**
 * 收书目录页的哨兵（第 65 期 3/5 起的死链，5/5 起加条目行的两个交互）。
 *
 * 本页此前**零 spec**，而它当时其实是坏的：同一条 `v-if` 链里两个分支的
 * 条件逐字相同（批量操作条与条目行都是 `dock && dock.items.length`），
 * 于是条目行**永不渲染** —— 页面上只看得见批量条和两个点不动的按钮。
 * 这个失效方式不会报错、不会告警，看起来就像「投递目录里还没有文件」。
 *
 * 所以核心断言是条目行的**数量**：mock 两条就得数出两条。
 *
 * 5/5 加的两组断言针对「重命名」与「入库到…」。它们共同的失效方式是
 * **静默做错事**：改名多发一次请求（或按 Enter 却什么都没发生）、
 * 「入库到…」把文件放进默认库而不是用户选的库 —— 两者都不报错。
 */
vi.mock('@/lib/api', () => ({
  api: {
    bookDock: vi.fn(),
    health: vi.fn(),
    watcherStatus: vi.fn(),
    bookDockRescan: vi.fn(),
    bookDockRename: vi.fn(),
    bookDockIgnore: vi.fn(),
    bookDockDelete: vi.fn(),
    // 页面上有按钮但用例不点（照实列出，免得真发请求）
    watcherStart: vi.fn(),
    watcherStop: vi.fn(),
    scanNow: vi.fn(),
    convertDrop: vi.fn(),
    getConfig: vi.fn(),
    libraries: vi.fn(),
    books: vi.fn(),
    collections: vi.fn(),
    smartScopes: vi.fn(),
    features: vi.fn(),
    readingThresholds: vi.fn().mockResolvedValue({ started: 1, finished: 99 }),
  },
  apiErrorMessage: (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback),
}))

function item(over: Partial<BookDockItem>): BookDockItem {
  // 用 `Object.assign` 而不是对象展开：展开 `Partial<T>` 会把每个键变成
  // `T | undefined`，`ext: string` 这种必填字段就赋不过去了（vue-tsc 会红）。
  const base: BookDockItem = {
    id: 'i1',
    name: '三体.epub',
    ext: 'epub',
    size: 1024,
    status: 'needs_review',
    output: '',
    detail: '',
    retries: 0,
    created_at: 0,
    updated_at: 0,
  }
  return Object.assign(base, over)
}

const A = item({ id: 'i-a', name: '三体.epub', ext: 'epub', status: 'needs_review' })
const B = item({ id: 'i-b', name: '球状闪电.txt', ext: 'txt', status: 'pending' })
/** 已入库的行：按口径它**不该**有「重命名 / 入库到…」两个动作。 */
const R = item({ id: 'i-r', name: '三体·全集.epub', ext: 'epub', status: 'ready', output: '三体·全集.epub' })

/**
 * 造一个**字段齐全**的 `LibraryEntity`（照 `stores/library.spec.ts` 的先例：
 * 不写 `as LibraryEntity` 强转 —— store 的接口加了新字段要能在这里报出来）。
 */
function makeLibrary(over: Partial<LibraryEntity> = {}): LibraryEntity {
  return {
    id: 'lib1',
    name: '主库',
    type: 'ebook',
    type_label: '电子书',
    source_dirs: ['/srv/library/main'],
    rules: '',
    sort_order: 0,
    publish_path: '',
    publish_exists: false,
    publish_writable: false,
    watch: 0,
    scan_interval: 0,
    scan_cron: '',
    icon: '',
    allowed_exts: [],
    exts_effective: ['.epub'],
    exclude: [],
    book_count: 0,
    exists: true,
    writable: true,
    last_scan_at: 0,
    last_scan_note: '',
    ...over,
  }
}

/** 收得了 .epub，且**两个**文件夹（用来钉「默认第一个、可以自己换」）。 */
const LIB_EBOOK = makeLibrary({
  id: 'lib-e',
  name: '电子书库',
  source_dirs: ['/srv/ebook-a', '/srv/ebook-b'],
  exts_effective: ['.epub', '.txt'],
})
/** 收不了 .epub 的库（照列 + 写明原因，而不是从列表里抹掉）。 */
const LIB_COMIC = makeLibrary({
  id: 'lib-c',
  name: '漫画库',
  type: 'comic',
  type_label: '漫画',
  source_dirs: ['/srv/comic'],
  exts_effective: ['.cbz'],
})

function libsResult(items: LibraryEntity[]) {
  return { items, total: items.length, types: [], source_roots: [] }
}

function dockResponse(items: BookDockItem[]): BookDockResponse {
  const review = items.filter((i) => i.status === 'needs_review').length
  return {
    items,
    counts: { all: items.length, needs_review: review },
    tabs: [
      { key: 'all', label: '全部', count: items.length },
      { key: 'needs_review', label: '待复核', count: review },
    ],
    statuses: [],
  }
}

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      // 名字要对上（弹窗里用 `{ name: 'settings-libraries' }` 跳转）：只写 path
      // 的话解析不到名字，vue-router 会往 stderr 泼「No match found」。
      { path: '/settings/libraries', name: 'settings-libraries', component: { template: '<div />' } },
      { path: '/settings', component: { template: '<div />' } },
      // 页面上这几个 `RouterLink` 的落点：缺席时 vue-router 会往 stderr 泼四条
      // 「No match found」，把真正的失败信息淹掉。
      { path: '/settings/ext/watcher', component: { template: '<div />' } },
      { path: '/settings/metadata/auto-fetch', component: { template: '<div />' } },
      { path: '/tools/local', component: { template: '<div />' } },
    ],
  })
}

const mounted: VueWrapper[] = []

async function mountPage(): Promise<VueWrapper> {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const w = mount(BookDockPage, { global: { plugins: [router] } })
  mounted.push(w)
  await flushPromises()
  return w
}

function rows(w: VueWrapper) {
  return w.findAll('[data-dock-row]')
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.bookDock).mockResolvedValue(dockResponse([A, B]))
  vi.mocked(api.health).mockResolvedValue({ input: 'D:/input' } as never)
  vi.mocked(api.watcherStatus).mockResolvedValue({ running: false } as never)
  vi.mocked(api.getConfig).mockResolvedValue({
    config: { watcher: { enabled: false } } as unknown as AppConfig,
    overrides: {},
    overridden: [],
    config_file: '',
    settings_file: '',
    backup_dir: '',
  })
  // 默认给两个库（第一个**收不了** .epub）—— 「默认选第一个收得了的」这条规则
  // 只有在顺序不是「收得了的排第一」时才测得出来。
  vi.mocked(api.libraries).mockResolvedValue(libsResult([LIB_COMIC, LIB_EBOOK]))
  vi.mocked(api.bookDockRename).mockResolvedValue({ ok: true, item: A })
  vi.mocked(api.books).mockResolvedValue({ items: [], total: 0 })
  vi.mocked(api.collections).mockResolvedValue({ items: [] })
  vi.mocked(api.smartScopes).mockResolvedValue({ items: [] })
  vi.mocked(api.features).mockResolvedValue({
    library_id: '',
    library_type: '',
    features: [],
    matrix: { types: {}, all: [], labels: {} },
  })
})

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('BookDockPage（第 65 期 3/5）', () => {
  it('条目行按 mock 的条数渲染（不是 0 条）', async () => {
    // 死链的哨兵：`v-else-if` 撞车时这里数到 0，而页面上看不出任何异常
    const w = await mountPage()
    expect(rows(w), '条目行没渲染 —— 同一条 v-if 链里两个分支的条件又撞上了').toHaveLength(2)
    expect(w.text()).toContain('三体.epub')
    expect(w.text()).toContain('球状闪电.txt')
  })

  it('批量条与条目行同时在场（不是二选一）', async () => {
    // 合并进同一个 `<template v-else-if>` 之后，两者必须**都在**：
    // 只留一处就会退回「有批量条没条目行」（复选框长在条目行里，
    // 批量按钮于是永远禁用）或反过来。
    const w = await mountPage()
    expect(w.text()).toContain('全选本页')
    expect(rows(w)).toHaveLength(2)

    const boxes = w.findAll('[data-dock-row] input[type="checkbox"]')
    expect(boxes, '条目行里没有复选框').toHaveLength(2)
  })

  it('勾选后批量重扫逐条调用，且选择被清空', async () => {
    const w = await mountPage()
    vi.mocked(api.bookDockRescan).mockResolvedValue({ ok: true, item: A })

    await w.findAll('[data-dock-row] input[type="checkbox"]')[0]!.setValue(true)
    const btn = w.findAll('button').find((b) => b.text().includes('批量重扫'))
    expect(btn, '找不到「批量重扫」').toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    expect(vi.mocked(api.bookDockRescan)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.bookDockRescan).mock.calls[0]![0]).toBe('i-a')
    expect(w.text()).toContain('已选 0 / 2')
  })

  it('重载后把已不在列表里的 id 从选择里摘掉', async () => {
    // 改名会换 id。旧 id 若一直躺在选择集里，条目**改名后又变回来**（id 撞回原值）
    // 时会莫名被勾上 —— `pickedIds` 是按 id 过滤的，它拦不住这种「复活」。
    vi.mocked(api.bookDockRescan).mockResolvedValue({ ok: true, item: A })
    const w = await mountPage()
    await w.findAll('[data-dock-row] input[type="checkbox"]')[0]!.setValue(true)
    expect(w.text()).toContain('已选 1 / 2')

    // 单项「重扫」会走 `refresh()`（**不**清空选择，与切 tab / 批量收尾不同）
    const rescan = () => w.findAll('button').find((b) => b.text() === '重扫')!

    vi.mocked(api.bookDock).mockResolvedValue(dockResponse([B])) // i-a 不在了
    await rescan().trigger('click')
    await flushPromises()
    expect(rows(w)).toHaveLength(1)

    vi.mocked(api.bookDock).mockResolvedValue(dockResponse([A, B])) // 它又回来了
    await rescan().trigger('click')
    await flushPromises()
    expect(w.text(), '已消失的条目回来后又被勾上了（幽灵 id 没摘）').toContain('已选 0 / 2')
  })
})

/** 打开第 `i` 行的「入库到…」弹窗（前置：该行确实有这个按钮）。 */
async function openIngest(w: VueWrapper, i = 0): Promise<void> {
  await rows(w)[i]!.find('[data-dock-act="ingest"]').trigger('click')
  await flushPromises()
}

describe('BookDockPage 第 65 期 5/5：重命名 + 入库到…', () => {
  it('「重命名 / 入库到…」只给未入库的行，就绪行没有（不出现、不灰置）', async () => {
    vi.mocked(api.bookDock).mockResolvedValue(dockResponse([A, R]))
    const w = await mountPage()
    const [a, r] = rows(w)
    expect(a!.find('[data-dock-act="rename"]').exists()).toBe(true)
    expect(a!.find('[data-dock-act="ingest"]').exists()).toBe(true)
    // 就绪行：成品已经在书库里了，改投递目录里的源文件既改不到那本书、又让两者对不上
    expect(r!.find('[data-dock-act="rename"]').exists(), '就绪行不该有「重命名」').toBe(false)
    expect(r!.find('[data-dock-act="ingest"]').exists(), '就绪行不该有「入库到…」').toBe(false)
    // 既有三个动作一个都没少（本期只收窄**新增的**两个）
    expect(r!.find('[data-dock-act="rescan"]').exists()).toBe(true)
    expect(r!.find('[data-dock-act="delete"]').exists()).toBe(true)
  })

  it('行内改名：Enter 提交一次，用的就是输入框里的新名字，改完重载列表', async () => {
    const w = await mountPage()
    const row = rows(w)[0]!
    await row.find('[data-dock-act="rename"]').trigger('click')

    const input = row.find('[data-dock-rename-input]')
    expect(input.exists(), '点了「重命名」却没出现输入框').toBe(true)
    expect(
      (input.element as HTMLInputElement).value,
      '预填的应该是**含扩展名**的完整文件名（所见即所得）',
    ).toBe('三体.epub')

    await input.setValue('三体 第二版.epub')
    await input.trigger('keydown.enter')
    await flushPromises()

    expect(vi.mocked(api.bookDockRename)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.bookDockRename).mock.calls[0]).toEqual(['i-a', '三体 第二版.epub'])
    // 条目 id **就是文件名** ⇒ 成功之后 id 变了，必须重载（首次挂载 1 次 + 这里 1 次）
    expect(vi.mocked(api.bookDock), '改名后没重载列表 —— 新 id 没进列表').toHaveBeenCalledTimes(2)
  })

  it('行内改名：Esc 只退回只读态，一个请求都不发', async () => {
    const w = await mountPage()
    const row = rows(w)[0]!
    await row.find('[data-dock-act="rename"]').trigger('click')
    await row.find('[data-dock-rename-input]').setValue('改了一半.epub')
    await row.find('[data-dock-rename-input]').trigger('keydown.esc')
    await flushPromises()

    expect(vi.mocked(api.bookDockRename), 'Esc 取消了却还是发了改名请求').not.toHaveBeenCalled()
    expect(row.find('[data-dock-rename-input]').exists()).toBe(false)
    expect(row.text()).toContain('三体.epub')
  })

  it('名字没改（或只多了空白）就提交：不发请求，退回只读', async () => {
    const w = await mountPage()
    const row = rows(w)[0]!
    await row.find('[data-dock-act="rename"]').trigger('click')
    await row.find('[data-dock-rename-input]').setValue('  三体.epub  ')
    await row.find('[data-dock-rename-input]').trigger('keydown.enter')
    await flushPromises()

    expect(vi.mocked(api.bookDockRename)).not.toHaveBeenCalled()
    expect(row.find('[data-dock-rename-input]').exists()).toBe(false)
  })

  it('名字清空后提交：不发请求，但**不静默关掉**编辑框', async () => {
    // 「按了 Enter 什么都没发生」与「点了没反应」是同一种假交互：要么说清原因，
    // 要么别关编辑框 —— 两者都不做，用户会以为改名成功了。
    const w = await mountPage()
    const row = rows(w)[0]!
    await row.find('[data-dock-act="rename"]').trigger('click')
    await row.find('[data-dock-rename-input]').setValue('   ')
    await row.find('[data-dock-rename-input]').trigger('keydown.enter')
    await flushPromises()

    expect(vi.mocked(api.bookDockRename)).not.toHaveBeenCalled()
    expect(row.find('[data-dock-rename-input]').exists()).toBe(true)
  })

  it('改名失败：保持编辑态（不必把名字重敲一遍）', async () => {
    vi.mocked(api.bookDockRename).mockRejectedValue(new Error('投递目录里已经有「三体 第二版.epub」了'))
    const w = await mountPage()
    const row = rows(w)[0]!
    await row.find('[data-dock-act="rename"]').trigger('click')
    await row.find('[data-dock-rename-input]').setValue('三体 第二版.epub')
    await row.find('[data-dock-rename-input]').trigger('keydown.enter')
    await flushPromises()

    const input = row.find('[data-dock-rename-input]')
    expect(input.exists(), '失败后编辑态被关掉了 —— 用户得重新点一次「重命名」再敲一遍').toBe(true)
    expect((input.element as HTMLInputElement).value).toBe('三体 第二版.epub')
  })

  it('「入库到…」默认选第一个**收得了这个格式**的库与它的第一个文件夹', async () => {
    const w = await mountPage()
    await openIngest(w)

    // 漫画库排在前面但收不了 .epub：**照列 + 写明原因**（抹掉它，用户会以为库没建好）
    const comic = w.find('[data-dock-ingest-lib="lib-c"]')
    expect(comic.exists(), '收不了的库被抹掉了 —— 应该照列并写明原因').toBe(true)
    expect(comic.text()).toContain('不收 .epub')
    expect(comic.attributes('disabled'), '收不了的库不该能选中').toBeDefined()

    // 默认落点 = 第一个收得了的库（电子书库）的第一个文件夹，而不是列表里的第一个库
    const sel = w.find('[data-dock-ingest-root]')
    expect((sel.element as HTMLSelectElement).value).toBe('/srv/ebook-a')
    expect(w.text()).toContain('将放进：/srv/ebook-a')
  })

  it('换到该库的第二个文件夹再入库：透传的 root 就是换后的那个，成功后关弹窗', async () => {
    const w = await mountPage()
    vi.mocked(api.bookDockRescan).mockResolvedValue({ ok: true, item: A })
    await openIngest(w)

    await w.find('[data-dock-ingest-root]').setValue('/srv/ebook-b')
    await w.find('[data-dock-ingest-ok]').trigger('click')
    await flushPromises()

    expect(vi.mocked(api.bookDockRescan)).toHaveBeenCalledTimes(1)
    // ⚠️ 必须**带参数**：不带 = 落回各库自己的默认路由，用户选的库白选了（且不报错）
    expect(vi.mocked(api.bookDockRescan).mock.calls[0]).toEqual([
      'i-a',
      { library_id: 'lib-e', root: '/srv/ebook-b' },
    ])
    expect(w.find('[data-dock-ingest-root]').exists(), '入库成功后弹窗该关掉').toBe(false)
  })

  it('一个库都收不了这个格式：入库按钮禁用、点了也不发请求、原因写在选项上', async () => {
    vi.mocked(api.libraries).mockResolvedValue(libsResult([LIB_COMIC]))
    const w = await mountPage()
    await openIngest(w)

    expect(w.find('[data-dock-ingest-lib="lib-c"]').text()).toContain('不收 .epub')
    const ok = w.find('[data-dock-ingest-ok]')
    expect(ok.attributes('disabled'), '收不了还让点 = 让用户以为入库了（实际是隐形文件）').toBeDefined()
    await ok.trigger('click')
    await flushPromises()
    expect(vi.mocked(api.bookDockRescan)).not.toHaveBeenCalled()
  })

  it('渲染出来的正文里没有字面 markdown 星号', async () => {
    // 模板是 HTML 不是 markdown：注释里写 `**加粗**` 没关系，但写进**文本节点**
    // 就会原样显示成两颗星。这种错不会报错、也不会被类型检查抓到。
    const w = await mountPage()
    await openIngest(w)
    expect(w.text()).not.toContain('**')
  })

  it('取消：关弹窗，一个请求都不发', async () => {
    const w = await mountPage()
    await openIngest(w)
    const cancel = w.findAll('button').find((b) => b.text() === '取消')
    expect(cancel, '找不到「取消」').toBeTruthy()
    await cancel!.trigger('click')
    await flushPromises()

    expect(vi.mocked(api.bookDockRescan)).not.toHaveBeenCalled()
    expect(w.find('[data-dock-ingest-root]').exists()).toBe(false)
  })
})
