/**
 * 实时事件客户端（第 153 期）。
 *
 * 后端在 `/ws` 上推「某件事发生了」（事件名与上游 BookOrbit 对齐）；这里只负责
 * **连接 / 重连 / 分发**，不缓存任何业务状态。界面收到事件后仍走原有 HTTP 接口
 * 重新取数 —— 事件不是第二份真值源，断线时一切照旧（轮询仍然在）。
 *
 * 约定：
 * - token 无效（后端用 4401 关闭）⇒ **停止重连**，等下次登录/换 token 再连；
 * - 其它断开 ⇒ 指数退避重连（1s → 30s 封顶）；
 * - `onRealtime('*', fn)` 订阅所有事件（调试用）。
 */

type Handler = (data: Record<string, unknown>, event: string) => void

const handlers = new Map<string, Set<Handler>>()
let socket: WebSocket | null = null
let token = ''
let enabled = false
let retry = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null

function wsUrl(t: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws?token=${encodeURIComponent(t)}`
}

function dispatch(event: string, data: Record<string, unknown>): void {
  for (const key of [event, '*']) {
    const set = handlers.get(key)
    if (!set) continue
    for (const fn of set) {
      try {
        fn(data, event)
      } catch {
        /* 单个订阅者报错不影响其它订阅者 */
      }
    }
  }
}

function scheduleReconnect(): void {
  if (!enabled || !token) return
  if (retryTimer !== null) return
  const delay = Math.min(30_000, 1000 * 2 ** Math.min(retry, 5))
  retry += 1
  retryTimer = setTimeout(() => {
    retryTimer = null
    connect()
  }, delay)
}

function connect(): void {
  if (!enabled || !token) return
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return
  }
  try {
    socket = new WebSocket(wsUrl(token))
  } catch {
    scheduleReconnect()
    return
  }
  socket.onopen = () => {
    retry = 0
  }
  socket.onmessage = (ev) => {
    try {
      const msg = JSON.parse(String(ev.data)) as { event?: string; data?: Record<string, unknown> }
      if (msg && typeof msg.event === 'string') dispatch(msg.event, msg.data || {})
    } catch {
      /* 非 JSON 帧忽略 */
    }
  }
  socket.onclose = (ev) => {
    socket = null
    if (ev.code === 4401) {
      // 令牌无效：重连没有意义，等下一次 startRealtime（登录/换 token）。
      enabled = false
      return
    }
    scheduleReconnect()
  }
  socket.onerror = () => {
    /* onclose 会接着触发，统一在那里退避 */
  }
}

/** 登录后调用（或 token 变化时）。重复调用是幂等的。 */
export function startRealtime(t: string): void {
  const next = (t || '').trim()
  if (!next) {
    stopRealtime()
    return
  }
  if (enabled && token === next && socket) return
  stopRealtime()
  token = next
  enabled = true
  retry = 0
  connect()
}

/** 退出登录 / 卸载时调用。 */
export function stopRealtime(): void {
  enabled = false
  token = ''
  retry = 0
  if (retryTimer !== null) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  if (socket) {
    const s = socket
    socket = null
    try {
      s.close()
    } catch {
      /* ignore */
    }
  }
}

/** 订阅一个事件（`'*'` = 全部）。返回取消订阅函数。 */
export function onRealtime(event: string, fn: Handler): () => void {
  let set = handlers.get(event)
  if (!set) {
    set = new Set()
    handlers.set(event, set)
  }
  set.add(fn)
  return () => {
    set?.delete(fn)
    if (set && set.size === 0) handlers.delete(event)
  }
}
