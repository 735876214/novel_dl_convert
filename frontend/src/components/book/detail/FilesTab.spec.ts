import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import FilesTab from '@/components/book/detail/FilesTab.vue'
import StatTile from '@/components/ui/StatTile.vue'
import { api, type BookFile } from '@/lib/api'

/**
 * 「文件」标签。三条纪律在这个页面上最容易破，各有一批用例盯着：
 *
 * 1. **远程不给服务器路径**（决策 6）—— 判据在服务端，但「给了就别显示」在前端。
 * 2. **不给不存在的路径** —— 用户照着去找会以为文件丢了，比不给更糟。
 * 3. **不造假数据** —— 恒真的 `ALL PRESENT` 一格不摆；没有的方块不渲染。
 */
vi.mock('@/lib/api', () => ({
  api: { bookLocalPaths: vi.fn() },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const m = { paths: vi.mocked(api.bookLocalPaths) }

const BOOK_ID = 'lib$aaa'
const ABS = String.raw`Z:\books\科幻\三体.epub`
const ABS_MOBI = String.raw`Z:\books\科幻\三体.mobi`

function makeFile(over: Partial<BookFile> = {}): BookFile {
  return { name: '三体.epub', format: 'EPUB', size: 1024, mtime: 1700000000, ...over }
}

async function mountTab(props: Record<string, unknown> = {}): Promise<VueWrapper> {
  const w = mount(FilesTab, {
    props: {
      files: [makeFile()],
      mainName: '三体.epub',
      mainFormat: 'EPUB',
      bookId: BOOK_ID,
      active: true,
      ...props,
    },
    global: { plugins: [createPinia()] },
  })
  await flushPromises()
  return w
}

/** 剪贴板在 happy-dom 里不保证有 —— 每次重建，且**必须是 configurable** 才改得动 */
const writeText = vi.fn()
beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  writeText.mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
    writable: true,
  })
  m.paths.mockResolvedValue({ local: true, paths: { '三体.epub': ABS } })
})

describe('文件标签 · 不点开就不拉', () => {
  it('active 为 false 时一个请求都不发', async () => {
    await mountTab({ active: false })
    expect(m.paths).not.toHaveBeenCalled()
  })

  it('active 变 true 才拉，且带的是这本书的 id', async () => {
    const w = await mountTab({ active: false })
    expect(m.paths).not.toHaveBeenCalled()

    await w.setProps({ active: true })
    await flushPromises()
    expect(m.paths).toHaveBeenCalledTimes(1)
    expect(m.paths).toHaveBeenCalledWith(BOOK_ID)
  })

  it('同一条路由记录内换书时按新 id 重拉', async () => {
    const w = await mountTab()
    expect(m.paths).toHaveBeenCalledWith(BOOK_ID)

    await w.setProps({ bookId: 'lib$bbb' })
    await flushPromises()
    expect(m.paths).toHaveBeenLastCalledWith('lib$bbb')
  })
})

