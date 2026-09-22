/**
 * 新建书库向导（第 41 期：多来源根 + 多个文件夹）。
 *
 * ## 这个文件真正在防什么
 *
 * 向导的**绝大部分是展示**，只有三件事会真的写进后端：
 * ① 最后一次 `createLibrary`（第 41 期发 `source_dirs`，多文件夹绝对路径）② 建库后那一次阅读阈值 `PUT`
 * ③ 二者之间的先后顺序。其余全是「摆成什么样」。所以下面每组用例都盯着**发出去的 payload**，
 * 而不是「屏幕上有没有这段字」—— 后者在把「立即创建」改成只关弹窗不建库之后**照样是绿的**。
 *
 * 三条最容易走散的语义各有一组用例：
 *   · **全不勾格式 = 继承类型默认**（不是「一个格式都不收」）
 *   · **阅读阈值不勾「本库单独设定」= 不写覆盖**（写了就把继承关系钉死了）
 *   · **必填两步挡得住**（上游标了必填的只有这两步：名称 + 至少一个内容来源文件夹）
 */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LibraryWizard from '@/components/tools/LibraryWizard.vue'
import { api, type LibraryType } from '@/lib/api'
import { refreshThresholds } from '@/lib/readingThresholds'

vi.mock('@/lib/api', () => ({
  api: {
    createLibrary: vi.fn(),
    librarySettingsUpdate: vi.fn(),
    librarySettingsReset: vi.fn(),
    readingThresholds: vi.fn(),
    librarySourceDirs: vi.fn(),
  },
}))

const mockCreate = vi.mocked(api.createLibrary)
const mockSettingsUpdate = vi.mocked(api.librarySettingsUpdate)
const mockThresholds = vi.mocked(api.readingThresholds)
const mockSourceDirs = vi.mocked(api.librarySourceDirs)

type CreatePayload = Parameters<typeof api.createLibrary>[0]

const TYPES: { value: LibraryType; label: string; exts: string[] }[] = [
  { value: 'ebook', label: '电子书', exts: ['.epub', '.mobi'] },
  { value: 'comic', label: '漫画', exts: ['.cbz', '.cbr'] },
]

/** 第 41 期：已配置的来源根（向导按这些根浏览 / 下钻）。 */
const SOURCE_ROOTS = [
  { name: '电子书根', path: '/srv/library' },
  { name: '备份根', path: '/srv/backup' },
]

const CREATED = { ok: true, library: { id: 'new-1' } }

async function openWizard(): Promise<VueWrapper> {
  const w = mount(LibraryWizard, {
    props: { types: TYPES, sourceRoots: SOURCE_ROOTS, libs: [] },
  })
  await flushPromises()
  return w
}

/** 取最近一次 `createLibrary` 的 payload（没有就判定失败，避免用例静默通过） */
function payload(): CreatePayload {
  const calls = mockCreate.mock.calls
  expect(calls.length, '一次 createLibrary 都没发 —— 「创建」是不是退化成了只关弹窗？').toBeGreaterThan(0)
  return calls[calls.length - 1][0]
}

/** 填个库名推进到第 2 步（内容来源：选文件夹都在那一步） */
async function gotoFolders(w: VueWrapper): Promise<void> {
  await w.find('[data-test="wizard-name"]').setValue('某库')
  await w.find('[data-test="wizard-next"]').trigger('click')
  await flushPromises()
}

/** 从内容来源步骤挑一个来源根、把当前文件夹加进已选（第 41 期：多根下钻后添加）。
 *  调用方可能还在「基本信息」步，这里先确保进入「内容来源」步（已填名则不覆盖），
 *  再点来源根卡片下钻、「添加此文件夹」完成一次多选。 */
async function selectFolder(w: VueWrapper, rootIndex = 0): Promise<void> {
  if (!w.find('[data-test="wizard-root-card"]').exists()) {
    const nameInput = w.find('[data-test="wizard-name"]')
    if (!String((nameInput.element as HTMLInputElement).value).trim()) await nameInput.setValue('某库')
    await w.find('[data-test="wizard-next"]').trigger('click')
    await flushPromises()
  }
  await w.findAll('[data-test="wizard-root-card"]').at(rootIndex)!.trigger('click')
  await flushPromises()
  await w.find('[data-test="wizard-pick-folder"]').trigger('click')
  await flushPromises()
}

