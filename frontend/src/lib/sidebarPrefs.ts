/**
 * 侧栏偏好：**本机存储**，不进服务端（第 90 期）。
 *
 * ⚠️ 为什么是 localStorage 而不是 `server.PREFS_BLOCKS`：
 * 「侧栏折叠了没」「侧栏拖多宽」是**屏幕尺寸**的属性，不是人的偏好。同一账号
 * 在 27 寸显示器上拖到 420px、在 iPad 上就该是抽屉 —— 跟着账号同步过去，
 * 等于把大屏的宽度硬塞给小屏。上游 BookOrbit 同理（它存的是设备级的
 * `sections`/`width`），所以这里**刻意不进** `lib/prefsPayload.ts` 的
 * `PAYLOAD_BLOCKS`（那份契约测试 `tests/test_prefs_shelf_block.py` 照着它断言）。
 *
 * ⚠️ 键名是 `nf_` 前缀而不是直接沿用上游的：本机和上游的站点可能同域，
 * 撞键会让两边互相覆盖对方的布局。
 */

const KEY_PREFIX = 'nf_sidebar_'

export const SIDEBAR_COLLAPSED_KEY = `${KEY_PREFIX}collapsed`
export const SIDEBAR_WIDTH_KEY = `${KEY_PREFIX}width`

/**
 * 读本机值。
 *
 * 类型由 `fallback` 决定（`localStorage` 只存字符串，读回来得自己还原）：
 *   · boolean → `'1'` 为真，其余为假；
 *   · number  → `Number(raw)`，`NaN` 视为没存过；
 *   · 其余    → 原样字符串。
 *
 * 任何异常（隐私模式、存储被禁、值被手改成垃圾）一律**返回 fallback**：
 * 读不到就按默认布局渲染，不能因此让整页挂掉。
 */
export function readDeviceValue<T>(key: string, fallback: T): T {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(key)
  } catch {
    return fallback
  }
  if (raw === null) return fallback

  if (typeof fallback === 'boolean') return (raw === '1') as unknown as T
  if (typeof fallback === 'number') {
    const n = Number(raw)
    return (Number.isFinite(n) ? n : fallback) as unknown as T
  }
  return raw as unknown as T
}

/** 写本机值。写不进去（隐私模式/配额满）**静默忽略** —— 布局照常在本会话内生效。 */
export function writeDeviceValue(key: string, value: unknown): void {
  const raw = typeof value === 'boolean' ? (value ? '1' : '0') : String(value)
  try {
    localStorage.setItem(key, raw)
  } catch {
    /* ignore */
  }
}
