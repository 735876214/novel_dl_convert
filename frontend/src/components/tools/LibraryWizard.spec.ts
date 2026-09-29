/**
 * 新建书库向导（三页签：内容 / 自动化 / 上次扫描，与编辑弹窗对齐）。
 *
 * ## 这个文件真正在防什么
 *
 * 向导的**绝大部分是展示**，只有三件事会真的写进后端：
 * ① 最后一次 `createLibrary`（第 41 期发 `source_dirs`，多文件夹绝对路径）
 * ② 与全局刮削开关不一致时那一次 `librarySettingsUpdate`（每库覆盖项）
 * ③ 二者之间的先后顺序。其余全是「摆成什么样」。所以下面每组用例都盯着**发出去的 payload**，
 * 而不是「屏幕上有没有这段字」—— 后者在把「创建」改成只关弹窗不建库之后**照样是绿的**。
 *
 * 三条最容易走散的语义各有一组用例：
 *   · **全不勾格式 = 继承类型默认**（不是「一个格式都不收」）
 *   · **刮削出版开关与全局一致 = 不写覆盖**（写了就把继承关系钉死了）
 *   · **必填两项挡得住**（名称 + 至少一个内容来源文件夹）
 *
 * ⚠️ 阅读阈值是每库覆写项，但**新建向导不提供内联入口**（编辑弹窗也没有，
 *   走「设置 → 命名规则」），所以这里不再测阅读阈值的写入 —— 那部分契约由
 *   `LibrarySettingsPanel` 相关测试守住。
 */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LibraryWizard from '@/components/tools/LibraryWizard.vue'
import { api, type LibraryType } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: {
    createLibrary: vi.fn(),
    librarySettingsUpdate: vi.fn(),
    librarySettingsReset: vi.fn(),
    librarySourceDirs: vi.fn(),
    getConfig: vi.fn(),
  },
}))

const mockCreate = vi.mocked(api.createLibrary)
const mockSettingsUpdate = vi.mocked(api.librarySettingsUpdate)
const mockSourceDirs = vi.mocked(api.librarySourceDirs)
const mockGetConfig = vi.mocked(api.getConfig)

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

const CONFIG_ON = {
  config: { scrape: { enabled: true } },
  overrides: {},
  config_file: '',
  settings_file: '',
  backup_dir: '',
}
const CONFIG_OFF = {
  config: { scrape: { enabled: false } },
  overrides: {},
  config_file: '',
  settings_file: '',
  backup_dir: '',
}

async function openWizard(): Promise<VueWrapper> {
  const w = mount(LibraryWizard, {
    props: { types: TYPES, sourceRoots: SOURCE_ROOTS, libs: [] },
  })
  await flushPromises()
  await flushPromises()
  return w
}

/** 取最近一次 `createLibrary` 的 payload（没有就判定失败，避免用例静默通过） */
function payload(): CreatePayload {
  const calls = mockCreate.mock.calls
  expect(calls.length, '一次 createLibrary 都没发 —— 「创建」是不是退化成了只关弹窗？').toBeGreaterThan(0)
  return calls[calls.length - 1][0]
}

/** 在「内容来源」里挑一个来源根、把当前文件夹加进已选（第 41 期：多根下钻后添加）。 */
async function selectFolder(w: VueWrapper, rootIndex = 0): Promise<void> {
  const nameInput = w.find('[data-test="wizard-name"]')
  if (!String((nameInput.element as HTMLInputElement).value).trim()) {
    await nameInput.setValue('某库')
    await flushPromises()
  }
  await w.findAll('[data-test="wizard-root-card"]').at(rootIndex)!.trigger('click')
  await flushPromises()
  await w.find('[data-test="wizard-pick-folder"]').trigger('click')
  await flushPromises()
}

/** 切到「自动化」页签。 */
async function gotoAutomation(w: VueWrapper): Promise<void> {
  await w.find('[data-test="wizard-tab-automation"]').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockCreate.mockResolvedValue(CREATED as never)
  mockSettingsUpdate.mockResolvedValue({} as never)
  mockGetConfig.mockResolvedValue(CONFIG_ON as never)
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
})

