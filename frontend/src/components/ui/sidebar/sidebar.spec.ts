import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'

import { DRAWER_QUERY } from '@/lib/viewport'
import { SIDEBAR_COLLAPSED_KEY, SIDEBAR_WIDTH_KEY } from '@/lib/sidebarPrefs'

import { Sidebar, SidebarProvider, SidebarRail, SidebarTrigger } from '.'
import {
  clampSidebarWidth,
  SIDEBAR_WIDTH_DEFAULT_PX,
  SIDEBAR_WIDTH_MAX_PX,
  SIDEBAR_WIDTH_MIN_PX,
} from './useSidebarWidth'

/**
 * 应用外壳侧栏（第 90 期，结构照搬 BookOrbit 的 `ui/sidebar`）。
 *
 * 这一套东西的失效方式**几乎全是静默的**，这正是它需要 spec 的原因：
 *   · 折叠态宽度类挂错元素 ⇒ 图标条**仍是 240px**，只是里面空了一大半；
 *   · 折叠态 / 宽度没落本机存储 ⇒ 每次刷新都弹回默认，用户以为「拖宽没生效」；
 *   · 3px 阈值写反 ⇒ 拉手永远点不出「开合」（手抖 1px 就算拖拽），而拖拽本身照常好用；
 *   · 窄屏没走抽屉 ⇒ 就是本期要修的那个原始缺陷（侧栏死占 240px，正文被挤成一列字）。
 * 一条都不报错、不告警，页面上只是「有点怪」。
 */

// ---------------------------------------------------------------------------
// 桩：可控的 matchMedia（同 lib/viewport.spec.ts 的理由 —— happy-dom 的实现
// 不跟着窗口尺寸变化触发 change，最该测的「跟随变化」反而测不到）
// ---------------------------------------------------------------------------

type ChangeListener = (event: { matches: boolean }) => void

const realMatchMedia = window.matchMedia
let teardown: (() => void) | null = null

function installMatchMedia(initialMatches: boolean) {
  const listeners = new Set<ChangeListener>()
  const queries: string[] = []
  const state = { matches: initialMatches }

  window.matchMedia = ((query: string) => {
    queries.push(query)
    return {
      media: query,
      get matches() {
        return state.matches
      },
      onchange: null,
      addEventListener: (type: string, cb: ChangeListener) => {
        if (type === 'change') listeners.add(cb)
      },
      removeEventListener: (_type: string, cb: ChangeListener) => {
        listeners.delete(cb)
      },
      addListener: (cb: ChangeListener) => listeners.add(cb),
      removeListener: (cb: ChangeListener) => listeners.delete(cb),
      dispatchEvent: () => false,
    }
  }) as unknown as typeof window.matchMedia

  teardown = () => {
    window.matchMedia = realMatchMedia
  }

  return {
    queries,
    change(matches: boolean) {
      state.matches = matches
      for (const cb of [...listeners]) cb({ matches })
    },
  }
}

/**
 * 造一个指针事件。
 *
 * 不用 `new PointerEvent(...)`：happy-dom 对指针事件的支持随版本变，而这里要的
 * 只是 `pointerId / clientX / button` 三个字段 —— 直接在 `Event` 上挂，行为确定。
 */
function pointerEvent(
  type: string,
  init: { pointerId: number; clientX: number; button?: number },
): PointerEvent {
  const event = new Event(type, { bubbles: true, cancelable: true }) as unknown as PointerEvent
  Object.assign(event, { button: 0 }, init)
  return event
}

// ---------------------------------------------------------------------------
// 挂载：Provider + Sidebar + Rail + Trigger（与 App.vue 的外壳同构，只是内容换成探针）
// ---------------------------------------------------------------------------

const mounted: VueWrapper[] = []

function mountShell(): VueWrapper {
  const w = mount(
    defineComponent({
      render() {
        return h(
          SidebarProvider,
          { class: 'h-[100dvh]' },
          {
            default: () => [
              h(
                Sidebar,
                { collapsible: 'icon', variant: 'floating' },
                { default: () => [h('div', '内容'), h(SidebarRail)] },
              ),
              h(SidebarTrigger),
            ],
          },
        )
      },
    }),
  )
  mounted.push(w)
  return w
}

/** 当前侧栏状态（桌面常驻那一块上的 `data-state`） */
function desktopState(w: VueWrapper): string | undefined {
  return w.get('[data-slot="sidebar"]').attributes('data-state')
}

