import { describe, expect, it } from 'vitest'

import {
  fmtAgo,
  fmtBytes,
  fmtClock,
  fmtClockHM,
  fmtDateTime,
  fmtDateTimeSec,
  fmtDay,
  fmtWhen,
  localDate,
  localDateToEpoch,
  localMonth,
} from './format'

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

/**
 * 第 265 期：把这些格式化收成**唯一实现**（此前 `fmtBytes` 有 11 份本地副本、取整规则 5 种
 * ⇒ 同一个 1.5 MB 在不同页面显示 1.5 / 1.50 / 2 MB；仪表盘对 500 KB 的书库显示 `0 MB`）。
 * `tests/test_shared_formatters_265.py` 钉住「除本文件外不许再定义这些名字」。
 */
describe('fmtBytes', () => {
  it('整数不带 `.0`，小数留一位，≥10 取整', () => {
    expect(fmtBytes(1024)).toBe('1 KB')
    expect(fmtBytes(7168)).toBe('7 KB')
    expect(fmtBytes(1536)).toBe('1.5 KB')
    expect(fmtBytes(10 * 1024)).toBe('10 KB')
    expect(fmtBytes(512 * 1024)).toBe('512 KB')   // 旧仪表盘对这一段显示 `0 MB`（只认 MB 档）
    expect(fmtBytes(1.5 * 1024 * 1024)).toBe('1.5 MB')
    expect(fmtBytes(1024 ** 4)).toBe('1 TB')
  })

  it('0 / null / undefined / NaN 各有明确出口（不吐 `NaN MB`）', () => {
    expect(fmtBytes(0)).toBe('0 B')
    expect(fmtBytes(null)).toBe('—')
    expect(fmtBytes(undefined)).toBe('—')
    expect(fmtBytes(Number.NaN)).toBe('—')
    expect(fmtBytes(undefined, '')).toBe('')
  })
})

describe('日期 / 时间', () => {
  const d = new Date(2026, 10, 6, 14, 30, 5)
  const sec = d.getTime() / 1000

  it('fmtDay / fmtDateTime / fmtDateTimeSec 同一把本地尺子', () => {
    expect(fmtDay(sec)).toBe('2026-11-06')
    expect(fmtDateTime(sec)).toBe('2026-11-06 14:30')
    expect(fmtDateTimeSec(sec)).toBe('2026-11-06 14:30:05')
    expect(fmtClockHM(d)).toBe('14:30')
  })

  it('0 / 空 走调用方给的占位符（各页文案不同，但都来自这一处）', () => {
    expect(fmtDay(0)).toBe('—')
    expect(fmtDay(0, '未知时间')).toBe('未知时间')
    expect(fmtDateTime(null, '')).toBe('')
    expect(fmtDateTimeSec(undefined, '从未使用')).toBe('从未使用')
  })

  it('fmtWhen：今天省年份、今年省年份、跨年给全年份', () => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 9, 5)
    expect(fmtWhen(today.getTime() / 1000)).toBe('今天 09:05')
    const sameYear = new Date(now.getFullYear(), 0, 15, 8, 0)
    expect(fmtWhen(sameYear.getTime() / 1000)).toBe('01-15 08:00')
    expect(fmtWhen(new Date(2020, 4, 3, 7, 8).getTime() / 1000)).toBe('2020-05-03 07:08')
  })
})

describe('fmtClock / fmtAgo', () => {
  it('时钟读数：不足一小时不带小时位，小时位不补零', () => {
    expect(fmtClock(0)).toBe('0:00')
    expect(fmtClock(65)).toBe('1:05')
    expect(fmtClock(3920)).toBe('1:05:20')
    expect(fmtClock(Number.NaN)).toBe('0:00')
  })

  it('相对时间四档', () => {
    const now = Date.now() / 1000
    expect(fmtAgo(now - 10)).toBe('刚刚')
    expect(fmtAgo(now - 600)).toBe('10 分钟前')
    expect(fmtAgo(now - 3 * 3600)).toBe('3 小时前')
    expect(fmtAgo(now - 2 * 86400)).toBe('2 天前')
    expect(fmtAgo(0, '从未扫描')).toBe('从未扫描')
  })
})
