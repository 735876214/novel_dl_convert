import { useMediaQuery } from '@vueuse/core'
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/**
 * 全站断点**唯一真值源**（第 90 期）。
 *
 * 起因：外壳侧栏与书架行都要判「是不是窄屏」，此前只有 `lib/shelfRows.ts`
 * 里一份私有的 `NARROW_QUERY`。本期外壳也要用同一个断点 ⇒ 再抄一份就是
 * 「两处各写一遍」，改断点时必然漏一处（漏了不报错，只是两个地方的
 * 响应式表现悄悄不一致）。故收到这里，两个消费方共用。
 *
 * ## 断点口径
 *
 * `639.98px` 而不是 `640px`：Tailwind 的 `sm` 是 `min-width: 40rem`（640px），
 * `max-width: 639.98px` 与它严丝合缝 —— 用 `640px` 的话 640.00–640.98 这段
 * 宽度会同时命中「窄屏」与 `sm:` 两套样式，出现一帧没人能解释的错位。
 *
 * ⚠️ 上游 BookOrbit 用的是 **768px**（`md`）。本项目**刻意不用**：768 档
 * 现在要与宽屏保持同样的两栏布局（用户口径），若把断点提到 768，
 * 640–767 这段会突然变成抽屉 —— 那是**行为变差**，不是对齐上游。
 *
 * ⚠️ 只影响**外壳结构**（侧栏是抽屉还是常驻）。页内栅格继续用各自的
 * `sm/md`，两者互不干涉。
 */
export const NARROW_QUERY = '(max-width: 639.98px)'

/**
 * 「侧栏按**抽屉**处理」的判据（第 108 期）—— 只给外壳侧栏用。
 *
 * `NARROW_QUERY` 只按宽度判，于是**宽而矮 / 触屏**的设备会落进「常驻侧栏」分支：
 * 手机横屏（844×390）与平板（1024×768）都 > 639.98px，侧栏就那么常驻着占掉一大块
 * （用户实测口径）。这里只补一个条件，宽屏桌面**一字不改**：
 *
 * - `(pointer: coarse) and (max-width: 1023.98px)`：触屏且不宽于 `lg`
 *   （1023.98 与 Tailwind `lg` 的 1024 严丝合缝，理由同 `NARROW_QUERY` 的 639.98）。
 *
 * 用**指针精度**而不是纯宽度，是为了不碰第 90 期的用户口径：桌面浏览器把窗口拖到
 * 900px 是常见操作，那**不该**突然变成抽屉（640–767 继续两栏）。
 *
 * 语义是「这台设备的侧栏该是抽屉」，不是「屏幕窄」—— 所以它替代 `NARROW_QUERY`
 * 去决定 `Sidebar.vue` 走 Sheet 还是常驻卡片（JS 先裁决分支，CSS 的 `sm:` 只在
 * 常驻分支内部生效）。
 */
export const DRAWER_QUERY = `${NARROW_QUERY}, (pointer: coarse) and (max-width: 1023.98px)`

function mediaQueryUsable(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
}

/**
 * 窄屏判定。
 *
 * `matchMedia` 不可用的环境（极老内核 / 测试桩 / SSR）**按宽屏处理** ——
 * 与 `shelfRows` 此前的兜底语义逐字一致：宁可多渲染一个常驻侧栏，
 * 也不要在读不到媒体查询的环境里把导航整块藏进一个打不开的抽屉里。
 */
export function useNarrowScreen(): Ref<boolean> {
  // 环境能力在进程内恒定，故这个分支不会造成 setup 里「钩子顺序不一致」。
  if (!mediaQueryUsable()) return ref(false)
  return useMediaQuery(NARROW_QUERY)
}

/**
 * 抽屉判定（第 108 期）：外壳侧栏该是抽屉（手机竖屏 / 手机横屏 / 平板）还是常驻卡片。
 *
 * 兜底与 `useNarrowScreen` 逐字一致 —— 读不到 `matchMedia` 一律**按宽屏处理**
 * （不抽屉）。反过来会把整个导航藏进一个打不开的抽屉里：页面不报错，只是左边空了。
 */
export function useDrawerLayout(): Ref<boolean> {
  if (!mediaQueryUsable()) return ref(false)
  return useMediaQuery(DRAWER_QUERY)
}

/**
 * 手写监听版（保留给「必须精确控制挂载时机」的场景，如既有书架行）。
 *
 * 与 `useNarrowScreen` 判据、兜底完全一致，只是把 `MediaQueryList` 的
 * 建立/移除放在 `onMounted` / `onBeforeUnmount` 里，避免在 setup 阶段
 * 触碰 `window`。同一个断点常量，两处实现各自只做一件事。
 */
export function useNarrowScreenOnMount(): Ref<boolean> {
  const narrow = ref(false)
  let mql: MediaQueryList | null = null
  let update: (() => void) | null = null

  onMounted(() => {
    if (!mediaQueryUsable()) return
    try {
      mql = window.matchMedia(NARROW_QUERY)
      update = () => {
        narrow.value = Boolean(mql?.matches)
      }
      update()
      mql.addEventListener('change', update)
    } catch {
      /* matchMedia 不可用：按宽屏处理 */
    }
  })

  onBeforeUnmount(() => {
    if (mql && update) {
      try {
        mql.removeEventListener('change', update)
      } catch {
        /* ignore */
      }
    }
    mql = null
    update = null
  })

  return narrow
}