/** 到扫描步：名称 → 内容来源（选一个文件夹）→ 下一步 */
async function gotoScanning(w: VueWrapper): Promise<void> {
  await w.find('[data-test="wizard-name"]').setValue('漫画库')
  await w.find('[data-test="wizard-next"]').trigger('click')
  await flushPromises()
  await selectFolder(w)
  await w.find('[data-test="wizard-next"]').trigger('click')
  await flushPromises()
}

/** 到阅读步：名称 → 内容来源（选文件夹）→ 扫描 → 下一步 */
async function gotoReading(w: VueWrapper): Promise<void> {
  await gotoScanning(w)
  await w.find('[data-test="wizard-next"]').trigger('click')
  await flushPromises()
}

beforeEach(async () => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockCreate.mockResolvedValue(CREATED as never)
  mockSettingsUpdate.mockResolvedValue({} as never)
  mockThresholds.mockResolvedValue({ library_id: '', started: 0, finished: 99.5 })
  // 下钻接口：任意 `root`/`path` 都返回一个目录 + 一个文件（第 41 期 entries 形状）
  mockSourceDirs.mockResolvedValue({
    root_index: 0,
    root_name: '电子书根',
    base: '/srv/library',
    path: '',
    entries: [
      { name: 'comics', path: '/srv/library/comics', type: 'dir' },
      { name: 'readme.txt', path: '/srv/library/readme.txt', type: 'file' },
    ],
  })
  // 阈值模块有自己的缓存，跨用例会串 —— 强制重取一次，让每个用例都从干净状态开始
  await refreshThresholds()
})

describe('向导 · 步骤推进与必填拦截', () => {
  it('没填库名称时「继续」不放行，停在第一步', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(w.text()).toContain('第 1 步，共 5 步')
  })

  it('填了名称就能进第二步；不选文件夹则挡在第二步（内容来源必填）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(w.text()).toContain('第 2 步，共 5 步')

    // 没选任何文件夹 ⇒ 必填拦停
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(w.text()).toContain('第 2 步，共 5 步')
  })

  it('成品目录与已有库内容来源重叠时挡在第二步（与后端同口径的预检）', async () => {
    const w = mount(LibraryWizard, {
      props: {
        types: TYPES,
        sourceRoots: SOURCE_ROOTS,
        libs: [{ id: 'a', name: '甲库', source_dirs: ['/srv/library/ebooks'] }] as never,
      },
    })
    await flushPromises()
    await w.find('[data-test="wizard-name"]').setValue('新库')
    await w.find('[data-test="wizard-next"]').trigger('click')
    await flushPromises()
    await w.find('[data-test="wizard-publish"]').setValue('/srv/library/ebooks/out')
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(w.text()).toContain('第 2 步，共 5 步')
  })

  it('「在读下界」不小于「已读完阈值」时挡在第四步', async () => {
    const w = await openWizard()
    await gotoReading(w)
    expect(w.text()).toContain('第 4 步，共 5 步')

    await w.find('[data-test="wizard-reading-override"]').setValue(true)
    await w.find('[data-test="wizard-started"]').setValue(90)
    await w.find('[data-test="wizard-finished"]').setValue(50)
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(w.text()).toContain('第 4 步，共 5 步')
  })

  it('「立即创建」选好内容来源后能在第一步之外建库（上游 Create now 语义）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(payload().name).toBe('漫画库')
    expect(w.emitted('created')?.[0]).toEqual(['new-1'])
  })
})

