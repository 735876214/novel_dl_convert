import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, apiErrorMessage } from '@/lib/api'

/**
 * 「上传本地书 → 投递入库」这条链路（第 89 期）。
 *
 * `api.convertDrop` 打的是 `POST /convert`，后端回的是 **FileResponse 文件流**（不是 JSON）。
 * 老实现对它用 `request()` → 末尾那句 `await res.json()` 会把文件字节按 UTF-8 解出 `�`，
 * 再抛 `Unexpected token '�', "…" is not valid JSON` —— 用户看到「上传报错」，可书其实
 * **已经入库**（后端另有一条写入 + 入库链路，报错文本在骗人）。
 *
 * 所以这里钉的不是「上传功能对不对」，而是「**响应不是 JSON 时也算成功、不抛解析错**」——
 * 这条失效方式是**静默而反直觉**的：功能其实是好的，只有一个假错误弹出来。
 *
 * ⚠️ 本文件**不 mock `@/lib/api`**：被测的就是它里面的 `convertDrop` / `requestAck`。
 * 改而去桩 `fetch`（与 `apiRequest.spec.ts` 同一手法）。
 */
const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

describe('api.convertDrop · 不解析响应体（第 89 期）', () => {
  it('响应是**文件流**（非 JSON）时，不抛 JSON 解析错，仍然成功', async () => {
    // 这段字节换成 `res.json()` 必然抛 `Unexpected token '�'`（0xFF / 0x80 不是合法 UTF-8 开头）
    const bytes = new Uint8Array([0xff, 0xfe, 0x00, 0x31, 0x80, 0x81, 0x40, 0x7f])
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(bytes, {
        status: 200,
        headers: { 'Content-Type': 'application/octet-stream' },
      }),
    ) as unknown as typeof fetch

    await expect(api.convertDrop(new File(['x'], '美利坚财富人生1-3059.txt'))).resolves.toBeTruthy()
  })

  it('请求形状不变：POST /convert，body 是带文件的 FormData', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('', { status: 200 }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await api.convertDrop(new File(['x'], '三体.epub'))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/convert')
    expect((init as RequestInit).method).toBe('POST')
    expect((init as RequestInit).body).toBeInstanceOf(FormData)
  })

  it('traditionalize=true 时附上该字段（与拖拽口径一致）', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('', { status: 200 }))
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await api.convertDrop(new File(['x'], 'a.txt'), true)

    const body = (fetchMock.mock.calls[0][1] as RequestInit).body as FormData
    expect(body.get('traditionalize')).toBe('true')
  })

  it('失败仍按既有约定：后端 detail 原文进 err.message（交给 apiErrorMessage 剥壳）', async () => {
    // ⚠️ 每次请求都要给**新**的 Response：Response 的 body 只能读一次，复用会让
    // 第二次调用读到空 body（于是被误判成「没有 detail」）。
    globalThis.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ detail: '还没有书库' }), { status: 400 })),
    ) as unknown as typeof fetch

    let caught: unknown
    try {
      await api.convertDrop(new File(['x'], 'a.txt'))
      throw new Error('本该失败')
    } catch (e) {
      caught = e
    }
    expect((caught as Error).message).toContain('还没有书库')
    expect(apiErrorMessage(caught, '兜底')).toBe('还没有书库')
  })

  it('4xx 且响应体为空时给一句分类过的兜底（不把空串抛上去）', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('', { status: 400 })) as unknown as typeof fetch
    await expect(api.convertDrop(new File(['x'], 'a.txt'))).rejects.toThrow('请求失败（HTTP 400）')
  })
})
