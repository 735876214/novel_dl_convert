import { describe, expect, it } from 'vitest'

import { localDate, localMonth } from './format'

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
