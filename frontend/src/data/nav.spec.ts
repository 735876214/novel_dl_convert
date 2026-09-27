import { describe, expect, it } from 'vitest'

import { ICONS } from '@/lib/icons'

import { NAV_GROUPS } from './nav'

/**
 * 第 65 期：侧栏结构（导航改造）。
 *
 * 这一期把七个入口（任务中心 / 工具 / 数据统计 / 阅读记录 / 阅读活动 /
 * 通知中心 / 成就）从侧栏搬到了顶栏，并新增「收书目录」一级项。
 *
 * 三种走样都是**静默**的：少一项 ⇒ 某个入口凭空消失；多一项 ⇒ 同一页出现两个
 * 入口（用户按哪条都能走，于是没人发现多了一条）；图标名拼错 ⇒ `iconPath()` 对
 * 未知键返回空串，渲染出一个**看不见的空 `<svg>`**，不报错、不告警。
 */
describe('data/nav', () => {
  /** 主导航组（title 为 null 的那一组） */
  const main = NAV_GROUPS.find((g) => g.title === null)

  /** 侧栏全部条目的 id（含各分组） */
  const allIds = (): string[] => NAV_GROUPS.flatMap((g) => g.items.map((i) => i.id))

  it('主导航只剩三项：仪表盘 / 探索发现 / 收书目录', () => {
    expect(main, '找不到 title 为 null 的主导航组').toBeTruthy()
    expect(main!.items.map((i) => i.id)).toEqual(['dashboard', 'search', 'book-dock'])
  })

  it('收书目录紧跟探索发现，且是同一组里的一级项', () => {
    const ids = main!.items.map((i) => i.id)
    expect(ids.indexOf('book-dock')).toBe(ids.indexOf('search') + 1)
  })

  it('七个入口不在任何分组里了', () => {
    // 用户口径是「只留顶栏」—— 侧栏再出现这七项就是同一页两个入口。
    // 逐个钉而不是只钉 tasks：照上游截图往回补时最容易补的是「工具」和「成就」。
    const gone = [
      'tasks',
      'tools',
      'stats',
      'log',
      'reading-activity',
      'notify',
      'achievements',
    ]
    for (const id of gone) {
      expect(allIds(), `${id} 回到了侧栏`).not.toContain(id)
    }
  })

  it('留下的六项（浏览组 / 帮助组）一个没动', () => {
    // 本期只搬用户点名的那七项。这条是反向哨兵：改侧栏时顺手删多了会在这里红。
    for (const id of ['browse', 'authors', 'series', 'annotations', 'docs', 'whatsnew', 'about']) {
      expect(allIds(), `${id} 不该被删`).toContain(id)
    }
  })

  it('每个导航项的图标名都在 ICONS 表里', () => {
    // ⚠️ 侧栏是 `<Icon :name="item.icon">`（**动态绑定**），静态扫模板字面量扫不到 ——
    // 而 `iconPath()` 对未知键静默返回空串，拼错就是渲染一个看不见的空 svg。
    // 所以这条判据只能在这里、对着真实数据跑一遍。
    for (const g of NAV_GROUPS) {
      for (const it of g.items) {
        expect(Object.keys(ICONS), `${g.title ?? '主导航'} / ${it.label} 的图标 ${it.icon}`).toContain(
          it.icon,
        )
      }
    }
  })
})