function sidebarWidthVar(w: VueWrapper): string {
  const el = w.get('[data-slot="sidebar-wrapper"]').element as HTMLElement
  return el.style.getPropertyValue('--sidebar-width')
}

/** 点一下拉手（按下不挪就抬起 = 「点击开合」） */
async function clickRail(w: VueWrapper, pointerId = 1, clientX = 200): Promise<void> {
  w.get('[data-sidebar="rail"]').element.dispatchEvent(
    pointerEvent('pointerdown', { pointerId, clientX }),
  )
  window.dispatchEvent(pointerEvent('pointerup', { pointerId, clientX }))
  await nextTick()
}

/** 拖一下拉手（位移 ≥3px = 「拖拽调宽」），起点 x 固定，位移就是宽度变化量 */
async function dragRail(w: VueWrapper, delta: number, pointerId = 2): Promise<void> {
  const x0 = 300
  w.get('[data-sidebar="rail"]').element.dispatchEvent(
    pointerEvent('pointerdown', { pointerId, clientX: x0 }),
  )
  window.dispatchEvent(pointerEvent('pointermove', { pointerId, clientX: x0 + delta }))
  window.dispatchEvent(pointerEvent('pointerup', { pointerId, clientX: x0 + delta }))
  await nextTick()
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
  teardown?.()
  teardown = null
})

describe('clampSidebarWidth（宽度的唯一判据）', () => {
  it('上下限 224–480，越界夹回、小数取整', () => {
    expect(clampSidebarWidth(100)).toBe(SIDEBAR_WIDTH_MIN_PX)
    expect(clampSidebarWidth(9999)).toBe(SIDEBAR_WIDTH_MAX_PX)
    expect(clampSidebarWidth(260.4)).toBe(260)
  })

  it('非有限数（存储被手改成垃圾）退回默认值，不是 NaN', () => {
    // NaN 会让 `--sidebar-width: NaNpx` 整根变量失效 ⇒ 侧栏宽度瞬间回到 auto，
    // 且 `transition-[width]` 无从过渡 —— 页面上是「侧栏突然贴住内容」。
    expect(clampSidebarWidth(Number.NaN)).toBe(SIDEBAR_WIDTH_DEFAULT_PX)
    expect(clampSidebarWidth(Number.POSITIVE_INFINITY)).toBe(SIDEBAR_WIDTH_DEFAULT_PX)
  })

  it('默认宽度是 240px（本仓既有的 w-[15rem]），不是上游的 256px', () => {
    // 本期唯一的红线：宽屏展开态的视觉不许变。跟着上游改成 256 会让**每一个**
    // 宽屏用户的开箱布局都动一下 —— 那是回归，不是对齐。
    expect(SIDEBAR_WIDTH_DEFAULT_PX).toBe(240)
  })
})

describe('SidebarProvider：折叠态与宽度都是本机持久化的', () => {
  it('默认展开 240px', () => {
    const w = mountShell()
    expect(desktopState(w)).toBe('expanded')
    expect(sidebarWidthVar(w)).toBe('240px')
  })

  it('刷新后按本机存的值恢复（折叠态 + 宽度）', () => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, '1')
    localStorage.setItem(SIDEBAR_WIDTH_KEY, '320')
    const w = mountShell()

    expect(desktopState(w)).toBe('collapsed')
    // 折叠成图标条靠的是 `data-collapsible=icon`，由它驱动所有
    // `group-data-[collapsible=icon]:*` 子孙选择器（文字收掉、按钮变方形）
    expect(w.get('[data-slot="sidebar"]').attributes('data-collapsible')).toBe('icon')
    expect(sidebarWidthVar(w)).toBe('320px')
  })

  it('存储里是越界值 ⇒ 夹回上下限后再用', () => {
    localStorage.setItem(SIDEBAR_WIDTH_KEY, '9999')
    const w = mountShell()
    expect(sidebarWidthVar(w)).toBe(`${SIDEBAR_WIDTH_MAX_PX}px`)
  })

  it('⌘/Ctrl+B 开合，并把新状态写回本机存储', async () => {
    const w = mountShell()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true }))
    await nextTick()
    expect(desktopState(w)).toBe('collapsed')
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe('1')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', metaKey: true }))
    await nextTick()
    expect(desktopState(w)).toBe('expanded')
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe('0')
  })

  it('⌘K 不会被侧栏抢走（两个快捷键各管各的键）', async () => {
    // ⌘/Ctrl+K 是全局搜索（App.vue）。这里若写成「有 meta/ctrl 就开合」，
    // 用户按 ⌘K 会**同时**弹出搜索框并收起侧栏 —— 而两边都不报错。
    const w = mountShell()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
    await nextTick()
    expect(desktopState(w)).toBe('expanded')
  })

  it('图标条宽度类挂在 group 元素上（挂到内层卡片就白挂）', () => {
    // `data-[collapsible=icon]:w-(--sidebar-width-icon)` 是**自身**选择器，
    // `group-data-*` 只匹配子孙 —— 写到内层卡片上，flex 子项仍是 240px 宽，
    // 图标条会「中间一小撮图标、两边一大片空白」。折叠不报错，只是难看。
    const w = mountShell()
    const classes = w.get('[data-slot="sidebar"]').classes()
    expect(classes).toContain('w-(--sidebar-width)')
    expect(classes).toContain('data-[collapsible=icon]:w-(--sidebar-width-icon)')
  })
})

