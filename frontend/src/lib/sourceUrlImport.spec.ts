import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'

/**
 * 「从 URL 订阅导入书源」的接口契约（第 94 期阶段 4a）。
 *
 * 这条链路的**判据全在后端**：开关（`source_import.url_enabled`）、SSRF 闸
 * （只放行 http/https 的公网地址）、取回上限与证书校验 —— 前端一件都不重复判断
 * （重复判断必然漂：前端放行的地址后端拒绝，界面就会显示一句自相矛盾的话）。
 *
 * 所以这里只钉两件事：
 * ① 打到的是**哪个端点**（写错路径 = 按钮没反应，而这是本期要修的那类病）；
 * ② 地址**原样**送出去 —— 不在前端做任何「补协议 / 去空格 / 加斜杠」的加工，
 *    因为后端要拿原地址给出准确的拒绝原因（拼过的地址会让原因指向别的地方）。
 *
 * ⚠️ 本文件**不 mock `@/lib/api`**：被测的就是它里面的 `importSourcesFromUrl`。
 * 改而去桩 `fetch`（与 `apiRequest.spec.ts` / `convertUpload.spec.ts` 同一手法）。
 */
const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

function stubOk(body: unknown = { counts: {}, format: 'legado-3' }) {
  const calls: { url: string; init: RequestInit }[] = []
  globalThis.fetch = vi.fn((url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} })
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
  }) as unknown as typeof fetch
  return calls
}

describe('api.importSourcesFromUrl（第 94 期阶段 4a）', () => {
  it('打到 POST /api/sources/import-url，body 带 url', async () => {
    const calls = stubOk()
    await api.importSourcesFromUrl('https://example.com/shuyuan.json')
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url).toContain('/api/sources/import-url')
    expect(String(calls[0]?.init.method)).toBe('POST')
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({
      url: 'https://example.com/shuyuan.json',
      origin: '',
      dry_run: false,
    })
  })

  it('地址原样送出，前端不做补协议 / 去空格之类的加工', async () => {
    const calls = stubOk()
    // 故意给一个后端会拒的形状：前端必须**照送**，让后端给出准确原因
    await api.importSourcesFromUrl('  127.0.0.1:8080/x.json  ')
    expect(JSON.parse(String(calls[0]?.init.body)).url).toBe('  127.0.0.1:8080/x.json  ')
  })

  it('失败原因（后端给的人话）原样抛给调用方，不吞不改写', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ detail: 'URL 订阅导入未启用：请到「设置 → 网络 …」' }), {
          status: 400,
        }),
      ),
    ) as unknown as typeof fetch
    await expect(api.importSourcesFromUrl('https://example.com/a.json')).rejects.toThrow(
      /URL 订阅导入未启用/,
    )
  })
})
