import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { overwriteConfirmLines, runCheckUpdate } from '@/lib/checkUpdate'

/**
 * 第 93 期 E5：「检查更新」的**报告契约**（书卡 ⋮ 菜单与详情页在线读卡共用这一份）。
 *
 * 这一块坏起来全是静默的：
 *   · 把报告换成前端自编的一句话（「更新完成」）⇒ 用户再也看不到「源站目录与本地不一致，
 *     未自动写入」—— 而那正是他**唯一**能知道「为什么没更新」的地方；
 *   · 400 的 `detail`（「下载功能未开启」/「先绑一个源」）被吞成「检查更新失败」⇒
 *     指令变成状态，用户不知道该干什么；
 *   · 轮询没了上限 / 上限不报 ⇒ 按钮永远转圈，用户以为还在跑；
 *   · 轮询期间一次抖动就判定整件事失败 ⇒ 明明在跑的任务被报成「失败」。
 *
 * ⚠️ 默认路径**只追加**、整本覆盖要二次确认 —— 确认文案在这里逐行钉住：它会被
 * `window.confirm` 原样显示，任何 Markdown 记号（`**加粗**`）都会露出来当乱码看。
 */
vi.mock('@/lib/api', () => ({
  api: { checkUpdate: vi.fn(), task: vi.fn() },
  apiErrorMessage: (e: unknown, fallback: string) =>
    (e instanceof Error && e.message) ? e.message : fallback,
}))

const m = {
  checkUpdate: vi.mocked(api.checkUpdate),
  task: vi.mocked(api.task),
}

/** 轮询间隔（与实现里的 `POLL_MS` 对齐；实现改了这里也要改，改错就是「等不到结果」） */
const POLL = 1200

/**
 * 让「第一次轮询」真的发生 ⇒ 再取结果。
 *
 * ⚠️ 必须**先把微任务跑干净**：`runCheckUpdate` 里 `api.checkUpdate` 是 await 的，
 * 第一个 `sleep` 定时器要等它回来才挂得上 —— 直接推时间会推到一个还不存在的定时器，
 * 于是用例永远等不到结果（假红）。
 */
async function settle<T>(p: Promise<T>, ms = POLL + 50): Promise<T> {
  for (let i = 0; i < 5; i += 1) await Promise.resolve()
  await vi.advanceTimersByTimeAsync(ms)
  return p
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  m.checkUpdate.mockResolvedValue({ task_id: 't1', overwrite: false, source: 'stub-src' })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('checkUpdate · 走哪条路', () => {
  it('默认**只追加**（overwrite=false 发给服务端）', async () => {
    m.task.mockResolvedValue({ status: 'done', notice: '新增 3 章', result: null, error: null, name: null })

    const r = await settle(runCheckUpdate('book-a'))

    expect(m.checkUpdate).toHaveBeenCalledWith('book-a', false)
    expect(r).toEqual({ ok: true, message: '新增 3 章' })
  })

  it('整本覆盖显式传 overwrite=true', async () => {
    m.task.mockResolvedValue({ status: 'done', notice: '已整本覆盖', result: null, error: null, name: null })

    await settle(runCheckUpdate('book-a', { overwrite: true }))

    expect(m.checkUpdate).toHaveBeenCalledWith('book-a', true)
  })

  it('还没跑完就继续轮询，不是一次就问完', async () => {
    m.task
      .mockResolvedValueOnce({ status: 'running', notice: '', result: null, error: null, name: null })
      .mockResolvedValueOnce({ status: 'done', notice: '新增 1 章', result: null, error: null, name: null })

    const r = await settle(runCheckUpdate('book-a'), POLL * 2 + 100)

    expect(m.task).toHaveBeenCalledTimes(2)
    expect(r.message).toBe('新增 1 章')
  })
})

describe('checkUpdate · 报告从哪儿来', () => {
  it('任务行的 notice 原样透出（**不**换成前端自编的一句话）', async () => {
    const why = '源站目录与本地不一致（5 章窗口里不足 3 章同名），未自动写入（避免进度错位）'
    m.task.mockResolvedValue({ status: 'done', notice: why, result: null, error: null, name: null })

    const r = await settle(runCheckUpdate('book-a'))

    expect(r.ok).toBe(true)
    expect(r.message).toBe(why)
  })

  it('notice 为空就回落 result，再回落一句老实话', async () => {
    m.task.mockResolvedValue({ status: 'done', notice: '', result: '报告在 result 里', error: null, name: null })
    expect((await settle(runCheckUpdate('book-a'))).message).toBe('报告在 result 里')

    m.task.mockResolvedValue({ status: 'done', notice: '', result: null, error: null, name: null })
    expect((await settle(runCheckUpdate('book-a'))).message).toContain('没有新章节')
  })

  it('任务失败 ⇒ 原文当结果，且 ok=false', async () => {
    m.task.mockResolvedValue({ status: 'failed', notice: '', result: null, error: '站点炸了', name: null })

    expect(await settle(runCheckUpdate('book-a'))).toEqual({ ok: false, message: '站点炸了' })
  })

  it('入队就被拒（400）⇒ 原文照给，一个任务都不建', async () => {
    m.checkUpdate.mockRejectedValue(new Error('下载功能未开启：到「设置 → 网络与下载」打开「开放搜索 / 下载」'))

    const r = await settle(runCheckUpdate('book-a'), 10)

    expect(r.ok).toBe(false)
    expect(r.message).toContain('下载功能未开启')
    expect(m.task).not.toHaveBeenCalled()
  })

  it('轮询期间的一次抖动不判负（下一次就回来了）', async () => {
    m.task
      .mockRejectedValueOnce(new Error('网络抖了一下'))
      .mockResolvedValueOnce({ status: 'done', notice: '新增 2 章', result: null, error: null, name: null })

    expect((await settle(runCheckUpdate('book-a'), POLL * 2 + 100)).ok).toBe(true)
  })

  it('一直跑不完 ⇒ 如实说「还在跑」并指向任务中心，不假装成功', async () => {
    m.task.mockResolvedValue({ status: 'running', notice: '', result: null, error: null, name: null })

    const r = await settle(runCheckUpdate('book-a'), POLL * 200 + 1000)

    expect(r.ok).toBe(false)
    expect(r.message).toContain('任务中心')
  })
})

describe('checkUpdate · 整本覆盖的确认文案', () => {
  it('纯文本、含书名、说清代价并给退路（`window.confirm` 不认任何标记）', () => {
    const text = overwriteConfirmLines('三体').join('\n')

    expect(text).toContain('三体')
    expect(text).toContain('整本重写')
    expect(text).toContain('进度')
    expect(text).toContain('检查更新')          // 退路：先试只追加那条
    expect(text).not.toMatch(/\*\*|`|<[a-z]/i)  // 标记会在对话框里原样露出来
  })
})