describe('SidebarRail（拉手：点开合 / 拖调宽，靠 3px 阈值分家）', () => {
  it('按下不挪就抬起 ⇒ 开合侧栏，并落盘', async () => {
    const w = mountShell()
    await clickRail(w)
    expect(desktopState(w)).toBe('collapsed')
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe('1')
  })

  it('挪 2px 仍算点击（阈值 3px 只决定「松手算不算开合」）', async () => {
    // ⚠️ 阈值**不**拦宽度：位移多少宽度就跟多少（1px 也跟）。拦掉的话拖动会
    //「先纹丝不动、过了 3px 突然跳一下」—— 手感是坏的，而上游也不这么写。
    // 阈值只回答一个问题：松手时这一下算「点击开合」还是「拖拽结束」。
    const w = mountShell()
    w.get('[data-sidebar="rail"]').element.dispatchEvent(
      pointerEvent('pointerdown', { pointerId: 3, clientX: 300 }),
    )
    window.dispatchEvent(pointerEvent('pointermove', { pointerId: 3, clientX: 302 }))
    window.dispatchEvent(pointerEvent('pointerup', { pointerId: 3, clientX: 302 }))
    await nextTick()

    expect(sidebarWidthVar(w)).toBe('242px')
    expect(desktopState(w)).toBe('collapsed')
  })

  it('拖 ≥3px ⇒ 改宽度，且**不**顺带开合侧栏', async () => {
    const w = mountShell()
    await dragRail(w, 80)
    expect(sidebarWidthVar(w)).toBe('320px')
    expect(desktopState(w)).toBe('expanded')
  })

  it('拖出上下限 ⇒ 夹回边界（拖多远都不会拖成 0 或无限宽）', async () => {
    const w = mountShell()
    await dragRail(w, -500, 4)
    expect(sidebarWidthVar(w)).toBe(`${SIDEBAR_WIDTH_MIN_PX}px`)
    await dragRail(w, 5000, 5)
    expect(sidebarWidthVar(w)).toBe(`${SIDEBAR_WIDTH_MAX_PX}px`)
  })

  it('宽度落盘有防抖：停手前不写，超过防抖窗口才写', async () => {
    const w = mountShell()
    await dragRail(w, 80)
    // 拖拽期间一帧能改几十次，每次都写 localStorage 就是每秒几十次同步 IO
    expect(localStorage.getItem(SIDEBAR_WIDTH_KEY)).toBeNull()

    await new Promise((r) => setTimeout(r, 200))
    expect(localStorage.getItem(SIDEBAR_WIDTH_KEY)).toBe('320')
  })

  it('拖到一半就卸载 ⇒ 补一次落盘（否则用户「拖完了但没生效」）', async () => {
    const w = mountShell()
    await dragRail(w, 60)
    expect(localStorage.getItem(SIDEBAR_WIDTH_KEY)).toBeNull()

    w.unmount()
    mounted.length = 0
    expect(localStorage.getItem(SIDEBAR_WIDTH_KEY)).toBe('300')
  })

  it('折叠态拖拽不改宽度，且这一下退化成「点击」⇒ 先展开', async () => {
    // 图标条只有 48px，在那儿拖动等于「一边改宽度一边看不见结果」，松手才发现变了。
    // 所以折叠态**不**认拖拽手势（`isResizeGesture = state === 'expanded'`）：
    // 位移被整个忽略，松手时按点击处理 —— 用户先展开，再在展开态拖。
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, '1')
    const w = mountShell()
    await dragRail(w, 120)

    expect(sidebarWidthVar(w)).toBe('240px')
    expect(desktopState(w)).toBe('expanded')
  })

  it('pointercancel 不算点击（系统接管手势时用户没打算开合）', async () => {
    const w = mountShell()
    w.get('[data-sidebar="rail"]').element.dispatchEvent(
      pointerEvent('pointerdown', { pointerId: 6, clientX: 300 }),
    )
    window.dispatchEvent(pointerEvent('pointercancel', { pointerId: 6, clientX: 300 }))
    await nextTick()
    expect(desktopState(w)).toBe('expanded')
  })

  it('松手后不留下 window 监听（否则整个会话都在跑空转的 handler）', async () => {
    const w = mountShell()
    const added: string[] = []
    const removed: string[] = []
    const origAdd = window.addEventListener.bind(window)
    const origRemove = window.removeEventListener.bind(window)
    window.addEventListener = ((type: string, ...rest: unknown[]) => {
      added.push(type)
      return (origAdd as (...a: unknown[]) => void)(type, ...rest)
    }) as typeof window.addEventListener
    window.removeEventListener = ((type: string, ...rest: unknown[]) => {
      removed.push(type)
      return (origRemove as (...a: unknown[]) => void)(type, ...rest)
    }) as typeof window.removeEventListener

    await dragRail(w, 40)

    window.addEventListener = origAdd as typeof window.addEventListener
    window.removeEventListener = origRemove as typeof window.removeEventListener

    const dragTypes = added.filter((t) => t === 'pointermove' || t === 'pointerup' || t === 'pointercancel')
    expect(dragTypes.length).toBeGreaterThan(0)
    // 每一次挂上都要有对应的摘掉
    for (const type of dragTypes) expect(removed).toContain(type)
    expect(removed.filter((t) => t === 'pointermove').length).toBe(dragTypes.filter((t) => t === 'pointermove').length)
  })
})

