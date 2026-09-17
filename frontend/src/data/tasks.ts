/**
 * 任务相关的共享类型。
 *
 * ⚠️ 本文件原先还有一份 **6 条演示种子数据**（`TASKS`：诡秘之主 / 深空彼岸 / 三体 /
 * 长安的荔枝 / 凡人修仙传 / 大奉打更人），由 `stores/tasks.ts` 当成真实任务渲染，
 * 并配一个 900ms 的 ticker 每跳 +1.5%「推进」进度条 —— 那是**伪造的任务状态**，
 * 用户会以为下载真的在按百分比推进。
 *
 * 现已删除：任务数据一律来自服务端任务表（`GET /api/tasks`），
 * 行类型见 `lib/api.ts` 的 `TaskItem`。
 */

export type TaskStatus = 'running' | 'done' | 'queued' | 'failed'
export type TaskType = 'download' | 'convert'
