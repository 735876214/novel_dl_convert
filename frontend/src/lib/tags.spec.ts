import { describe, expect, it } from 'vitest'

import { parseTokenList } from './tags'

/**
 * 第 157 期：题材 / 演播者这类多值输入的唯一解析。
 *
 * 单书编辑与批量编辑共用它；分开写时「换个分隔符」会让同一段文字在两处拆成不同结果，
 * 而且不会报错 —— 只会在书目里多出一堆近义标签。
 */
describe('parseTokenList', () => {
  it('按中文顿号 / 中英文逗号拆分，去空白与空项', () => {
    expect(parseTokenList('科幻、 经典 , 太空，  ')).toEqual(['科幻', '经典', '太空'])
  })

  it('空值返回空数组（不产生空标签）', () => {
    expect(parseTokenList('')).toEqual([])
    expect(parseTokenList(null)).toEqual([])
  })
})
