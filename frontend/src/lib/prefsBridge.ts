/**
 * 偏好变更桥：把「某个偏好被改动」这件事从各偏好模块传出去。
 *
 * 为什么需要它（而不是让 `lib/readerPrefs.ts` 直接 import prefSync store）：
 * 同步层要读这些模块（`stores/prefSync.ts` → `lib/readerPrefs.ts`），
 * 反向再 import 就成环。桥接层是零依赖的，两边都能用。
 *
 * 各偏好模块的写入入口在落盘后调用 `notifyPrefsChanged()`，
 * 同步层用 `onPrefsChanged()` 注册回调（只允许一个 —— 本项目单实例）。
 *
 * `suppressing()` 用于「应用远端值」：那批写入会依次触发各模块的 save，
 * 若不抑制就会把刚从服务端拉下来的值又推回去（回环）。
 */

type Listener = () => void

let listener: Listener | null = null
let suppressDepth = 0

/** 注册变更回调（同步层在 setup 时调用一次） */
export function onPrefsChanged(fn: Listener): void {
  listener = fn
}

/** 偏好已写入本机缓存 —— 由各偏好模块的写入入口调用 */
export function notifyPrefsChanged(): void {
  if (suppressDepth > 0) return
  listener?.()
}

/** 在期间发生的偏好写入不触发通知（用于应用远端值） */
export function suppressing<T>(fn: () => T): T {
  suppressDepth += 1
  try {
    return fn()
  } finally {
    suppressDepth -= 1
  }
}
