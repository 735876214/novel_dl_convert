/**
 * 新建书库向导（第 40 期）。
 *
 * ## 这个文件真正在防什么
 *
 * 向导的**绝大部分是展示**，只有三件事会真的写进后端：
 * ① 最后一次 `createLibrary` ② 建库后那一次阅读阈值 `PUT` ③ 二者之间的先后顺序。
 * 其余全是「摆成什么样」。所以下面每组用例都盯着**发出去的 payload**，
 * 而不是「屏幕上有没有这段字」—— 后者在把「立即创建」改成只关弹窗不建库之后**照样是绿的**。
 *
 * 三条最容易走散的语义各有一组用例：
 *   · **全不勾格式 = 继承类型默认**（不是「一个格式都不收」）
 *   · **阅读阈值不勾「本库单独设定」= 不写覆盖**（写了就把继承关系钉死了）
 *   · **必填两步挡得住**（上游标了必填的只有这两步，其余步骤跳过也要能建出来）
 */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LibraryWizard from '@/components/tools/LibraryWizard.vue'
import { api, type LibraryMode, type LibraryType } from '@/lib/api'
import { refreshThresholds } from '@/lib/readingThresholds'

vi.mock('@/lib/api', () => ({
  api: {
    createLibrary: vi.fn(),
    librarySettingsUpdate: vi.fn(),
    librarySettingsReset: vi.fn(),
    readingThresholds: vi.fn(),
  },
}))

const mockCreate = vi.mocked(api.createLibrary)
const mockSettingsUpdate = vi.mocked(api.librarySettingsUpdate)
const mockThresholds = vi.mocked(api.readingThresholds)

type CreatePayload = Parameters<typeof api.createLibrary>[0]

const TYPES: { value: LibraryType; label: string; exts: string[] }[] = [
  { value: 'ebook', label: '电子书', exts: ['.epub', '.mobi'] },
  { value: 'comic', label: '漫画', exts: ['.cbz', '.cbr'] },
]
const MODES: { value: LibraryMode; label: string }[] = [
  { value: 'inplace', label: '就地引用' },
  { value: 'import', label: '独立存储' },
]

const CREATED = { ok: true, library: { id: 'new-1' } }

async function openWizard(): Promise<VueWrapper> {
  const w = mount(LibraryWizard, {
    props: { types: TYPES, modes: MODES, sourceDir: '/srv/library', libs: [] },
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

function stepText(w: VueWrapper): string {
  return w.text()
}

/** 读某个受控输入框当前的值 */
function val(w: VueWrapper, test: string): string {
  return (w.find(`[data-test="${test}"]`).element as HTMLInputElement).value
}

/** 填个库名推进到第 2 步（库根 / 来源子目录 / 成品目录都在那一步） */
async function gotoFolders(w: VueWrapper): Promise<void> {
  await w.find('[data-test="wizard-name"]').setValue('某库')
  await w.find('[data-test="wizard-next"]').trigger('click')
}

beforeEach(async () => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockCreate.mockResolvedValue(CREATED as never)
  mockSettingsUpdate.mockResolvedValue({} as never)
  mockThresholds.mockResolvedValue({ library_id: '', started: 0, finished: 99.5 })
  // 阈值模块有自己的缓存，跨用例会串 —— 强制重取一次，让每个用例都从干净状态开始
  await refreshThresholds()
})

describe('向导 · 步骤推进与必填拦截', () => {
  it('没填库名称时「继续」不放行，停在第一步', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(stepText(w)).toContain('第 1 步，共 5 步')
  })

  it('填了名称就能进第二步；清空库根则挡在第二步', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(stepText(w)).toContain('第 2 步，共 5 步')

    // onMounted 已经填了默认库根 —— 清掉它，看拦不拦
    await w.find('[data-test="wizard-root"]').setValue('')
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(stepText(w)).toContain('第 2 步，共 5 步')
  })

  it('成品目录与已有库根重叠时挡在第二步（与后端同口径的预检）', async () => {
    const w = mount(LibraryWizard, {
      props: {
        types: TYPES,
        modes: MODES,
        sourceDir: '/srv/library',
        libs: [{ id: 'a', name: '甲库', root_path: '/srv/library/ebooks' }] as never,
      },
    })
    await flushPromises()
    await w.find('[data-test="wizard-name"]').setValue('新库')
    await w.find('[data-test="wizard-next"]').trigger('click')
    await w.find('[data-test="wizard-publish"]').setValue('/srv/library/ebooks/out')
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(stepText(w)).toContain('第 2 步，共 5 步')
  })

  it('「在读下界」不小于「已读完阈值」时挡在第四步', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    for (let i = 0; i < 3; i += 1) await w.find('[data-test="wizard-next"]').trigger('click')
    expect(stepText(w)).toContain('第 4 步，共 5 步')

    await w.find('[data-test="wizard-reading-override"]').setValue(true)
    await w.find('[data-test="wizard-started"]').setValue(90)
    await w.find('[data-test="wizard-finished"]').setValue(50)
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(stepText(w)).toContain('第 4 步，共 5 步')
  })

  it('「立即创建」在第 1 步就能建库（上游的 Create now 语义）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(payload().name).toBe('漫画库')
    expect(w.emitted('created')?.[0]).toEqual(['new-1'])
  })
})

