import { afterEach, describe, expect, it, vi } from 'vitest'

/**
 * 书卡 ⋮ 菜单的状态模块（第 64 期）。
 *
 * 这个模块只有三件事，而三件事写错**都不会报错**：
 *
 * 1. **同时只开一个** —— 写错的症状是两个面板一起亮，界面看起来只是「有点怪」；
 * 2. **只挂一份 document 监听** —— 写错的症状是「每张卡挂一份」（一屏 60 张就是 60 份），
 *    功能完全正常，只有内存与每次点击的处理器数量悄悄涨，**没有任何可见症状**；
 * 3. **点面板内部不关** —— 写错的症状是点菜单项时面板先关掉、动作没执行，
 *    用户读成「点了没反应」。
 */
async function freshMenu(): Promise<typeof import('@/lib/bookMenu')> {
  // `openKey` 与 `installed` 都是**模块级**单例，会跨用例残留 ⇒ 每个用例都拿一份全新的
  // 模块实例（动态 import 配 `vi.resetModules()`）。不这么做的话，「只挂一份监听」
  // 那条会因为「上一个用例已经挂过了」而永远看着是绿的。
  vi.resetModules()
  return await import('@/lib/bookMenu')
}

function clickOn(el: Element | null): void {
  el?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('bookMenu', () => {
  it('toggle：开 → 换一个（前一个自动关）→ 再点关掉', async () => {
    const { useBookMenu } = await freshMenu()
    const menu = useBookMenu()
    expect(menu.openKey.value).toBeNull()
    expect(menu.isOpen('a')).toBe(false)

    menu.toggle('a')
    expect(menu.openKey.value).toBe('a')
    expect(menu.isOpen('a')).toBe(true)
    expect(menu.isOpen('b')).toBe(false)

    // 开第二个会关掉第一个 —— 这不是一条额外规则，是「状态只有一个 key」带来的结果
    menu.toggle('b')
    expect(menu.openKey.value).toBe('b')

    menu.toggle('b')
    expect(menu.openKey.value).toBeNull()
  })

  it('toggle 三十次只挂一份监听，且挂完之后依然管用', async () => {
    const spy = vi.spyOn(document, 'addEventListener')
    const { useBookMenu } = await freshMenu()
    const menu = useBookMenu()

    for (let i = 0; i < 30; i += 1) menu.toggle(`k${i}`)
    menu.close()

    const names = spy.mock.calls.map((c) => String(c[0]))
    expect(names.filter((n) => n === 'click')).toHaveLength(1)
    expect(names.filter((n) => n === 'keydown')).toHaveLength(1)

    // ⚠️ 「只挂了一份」也可能是「挂了一份永远不管用的」⇒ 还得证明那一份真的在干活
    menu.toggle('x')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(menu.openKey.value).toBeNull()
  })

  it('Escape 关掉当前面板；没开菜单时按它什么也不发生', async () => {
    const { useBookMenu } = await freshMenu()
    const menu = useBookMenu()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(menu.openKey.value).toBeNull()

    menu.toggle('a')
    // 别的键不该关（不然打字都会关菜单）
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }))
    expect(menu.openKey.value).toBe('a')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(menu.openKey.value).toBeNull()
  })

  it('点面板 / 触发器内部不关，点别处才关', async () => {
    const { useBookMenu } = await freshMenu()
    const menu = useBookMenu()
    // 面板是 Teleport 到 body 的，与触发器不在同一棵 DOM 子树里 —— 所以判据只能是
    // 属性（`closest`），不能是 `contains`。
    // ⚠️ 这里**照抄真实标记**：面板上那两个属性都要有 —— 只写 `data-book-menu-panel`
    // 的话放行判据匹配不上，点菜单项会先关面板（正是这条用例要防的那种错）。
    document.body.innerHTML = `
      <div data-book-menu><button id="trigger">⋮</button></div>
      <div data-book-menu data-book-menu-panel id="panel"><button id="item">删除</button></div>
      <div id="outside">别处</div>`

    menu.toggle('a')
    clickOn(document.getElementById('trigger'))
    expect(menu.openKey.value).toBe('a')

    clickOn(document.getElementById('item'))
    expect(menu.openKey.value).toBe('a')

    clickOn(document.getElementById('outside'))
    expect(menu.openKey.value).toBeNull()
  })

  it('close() 关掉；它本身不需要先开过菜单（关一个没开的菜单不该报错）', async () => {
    const { useBookMenu } = await freshMenu()
    const menu = useBookMenu()
    expect(() => menu.close()).not.toThrow()
    expect(menu.openKey.value).toBeNull()

    menu.toggle('a')
    menu.close()
    expect(menu.openKey.value).toBeNull()
  })
})
