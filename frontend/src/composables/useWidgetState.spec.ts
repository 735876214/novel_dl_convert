import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import { useWidgetState, widgetStateOf } from './useWidgetState'

/** 部件数据态的唯一真值源（第 82 期）：优先级 loading > error > empty > ready */
describe('useWidgetState', () => {
  it('widgetStateOf：优先级与四态', () => {
    expect(widgetStateOf({})).toBe('ready')
    expect(widgetStateOf({ empty: true })).toBe('empty')
    expect(widgetStateOf({ error: 'x', empty: true })).toBe('error')
    expect(widgetStateOf({ loading: true, error: 'x' })).toBe('loading')
    expect(widgetStateOf({ loading: false, error: '' })).toBe('ready')
  })

  it('getter 形式保持响应性（响应源变化后重算）', () => {
    // ⚠️ 响应性来自 getter 里读到的**响应式**源（store 字段 / ref）；
    // 普通变量不是响应源 —— 这里用 ref 模拟 store 字段。
    const loading = ref(true)
    const state = useWidgetState(() => ({ loading: loading.value }))
    expect(state.value).toBe('loading')
    loading.value = false
    expect(state.value).toBe('ready')
  })

  it('error 既接受字符串也接受布尔（library 无 error 字段、批注部件是本地 ref）', () => {
    expect(widgetStateOf({ error: true })).toBe('error')
    expect(widgetStateOf({ error: false, empty: true })).toBe('empty')
  })
})