describe('该抽屉的视口变成抽屉（第 90 期：窄屏；第 108 期：再加手机横屏与平板）', () => {
  it('不再常驻：桌面那一块不渲染，点触发器才挂到 body 上', async () => {
    // 这个桩对**所有** query 返回同一个答案 ⇒ 这里只能证明「抽屉分支被选中了」。
    // 「什么设备算该抽屉」的那张表（390 触屏 / 844 触屏 / 844 鼠标 …）在
    // `lib/viewport.spec.ts` 里用会真评媒体查询的桩穷举，两处不要互相替代。
    const mm = installMatchMedia(true)

    const w = mountShell()
    expect(mm.queries).toContain(DRAWER_QUERY)

    // 侧栏常驻块没了 —— 这正是本期要修的原始缺陷（死占 240px，正文被挤成一列字）
    expect(w.find('[data-slot="sidebar"][data-state]').exists()).toBe(false)
    expect(document.body.querySelector('[data-mobile="true"]')).toBeNull()

    const trigger = w.get('[data-sidebar="trigger"]')
    expect(trigger.attributes('aria-expanded')).toBe('false')

    trigger.element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()
    await nextTick()

    // ⚠️ 必须挂在 body 上：内容卡片带 `backdrop-blur`，而 `backdrop-filter` 会让
    // `position: fixed` 的后代**以外壳为包含块**，抽屉会被裁掉（第 83 期踩过）。
    const panel = document.body.querySelector('[data-mobile="true"]')
    expect(panel, '窄屏下抽屉必须 Teleport 到 body').toBeTruthy()
    expect(document.body.querySelector('[data-slot="sheet-overlay"]')).toBeTruthy()
    expect(trigger.attributes('aria-expanded')).toBe('true')
  })

  it('⌘/Ctrl+B 在窄屏开的是抽屉，再按一次收起', async () => {
    installMatchMedia(true)
    const w = mountShell()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true }))
    await nextTick()
    await nextTick()
    expect(w.get('[data-sidebar="trigger"]').attributes('aria-expanded')).toBe('true')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true }))
    await nextTick()
    await nextTick()
    expect(w.get('[data-sidebar="trigger"]').attributes('aria-expanded')).toBe('false')
  })
})

describe('useSidebar 的兜底上下文', () => {
  it('没有 Provider 时单独挂触发器不抛异常（读屏与键盘仍可达）', () => {
    // 兜底**只为组件测试而存在**：应用里始终有真 Provider。没有它，单独 mount
    // 一个侧栏部件会直接抛「注入失败」，测试就只看到报错、看不到要断言的东西。
    const w = mount(SidebarTrigger)
    mounted.push(w)
    const btn = w.get('[data-sidebar="trigger"]')
    expect(btn.attributes('aria-expanded')).toBe('true')
    expect(btn.attributes('aria-label')).toBe('收起侧边栏')
  })
})