describe('向导 · 建议值（库根 / 来源子目录 / 成品目录）', () => {
  it('来源目录后到 ⇒ 库根补上前缀（挂载时父组件还没加载完）', async () => {
    // 实测过的线上形态：向导先挂载，`reload()` 还没回来，`sourceDir` 是空串，
    // 于是默认库根算成 `/ebooks` —— 一个丢掉了来源目录前缀的、看着像根目录的路径。
    const w = mount(LibraryWizard, {
      props: { types: TYPES, modes: MODES, sourceDir: '', libs: [] },
    })
    await flushPromises()
    await w.setProps({ sourceDir: '/srv/library' })
    await flushPromises()
    await gotoFolders(w)
    expect(val(w, 'wizard-root')).toBe('/srv/library/ebooks')
    expect(val(w, 'wizard-sub')).toBe('ebooks')
    expect(val(w, 'wizard-publish')).toBe('/srv/library/../output/ebook-sorted')
  })

  it('换库类型 ⇒ 库根与来源子目录都换成新类型的（不留上一个类型的）', async () => {
    const w = await openWizard()
    // 类型在第一步，库根在第二步 —— 按真实顺序走
    await w.findAll('button').find((b) => b.text() === '漫画')!.trigger('click')
    await gotoFolders(w)
    expect(val(w, 'wizard-root')).toBe('/srv/library/comics')
    expect(val(w, 'wizard-sub')).toBe('comics')
    expect(val(w, 'wizard-publish')).toBe('/srv/library/../output/comic-sorted')
  })

  it('手改过库根 ⇒ 再换类型不覆盖（尊重用户已经填进去的东西）', async () => {
    const w = await openWizard()
    await gotoFolders(w)
    await w.find('[data-test="wizard-root"]').setValue('/srv/library/我自己分的')

    await w.find('[data-test="wizard-back"]').trigger('click')
    await w.findAll('button').find((b) => b.text() === '漫画')!.trigger('click')
    await w.find('[data-test="wizard-next"]').trigger('click')
    expect(val(w, 'wizard-root')).toBe('/srv/library/我自己分的')
  })

  it('换存放方式 ⇒ 库根按新模式重算（这种切换不保留旧库根）', async () => {
    const w = await openWizard()
    await gotoFolders(w)
    await w.find('[data-test="wizard-root"]').setValue('/srv/library/自定义')
    await w.findAll('button').find((b) => b.text() === '独立存储')!.trigger('click')
    await flushPromises()
    expect(val(w, 'wizard-root')).toBe('/srv/library/../data/libraries/ebook')
  })
})