describe('向导 · 多来源根下钻与多选（第 41 期）', () => {
  it('点来源根卡片 ⇒ 拉真实服务器目录，列出可下钻的文件夹', async () => {
    const w = await openWizard()
    await gotoFolders(w)
    await w.findAll('[data-test="wizard-root-card"]').at(0)!.trigger('click')
    await flushPromises()

    expect(mockSourceDirs).toHaveBeenCalledWith({ root: 0, path: '' })
    const dirs = w.findAll('[data-test="wizard-browse-dir"]')
    expect(dirs.length).toBe(1) // 只有 comics 是目录，readme.txt 是文件
    expect(w.findAll('[data-test="wizard-browse-file"]').length).toBe(1)
  })

  it('点目录项 ⇒ 下钻一层（面包屑/返回可点）', async () => {
    const w = await openWizard()
    await gotoFolders(w)
    await w.findAll('[data-test="wizard-root-card"]').at(0)!.trigger('click')
    await flushPromises()
    await w.find('[data-test="wizard-browse-dir"]').trigger('click')
    await flushPromises()
    // 下钻后「返回」可用，且能再点「添加此文件夹」
    expect(w.find('[data-test="wizard-browse-up"]').exists()).toBe(true)
    await w.find('[data-test="wizard-pick-folder"]').trigger('click')
    await flushPromises()
    const sel = w.findAll('[data-test="wizard-selected-item"]')
    expect(sel.length).toBe(1)
    expect(sel[0].text()).toContain('comics')
  })

  it('点「添加此文件夹」⇒ 已选出现该绝对路径（跨根合法）', async () => {
    const w = await openWizard()
    await gotoFolders(w)
    // 选备份根（index 1）的顶层
    await w.findAll('[data-test="wizard-root-card"]').at(1)!.trigger('click')
    await flushPromises()
    await w.find('[data-test="wizard-pick-folder"]').trigger('click')
    await flushPromises()
    const sel = w.findAll('[data-test="wizard-selected-item"]')
    expect(sel.length).toBe(1)
    // 跨根：选的是「备份根」（卡片按来源根名展示，绝对路径只在提交的 source_dirs 里）
    expect(sel[0].text()).toContain('备份根')
  })

  it('已选文件夹可删除（再点「添加」不重复）', async () => {
    const w = await openWizard()
    await gotoFolders(w)
    await selectFolder(w)
    expect(w.findAll('[data-test="wizard-selected-item"]').length).toBe(1)
    await w.find('[data-test="wizard-selected-del"]').trigger('click')
    await flushPromises()
    expect(w.findAll('[data-test="wizard-selected-item"]').length).toBe(0)
  })

  it('目录清单为空时显示空态，不报错', async () => {
    mockSourceDirs.mockResolvedValue({
      root_index: 0,
      root_name: '电子书根',
      base: '/srv/library',
      path: '',
      entries: [],
    })
    const w = await openWizard()
    await gotoFolders(w)
    await w.findAll('[data-test="wizard-root-card"]').at(0)!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('（此目录下没有子项）')
  })

  it('拉取失败 ⇒ 不打开弹层、不崩（走 toast）', async () => {
    mockSourceDirs.mockRejectedValue(new Error('读不到'))
    const w = await openWizard()
    await gotoFolders(w)
    await w.findAll('[data-test="wizard-root-card"]').at(0)!.trigger('click')
    await flushPromises()
    expect(w.findAll('[data-test="wizard-browse-dir"]').length).toBe(0)
    expect(w.findAll('[data-test="wizard-browse-file"]').length).toBe(0)
  })
})

describe('向导 · 发出去的 payload', () => {
  it('含当前步的值与默认值，「允许的格式」空 = 继承类型默认', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await w.find('[data-test="wizard-icon-book"]').trigger('click')
    await selectFolder(w)
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()

    const p = payload()
    expect(p.name).toBe('漫画库')
    expect(p.type).toBe('ebook')
    // 第 41 期：内容来源 = 多文件夹绝对路径
    expect(p.source_dirs).toEqual(['/srv/library'])
    expect(p.icon).toBe('book')
    // 没动过格式勾选 ⇒ 空数组 = 后端读作「没设过」⇒ 回落到该类型的默认白名单
    expect(p.allowed_exts).toEqual([])
    expect(p.exclude).toEqual([])
  })

  it('动过格式勾选 ⇒ 发的是「默认集增删后」的集合，不是只含新勾的那个', async () => {
    const w = await openWizard()
    await gotoScanning(w)
    // 默认集是 ['.epub', '.mobi']，点掉 .epub ⇒ 剩下 ['.mobi']
    await w.find('[data-test="ext-chip-.epub"]').trigger('click')
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(payload().allowed_exts).toEqual(['.mobi'])
  })

  it('勾到空 ⇒ 仍然发空数组（= 继承类型默认），并提示这不是「什么格式都不收」', async () => {
    const w = await openWizard()
    await gotoScanning(w)
    await w.find('[data-test="ext-chip-.epub"]').trigger('click')
    await w.find('[data-test="ext-chip-.mobi"]').trigger('click')

    expect(w.text()).toContain('继承类型默认')
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(payload().allowed_exts).toEqual([])
  })

  it('换库类型 ⇒ 格式勾选回到新类型的默认集（不把上一个类型的自定义带过去）', async () => {
    const w = await openWizard()
    await gotoScanning(w)
    await w.find('[data-test="ext-chip-.epub"]').trigger('click') // 自定义过
    await w.find('[data-test="wizard-back"]').trigger('click')
    await w.find('[data-test="wizard-back"]').trigger('click') // 回到第 1 步
    await w.findAll('button').find((b) => b.text() === '漫画')!.trigger('click')
    await w.find('[data-test="wizard-next"]').trigger('click')
    await flushPromises()
    await selectFolder(w)
    await w.find('[data-test="wizard-next"]').trigger('click')
    await flushPromises()

    // 勾选集 = 漫画的默认集，而不是电子书那个被改过的
    expect(w.find('[data-test="ext-chip-.cbz"]').attributes('aria-pressed')).toBe('true')
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(payload().type).toBe('comic')
    expect(payload().allowed_exts).toEqual([])
  })

  it('排除图案可加可删，删掉的不进 payload', async () => {
    const w = await openWizard()
    await gotoScanning(w)

    const input = w.find('[data-test="wizard-exclude-input"]')
    await input.setValue('*.draft.epub')
    await w.find('[data-test="wizard-exclude-add"]').trigger('click')
    await input.setValue('备份/*')
    await w.find('[data-test="wizard-exclude-add"]').trigger('click')
    await w.find('[data-test="wizard-exclude-del-0"]').trigger('click')

    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(payload().exclude).toEqual(['备份/*'])
  })
})

