import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'

/**
 * 请求健壮性（第 88 期）：超时 / 网络错 / 4xx / 5xx 的**区分**，以及「只对 GET 重试一次」。
 *
 * 为什么值得单测：这些失效方式全是**静默**的 ——
 *   · 超时不生效只是「转圈更久」（用户看到的正是「打开书库等很久」）；
 *   · 写操作被误重试会造成重复副作用（重复建库、重复搬文件），却不报错；
 *   · 调用方主动取消被误报成「超时」，会让探索页把「我自己取消的旧检索」当成失败弹 toast。
 * 三条都不会崩，只会悄悄害人，故逐条钉住。
 *
 * ⚠️ 本文件**不 mock `@/lib/api`**：被测的就是它里面的 `request()`。改而去桩 `fetch`。
 */
const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
  vi.useRealTimers()
})

/** 取一次请求最终的失败 `name`（没失败则空串）。用取名字而不是 toMatchObject —— 更直白。 */
async function nameOf(p: Promise<unknown>): Promise<string> {
  try {
    await p
    return ''
  } catch (e) {
    return (e as Error)?.name ?? ''
  }
}

describe('request · 超时（第 88 期）', () => {
  it('GET 超时 → TimeoutError，且**只发一次**（超时不重试）', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_res, rej) => {
          // 只会在「被 abort」时 reject（模拟一个永远不回的慢请求）
          init?.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
        }),
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const p = api.books()
    const cond = expect(nameOf(p)).resolves.toBe('TimeoutError')
    await vi.advanceTimersByTimeAsync(15000) // 默认超时 15s
    await cond
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('request · 重试纪律（第 88 期）', () => {
  it('GET 网络层失败 → 重试一次（共 2 次），最终抛 NetworkError', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('fetch failed'))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await expect(nameOf(api.books())).resolves.toBe('NetworkError')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('写操作（POST）网络失败**不重试**（共 1 次）—— 重发可能造成重复副作用', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('fetch failed'))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await expect(nameOf(api.scanNow())).resolves.toBe('NetworkError')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('调用方 abort → 抛 AbortError（不被误报成超时 / 网络错）', async () => {
    const ctrl = new AbortController()
    globalThis.fetch = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_res, rej) => {
          init?.signal?.addEventListener('abort', () => rej(new DOMException('x', 'AbortError')))
        }),
    ) as unknown as typeof fetch

    const p = api.search('三体', 1, ctrl.signal)
    const cond = expect(nameOf(p)).resolves.toBe('AbortError')
    ctrl.abort()
    await cond
  })
})

describe('request · 失败原因的分类（第 88 期）', () => {
  it('4xx → 「请求失败（HTTP xxx）」', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('', { status: 404 })) as unknown as typeof fetch
    await expect(api.books()).rejects.toThrow('请求失败（HTTP 404）')
  })

  it('5xx → 「服务器错误（HTTP xxx）」', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('', { status: 503 })) as unknown as typeof fetch
    await expect(api.books()).rejects.toThrow('服务器错误（HTTP 503）')
  })

  it('后端有 detail 时**保留原文**（交给 apiErrorMessage 剥壳）', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ detail: '库不存在' }), { status: 500 })) as unknown as typeof fetch
    await expect(api.books()).rejects.toThrow('库不存在')
  })
})
