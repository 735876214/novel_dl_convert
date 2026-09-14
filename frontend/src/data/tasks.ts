/** 下载 / 转换任务。迁移自 v2 app.js 的 TASKS（原第 56–63 行，6 条演示数据）。 */

export type TaskStatus = 'running' | 'done' | 'queued' | 'failed'
export type TaskType = 'download' | 'convert'

export interface Task {
  id: string
  book: string
  type: TaskType
  detail: string
  progress: number
  status: TaskStatus
  /** 仅运行中 */
  speed?: string
  /** 仅运行中 */
  eta?: string
  /** 仅失败 */
  error?: string
}

export const TASKS: Task[] = [
  { id: 't1', book: '诡秘之主', type: 'download', detail: 'EPUB · 1432 章 · 起点中文网', progress: 68, status: 'running', speed: '1.24 MB/s', eta: '2 分 12 秒' },
  { id: 't2', book: '深空彼岸', type: 'download', detail: 'TXT · 1108 章 · 起点中文网', progress: 34, status: 'running', speed: '862 KB/s', eta: '5 分 40 秒' },
  { id: 't3', book: '三体', type: 'convert', detail: 'EPUB → MOBI · Calibre', progress: 100, status: 'done' },
  { id: 't4', book: '长安的荔枝', type: 'convert', detail: 'TXT → EPUB · 生成目录', progress: 0, status: 'queued' },
  { id: 't5', book: '凡人修仙传', type: 'download', detail: 'EPUB · 2446 章 · 顶点小说', progress: 100, status: 'failed', error: '书源响应超时' },
  { id: 't6', book: '大奉打更人', type: 'download', detail: 'EPUB · 1149 章 · 笔趣阁', progress: 100, status: 'done' },
]
