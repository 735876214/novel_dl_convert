import { describe, expect, it } from 'vitest'

import { getDashboardGreeting, getDashboardGreetingKey } from './dashboardGreeting'

/** 问候语的按时段分段（第 82 期）：纯函数，直接对表 */
describe('dashboardGreeting', () => {
  const mk = (h: number) => new Date(2026, 8, 30, h, 0, 0)

  it('按小时分段：清晨 5–12 / 下午 12–18 / 晚上 18–23 / 其余深夜', () => {
    expect(getDashboardGreetingKey(mk(5))).toBe('morning')
    expect(getDashboardGreetingKey(mk(11))).toBe('morning')
    expect(getDashboardGreetingKey(mk(12))).toBe('afternoon')
    expect(getDashboardGreetingKey(mk(17))).toBe('afternoon')
    expect(getDashboardGreetingKey(mk(18))).toBe('evening')
    expect(getDashboardGreetingKey(mk(22))).toBe('evening')
    expect(getDashboardGreetingKey(mk(23))).toBe('night')
    expect(getDashboardGreetingKey(mk(4))).toBe('night')
    expect(getDashboardGreeting(mk(9))).toBe('早上好')
    expect(getDashboardGreeting(mk(15))).toBe('下午好')
    expect(getDashboardGreeting(mk(20))).toBe('晚上好')
    expect(getDashboardGreeting(mk(2))).toBe('夜深了')
  })

  it('带时区时按该时区的小时判定（同一时刻北京是深夜、UTC 还是下午）', () => {
    // 2026-09-30T15:00:00Z = 北京 23 点（night）= UTC 15 点（afternoon）
    const utc = new Date('2026-09-30T15:00:00Z')
    expect(getDashboardGreetingKey(utc, 'Asia/Shanghai')).toBe('night')
    expect(getDashboardGreetingKey(utc, 'UTC')).toBe('afternoon')
  })

  it('时区非法或解析失败时回落浏览器本地时间，不抛错', () => {
    const now = mk(9)
    expect(getDashboardGreeting(now, 'Not/AZone')).toBe('早上好')
    expect(getDashboardGreetingKey(now, undefined)).toBe('morning')
  })
})
