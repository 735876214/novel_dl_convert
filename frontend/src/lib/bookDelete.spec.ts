import { describe, expect, it, vi } from 'vitest'

import type { BookCard } from '@/lib/api'
import {
  confirmAndDeleteBook,
  deleteConfirmLines,
  deletedToast,
  siblingNamesOf,
} from './bookDelete'

/**
 * 「删书」的共享流程（第 83 期）。
 *
 * 这条流程的每一句都是**用户可见的承诺**，而写错的形态全是静默的：
 *  · 没有同 stem 兄弟却写「其它格式不会被删除」⇒ 用户以为还有别的文件在别处；
 *  · 有兄弟却漏了那行 ⇒ 用户担心「删了 epub 会不会把 mobi 也删了」；
 *  · 三份里有一份移不动却报「已移入回收站」⇒ **静默的部分成功**（比失败更糟）；
 *  · 点「取消」还发请求 ⇒ 白问一次后端（用户看不到，但保底要钉住）。
 */
vi.mock('@/lib/api', () => ({
  apiErrorMessage: (e: unknown, fallback: string) =>
    e instanceof Error && e.message ? e.message : fallback,
}))

function makeBook(over: Partial<BookCard> = {}): BookCard {
  return { id: 'lib$aaa', name: '三体.epub', title: '三体', ...over } as BookCard
}

describe('siblingNamesOf', () => {
  it('只认同 stem 的兄弟，且取 basename、排除主文件本身', () => {
    const files = [
      { name: '科幻/三体.epub' },
      { name: '科幻/三体.mobi' },
      { name: '科幻/三体.txt' },
      { name: '科幻/球状闪电.epub' },
    ]
    expect(siblingNamesOf(files, '科幻/三体.epub')).toEqual(['三体.mobi', '三体.txt'])
  })

  it('没有兄弟 / 没有详情 / 没有主文件名 ⇒ 空数组（调用方据此少说一句话）', () => {
    expect(siblingNamesOf([{ name: '三体.epub' }], '三体.epub')).toEqual([])
    expect(siblingNamesOf(undefined, '三体.epub')).toEqual([])
    expect(siblingNamesOf([{ name: '三体.mobi' }], '')).toEqual([])
  })
})

describe('deleteConfirmLines', () => {
  it('三句承诺恒在：回收站（可恢复）/ 三份文件 / 关联数据保留', () => {
    const text = deleteConfirmLines('三体', []).join('\n')
    expect(text).toContain('确定删除《三体》？')
    expect(text).toContain('回收站')
    expect(text).toContain('不是真删')
    expect(text).toContain('本地原件')
    expect(text).toContain('出版副本')
    expect(text).toContain('批注')
  })

  it('没有同 stem 兄弟时**不写**「其它格式」那一行（否则会让人以为有别的文件）', () => {
    expect(deleteConfirmLines('三体', []).join('\n')).not.toContain('其它格式')
  })

  it('有兄弟时点名它们 —— 否则用户会担心连兄弟一起删了', () => {
    const text = deleteConfirmLines('三体', ['三体.mobi']).join('\n')
    expect(text).toContain('三体.mobi')
    expect(text).toContain('不会被删除')
  })
})

describe('deletedToast', () => {
  it('三份都成功 ⇒ 「已移入回收站」', () => {
    const targets = {
      library: { state: 'recycled' },
      source: { state: 'missing' }, // 本来就不在磁盘上，不是失败
      copy: { state: 'recycled' },
    }
    expect(deletedToast('三体', targets)).toBe('《三体》已移入回收站')
  })

  it('有一份移不动 ⇒ 点名是哪一份 + 原因，**不许**报成已删除', () => {
    const targets = {
      library: { state: 'recycled' },
      source: { state: 'failed', error: '只读文件系统' },
      copy: { state: 'recycled' },
    }
    const msg = deletedToast('三体', targets)
    expect(msg).toContain('部分失败')
    expect(msg).toContain('本地的原件')
    expect(msg).toContain('只读文件系统')
    expect(msg).not.toContain('已移入回收站')
  })
})

describe('confirmAndDeleteBook', () => {
  const deps = () => ({
    getDetail: vi.fn(async () => ({ files: [{ name: '三体.epub' }] })),
    remove: vi.fn(async () => ({ targets: { library: { state: 'recycled' } } })),
    // 显式带参：否则 mock 推断成零参元组，`mock.calls[0][0]` 会是 TS2493
    confirm: vi.fn((_message: string) => true),
  })

  it('用户点取消 ⇒ 一个请求都不发（既不删，也不白问后端）', async () => {
    const d = deps()
    d.confirm.mockReturnValue(false)

    const res = await confirmAndDeleteBook(makeBook(), d)

    expect(res).toEqual({ deleted: false })
    expect(d.remove).not.toHaveBeenCalled()
  })

  it('确认后调一次删除并给出回执文案', async () => {
    const d = deps()
    const res = await confirmAndDeleteBook(makeBook(), d)

    expect(d.remove).toHaveBeenCalledTimes(1)
    expect(d.remove).toHaveBeenCalledWith('lib$aaa')
    expect(res.deleted).toBe(true)
    expect(res.message).toBe('《三体》已移入回收站')
  })

  it('确认文案里带上了同 stem 兄弟（有兄弟时必须说清不会被删）', async () => {
    const d = deps()
    d.getDetail.mockResolvedValue({
      files: [{ name: '三体.epub' }, { name: '三体.mobi' }],
    })

    await confirmAndDeleteBook(makeBook(), d)

    expect(d.confirm.mock.calls[0][0]).toContain('三体.mobi')
  })

  it('详情拉失败 ⇒ 不影响删除，只是少说一句兄弟提醒', async () => {
    const d = deps()
    d.getDetail.mockRejectedValue(new Error('后端连不上'))

    const res = await confirmAndDeleteBook(makeBook(), d)

    expect(res.deleted).toBe(true)
    expect(d.confirm.mock.calls[0][0]).not.toContain('其它格式')
  })

  it('删除失败**不抛**，返回错误文案（调用方据此决定不刷新列表）', async () => {
    const d = deps()
    d.remove.mockRejectedValue(new Error('后端连不上'))

    const res = await confirmAndDeleteBook(makeBook(), d)

    expect(res.deleted).toBe(false)
    expect(res.error).toBe('后端连不上')
    expect(res.message).toBeUndefined()
  })
})
