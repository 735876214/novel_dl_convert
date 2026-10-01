import { describe, expect, it } from 'vitest'

import { chunkIntoBands, coverDelayMs, effectiveShelfRows, shelfBookLimit } from './shelfRows'

/** 书架行「多行分带」的纯函数（第 82 期对齐 BookOrbit 的 shelf-rows） */
describe('shelfRows', () => {
  it('effectiveShelfRows：夹取 1..3，窄屏最多压到 2 行', () => {
    expect(effectiveShelfRows(1, false)).toBe(1)
    expect(effectiveShelfRows(2, false)).toBe(2)
    expect(effectiveShelfRows(3, false)).toBe(3)
    expect(effectiveShelfRows(3, true)).toBe(2)
    expect(effectiveShelfRows(2, true)).toBe(2)
    expect(effectiveShelfRows(1, true)).toBe(1)
    // 脏值夹取
    expect(effectiveShelfRows(0, false)).toBe(1)
    expect(effectiveShelfRows(9, false)).toBe(3)
  })

  it('chunkIntoBands：单行等价于原列表；多行均分、最后一带可不满', () => {
    const items = [1, 2, 3, 4, 5]
    expect(chunkIntoBands(items, 1)).toEqual([[1, 2, 3, 4, 5]])
    const bands = chunkIntoBands(items, 2)
    expect(bands).toHaveLength(2)
    expect(bands[0]).toEqual([1, 2, 3])
    expect(bands[1]).toEqual([4, 5])
    // 空列表也要给一带（渲染层按「带」循环，不能拿到空数组）
    expect(chunkIntoBands([], 3)).toEqual([[]])
    // 入参不被改写（分带是纯函数）
    expect(items).toEqual([1, 2, 3, 4, 5])
  })

  it('shelfBookLimit：每行上限 × 行数，再夹到硬顶', () => {
    expect(shelfBookLimit(20, 1, 50)).toBe(20)
    expect(shelfBookLimit(20, 2, 50)).toBe(40)
    expect(shelfBookLimit(20, 3, 50)).toBe(50)
    expect(shelfBookLimit(20, 4, 50)).toBe(50)
    // perRow 非法时按 1 行兜底
    expect(shelfBookLimit(0, 2, 50)).toBe(2)
  })

  it('coverDelayMs：按 35ms 递进，且有上限兜底（长尾延迟会被读成「这一行坏了」）', () => {
    expect(coverDelayMs(0)).toBe(0)
    expect(coverDelayMs(1)).toBe(35)
    expect(coverDelayMs(19)).toBe(665) // 本项目每带上限 20 张 ⇒ 实际最大延迟
    // 上限：再往后不再线性增长
    expect(coverDelayMs(100)).toBe(700)
    // 脏值不产生负延迟 / NaN
    expect(coverDelayMs(-3)).toBe(0)
    expect(coverDelayMs(Number.NaN)).toBe(0)
  })
})