describe('文件标签 · 路径按访问来源区分（决策 6）', () => {
  /**
   * 同一组 props，只翻转服务端给的 `local` —— 这条**成对**的写法是刻意的：
   * 单看「远程不出现绝对路径」可能是恒真的（模板里本来就写错了），
   * 有正例在场才说明这个断言真的盯着那个分支。
   */
  it('本机来源：摆出绝对路径与复制按钮', async () => {
    const w = await mountTab()
    expect(w.find('[data-test="main-abs-path"]').text()).toBe(ABS)
    expect(w.find('[data-test="copy-main-path"]').text()).toBe('复制路径')
  })

  /**
   * ⚠️ 这里**故意**让桩返回一个服务端当前不会产生的响应（`local: false` 却带着路径）。
   *
   * 服务端在远程来源下给的是 `paths: {}`，所以「前端摆不摆」在真实响应上根本分不出来
   * —— 把 `paths: {}` 喂进来再断言「没显示绝对路径」是**恒真的空跑**（本项目对判据力
   * 的既有要求：一条永远绿的用例等于没有）。喂一个非空 `paths` 才真的压到前端那一行
   * 降级（`paths.value = r.local ? r.paths : {}`）：把它改掉，这条就红。
   *
   * 它守的是**纵深**：判据只有服务端一处，但万一将来中间加了缓存层把本机响应回放给
   * 远程，前端这一行是最后一道。
   */
  it('远程来源：即使响应里带了路径也不显示', async () => {
    m.paths.mockResolvedValue({ local: false, paths: { '三体.epub': ABS } })
    const w = await mountTab()

    expect(w.find('[data-test="main-abs-path"]').exists()).toBe(false)
    expect(w.find('[data-test="copy-main-path"]').exists()).toBe(false)
    expect(w.text()).not.toContain('Z:\\books')
    // 降级后剩下的是**库内相对路径** —— 它本来就在文件名那一行
    expect(w.text()).toContain('三体.epub')
  })

  it('复制按钮把绝对路径写进剪贴板，文案回「已复制」', async () => {
    const w = await mountTab()
    await w.find('[data-test="copy-main-path"]').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith(ABS)
    expect(w.find('[data-test="copy-main-path"]').text()).toBe('已复制')
  })

  /**
   * 探测过了、服务端也说「你是本机」、却一条路径都没给 —— 只可能是盘上找不到。
   * 这时**如实说**，一个路径都不摆（摆一个不存在的比不摆更糟）。
   */
  it('本机来源但没定位到文件：说明情况，且不摆任何路径', async () => {
    m.paths.mockResolvedValue({ local: true, paths: {} })
    const w = await mountTab()

    expect(w.find('[data-test="main-path-missing"]').exists()).toBe(true)
    expect(w.find('[data-test="main-abs-path"]').exists()).toBe(false)
    expect(w.text()).not.toContain('Z:\\books')
  })

  it('路径还没拉到时不说「没定位到」（那是一句还没核实过的话）', async () => {
    let release!: (v: { local: boolean; paths: Record<string, string> }) => void
    m.paths.mockReturnValue(new Promise((r) => (release = r)))

    const w = await mountTab()
    expect(w.find('[data-test="main-path-missing"]').exists()).toBe(false)

    release({ local: true, paths: {} })
    await flushPromises()
    expect(w.find('[data-test="main-path-missing"]').exists()).toBe(true)
  })

  it('探测失败当没有：既不给路径，也不断言文件不在', async () => {
    m.paths.mockRejectedValue(new Error('后端挂了'))
    const w = await mountTab()

    expect(w.find('[data-test="main-abs-path"]').exists()).toBe(false)
    expect(w.find('[data-test="main-path-missing"]').exists()).toBe(false)
  })

  it('每份成品都能单独复制自己的路径', async () => {
    m.paths.mockResolvedValue({
      local: true,
      paths: { '三体.epub': ABS, '三体.mobi': ABS_MOBI },
    })
    const w = await mountTab({
      files: [makeFile(), makeFile({ name: '三体.mobi', format: 'MOBI', size: 2048 })],
    })

    const rows = w.findAll('[data-test="file-row"]')
    const copy = rows[1].findAll('button').find((b) => b.text() === '复制')!
    await copy.trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(ABS_MOBI)
  })
})

describe('文件标签 · 统计条不摆恒真的格子', () => {
  /**
   * 样板顶部有第四格 `ALL PRESENT`。本项目**没有**那个数据源：`files` 本身就是磁盘
   * 枚举的结果，「全在」是恒真的 —— 恒真的一格不是信息，是假信息。
   *
   * 断言按格数与标签集合写（不是 `not.toContain('ALL PRESENT')`）：后者在有人
   * 换个名字加回一格时照样绿。
   */
  it('统计条正好三格：文件 / 总大小 / 格式', async () => {
    const w = await mountTab()
    const tiles = w.findAllComponents(StatTile)
    expect(tiles.map((t) => t.props('label'))).toEqual(['文件', '总大小', '格式'])
  })

  it('数值是算出来的，不是硬编码的', async () => {
    const w = await mountTab({
      files: [
        makeFile(),
        makeFile({ name: '三体.mobi', format: 'MOBI', size: 2048 }),
        makeFile({ name: '三体.azw3', format: 'AZW3', size: 4096 }),
      ],
    })
    const tiles = w.findAllComponents(StatTile)
    expect(tiles[0].props('value')).toBe('3')
    expect(tiles[1].props('value')).toBe('7.0 KB')    // 1024 + 2048 + 4096 = 7168（fmtBytes 的口径）
    expect(tiles[2].props('value')).toBe('3')
    // 每组各一个文件 ⇒ 按格式名字典序；主文件那一组（EPUB）永远排头
    expect(tiles[2].props('hint')).toBe('EPUB / AZW3 / MOBI')
  })

  it('一份文件都没有时，统计条整条不渲染', async () => {
    m.paths.mockResolvedValue({ local: false, paths: {} })
    const w = await mountTab({ files: [], mainFormat: 'EPUB' })
    expect(w.findAllComponents(StatTile)).toHaveLength(0)
  })
})

