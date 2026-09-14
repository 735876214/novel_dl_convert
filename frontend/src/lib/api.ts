/**
 * 后端 API 封装（迁移自 v1 app.js 的 api()）。
 *
 * 约定：
 *   · 同源请求，dev 期由 vite.config.ts 的 server.proxy 转发到 localhost:8993
 *   · 统一的错误处理：非 2xx 打 console.error 并抛 Error（消息取自后端 detail）
 *   · 搜索等易竞态的场景由调用方传 AbortSignal
 */

export interface HealthInfo {
  status: string
  input: string
  output: string
  watcher: boolean
}

export interface SourceItem {
  name: string
  builtin?: boolean
  [key: string]: unknown
}

export interface FileEntry {
  name: string
  size: number
  mtime: number
}

export interface FileListing {
  input: FileEntry[]
  output: FileEntry[]
}

export interface SearchHit {
  title: string
  author?: string
  source: string
  url: string
  [key: string]: unknown
}

export interface TaskState {
  status: 'pending' | 'running' | 'done' | 'error' | string
  result: string | null
  error: string | null
  name: string | null
}

export interface LogItem {
  ts?: string
  time?: string
  action?: string
  status?: string
  message?: string
  [key: string]: unknown
}

export interface LogQuery {
  limit?: number
  action?: string
  status?: string
  q?: string
}

export interface WatcherStatus {
  running: boolean
  [key: string]: unknown
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    console.error(`[api] ${init?.method ?? 'GET'} ${path} → ${res.status}`, detail)
    throw new Error(detail || `请求失败（HTTP ${res.status}）`)
  }
  return (await res.json()) as T
}

/** 下载类接口返回文件流，直接交给浏览器 */
function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  return fetch(path, init).then((res) => {
    if (!res.ok) {
      console.error(`[api] POST ${path} → ${res.status}`)
      throw new Error(`请求失败（HTTP ${res.status}）`)
    }
    return res.blob()
  })
}

export const api = {
  health: () => request<HealthInfo>('/health'),

  // ---------- 书源 ----------
  listSources: () => request<{ sources: SourceItem[] }>('/api/sources'),

  addSourcesText: (text: string) =>
    request<{ added?: number; ok?: boolean }>('/api/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
      body: text,
    }),

  uploadSourcesFile: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ added?: number; ok?: boolean }>('/api/sources/upload', {
      method: 'POST',
      body: form,
    })
  },

  deleteSource: (name: string) =>
    request<{ ok: boolean }>(`/api/sources/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  // ---------- 搜索 / 预览 / 下载 ----------
  search: (title: string, signal?: AbortSignal) =>
    request<{ results?: SearchHit[]; items?: SearchHit[]; errors?: unknown[] }>('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
      signal,
    }),

  preview: (source: string, url: string) =>
    request<Record<string, unknown>>(
      `/api/preview?source=${encodeURIComponent(source)}&url=${encodeURIComponent(url)}`,
    ),

  download: (item: Record<string, unknown>) =>
    request<{ task_id: string }>('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    }),

  task: (tid: string) => request<TaskState>(`/api/tasks/${encodeURIComponent(tid)}`),

  // ---------- 文件 ----------
  files: () => request<FileListing>('/api/files'),

  // ---------- 目录监听 ----------
  watcherStatus: () => request<WatcherStatus>('/api/watcher'),
  watcherStart: () => request<WatcherStatus>('/api/watcher/start', { method: 'POST' }),
  watcherStop: () => request<WatcherStatus>('/api/watcher/stop', { method: 'POST' }),
  scanNow: () => request<Record<string, unknown>>('/api/scan', { method: 'POST' }),

  // ---------- 日志 ----------
  logs: (query: LogQuery = {}) => {
    const p = new URLSearchParams()
    if (query.limit) p.set('limit', String(query.limit))
    if (query.action) p.set('action', query.action)
    if (query.status) p.set('status', query.status)
    if (query.q) p.set('q', query.q)
    const qs = p.toString()
    // 注意：后端的 count 字段未必是数字（activity_log.count() 可能返回聚合对象），
    // 因此类型放宽为 unknown，由调用方归一化。
    return request<{ items: LogItem[]; count: unknown; dir: string }>(`/api/logs${qs ? `?${qs}` : ''}`)
  },

  clearLogs: () => request<{ ok: boolean }>('/api/logs', { method: 'DELETE' }),

  logsDownloadUrl: () => '/api/logs/download',

  // ---------- 本地转换 ----------
  convertFile: (file: File, traditionalize = false) => {
    const form = new FormData()
    form.append('file', file)
    form.append('traditionalize', String(traditionalize))
    return requestBlob('/convert', { method: 'POST', body: form })
  },

  convertPath: (path: string, traditionalize = false) => {
    const form = new FormData()
    form.append('path', path)
    form.append('traditionalize', String(traditionalize))
    return requestBlob('/convert-path', { method: 'POST', body: form })
  },

  downloadUrl: (name: string) => `/download/${encodeURIComponent(name)}`,
}
