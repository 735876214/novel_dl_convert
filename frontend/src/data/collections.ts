/**
 * 侧栏三组导航条目的静态骨架（库 / 智能书架 / 收藏夹）。
 *
 * **三组都不预置任何条目**（第 37 期口径）：全新部署时侧栏这三组是空的，
 * 建什么、叫什么名字，全部由用户手动新增。所以这里的 `LIBRARIES` /
 * `SMART_SHELVES` / `COLLECTIONS` 一律是空骨架，条目分别由：
 *   · 库       —— 后端 `/api/libraries`（用户建的库实体）；
 *   · 智能书架 —— 后端 `/api/smart-scopes`（用户建的规则书架）；
 *   · 收藏夹   —— 后端 `/api/collections`。
 * 计数也一律不写死在数据里，用后端回来的真实数字。
 *
 * ⚠️ 以前「智能书架」这组硬编码过 5 条（最近添加 / 未读 / 在读 / 已完成 / 有批注），
 * 现在它们不再是默认项 —— 想重建请到「智能书架」页用规则自己建，规则字段已补上
 * `批注数` 与 `入库天数`（见 lib/smartScope.ts），够重建这 5 条。
 */

export interface NavEntry {
  id: string
  label: string
  icon: string
  /** 计数；不写则不渲染计数胶囊 */
  count?: number
}

/** 书库（侧栏「库」组）：整组由侧栏用后端库实体覆盖，这里只留空骨架 */
export const LIBRARIES: NavEntry[] = []

/** 智能书架：**不预置**任何书架，条目全部来自后端 smart_scopes（用户手建） */
export const SMART_SHELVES: NavEntry[] = []

/** 收藏夹：**不预置**任何收藏夹，条目全部来自后端 collections（用户手建） */
export const COLLECTIONS: NavEntry[] = []