describe('文件标签 · 分组', () => {
  it('主文件所在的格式排第一，其余按组内文件数降序', async () => {
    m.paths.mockResolvedValue({ local: false, paths: {} })
    const w = await mountTab({
      mainName: '三体.mobi',
      mainFormat: 'MOBI',
      files: [
        makeFile({ name: '三体.azw3', format: 'AZW3' }),
        makeFile({ name: '三体.epub', format: 'EPUB' }),
        makeFile({ name: '三体.mobi', format: 'MOBI' }),
      ],
    })

    const groups = w.findAll('[data-test="format-group"]')
    expect(groups.map((g) => g.find('span').text())).toEqual(['MOBI', 'AZW3', 'EPUB'])
  })

  it('主文件那一行标「本条目」，别的行不标', async () => {
    m.paths.mockResolvedValue({ local: false, paths: {} })
    const w = await mountTab({
      files: [makeFile(), makeFile({ name: '三体.mobi', format: 'MOBI' })],
    })

    const rows = w.findAll('[data-test="file-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('本条目')
    expect(rows[1].text()).not.toContain('本条目')
  })

  it('点下载把**那一份**的文件名抛出去', async () => {
    m.paths.mockResolvedValue({ local: false, paths: {} })
    const w = await mountTab({
      files: [makeFile(), makeFile({ name: '三体.mobi', format: 'MOBI' })],
    })

    await w.findAll('[data-test="file-row"]')[1]
      .findAll('button').find((b) => b.text() === '下载')!.trigger('click')

    expect(w.emitted('download')).toEqual([['三体.mobi']])
  })
})

describe('文件标签 · 空态分两种', () => {
  it('普通书没有成品文件 → 「这本书还没有文件」', async () => {
    m.paths.mockResolvedValue({ local: false, paths: {} })
    const w = await mountTab({ files: [], mainFormat: 'EPUB' })

    expect(w.text()).toContain('这本书还没有文件')
    expect(w.text()).not.toContain('Z:\\books')
  })

  /**
   * 目录型有声书 `files` 也是空的（`sibling_files` 对目录返回空），但它**有一整个
   * 目录的轨道** —— 说「还没有文件」是假话。本机来源时这一页给的正是那个目录的路径。
   */
  it('目录型有声书（本机）→ 给目录路径，不说「还没有文件」', async () => {
    const dir = String.raw`Z:\books\三体 广播剧`
    m.paths.mockResolvedValue({ local: true, paths: { '三体 广播剧': dir } })
    const w = await mountTab({ files: [], mainName: '三体 广播剧', mainFormat: 'AUDIO' })

    expect(w.text()).not.toContain('这本书还没有文件')
    expect(w.find('[data-test="main-abs-path"]').text()).toBe(dir)
    expect(w.text()).toContain('轨道清单在「目录」标签')
  })

  it('目录型有声书（远程）→ 说清「路径只在本机显示」，不说「还没有文件」', async () => {
    // 同「远程来源」那条：喂非空 paths 才压得到降级那一行（否则是恒真的空跑）
    m.paths.mockResolvedValue({
      local: false,
      paths: { '三体 广播剧': String.raw`Z:\books\三体 广播剧` },
    })
    const w = await mountTab({ files: [], mainName: '三体 广播剧', mainFormat: 'AUDIO' })

    expect(w.text()).toContain('目录位置只在服务器本机显示')
    expect(w.text()).not.toContain('这本书还没有文件')
    expect(w.text()).not.toContain('Z:\\books')
  })
})
