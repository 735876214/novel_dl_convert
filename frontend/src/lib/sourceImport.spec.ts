import { describe, expect, it } from 'vitest'

import {
  countsLine,
  formatLabel,
  importOutcome,
  importSummary,
  needsAttention,
  type ImportResult,
} from '@/lib/sourceImport'

/**
 * 本模块存在的唯一理由就是**第 94 期那个静默失败**：
 * 旧代码 `已添加 ${r.added ?? 0} 个书源` 在 `added: []` 时渲染成「已添加  个书源」，
 * 用户看到的结论是「导入没反应」。下面第一条用例就是把这个缺陷钉死。
 */
describe('lib/sourceImport', () => {
  it('被拒时绝不回「已添加 N 个」这种假成功 —— 必须逐档报出真实计数', () => {
    // 这是当年那条接口的真实返回形状：200 + added:[] + errors 非空
    const r: ImportResult = {
      added: [],
      errors: [{ name: 'lg-x.com', error: '缺少 search.url', instead: '请在手动表单里补齐' }],
      counts: { new: 0, unsupported: 1 },
      format: 'legado-3',
    }
    const text = importOutcome(r)
    expect(text).not.toContain('已添加')
    expect(text).toContain('新增 0')
    expect(text).toContain('不可执行 1')
    expect(text).toContain('去「书源工具」看原因')
    // 后端给的人话原因**原样**带出来，前端不另写一套解释
    expect(text).toContain('缺少 search.url')
    expect(text).toContain('格式：Legado / 阅读书源')
  })

  it('`added` 是名字数组（不是数字）—— 类型修正后不再有 `?? 0` 渲染成空串的空间', () => {
    const r: ImportResult = { added: ['a', 'b'], counts: { new: 2 }, format: 'nf-native' }
    expect(importOutcome(r)).toBe(
      '导入完成（格式：本项目书源规则）：新增 2 · 更新 0 · 重复 0 · 跳过 0 · 冲突 0 · 不可执行 0',
    )
  })

  it('零值也照打：用户要能从这一行区分「空文件 / 全重复 / 全跑不了」', () => {
    expect(countsLine({})).toBe('新增 0 · 更新 0 · 重复 0 · 跳过 0 · 冲突 0 · 不可执行 0')
    expect(countsLine({ duplicate: 1537 })).toContain('重复 1537')
  })

  it('冲突与不可执行都要人看一眼；`skipped`（用户自己的选择）不算', () => {
    expect(needsAttention({ conflict: 2, unsupported: 3, skipped: 9 })).toBe(5)
    expect(needsAttention({ skipped: 9 })).toBe(0)
    // 有冲突就得提示，不能被「跳过 0」蒙混过去
    expect(importOutcome({ counts: { conflict: 1 } })).toContain('1 条需要你看一眼')
  })

  it('认不出的格式标识原样回显，不吞（前端没跟上后端时也要看得见）', () => {
    expect(formatLabel('legado-2')).toBe('Legado / 阅读旧版书源')
    expect(formatLabel('xbs')).toBe('xbs')
    expect(formatLabel(undefined)).toBe('')
    expect(importSummary({ new: 1 }, 'xbs')).toBe(
      '导入完成（格式：xbs）：新增 1 · 更新 0 · 重复 0 · 跳过 0 · 冲突 0 · 不可执行 0',
    )
  })

  it('后端没给 counts（极老的响应体）时如实报失败，不假装成功', () => {
    expect(importOutcome({ errors: [{ error: '不能识别' }] })).toBe('导入失败：不能识别')
    expect(importOutcome({})).toBe('导入失败：响应里没有结果')
  })
})
