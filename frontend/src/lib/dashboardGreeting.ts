/**
 * 首页问候语的按时段分段（第 82 期对齐 BookOrbit 的 `lib/greeting.ts`）。
 *
 * 纯函数 + 文案表，便于单测；本项目无 i18n，文案是中文字面量。
 * 时段判定优先用**账号资料里的 IANA 时区**（`auth.timezone`，设置页可改），
 * 没有或解析不了回落浏览器本地时间 —— 与上游「按用户时区」的语义一致。
 */

export type GreetingKey = 'morning' | 'afternoon' | 'evening' | 'night'

export const GREETING_LABEL: Record<GreetingKey, string> = {
  morning: '早上好',
  afternoon: '下午好',
  evening: '晚上好',
  night: '夜深了',
}

/** 把时刻换算到指定时区的小时（0..23）；解析失败回落浏览器本地时间 */
function hourIn(now: Date, timezone?: string): number {
  if (!timezone) return now.getHours()
  try {
    const text = now.toLocaleString('zh-CN', { timeZone: timezone, hour: 'numeric', hour12: false })
    const hour = Number.parseInt(text, 10)
    return Number.isFinite(hour) ? Math.abs(hour) % 24 : now.getHours()
  } catch {
    return now.getHours()
  }
}

/** 按小时分段：清晨 5–12 / 下午 12–18 / 晚上 18–23 / 其余为深夜 */
export function getDashboardGreetingKey(now: Date, timezone?: string): GreetingKey {
  const hour = hourIn(now, timezone)
  if (hour >= 5 && hour < 12) return 'morning'
  if (hour >= 12 && hour < 18) return 'afternoon'
  if (hour >= 18 && hour < 23) return 'evening'
  return 'night'
}

/** 直接取问候文案（问候语行的唯一入口） */
export function getDashboardGreeting(now: Date, timezone?: string): string {
  return GREETING_LABEL[getDashboardGreetingKey(now, timezone)]
}
