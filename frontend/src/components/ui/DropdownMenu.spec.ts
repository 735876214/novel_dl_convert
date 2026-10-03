import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import DropdownMenu from '@/components/ui/DropdownMenu.vue'

/**
 * 浮层菜单壳的**键盘契约**（第 91 期）。
 *
 * 这些用例是「真按 Tab 走一遍」查出来的缺陷的回归钉 —— 在这个组件补键盘之前，
 * 面板 `Teleport` 到 `<body>` 末尾 ⇒ Tab 序排在整个页面之后，**键盘根本够不着**；
 * `Esc` 也完全没人监听。第 64 期这不致命（书卡的 ⋮ 只是便捷项），第 91 期把窄屏
 * 顶栏的 7 个入口（含「设置」）**只**放进这个浮层之后，它就变成了硬缺陷。
 *
 * ⚠️ 面板是 `Teleport` 到 `document.body` 的 ⇒ 断言一律查 `document.body`，
 * `wrapper.find(...)` 找不到它。`attachTo: document.body` 也不能省：不挂载到文档里，
 * `document.activeElement` 永远回不到这些节点，`focus()` 的断言会全假绿。
 */
const mounted: VueWrapper[] = []

function mountMenu() {
  const w = mount(
    {
      components: { DropdownMenu },
      data: () => ({ open: false }),
      template: `
        <DropdownMenu :open="open" @toggle="open = !open" @close="open = false">
          <template #trigger>
            <button type="button" data-trigger>打开</button>
          </template>
          <template #panel>
            <button type="button" role="menuitem" data-a>第一项</button>
            <button type="button" role="menuitem" data-b>第二项</button>
            <button type="button" role="menuitemcheckbox" data-c>第三项（复选框）</button>
          </template>
        </DropdownMenu>`,
    },
    { attachTo: document.body },
  )
  mounted.push(w)
  return w
}

const panel = (): Element | null => document.body.querySelector('[data-book-menu-panel]')
const items = (): HTMLElement[] =>
  Array.from(document.body.querySelectorAll<HTMLElement>('[role^="menuitem"]'))
const triggerBtn = (): HTMLElement => document.body.querySelector<HTMLElement>('[data-trigger]')!
const active = (): HTMLElement | null => document.activeElement as HTMLElement | null

/** 开面板：走真实点击（触发器上的 `@click.stop` 只在事件冒泡路径上才生效）。 */
async function open(w: VueWrapper): Promise<void> {
  await w.find('[data-book-menu]').trigger('click')
  await w.vm.$nextTick()
}

/**
 * 按一个键并**等一次渲染**。
 *
 * 监听器绑在 `window`（派给面板收不到），而且 `emit('close')` 只是让父组件改了
 * `open` —— Vue 的渲染是异步的，不等这一拍，`v-if` 还没把面板摘掉，断言会假红。
 */
async function press(w: VueWrapper, key: string): Promise<void> {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  await w.vm.$nextTick()
}

type Vm = { open: boolean }
const vm = (w: VueWrapper): Vm => w.vm as unknown as Vm

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
})

describe('DropdownMenu 键盘可达（第 91 期）', () => {
  it('打开后焦点自动落在第一项（否则 Tab 序里它在整页之后）', async () => {
    const w = mountMenu()
    expect(panel(), '面板还没开就不该有面板节点').toBeNull()

    await open(w)

    expect(panel(), '面板没打开，请同步本测试').not.toBeNull()
    expect(
      active(),
      '打开后焦点没进面板 ⇒ 键盘用户要按遍整页才能摸到菜单项',
    ).toBe(items()[0])
  })

  it('三种 menuitem 角色都算菜单项（menuitemcheckbox 也要能聚焦）', async () => {
    const w = mountMenu()
    await open(w)
    expect(items()).toHaveLength(3)

    await press(w, 'ArrowDown')
    expect(active()).toBe(items()[1])
    await press(w, 'ArrowDown')
    expect(active(), 'menuitemcheckbox 被漏掉了').toBe(items()[2])
  })

  it('上下键环绕', async () => {
    const w = mountMenu()
    await open(w)

    await press(w, 'ArrowUp')
    expect(active(), '在第一项上按上键应回卷到最后一项').toBe(items()[2])

    await press(w, 'ArrowDown')
    expect(active(), '在最后一项按下键应回卷到第一项').toBe(items()[0])
  })

  it('Esc 关闭浮层，并把焦点还给触发器', async () => {
    const w = mountMenu()
    await open(w)
    expect(active()).toBe(items()[0])

    await press(w, 'Escape')

    expect(panel(), 'Esc 没能关掉浮层').toBeNull()
    expect(
      active(),
      'Esc 之后焦点掉到 body ⇒ 键盘用户丢了位置，得从头 Tab',
    ).toBe(triggerBtn())
  })

  it('Tab 关闭浮层并把焦点交还触发器（不把人留在页面之外）', async () => {
    const w = mountMenu()
    await open(w)

    await press(w, 'Tab')

    expect(panel(), 'Tab 应该按 ARIA menu 惯例收起浮层').toBeNull()
    // 面板在 body 末尾：放任原生 Tab 会把焦点送到页面之外，所以这里明确交还触发器
    expect(
      active(),
      'Tab 关掉面板后焦点应回到触发器，再按一次 Tab 才继续往前走',
    ).toBe(triggerBtn())
  })

  it('点别处导致关闭时不抢焦点', async () => {
    const w = mountMenu()
    await open(w)

    // 模拟「关闭时焦点已经不在面板里」：焦点挪到触发器上再关
    triggerBtn().focus()
    vm(w).open = false
    await w.vm.$nextTick()

    expect(panel()).toBeNull()
    expect(active(), '不是面板里的焦点就不该被抢回来').toBe(triggerBtn())
  })
})
