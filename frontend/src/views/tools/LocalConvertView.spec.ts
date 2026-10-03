import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'
import LocalConvertView from '@/views/tools/LocalConvertView.vue'

/**
 * 本地导入页的**投递链路**（第 91 期）。
 *
 * 这一页原来的失效方式很安静：上传后文件**已经进了书库**，页面却又把后端返回的成品
 * 文件流 `saveBlob()` 推回浏览器 —— 于是多出一次「下载」（浏览器还会拦「是否允许多文件
 * 下载」），而文案写着「逐个入库并下载」。用户会以为「我下到了哪」，实际他并不需要那份文件。
 *
 * 本期改成与收书目录页逐字同源的 **投递 → toast → 刷新**，所以断言落在四件事上：
 *   ① 走的是 **ack 变体**（`convertDrop` / `convertPathDrop`），不是任何读响应体的写法；
 *   ② **不再出现 `createObjectURL`**（半路回退到「推给浏览器存盘」就是本缺陷复发）；
 *   ③ 失败走 toast，且文案是**剥过壳**的（不是后端 `{"detail":"…"}` 原文）；
 *   ④ 投递之后**刷新 input 目录列表**（否则用户看不到刚投进去的文件）。
 */
vi.mock('@/lib/api', () => ({
  api: {
    convertDrop: vi.fn(),
    convertPathDrop: vi.fn(),
    files: vi.fn(),
    watcherStatus: vi.fn(),
    watcherStart: vi.fn(),
    watcherStop: vi.fn(),
    scanNow: vi.fn(),
  },
  apiErrorMessage: (e: unknown, fallback: string) =>
    e instanceof Error && e.message ? e.message : fallback,
}))

function fileEntry(names: string[]): FileList {
  const files = names.map((n) => new File(['x'], n, { type: 'text/plain' }))
  // happy-dom 没有 DataTransfer 构造器，`FileList` 也是只读的 —— 直接做一个最小替身：
  // 被测代码只用 `Array.from(fileList)`，所以只要可迭代、带 `length` 即可。
  return Object.assign(files, { length: files.length }) as unknown as FileList
}

const mounted: VueWrapper[] = []

async function mountView() {
  const w = mount(LocalConvertView, { global: { plugins: [] } })
  mounted.push(w)
  await flushPromises()
  return w
}

/**
 * 抓全部 toast 文案。
 *
 * ⚠️ `ui.toastMessage` 是**单个** ref（后一条覆盖前一条）。只断言它的话，
 * 「逐个文件的失败提示」会被紧随其后的汇总提示顶掉、看不见 —— 于是失败提示
 * 悄悄消失也不会红。所以这里挂在 `ui.toast` 上收全量。
 */
function toastSpy(): { mock: { calls: unknown[][] } } {
  return vi.spyOn(useUiStore(), 'toast') as unknown as { mock: { calls: unknown[][] } }
}

function toasts(spy: { mock: { calls: unknown[][] } }): string[] {
  return spy.mock.calls.map((c) => String(c[0]))
}

/** 让被测组件认为「有几个书库」。0 库会被提前拦下，那是另一条契约（见对应用例）。 */
function setLibraries(n: number): void {
  const s = useLibraryStore()
  s.libraryEntities = Array.from({ length: n }, (_, i) => ({
    id: `lib-${i}`,
    name: `库 ${i}`,
    type: 'mixed',
    type_label: '混合',
    source_dirs: [],
    rules: '{}',
    sort_order: i,
  })) as never
  // `hasNoLibraries` 要求「**已成功取回过**」——不设它的话判据恒为假，0 库那条会假绿
  s.librariesLoaded = true
}

function withLibrary(): void {
  setLibraries(1)
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.files).mockResolvedValue({ input: [], output: [] })
  vi.mocked(api.watcherStatus).mockResolvedValue({
    running: false, dir: '', interval: 0, last_scan: 0,
  } as never)
  vi.mocked(api.convertDrop).mockResolvedValue({ ok: true })
  vi.mocked(api.convertPathDrop).mockResolvedValue({ ok: true })
  vi.mocked(api.scanNow).mockResolvedValue({ ok: true } as never)
})

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  vi.restoreAllMocks()
})

/** 直接调组件暴露的方法：模板只负责把 `FileList` / 路径串递进来，值的来源不是本页的判据 */
type Vm = {
  pathValue: string
  convertFiles(f: FileList): Promise<void>
  convertByPath(): Promise<void>
}

