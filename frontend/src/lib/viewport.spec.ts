import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'

import { NARROW_QUERY, useNarrowScreen, useNarrowScreenOnMount } from './viewport'

/**
 * 断点唯一真值源（第 90 期）。
 *
 * 本期之前 `NARROW_QUERY` 是 `lib/shelfRows.ts` 里的一份**私有**常量；外壳侧栏要
 * 用同一个断点时，最顺手的做法是再抄一份。抄了之后两处各自演化：改一处、漏一处，
 * **不会报错**，只是「书架行认为该横滑、侧栏认为还该常驻」这种谁都说不清的错位。
 * 所以这里先钉住「常量本身是什么」，再钉住两个消费函数都对它负责。
 *
 * 兜底语义同样是要钉的：读不到 `matchMedia` 的环境**按宽屏处理**。反过来（按窄屏）
 * 会把整个导航藏进一个打不开的抽屉里 —— 页面看着正常，只是左边空了。
 */

type ChangeListener = (event: { matches: boolean }) => void

const realMatchMedia = window.matchMedia
let teardown: (() => void) | null = null

interface FakeMedia {
  /** 当前是否命中窄屏 */
  state: { matches: boolean }
  /** 已注册的 change 监听器（用来断言「挂上 / 摘掉」） */
  listeners: Set<ChangeListener>
  /** 被问过的查询串（断言「用的就是那一个断点」） */
  queries: string[]
  change: (matches: boolean) => void
}

/**
 * 装一个可控的 `matchMedia`。
 *
 * 不用 happy-dom 自己的实现：它的命中结果跟着 `window.innerWidth` 走，而改建窗口
 * 尺寸**不会**触发它已建好的 MediaQueryList 的 `change`（真实的浏览器会）——
 * 于是「跟随变化」这条最该测的行为反而测不到。
 *
 * `available: false` 用**赋值 undefined**（而不是 `delete`）模拟环境不支持：
 * `window.matchMedia` 可能是原型上的方法，`delete` 删不掉，`typeof` 照样是 function。
 */
function installMatchMedia(initialMatches: boolean, available = true): FakeMedia {
  const listeners = new Set<ChangeListener>()
  const queries: string[] = []
  const state = { matches: initialMatches }

  if (!available) {
    window.matchMedia = undefined as unknown as typeof window.matchMedia
  } else {
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
        // 老式 API：@vueuse/core 走的是 addEventListener，一并给上免得不兼容
        addListener: (cb: ChangeListener) => listeners.add(cb),
        removeListener: (cb: ChangeListener) => listeners.delete(cb),
        dispatchEvent: () => false,
      }
    }) as unknown as typeof window.matchMedia
  }

  teardown = () => {
    window.matchMedia = realMatchMedia
  }

  return {
    state,
    listeners,
    queries,
    change(matches: boolean) {
      state.matches = matches
      for (const cb of [...listeners]) cb({ matches })
    },
  }
}

/** 只渲染「窄 / 宽」两个字的探针，让 ref 的值肉眼可断 */
function probeOf(useNarrow: () => { value: boolean }) {
  return defineComponent({
    setup() {
      const narrow = useNarrow()
      return () => h('span', narrow.value ? '窄' : '宽')
    },
  })
}

afterEach(() => {
  teardown?.()
  teardown = null
  document.body.innerHTML = ''
})

describe('NARROW_QUERY（外壳与书架行共用的断点）', () => {
  it('逐字是 639.98px —— 与 Tailwind 的 sm(640px) 严丝合缝', () => {
    // 写 640px 会让 640.00–640.98 这段同时命中「窄屏」与 `sm:` 两套样式
    expect(NARROW_QUERY).toBe('(max-width: 639.98px)')

    const px = Number(/max-width:\s*([\d.]+)px/.exec(NARROW_QUERY)?.[1])
    expect(Number.isFinite(px)).toBe(true)
    // 只钉「恰好贴住 640 的下沿」：写小了（比如 600）窄屏抽屉会提前出现，
    // 写大了（640 及以上）会和 `sm:` 重叠。上下各留一点余量，够拦住手滑。
    expect(px).toBeGreaterThan(600)
    expect(px).toBeLessThan(640)
  })

  it('**不是**上游的 768px（本项目 640–767 要继续两栏）', () => {
    // 上游 BookOrbit 用 md=768。本项目第 90 期明确不跟：768 档要与宽屏保持同样的
    // 两栏布局，把断点提上去等于让这一整段宽度**行为变差**。这条防的是
    // 「照上游对齐时顺手把数字也改了」——那种改动只看 diff 是看不出来的。
    expect(NARROW_QUERY).not.toContain('768')
    expect(NARROW_QUERY).not.toContain('767')
  })
})

describe('useNarrowScreen', () => {
  it('跟随 matchMedia：窄屏为真、宽屏为假，且问的就是那一个断点', async () => {
    const mm = installMatchMedia(false)
    const w = mount(probeOf(useNarrowScreen))
    expect(w.text()).toBe('宽')
    expect(mm.queries).toContain(NARROW_QUERY)

    mm.change(true)
    await nextTick()
    expect(w.text()).toBe('窄')
    w.unmount()
  })

  it('环境读不到 matchMedia 时按**宽屏**处理，且不抛异常', () => {
    // 兜底方向不能反：按窄屏兜底会把整个导航塞进一个打不开的抽屉 ——
    // 页面不报错，只是左边永远空着。
    const mm = installMatchMedia(false, false)
    const w = mount(probeOf(useNarrowScreen))
    expect(w.text()).toBe('宽')
    expect(mm.queries).toEqual([])
  })
})

describe('useNarrowScreenOnMount（既有书架行那条路）', () => {
  it('setup 阶段不碰 window，挂载时建 MQL、卸载时摘掉监听', async () => {
    const mm = installMatchMedia(false)

    // 「setup 里没碰 window」必须在 setup **当场**采样：`mount()` 是一次性跑完
    // setup + onMounted 的，挂载后再断言就分不出是哪一段调用的了。
    let queriesAtSetup = -1
    const w2 = mount(
      defineComponent({
        setup() {
          const narrow = useNarrowScreenOnMount()
          queriesAtSetup = mm.queries.length
          return () => h('span', narrow.value ? '窄' : '宽')
        },
      }),
    )

    expect(queriesAtSetup).toBe(0)
    expect(mm.queries.length).toBe(1)
    expect(mm.listeners.size).toBe(1)
    expect(w2.text()).toBe('宽')

    mm.change(true)
    await nextTick()
    expect(w2.text()).toBe('窄')

    // 卸载必须摘干净：不摘的话每挂一次留一个监听器，且 update 里还攥着已卸载的 ref
    w2.unmount()
    expect(mm.listeners.size).toBe(0)
  })

  it('判据与 useNarrowScreen 完全一致（同一个常量、同一个兜底）', () => {
    // 两个函数各自只做一件事（一个用 @vueuse 的 useMediaQuery，一个手写 MQL），
    // 但问的必须是同一个断点 —— 分别断言一次查询串，防止其中一处被改成别的值。
    const mm = installMatchMedia(false)
    const w = mount(probeOf(useNarrowScreenOnMount))
    expect(mm.queries).toEqual([NARROW_QUERY])
    w.unmount()
  })
})
