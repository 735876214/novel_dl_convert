import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import BatchMetadataDialog from '@/components/book/BatchMetadataDialog.vue'

/**
 * 第 157 期：批量元数据编辑。
 *
 * 钉住两条「写错了不会报错」的语义：
 *  - **留空 = 不修改**（不是「撤销覆盖」）—— 只把非空字段发出去；
 *  - 失败逐本显示原因，不能把「部分成功」显示成全部成功。
 */
vi.mock('@/lib/api', () => ({
  api: { batchSetMetadata: vi.fn() },
}))

const m = { batch: vi.mocked(api.batchSetMetadata) }

function mountDialog() {
  return mount(BatchMetadataDialog, {
    props: { open: true, bookIds: ['b1', 'b2'] },
  })
}

describe('BatchMetadataDialog', () => {
  it('只提交填了的字段（留空 = 不修改）', async () => {
    m.batch.mockResolvedValue({ ok: true, results: [], saved: 2, failed: 0 })
    const w = mountDialog()
    const inputs = w.findAll('input')
    // 字段顺序：作者 / 系列 / 出版社 / 语言 / 出版日期 / 题材
    await inputs[0].setValue('某作者')
    await inputs[5].setValue('科幻、 经典')
    const btn = w.findAll('button').find((b) => b.text().includes('应用到 2 本'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    expect(m.batch).toHaveBeenCalledWith(['b1', 'b2'], { author: '某作者', tags: ['科幻', '经典'] })
    expect(w.text()).toContain('已写入 2 本')
  })

  it('失败逐本列出原因，不显示成全部成功', async () => {
    m.batch.mockResolvedValue({
      ok: false,
      results: [
        { id: 'b1', ok: true, changed: ['author'] },
        { id: 'b2', ok: false, error: '书籍不存在' },
      ],
      saved: 1,
      failed: 1,
    })
    const w = mountDialog()
    await w.findAll('input')[0].setValue('X')
    const btn = w.findAll('button').find((b) => b.text().includes('应用到 2 本'))
    await btn!.trigger('click')
    await flushPromises()

    expect(w.text()).toContain('已写入 1 本，1 本失败')
    expect(w.text()).toContain('b2：书籍不存在')
    expect(w.text()).not.toContain('全部成功')
  })
})
