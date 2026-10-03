import type { ComputedRef, Ref } from 'vue'
import { computed, ref } from 'vue'
import { createContext } from 'reka-ui'

/**
 * 侧栏上下文的常量与注入键（第 90 期，逐字移植 BookOrbit 的 `ui/sidebar/utils.ts`）。
 */

/** 抽屉态（≤640px）的宽度。移动端比桌面宽一点更好按，与上游一致。 */
export const SIDEBAR_WIDTH_MOBILE = '18rem'
/** 折叠成图标条时的宽度。 */
export const SIDEBAR_WIDTH_ICON = '3rem'
/** ⌘/Ctrl + 这个键 = 开合侧栏。与 ⌘K（全局搜索）不冲突，见 `SidebarProvider`。 */
export const SIDEBAR_KEYBOARD_SHORTCUT = 'b'

/**
 * ⚠️ 上游这里还有一个 `SIDEBAR_WIDTH = '16rem'`，本移植**故意不搬**：
 * 它在上游只用于「`--sidebar-width` 没被 JS 设过」的兜底，而本项目
 * `SidebarProvider` 的 `widthPx` 是**同步**从 localStorage 读出来的（默认 240px，
 * 见 `useSidebarWidth.ts`），那根 CSS 变量任何一帧都不会缺席。留一个没人读的
 * 宽度字面量，就会在「默认宽度到底是 240 还是 256」上留下第二份答案。
 */

export interface SidebarContext {
  state: ComputedRef<'expanded' | 'collapsed'>
  open: Ref<boolean>
  setOpen: (value: boolean) => void
  isMobile: Ref<boolean>
  openMobile: Ref<boolean>
  setOpenMobile: (value: boolean) => void
  toggleSidebar: () => void
  widthPx: Ref<number>
  setWidth: (value: number) => void
  minWidthPx: number
  maxWidthPx: number
}

const [injectSidebar, provideSidebarContext] = createContext<SidebarContext>('Sidebar')

/**
 * 兜底上下文：**只为组件测试而存在**。
 *
 * 与 `ui/tooltip/Tooltip.vue` 里那段 `providerInScope` 是同一个理由 —— 单独 mount
 * 一个侧栏部件（`AppHeader.spec.ts` 就是如此）时没有 `SidebarProvider` 祖先，
 * reka-ui 的 `createContext` 会直接抛异常，测试就只会看到「注入失败」而看不到
 * 真正要断言的东西。有了兜底，应用内仍以真 Provider 为准，测试里退化成一个
 * 空壳（`state` 恒为 expanded，点击开合是空操作）。
 *
 * ⚠️ 兜底的 `setWidth` **不写 localStorage**：兜底值不该在测试里留下副作用。
 * ⚠️ 整个进程共用一个实例（不是每次调用新建）：否则同一次渲染里两个部件各自
 * 拿到不同的 `ref`，「点了没反应」会变成随机现象。
 */
let fallbackContext: SidebarContext | null = null

function sidebarFallback(): SidebarContext {
  if (!fallbackContext) {
    fallbackContext = {
      state: computed<'expanded' | 'collapsed'>(() => 'expanded'),
      open: ref(true),
      setOpen: () => {},
      isMobile: ref(false),
      openMobile: ref(false),
      setOpenMobile: () => {},
      toggleSidebar: () => {},
      widthPx: ref(240),
      setWidth: () => {},
      minWidthPx: 224,
      maxWidthPx: 480,
    }
  }
  return fallbackContext
}

/**
 * 取侧栏上下文。**签名与上游一致（无参）**，缺 Provider 时退化为空壳而不是抛异常。
 */
export function useSidebar(): SidebarContext {
  return injectSidebar(sidebarFallback())
}

export { provideSidebarContext }