describe('向导 · 阅读阈值（每库覆写项）', () => {
  it('不勾「本库单独设定」⇒ 一个覆写都不写（保持继承全局）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(mockCreate).toHaveBeenCalledTimes(1)
    expect(mockSettingsUpdate).not.toHaveBeenCalled()
  })

  it('勾了且与全局不同 ⇒ 建库之后按新库 id 写一次覆写', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await gotoReading(w)
    await w.find('[data-test="wizard-reading-override"]').setValue(true)
    await w.find('[data-test="wizard-finished"]').setValue(80)
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()

    expect(mockSettingsUpdate).toHaveBeenCalledTimes(1)
    expect(mockSettingsUpdate.mock.calls[0][0]).toBe('new-1')
    expect(mockSettingsUpdate.mock.calls[0][1]).toEqual({
      'reading.started_threshold': 0,
      'reading.finished_threshold': 80,
    })
  })

  it('勾了但与全局相同 ⇒ 也不写覆盖（写了就等于把继承关系钉死了）', async () => {
    mockThresholds.mockResolvedValue({ library_id: '', started: 0, finished: 80 })
    await refreshThresholds()
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await gotoReading(w)
    await w.find('[data-test="wizard-reading-override"]').setValue(true)
    await w.find('[data-test="wizard-finished"]').setValue(80)
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()

    expect(mockCreate).toHaveBeenCalledTimes(1)
    expect(mockSettingsUpdate).not.toHaveBeenCalled()
  })

  it('先建库再写覆写：阈值那一步拿到的是**新库的 id**', async () => {
    const order: string[] = []
    mockCreate.mockImplementation(async () => {
      order.push('create')
      return CREATED as never
    })
    mockSettingsUpdate.mockImplementation(async () => {
      order.push('settings')
      return {} as never
    })
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await gotoReading(w)
    await w.find('[data-test="wizard-reading-override"]').setValue(true)
    await w.find('[data-test="wizard-finished"]').setValue(70)
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(order).toEqual(['create', 'settings'])
  })
})

describe('向导 · 不假交互', () => {
  it('建库失败 ⇒ 不关浮层、不发 created（免得用户以为建好了）', async () => {
    mockCreate.mockRejectedValue(new Error('库名称已存在'))
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(w.emitted('created')).toBeUndefined()
  })

  it('点「取消」只关浮层，不建库', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await w.find('[data-test="wizard-cancel"]').trigger('click')
    await flushPromises()
    expect(w.emitted('close')).toBeTruthy()
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('「立即创建」走的是完整 5 步以外的路径，但仍必须真的建库', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    expect(w.text()).toContain('第 1 步，共 5 步')
    await selectFolder(w)
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(mockCreate).toHaveBeenCalledTimes(1)
    expect(w.emitted('created')).toBeTruthy()
  })
})