describe('向导 · 发出去的 payload', () => {
  it('含当前步的值与默认值，「允许的格式」空 = 继承类型默认', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    await w.find('[data-test="wizard-icon-book"]').trigger('click')
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()

    const p = payload()
    expect(p.name).toBe('漫画库')
    expect(p.type).toBe('ebook')
    expect(p.root_path).toBe('/srv/library/ebooks')
    expect(p.icon).toBe('book')
    // 没动过格式勾选 ⇒ 空数组 = 后端读作「没设过」⇒ 回落到该类型的默认白名单
    expect(p.allowed_exts).toEqual([])
    expect(p.exclude).toEqual([])
  })

  it('动过格式勾选 ⇒ 发的是「默认集增删后」的集合，不是只含新勾的那个', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    for (let i = 0; i < 2; i += 1) await w.find('[data-test="wizard-next"]').trigger('click')
    expect(stepText(w)).toContain('第 3 步，共 5 步')

    // 默认集是 ['.epub', '.mobi']，点掉 .epub ⇒ 剩下 ['.mobi']
    await w.find('[data-test="ext-chip-.epub"]').trigger('click')
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(payload().allowed_exts).toEqual(['.mobi'])
  })

  it('勾到空 ⇒ 仍然发空数组（= 继承类型默认），并提示这不是「什么格式都不收」', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    for (let i = 0; i < 2; i += 1) await w.find('[data-test="wizard-next"]').trigger('click')
    await w.find('[data-test="ext-chip-.epub"]').trigger('click')
    await w.find('[data-test="ext-chip-.mobi"]').trigger('click')

    expect(w.text()).toContain('继承类型默认')
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(payload().allowed_exts).toEqual([])
  })

  it('换库类型 ⇒ 格式勾选回到新类型的默认集（不把上一个类型的自定义带过去）', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    for (let i = 0; i < 2; i += 1) await w.find('[data-test="wizard-next"]').trigger('click')
    await w.find('[data-test="ext-chip-.epub"]').trigger('click')       // 自定义过
    await w.find('[data-test="wizard-back"]').trigger('click')
    await w.find('[data-test="wizard-back"]').trigger('click')          // 回到第 1 步
    await w.findAll('button').find((b) => b.text() === '漫画')!.trigger('click')
    for (let i = 0; i < 2; i += 1) await w.find('[data-test="wizard-next"]').trigger('click')

    // 勾选集 = 漫画的默认集，而不是电子书那个被改过的
    expect(w.find('[data-test="ext-chip-.cbz"]').attributes('aria-pressed')).toBe('true')
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(payload().type).toBe('comic')
    expect(payload().allowed_exts).toEqual([])
  })

  it('排除图案可加可删，删掉的不进 payload', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    for (let i = 0; i < 2; i += 1) await w.find('[data-test="wizard-next"]').trigger('click')

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
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(mockCreate).toHaveBeenCalledTimes(1)
    expect(mockSettingsUpdate).not.toHaveBeenCalled()
  })

  it('勾了且与全局不同 ⇒ 建库之后按新库 id 写一次覆写', async () => {
    const w = await openWizard()
    await w.find('[data-test="wizard-name"]').setValue('漫画库')
    for (let i = 0; i < 3; i += 1) await w.find('[data-test="wizard-next"]').trigger('click')
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
    for (let i = 0; i < 3; i += 1) await w.find('[data-test="wizard-next"]').trigger('click')
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
    for (let i = 0; i < 3; i += 1) await w.find('[data-test="wizard-next"]').trigger('click')
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
    // 停在第一步就点创建 —— 这正是上游 Any step 的 Create now
    expect(stepText(w)).toContain('第 1 步，共 5 步')
    await w.find('[data-test="wizard-create-now"]').trigger('click')
    await flushPromises()
    expect(mockCreate).toHaveBeenCalledTimes(1)
    expect(w.emitted('created')).toBeTruthy()
  })
})
