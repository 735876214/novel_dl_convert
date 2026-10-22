import { describe, expect, it } from 'vitest'

import { localDate, localDateToEpoch, localMonth } from './format'

/**
 * 第 135 期：全前端的「本地日期」收敛到这两个函数。
 *
 * 用例刻意用 `new Date(年, 月, 日, …)`（**本地**构造器）而不是 ISO 字符串
 * —— ISO 带 Z 就是 UTC，会把断言变成「在哪个时区跑就绿/红」的假绿。
 */
describe('localDate', () => {
  it('取本地日：本地 00:30 仍是当天（UTC 口径会算成前一天）', () => {
    expect(localDate(new Date(2026, 0, 2, 0, 30))).toBe('2026-01-02')
  })

  it('月和日都补零', () => {
    expect(localDate(new Date(2026, 8, 7))).toBe('2026-09-07')
  })

  it('缺省参数是现在（本地）', () => {
    const now = new Date()
    const want = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    expect(localDate()).toBe(want)
  })
})

describe('localMonth', () => {
  it('只要年 + 月，同样按本地时区', () => {
    expect(localMonth(new Date(2026, 8, 7))).toBe('2026-09')
    expect(localMonth(new Date(2026, 0, 1, 0, 30))).toBe('2026-01')
  })
})

/**
 * 第 142 期：`<input type=date>` 的字符串 → epoch 秒。
 *
 * ⚠️ 这条用例守的是「**别用 `Date.parse`**」：`Date.parse('2026-10-22')` 按规范是
 * **UTC 午夜**，在 UTC 以西的时区会退回前一天（西半球用户存一次「今天」，读回来变昨天）。
 * 断言方式：`localDateToEpoch` 的结果再经 `localDate()` 还原，必须还是同一个日期 ——
 * 这条不依赖跑用例的机器在哪个时区，UTC 以东/以西都成立。
 */
describe('localDateToEpoch', () => {
  it('取本地当日零点（与 localDate 同一把尺子：来回一趟仍是同一天）', () => {
    for (const s of ['2026-01-02', '2026-03-08', '2026-10-22', '2026-12-31']) {
      const epoch = localDateToEpoch(s)
      expect(localDate(new Date(epoch * 1000))).toBe(s)
    }
  })

  it('空串 / 非法串 → 0（调用方按「没填」处理，不写一个 1970 年进去）', () => {
    expect(localDateToEpoch('')).toBe(0)
    expect(localDateToEpoch('  ')).toBe(0)
    expect(localDateToEpoch('2026/10/22')).toBe(0)
    expect(localDateToEpoch('2026-13-01')).toBeGreaterThan(0) // 越界由 Date 归一，不做二次判断
  })
})
