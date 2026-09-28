import { describe, expect, it } from 'vitest'

import { fromPercent, toPercent } from './unitsProgress'

/**
 * 第 73 期：「话 / 轨 ↔ 百分比」的换算（唯一真值源）。
 *
 * 这份用例钉的是**两个方向严格互逆**与**边界不越界**：
 * 它一处出错，表现都是「书架说读到第 3 话、点进去从第 1 话开始」，而且不报错。
 */
describe('toPercent / fromPercent', () => {
  it('基本口径：percent = (话号 + 话内比例) / 话数 × 100', () => {
    expect(toPercent(0, 0, 4)).toBe(0)
    expect(toPercent(0, 0.5, 4)).toBe(12.5)
    expect(toPercent(2, 0.5, 4)).toBe(62.5)
    expect(toPercent(3, 1, 4)).toBe(100)
  })

  it('每一话的开头都能原样反解回来（往返不漂）', () => {
    const total = 43
    for (let i = 0; i < total; i += 1) {
      const r = fromPercent(toPercent(i, 0, total), total)
      // 话号必须**精确**（它决定点进去打开的是哪一话）；话内比例只要求浮点容差
      // —— 43 话里 `7 / 43 × 100` 反解回来会留 8.9e-16 的尾巴，而下游拿它做的是
      // `floor(w × 页数) + 1`，这点尾巴落在第 1 页上，不影响任何东西。
      expect(r.index).toBe(i)
      expect(r.within).toBeLessThan(1e-9)
    }
  })

  it('「这一话读完」与「下一话开头」是同一个数，反解一律给下一话', () => {
    const total = 43
    expect(toPercent(7, 1, total)).toBe(toPercent(8, 0, total))
    expect(fromPercent(toPercent(7, 1, total), total).index).toBe(8)
  })

  it('话内位置也能反解回来（浮点往返在容差内）', () => {
    const total = 43
    for (const w of [0.1, 0.25, 0.5, 0.9]) {
      const r = fromPercent(toPercent(7, w, total), total)
      expect(r.index).toBe(7)
      expect(r.within).toBeCloseTo(w, 10)
    }
  })

  it('100% 落在**最后一话的末尾**，不越界到不存在的一话', () => {
    // 读完最后一话时 percent 正好是 100：floor 的结果是 total，被夹回 total-1
    const r = fromPercent(100, 4)
    expect(r.index).toBe(3)
    expect(r.within).toBeLessThan(1)
    expect(r.within).toBeGreaterThan(0.99)
  })

  it('越界输入一律被夹住，不产生负数下标 / 超过话数的下标', () => {
    expect(fromPercent(-50, 4)).toEqual({ index: 0, within: 0 })
    expect(fromPercent(999, 4)).toEqual({ index: 3, within: 0.999 })
    expect(fromPercent(Number.NaN, 4)).toEqual({ index: 0, within: 0 })
    expect(toPercent(-3, 0, 4)).toBe(0)
    expect(toPercent(99, 0, 4)).toBe(75)
    expect(toPercent(1, 5, 4)).toBe(50)      // within 夹到 1
    expect(toPercent(1, -5, 4)).toBe(25)     // within 夹到 0
  })

  it('话数未知（0 / NaN）时给 0，不产生 NaN / Infinity 写进库', () => {
    for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(toPercent(3, 0.5, bad)).toBe(0)
      expect(fromPercent(50, bad)).toEqual({ index: 0, within: 0 })
    }
  })

  it('百分比的整数化会把话内位置挪走 —— 所以写库那一步**不取整**', () => {
    // 43 话的书里 1 话只占 2.33%：5.58% 与 6.74% 都还在第 3 话（下标 2）里，
    // 四舍五入成 6 之后反解出来的话内比例已经不是写进去的那个了。
    const total = 43
    const exact = toPercent(2, 0.4, total)
    expect(exact).toBeCloseTo(5.5814, 3)
    const restored = fromPercent(Math.round(exact), total)
    expect(restored.index).toBe(2)
    expect(restored.within).not.toBeCloseTo(0.4, 2)   // 被挪到 58% 左右
  })
})
