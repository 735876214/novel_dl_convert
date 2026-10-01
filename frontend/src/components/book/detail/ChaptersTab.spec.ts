import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import ChaptersTab from '@/components/book/detail/ChaptersTab.vue'
import type { BookVolume } from '@/lib/api'

/**
 * 详情页「目录」标签的分组渲染。
 *
 * 三条都是**静默**失效（不改代码就没人发现）：空卷名回落成「目录」（看着像重复标题）、
 * 无编号条目仍显示序号（章号对不上）、段 key 用段名导致两段互相串折叠。
 */
const VOLUMES: BookVolume[] = [
  { volume: '', kind: 'front', chapters: [{ title: '楔子', index: 0 }] },
  {
    volume: '第一卷',
    chapters: [
      { title: '第一章', index: 1, num: 1 },
      { title: '第二章', index: 2, num: 2 },
    ],
  },
  { volume: '', kind: 'back', chapters: [{ title: '番外', index: 3 }] },
]

/** 某一行的整行文本（去掉空白）：用来断言「序号有没有渲染」 */
function rowTextOf(wrapper: ReturnType<typeof mount>, title: string): string {
  const span = wrapper.findAll('span').find((s) => s.text() === title)
  expect(span, `没找到标题为「${title}」的行`).toBeTruthy()
  return (span!.element.parentElement!.textContent || '').replace(/\s+/g, '')
}

describe('ChaptersTab：按段分组渲染', () => {
  it('段名用 卷前 / 卷名 / 卷尾 —— 不再把无名段回落成「目录」', () => {
    const w = mount(ChaptersTab, { props: { chapters: VOLUMES } })
    const text = w.text()
    expect(text).toContain('卷前')
    expect(text).toContain('第一卷')
    expect(text).toContain('卷尾')
    expect(text).not.toContain('目录')
  })

  it('无编号条目不渲染序号，普通章照旧显示段内序号', () => {
    const w = mount(ChaptersTab, { props: { chapters: VOLUMES } })
    expect(rowTextOf(w, '楔子')).toBe('楔子')
    expect(rowTextOf(w, '第一章')).toBe('1第一章')
    expect(rowTextOf(w, '番外')).toBe('番外')
  })

  it('点段头折叠该段：段内容被 v-show 收起，再点展开', async () => {
    // ⚠️ 断言必须落在 `v-show` 的机制上（面板 `style.display`），**不要用 `isVisible()`**：
    // happy-dom 不把祖先的内联 `display:none` 级联进计算样式，`isVisible()` 会一路报 true，
    // 于是「折叠根本没生效」这个真缺陷被静默放过（本轮实测踩过）。
    const w = mount(ChaptersTab, { props: { chapters: VOLUMES } })
    const hiddenCount = () =>
      w.findAll('div.border-t').filter((p) => p.element.style.display === 'none').length
    expect(w.findAll('div.border-t')).toHaveLength(3)      // 三段各一个面板
    expect(hiddenCount()).toBe(0)

    const head = w.findAll('button').find((b) => b.text().includes('第一卷'))
    expect(head).toBeTruthy()
    await head!.trigger('click')
    expect(hiddenCount()).toBe(1)                          // 只有第一卷被收起
    await head!.trigger('click')
    expect(hiddenCount()).toBe(0)
  })

  it('搜索只切行显隐：命中为空时给空状态，命中非空时按段保留', async () => {
    const w = mount(ChaptersTab, { props: { chapters: VOLUMES } })
    const input = w.find('input')
    await input.setValue('第二')
    expect(w.text()).toContain('第二章')
    expect(w.text()).not.toContain('第一章')
    await input.setValue('不存在的东西')
    expect(w.text()).toContain('没有匹配的章节')
  })
})