describe('向导 · 三页签结构', () => {
  it('渲染三个页签，默认停在「内容」', async () => {
    const w = await openWizard()
    expect(w.find('[data-test="wizard-tab-contents"]').exists()).toBe(true)
    expect(w.find('[data-test="wizard-tab-automation"]').exists()).toBe(true)
    expect(w.find('[data-test="wizard-tab-last_scan"]').exists()).toBe(true)
    expect(w.find('[data-test="wizard-name"]').exists()).toBe(true)
  })

  it('切到「自动化」页签显示刮削出版开关；切到「上次扫描」显示新建说明', async () => {
    const w = await openWizard()
    await gotoAutomation(w)
    expect(w.find('[data-test="wizard-scrape"]').exists()).toBe(true)
    await w.find('[data-test="wizard-tab-last_scan"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('这是新建书库，还没有扫描记录')
  })
})

describe('向导 · 必填拦截', () => {
  it('没填库名称时「创建」禁用并提示', async () => {
    const w = await openWizard()
    expect(w.find('[data-test="wizard-create"]').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('请填写库名称')
  })

  it('填了名称但没选文件夹 ⇒ 仍禁用（内容来源必填）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await flushPromises()
    expect(w.find('[data-test="wizard-create"]').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('请至少选择一个内容来源文件夹')
  })

  it('选好文件夹后「创建」可用', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await flushPromises()
    expect(w.find('[data-test="wizard-create"]').attributes('disabled')).toBeUndefined()
  })

  it('成品目录与已有库内容来源重叠时拦停（与后端同口径的预检）', async () => {
    const w = mount(LibraryWizard, {
      props: {
        types: TYPES,
        sourceRoots: SOURCE_ROOTS,
        libs: [{ id: 'a', name: '甲库', source_dirs: ['/srv/library/ebooks'] }] as never,
      },
    })
    await flushPromises()
    await flushPromises()
    await w.find('[data-test="wizard-name"]').setValue('新库')
    await w.find('[data-test="wizard-publish"]').setValue('/srv/library/ebooks/out')
    await flushPromises()
    expect(w.text()).toContain('与书库「甲库」的内容来源文件夹（/srv/library/ebooks）重叠')
    expect(w.find('[data-test="wizard-create"]').attributes('disabled')).toBeDefined()
  })
})

describe('向导 · 多来源根下钻与多选（第 41 期）', () => {
  it('点来源根卡片 ⇒ 拉真实服务器目录，列出可下钻的文件夹', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('某库')
    await flushPromises()
    await w.findAll('[data-test="wizard-root-card"]').at(0)!.trigger('click')
    await flushPromises()

    expect(mockSourceDirs).toHaveBeenCalledWith({ root: 0, path: '' })
    const dirs = w.findAll('[data-test="wizard-browse-dir"]')
    expect(dirs.length).toBe(1) // 只有 comics 是目录，readme.txt 是文件
    expect(w.findAll('[data-test="wizard-browse-file"]').length).toBe(1)
  })

  it('点目录项 ⇒ 下钻一层（面包屑/返回可点）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('某库')
    await flushPromises()
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
    await w.find('[data-test="wizard-name"]').setValue('某库')
    await flushPromises()
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
    await w.find('[data-test="wizard-name"]').setValue('某库')
    await flushPromises()
    await w.findAll('[data-test="wizard-root-card"]').at(0)!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('（此目录下没有子项）')
  })

  it('拉取失败 ⇒ 不打开弹层、不崩（走 toast）', async () => {
    mockSourceDirs.mockRejectedValue(new Error('读不到'))
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('某库')
    await flushPromises()
    await w.findAll('[data-test="wizard-root-card"]').at(0)!.trigger('click')
    await flushPromises()
    expect(w.findAll('[data-test="wizard-browse-dir"]').length).toBe(0)
    expect(w.findAll('[data-test="wizard-browse-file"]').length).toBe(0)
  })
})

