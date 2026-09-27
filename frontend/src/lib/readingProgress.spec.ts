import { describe, expect, it, vi } from 'vitest'

import type { ProgressState } from './api'
import { progressForFile, type GetProgress } from './readingProgress'

/**
 * 第 63 期 4/6：恢复阅读位置时该信哪一行（进度按文件维度）。
 *
 * 这份用例钉两条最容易走样的边界：
 * 1. **「本文件没读过」的判据只能是 `file_rel == null`，不能是 `locator === 0`**
 *    —— 第 0 章 / 第 1 页是合法位置，用 locator 判会把一个真读点当成没读过，
 *    然后拿另一个文件的读点顶上来；
 * 2. **回落只认「说的不是别的文件」的书级行** —— 书级 = 最新那行，它可能是 PDF
 *    读出来的（90 是**页码**），拿来当章节号跳到毫不相干的一章。
 */

/** 造一个「查得到」的响应。`file_rel` 用 `''` 表示「不知道文件的那次写入」。 */
function row(file_rel: string | null, locator: number, updated_at = 100): ProgressState {
  return { locator, percent: locator, cfi: '', updated_at, file_rel }
}

/** 一个按 `file_rel` 分发的假接口；记下每次收到的参数，供「查了几次、查的什么」断言。 */
function fakeApi(table: Record<string, ProgressState | undefined>) {
  const calls: (string | undefined)[] = []
  const get: GetProgress = (_id, fileRel) => {
    calls.push(fileRel)
    // 键：undefined → '∅'，其余原样（含空串）
    return Promise.resolve(table[fileRel === undefined ? '∅' : fileRel] ?? MISSING)
  }
  return { get, calls }
}

/** 服务端在「这一行不存在」时给的东西（`file_rel` 是 null，locator 是 0）。 */
const MISSING: ProgressState = { locator: 0, percent: 0, cfi: '', file_rel: null }

describe('progressForFile', () => {
  it('本文件有读点 ⇒ 就用它，且**不再查书级**', async () => {
    const { get, calls } = fakeApi({
      '∅': row('', 9, 500), // 书级有更新的别的读点 —— 有本文件的读点时它不该被用到
      '书.epub': row('书.epub', 3),
    })
    const p = await progressForFile('b', '书.epub', get)
    expect(p.locator).toBe(3)
    expect(calls).toEqual(['书.epub']) // 一次查询 —— 多查一次书级是白跑一个往返
  })

  it('第 0 章是合法位置，不是「没读过」', async () => {
    // 这条是上面那个「不能用 locator 判存在」的钉子：本文件的 locator 就是 0，
    // 而书级有一行**别的文件**的读点。正确行为是用本文件的 0，而不是回落到别人的。
    const { get, calls } = fakeApi({
      '∅': row('书.pdf', 90, 900),
      '书.epub': row('书.epub', 0, 10),
    })
    const p = await progressForFile('b', '书.epub', get)
    expect(p.locator).toBe(0)
    expect(calls).toEqual(['书.epub'])
  })

  it('本文件没读过 + 书级「不知道文件」⇒ 用书级（KOReader / Komga 同步的读点）', async () => {
    const { get, calls } = fakeApi({
      '∅': row('', 12, 800),
      '书.epub': undefined,
    })
    const p = await progressForFile('b', '书.epub', get)
    expect(p.locator).toBe(12)
    expect(calls).toEqual(['书.epub', undefined]) // 先按文件查，查不到才回落
  })

  it('本文件没读过 + 书级说的是**别的文件** ⇒ 不许用，从头开始', async () => {
    // 书级 = 最新那行 = 用户在 PDF 上读到的第 90 页（页码坐标系）。
    // 拿它去章节流恢复会跳到第 90 章 —— 一个「看起来很正常」的错位置。
    const { get } = fakeApi({
      '∅': row('书.pdf', 90, 900),
      '书.epub': undefined,
    })
    const p = await progressForFile('b', '书.epub', get)
    expect(p.locator).toBe(0)
    expect(p.percent).toBe(0)
  })

  it('本文件没读过 + 书级正是本文件 ⇒ 用书级（同一件事，别多一层判断）', async () => {
    const { get } = fakeApi({
      '∅': row('书.epub', 7, 900),
      '书.epub': undefined,
    })
    expect((await progressForFile('b', '书.epub', get)).locator).toBe(7)
  })

  it('不给 fileRel（单文件的书）⇒ 只查书级，一次', async () => {
    const { get, calls } = fakeApi({ '∅': row('', 5, 300) })
    const p = await progressForFile('b', undefined, get)
    expect(p.locator).toBe(5)
    expect(calls).toEqual([undefined])
  })

  it('响应里没有 file_rel（旧服务端）⇒ 按「不知道文件」处理', async () => {
    // 两个方向都说得通，选「不知道文件」是因为代价小：旧服务端**不认识** file_rel
    // 这个参数，两次查询其实返回同一个响应（用户的唯一读点）—— 当成「别的文件」
    // 丢掉它就是凭空从第一章开始；而当成「不知道文件」用上它，在那个服务端上
    // 不可能跳错位置（那时压根没有「第二个文件」这个概念）。
    const { get } = fakeApi({ '∅': { locator: 4, percent: 4, cfi: '' } })
    expect((await progressForFile('b', '书.epub', get)).locator).toBe(4)
  })

  it('默认入口走 api.getProgress（不注入时也能用）', async () => {
    // 注入是为了单测，但生产路径必须真的打到 api 上 —— 这条用 spy 挡在模块边界上，
    // 钉住「默认参数没写错成别的函数」。
    const { api } = await import('./api')
    const spy = vi.spyOn(api, 'getProgress').mockResolvedValue(row('书.epub', 2))
    try {
      expect((await progressForFile('b', '书.epub')).locator).toBe(2)
      expect(spy).toHaveBeenCalledWith('b', '书.epub')
    } finally {
      spy.mockRestore()
    }
  })
})
