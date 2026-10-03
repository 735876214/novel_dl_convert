import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'

import { Sheet, SheetContent } from '.'

/**
 * 抽屉（第 90 期，移植 BookOrbit 的 `ui/sheet`，基座是 reka-ui 的 Dialog）。
 *
 * 它是窄屏侧栏的载体，所以这里的每一条都对应一个**不会报错**的失效：
 *   · 没 Teleport 到 body ⇒ 抽屉被外壳的 `backdrop-blur` 裁掉一半（第 83 期踩过），
 *     页面上只像「侧栏没打开」或者「打开了一半」；
 *   · 少了 `role="dialog"` / `aria-modal` ⇒ 读屏用户完全不知道浮层存在；
 *   · Esc / 点遮罩关不掉 ⇒ 用户被锁在抽屉里，只能刷新；
 *   · 遮罩用 `--foreground` 调 ⇒ 深色主题下是一层**浅雾**，盖不住底下的内容；
 *   · `hideClose` 失效 ⇒ 侧栏抽屉右上角多出一个与内容打架的关闭按钮。
 */

function pointerDown(target: EventTarget): void {
  const event = new Event('pointerdown', { bubbles: true, cancelable: true })
  Object.assign(event, { button: 0, pointerId: 1, clientX: 10, clientY: 10, pointerType: 'mouse' })
  target.dispatchEvent(event)
}

let mounted: VueWrapper[] = []

function mountSheet(props: { side?: 'right' | 'left' | 'top' | 'bottom'; hideClose?: boolean } = {}) {
  const open = ref(true)
  const w = mount(
    defineComponent({
      setup() {
        return () =>
          h(
            Sheet,
            {
              open: open.value,
              'onUpdate:open': (value: boolean) => {
                open.value = value
              },
            },
            {
              default: () =>
                h(SheetContent, { side: props.side ?? 'right', hideClose: props.hideClose }, {
                  default: () => h('p', '抽屉内容'),
                }),
            },
          )
      },
    }),
    { attachTo: document.body },
  )
  mounted.push(w)
  return { w, open }
}

/**
 * 等 reka 那两处**异步**落定。它们都不是同步的，少等一步就会把「关得掉」误判成
 * 「关不掉」—— 而且误判的方向是「以为功能坏了」，最难查：
 *
 *   1. 点击外部的 `pointerdown` 监听器：`usePointerDownOutside` 在 `watchEffect`
 *      （微任务里才跑）内部**再排一个 `setTimeout(0)`** 才挂到 document 上，
 *      而且要避开「挂载这一下本身就是 pointerdown 触发的」⇒ 要等**两个宏任务**；
 *   2. 真正的卸载：`usePresence` 的 watch 里有一次 `await nextTick()`，dispatch 完
 *      还要再等组件重渲染 ⇒ DOM 消失比状态变化慢两拍。
 */
async function settle(): Promise<void> {
  for (let i = 0; i < 3; i += 1) {
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()
    await nextTick()
  }
}

function panel(): HTMLElement | null {
  return document.body.querySelector<HTMLElement>('[data-slot="sheet-content"]')
}

function overlay(): HTMLElement | null {
  return document.body.querySelector<HTMLElement>('[data-slot="sheet-overlay"]')
}

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  mounted = []
  document.body.innerHTML = ''
})

describe('SheetContent 的挂载位置', () => {
  it('内容 Teleport 到 body，**不在**挂载点内部', async () => {
    // ⚠️ 这是本文件最要紧的一条：外壳的内容卡片带 `backdrop-blur`，而
    // `backdrop-filter` 会让 `position: fixed` 的后代**以外壳为包含块** ——
    // 挂在挂载点里，`inset-y-0` 量的是卡片而不是视口，抽屉会被裁掉一半。
    const { w } = mountSheet()
    await nextTick()

    expect(panel(), '抽屉必须挂在 body 上').toBeTruthy()
    // 反面：挂载点自己的子树里**不该**有抽屉（有就说明 Portal 没生效）
    expect(w.find('[data-slot="sheet-content"]').exists()).toBe(false)
  })

  it('打开时底下整页对读屏隐藏，且抽屉自己是 role=dialog', async () => {
    // 「模态」在这个实现里**不是靠 `aria-modal`**（reka 不写这个属性），
    // 而是靠 `useHideOthers`：把 body 下其余的子树统统标成 `aria-hidden` ——
    // 读屏用户不会跑到浮层背后的页面上去。这一条失效时没有任何可见征兆，
    // 只有读屏用户会莫名其妙地「读到抽屉后面的东西」。
    mountSheet()
    await nextTick()
    await settle()

    expect(panel()?.getAttribute('role')).toBe('dialog')
    expect(
      document.body.querySelector('[aria-hidden="true"]'),
      '抽屉打开时，底下那一层必须对读屏隐藏',
    ).toBeTruthy()
  })

  it('遮罩走 --scrim，不是拿 --foreground 调出来的', async () => {
    mountSheet()
    await nextTick()

    // 深色主题下 `--foreground` 是**近白**，拿它做纱会变成一层浅雾：
    // 底下的内容照常看得见，用户以为「遮罩没生效」。
    expect(overlay()?.className).toContain('bg-scrim')
  })
})

describe('关闭路径（用户必须走得掉）', () => {
  it('Esc 关闭', async () => {
    const { open } = mountSheet()
    await settle()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await settle()

    expect(open.value).toBe(false)
    expect(panel()).toBeNull()
  })

  it('点抽屉外面（遮罩）关闭', async () => {
    const { open } = mountSheet()
    await settle()

    const scrim = overlay()
    expect(scrim, '遮罩必须与抽屉一起渲染').toBeTruthy()

    pointerDown(scrim!)
    await settle()

    expect(open.value).toBe(false)
    expect(panel()).toBeNull()
  })

  it('内置关闭按钮：默认渲染、可点、带读屏名', async () => {
    const { open } = mountSheet()
    await settle()

    const close = panel()?.querySelector<HTMLElement>('button')
    expect(close, '默认必须有一个关闭按钮').toBeTruthy()
    // 读屏名（`sr-only` 的「关闭」）不能省：光一个 ✕ 图标，读屏只会念「按钮」
    expect(panel()?.textContent ?? '').toContain('关闭')

    close!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await settle()
    expect(open.value).toBe(false)
  })

  it('hideClose ⇒ 一个关闭按钮都不留（侧栏抽屉自带头部动作）', async () => {
    mountSheet({ hideClose: true })
    await settle()

    expect(panel()?.textContent ?? '').not.toContain('关闭')
    expect(panel()?.querySelector('button')).toBeNull()
  })
})

describe('侧别决定滑入方向', () => {
  it('side=left 从左滑入、side=right 从右滑入', async () => {
    // 方向写错不会报错：抽屉照样打开，只是**从另一边**滑出来盖住内容
    const { w } = mountSheet({ side: 'left' })
    await nextTick()
    expect(panel()?.className).toContain('nf-slide-in-left')
    expect(panel()?.className).not.toContain('nf-slide-in-right')
    w.unmount()
    mounted = []
    document.body.innerHTML = ''

    mountSheet({ side: 'right' })
    await nextTick()
    expect(panel()?.className).toContain('nf-slide-in-right')
  })
})
