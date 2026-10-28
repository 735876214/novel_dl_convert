/**
 * 设置页的「分区 → 顶层配置键」映射（第 179 期从 `data/settingsFields.ts` 拆出来）。
 *
 * 为什么单独一个文件：它唯一的消费者是 `composables/useSettingsConfig`（保存某分区时
 * 按这张表收集 patch），而这个 composable 被 `AppHeader` **静态**引用 —— 放在
 * `settingsFields.ts` 里会让整份「设置项定义」（含 30 个页面的字段文案，约 8.5 KB chunk）
 * 被拽进首屏 preload。拆开后首屏那份 chunk 消失，而设置页仍按需加载其余部分。
 *
 * ⚠️ 新增可保存的分区时这里是**第三处**必须改的地方（另两处是后端
 * `server.EDITABLE` 与 `GET /api/config` 里那把硬编码键列表）。
 * 漏了这里的表现很隐蔽：界面上的开关会正常切换（本地草稿改了），但
 * `saveSection()` 收集到空 patch → 后端 400「没有可保存的配置项」，
 * 且只有一条 toast 一闪而过 —— 新增 OPDS 时就踩过这一次。
 */
/**
 * 分区 → 该分区保存时要提交的**顶层配置键**。
 *
 * ⚠️ 新增可保存的分区时这里是**第三处**必须改的地方（另两处是后端
 * `server.EDITABLE` 与 `GET /api/config` 里那把硬编码键列表）。
 * 漏了这里的表现很隐蔽：界面上的开关会正常切换（本地草稿改了），但
 * `saveSection()` 收集到空 patch → 后端 400「没有可保存的配置项」，
 * 且只有一条 toast 一闪而过 —— 新增 OPDS 时就踩过这一次。
 */
export const SECTION_KEYS: Record<string, string[]> = {
  conversion: ['chapter_detection', 'traditionalize', 'llm'],
  watcher: ['watcher'],
  // 第 94 期阶段 4a：URL 订阅导入的开关与护栏也在这页（`source_import.*`）
  // 第 138 期：`logging` 已迁出（归 `logs`，见 LOGGING_FIELDS 注释）——一个段只许一个归属分区
  network: ['network', 'download', 'auto_update', 'source_import'],
  naming: ['naming'],
  upload: ['upload'],
  achievements: ['achievements'],
  opds: ['opds'],
  // Komga 页有两块：输出布局（output.layout）+ 兼容服务端（komga.*）
  komga: ['output', 'komga'],
  // 元数据抓取的 7 个页面共用同一配置段（同一份 cfg 草稿，各页只改自己的子键）
  metadata: ['metadata_fetch'],
  // 审计日志（第 52 期留存 / 第 138 期日志文件位置）：**独占** logging 段。
  // 刻意不复用 network 分区 —— 那个分区还含 network / download，连带提交会把别页
  // 未保存的草稿一起写进去（草稿是跨页共享的单例，见 useSettingsConfig）。
  // 反过来也一样：`logging` 不许再挂到第二页（第 138 期起 `network` 已不含它）。
  logs: ['logging'],
  // 阅读进度口径的全局默认值（页面在「偏好与同步」；每库覆写在书库管理里）
  reading: ['reading'],
  // 版本检查与一键更新（第 78 期）：四个键都在后端 EDITABLE 白名单里
  update: ['update'],
}
