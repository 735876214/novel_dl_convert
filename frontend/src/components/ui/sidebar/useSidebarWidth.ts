import { onBeforeUnmount, ref } from 'vue'

import { readDeviceValue, SIDEBAR_WIDTH_KEY, writeDeviceValue } from '@/lib/sidebarPrefs'

/**
 * 侧栏宽度（第 90 期，移植 BookOrbit 的 `ui/sidebar/useSidebarWidth.ts`）。
 *
 * ⚠️ 默认宽度改成了 **240px**（上游是 256px）：本项目既有的侧栏就是 `w-[15rem]`
 * = 240px，直接改成 256 会让**每一个**宽屏用户的开箱布局都变一下 —— 那是本期内
 * 唯一明确不允许的「视觉回归」。上下限（224–480）与上游一致：下限保证最窄时
 * 还放得下图标 + 文字，上限之外再宽就只剩空白。
 */

export const SIDEBAR_WIDTH_DEFAULT_PX = 240
export const SIDEBAR_WIDTH_MIN_PX = 224
export const SIDEBAR_WIDTH_MAX_PX = 480
/** 拖拽期间**不**每次都写 localStorage（一帧能写几十次）；停手 120ms 才落盘。 */
export const SIDEBAR_WIDTH_PERSIST_DEBOUNCE_MS = 120

export function clampSidebarWidth(value: number): number {
  if (!Number.isFinite(value)) return SIDEBAR_WIDTH_DEFAULT_PX
  const rounded = Math.round(value)
  return Math.min(SIDEBAR_WIDTH_MAX_PX, Math.max(SIDEBAR_WIDTH_MIN_PX, rounded))
}

export function useSidebarWidth() {
  const widthPx = ref<number>(clampSidebarWidth(readDeviceValue<number>(SIDEBAR_WIDTH_KEY, SIDEBAR_WIDTH_DEFAULT_PX)))

  let persistTimer: ReturnType<typeof setTimeout> | null = null
  let pendingPersistWidth: number | null = null

  function flushPersist() {
    if (persistTimer !== null) {
      clearTimeout(persistTimer)
      persistTimer = null
    }
    if (pendingPersistWidth !== null) {
      writeDeviceValue(SIDEBAR_WIDTH_KEY, pendingPersistWidth)
      pendingPersistWidth = null
    }
  }

  function schedulePersist(width: number) {
    pendingPersistWidth = width
    if (persistTimer !== null) clearTimeout(persistTimer)
    persistTimer = setTimeout(flushPersist, SIDEBAR_WIDTH_PERSIST_DEBOUNCE_MS)
  }

  function setWidth(value: number) {
    const clamped = clampSidebarWidth(value)
    if (clamped === widthPx.value) return
    widthPx.value = clamped
    schedulePersist(clamped)
  }

  /**
   * ⚠️ 卸载时必须补一次 flush：拖动到一半就切走（改路由、关标签）时，
   * 最后那次宽度还在防抖窗口里 —— 不补这一下，用户「拖完了但没生效」。
   */
  onBeforeUnmount(flushPersist)

  return {
    widthPx,
    setWidth,
    minWidthPx: SIDEBAR_WIDTH_MIN_PX,
    maxWidthPx: SIDEBAR_WIDTH_MAX_PX,
  }
}
