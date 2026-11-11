import { describe, expect, it } from 'vitest'

import { isFormControlTarget } from './keyboard'

function evt(target: unknown): KeyboardEvent {
  return { target } as unknown as KeyboardEvent
}

describe('isFormControlTarget', () => {
  it('输入类控件返回 true（方向键属于控件自己）', () => {
    for (const tag of ['INPUT', 'TEXTAREA', 'SELECT']) {
      expect(isFormControlTarget(evt({ tagName: tag }))).toBe(true)
    }
    expect(isFormControlTarget(evt({ tagName: 'DIV', isContentEditable: true }))).toBe(true)
  })

  it('普通元素返回 false（阅读器照常翻页）', () => {
    for (const tag of ['DIV', 'BUTTON', 'BODY']) {
      expect(isFormControlTarget(evt({ tagName: tag }))).toBe(false)
    }
    expect(isFormControlTarget(evt(null))).toBe(false)
    expect(isFormControlTarget(evt({}))).toBe(false)
  })
})
