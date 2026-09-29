import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import Switch from '@/components/ui/Switch.vue'

/**
 * 共享开关的契约（第 70 期）。
 *
 * 这些断言守的是**「统一」本身**：尺寸/圆角/配色/过渡/禁用一旦被人手改回去，
 * 界面上不会报错 —— 只会「某一个开关看起来跟别的不一样」，靠眼睛很难发现。
 * 所以把口径钉在这里：谁改都会红。
 */
function cls(el: { attributes: (n: string) => string | undefined }): string {
  return el.attributes('class') ?? ''
}

describe('Switch（共享开关胶囊）', () => {
  it('是原生 button + role=switch：空格/回车切换由浏览器保证，不必自己补键盘处理', () => {
    const w = mount(Switch, { props: { modelValue: false } })
    const btn = w.find('button')
    expect(btn.attributes('type')).toBe('button')
    expect(btn.attributes('role')).toBe('switch')
    // 不该有 tabindex：原生按钮本来就在焦点序列里
    expect(btn.attributes('tabindex')).toBeUndefined()
  })

  it('关：aria-checked=false、轨道中性色、滑块靠左', () => {
    const w = mount(Switch, { props: { modelValue: false } })
    const btn = w.find('button')
    expect(btn.attributes('aria-checked')).toBe('false')
    expect(cls(btn)).toContain('bg-muted')
    expect(cls(btn)).not.toContain('bg-primary')
    expect(cls(w.find('span'))).toContain('translate-x-[2px]')
  })

  it('开：aria-checked=true、轨道主题色、滑块靠右', () => {
    const w = mount(Switch, { props: { modelValue: true } })
    const btn = w.find('button')
    expect(btn.attributes('aria-checked')).toBe('true')
    expect(cls(btn)).toContain('bg-primary')
    expect(cls(w.find('span'))).toContain('translate-x-[16px]')
  })

  it('点击把值取反交回上层（不自己改状态）', async () => {
    const off = mount(Switch, { props: { modelValue: false } })
    await off.find('button').trigger('click')
    expect(off.emitted('update:modelValue')).toEqual([[true]])

    const on = mount(Switch, { props: { modelValue: true } })
    await on.find('button').trigger('click')
    expect(on.emitted('update:modelValue')).toEqual([[false]])
  })

  it('轨道只用主题变量；圆点是唯一的写死白色（刻意，配半透明细边）', () => {
    const w = mount(Switch, { props: { modelValue: true } })
    // 轨道随主题走（开 = 主题色），不写死
    expect(cls(w.find('button'))).toContain('bg-primary')
    // 不许出现写死的色值（十六进制 / rgb / oklch）——白色只用 Tailwind 关键字 `bg-white`
    const html = w.html()
    expect(html).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(html).not.toMatch(/\brgb(a)?\(/)
    expect(html).not.toMatch(/\boklch\(/)
    // 圆点刻意固定白色（用户口径：与主题色不一致），不再是随主题的 `bg-card`
    const thumb = cls(w.find('span'))
    expect(thumb).toContain('bg-white')
    expect(thumb).not.toContain('bg-card')
  })

  it('尺寸与过渡是唯一口径（改动会立刻红，避免又长出一个「大胶囊」）', () => {
    const w = mount(Switch, { props: { modelValue: true } })
    const btn = cls(w.find('button'))
    expect(btn).toContain('h-[18px]')
    expect(btn).toContain('w-8')
    expect(btn).toContain('rounded-full')
    expect(btn).toContain('transition-colors')
    // 滑块：尺寸 + 位移过渡
    const thumb = cls(w.find('span'))
    expect(thumb).toContain('h-[14px]')
    expect(thumb).toContain('w-[14px]')
    expect(thumb).toContain('rounded-full')
    expect(thumb).toContain('transition-transform')
    // 细边框：白色圆点在浅色轨道上对比偏弱，没有这道边轮廓几乎看不出来
    // ⇒ 刻意用**半透明黑**（不随主题变）勾边，深浅两套主题里都成立
    expect(thumb).toContain('border-black/15')
    expect(thumb).toContain('bg-white')
  })

  it('disabled：带原生 disabled 与禁用光标/降透明；禁用态样式只有这一处定义', () => {
    const w = mount(Switch, { props: { modelValue: false, disabled: true } })
    const btn = w.find('button')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(cls(btn)).toContain('disabled:cursor-not-allowed')
    expect(cls(btn)).toContain('disabled:opacity-40')
  })

  it('title 与 aria-label 可选：不传就不渲染，传了原样用', () => {
    const bare = mount(Switch, { props: { modelValue: false } })
    expect(bare.find('button').attributes('title')).toBeUndefined()
    expect(bare.find('button').attributes('aria-label')).toBeUndefined()

    const named = mount(Switch, {
      props: { modelValue: false, title: '停用', ariaLabel: '启用该来源' },
    })
    expect(named.find('button').attributes('title')).toBe('停用')
    expect(named.find('button').attributes('aria-label')).toBe('启用该来源')
  })
})
