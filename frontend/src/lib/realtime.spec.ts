import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { onRealtime, startRealtime, stopRealtime } from './realtime'

/**
 * `lib/realtime.ts` 的契约：
 * - 登录后连 `/ws?token=…`；
 * - 收到帧按事件名分发（`'*'` 收全部）；
 * - 4401（令牌无效）**不再重连**，其余断开指数退避重连。
 *
 * 这里用假 WebSocket，不碰真实网络 —— 真连接的行为由后端 `tests/test_realtime.py` 钉住。
 */

class FakeWebSocket {
  static OPEN = 1
  static CONNECTING = 0
  static CLOSING = 2
  static CLOSED = 3
  static instances: FakeWebSocket[] = []

  url: string
  readyState = FakeWebSocket.CONNECTING
  onopen: ((ev: unknown) => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: ((ev: { code: number }) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.({ code: 1000 })
  }
}

const OriginalWebSocket = globalThis.WebSocket

beforeEach(() => {
  FakeWebSocket.instances = []
  ;(globalThis as unknown as { WebSocket: typeof FakeWebSocket }).WebSocket = FakeWebSocket
  vi.useFakeTimers()
})

afterEach(() => {
  stopRealtime()
  vi.useRealTimers()
  ;(globalThis as unknown as { WebSocket: typeof OriginalWebSocket }).WebSocket = OriginalWebSocket
})

describe('realtime', () => {
  it('连接地址带 token，并把事件分发给订阅者', () => {
    const got: Array<[string, unknown]> = []
    const off = onRealtime('book-dock:changed', (data, event) => got.push([event, data]))
    const offAll = onRealtime('*', (_data, event) => got.push(['*:' + event, null]))

    startRealtime('tok-1')
    const ws = FakeWebSocket.instances.at(-1)!
    expect(ws.url).toContain('/ws?token=tok-1')

    ws.onmessage?.({ data: JSON.stringify({ event: 'book-dock:changed', data: { item: 'a.epub' } }) })
    expect(got).toEqual([
      ['book-dock:changed', { item: 'a.epub' }],
      ['*:book-dock:changed', null],
    ])

    off()
    offAll()
  })

  it('4401 之后不再重连（令牌无效，等下次登录）', () => {
    startRealtime('bad')
    const ws = FakeWebSocket.instances.at(-1)!
    ws.onclose?.({ code: 4401 })
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('普通断开后按退避重连', () => {
    startRealtime('tok-2')
    const first = FakeWebSocket.instances.at(-1)!
    first.onclose?.({ code: 1006 })
    vi.advanceTimersByTime(1000)
    expect(FakeWebSocket.instances.length).toBe(2)
    expect(FakeWebSocket.instances[1].url).toContain('token=tok-2')
  })

  it('stopRealtime 关闭连接并停止重连', () => {
    startRealtime('tok-3')
    const ws = FakeWebSocket.instances.at(-1)!
    stopRealtime()
    expect(ws.readyState).toBe(FakeWebSocket.CLOSED)
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })
})