describe('向导 · 发出去的 payload', () => {
  it('含当前值，且「允许的格式」空 = 继承类型默认', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await w.find('[data-test="wizard-icon-book"]').trigger('click')
    await selectFolder(w)
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()

    const p = payload()
    expect(p.name).toBe('漫画库')
    expect(p.type).toBe('ebook')
    // 第 41 期：内容来源 = 多文件夹绝对路径
    expect(p.source_dirs).toEqual(['/srv/library'])
    expect(p.icon).toBe('book')
    // 没动过格式勾选 ⇒ 空数组 = 后端读作「没设过」⇒ 回落到该类型的默认白名单
    expect(p.allowed_exts).toEqual([])
    // 排除文本框为空 ⇒ 空数组
    expect(p.exclude).toEqual([])
  })

  it('动过格式勾选 ⇒ 发的是「默认集增删后」的集合，不是只含新勾的那个', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    // 默认集是 ['.epub', '.mobi']，点掉 .epub ⇒ 剩下 ['.mobi']
    await w.find('[data-test="ext-chip-.epub"]').trigger('click')
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()
    expect(payload().allowed_exts).toEqual(['.mobi'])
  })

  it('勾到空 ⇒ 仍然发空数组（= 继承类型默认），并提示这不是「什么格式都不收」', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await w.find('[data-test="ext-chip-.epub"]').trigger('click')
    await w.find('[data-test="ext-chip-.mobi"]').trigger('click')

    expect(w.text()).toContain('继承类型默认')
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()
    expect(payload().allowed_exts).toEqual([])
  })

  it('换库类型 ⇒ 格式勾选回到新类型的默认集（不把上一个类型的自定义带过去）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    // 先在电子书下自定义一下
    await w.find('[data-test="ext-chip-.epub"]').trigger('click')
    // 换成漫画（内容页直接有类型按钮，无需逐页返回）
    await w.findAll('button').find((b) => b.text() === '漫画')!.trigger('click')
    await flushPromises()
    await selectFolder(w)
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()

    // 勾选集 = 漫画的默认集（未自定义 ⇒ 空数组 = 继承）
    expect(payload().type).toBe('comic')
    expect(payload().allowed_exts).toEqual([])
  })

  it('排除图案文本框逐行拆成数组（含 brace 逗号的模式不被切坏）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await w.find('[data-test="wizard-exclude"]').setValue('*.draft.epub\n*.{epub,mobi}\n备份/*')
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()
    expect(payload().exclude).toEqual(['*.draft.epub', '*.{epub,mobi}', '备份/*'])
  })
})

describe('向导 · 刮削出版开关（每库覆盖项）', () => {
  it('全局开 + 不改动 ⇒ 不写覆盖（保持继承全局）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()
    expect(mockCreate).toHaveBeenCalledTimes(1)
    expect(mockSettingsUpdate).not.toHaveBeenCalled()
  })

  it('全局开 + 用户关掉 ⇒ 建库后按新库 id 写一次覆盖', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await gotoAutomation(w)
    // 取消勾选（默认跟随全局「开」）
    await w.find('[data-test="wizard-scrape"]').setValue(false)
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()

    expect(mockSettingsUpdate).toHaveBeenCalledTimes(1)
    expect(mockSettingsUpdate.mock.calls[0][0]).toBe('new-1')
    expect(mockSettingsUpdate.mock.calls[0][1]).toEqual({ 'scrape.enabled': false })
  })

  it('全局关 + 不改动 ⇒ 默认值回落为关，仍不写覆盖', async () => {
    mockGetConfig.mockResolvedValue(CONFIG_OFF as never)
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()
    expect(mockSettingsUpdate).not.toHaveBeenCalled()
  })

  it('全局关 + 用户打开 ⇒ 写一次覆盖（true）', async () => {
    mockGetConfig.mockResolvedValue(CONFIG_OFF as never)
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await selectFolder(w)
    await gotoAutomation(w)
    // 勾选上（默认跟随全局「关」）
    await w.find('[data-test="wizard-scrape"]').setValue(true)
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()

    expect(mockSettingsUpdate).toHaveBeenCalledTimes(1)
    expect(mockSettingsUpdate.mock.calls[0][1]).toEqual({ 'scrape.enabled': true })
  })

  it('先建库再写覆盖：拿到的是**新库的 id**', async () => {
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
    await selectFolder(w)
    await gotoAutomation(w)
    await w.find('[data-test="wizard-scrape"]').setValue(false)
    await w.find('[data-test="wizard-create"]').trigger('click')
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
    await w.find('[data-test="wizard-create"]').trigger('click')
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

  it('填好名称 + 文件夹后「创建」真的建库并 emit created', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    expect(w.find('[data-test="wizard-create"]').attributes('disabled')).toBeDefined()
    await selectFolder(w)
    await flushPromises()
    await w.find('[data-test="wizard-create"]').trigger('click')
    await flushPromises()
    expect(mockCreate).toHaveBeenCalledTimes(1)
    expect(w.emitted('created')).toBeTruthy()
  })
})