describe('LocalConvertView（第 91 期：投递 + 提示 + 刷新）', () => {
  it('一批文件：逐个走 ack 变体，一个不落', async () => {
    withLibrary()
    const w = await mountView()

    await (w.vm as unknown as Vm).convertFiles(fileEntry(['a.txt', 'b.epub']))
    await flushPromises()

    expect(vi.mocked(api.convertDrop).mock.calls.map((c) => (c[0] as File).name))
      .toEqual(['a.txt', 'b.epub'])
    // ① 不再有 blob 变体（那两个方法已从 api 里删掉，存在即说明回潮了）
    expect('convertFile' in api, 'blob 变体回来了').toBe(false)
    expect('convertPath' in api, 'blob 变体回来了').toBe(false)
  })

  it('不往浏览器推任何文件：整条链路里没有 createObjectURL', async () => {
    withLibrary()
    const create = vi.fn(() => 'blob:fake')
    vi.stubGlobal('URL', { ...URL, createObjectURL: create, revokeObjectURL: vi.fn() })

    const w = await mountView()
    await (w.vm as unknown as Vm).convertFiles(fileEntry(['a.txt']))
    await flushPromises()

    expect(create, '又把成品文件推回浏览器了（本缺陷的原文症状）').not.toHaveBeenCalled()
  })

  it('投递成功后：给提示 + 刷新 input 目录列表', async () => {
    withLibrary()
    const w = await mountView()
    const spy = toastSpy()
    vi.mocked(api.files).mockResolvedValue({
      input: [{ name: 'a.txt', size: 12, mtime: 0 }], output: [],
    } as never)

    await (w.vm as unknown as Vm).convertFiles(fileEntry(['a.txt']))
    await flushPromises()

    expect(toasts(spy).some((t) => t.includes('已投递 1'))).toBe(true)
    expect(api.files, '投递后没刷新 input 列表，用户看不到刚投进去的文件').toHaveBeenCalled()
  })

  it('部分失败：成功的计数、失败的逐个点名（且提示已剥壳）', async () => {
    withLibrary()
    vi.mocked(api.convertDrop)
      .mockResolvedValueOnce({ ok: true })
      .mockRejectedValueOnce(new Error('服务端拒绝了这次投递'))

    const w = await mountView()
    const spy = toastSpy()
    await (w.vm as unknown as Vm).convertFiles(fileEntry(['ok.txt', 'bad.txt']))
    await flushPromises()

    const msgs = toasts(spy)
    expect(msgs, '失败的文件名必须点名，否则多选时用户不知道该重投哪个')
      .toContain('bad.txt：服务端拒绝了这次投递')
    expect(msgs.some((t) => t.includes('已投递 1'))).toBe(true)
    expect(msgs.some((t) => t.includes('{"detail"')), '把后端响应原文塞给用户了').toBe(false)
  })

  it('0 库：一个请求都不发（提前拦下并说明原因）', async () => {
    // 0 库 = 「已成功取回过、而且是空的」——不设 `librariesLoaded` 的话判据恒为假
    setLibraries(0)
    const w = await mountView()
    const spy = toastSpy()
    await (w.vm as unknown as Vm).convertFiles(fileEntry(['a.txt']))
    await flushPromises()

    expect(api.convertDrop, '0 库时不该真的投递').not.toHaveBeenCalled()
    expect(toasts(spy).some((t) => t.includes('还没有书库'))).toBe(true)
  })

  it('按路径入库：走 convertPathDrop（ack 变体），不是 blob 变体', async () => {
    withLibrary()
    const w = await mountView()
    const spy = toastSpy()
    const vm = w.vm as unknown as Vm
    vm.pathValue = '小说/某书.txt'
    await vm.convertByPath()
    await flushPromises()

    expect(api.convertPathDrop).toHaveBeenCalledWith('小说/某书.txt')
    expect(toasts(spy).some((t) => t.includes('已投递 小说/某书.txt'))).toBe(true)
  })

  it('按路径入库：不支持的扩展名不发请求，并说清支持范围', async () => {
    withLibrary()
    const w = await mountView()
    const spy = toastSpy()
    const vm = w.vm as unknown as Vm
    vm.pathValue = '小说/某书.xyz'
    await vm.convertByPath()
    await flushPromises()

    expect(api.convertPathDrop).not.toHaveBeenCalled()
    expect(toasts(spy).some((t) => t.includes('不支持的格式'))).toBe(true)
  })

  it('一批文件里混着不支持的格式：跳过的报数，支持的一个不少', async () => {
    withLibrary()
    const w = await mountView()
    const spy = toastSpy()
    await (w.vm as unknown as Vm).convertFiles(fileEntry(['a.txt', 'b.xyz', 'c.epub']))
    await flushPromises()

    expect(vi.mocked(api.convertDrop).mock.calls.map((c) => (c[0] as File).name))
      .toEqual(['a.txt', 'c.epub'])
    expect(toasts(spy).some((t) => t.includes('已跳过 1 个不支持的格式'))).toBe(true)
  })

  it('文案说的是「投递入库」，不再提下载', async () => {
    withLibrary()
    const w = await mountView()
    expect(w.text()).toContain('逐个投递入库')
    expect(w.text(), '又说回「下载」了').not.toContain('入库并下载')
    // 模板不做 markdown 渲染 —— 字面 `**` 会原样显示给用户（模板里本来有一处，已清掉）
    expect(w.text(), '模板里混进了字面 markdown').not.toContain('**')
  })
})
