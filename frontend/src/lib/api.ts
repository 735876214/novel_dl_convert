/**
 * 后端 API 封装（迁移自 v1 app.js 的 api()）。
 *
 * 约定：
 *   · 同源请求，dev 期由 vite.config.ts 的 server.proxy 转发到 localhost:8993
 *   · 统一的错误处理：非 2xx 打 console.error 并抛 Error（消息取自后端 detail）
 *     调用方要避免这条日志，只能**不发这个请求** —— 浏览器自身的网络层日志
 *     任何 JS 都压不掉，压制应用层日志只是自欺。
 *   · 搜索等易竞态的场景由调用方传 AbortSignal
 */
// 类型-only 循环引用在运行时会被擦除，安全（smartScope.ts 需要 BookCard）
import type { PrefsPayload } from './prefsPayload'
import type { SmartScope, ScopeRule } from './smartScope'

export interface HealthInfo {
  status: string
  input: string
  output: string
  watcher: boolean
  /** 应用版本（后端单一真值源下发；前端 About / 更新日志据此渲染，不再手写版本号） */
  version: string
  /** 是否挂了 docker.sock（决定「一键更新」是否可用；侧栏据此决定是否挂 new 提示） */
  updater_available?: boolean
  /** 活动日志目录（后端 /health 会返回） */
  logs?: string
}

/** 更新检查快照（GET /api/update/status）。 */
export interface UpdateStatus {
  /** 本地当前版本 */
  current: string
  /** 远端最新版本（取不到为 null） */
  latest: string | null
  /** 远端是否比本地新 */
  has_update: boolean
  /** 上次检查时间戳（秒） */
  checked_at: number
  /** 远端 Release 链接 */
  url: string
  /** 一键更新是否可用（挂了 docker.sock） */
  updater_available: boolean
  /** 检查失败原因（空 = 正常） */
  error: string
  /** 是否开着定时检查（第 80 期回显；关掉后后端不再出网） */
  check_enabled?: boolean
  /** 是否开着「发现新版自动更新」（第 80 期回显；横幅据此如实说明） */
  auto_apply?: boolean
  /** 自动更新连续失败次数（第 84 期；退避长度的依据，0 = 没失败过） */
  auto_failures?: number
  /** 下次允许自动更新重试的时间戳（秒，0 = 不在退避窗口内） */
  auto_retry_at?: number
  /** 上次自动更新尝试的 stage（"" / restarting / pull_failed / backup_failed / unavailable） */
  last_auto_result?: string
  /** 上次自动更新失败的人话原因（界面横幅要显示它） */
  auto_message?: string
}

/** 更新应用结果（POST /api/update/apply）。 */
export interface UpdateApplyResult {
  ok: boolean
  /** unavailable / backup_failed / pull_failed / restarting */
  stage: string
  image?: string
  message?: string
  /** 第 84 期：更新前快照落点（持久卷上的备份文件路径） */
  backup?: string
}

/** CHANGELOG 一个分组下的条目。 */
export interface ChangelogGroup {
  tag: string
  items: string[]
}

/** CHANGELOG 一个版本段。 */
export interface ChangelogEntry {
  version: string
  /** 发布日期（更早段为空） */
  date: string | null
  note: string
  groups: ChangelogGroup[]
}

export interface SourceItem {
  name: string
  builtin?: boolean
  [key: string]: unknown
}

/** 书源运行状态（/api/sources/status）：Cookie 持久化 + 当前配置下的可用性 */
export interface SourceStatus {
  name: string
  display_name?: string
  domains: string[]
  public: boolean
  user: boolean
  download_enabled: boolean
  public_only: boolean
  cookie: { has: boolean; mtime: number | null; size: number }
  usable: boolean
  blocked_reason: string
}

export interface FileEntry {
  name: string
  size: number
  mtime: number
}

/** 书源试搜结果（/api/sources/test）：`errors` = 规则校验错，`error` = 运行期错误（网络/解析） */
export interface SourceTestResult {
  ok: boolean
  errors: string[]
  /** 命中条数（可能大于 items 的长度 —— items 最多回前 5 条） */
  count: number
  items: Array<{ title: string; author: string; url: string }>
  error: string
}

export interface FileListing {
  input: FileEntry[]
  output: FileEntry[]
}

export interface SearchHit {
  title: string
  author?: string
  /**
   * 书源名（`manager._mark()` 打的，第 71 期起**同时**写 `_source` 与 `source`）。
   * 结果行的来源徽章与「预览」都用它 —— 第 71 期之前后端只给了 `_source`，
   * 于是 `hit.source` 恒为 `undefined`：徽章空白、预览必然报「未知书源: undefined」。
   */
  source: string
  url: string
  /** 书源的展示名（可选；缺省时前端回落 `source`） */
  source_name?: string
  [key: string]: unknown
}

/**
 * 逐源检索状态（第 71 期 `/api/search` 的 `sources[]`）。
 *
 * 存在的意义就是**如实**回答「这个源为什么没结果」：`ok` = 成功，
 * `skipped` = 被闸门（下载未开启 / 仅放行公版源）跳过，其余为失败且 `error` 是原因原文。
 * 第 71 期之前这些原因只进后端日志，界面那条「部分书源检索失败」横幅永远不显示。
 */
export interface SearchSourceState {
  name: string
  display_name: string
  ok: boolean
  /** 该源本页命中数（失败/跳过时为 0） */
  count: number
  /** 失败原因原文（`ok` 为真时是空串） */
  error: string
  /** 是否被闸门跳过（跳过 ≠ 失败，两者不能混为一谈） */
  skipped: boolean
  /** 被跳过的原因（`skipped` 为假时是空串） */
  reason: string
  /** 该源是否还能取下一页 */
  has_more: boolean
}

export interface TaskState {
  /**
   * 任务状态。⚠️ 后端**失败时写的是 `failed`**（不是 `error`）——
   * 旧类型这里写的是 `'error'`，导致调用方判断失败的分支永远不成立
   * （失败任务会一直显示「下载中」并无限轮询）。已按后端实际取值修正。
   */
  status: 'queued' | 'running' | 'done' | 'failed' | string
  result: string | null
  error: string | null
  name: string | null
}

/** 任务表的一行（`GET /api/tasks`）。progress 只含真实里程碑：0 入队 / 50 开始 / 100 结束。 */
export interface TaskItem {
  id: string
  type: string
  title: string
  detail: string
  status: string
  progress: number
  error: string
  result: string
  name: string
  notice: string
  actor: string
  created_at: number
  updated_at: number
}

export interface LogItem {
  ts?: string
  time?: string
  action?: string
  status?: string
  message?: string
  /**
   * 合并计数（第 61 期）：同类型（动作 + 结果 + 主体）在 10s 窗口内重复了 N 次 ⇒
   * **只有这一条**通知，`merged` = N。界面据此显示「×N」，而角标不会因刷屏虚高。
   */
  merged?: number
  /**
   * 操作者（登录账号名）。由后端鉴权中间件写入（见 `core/activity_log.py` 的 actor）。
   * 历史条目没有该字段（字段是后加的），读取端必须按「未记录」渲染而非报错。
   */
  actor?: string
  [key: string]: unknown
}

/** 日志存盘情况（第 52 期；审计页「留存策略」区展示） */
export interface LogStorage {
  /** 当前 activity.log + activity.jsonl 的合计字节数 */
  bytes: number
  /** 已归档的份数（文件名带时间戳，读取端会跨归档） */
  archives: number
  retention: {
    enabled: boolean
    max_bytes: number
    keep: number
    compress: boolean
  }
}

export interface LogQuery {
  limit?: number
  action?: string
  status?: string
  q?: string
  /** 操作者（登录账号名），**精确匹配**；空/不传 = 不过滤 */
  actor?: string
}

export interface WatcherStatus {
  running: boolean
  [key: string]: unknown
}

// ---------- 收书目录条目（Book Dock 五态流水线） ----------

export type BookDockStatus = 'pending' | 'ready' | 'needs_review' | 'error' | 'ignored'

export interface BookDockItem {
  id: string
  name: string
  ext: string
  size: number
  status: BookDockStatus
  /** 成品相对路径（ready 时才有） */
  output: string
  /** 说明 / 错误原因 */
  detail: string
  retries: number
  created_at: number
  updated_at: number
}

export interface BookDockTab {
  key: 'all' | 'needs_review' | 'pending' | 'ready' | 'error'
  label: string
  count: number
}

export interface BookDockResponse {
  items: BookDockItem[]
  counts: Record<string, number>
  tabs: BookDockTab[]
  statuses: string[]
}

// ---------- 工具页（实体管理 / 重排册号 / 重复书籍 / 缺失资源） ----------

export type EntityKind = 'author' | 'series'

export interface EntityItem {
  name: string
  count: number
  books: string[]
}

export interface EntityListing {
  type: EntityKind
  items: EntityItem[]
  total: number
}

/**
 * 实体改名预览里的一条「旧名 → 新名」。
 *
 * 第 28 期起实体改名**只写服务端元数据、不动源文件名**，所以这里的 `old` 与 `new`
 * 恒等（`meta_only` 为真），只用来展示「这本会被改到」；文件是否改名与此无关。
 * 冲突项前端必须置灰、禁止提交。
 */
export interface RenameItem {
  old: string
  new: string
  conflict: boolean
  reason: string
  /** 文件名不变、改的是元数据（实体改名 / 合并的条目恒为真） */
  meta_only?: boolean
  /** 该条目对应的书（`meta_only` 时用于展示与计数） */
  book_id?: string
  title?: string
  /** 条目所属书库（多库下同名书会撞 book_id，得让人看见是哪一本） */
  library_id?: string | null
}

export interface RenamePlan {
  items: RenameItem[]
  type?: EntityKind
  from?: string
  to?: string
  /** 命中数（= items.length；后端一并给出，前端不必自己数） */
  count?: number
}

/** 实体改名 / 合并的落库结果（**只写服务端元数据**，没有改名文件这回事）。 */
export interface EntityRenameResult {
  type: EntityKind
  from: string
  to: string
  count: number
  items: Array<{ book_id: string; name: string; library_id?: string | null }>
  errors: Array<{ name: string; error: string }>
}

export interface DuplicateItem {
  name: string
  size: number
  mtime: number
  format?: string
  library_id?: string | null
}

/** 元数据源（OpenLibrary / Google Books） */
export interface MetadataSource {
  id: string
  label: string
  home: string
  note: string
  /** 是否在当前启用的源顺序里 */
  active: boolean
}

/**
 * 元数据**提供商**（第 57 期「设置 → 书库 → 元数据 → 提供商」页）。
 *
 * 目录 = 上游那 14 家（分四组）；⚠️ `implemented=false` 的家**只列出、不给开关** ——
 * 「能点但点了没用」就是假交互，它们的备注里写清「可经插件市场安装」。
 */
export interface MetadataProvider {
  id: string
  label: string
  /** 分组（与上游同构：一般书籍目录 / 有声读物 / 漫画和小说 / 极权目录） */
  group: string
  home: string
  note: string
  /** 本项目是否真的实现了抓取（14 家全实现 ⇒ 恒 true；留着以防注册表先加条目） */
  implemented: boolean
  /** 页面抓取型（站点改版就可能失效）⇒ 前端给「易失效」徽标 */
  fragile: boolean
  /** 是否需要 API Key / 账号 */
  needs_config?: boolean
  /** 需要 Key 但还没填 ⇒ 归到「需要设置」过滤器 */
  needs_setup: boolean
  /** 配置提示（给用户看的一句话） */
  config_hint?: string
  /** 配置落在 `metadata_fetch.<key_field>`（后端注册表给的键名） */
  key_field?: string
  /** 行内「配置」区的输入框标签 / 占位提示（注册表给，前端不另写一份） */
  key_label?: string
  key_placeholder?: string
  /** 行内配置项**列表**（secret 输入 / select 下拉；空 = 该行不显示「配置」） */
  config_fields?: MetadataConfigField[]
  /** 是否在启用顺序里 */
  active: boolean
  /** 启用时的优先级（1 起；0 = 未启用） */
  order: number
  /** 需要的配置是否已填 */
  has_config: boolean
  /**
   * 语种亲和（第 60 期）：这家**专精**的语种短码（空 + `lang_broad=true` = 多语种通吃）。
   * 「按语种自动重排来源顺序」就是据此分档：专精本语种 → 通吃 → 专精别的语种。
   */
  langs?: string[]
  lang_broad?: boolean
}

/** 提供商的一个**行内配置项**（注册表声明：`type=secret` 掩码输入，`select` 下拉） */
export interface MetadataConfigField {
  /** `metadata_fetch` 下的配置键名 */
  key: string
  /** 传给后端 fetcher 的 opts 键名（缺省 api_key） */
  opt?: string
  label: string
  type: 'secret' | 'select'
  options?: Array<{ value: string; label: string }>
  placeholder?: string
  hint?: string
}

export interface MetadataProvidersResult {
  items: MetadataProvider[]
  groups: Array<{ name: string; items: MetadataProvider[] }>
  enabled: boolean
  active_count: number
  total: number
  implemented_count: number
}

/** 单家体检结论（第 59 期） */
export interface MetadataHealthItem {
  id: string
  label: string
  group: string
  /** 页面抓取型（易失效）—— 它报「能连通但没解析到结果」时多半是站点改版 */
  fragile: boolean
  needs_config: boolean
  ok: boolean
  /** 结论分类键（文案见 `kind_labels`，由后端给，前端不另写一套） */
  kind: string
  ms: number
  count: number
  /** 命中的第一条「书名 · 作者」——用来确认它返回的确实是这本书 */
  first: string
  error: string
}

export interface MetadataHealthResult {
  items: Record<string, MetadataHealthItem>
  order: string[]
  summary: Record<string, number>
  kind_labels: Record<string, string>
  query: string
  /** true = 用的是**各家样本**（地区性目录用当地书名，否则会误报「无结果」） */
  samples: boolean
  elapsed_ms: number
  ran_at: number
  message?: string
}

/** 一次抓取给出的候选 */
export interface MetadataCandidate {
  source: string
  title: string
  author: string
  publisher: string
  year: string
  language: string
  isbn: string
  description: string
  tags: string[]
  cover_url: string
  /** 与目标书的匹配分（0–1） */
  score: number
}

/** 一本书的抓取预览 */
export interface MetadataPlanItem {
  name: string
  book_id: string
  title: string
  author: string
  format: string
  candidates: MetadataCandidate[]
  sources: Record<string, { ok: boolean; count: number; error: string }>
  best_score: number
  /**
   * 参与**跨源字段级合并**的源（第 58 期）；空数组 = 本次没有合并（只用最佳候选）。
   * 每字段自己的来源在 `changes[field].source` 里 —— 合并后同一本书不同字段可能来自不同源。
   */
  merged_from?: string[]
  /** 最佳候选是否达到置信度阈值 */
  auto_ok: boolean
  /** 字段级改动：{字段: {from, to, source, score}}（字段名是 OPF 口径，年份叫 date） */
  changes: Record<string, { from: unknown; to: unknown; source: string; score: number }>
  cover: { url: string; action: string; source: string; score: number } | null
  /**
   * 该书被**显式锁定**的字段（第 35 期，含封面用的独立键 `cover`）。
   *
   * 锁定字段不会出现在 `changes` 里（锁比字段策略更硬），这份清单是让预览页能
   * 如实标注「为什么这次没动它」，而不是让用户以为抓取漏了。
   */
  locked: string[]
  /** 跳过原因（例如该库关闭了在线元数据抓取、或没有够格的候选） */
  skipped: string
  error: string
  /**
   * **本次实际检索顺序**（第 60 期）：开了「按语种自动重排」且本书语种已知时，
   * 它会与配置里的 `sources` 不同 —— 界面据此解释「为什么先问了它」。
   */
  sources_order?: string[]
}

export interface MetadataPlan {
  enabled: boolean
  items: MetadataPlanItem[]
  sources?: string[]
  threshold?: number
  /** 达到阈值可自动应用的本数 */
  auto?: number
  total?: number
  /** 本次是否开了「按书籍语种自动重排来源顺序」（第 60 期） */
  auto_order_by_language?: boolean
  message?: string
}

export interface MetadataApplyResult {
  applied: Array<{ name: string; fields: string[]; cover: boolean }>
  failed: Array<{ name: string; error: string }>
  count: number
  covers: number
}

// ---------- 元数据完整度评分（Confidence Score）----------

export interface MetadataScoreField {
  key: string
  label: string
  weight: number
  /** 该字段在全库的覆盖率（0–100） */
  coverage: number
}

export interface MetadataScoreGroup {
  key: string
  label: string
  zh: string
  weight: number
  coverage: number
  fields: MetadataScoreField[]
}

export interface MetadataScoreBucket {
  key: string
  label: string
  count: number
  percent: number
}

export interface MetadataScoreBook {
  id: string
  name: string
  title: string
  author: string
  format: string
  score: number
  present: string[]
  missing: Array<{ key: string; label: string; weight: number }>
}

export interface MetadataScoreResponse {
  total: number
  avg: number
  p50: number
  p90: number
  min: number
  max: number
  buckets: MetadataScoreBucket[]
  groups: MetadataScoreGroup[]
  lowest: MetadataScoreBook[]
  not_scored: Array<{ key: string; label: string; why: string }>
  notes: string[]
}

/** 外部服务的一个凭据字段（定义由后端给，前端不重复维护） */
export interface IntegrationField {
  key: string
  label: string
  type: 'password' | 'text'
  hint?: string
}

/** 外部服务集成（Hardcover / Readwise / StoryGraph） */
export interface IntegrationService {
  id: string
  label: string
  desc: string
  fields: IntegrationField[]
  /** 能否验证凭据（第 52 期起 StoryGraph 也可**启发式**校验） */
  verify: boolean
  /** 是否支持同步（StoryGraph 无公开 API → false，前端不渲染预览/同步） */
  sync: boolean
  /** 「自动推送」开关（默认关）：新增批注 / 改状态 / 改评分书评时自动推 */
  auto_push: boolean
  doc: string
  note?: string
  /** 当前值：已保存回显掩码，未保存为空串 */
  values: Record<string, string>
  /** 每个字段是否已设置 */
  has: Record<string, boolean>
}

export interface IntegrationTestResult {
  ok: boolean
  message: string
  detail?: string
  /** 无法验证的服务会带这个标记（当前三家都已提供校验，保留兼容） */
  unsupported?: boolean
}

/** 同步预览（`POST /api/integrations/{svc}/preview`）：**只算不改、零外呼** */
export interface SyncPreview {
  service: string
  /** 计量单位（Hardcover = 本书；Readwise = 批注） */
  unit: string
  books: number
  total: number
  /**
   * Hardcover 侧要查对方库才知道有没有这本 ⇒ 预览**不做匹配**，
   * 匹配发生在同步时（结果里带跳过计数）。此项为 true 时前端如实说明。
   */
  remote_match_at_sync: boolean
}

/** 同步结果（`POST /api/integrations/{svc}/sync`） */
export interface SyncResult {
  ok: boolean
  service: string
  message?: string
  matched: number
  pushed: number
  skipped: Array<{ book_id: string; title: string; reason: string }>
  failed: Array<{ book_id: string; title: string; error: string }>
  at: number
}

/** KOReader 进度互通状态（`GET /api/koreader`） */
export interface KoreaderStatus {
  enabled: boolean
  username: string
  /** 是否已设置同步密钥（= 密码的 MD5）。密钥本身永不回显 */
  has_key: boolean
  /** 已建立文档索引的书数 */
  doc_count: number
  /** 书库里的总数（用来看还有多少书没索引） */
  book_count: number
}

/** 一本书的 KOReader 文档索引（`GET /api/koreader/docs`） */
export interface KoreaderDoc {
  book_id: string
  name: string
  title: string
  /** partialMD5：KOReader 默认的 document 标识 */
  doc_md5: string
  /** md5(basename)：checksum_method=FILENAME 时用 */
  alt_md5: string
  size: number
}

/** `POST /api/komga/layout/preview`：整理为 Komga 库布局的预览（只算不改） */
export interface KomgaLayoutItem {
  /** 原相对路径（平铺时就是文件名） */
  old: string
  /** 目标相对路径，形如 `系列名/系列名 #1.epub` */
  new: string
  title: string
  author: string
  series: string
  index: string
  /** 会改 basename → book_id 变 → 应用时自动搬进度/批注/评分/收藏 */
  id_changes: boolean
  conflict: boolean
  reason: string
}

export interface KomgaLayoutPlan {
  items: KomgaLayoutItem[]
  /** 书总数 */
  total: number
  /** 可安全移动的条目数（不含冲突项） */
  movable: number
  /** 无系列或已在目标位置、无需移动的书 */
  unchanged: number
  /** 涉及的系列数 */
  series_count: number
  /** 其中会换 book_id 的条数（需搬关联数据） */
  id_changing: number
}

export interface KomgaLayoutResult {
  moved: Array<{ old: string; new: string }>
  errors: Array<{ old: string; error: string }>
  count: number
  /** 搬迁了关联数据的条目数 */
  remapped: number
  /** 清理掉的空系列目录数 */
  pruned_dirs: number
}

export interface DuplicateGroup {
  key: string
  reason: string
  /** 组内最小书名相似度（%）：这组「最不像的一对」的得分，判定强度最诚实的体现 */
  similarity: number
  title: string
  author: string
  /** **跨库重复**：成员分属不同书库（「全部书库」范围下最该先看的那批） */
  cross_library?: boolean
  items: DuplicateItem[]
}

export interface MissingItem {
  name: string
  size: number
  mtime: number
  issues: string[]
  library_id?: string | null
}

/** 同名冲突组里的一条（`/api/library-conflicts`）。 */
export interface ConflictItem {
  name: string
  library_id: string | null
  library_name: string
  format?: string
  size?: number
  mtime?: number
  /** 保留项：不动它，改的是同组其余项（改一个就够消除冲突） */
  keep: boolean
  /** 建议名（后端给的口径；第 87 期起同名的不同目录会带目录名区分），保留项为空串 */
  suggest: string
  /** 卷号签名（`Vol.01` → `"1"`；解析不出为空串）—— 第 87 期加，用于说清结论 */
  volume?: string
}

/** 冲突组的结论（第 87 期，后端 `library.conflict_kind`）：界面据此写提示与默认勾选。 */
export type ConflictKind = 'cross_library' | 'duplicate_scan' | 'same_name_different_dirs'

export interface ConflictGroup {
  id: string
  name: string
  title: string
  /** **跨库**冲突：分属不同库，最该先处理（阅读数据会张冠李戴） */
  cross_library: boolean
  library_count: number
  keep: string
  suggest: string
  /** 这一组到底是什么：`duplicate_scan`（同一个文件被扫两遍）**不该改名** */
  kind?: ConflictKind
  /** 组级结论的中文说明，直接展示给用户 */
  reason?: string
  items: ConflictItem[]
}

/** 同一本书的**副本**组（第 87 期 `/api/library-copies`）：没撞 id、不需要改名。 */
export interface CopyItem {
  name: string
  size: number
  mtime: number
  /** 建议保留的那一份（体积最大者更完整） */
  keep: boolean
}

export interface CopyGroup {
  library_id: string
  dir: string
  key: string
  count: number
  keep: string
  reason: string
  items: CopyItem[]
}

export interface CopiesResult {
  items: CopyGroup[]
  total: number
  libraries: Array<{ id: string; name: string }>
}

export interface ConflictsResult {
  groups: ConflictGroup[]
  total: number
  /** 其中跨库冲突组数 */
  cross_library: number
  libraries: Array<{ id: string; name: string }>
}

/** 待展开的容器条目（`/api/library-containers`，第 87 期）。 */
export interface ContainerItem {
  id: string
  name: string
  library_id?: string | null
  size: number
  /** 能不能展开（false = 容器里没有可落地的文档；界面要如实说，不假装能） */
  unpackable: boolean
  reason: string
  /** 展开后会得到的文件名 */
  targets: string[]
}

export interface ContainersResult {
  items: ContainerItem[]
  total: number
  libraries: Array<{ id: string; name: string }>
}

/** 展开的逐条结果（`POST /api/books/{bid}/unpack`，第 87 期）。 */
export interface UnpackAction {
  /** repackage = 整份另存（改了后缀的 EPUB）/ extract = 从容器里取一个条目 */
  kind: 'repackage' | 'extract'
  name: string
  dest: string
  ok: boolean
  /** 失败原因（撞名 / 读不到 / 写失败）—— 逐条如实报，不整批失败 */
  note: string
}

export interface UnpackResult {
  name: string
  ok: boolean
  reason: string
  source_removed: boolean
  actions: UnpackAction[]
}

// ---------- 书源：导入 / 台账 / 登录 / 验证（第 86 期能力的界面接线）----------
// ⚠️ 涉及凭据的接口**一律只回「有没有设置」**，绝不回值（后端口径，界面不要试图显示明文）。

/** 导入差异表的一行（`POST /api/sources/import` 的 dry-run 结果）。 */
export interface SourceImportRow {
  name: string
  display_name: string
  group: string
  source_type: string
  supported: 'yes' | 'partial' | 'no'
  /** duplicate=内容相同（幂等）；update=同一个源的新版；conflict=撞名/同站点；unsupported=不可执行 */
  verdict: 'new' | 'update' | 'duplicate' | 'conflict' | 'unsupported'
  unsupported_fields: Array<{ field?: string; why?: string; instead?: string }>
  notes: string[]
  dedup_key: string
  rule_hash: string
  /** 撞上谁（冲突 / 更新时才有） */
  conflict_with: string
  changed_fields: string[]
}

export interface SourceImportItem {
  name: string
  verdict: string
  action: string
  ok: boolean
  note: string
}

export interface SourceImportResult {
  dry_run: boolean
  origin: string
  rows?: SourceImportRow[]
  items?: SourceImportItem[]
  counts?: Record<string, number>
}

/** 台账一行（`GET /api/sources/ledger`，**不含** raw_json：那是整条源原文，列表不必背）。 */
export interface SourceLedgerRow {
  name: string
  origin: string
  dedup_key: string
  rule_hash: string
  supported: 'yes' | 'partial' | 'no'
  source_type: string
  group_name: string
  unsupported: Array<{ field?: string; why?: string; instead?: string }>
  notes: string[]
  enabled: boolean
  imported: boolean
  imported_at: number
  updated_at: number
  verified_at?: number | null
  verify_ok?: boolean | null
  verify_count: number
  verify_ms: number
  verify_error: string
  last_update_at?: number | null
  last_update_note: string
}

export interface SourceHistoryItem {
  id: string
  name: string
  kind: string
  rule_hash: string
  note: string
  created_at: number
}

/** 登录态：**只有元数据**（有没有、几条、哪些域），没有任何 cookie 值。 */
export interface SourceCookieStatus {
  name: string
  domains: string[]
  has?: boolean
  count?: number
  mtime?: number
  size?: number
  names?: string[]
}

/** 变量：`keys` 只回答「某个键设没设」，**值永不下发**。 */
export interface SourceVarsResult {
  name: string
  keys: Record<string, boolean>
  referenced: string[]
}

/** 登录面板的全部输入（由书源自己的声明驱动，不写死站点）。 */
export interface SourceLoginSpec {
  name: string
  has_declaration: boolean
  needs_cookie: boolean
  open_url: string
  instructions: string
  note?: string
  vars: Array<Record<string, unknown>>
  unsupported: Array<Record<string, unknown>>
  cookie?: SourceCookieStatus
  keys?: Record<string, boolean>
  referenced?: string[]
}

export interface ConflictApplyResult {
  renamed: Array<{ old: string; new: string; library_id: string }>
  errors: Array<{ old?: string; error: string }>
  count: number
  /** 搬迁了关联数据的条数（改名必然换 book_id，所以正常 = count） */
  remapped: number
}

export interface RecycleResult {
  moved: Array<{ name: string; moved_to: string; library_id?: string | null }>
  errors: Array<{ name: string; error: string }>
  recycle_dir: string
  keep?: string
}

// ---------- 书库（图书馆浏览 / 书籍详情） ----------

export interface BookChapter {
  /**
   * 段内序号（**每段从 1 重新计**，第 85 期口径不变）。
   * ⚠️ **缺省 = 无编号条目**（楔子 / 序章 / 番外 / 后记…）：它们不参与编号，
   * 目录里不显示序号。
   */
  num?: number
  title: string
  /** 在 EPUB spine 中的顺序索引，阅读器据此加载正文 */
  index?: number
}

export interface BookVolume {
  /**
   * 段名：卷段是卷名（`第一卷`）；**无名段是空串** —— 显示层统一叫法
   * （见 `lib/chapterGroups.ts` 的 `groupLabel`），数据侧不留一个假卷名。
   */
  volume: string
  /**
   * 无编号条目的前后段标记：`front`（卷前：楔子 / 序章 / 引子 / 前言）/
   * `back`（卷尾：番外 / 后记 / 尾声 / 终章）；卷段与无名正文段**没有这个字段**。
   */
  kind?: 'front' | 'back'
  chapters: BookChapter[]
}

export interface BookFile {
  name: string
  format: string
  size: number
  mtime: number
}

/**
 * 「这本书在磁盘上的位置」（第 63 期 5/6，决策 6）。
 *
 * 与 `BookDetail.files` 分开是有意的：`files` 是与请求者无关的资源表示，
 * 这个响应**取决于谁在问**（本机/局域网才给绝对值），所以单独一个端点、
 * 单独一次请求、`no-store`。键与 `files[].name` 同一套取值，两边能对上。
 */
export interface BookLocalPaths {
  /** 服务端判定「这次请求来自本机/局域网」。false 时 `paths` 恒空 */
  local: boolean
  /** 库内相对路径 → 服务器绝对路径。含主文件本身与同 stem 的兄弟文件 */
  paths: Record<string, string>
}

/** 书架网格与详情页共用的书籍卡片（对齐 docs/bookorbit/bookorbit-library-contract.md）。 */
export interface BookCard {
  id: string
  name: string
  title: string
  author: string
  series: string
  /** 真实阅读状态；**null = 没设过状态**，界面用进度兜底推导（不能当 unread 用） */
  status?: 'unread' | 'reading' | 'finished' | 'paused' | 'abandoned' | null
  started_at?: number
  finished_at?: number
  /** 系列内序号（字符串，空串 = 无）。解析见 core/library._series_index_of */
  series_index?: string
  has_cover: boolean
  format: string
  size: number
  mtime: number
  /** 封面占位渐变（oklch），由后端按 id 派生，保证稳定 */
  c1: string
  c2: string
  tags: string[]
  /** 演播者（第 53 期）；有声书才可能有值，列表形态与 tags 同构 */
  narrators: string[]
  year: string
  publisher: string
  isbn: string
  language: string
  /**
   * 简介。⚠️ **列表接口不下发正文**（第 68 期：它曾占 `/api/books` 体积的 68%），
   * 只有详情接口（`/api/books/{bid}`）带它；列表侧要判「有没有简介」看 `has_description`。
   */
  description?: string
  /** 列表侧判「这本书有没有简介」——正文只在详情里（第 68 期） */
  has_description?: boolean
  issues: string[]
  /** 阅读进度 0-100（由 /api/books 附加，来自 SQLite） */
  percent?: number
  /** 最近阅读时间戳（秒） */
  updated_at?: number
  /** 批注数量 */
  annotation_count?: number
  /** 所属收藏夹 id 列表（由 /api/books 附加；不在任何夹里 = 空数组） */
  collection_ids?: number[]
  /** 评分 1–5；**0 = 未评分**（未评分不用 0 星表示，见 core/db.py 的说明） */
  stars?: number
  /** 页数——**估算值**：EPUB 没有固定页数概念，见 core/library._pages_in */
  pages?: number
  /** 页数来源：'estimate'（EPUB 估算）/ 'archive'（漫画归档真实页数）/ 空串 */
  pages_source?: string
  /**
   * 固定版式（pre-paginated）：整页已排好版，重排设置（字号 / 行高 / 首行缩进 / 分栏…）
   * 对它没有意义，页宽也由书本身决定 —— 阅读器据此不套用重排偏好。
   * 由后端读 OPF 的 `rendition:layout` 判定（core/library._fixed_layout_of）；
   * 非 EPUB 恒 false。
   */
  fixed_layout?: boolean
  /** 有声书轨数（单文件 1、目录 n）；非音频为 0 或未定义 */
  tracks?: number
  /** 所属书库 id（第 10 期多书库；`name` 仍是**相对该库根**的路径） */
  library_id?: string
  /** 所属书库类型（ebook / comic / audiobook / mixed） */
  library_type?: LibraryType
}

/** 书城目录来源的**注册表条目**（第 85 期批次 B）：`usable` 与 `blocked_reason` 由后端算好。 */
export interface TocSourceItem {
  id: string
  label: string
  home: string
  /** `available` 内置规则可用；`needs_credentials` 要登录凭据；`unsupported` 本批没写规则 */
  status: 'available' | 'needs_credentials' | 'unsupported'
  /** ⚠️ 规则是否**在本机验证过**。false 的必须显示成「未验证」—— 拿不准就说不准。 */
  verified: boolean
  note: string
  usable: boolean
  /** 不可用时的原因原文（空串 = 可用） */
  blocked_reason: string
}

/**
 * 一本书在某个来源上的**一次取目录结果**（第 85 期批次 B）。
 *
 * ⚠️ `ok: false` 的行**不是错误数据**，而是「上次没取到」的事实：界面据此如实显示原因，
 * 后端也不会因此反复外呼（负结果同样落库）。
 */
export interface TocSourceRow {
  source: string
  label: string
  /** 来源自身的档位说明（如「需要登录凭据」） */
  state: string
  ok: boolean
  /** 失败原因原文（`ok=false` 时可直接展示） */
  note: string
  /** 用户手动指定过书页 ⇒ 视为确定 */
  manual: boolean
  confidence: number
  matched_title: string
  store_ref: string
  fetched_at: number
  /** 书城那份有多少条 */
  entry_count: number
  /** 其中已对齐到本地章节的条数 */
  mapped: number
}

export interface BookDetail extends BookCard {
  chapters: BookVolume[]
  files: BookFile[]
  /** 书城目录来源状态清单（第 85 期批次 B；空数组 = 这本书没取过） */
  toc_sources?: TocSourceRow[]
  /** 当前生效的书城来源 id；空串 = 用的是**本地目录** */
  toc_applied?: string
  /** 有声书专有：轨清单（随详情一起下发，播放器首屏无需再请求一次） */
  audio_tracks?: AudioTrack[]
  /** 序号单元合集的**话清单**（第 73 期；随详情下发，阅读器首屏无需再请求一次） */
  units?: UnitItem[]
}

/** 单条音轨（目录型有声书里一章一文件） */
export interface AudioTrack {
  index: number
  name: string
  size: number
}

/**
 * 一「话」（第 73 期）：序号单元合集里的一个文件。
 *
 * `name` 是**相对树根**的 posix 路径（`第1卷/第1话.pdf`）—— 目录里显示它，媒体 URL
 * 只按 `index` 拼；`num` 是解析出的序号（解析不出的为 0，且排在最后，不猜位置）；
 * `kind` 决定用哪个阅读器（`pdf` → PdfReader / `comic` → ComicReader / `audio` → AudioPlayer）。
 */
export interface UnitItem {
  index: number
  name: string
  num: number
  kind: 'pdf' | 'comic' | 'audio' | string
  size: number
}

/**
 * 交给单个阅读器的「当前话」（第 73 期）。
 *
 * 三个复用阅读器（ComicReader / PdfReader / AudioPlayer）拿到它就进入**单话模式**：
 * 数据源换成 `/units/{index}/…`、进度**由上层记**（它们不读不写），读完发 `unitEnd`
 * 让上层翻下一话。
 *
 * - `within`：这一话内要恢复到哪（0–1）—— 上层从跨话的 `percent` 反推出来
 *   （见 `lib/unitsProgress.ts`），子阅读器自己换算成页码 / 秒数；
 * - `total`：整本书有多少话 —— 子阅读器报**阅读时长**快照时要算全书百分比
 *   （它只知道这一话的页码，不知道全书有多大）。
 */
export interface UnitRef {
  index: number
  total: number
  name: string
  within?: number
}

/**
 * 子阅读器 → 上层的**话内进度上报**（第 73 期）。
 *
 * `index` 是「这是哪一话」—— 上层**必须**核对它：换话时旧话的那个组件会先卸载，
 * 而卸载钩子里还有一次收尾上报（把最后位置落盘），那一刻上层手里的 `index` 已经
 * 是新话了。不核对就会把「第 3 话读到一半」写成「第 4 话读到一半」。
 */
export interface UnitPos {
  index: number
  within: number
  locator: number
}

// ---------- 账户（单用户轻登录） ----------

export interface AuthResult {
  token: string
  user: string
}

export interface MeInfo {
  user: string
}

/** 账号资料（第 25 期）：展示名 / 时区 / 头像分发 URL。 */
export interface AccountProfile {
  username: string
  display_name: string
  timezone: string
  avatar_path: string
  avatar_url: string | null
}

// ---------- 阅读器：章节内容 / 进度 / 批注 ----------

export interface ChapterContent {
  index: number
  total: number
  title: string
  /** 章节正文 HTML（资源 URL 已改写为后端接口） */
  html: string
}

export interface ProgressState {
  locator: number
  percent: number
  /** 精确阅读位置（第 54 期）：EPUB CFI，空串 = 没有（回落「章 + 全书百分比」） */
  cfi?: string
  /** 服务端把 CFI 反解出的章内字符偏移（textContent 坐标）；仅在能反解时返回 */
  offset?: number
  /**
   * 服务端写入时间戳（第 56 期）：多设备进度提示的比较基准 ——
   * 比「本机已知的最新写入」更新的写入才可能是别的设备。
   */
  updated_at?: number
  /**
   * 这一行说的是**哪个文件**（第 63 期 4/6，库内相对路径，与
   * `reading_sessions.file_rel` 同一套取值约定）。书级查询时它是**答案的一部分**：
   * 「读到 60%」说的是哪个文件读到 60%，「继续阅读」据此指向对的文件。
   * 空串 = 「这本书自己 / 不知道文件」（KOReader 同步 / Komga / 标记已读完的写入）。
   *
   * ⚠️ **`null` = 这一行压根不存在**（服务端在查不到行时回 null，见
   * `server.api_get_progress`）。判「有没有读过」**必须**看它，不能看 `locator === 0`
   * —— 第 0 章 / 第 1 页是合法位置，两者会混。
   */
  file_rel?: string | null
}

export interface Annotation {
  id: number
  /**
   * 章节**序号**；**`-1` = 序号未知**（设备只给得出章节标题，见 `chapter_title`）。
   *
   * ⚠️ 别照 `chapter + 1` 硬渲染 —— 那会把「不知道」显示成「第 1 章」，是编造。
   * 显示一律走 `chapterLabel()`（`lib/annotations.ts`）。
   */
  chapter: number
  quote: string
  color: string
  note: string
  style: string
  created_at: number
  /** 来源枚举：`web` / `koreader` / `kobo`。 */
  origin?: string
  /**
   * 来源给的章节**标题**（设备批注才有；本应用自己写的批注留空 —— 它知道序号）。
   * 只在 `chapter < 0` 时有意义。
   */
  chapter_title?: string
  /**
   * 位置锚，**两列是两回事**（第 63 期 6/6，见 `lib/textAnchor.ts` 的文件头）：
   *
   * - `anchor`：**来源原生**的位置标识（KOReader 的 XPointer、Kobo 的 locator）。
   *   本项目**解析不了它** —— 没有对方那套排版。只用于导入去重与「这条是哪来的」。
   * - `start_off` / `end_off`：本应用**章内字符偏移**（半开区间 `[起, 止)`），
   *   由阅读器自己算，**真能定位**。`-1` = 无锚。
   *
   * 三者在老批注上都是空/`-1` —— 当时没记，补不回来，界面如实说明按文本定位。
   */
  anchor?: string
  start_off?: number
  end_off?: number
}

/**
 * 本地书签（第 34 期）。软删除语义与批注同构：`deleted_at` 0 = 活跃、> 0 = 在垃圾桶。
 * `anchor` 是**位置锚**（章序号 + 章内归一化位置），服务端按它去重 ⇒ 同一位置恒为同一条。
 */
export interface Bookmark {
  id: number
  book_id: string
  anchor: string
  chapter: number
  /** 全书百分比（列表排序 / 展示用） */
  percent: number
  label: string
  created_at: number
  /** 版本戳：并发合并时客户端回传它 */
  updated_at: number
  /** 0 = 活跃；> 0 = 在垃圾桶 */
  deleted_at?: number
}

/** 加书签的返回。`applied=false` = 并发冲突且服务端更新 ⇒ 库里未被改写，看 `server`。 */
export interface BookmarkSaveResult {
  ok: boolean
  id: number
  /** 新插入了一行 */
  created: boolean
  /** 复活了同位置的墓碑行 */
  revived: boolean
  applied: boolean
  server: Bookmark
}

// ---------- 阅读会话（第 63 期）----------

/**
 * 会话上报的可选字段。**每一个都可以不给**，不给就是「这次没记录」——
 * 服务端存「未知」哨兵，而不是 0。0% 与「没记录」是两个结论（前者是「翻回开头了」）。
 *
 * 带 `session_uid` = 「这是某一段阅读的又一次心跳」⇒ 服务端 upsert，一段只留**一行**；
 * 不带 = 「这是一次独立上报」⇒ 插新行。见 `lib/readingSession.ts`。
 */
export interface SessionExtra {
  session_uid?: string
  /** 这一段开始时的全书百分比（0–100）；只在开段那一次被服务端采纳 */
  start_percent?: number
  /** 此刻的全书百分比 */
  end_percent?: number
  /** 起始章节 / 音轨序号 */
  start_locator?: number
  /** 此刻的章节 / 音轨序号 */
  end_locator?: number
  /**
   * **书内**相对路径（多轨有声书的当前轨）。
   *
   * 空串 = **这本书自己**（单文件书 / PDF / 漫画都是这一类），不是「不知道哪一轨」——
   * 所以单文件书**不必给**，缺省与显式给空串是同一件事。
   */
  file_rel?: string
  /** `web`（阅读器）/ `audio`（播放器）/ `manual`（手工补录） */
  source?: string
}

/** 一条阅读会话（服务端已把「未知」转成 `null`）。 */
export interface ReadingSessionRow {
  id: number
  seconds: number
  started_at: number
  ended_at: number
  start_percent: number | null
  end_percent: number | null
  /** 本次读了多少（`end - start`）；两端任一未知就是 `null` —— 界面显示「—」而不是 0% */
  change: number | null
  start_locator: number | null
  end_locator: number | null
  file_rel: string
  source: string
}

/** 折线图上的一天：读了多少 + 那天结束时读到哪。 */
export interface ReadingDayPoint {
  date: string
  seconds: number
  sessions: number
  /** 当天最后一次已知位置；当天全是老数据就是 `null`（图上断线，不画到 0%） */
  end_percent: number | null
}

/** 单书阅读记录（`GET /api/books/{id}/stats`）。 */
export interface BookReadingStats {
  book_id: string
  /** **没读过就是 `null`**，不是全 0 对象（全 0 会把「没记录」渲染成「读了 00:00」） */
  reading: {
    seconds: number
    sessions: number
    avg_seconds: number
    active_days: number
    first_started: number
    last_ended: number
  } | null
  records: {
    longest_session: { seconds: number; ended_at: number; date: string }
    best_day: ReadingDayPoint
    busiest_day: ReadingDayPoint
    /** 历史**最长**连续天数（与全站「当前连续」不是一回事）；没有会话时为 `null` */
    longest_streak: { days: number; start: string; end: string } | null
  } | null
  /** 升序（折线图 x 轴） */
  days: ReadingDayPoint[]
  /** 降序（流水表），最多 200 条 */
  sessions: ReadingSessionRow[]
}

// ---------- 系列 ----------

export interface SeriesCover {
  id: string
  title: string
  c1: string
  c2: string
  /** 有内嵌封面时才去请求 /cover，避免为无封面的书发一堆注定 404 的请求 */
  has_cover?: boolean
}

export interface SeriesItem {
  name: string
  count: number
  authors: string[]
  covers: SeriesCover[]
  /** 系列简介（第 12 期 C3）：无值/未抓到时为空串，**有值才渲染** */
  description?: string
  source?: string
  score?: number
}

/** 系列内**按媒体**分组（第 10 期 C2）：同一系列可能横跨电子书 / 漫画 / 有声书 */
export interface SeriesGroup {
  /** ebook / comic / audiobook / other */
  media: string
  label: string
  count: number
  books: BookCard[]
}

/**
 * 系列级元数据生效值（第 12 期 C3）。
 *
 * ⚠️ 数据只存本项目服务端，**不写回 EPUB**（OPF 没有「系列简介」字段）；
 *    `owned_count` 与 `declared_count` 是两个概念，界面上不要混成一个「册数」。
 */
export interface SeriesMeta {
  name: string
  description: string
  publisher: string
  first_year: string
  tags: string[]
  /** 库里**实际拥有**的册数（本地聚合，必为真） */
  owned_count: number
  /** 外部**声明**的系列总册数（0 = 未知） */
  declared_count: number
  overridden: Record<string, boolean>
  /** 在线来源（openlibrary / googlebooks / ''）与一致性打分 —— 界面据此如实展示置信度 */
  source: string
  score: number
  fetched_at: number
}

/** 逐字段明细（编辑器渲染「已本地修改」徽标与「恢复在线」用） */
export interface SeriesMetaFieldState {
  value: string | string[]
  online: string | string[]
  aggregated: string | string[]
  local: string | string[]
  overridden: boolean
}

export interface SeriesMetaState {
  description: SeriesMetaFieldState
  publisher: SeriesMetaFieldState
  first_year: SeriesMetaFieldState
  tags: SeriesMetaFieldState
}

/** 重排预览的一条：**只写服务端序号、不动文件名也不改文件**（book_id 不变 → 进度不断链） */
export interface SeriesRenumberItem {
  name: string
  book_id: string
  title: string
  format: string
  old_index: string
  new_index: string
  changed: boolean
}

export interface SeriesDetail {
  name: string
  count: number
  books: BookCard[]
  /** 按媒体分组（组内保持扫描顺序；只有多于一组时前端才显示组标题） */
  groups?: SeriesGroup[]
  /** 系列级元数据（单系列查询走完整分层，含成员书聚合） */
  meta?: SeriesMeta
  meta_state?: SeriesMetaState
  /** 缺册（第 43 期）：见 SeriesGaps —— 后端唯一真值源，前端不再自己算 */
  gaps?: SeriesGaps
}

/**
 * 系列缺册（第 43 期）。`missing` 是 `[1..max_index]` 里缺的数字册号（中间空洞与尾部缺口都算）；
 * 无序号 / 非数字序号各自单列、**不**并入缺册（否则每本没序号的书都会凭空造出一个「缺 1」）。
 */
export interface SeriesGaps {
  missing: number[]
  max_index: number
  numbered: number
  unnumbered: number
  has_unnumbered: boolean
  non_numeric: number
  has_non_numeric: boolean
  total: number
}

/**
 * 阅读尝试（轮次，第 43 期）：一轮 = 「开始读 → 读完」。
 * `finished_at === 0` 表示该轮进行中；读完后重新开始 = 新一轮（`round` 递增）。
 */
export interface ReadingAttempt {
  id: number
  book_id: string
  round: number
  started_at: number
  finished_at: number
  status: 'reading' | 'finished'
  created_at: number
}

// ---------- 作者 ----------

export interface AuthorItem {
  name: string
  count: number
  series: string[]
  covers: SeriesCover[]
  /** 是否有本地缓存的头像（有则去 `/api/authors/{name}/photo` 取图） */
  has_photo: boolean
  /**
   * 排序名（本地覆盖 > 在线），空串 = 没设 ⇒ **排序时回退到 `name`**。
   *
   * 列表接口只给生效值、不给 `*_overridden` 标记 —— 「按姓名」排序用不上它，
   * 少下发一个字段就少一处被误用的机会（覆盖标记只在详情/写接口里给）。
   */
  sort_name: string
  /** 名下最早一本书的入库时间（秒），用于「本周新增」筛选 */
  added_ts: number
}

export interface AuthorDetail {
  name: string
  count: number
  books: BookCard[]
  /** 传记（本地覆盖 > 在线抓取），无则空串 */
  bio: string
  /** 传记是否被用户本地覆盖（受抓取保护） */
  bio_overridden: boolean
  /** 排序名（本地覆盖 > 在线），空串 = 按显示名排序 */
  sort_name: string
  /** 排序名是否被用户本地覆盖（受抓取保护） */
  sort_name_overridden: boolean
  /** 是否有头像（本地缓存的在线照片 或 用户上传） */
  has_photo: boolean
  /** 头像是否被用户本地覆盖（上传过头像） */
  photo_overridden: boolean
  /** 头像在线来源（如 openlibrary），空串 = 无 */
  photo_source: string
  /** 在线抓取时间戳（秒），0 = 未抓取过 */
  fetched_at: number
  /** 名下最早一本书的入库时间（秒） */
  added_ts: number
}

/** 作者元数据写操作的返回（btw BIO / 排序名 / 头像 / 抓取接口，只回生效信息不含书目） */
export interface AuthorMeta {
  ok?: boolean
  name: string
  bio: string
  bio_overridden: boolean
  /** 排序名（本地覆盖 > 在线），空串 = 按显示名排序 */
  sort_name: string
  /** 排序名是否被用户本地覆盖（受抓取保护） */
  sort_name_overridden: boolean
  has_photo: boolean
  photo_overridden: boolean
  photo_source: string
  fetched_at: number
  /** 仅抓取接口返回：本次抓取结果 */
  result?: { ok: boolean; bio?: string; has_photo?: boolean; error?: string }
}

// ---------- 批注总览 ----------

/**
 * 批注总览的一行 = `Annotation` + 书名作者 + 墓碑。
 *
 * **继承而不是重抄一遍**：服务端 `GET /api/annotations` 走的是同一份列清单
 * （`db._ANNO_COLS_FULL`），手抄一份就会漏 —— `chapter_title` / `anchor` /
 * `start_off` / `end_off` 四列当初就漏在这份声明里，而运行时一直是有值的，
 * 于是类型在骗人：按 `AllAnnotation` 写代码的人会以为没有章节标题可用。
 */
export interface AllAnnotation extends Annotation {
  book_id: string
  book_title: string
  book_author: string
  /** 0 = 活跃；> 0 = 在垃圾桶（软删除时刻）。仅在 `include_trashed=1` 时有意义。 */
  deleted_at: number
}

/** 批注总览统计。上游同名字段还有 needsReview / devices，本项目无对应数据源故不返回。 */
export interface AnnotationOverview {
  active: number
  trashed: number
  /** 有过批注的周数（同一周多条只算一周） */
  weeks: number
  /** 最长的一段「连续无批注」周数，含最后一次批注到本周的空档 */
  longest_quiet_weeks: number
}

/**
 * KOReader 批注导入（`POST /api/annotations/import-koreader`）的返回。
 *
 * `files` 只列出**真的找到了导出文件**的书 —— 没有导出文件的书不在里面，
 * 这不是错误，只是没东西可导。`totals.skipped` 是文件里被**有意跳过**的条目数
 * （没有引文的书签、没有位置的条目），每一项的原因在 `files[].stats` 里分开记。
 */
export interface KoreaderImportResult {
  applied: boolean
  /** 找到的导出文件数 */
  scanned: number
  /** 其中读得懂、能导的（`scanned - with_file` = 读不懂的那几个） */
  with_file: number
  /** ⚠️ 恒为空 —— 我们是「按书找文件」，书不在库里就不会去看它（见后端注释） */
  unmatched: unknown[]
  files: {
    path: string
    book: string
    book_id: string
    /** 非空表示这个文件没读成（整份跳过），原因写在这里 */
    error: string
    items: number
    skipped: number
    device_id: string
    stats: Record<string, number>
    imported?: Record<string, number>
  }[]
  totals: {
    added: number
    updated: number
    unchanged: number
    trashed: number
    no_anchor: number
    no_quote: number
    skipped: number
    files: number
  }
}

/**
 * 侧栏「浏览」组的三计数（第 34 期）。
 * `authors` / `series` / `annotations` 与各自目标页**同源**（等于页面上会列出的条数）；
 * `cached` = 服务端 60 秒节流命中了缓存（数字可能比数据晚至多一分钟）。
 */
export interface BrowseCounts {
  /** 空串 = 全部书库 */
  library_id: string
  authors: number
  series: number
  annotations: number
  books: number
  computed_at: number
  cached: boolean
}

// ---------- 收藏夹 ----------

export interface CollectionItem {
  id: number
  name: string
  count: number
  created_at: number
  /** 最后修改时间（秒）；成员增删或重命名都会刷新（第 47 期） */
  updated_at: number
  /** 首本成员的书 id（用于总览卡封面预览）；无成员为 null */
  first_book_id: string | null
  /** 首本成员是否有真实封面 */
  first_book_has_cover: boolean
}

export interface CollectionDetail {
  id: number
  name: string
  books: BookCard[]
}

// ---------- 数据统计 ----------

export interface StatsTop {
  name: string
  count: number
}

/** 体积榜一项（对应上游 `LargestBookItem`；snake_case 是本项目接口口径） */
export interface LargestBook {
  id: string
  title: string
  size_bytes: number
  format: string
}

export interface RecentRead {
  id: string
  title: string
  author: string
  percent: number
  updated_at: number
}

/**
 * 页数的五数概括（箱线图用），按格式分组。
 *
 * ⚠️ `pages` 的 0 是「不知道」不是「0 页」（EPUB 是估算值、漫画是归档实际值、
 * 其余格式恒 0），所以**只有 pages > 0 的书进这个序列** —— 否则 PDF / 有声书
 * 会在箱线图上压出一根假底线。`sources` 是页数来源构成，界面据此如实标注。
 */
export interface StatsPagesByFormat {
  format: string
  count: number
  min: number
  q1: number
  median: number
  q3: number
  max: number
  /** 来源构成：estimate（估算）/ archive（归档实际值）/ unknown */
  sources: Record<string, number>
}

export interface StatsOverview {
  books: {
    total: number
    size: number
    by_format: Record<string, number>
    /** 出现过的语言数 */
    languages: number
  }
  authors: { total: number; top: StatsTop[] }
  series: { total: number; top: StatsTop[] }
  publishers: { total: number; top: StatsTop[] }
  /** 题材：来自 EPUB 的 dc:subject，一本书可贡献多个 */
  genres: { total: number; top: StatsTop[] }
  /** 出版年份按十年聚合（逐年噪声太大）；unknown = 没写年份的书 */
  years: { known: number; unknown: number; decades: Array<{ decade: number; count: number }> }
  /** 全库平均阅读进度（0–100，含未读书的 0） */
  avg_progress: number
  /**
   * 书库体检。
   *
   * 前 5 个是**计数**（哪一类有问题、各几本，可照着修）；后 8 个是**百分比口径**
   * （对齐上游 `LibraryIntegrityGauge` 的四值：Integrity 综合分 + Present / Primary /
   * Metadata 三项覆盖率）。两者是增补关系，不是替代 —— 计数键一直在，别删。
   */
  integrity: {
    missing_author: number
    missing_language: number
    no_cover: number
    zero_size: number
    unparsable: number
    /** 分母（= books.total） */
    total_books: number
    /** 文件有实体内容（非 0 字节）的本数 */
    present: number
    present_percent: number
    /** 主文件能被解析出结构的本数 */
    primary: number
    primary_percent: number
    /** 元数据完整度达标（评分 ≥ 70）的本数 */
    metadata: number
    metadata_percent: number
    /** 综合分：三项覆盖率的算术平均（0–100） */
    score: number
  }
  /**
   * 元数据完整度评分摘要（`metascore._summarize`）。第 33 期之前就在响应里，
   * 只是 `StatsOverview` 漏了这座键 —— 补上类型，契约不变。
   *
   * ⚠️ `buckets` 是**常量分档表**：`< 50` / `50–69` / `70–89` / `90+` 永远 4 条，
   * 空库给的是「4 条计数全 0」而不是空数组。判空要看 `total`（= `books.total`）。
   */
  metadata_score: {
    total: number
    avg: number
    /** 分位（线性插值，与 `metascore.percentile` 同口径） */
    p25: number
    p50: number
    p75: number
    p90: number
    min: number
    max: number
    buckets: Array<{ key: string; label: string; count: number; percent: number }>
  }
  /**
   * 体积榜（Top 50 Largest Books）：按 size_bytes 降序，**固定最多 50 条**，
   * 不随 `top` 参数伸缩（`top` 管的是作者/系列/出版社/题材四个计数器榜）。
   */
  largest: LargestBook[]
  reading: {
    unread: number
    reading: number
    finished: number
    annotations: number
    /** 累计阅读秒数 */
    seconds: number
    /** 会话次数 */
    sessions: number
    /** 平均每次会话秒数 */
    avg_seconds: number
    /** 当前连续阅读天数 */
    streak: number
    /** 累计有阅读记录的天数 */
    days: number
  }
  /** 近 N 天每日入库数量（索引 0 = N 天前，末尾 = 今天）。字段名保留历史叫法，长度跟随 window */
  added_28d: number[]
  /** 本月入库数量 */
  added_month: number
  /** 会话开始时段分布（24 小时） */
  hours: number[]
  /** 近 N 天每日阅读秒数。字段名保留历史叫法，长度跟随 window */
  reading_28d: number[]
  /** 本次返回的节奏图窗口（天）——两个 28d 命名的数组的实际长度 */
  window: number
  /** 统计范围回显：**空串 = 全部书库**（第 30 期按库筛选）；界面据此标注口径 */
  library_id: string
  recent: RecentRead[]

  // ---- 第 32 期图表序列 ----
  // 上游统计页是「一张图一个 composable 一次请求」，本项目是单接口共享一份 overview，
  // 故这些序列一次算齐。全部是**新键**，上面那些一个都没动（8 个仪表盘部件读它们）。
  // 一律**跟随 `library_id`**：书库侧从书目算，阅读侧靠「这本书属于哪个库」过滤。

  /** 语言分布（未知语言归到 `"?"`，照 by_format 的惯例）；书库侧 */
  by_language: Record<string, number>
  /** 按格式的体积（字节）；书库侧。各值之和 = `books.size` */
  by_format_size: Record<string, number>
  /** 按格式的页数五数概括（箱线图）；只含 pages > 0 的书，见 StatsPagesByFormat */
  pages_by_format: StatsPagesByFormat[]
  /** 全时段按月入库（按成品文件 mtime 的日历月），年月升序；书库侧 */
  added_monthly: Array<{ year: number; month: number; count: number }>
  /** 逐年出版（年份合法且已知的书），年份升序；书库侧 */
  publication_yearly: Array<{ year: number; count: number; top_titles: string[] }>
  /**
   * 进度漏斗五档（阅读侧）。⚠️ **只走进度、不走真实状态** —— 真实状态允许把
   * 20% 的书标成 finished，跟着它走会出现「后档比前档多」的畸形图。
   * 故各档**单调包含**：started ≥ reached25 ≥ reached50 ≥ reached75 ≥ completed。
   */
  progress_funnel: {
    started: number
    reached25: number
    reached50: number
    reached75: number
    completed: number
  }
  /** 按月读完（`finished_at`，本地日），年月升序；阅读侧 */
  completion_monthly: Array<{ year: number; month: number; count: number }>
  /**
   * 周几读多久，**索引 0 = 周日**（与 `Date.getDay()` 一致，不是 ISO 的周一）。
   * `days` = 该星期几在统计窗口里出现过几天 —— 界面算日均要用它，
   * 直接比总时长会在窗口不整除 7 天时造出「某个星期几总是最多」的假信号。
   * `events` = 该星期几的会话次数，只用于「样本够不够画」的判定（次数太少时
   * 日均时长没有意义，界面走「数据不足」而不是画一根噪声柱）。
   */
  weekdays: Array<{ weekday: number; seconds: number; days: number; events: number }>

  // ---- 第 33 期图表序列（书库侧）----
  // 同样是**新键**，上面一个都没动。字段顺序与 `core/stats.py` 的 `metascore.FIELDS`
  // 一致（后端定序，前端照单渲染）。

  /**
   * 按字段的元数据覆盖率（1x1 横条图）。分母是**在册书总数**，与元数据页
   * `metascore.payload()` 的字段覆盖率同口径 —— 封面 / 页数只对 EPUB 有意义，
   * 这里刻意不做格式归一，两个页面的数字必须能对上。
   */
  metadata_fields: Array<{
    key: string
    label: string
    present: number
    total: number
    percent: number
  }>
  /**
   * 按 书库 × 字段 的覆盖率（热力图）。⚠️ **唯一不跟随 `library_id` 的序列** ——
   * 它要回答「哪个库的元数据更完整」，跟随筛选就只剩一行、图本身失去意义。
   *
   * 行序 = `library.libraries()` 的顺序、列序 = `metascore.FIELDS` 的顺序，都由后端
   * 定死（前端自己排会让每次刷新出来一张不一样的热图）。0 本书的库**照样出行**、
   * `percent` 全 0：那是一条真实状态，藏掉会让人以为库不存在。
   */
  library_metadata: Array<{
    library_id: string
    library_name: string
    key: string
    label: string
    present: number
    total: number
    percent: number
  }>
  /**
   * 题材两两共现（弦图）。节点收敛到 12（弦一多就糊成一团），**只留两端都在节点
   * 集里的边**；对是无序的、书内重复题材已去重。
   */
  genre_cooccurrence: {
    nodes: Array<{ name: string; count: number }>
    links: Array<{ source: string; target: string; value: number }>
  }
  /**
   * 格式 × 月份的入库交叉序列（堆叠面积图）。**只给计数、占比由前端算** ——
   * 分母是「当月入库总数」，后端先折算成百分比的话 tooltip 就没法同时给出本数了。
   */
  format_share_monthly: Array<{ year: number; month: number; format: string; count: number }>
  /**
   * 出版年 → 入库滞后点集（散点图）。只收**出版年已知**的书（不知道出版年 ≠
   * 滞后 0 年），未标注的本数由界面用 `books.total − Σcount` 反推。
   */
  acquisition_lag: Array<{ added_year: number; lag_years: number; count: number }>

  // ---- 第 33 期图表序列（阅读侧）----
  // ⚠️ 三条各自的时间窗口**不统一**，也**不跟随 `days` 参数**（那个参数管的是入库与
  // 阅读节奏两张图的粒度）：完成耗时 5 年、题材阅读时长与会话形态 365 天。
  // 理由见 `core/stats.py` 文件头。

  /**
   * 开始读 → 读完的耗时分布（1x1 直方图 + 三个分位读数）。窗口 5 年。
   *
   * ⚠️ 分位数**无数据时是 `null` 而不是 0** —— 0 天会被读成「当天就读完」。
   * 只收 `started_at > 0 && finished_at >= started_at` 的书（结束早于开始是脏数据，
   * 记成负数会把 P50 拉到 0 附近）。
   */
  completion_latency: {
    total: number
    median_days: number | null
    p75_days: number | null
    p90_days: number | null
    buckets: Array<{
      label: string
      min_days: number
      /** `null` = 最后一档（`731d+`），没有上界 */
      max_days: number | null
      count: number
    }>
  }
  /**
   * 题材 × 阅读时长（矩形树图）。窗口 365 天，取前 30 个题材。
   *
   * ⚠️ **各题材之和 ≥ 窗口内实际总时长**：一本书的整段时长会计入它的**每个**题材
   * （与上游内连接后 `SUM` 的扇出同义）；**没打题材的书完全不进这张表**。
   */
  genre_reading: Array<{ genre: string; seconds: number }>
  /**
   * 阅读速度点集（散点图）。⚠️ **口径与上游不同**：上游要 per-session 的
   * `progressDelta`，本项目 `reading_sessions` 没有那一列，故换成**按书聚合**
   * （累计时长 × 当前进度）。已按 seconds 降序，前端照单渲染。
   */
  reading_pace: Array<{
    book_id: string
    title: string
    format: string
    seconds: number
    percent: number
  }>
  /**
   * 会话时间轴明细：**最近 400 条**（5 年窗内、按 `ended_at` 倒序），带书名与格式。
   * 本期只做只读渲染 —— 上游那张图能拖动改会话时间，那要新接口与冲突检测。
   */
  session_timeline: Array<{
    book_id: string
    title: string
    format: string
    started_at: number
    ended_at: number
    seconds: number
  }>
  /**
   * 会话形态点集（散点图）：x = 一天内的时刻（**小数小时**，9:30 → 9.5）、
   * y = 这次读了多少分钟，`weekday` 分色。
   *
   * 窗口 365 天、只收 **≥ 300 秒**的会话、最多 2000 条；按**开始**时刻定档
   * （按结束时刻会把跨零点的会话算到第二天）。`weekday` **0 = 周日**。
   */
  session_archetypes: Array<{ hour: number; minutes: number; weekday: number }>
}

// ---------- 应用设置（服务端持久化） ----------

export interface AppConfig {
  chapter_detection: { mode?: string; context_lines?: number; fallback?: string }
  traditionalize: boolean
  output: { format?: string; [k: string]: unknown }
  /** 成品**副本名**的默认命名规则（服务端持久化；每库可覆写，见 librarySettings） */
  naming: { pattern?: string; scope?: string }
  llm: { api_key: string; base_url: string; model: string; has_key: boolean }
  watcher: {
    enabled?: boolean
    interval?: number
    recursive?: boolean
    settle_seconds?: number
    stable_rounds?: number
    copy_non_txt?: boolean
    process_existing?: boolean
    max_retries?: number
    ignore?: string[]
  }
  network: { max_retries?: number; host_replace?: Record<string, string> }
  download: { enabled?: boolean; public_only?: boolean }
  logging: { dir?: string; max_entries?: number }
  /** 上传上限（字节）。此前后端对上传**完全没有限制**，见 server.py 的 _read_capped */
  upload: { max_bytes?: number; max_source_rules_bytes?: number }
  /** 成就统计与界面开关（对应上游 Profile 页的 Enable achievements） */
  achievements: { enabled?: boolean }
  /**
   * 多书库跨库策略（第 10 期）。库实体本身存 SQLite（见 `/api/libraries`）。
   * ⚠️ 第 77 期起**没有可编辑键**了：原先只有 `auto_migrate`（启动时静默按格式归库），
   * 随自动归库一并移除 ⇒ 后端 `GET /api/config` 现在回一个空对象。
   */
  libraries: Record<string, never>
}

/** 目录占用（维护页） */
export interface DirUsage {
  path: string
  files: number
  bytes: number
}

/** 维护页只读总览（`GET /api/maintenance`） */
export interface MaintenanceInfo {
  upload: { max_bytes: number; max_source_rules_bytes: number }
  overridden: string[]
  dirs: {
    input: DirUsage
    output: DirUsage
    cache: DirUsage
    backups: DirUsage
    recycle: DirUsage
  }
  library: { books: number }
}

// ---------- 回收站（第 81 期：台账 + 还原）----------

/** 回收站里的一条台账条目（`GET /api/recycle`）：知道它原来在哪、为什么被搬走 */
export interface RecycledItem {
  id: number
  /** 回收目录里的文件名（含时间戳前缀） */
  name: string
  /** 被移走前的绝对路径 —— 还原就搬回这里 */
  orig_path: string
  orig_dir: string
  why: string
  size: number
  created_at: number
  /** 磁盘上是否还在（用户手工删过回收目录时会是 false） */
  exists: boolean
  kind: 'file' | 'dir'
}

/** 无台账的孤儿条目（第 81 期之前的历史回收 / 用户手工丢进回收目录的东西） */
export interface RecycleOrphan {
  name: string
  /** 剥掉 `YYYYMMDD-HHMMSS_[n_]` 前缀后的名字（还原时用） */
  stripped: string
  stamp: string
  kind: 'file' | 'dir'
  size: number
}

export interface RecycleListPayload {
  /** 回收目录的绝对路径 */
  dir: string
  items: RecycledItem[]
  total: number
  orphans: RecycleOrphan[]
  orphan_total: number
}

/** 通知条目 = 活动日志条目 + 稳定 id 与已读态（`GET /api/notifications`） */
export interface NotificationItem extends LogItem {
  id: string
  read: boolean
}

/** 单条成就。`progress` 是实时算出来的，**不落库**（见 core/achievements.py） */
export interface AchievementItem {
  key: string
  name: string
  desc: string
  group: string
  metric: string
  target: number
  progress: number
  percent: number
  unlocked: boolean
  /** 0 表示未解锁 */
  unlocked_at: number
  /** metric 名拼错时为 false —— 用于暴露配置错误，而不是静默算成 0 */
  known_metric: boolean
}

export interface AchievementsOverview {
  /** 由「设置 → 个人资料 → 成就」控制；**关闭时 items 为空数组**、不判定也不解锁 */
  enabled: boolean
  items: AchievementItem[]
  groups: Array<{ group: string; total: number; unlocked: number }>
  total: number
  unlocked: number
  newly_unlocked: string[]
  metrics: Record<string, number>
  /** `backfillAchievements` 返回时为真：清空解锁记录后按当前数据重判（解锁时间被重置） */
  backfilled?: boolean
}

// ---------- 阅读活动（热力图 + 时间轴）----------

export interface ReadingHeatmapDay {
  date: string
  minutes: number
  sessions: number
}

export interface ReadingHeatmap {
  library_id: string
  year: number | null
  days: ReadingHeatmapDay[]
  total_minutes: number
  active_days: number
}

export type ReadingEvent =
  | { type: 'session'; ts: number; date: string; book_id: string; title: string; seconds: number }
  | { type: 'annotation'; ts: number; date: string; book_id: string; title: string; note: string; quote: string }
  | { type: 'achievement'; ts: number; date: string; key: string; name: string }

export interface ReadingActivity {
  heatmap: ReadingHeatmap
  timeline: {
    library_id: string
    events: ReadingEvent[]
    total: number
  }
}

/** 孤儿记录：引用了已不存在的书的数据库行（`GET /api/maintenance/orphans`） */
export interface OrphansInfo {
  /** 表名 → 孤儿书数 + 样例 book_id（便于确认清的是什么） */
  tables: Record<string, { books: number; sample: string[] }>
  total: number
  library_books: number
}

/** 可编辑的元数据字段（与后端 fileops.METADATA_FIELDS 一一对应） */
export interface BookMetadataFields {
  title: string
  author: string
  series: string
  series_index: string
  /** 出版年（OPF 里是 dc:date，书目里叫 year，接口层已映射） */
  date: string
  publisher: string
  language: string
  description: string
  isbn: string
  /** 题材；后端写入时会**去重且保序** */
  tags: string[]
  /** 演播者（第 53 期）；多值列表，写入时去重且保序 */
  narrators: string[]
  /** 副标题（第 63 期）。**不计入元数据完整度分**（与上游口径一致） */
  subtitle: string
  // ---- 提供商 ID（第 63 期，对齐上游的 CATALOG 组）----
  //
  // ⚠️ 这些字段**没有 OPF 对应物** —— 与 `narrators` 同一种待遇：经 `meta_override`
  // 落库、不写回书文件。所以「恢复在线」对它们 = 回落到在线抓取值、没有就为空。
  //
  // 只有 9 家源有字段：另外 4 家（comicvine / ranobedb / librofm / lubimyczytac）
  // 抓到的只是页面 URL，宁可留空也不把 URL 记成一个叫 `*_id` 的字段。
  /** Google Books 卷 ID（形如 `zyTCAlFPjgYC`） */
  google_books_id: string
  /** Goodreads 书目 ID（数字） */
  goodreads_id: string
  /** Amazon ASIN（10 位） */
  amazon_id: string
  /** Hardcover 书目 ID（数字） */
  hardcover_id: string
  /** Open Library work key（形如 `/works/OL1234W`） */
  openlibrary_id: string
  /** iTunes trackId / collectionId（数字） */
  itunes_id: string
  /** Kobo 书目 slug（Kobo 不对外给数字 ID，它用详情页 URL 末段定位） */
  kobo_id: string
  /** Aladin itemId */
  aladin_id: string
  /** Audible ASIN（audible 与 audnexus 两家同填这一个） */
  audible_id: string
}

/** 单字段的分层状态（编辑器渲染「已本地修改」徽标 / 恢复在线按钮用） */
export interface MetaFieldState {
  /** 当前生效值（override > online > opf） */
  value: string | string[]
  /** 在线抓取的候选值（空串 = 无在线建议） */
  online: string | string[]
  /** OPF 文件原值 */
  opf: string | string[]
  /** 是否已被用户本地覆盖（受抓取保护，再抓取不冲掉） */
  overridden: boolean
  /**
   * 第 35 期：该字段是否被**显式锁定**。
   *
   * 与 `overridden` **正交**（两种组合都成立）：`overridden` 是「改过就受保护」的隐式保护，
   * `locked` 是显式开关 —— 能锁住一个从没改过的字段，也能在改过之后解锁让抓取重新接管。
   * 作用面只到**抓取**：锁不挡手动编辑。
   */
  locked: boolean
}

/** 字段名 → 分层状态 */
export type MetaStateMap = Record<string, MetaFieldState>

/**
 * 提交给 `POST /api/books/{bid}/metadata` 的值（第 22 期起对所有格式一致）：
 *  - 字符串 / 字符串数组：正常写入 —— 非空值记成**服务端覆盖**，再抓取也不冲掉；
 *  - `null`：**显式清空**该字段（后端写「无值」标记）—— 该字段显示为空，
 *    且盖住在线的抓取值（之后抓取也不会把它填回来）；
 *  - 空串 / 空数组：**撤销覆盖**，回到「跟随在线 / 文件原值」（等同「恢复在线」）。
 */
export type BookMetadataWriteFields = {
  [K in keyof BookMetadataFields]?: BookMetadataFields[K] | null
}

/** `GET /api/books/{bid}/metadata` */
export interface BookMetadata {
  id: string
  name: string
  format: string
  /** 是否可编辑；第 22 期起**所有格式都是 true**（保留字段以便将来真有不可编辑的形态） */
  editable: boolean
  /** 生效值（override > online > opf） */
  fields: BookMetadataFields
  /** 逐字段明细（在线建议 / 是否已本地覆盖 / 是否已锁定） */
  meta: MetaStateMap
  /**
   * 被锁定的字段清单（第 35 期，按字段表顺序）。
   * 比 `meta` 多一项：**封面**用独立键 `cover`（不在 `BookMetadataFields` 里）。
   */
  locked: string[]
  /**
   * 自定义字段（第 35 期）：**只含该书适用且未归档**的定义 + 这本书的当前值，
   * 顺序即定义的排序。值不是 OPF 字段 —— 它们存 `book_custom_values`。
   */
  custom: CustomFieldState[]
}

/** `GET /api/books/{bid}/metadata/online` */
export interface MetadataOnlineResult {
  ok: boolean
  /** 在线候选字段值 */
  values: Partial<BookMetadataFields>
  source: string
  score: number
  /** 参与跨源字段级合并的源（第 58 期）；空 = 未合并 */
  merged_from?: string[]
  /** 逐字段来源（合并后不同字段可能来自不同源） */
  field_sources?: Record<string, string>
  message?: string
}

/** `POST /api/books/{bid}/metadata/revert` */
export interface MetadataRevertResult {
  ok: boolean
  fields: BookMetadataFields
  meta: MetaStateMap
  /** 实际恢复到在线值的字段 */
  recovered: string[]
}

/** 阅读状态行（`GET/PUT /api/books/{bid}/status`）。时间戳为 epoch 秒，0 = 未发生 */
export interface ReadingStatus {
  book_id: string
  status: 'unread' | 'reading' | 'finished' | 'paused' | 'abandoned'
  started_at: number
  finished_at: number
  updated_at: number
}

/** 评分 + 书评（`GET/PUT /api/books/{bid}/review`）。stars 0 = 未评分 */
export interface BookReview {
  book_id: string
  stars: number
  review: string
}

/** 相似书条目（`GET /api/books/{bid}/similar`）。reasons 说明为什么相似 */
export interface SimilarBook {
  id: string
  title: string
  author: string
  series: string
  series_index: string
  cover_url: string
  has_cover: boolean
  /**
   * **0–1 的加权总分**（第 35 期起；此前是 3.0 / 2.0 这样的裸分值）。
   * 口径：0.5·元数据余弦 + 0.1·同作者 + 0.25·题材 Jaccard + 0.1·同系列 + 0.05·评分接近度。
   * 界面只用 `reasons` 解释「为什么相似」，不展示这个数（换口径不会影响观感）。
   */
  score: number
  reasons: string[]
}

/** Reading Log 的单日行（`GET /api/reading-log`）。books 按当天时长倒序 */
export interface ReadingLogDay {
  date: string
  seconds: number
  sessions: number
  books: Array<{ id: string; title: string; seconds: number }>
}

export interface ReadingLogBook {
  id: string
  title: string
  author: string
  seconds: number
  sessions: number
  /** 平均单次时长（秒），后端 AVG(seconds) 算出 */
  avg_seconds: number
  /** 页数：非 EPUB 恒 0；阅读速度按此算 */
  pages: number
  /** 页数来源：'estimate'（EPUB 估算）/ 'archive'（漫画归档真实值）/ 空串（无可靠页数） */
  pages_source: string
  last_ended: number
}

export interface ReadingLogSession {
  book_id: string
  title: string
  seconds: number
  started_at: number
  ended_at: number
  /** 已格式化的结束时间（YYYY-MM-DD HH:MM，本地时区） */
  date: string
}

// ---------- 偏好模式 / 设备（按设备的偏好同步）----------

/** 偏好「模式」：具名的整套偏好快照（payload 五块，见 lib/prefsPayload.ts） */
export interface PrefProfile {
  id: number
  name: string
  payload: PrefsPayload
  created_at: number
  updated_at: number
}

/** 偏好「设备」：每台设备持有自己的一份配置 */
export interface PrefDevice {
  id: string
  name: string
  payload: PrefsPayload
  /**
   * 当前套用了哪个模式 —— **只是来源标记**：应用模式 = 拷贝内容，
   * 之后设备各改各的，改模式本体不影响它。null = 未套用。
   */
  active_profile_id: number | null
  created_at: number
  last_seen: number
}

/** 上传的阅读字体（`GET /api/fonts`）。id = 文件名，name = 字体族名（解析不出时回落文件名） */
export interface FontItem {
  id: string
  name: string
  /** 子样式（Regular/Bold…）；族名未解析出时是提示文案 */
  style: string
  size: number
  /** ttf / otf / woff / woff2 */
  format: string
  mtime: number
  /** 字重 100–900；解析不出为 null（回落浏览器合成 / 默认 400） */
  weight: number | null
  /** 是否斜体；解析不出为 null */
  italic: boolean | null
  /** 族名归一键；同一族的不同变体（Regular/Bold…）共享同一键以便分组。空串=不归组 */
  family_key: string
}

/** POST /api/books/batch 的返回：逐本执行，单本失败不影响其余 */
export interface BatchResult {
  ok: boolean
  /** 请求中的 id 总数 */
  total: number
  /** 成功处理的 book_id 列表 */
  succeeded: string[]
  /** 失败的（书不存在 / 参数非法），每项带原因 */
  failed: Array<{ id: string; error: string }>
}

/** POST /api/books/{bid}/metadata */
export interface MetadataWriteResult {
  ok: boolean
  /** 被接受的字段（已按白名单过滤） */
  written: string[]
  /** **实际发生变化**的字段（同值重写不在此列） */
  changed: string[]
  /** 提交了但不支持的字段 */
  unknown: string[]
  /** 回写的生效值 */
  fields: BookMetadataFields
  /** 回写的逐字段明细 */
  meta: MetaStateMap
  /** 第 35 期：写完后的自定义字段全量状态（含定义与值），前端直接替换 */
  custom: CustomFieldState[]
  /** 本次实际写入的自定义字段键 */
  custom_saved: string[]
  /** 提交了但该书不适用的自定义字段键（不静默丢，如实回报） */
  custom_ignored: string[]
}

/**
 * 自定义字段的**定义**（第 35 期，`/api/custom-fields`）。
 *
 * `key` 是稳定标识（值表按它引用，改 label 不动值），`label` 才是给人看的显示名。
 * `library_ids` 为空 = 全部书库；`archived` = 不进编辑界面（值不丢）；
 * `deleted_at > 0` = 在垃圾桶里（软删，可恢复，彻底删除走 purge）。
 */
export interface CustomFieldDef {
  id: number
  key: string
  label: string
  /** text / number / date / list（只约束录入，不是存储类型） */
  type: string
  position: number
  library_ids: string[]
  /** 抓取时给「还没有这一项」的书补的值（空 = 不参与抓取） */
  default_value: string
  archived: boolean
  created_at: number
  updated_at: number
  deleted_at?: number
}

/** 详情页里该书的自定义字段：定义 + 这本书当前的值（`list` 类型给数组） */
export interface CustomFieldState {
  key: string
  label: string
  type: string
  default_value: string
  value: string | string[]
}

export interface ConfigPayload {
  config: AppConfig
  overrides: Record<string, unknown>
  /** 被 settings.json 覆盖的点号键（提示「改了 config.yaml 但不生效」的原因） */
  overridden: string[]
  config_file: string
  settings_file: string
  backup_dir: string
}

/** config.yaml 原文 */
export interface RawConfig {
  exists: boolean
  text: string
  path: string
  mtime: number
  size: number
}

export interface BackupItem {
  name: string
  mtime: number
  size: number
}

// ---------- 库（第 10 期：库实体 / 格式分面 / 能力 / 迁移） ----------

/**
 * 格式分面（`/api/library-facets`）。
 *
 * ⚠️ 这就是第 10 期**改址**的旧 `/api/libraries` 语义：侧栏已不再用它
 * （书库页自带格式筛选），保留给需要按格式筛选的页面与既有调用方。
 */
export interface LibraryFacet {
  /** 筛选键：fmt:EPUB / issues:1 / nocover:1 */
  key: string
  label: string
  count: number
  kind: string
}

/** 库类型：决定功能显隐矩阵（见后端 core/features.py） */
export type LibraryType = 'ebook' | 'comic' | 'audiobook' | 'mixed'

/** 书库实体（`/api/libraries`，第 10 期起） */
export interface LibraryEntity {
  id: string
  name: string
  type: LibraryType
  type_label: string
  /** 第 41 期：该库所有文件夹的绝对路径（就地引用语义，跨根合法） */
  source_dirs: string[]
  /** 归类规则（JSON 字符串：`{"keywords":[...],"subdirs":[...]}`） */
  rules: string
  sort_order: number
  /**
   * 刮削出版**成品目录**（第 18 期）：刮削后的硬链接副本落点，供外部阅读器
   * （Komga 等）直接挂载读取。空串 = 该库不产出副本。
   *
   * 副本只读源、只写自己 —— 原书文件永不改写。该目录不得位于任何库根 /
   * 扫描源目录内部（否则会被扫回来变成重复书），后端在建/改库时会拦。
   */
  publish_path: string
  publish_exists: boolean
  publish_writable: boolean
  /** 逐库扫描调度（第 17 期 T2）：1 = 监听该库来源子目录 */
  watch: number
  /** 轮询间隔秒；0 = 继承全局 */
  scan_interval: number
  /** 定时表达式（空 = 不启用）；坏表达式会退化为间隔扫描 */
  scan_cron: string
  /**
   * 图标 key（第 40 期）。**仅用于展示** —— 值取自 `lib/icons.ts` 的 `ICONS`，
   * 后端刻意不维护白名单（图标表的唯一真相源在前端，未知 key 由 `AppIcon` 懒降级）。
   */
  icon: string
  /** 「允许的格式」原始设值（空数组 = **没设过**，看 `exts_effective`） */
  allowed_exts: string[]
  /** **生效**的扩展名集合（`allowed_exts` 为空时 = 库类型默认白名单） */
  exts_effective: string[]
  /** 「排除图案」glob 列表（空数组 = 不过滤） */
  exclude: string[]
  book_count: number
  exists: boolean
  writable: boolean
  last_scan_at: number
  last_scan_note: string
}

export interface LibrariesResult {
  items: LibraryEntity[]
  total: number
  /**
   * 库类型。`exts` = 该类型的**默认扫描白名单**（第 40 期）——
   * 新建向导的「允许的格式」选完类型就用它带出默认勾选集。
   * ⚠️ 别在前端抄一份：抄了就会与后端的扫描口径走散。
   */
  types: { value: LibraryType; label: string; exts: string[] }[]
  /** 第 41 期：已配置的来源根（向导按这些根浏览 / 下钻，数量不定） */
  source_roots: { name: string; path: string }[]
}

/**
 * 单个书库的**扫描状态**（第 88 期 `GET /api/libraries/scan-state`）。
 *
 * 用于「导入后第一次打开特别慢」的**感知**：后端正在刷新索引时，界面显示
 * 「正在建立索引…（已扫 N 本 / 新增 N 本）」，扫完即停轮询（别常驻）。
 *
 * ⚠️ 字段全部**可选**：后端该接口是并行开发的，尚未落地时前端不能因此报错
 * （拿不到就当空数组，见 store 里的容错）。`scanning` 是唯一的「在扫」判据。
 */
export interface LibraryScanState {
  library_id: string
  scanning: boolean
  /** 本轮扫描开始时间（epoch 秒；未在扫时为 0 / 缺省） */
  started_at?: number
  /** 上次结果：本次已扫文件数 */
  scanned?: number
  /** 上次结果：新增本数 */
  added?: number
  /** 上次结果：移除本数 */
  removed?: number
  /** 上次结果：错误原因（空 / 缺省 = 无错） */
  error?: string
}

/** 每库可覆写项中的一项（`/api/libraries/{id}/settings` 的 `schema`）。 */
export interface LibrarySettingItem {
  /** 全局配置的点分路径（如 `output.layout`）—— 覆写就以它为键 */
  key: string
  label: string
  /**
   * `str` 是自由文本（命名规则 / 适用格式）。
   * ⚠️ `number` 的区间是 **0–1**（比例），`percent` 是 **0–100** ——
   * 两者不能混用（第 40 期新增 `percent`，阅读阈值就是它）。
   */
  kind: 'bool' | 'enum' | 'number' | 'percent' | 'str' | 'policy_map'
  /** `kind = enum` 时的候选项 */
  options: string[]
  note: string
  /** 需要的能力键：库类型没有它 → 该项根本不会出现在 schema 里 */
  capability: string
}

export interface LibrarySettingsResult {
  library_id: string
  name: string
  library_type: LibraryType
  /** 生效值（该库覆写 ?? 全局），键为点分路径 */
  values: Record<string, unknown>
  /** 全局值（该项未覆写时与 `values` 相同） */
  global: Record<string, unknown>
  /** `overridden[key]` 为真 = 本库显式覆写过（界面据此显示「已覆盖 / 恢复继承」） */
  overridden: Record<string, boolean>
  /** **原始覆写**（未与全局合并）：`policy_map` 逐字段判断「继承 / 覆盖」要靠它 */
  overrides: Record<string, unknown>
  schema: LibrarySettingItem[]
}

/**
 * 命名规则预览里的一条（`/api/naming/preview`）。
 *
 * `old_rel` 是台账里的当前副本名，`new_rel` 是按规则重出版后的副本名 ——
 * 两者都由服务端用同一个函数算出，所以预览与落盘一致。
 */
export interface NamingItem {
  book_id: string
  library_id?: string | null
  /** 源文件名（相对库根，**永不改动**） */
  name: string
  title: string
  old_rel: string
  new_rel: string
  changed: boolean
  /** 空串 = 可重出版；`dup` = 同批内落点重复；`occupied` = 落点被别的文件占着 */
  conflict: '' | 'dup' | 'occupied'
  reason: string
}

export interface NamingPlan {
  library_id: string
  /** 实际生效的规则（回显：让用户确认用的是保存值还是草稿） */
  pattern: string
  scope: string
  /** 规则里可用的占位符，由后端给出，避免前后端各写一份 */
  fields: string[]
  items: NamingItem[]
  stats: { total: number; changed: number; conflict: number; ready: number }
}

/** 重出版结果（`/api/naming/apply`）。`skipped` = 名字未变或落点冲突而未处理的本数。 */
export interface NamingApplyResult {
  ok: boolean
  total: number
  done: number
  failed: number
  skipped: number
  items: Array<{
    book_id: string
    name: string
    old_rel: string
    new_rel: string
    /** 实际落盘的副本名（成功时与 new_rel 相同） */
    rel: string
    ok: boolean
    error: string
  }>
}

/** 能力清单（`/api/features`）。后端是「库类型 → 能力」的真值源，前端只声明「哪项菜单需要哪个能力」。 */export interface FeaturesResult {
  library_id: string
  library_type: string
  features: string[]
  matrix: { types: Record<string, string[]>; all: string[]; labels: Record<string, string> }
}

// ---------- 刮削出版（第 18 期） ----------

/**
 * 逐书刮削状态（与后端 `core/db.SCRAPE_STATUSES` 一一对应）：
 * - `pending` 待刮削 / `running` 进行中 / `ok` 已出版 / `failed` 失败
 * - `skipped` 跳过（库未配成品目录等「不是错误但没出版」）
 * - `removed` 副本已被删除，**待确认**（是否连原文件一起删）
 * - `kept` 已确认保留 / `orphan` 原文件已不在、副本成孤本
 * - `source_removed` 原文件已按确认移入回收站（副本保留）
 *
 * ⚠️ 状态机**只许降级**：回到 `ok` 只能由用户在页面上显式点「重新生成副本」。
 */
export type ScrapeStatus =
  | 'pending'
  | 'running'
  | 'ok'
  | 'failed'
  | 'skipped'
  | 'removed'
  | 'kept'
  | 'orphan'
  | 'source_removed'

/** 刮削页允许的显式处置动作 */
export type ScrapeAction =
  | 'delete_source'
  | 'keep_source'
  | 'rebuild'
  | 'keep_copy'
  | 'recycle_copy'

export interface ScrapeItem {
  book_id: string
  library_id: string
  library_name: string
  /** 源文件在库内的相对路径（书名，可能带一层系列目录） */
  name: string
  title: string
  author: string
  status: ScrapeStatus
  /** 后端给的中文文案（真值源在后端，免得两处各写一套） */
  status_label: string
  /** 原文件绝对路径 */
  source_path: string
  /** 副本绝对路径（空 = 还没出版） */
  copy_path: string
  /** 副本相对成品目录的路径 */
  link_rel: string
  /** `hardlink` = 硬链接；`copy` = 回退复制；空 = 未产出 */
  link_mode: '' | 'hardlink' | 'copy'
  /** 是否仍与源**共享数据块**（内嵌过元数据 = false，占额外空间） */
  shared: boolean
  /** 已写进副本的字段 */
  embedded: string[]
  has_cover: boolean
  error: string
  attempts: number
  removed_at: number
  removed_path: string
  confirmed_at: number
  updated_at: number
  /** 当前状态下允许的动作（后端二次校验） */
  actions: ScrapeAction[]
  /** 是否处于「降级待确认」（removed / orphan）—— 界面需高亮提醒 */
  degraded: boolean
}

export interface ScrapeState {
  items: ScrapeItem[]
  count: number
  /** 状态 → 条数 */
  counts: Record<string, number>
  total: number
  /** 待刮削 + 进行中 */
  pending: number
  /** 待确认 + 孤本 */
  needs_confirm: number
  /**
   * worker 运行态。
   * ⚠️ `running` = 线程活着（起来后常驻，**不代表在干活**）；判断「正在刮削」与
   * 「要不要开轮询」一律用 `busy`。
   */
  worker: { running: boolean; current: string; busy: boolean }
  labels: Record<string, string>
  actions: Record<string, string>
  /** 该库（或全局）是否开了自动刮削 */
  auto_enabled: boolean
  /** 当前筛选范围内有没有配了成品目录的库（空状态据此给出可执行的下一步） */
  publish_configured: boolean
}

// ---------- 跨库移动（用户点选；`/api/book-move/*`） ----------

/** 可选的目标库（`/api/book-move/targets`）：不相容的置灰，`reason` 就是后端拒绝时的那句 */
export interface BookMoveTarget {
  id: string
  name: string
  type: LibraryType
  type_label: string
  /** 选中的书能不能**全**进得去这个库 */
  compatible: boolean
  /** 进不去这个库的书目数（不是原因数） */
  blocked_count: number
  reason: string
  /** 选中的书现在就在这个库里 */
  same_as_source: boolean
  /** 没配成品目录 ⇒ 副本会留在原库（提前说，别等搬完才发现） */
  publish_configured: boolean
}

export interface BookMoveTargets {
  items: BookMoveTarget[]
  total_books: number
  missing_books: number
  /** 选中的书都在同一个库时给出源库 id，混库为空 */
  source_library_id: string
  message: string
}

/** 副本随书搬的处置（`none` 没有副本 / `left` 目标库没配成品目录 ⇒ 留在原库） */
export type BookMoveCopyAction = 'none' | 'left' | 'same' | 'reuse' | 'move'

export interface BookMoveCopy {
  action: BookMoveCopyAction
  old_copy: string
  new_copy: string
  rel: string
  reason: string
}

/** 逐本预检的一条（`/api/book-move/preflight`） */
export interface BookMoveItem {
  name: string
  book_id: string
  title: string
  format: string
  target_type: LibraryType
  target_label: string
  library_id: string
  library_name: string
  src: string
  is_dir: boolean
  dst_library_id: string
  dst_library_name: string
  dst: string
  status: 'ready' | 'conflict' | 'blocked' | 'skip'
  /** blocked 的原因属于哪一类：compat=相容闸门（契约）/ source=源与 id 状态 / name=改名不合法 */
  blocked_kind: '' | 'compat' | 'source' | 'name'
  reason: string
  suggest: string
  copy: BookMoveCopy
}

export interface BookMovePreview {
  items: BookMoveItem[]
  total: number
  ready: number
  conflict: number
  blocked: number
  skip: number
  movable: number
  dst_library_id: string
  dst_library_name: string
  copy_counts: Record<BookMoveCopyAction, number>
  /** 真会动磁盘的数量（照这两个数写文案，别自己加） */
  will_move_files: number
  will_move_copies: number
}

export interface BookMovePlanResult {
  batch_id: string
  created: number
  reused: boolean
  items: BookMoveItem[]
  message: string
}

/**
 * 撤回本次移动的结果（`/api/book-move/rollback`）。
 *
 * 第 77 期前它借用了「按格式迁移」的 `MigrationRunResult`；那个类型随自动归库一起删了，
 * 这里按**真实消费面**（书架的 `undoMove` 读 `restored` / `copies` / `failed`）另立一个，
 * 而不是把后端 `migrate.execute` 的整套返回抄一遍。
 */
export interface BookMoveRollbackResult {
  ok: boolean
  batch_id: string
  /** 搬回原库的本数 */
  restored: number
  failed: number
  /** 随迁回来的出版副本数（目标库没配成品目录时缺省） */
  copies?: number
  errors: { src: string; dst: string; error: string }[]
  /** 逐条台账行（`library_migrations` 一行一对象，字段与后端表同形） */
  items: {
    id: number
    batch_id: string
    direction: string
    library_id: string
    src: string
    dst: string
    status: string
    error: string
    created_at: number
  }[]
}

/** 冲突 / 跳过时用户对单本的处置：不传 = 冲突即不搬 */
export interface BookMoveDecision {
  id: string
  action: 'move' | 'rename' | 'skip'
  new_name?: string
}

export interface BookMoveBatch {
  batch_id: string
  direction: string
  /** 批次里的条目总数（含已回滚的） */
  total: number
  /** 真正搬过去的本数 —— 文案照它写 */
  done: number
  failed: number
  rolled_back: number
  can_rollback: boolean
  label: string
  src_library_id: string
  src_library_name: string
  dst_library_id: string
  dst_library_name: string
  at: number
}

function _authToken(): string {
  try {
    return localStorage.getItem('nf_token') || ''
  } catch {
    return ''
  }
}

/** `request()` 的默认超时（第 88 期）。15 秒覆盖绝大多数接口；个别慢接口按需覆盖。 */
export const DEFAULT_REQUEST_TIMEOUT_MS = 15000

export interface RequestOptions {
  /**
   * 超时（毫秒）。传 0 = 不限时（谨慎使用：会退回「一直转圈」的老毛病）。
   * 默认 `DEFAULT_REQUEST_TIMEOUT_MS`。
   */
  timeoutMs?: number
  /**
   * **网络层**失败时的重试次数（不含首次请求）。默认：GET = 1，其余 = 0。
   *
   * ⚠️ 三条纪律（第 88 期）：
   *   · 只对 GET 生效 —— 写操作（POST/PUT/DELETE）重发可能造成重复副作用；
   *   · **不重试超时** —— 超时意味着「慢」，再等一轮只会让用户等更久；
   *   · 调用方主动取消（AbortSignal）不重试。
   */
  retries?: number
}

/** 造一个带 `name` 的错误（`Error` 的 options 只认 `cause`，`name` 得手写）。 */
function _namedError(name: string, message: string, cause?: unknown): Error {
  const err = new Error(message, cause === undefined ? undefined : { cause })
  err.name = name
  return err
}

/**
 * 带超时的 fetch（第 88 期）。
 *
 * `fetch` 自身**没有超时**：网络半死不活时它会挂到浏览器默认（可达数分钟），
 * 界面就一直停在「正在载入…」——「打开书库等很久」的现场正是这种「其实早该报错」的等待。
 *
 * 语义：
 *   · 超时            → 抛 `name === 'TimeoutError'`；
 *   · 调用方 abort（如探索页「新检索取消旧检索」）→ **原样抛 AbortError**，
 *     调用方仍能按 `e.name === 'AbortError'` 识别「这是我自己取消的」；
 *   · 其余 fetch 抛错 = 网络层失败 → 抛 `name === 'NetworkError'`。
 */
async function _fetchWithTimeout(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const callerSignal = init.signal ?? null
  const ctrl = new AbortController()
  let timedOut = false

  // 调用方自带的取消信号必须保留：探索页用它「取消上一次检索」。
  const forwardAbort = (): void => ctrl.abort(callerSignal?.reason)
  if (callerSignal) {
    if (callerSignal.aborted) forwardAbort()
    else callerSignal.addEventListener('abort', forwardAbort, { once: true })
  }
  const timer =
    timeoutMs > 0
      ? setTimeout(() => {
          timedOut = true
          ctrl.abort()
        }, timeoutMs)
      : null

  try {
    return await fetch(path, { ...init, signal: ctrl.signal })
  } catch (e) {
    if (timedOut) throw _namedError('TimeoutError', `请求超时（${Math.round(timeoutMs / 1000)} 秒未响应）`)
    const name = (e as { name?: string } | undefined)?.name
    // 调用方取消：原样抛出，别把它错报成超时 / 网络错
    if (name === 'AbortError' || name === 'TimeoutError') throw e
    throw _namedError('NetworkError', '网络错误：无法连接到服务器', e)
  } finally {
    if (timer !== null) clearTimeout(timer)
    callerSignal?.removeEventListener('abort', forwardAbort)
  }
}

/**
 * 统一请求入口（第 88 期：加超时 + 有限重试 + 可诊断的失败原因）。
 *
 * ⚠️ 抛错约定**保持不变**：HTTP 错误仍把后端响应原文（可能是 `{"detail":"…"}`）
 * 塞进 `err.message`，交给 `apiErrorMessage()` 剥壳 —— 全站既有调用点不受影响。
 */
async function request<T>(path: string, init?: RequestInit, opts?: RequestOptions): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const timeoutMs = opts?.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS
  // 只有 GET 默认重试一次；写操作默认不重试（重发可能重复副作用）
  const maxRetries = opts?.retries ?? (method === 'GET' ? 1 : 0)

  const headers = new Headers(init?.headers)
  const token = _authToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  for (let attempt = 0; ; attempt += 1) {
    let res: Response
    try {
      res = await _fetchWithTimeout(path, { ...init, headers }, timeoutMs)
    } catch (e) {
      const name = (e as { name?: string } | undefined)?.name
      // 网络错可重试（GET）；超时 / 调用方取消一律不重试
      if (name === 'NetworkError' && attempt < maxRetries) continue
      console.error(`[api] ${method} ${path} → ${name ?? 'error'}`)
      throw e
    }

    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      if (res.status === 401) {
        // 登录失效 / 未登录：清 token 并通知全局弹出登录门禁
        try {
          localStorage.removeItem('nf_token')
        } catch {
          /* ignore */
        }
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('nf-unauthorized'))
        }
      }
      console.error(`[api] ${method} ${path} → ${res.status}`, detail)
      // 保留后端 detail 原文（apiErrorMessage 会剥壳）；没有就按 4xx / 5xx 给一句分类过的兜底
      throw new Error(
        detail || (res.status >= 500 ? `服务器错误（HTTP ${res.status}）` : `请求失败（HTTP ${res.status}）`),
      )
    }
    return (await res.json()) as T
  }
}

/**
 * 把接口抛出的错误转成**能给用户看的一行字**。
 *
 * `request()` 抛的是后端响应原文，而后端错误体是 `{"detail":"同名收藏夹已存在"}`
 * —— 直接 `e.message` 塞进 toast 会把花括号和键名一起露给用户。
 * 这里只做「剥壳」，不改 `request()` 本身的抛错约定（全站既有调用点不受影响）。
 */
export function apiErrorMessage(e: unknown, fallback: string): string {
  if (!(e instanceof Error) || !e.message) return fallback
  try {
    const parsed: unknown = JSON.parse(e.message)
    if (parsed && typeof parsed === 'object') {
      const d = (parsed as { detail?: unknown }).detail
      if (typeof d === 'string' && d.trim()) return d
    }
  } catch {
    /* 非 JSON 响应体（如纯文本 / HTML 错误页）：原样用之 */
  }
  return e.message
}

/** 下载类接口返回文件流（后端用 FileResponse(filename=...) 在 Content-Disposition 给真实文件名）。 */
export interface BlobResult {
  blob: Blob
  /** 解析自 Content-Disposition 的文件名（filename*=UTF-8'' 优先，回落裸 filename=）；无则用 URL 兜底 */
  filename: string
}

/**
 * 从 Content-Disposition 取文件名。
 * 兼容性：上游/本服务两种写法都要认 ——
 *   `filename*=UTF-8''%E4%B9%A6.epub`（RFC 5987，百分号编码）
 *   `filename="书.epub"`（裸 filename=，可能带引号）
 */
function _parseDispositionFilename(cd: string | null, fallback: string): string {
  if (!cd) return fallback
  const star = /filename\*\s*=\s*[^']*''((?:[^;]|%[^;])+)/i.exec(cd)
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/\+/g, ' '))
    } catch {
      /* 编码损坏则回落裸 filename */
    }
  }
  const plain = /filename\s*=\s*("([^"]*)"|([^;]*))/i.exec(cd)
  if (plain) {
    const v = (plain[2] ?? plain[3] ?? '').trim()
    if (v) return v
  }
  return fallback
}

async function requestBlob(path: string, init?: RequestInit): Promise<BlobResult> {
  const res = await fetch(path, init)
  if (!res.ok) {
    console.error(`[api] POST ${path} → ${res.status}`)
    throw new Error(`请求失败（HTTP ${res.status}）`)
  }
  const fallback = (path.split('/').pop() || 'download').split('?')[0] || 'download'
  const blob = await res.blob()
  return { blob, filename: _parseDispositionFilename(res.headers.get('Content-Disposition'), fallback) }
}

export const api = {
  health: () => request<HealthInfo>('/health'),

  // ---------- 版本检查与更新（第 78 期）----------
  /** 「新功能」页数据源：解析仓库 CHANGELOG.md（离线可读）。 */
  changelog: () => request<{ current: string; entries: ChangelogEntry[] }>('/api/changelog'),
  /** 当前版本 / 远端最新 / 是否有更新 / 一键更新是否可用的快照。 */
  updateStatus: () => request<UpdateStatus>('/api/update/status'),
  /** 手动触发一次远端检查（绕过定时缓存）。 */
  updateCheck: () => request<UpdateStatus>('/api/update/check', { method: 'POST' }),
  /** 一键更新：挂了 docker.sock 时拉取最新镜像并重建自身容器。 */
  updateApply: () => request<UpdateApplyResult>('/api/update/apply', { method: 'POST' }),

  // ---------- 书源 ----------
  listSources: () => request<{ sources: SourceItem[] }>('/api/sources'),

  addSourcesText: (text: string) =>
    request<{ added?: number; ok?: boolean; errors?: Array<{ name?: string; error?: string }> }>(
      '/api/sources',
      {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
        body: text,
      },
    ),

  uploadSourcesFile: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ added?: number; ok?: boolean; errors?: Array<{ name?: string; error?: string }> }>(
      '/api/sources/upload',
      {
        method: 'POST',
        body: form,
      },
    )
  },

  /** 收书目录整页拖拽投递：把文件丢进 INPUT_DIR（监听目录）并按现有管线处理。
   *  复用后端的 /convert（写入 INPUT_DIR 后走 pipeline），等价于把文件放进投递目录。 */
  convertDrop: (file: File, traditionalize = false) =>
    request<{ ok?: boolean }>('/convert', {
      method: 'POST',
      body: (() => {
        const f = new FormData()
        f.append('file', file)
        if (traditionalize) f.append('traditionalize', 'true')
        return f
      })(),
    }),

  deleteSource: (name: string) =>
    request<{ ok: boolean }>(`/api/sources/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  /** 书源运行状态：Cookie 是否已持久化、当前配置下是否可用 */
  sourcesStatus: () => request<{ items: SourceStatus[] }>('/api/sources/status'),

  /**
   * 书源试搜（第 57 期，**不落盘**）：`{rule}` 试表单里正在填的规则，`{name}` 试已注册的源。
   * 校验错误逐条回 `errors`，网络/解析失败回 `error`。
   */
  testSource: (payload: { rule?: Record<string, unknown>; name?: string; query: string }) =>
    request<SourceTestResult>('/api/sources/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  // ---------- 搜索 / 预览 / 下载 ----------
  /**
   * 跨源聚合检索（第 71 期：`page` 分页 + 逐源状态）。
   *
   * - `results`：**本页**命中并集，每条带 `source`（书源名）指路 —— 下载与预览都要用它；
   * - `sources`：逐源状态（成功 N 条 / 失败原因原文 / 被闸门跳过原因）。第 71 期之前
   *   后端不返回它，于是界面那条「部分书源检索失败」永远不显示（旧字段 `errors` 已下线）；
   * - `has_more`：由后端按「**任一**源还能取下一页」算好。分页是逐源的，聚合口径只有
   *   后端知道，前端不自己再数一遍（那是第二份真值源）。
   */
  search: (title: string, page = 1, signal?: AbortSignal) =>
    request<{
      count: number
      results: SearchHit[]
      sources: SearchSourceState[]
      has_more: boolean
      page: number
    }>('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, page }),
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

  /** 任务列表（服务端真实任务表，新 → 旧） */
  tasks: (limit = 100) => request<{ items: TaskItem[]; count: number }>(`/api/tasks?limit=${limit}`),

  // ---------- 文件 ----------
  files: () => request<FileListing>('/api/files'),

  // ---------- 目录监听 ----------
  watcherStatus: () => request<WatcherStatus>('/api/watcher'),
  watcherStart: () => request<WatcherStatus>('/api/watcher/start', { method: 'POST' }),
  watcherStop: () => request<WatcherStatus>('/api/watcher/stop', { method: 'POST' }),
  scanNow: () => request<Record<string, unknown>>('/api/scan', { method: 'POST' }),

  // ---------- 收书目录条目（Book Dock 五态流水线） ----------
  bookDock: (status?: string) =>
    request<BookDockResponse>(
      `/api/book-dock${status && status !== 'all' ? `?status=${encodeURIComponent(status)}` : ''}`,
    ),
  /**
   * 重跑单个条目。
   *
   * 第 65 期起多两个**可选**参数 = 界面上的「入库到…」：入库前当场指定目标库与
   * 目标文件夹（口径：目标文件夹默认该库的第一个）。不传时发的 body 是 `{}`，
   * 与第 65 期之前的请求等价（后端 `payload or {}`）—— 老调用点一个都不用改。
   */
  bookDockRescan: (id: string, opts?: { library_id?: string; root?: string }) =>
    request<{ ok: boolean; item: BookDockItem }>(
      `/api/book-dock/${encodeURIComponent(id)}/rescan`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(opts ?? {}),
      },
    ),
  /**
   * 改投递目录里的文件名（第 65 期）。
   *
   * ⚠️ 条目 id **就是文件名**：成功之后 id 会变（用 `item.id`，或直接重载列表），
   * 不能拿旧 id 接着操作。扩展名不许换、`ready` 条目不接受改名 —— 都在后端拦。
   */
  bookDockRename: (id: string, name: string) =>
    request<{ ok: boolean; item: BookDockItem }>(
      `/api/book-dock/${encodeURIComponent(id)}/rename`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      },
    ),
  bookDockIgnore: (id: string) =>
    request<{ ok: boolean; item: BookDockItem }>(
      `/api/book-dock/${encodeURIComponent(id)}/ignore`,
      { method: 'POST' },
    ),
  bookDockDelete: (id: string) =>
    request<{ ok: boolean; name: string; recycled: string }>(
      `/api/book-dock/${encodeURIComponent(id)}/delete`,
      { method: 'POST' },
    ),

  // ---------- 日志 ----------
  // 存盘情况随 `logs()` 一起返回（第 52 期），无需单独请求。
  logs: (query: LogQuery = {}) => {
    const p = new URLSearchParams()
    if (query.limit) p.set('limit', String(query.limit))
    if (query.action) p.set('action', query.action)
    if (query.status) p.set('status', query.status)
    if (query.q) p.set('q', query.q)
    if (query.actor) p.set('actor', query.actor)
    const qs = p.toString()
    // 注意：后端的 count 字段未必是数字（activity_log.count() 可能返回聚合对象），
    // 因此类型放宽为 unknown，由调用方归一化。
    // actors 是操作者下拉的候选，**不受 query.actor 影响**（后端另行取全量）。
    return request<{
      items: LogItem[]
      count: unknown
      dir: string
      actors: string[]
      storage: LogStorage
    }>(`/api/logs${qs ? `?${qs}` : ''}`)
  },

  clearLogs: () =>
    request<{ ok: boolean; read_marks_cleared?: number }>('/api/logs', { method: 'DELETE' }),

  logsDownloadUrl: () => '/api/logs/download',

  /**
   * 封面 URL，直接给 `<img src>` 用。
   *
   * ⚠️ 必须带 `?token=`：`<img>` 无法携带 Authorization 头，而 /api 前缀一律要求 Bearer。
   * 后端只为 `/cover` 与 `/asset` 这两个**只读图片接口**接受 query 令牌
   * （见 `server._request_token`），其余接口仍只认请求头。
   */
  coverUrl: (bid: string) => {
    const t = _authToken()
    return `/api/books/${encodeURIComponent(bid)}/cover${t ? `?token=${encodeURIComponent(t)}` : ''}`
  },

  // ---------- 漫画（CBZ / CBR）----------
  /** 漫画页清单。前端按 index 逐页取图，不一次拉整本（一话可能几十 MB） */
  comicPages: (bid: string) =>
    request<{ pages: Array<{ index: number; name: string; size: number }>; total: number }>(
      `/api/books/${encodeURIComponent(bid)}/comic`,
    ),

  /**
   * 漫画单页 URL（1-based 的 index 由调用方转 0-based）。
   * ⚠️ 必须带 `?token=`：漫画页用 `<img>` 加载（比 fetch+blob 更省内存），
   * `<img>` 无法携带 Authorization 头。后端只为只读图片接口接受 query 令牌，
   * 该路径已在 `server._MEDIA_TOKEN_PATHS` 中（见那里的注释）。
   */
  comicPageUrl: (bid: string, index: number) => {
    const t = _authToken()
    return `/api/books/${encodeURIComponent(bid)}/comic/${index}${t ? `?token=${encodeURIComponent(t)}` : ''}`
  },

  // ---------- 序号单元合集（第 73 期：一话一文件的目录 = 一本书）----------
  /** 话清单（按序号排序，解析不出序号的排最后）。条数与卡片上的 `tracks` 同源 */
  units: (bid: string) =>
    request<{ items: UnitItem[]; total: number }>(
      `/api/books/${encodeURIComponent(bid)}/units`,
    ),

  /** 某一话的页清单（仅 CBZ / CBR 话；形状与 `comicPages` 相同） */
  unitPages: (bid: string, index: number) =>
    request<{ pages: Array<{ index: number; name: string; size: number }>; total: number }>(
      `/api/books/${encodeURIComponent(bid)}/units/${index}/pages`,
    ),

  /**
   * 某一话的字节流 URL —— 音频话直接给 `<audio src>`、PDF 话给 pdf.js。
   *
   * ⚠️ 必须带 `?token=`：音频话是浏览器原生请求（带不了 Authorization）。
   * 该路径已在 `server._MEDIA_TOKEN_PATHS` 中（见那里的注释）。PDF 话走 pdf.js 的
   * `httpHeaders` 时这个 query 也无害（多一种携带方式，令牌强度不变）。
   */
  unitFileUrl: (bid: string, index: number) => {
    const t = _authToken()
    return `/api/books/${encodeURIComponent(bid)}/units/${index}${t ? `?token=${encodeURIComponent(t)}` : ''}`
  },

  /**
   * 某一话里第 n 页的图片 URL（0 起的页号，与 `/comic/{index}` 同一套约定）。
   * ⚠️ 同样必须带 `?token=`：漫画页用 `<img>` 加载。
   */
  unitPageUrl: (bid: string, index: number, page: number) => {
    const t = _authToken()
    return `/api/books/${encodeURIComponent(bid)}/units/${index}/page/${page}${t ? `?token=${encodeURIComponent(t)}` : ''}`
  },

  // ---------- 有声书（单文件 / 多轨目录）----------
  /** 轨清单（单文件 1 轨 / 目录 n 轨，自然序） */
  audioTracks: (bid: string) =>
    request<{ items: AudioTrack[]; total: number }>(
      `/api/books/${encodeURIComponent(bid)}/audio`,
    ),

  /**
   * 单轨音频 URL，直接给 `<audio src>` 用。
   * ⚠️ 必须带 `?token=`：`<audio>` 无法携带 Authorization 头。
   * 后端为只读媒体接口接受 query 令牌，该路径已在 `server._MEDIA_TOKEN_PATHS` 中。
   */
  audioTrackUrl: (bid: string, index: number) => {
    const t = _authToken()
    return `/api/books/${encodeURIComponent(bid)}/audio/${index}${t ? `?token=${encodeURIComponent(t)}` : ''}`
  },

  // ---------- 通知（活动日志 + 已读态）----------
  notifications: (limit = 100) =>
    request<{ items: NotificationItem[]; count: number; unread: number; unread_total: number }>(
      `/api/notifications?limit=${limit}`,
    ),

  markNotificationsRead: (payload: { ids?: string[]; all?: boolean }) =>
    request<{ ok: boolean; marked: number }>('/api/notifications/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  // ---------- 成就 ----------
  achievements: () => request<AchievementsOverview>('/api/achievements'),

  /** 重算全部成就（会重置解锁时间，见 core/achievements.backfill） */
  backfillAchievements: () =>
    request<AchievementsOverview>('/api/achievements/backfill', { method: 'POST' }),


  // ---------- 孤儿记录 ----------
  orphans: () => request<OrphansInfo>('/api/maintenance/orphans'),

  // ---------- 单书元数据编辑 ----------
  bookMetadata: (bid: string) =>
    request<BookMetadata>(`/api/books/${encodeURIComponent(bid)}/metadata`),

  /**
   * 编辑单本书的元数据：**只写服务端，不改写任何书文件**（第 18 期口径）。
   * 值语义见 `BookMetadataWriteFields`（`null` = 显式清空，空串 = 撤销覆盖）。
   * 返回的 `changed` 只含**实际发生变化**的字段（同值重写不会出现在里面）。
   *
   * `custom`（第 35 期）是**同一张表单里的另一套值**（自定义字段，存 `book_custom_values`）：
   * 详情页一次保存把两者一起提交。只传 `custom`、不传 `fields` 也合法
   * （后端只在两者都空时才拒绝）。
   */
  setBookMetadata: (
    bid: string,
    fields: BookMetadataWriteFields,
    custom?: Record<string, string | string[]>,
  ) =>
    request<MetadataWriteResult>(`/api/books/${encodeURIComponent(bid)}/metadata`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(custom ? { fields, custom } : { fields }),
    }),

  /** 实时在线建议（编辑器「在线建议 / 重新获取」用，不写库）。 */
  bookMetadataOnline: (bid: string) =>
    request<MetadataOnlineResult>(`/api/books/${encodeURIComponent(bid)}/metadata/online`),

  /** 撤销用户覆盖（含「显式清空」）让字段回落到在线值 / 文件原值；**不改写任何文件**。 */
  revertBookMetadata: (bid: string, fields: string[]) =>
    request<MetadataRevertResult>(`/api/books/${encodeURIComponent(bid)}/metadata/revert`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fields }),
    }),

  /**
   * 字段级锁定开关（第 35 期）：`field` 取可编辑字段名，或封面用的 `cover`。
   *
   * 锁只挡**抓取**（即使该字段策略是「总是覆盖」），手动编辑照旧可用。
   */
  lockBookMetadata: (bid: string, field: string, locked = true) =>
    request<{ ok: boolean; field: string; locked: boolean; locked_fields: string[] }>(
      `/api/books/${encodeURIComponent(bid)}/metadata/lock`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field, locked }),
      },
    ),

  // ---------- 自定义字段定义（第 35 期）----------
  // 定义是**全局**的（不属于某本书）；每本书的值走上面 `bookMetadata` / `setBookMetadata`。

  /** 定义列表（含归档项）；`includeTrashed` 时额外带回垃圾桶条目。`types` 供下拉直接用。 */
  customFields: (includeTrashed = false) =>
    request<{
      items: CustomFieldDef[]
      types: Array<{ key: string; label: string }>
      trashed?: CustomFieldDef[]
    }>(`/api/custom-fields${includeTrashed ? '?include_trashed=1' : ''}`),

  /** 新建定义。`key` 缺省由显示名派生（纯中文名会派生出一个名字摘要，不是随机值）。 */
  createCustomField: (payload: {
    label: string
    key?: string
    type?: string
    library_ids?: string[]
    default_value?: string
  }) =>
    request<{ ok: boolean; item: CustomFieldDef; items: CustomFieldDef[] }>('/api/custom-fields', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 改定义（**不含 key**：改 key 等于换一个字段，值会失去归属）。 */
  updateCustomField: (
    cid: number,
    patch: {
      label?: string
      type?: string
      library_ids?: string[]
      default_value?: string
      archived?: boolean
      position?: number
    },
  ) =>
    request<{ ok: boolean; item: CustomFieldDef; items: CustomFieldDef[] }>(
      `/api/custom-fields/${cid}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      },
    ),

  /** 按给定 id 次序重排（position = 下标）—— 这就是「排序」那一项操作的落点。 */
  reorderCustomFields: (ids: number[]) =>
    request<{ ok: boolean; moved: number; items: CustomFieldDef[] }>(
      '/api/custom-fields/reorder',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      },
    ),

  /** **移入垃圾桶**（软删除）。值保留，恢复后一切照旧；彻底删除走 `purgeCustomField`。 */
  deleteCustomField: (cid: number) =>
    request<{ ok: boolean; trashed: boolean; items: CustomFieldDef[]; trashed_items: CustomFieldDef[] }>(
      `/api/custom-fields/${cid}`,
      { method: 'DELETE' },
    ),

  restoreCustomField: (cid: number) =>
    request<{ ok: boolean; items: CustomFieldDef[] }>(`/api/custom-fields/${cid}/restore`, {
      method: 'POST',
    }),

  /** 彻底删除（不可恢复），并**连带清掉所有书上的值**。只对垃圾桶里的条目成立。 */
  purgeCustomField: (cid: number) =>
    request<{ ok: boolean; items: CustomFieldDef[]; trashed_items: CustomFieldDef[] }>(
      `/api/custom-fields/${cid}/purge`,
      { method: 'DELETE' },
    ),

  // ---------- 阅读状态 / 书评 / 相似书 ----------
  bookStatus: (bid: string) =>
    request<ReadingStatus>(`/api/books/${encodeURIComponent(bid)}/status`),

  /** status 之外可显式传起止日期（epoch 秒）；不传则由后端按状态规则自动维护 */
  setStatus: (bid: string, payload: { status: string; started_at?: number; finished_at?: number }) =>
    request<ReadingStatus>(`/api/books/${encodeURIComponent(bid)}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /**
   * 从头开始（第 34 期）：清掉这本书的阅读会话 / 进度 / 状态。
   * 只删服务端记录，**不动文件**；批注 / 书签 / 评分 / 收藏也不受影响。
   */
  resetReadingState: (bid: string) =>
    request<{ ok: boolean; removed: Record<string, number>; total: number }>(
      `/api/books/${encodeURIComponent(bid)}/reset-reading-state`,
      { method: 'POST' },
    ),

  bookReview: (bid: string) =>
    request<BookReview>(`/api/books/${encodeURIComponent(bid)}/review`),

  /** stars 0 = 清除评分；review 空串 = 清除书评。两者一起保存但可独立留空 */
  setReview: (bid: string, payload: { stars: number; review: string }) =>
    request<BookReview>(`/api/books/${encodeURIComponent(bid)}/review`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  // ---------- 阅读尝试 / 重读（第 43 期）----------
  /** 这本书的阅读尝试清单 + 当前进行中的那一轮 */
  readingAttempts: (bid: string) =>
    request<{ items: ReadingAttempt[]; total: number; current: ReadingAttempt | null }>(
      `/api/books/${encodeURIComponent(bid)}/reading-attempts`,
    ),

  /** 开新一轮阅读（「再来一遍」）。幂等：已有进行中的那一轮则原样返回。 */
  startReadingAttempt: (bid: string) =>
    request<{ ok: boolean; attempt: ReadingAttempt }>(
      `/api/books/${encodeURIComponent(bid)}/reading-attempts`,
      { method: 'POST' },
    ),

  /** 收尾进行中的那一轮；没有进行中的轮次后端返回 404。 */
  finishReadingAttempt: (bid: string) =>
    request<{ ok: boolean; attempt: ReadingAttempt }>(
      `/api/books/${encodeURIComponent(bid)}/reading-attempts/finish`,
      { method: 'POST' },
    ),

  /** 一次性历史补录：给既有阅读状态但无轮次的书各补一轮。 */
  backfillReadingAttempts: () =>
    request<{ ok: boolean; created: number }>('/api/reading-attempts/backfill', { method: 'POST' }),

  /**
   * 相似书：五路加权打分派生（第 35 期）。至少要有一条实质重合（同作者 / 题材 / 同系列）
   * 才返回；``limit`` 上限 25（后端 Query 会拦，超过即 422）。
   */
  similarBooks: (bid: string, limit = 6) =>
    request<{ items: SimilarBook[] }>(`/api/books/${encodeURIComponent(bid)}/similar?limit=${limit}`),

  /**
   * 导出全部书目 CSV（含阅读进度 / 状态 / 评分）。
   * 用 blob 触发下载：`/api` 一律要求 Bearer 头，`<a download>` 带不了，
   * 所以不能像 /cover 那样直接给 URL（那是后端专门为图片开的 ?token= 口子）。
   */
  exportBooks: async (): Promise<void> => {
    const headers = new Headers()
    const token = _authToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch('/api/books/export', { headers })
    if (!res.ok) throw new Error(`导出失败（${res.status}）`)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `library-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  },

  /**
   * 导出批注（第 43 期）：`format` ∈ markdown / json / csv，可按书库或单书收窄。
   * 同样走 blob 下载（`/api` 要求 Bearer 头，`<a download>` 带不了）。
   * 只导活跃批注（后端按 `deleted_at=0` 过滤）。
   */
  exportAnnotations: async (
    format: 'markdown' | 'json' | 'csv' = 'markdown',
    opts: { libraryId?: string; bookId?: string } = {},
  ): Promise<void> => {
    const q = new URLSearchParams({ format })
    if (opts.libraryId) q.set('library_id', opts.libraryId)
    if (opts.bookId) q.set('book_id', opts.bookId)
    const headers = new Headers()
    const token = _authToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`/api/annotations/export?${q.toString()}`, { headers })
    if (!res.ok) throw new Error(`导出失败（${res.status}）`)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `annotations-${new Date().toISOString().slice(0, 10)}.${format === 'markdown' ? 'md' : format}`
    a.click()
    URL.revokeObjectURL(url)
  },

  /** 批量动作（详见后端 api_batch）。逐本执行，返回成功/失败清单。 */
  batch: (payload: { action: string; ids: string[]; params?: Record<string, unknown> }) =>
    request<BatchResult>('/api/books/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  // ---------- 自定义智能书架（规则存后端，求值在前端 lib/smartScope.ts）----------
  smartScopes: () => request<{ items: SmartScope[] }>('/api/smart-scopes'),

  createSmartScope: (payload: { name: string; rules: ScopeRule[]; match: 'all' | 'any' }) =>
    request<SmartScope>('/api/smart-scopes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  updateSmartScope: (id: number, payload: { name: string; rules: ScopeRule[]; match: 'all' | 'any' }) =>
    request<SmartScope>(`/api/smart-scopes/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteSmartScope: (id: number) =>
    request<{ ok: boolean }>(`/api/smart-scopes/${id}`, { method: 'DELETE' }),

  // ---------- 偏好模式 / 设备（按设备的偏好同步）----------
  prefProfiles: () => request<{ items: PrefProfile[] }>('/api/prefs/profiles'),

  prefProfileCreate: (payload: { name: string; payload: PrefsPayload }) =>
    request<PrefProfile>('/api/prefs/profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  prefProfileUpdate: (id: number, payload: { name: string; payload: PrefsPayload }) =>
    request<PrefProfile>(`/api/prefs/profiles/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 删模式：返回被解除引用的设备数（那些设备的配置不变） */
  prefProfileDelete: (id: number) =>
    request<{ ok: boolean; deleted: boolean; detached_devices: number }>(`/api/prefs/profiles/${id}`, {
      method: 'DELETE',
    }),

  prefDevices: () => request<{ items: PrefDevice[] }>('/api/prefs/devices'),

  /** 设备上报。`active_profile_id` 不传即保留原值（推送配置时不该顺手清掉来源标记） */
  prefDeviceUpsert: (
    id: string,
    payload: { name: string; payload: PrefsPayload; active_profile_id?: number | null },
  ) =>
    request<PrefDevice>(`/api/prefs/devices/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 应用模式到本设备（服务端把模式 payload 拷贝过来） */
  prefDeviceApply: (id: string, pid: number) =>
    request<PrefDevice>(`/api/prefs/devices/${encodeURIComponent(id)}/apply/${pid}`, { method: 'POST' }),

  prefDeviceDelete: (id: string) =>
    request<{ ok: boolean }>(`/api/prefs/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // ---------- 阅读字体（后端字体库；上传后可在阅读器里选用）----------
  fonts: () =>
    request<{ items: FontItem[]; max_bytes: number; max_count: number }>('/api/fonts'),

  /** 上传字体（multipart）。Content-Type 交给浏览器自动带 boundary，不能手写。 */
  uploadFont: async (file: File): Promise<FontItem> => {
    const fd = new FormData()
    fd.append('file', file)
    const headers = new Headers()
    const token = _authToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch('/api/fonts', { method: 'POST', headers, body: fd })
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      let msg = `上传失败（${res.status}）`
      try {
        msg = (JSON.parse(detail) as { detail?: string }).detail || msg
      } catch {
        /* 非 JSON 响应 */
      }
      throw new Error(msg)
    }
    return (await res.json()) as FontItem
  },

  deleteFont: (id: string) =>
    request<{ ok: boolean }>(`/api/fonts/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  /** Reading Log：按天明细 + 按书聚合 + 最近会话（reading_sessions 表） */
  readingLog: (days = 60) =>
    request<{ days: number; items: ReadingLogDay[]; by_book: ReadingLogBook[]; recent: ReadingLogSession[] }>(
      `/api/reading-log?days=${days}`,
    ),

  /** 手工补录一次阅读会话（读了纸质书 / 没开阅读器的场景）。返回会话结束时间 */
  addReadingSession: (payload: { book_id: string; minutes: number; date: string; start?: string }) =>
    request<{ ok: boolean; session: ReadingLogSession }>('/api/reading-log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 清理孤儿记录 —— **不可恢复**（但把文件放回原处会重新关联） */
  clearOrphans: () =>
    request<{ ok: boolean; removed: Record<string, number>; total: number }>(
      '/api/maintenance/orphans/clear',
      { method: 'POST' },
    ),

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

  /**
   * 成品文件的下载地址（`<a download>` 用，浏览器原生请求带不了 Bearer —— 该路由与
   * 其它旧接口一样**不强制鉴权**，见 server 中间件）。
   *
   * 第 64 期两处修正：① 加 `libraryId` —— 服务端原来写死 `OUTPUT_DIR` 拼路径，
   * 多书库下对其它库的书必 404；② **按段编码**而不是整串 `encodeURIComponent`：
   * `name` 是库内相对路径（Komga 布局下形如 `三体/三体 #1.epub`），整串编码会把 `/`
   * 变成 `%2F`，能否还原取决于中间层怎么解 URL，按段编码则不依赖那件事。
   */
  downloadUrl: (name: string, libraryId = '') =>
    `/download/${name.split('/').map(encodeURIComponent).join('/')}` +
    (libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : ''),

  // ---------- 工具页：实体管理 / 重复书籍 / 缺失资源 ----------
  // 实体改名一律「先 preview、再 apply」；apply 只回传 {type, from, to} ——
  // **改哪些书由服务端按 from 自己算**，客户端不能指定去动哪本书（预览过期也改不错）。
  /** libraryId 为空 = 全部书库（与加库维度之前一致）；给了就只统计该库。 */
  entities: (type: EntityKind, libraryId = '') =>
    request<EntityListing>(
      `/api/entities?type=${type}${libraryId ? `&library_id=${encodeURIComponent(libraryId)}` : ''}`,
    ),

  entityRenamePreview: (type: EntityKind, from: string, to: string, libraryId = '') =>
    request<RenamePlan>('/api/entities/rename/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, from, to, library_id: libraryId }),
    }),

  /**
   * 执行实体改名 / 合并：**只写服务端元数据**（源文件名与字节原样），
   * 落库后列表 / 详情 / 实体聚合按新名字走。
   */
  entityRenameApply: (type: EntityKind, from: string, to: string, libraryId = '') =>
    request<EntityRenameResult>('/api/entities/rename/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, from, to, library_id: libraryId }),
    }),

  entityMerge: (type: EntityKind, source: string, target: string, libraryId = '') =>
    request<RenamePlan>('/api/entities/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, source, target, library_id: libraryId }),
    }),

  /**
   * 命名规则预览（**副本名**）：列出「当前副本名 → 按此规则重出版后的副本名」。
   *
   * `pattern` / `scope` 留空时用**该库的生效命名规则**（每库覆写 ?? 全局，见
   * `/api/libraries/{id}/settings`）；给了就按草稿算（所见即所得）。
   * 预览与落盘共用服务端的 `publish.relpath_for`，所以预览里的 `new_rel`
   * 就是重出版后台账里的 `link_rel`。
   */
  namingPreview: (opts: { libraryId?: string; pattern?: string; scope?: string } = {}) =>
    request<NamingPlan>('/api/naming/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        library_id: opts.libraryId ?? '',
        pattern: opts.pattern ?? '',
        scope: opts.scope ?? '',
      }),
    }),

  /**
   * 按**已保存**的命名规则重出版副本：只动硬链接副本、源文件只读，
   * 旧副本移入回收目录不留双份，全程不外呼。
   *
   * `bookIds` 只是**收窄**范围：改哪些书由服务端自己算（名字没变的不做、
   * 落点冲突的跳过），客户端指定不了别的。
   */
  namingApply: (opts: { libraryId?: string; bookIds?: string[] } = {}) =>
    request<NamingApplyResult>('/api/naming/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        library_id: opts.libraryId ?? '',
        book_ids: opts.bookIds ?? null,
      }),
    }),

  /**
   * threshold = 书名相似度阈值（%，50–100）。同作者是硬条件，阈值只管书名。
   * libraryId 为空 = 全部书库；给定时只在该库内比对。组上的 cross_library 标跨库重复。
   */
  duplicates: (threshold = 85, libraryId = '') =>
    request<{ groups: DuplicateGroup[]; total: number; threshold: number }>(
      `/api/duplicates?threshold=${threshold}${libraryId ? `&library_id=${encodeURIComponent(libraryId)}` : ''}`,
    ),

  // ---------- Komga 库布局（输出侧）----------
  /** 预览「整理为 Komga 布局」：哪些书会移进系列目录（只算不改） */
  komgaLayoutPreview: () =>
    request<KomgaLayoutPlan>('/api/komga/layout/preview', { method: 'POST' }),

  /** 应用整理。只传回预览里确认过的条目，后端会再校验一遍 */
  komgaLayoutApply: (items: Array<{ old: string; new: string }>) =>
    request<KomgaLayoutResult>('/api/komga/layout/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    }),

  // ---------- 元数据抓取与治理 ----------
  metadataSources: () =>
    request<{ items: MetadataSource[]; enabled: boolean; has_googlebooks_key: boolean }>(
      '/api/metadata/sources',
    ),

  /** 提供商目录（第 57 期：分组 + 启用 / 配置现状；设置页「提供商」页的唯一数据源） */
  metadataProviders: () => request<MetadataProvidersResult>('/api/metadata/providers'),

  /**
   * 元数据来源**真联网体检**（第 59 期）：并发跑、单家超时、失败分门别类。**只读**。
   * 不传 `query` ⇒ 用**各家样本**（地区性目录用当地书名，否则会误报「无结果」）。
   */
  metadataHealth: (query?: string) =>
    request<MetadataHealthResult>('/api/metadata/health', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(query ? { query } : {}),
    }),

  /** 上次体检结果（进程内缓存；后端重启后为空 —— 界面如实显示「尚未体检过」） */
  metadataHealthLast: () => request<MetadataHealthResult>('/api/metadata/health'),

  /**
   * 源连通性自检（真的外呼；被点的源才测）。
   *
   * - `keys`：按源 id 给的**主密钥**覆盖（早期接口，保留兼容）；
   * - `configs`：按源 id 给的**整行配置草稿** `{sid: {字段键: 值}}`（行内「配置」区用）。
   *
   * 两者都**优先于已保存配置、且不落盘** —— 否则只能测「上次保存的旧值」，
   * 或被迫为了测试先保存一次。
   */
  metadataProbe: (
    sources?: string[],
    keys?: Record<string, string>,
    configs?: Record<string, Record<string, string>>,
  ) =>
    request<{ items: Record<string, { ok: boolean; message: string; ms: number }> }>(
      '/api/metadata/probe',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sources,
          ...(keys && Object.keys(keys).length ? { keys } : {}),
          ...(configs && Object.keys(configs).length ? { configs } : {}),
        }),
      },
    ),

  /** 抓取预览（只算不改）。一次最多 10 本，前端逐本调以便显示进度 */
  metadataPlan: (names?: string[], limit?: number) =>
    request<MetadataPlan>('/api/metadata/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ names, limit }),
    }),

  /** 应用：只传回预览里确认过的具体值（后端会再校验） */
  metadataApply: (
    items: Array<{ name: string; fields: Record<string, unknown>; cover: { url: string } | null }>,
  ) =>
    request<MetadataApplyResult>('/api/metadata/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    }),

  /** 元数据完整度分布（force=true 绕过 library 的 5 秒缓存重算） */
  metadataScore: (force = false) =>
    request<MetadataScoreResponse>(`/api/metadata-score${force ? '?force=true' : ''}`),

  // ---------- 外部服务集成（Hardcover / Readwise / StoryGraph）----------
  integrations: () => request<{ items: IntegrationService[] }>('/api/integrations'),

  /** 提交掩码 = 不修改（与其它凭据同一约定）；`auto_push` 是布尔开关，单独处理 */
  saveIntegration: (service: string, payload: Record<string, string | boolean>) =>
    request<{ ok: boolean }>(`/api/integrations/${service}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 连通性验证（三家都提供；StoryGraph 是启发式判定，返回文案里会说明） */
  testIntegration: (service: string) =>
    request<IntegrationTestResult>(`/api/integrations/${service}/test`, { method: 'POST' }),

  /** 同步预览：只算不改、零外呼 */
  previewIntegration: (service: string) =>
    request<SyncPreview>(`/api/integrations/${service}/preview`, { method: 'POST' }),

  /** 执行一次同步（会向对方写入） */
  syncIntegration: (service: string) =>
    request<SyncResult>(`/api/integrations/${service}/sync`, { method: 'POST' }),

  // ---------- KOReader 进度互通 ----------
  koreaderStatus: () => request<KoreaderStatus>('/api/koreader'),

  /** 保存。`password` 留空 = 不修改密钥（后端存的是 md5，永不回显） */
  saveKoreader: (payload: { enabled: boolean; username: string; password?: string }) =>
    request<{ ok: boolean }>('/api/koreader', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 重建文档索引（为每本书算 partialMD5，KOReader 靠它认出是哪本） */
  koreaderScan: () =>
    request<{ ok: boolean; scanned: number }>('/api/koreader/scan', { method: 'POST' }),

  koreaderDocs: () => request<{ items: KoreaderDoc[] }>('/api/koreader/docs'),

  /**
   * 清理重复项（move 进回收目录，**不是删除**）。
   *
   * `remove` 的条目在**多库**下必须带 `library_id`：同名文件可以同时存在于多个库，
   * 只给名字时后端只能按名字反查出其中一个，那个库未必是这条命中的库。
   */
  duplicatesResolve: (keep: string, remove: Array<string | { name: string; library_id?: string | null }>) =>
    request<RecycleResult>('/api/duplicates/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keep, remove }),
    }),

  missing: (libraryId = '') =>
    request<{ items: MissingItem[]; total: number }>(
      `/api/missing${libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : ''}`,
    ),

  // ---------- 书库：图书馆浏览 / 书籍详情 ----------
  /**
   * 书目列表（可分页）。
   *
   * 第 88 期：响应新增可选 `scanning`（**正在刷新索引的库 id 列表**）。
   * ⚠️ 它**可选**（后端并行开发中）—— 拿不到就当空数组，别因此报错。
   *
   * 第 88 期 C 批：新增可选 `limit` / `offset`。
   *   · **不传参数 ⇒ 与改造前一致**（返回全部）—— 别的调用方（侧栏 / 其它视图）照旧拿全量；
   *   · 传了就分页：`total` 仍是**未切片前的总数**，`has_more` 告诉我们还有没有下一页。
   * ⚠️ `limit` / `offset` / `has_more` 三个字段**可选**：拿不到（旧后端）就由 store 兜底推。
   */
  books: (opts?: { limit?: number; offset?: number }) => {
    const q = new URLSearchParams()
    if (opts && typeof opts.limit === 'number') q.set('limit', String(opts.limit))
    if (opts && typeof opts.offset === 'number') q.set('offset', String(opts.offset))
    const qs = q.toString()
    return request<{
      items: BookCard[]
      total: number
      scanning?: string[]
      limit?: number | null
      offset?: number
      has_more?: boolean
    }>(`/api/books${qs ? `?${qs}` : ''}`)
  },

  bookDetail: (id: string) =>
    request<BookDetail>(`/api/books/${encodeURIComponent(id)}`),

  /** 可用的书城目录来源（含闸门状态与每个来源的诚实档位，第 85 期批次 B） */
  tocSources: () =>
    request<{ items: TocSourceItem[]; enabled: boolean; reason: string }>('/api/toc/sources'),

  /**
   * 取一本书的目录（**只读目录页**，第 85 期批次 B）。
   *
   * `url` 可选：手动指定书页 ⇒ 跳过自动匹配、视为确定。
   * ⚠️ 取不到时这里会抛（错误信息就是后端的**原因原文**），但**失败同样落库** ——
   * 调用方在 `catch` 之后刷新详情，就能看到「上次为什么没取到」。
   */
  tocFetch: (bookId: string, source: string, url = '') =>
    request<{ mapped: number; total: number; matched_title: string; confidence: number }>(
      '/api/toc/fetch',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ book_id: bookId, source, url }),
      },
    ),

  /** 还原为本地目录（删掉这本书的书城目录与映射，零副作用） */
  tocClear: (bookId: string) =>
    request<{ ok: boolean; cleared: number }>(`/api/toc/${encodeURIComponent(bookId)}`, {
      method: 'DELETE',
    }),

  /**
   * 删除一本书（第 64 期；第 75 期扩到**三份文件**）：文件**移入回收站**（可恢复，不是真删），
   * 而进度 / 批注 / 书签 / 评分一律**保留** —— `book_id` 由「库 id + 文件名」派生，
   * 文件放回原路径数据就接回来了（详见后端 `api_delete_book` 的 docstring）。
   *
   * ⚠️ 第 75 期起一次删的是**同一本书的三份拷贝**（用户口径「本地和项目里的都删掉」）：
   * `library` = 书库根里的成品、`source` = 收书目录里的原件（用户本地那份）、
   * `copy` = 项目产出的出版副本。三份**逐份独立**，每份 `state` 可能是
   * `recycled`（已回收）/ `missing`（本来就没有 —— **不是错误**）/ `failed`（移不动）。
   *
   * 返回里的 `siblings` 是**同目录同 stem 的其它格式**（`三体.epub` 删了就剩 `三体.mobi`）：
   * 它们是另外两张卡、两个 id，不会被一起删。⚠️ 这是**删完之后**才知道的，
   * 确认文案里要点名兄弟文件，只能在删之前另拉一次详情（见 `BookActionsMenu`）。
   */
  deleteBook: (id: string) =>
    request<{
      ok: boolean
      id: string
      name: string
      /** ② 书库根成品在回收目录里的文件名；它本来就不在磁盘上时为 null */
      recycled: string | null
      siblings: string[]
      /** 三份文件各自的结果（第 75 期）—— 前端据此写 toast，别只说「已删除」 */
      targets: Record<
        'library' | 'source' | 'copy',
        { state: 'recycled' | 'missing' | 'failed'; recycled?: string; error?: string }
      >
    }>(`/api/books/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  /** 服务器上这本书的绝对路径（只有本机/局域网来源才拿得到，见 BookLocalPaths） */
  bookLocalPaths: (id: string) =>
    request<BookLocalPaths>(`/api/books/${encodeURIComponent(id)}/local-paths`),

  // ---------- 账户（单用户轻登录） ----------
  login: (user: string, pin: string) =>
    request<AuthResult>('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user, pin }),
    }),

  me: () => request<MeInfo>('/api/auth/me'),

  /** 修改当前账号密码（需原密码） */
  changePin: (oldPin: string, newPin: string) =>
    request<{ ok: boolean }>('/api/auth/pin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_pin: oldPin, new_pin: newPin }),
    }),

  /** 当前账号资料（头像以可分发 URL 形式返回）。 */
  getProfile: () => request<AccountProfile>('/api/account/profile'),

  /** 更新展示名 / 时区（缺字段则沿用当前值）。 */
  updateProfile: (p: { display_name?: string; timezone?: string }) =>
    request<AccountProfile>('/api/account/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    }),

  /** 上传账号头像（JPG/PNG/WEBP，≤5MB）。 */
  uploadAvatar: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ ok: boolean; avatar_url: string }>('/api/account/avatar', {
      method: 'POST',
      body: form,
    })
  },

  /** 移除账号头像，回退占位。 */
  deleteAvatar: () =>
    request<{ ok: boolean }>('/api/account/avatar', { method: 'DELETE' }),

  /** 账号头像 URL，给 `<img src>` 用（带 ?token=；可选 ts 做缓存破坏）。 */
  accountAvatarUrl: (ts?: number) => {
    const t = _authToken()
    const q = t ? `?token=${encodeURIComponent(t)}` : ''
    return `/api/account/avatar${q}${ts ? `${q ? '&' : '?'}t=${ts}` : ''}`
  },

  // ---------- 阅读器：章节内容 / 进度 / 批注 ----------
  chapter: (id: string, index: number) =>
    request<ChapterContent>(
      `/api/books/${encodeURIComponent(id)}/chapter/${index}`,
    ),

  /**
   * 一本书的**书内样式**（EPUB 自带的 `<style>` / `<link rel=stylesheet>` / `@import` 链，
   * 里面的图片与字体 URL 已由后端改写成 asset 接口并**带上令牌**）。
   *
   * ⚠️ 与正文**分两条通道**下发是刻意的（第 76 期）：样式必须挂在**被测量的正文容器
   * 之外** —— CSS 文本本身是文本节点，注入进 `.reader-content` 会把 `textContent`
   * 顶长，让进度 / 批注的字符偏移全线错位（见后端 `core/epub_cfi`）。
   *
   * 取不到样式（非 EPUB / 坏书 / 没有样式）返回空串，**不是错误** —— 调用方据此
   * 回落应用自身的排版。走 Bearer 即可（它是 `fetch` 取的，不是浏览器原生请求），
   * 但样式**内部**引用的字体 / 背景图是原生请求，所以 `css` 里的 asset URL 已带令牌。
   */
  epubCss: (id: string) =>
    request<{ css: string; sheets: string[]; fixed_layout: boolean }>(
      `/api/books/${encodeURIComponent(id)}/epub-css`,
    ),

  /**
   * 读阅读进度（第 63 期 4/6）。两个口径：
   * - **不给** `fileRel` = 书级：读者最后在看的那个文件的读点（书架 / Komga 走这条）；
   * - **给** `fileRel` = 精确到那个文件：阅读器恢复位置时用。
   *
   * ⚠️ 判据必须是 `fileRel !== undefined`，**不能**写成真值判断（`fileRel ? … : …`）：
   * 「不给」与「给空串」在服务端是**两个不同的落点** —— 给空串要的是
   * `file_rel=''` 那一行（= 不知道文件的那次写入），不给要的是 `updated_at`
   * 最新的那一行。空串是个合法取值，不是「没有」。（后端由
   * `tests/test_progress_per_file.py` 的接口层用例钉住。）
   */
  getProgress: (id: string, fileRel?: string) =>
    request<ProgressState>(
      `/api/books/${encodeURIComponent(id)}/progress` +
        (fileRel !== undefined ? `?file_rel=${encodeURIComponent(fileRel)}` : ''),
    ),

  setProgress: (id: string, locator: number, percent: number, offset?: number, fileRel?: string) =>
    // updated_at（第 56 期）：服务端写入时间戳，前端据此更新「本机上次写入」基准
    request<{ ok: boolean; updated_at?: number }>(`/api/books/${encodeURIComponent(id)}/progress`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        locator,
        percent,
        // offset（第 54 期）：章内字符偏移（textContent 坐标），服务端据此生成 CFI；
        // 不给就是旧行为（恢复回落「章 + 全书百分比」）
        ...(offset === undefined ? {} : { offset }),
        // file_rel（第 63 期 4/6）：这份进度属于哪个文件（库内相对路径）。
        // **不给 = 书级** —— KOReader 同步 / Komga / 标记已读完这些不知道文件的
        // 写入方走的正是这条，与加这一列之前逐字节相同
        ...(fileRel === undefined ? {} : { file_rel: fileRel }),
      }),
    }),

  listAnnotations: (id: string) =>
    request<{ items: Annotation[] }>(
      `/api/books/${encodeURIComponent(id)}/annotations`,
    ),

  addAnnotation: (id: string, a: Omit<Annotation, 'id' | 'created_at' | 'origin'>) =>
    request<{ id: number; ok: boolean }>(
      `/api/books/${encodeURIComponent(id)}/annotations`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(a),
      },
    ),

  /** **移入垃圾桶**（软删除）。彻底删除走 `purgeAnnotation`。 */
  deleteAnnotation: (id: string, aid: number) =>
    request<{ ok: boolean; trashed: boolean }>(
      `/api/books/${encodeURIComponent(id)}/annotations/${aid}`,
      { method: 'DELETE' },
    ),

  restoreAnnotation: (id: string, aid: number) =>
    request<{ ok: boolean }>(
      `/api/books/${encodeURIComponent(id)}/annotations/${aid}/restore`,
      { method: 'POST' },
    ),

  /** 彻底删除（不可恢复）。只对垃圾桶里的条目成立，活跃条目会 400。 */
  purgeAnnotation: (id: string, aid: number) =>
    request<{ ok: boolean }>(
      `/api/books/${encodeURIComponent(id)}/annotations/${aid}/purge`,
      { method: 'DELETE' },
    ),

  // ---------- 书签（第 34 期） ----------

  /** 某本书的书签。默认只给活跃条目；`includeTrashed` 时额外带回有序的 `trashed`。 */
  listBookmarks: (id: string, includeTrashed = false) =>
    request<{ items: Bookmark[]; total: number; trashed?: Bookmark[] }>(
      `/api/books/${encodeURIComponent(id)}/bookmarks${includeTrashed ? '?include_trashed=1' : ''}`,
    ),

  /** 加书签（或复活同位置的墓碑、合并并发冲突）。`anchor` 是去重键。 */
  addBookmark: (
    id: string,
    b: { anchor: string; chapter: number; percent: number; label?: string; updated_at?: number },
  ) =>
    request<BookmarkSaveResult>(`/api/books/${encodeURIComponent(id)}/bookmarks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(b),
    }),

  /** 改备注 / 位置（只对活跃书签）。返回体同加书签：`applied=false` 即服务端胜。 */
  updateBookmark: (
    id: string,
    bmid: number,
    b: { label?: string; percent?: number; chapter?: number; updated_at?: number },
  ) =>
    request<{ ok: boolean; found: boolean; applied?: boolean; server?: Bookmark }>(
      `/api/books/${encodeURIComponent(id)}/bookmarks/${bmid}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(b),
      },
    ),

  /** **移入垃圾桶**（软删除）。彻底删除走 `purgeBookmark`。 */
  deleteBookmark: (id: string, bmid: number) =>
    request<{ ok: boolean; trashed: boolean }>(
      `/api/books/${encodeURIComponent(id)}/bookmarks/${bmid}`,
      { method: 'DELETE' },
    ),

  restoreBookmark: (id: string, bmid: number) =>
    request<{ ok: boolean }>(
      `/api/books/${encodeURIComponent(id)}/bookmarks/${bmid}/restore`,
      { method: 'POST' },
    ),

  /** 彻底删除（不可恢复）。只对垃圾桶里的条目成立，活跃条目会 400。 */
  purgeBookmark: (id: string, bmid: number) =>
    request<{ ok: boolean }>(
      `/api/books/${encodeURIComponent(id)}/bookmarks/${bmid}/purge`,
      { method: 'DELETE' },
    ),

  // ---------- 系列 ----------
  series: () => request<{ items: SeriesItem[]; total: number }>('/api/series'),

  seriesDetail: (name: string) =>
    request<SeriesDetail>(`/api/series/${encodeURIComponent(name)}`),

  // 系列级元数据（第 12 期 C3）：只写服务端 DB，不动 EPUB 文件
  seriesMeta: (name: string) =>
    request<{
      ok: boolean
      meta: SeriesMeta
      state: SeriesMetaState
      fields: string[]
      labels: Record<string, string>
    }>(`/api/series/${encodeURIComponent(name)}/meta`),

  saveSeriesMeta: (name: string, fields: Record<string, string>) =>
    request<{ ok: boolean; meta: SeriesMeta; state: SeriesMetaState }>(
      `/api/series/${encodeURIComponent(name)}/meta`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
      },
    ),

  fetchSeriesMeta: (name: string) =>
    request<{
      ok: boolean
      result: {
        ok: boolean
        error?: string
        score?: number
        matched_title?: string
        source?: string
      }
      meta: SeriesMeta
    }>(`/api/series/${encodeURIComponent(name)}/fetch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    }),

  /** 批量抓取：一次只处理一批（`remaining` > 0 时由调用方循环，避免单请求超时） */
  fetchAllSeriesMeta: (payload: { names?: string[]; limit?: number } = {}) =>
    request<{ total: number; ok: number; failed: number; remaining: number }>(
      '/api/series/fetch-all',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),

  seriesRenumberPreview: (name: string) =>
    request<{ series: string; items: SeriesRenumberItem[]; total: number; changing: number }>(
      `/api/series/${encodeURIComponent(name)}/renumber/preview`,
    ),

  seriesRenumberApply: (name: string, items: Array<{ name: string; new_index: string }>) =>
    request<{
      ok: boolean
      series: string
      renumbered: number
      /** 被清空序号的那些（`new_index` 传空串）—— 服务端存「显式无值」 */
      cleared?: Array<{ name: string; book_id: string; old_index: string; new_index: string }>
      skipped: Array<{ name: string; error: string }>
      mismatched: string[]
    }>(`/api/series/${encodeURIComponent(name)}/renumber/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    }),

  // ---------- 收藏夹 ----------
  collections: () => request<{ items: CollectionItem[] }>('/api/collections'),

  createCollection: (name: string) =>
    request<{ id: number; name: string }>('/api/collections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  collectionDetail: (id: number) =>
    request<CollectionDetail>(`/api/collections/${id}`),

  deleteCollection: (id: number) =>
    request<{ ok: boolean }>(`/api/collections/${id}`, { method: 'DELETE' }),

  renameCollection: (id: number, name: string) =>
    request<{ ok: boolean; id: number; name: string }>(`/api/collections/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  addToCollection: (id: number, bookId: string) =>
    request<{ ok: boolean }>(`/api/collections/${id}/books`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ book_id: bookId }),
    }),

  removeFromCollection: (id: number, bookId: string) =>
    request<{ ok: boolean }>(
      `/api/collections/${id}/books/${encodeURIComponent(bookId)}`,
      { method: 'DELETE' },
    ),

  bookCollections: (bookId: string) =>
    request<{ items: number[] }>(
      `/api/books/${encodeURIComponent(bookId)}/collections`,
    ),

  // ---------- 作者 ----------
  authors: () => request<{ items: AuthorItem[]; total: number }>('/api/authors'),

  authorDetail: (name: string) =>
    request<AuthorDetail>(`/api/authors/${encodeURIComponent(name)}`),

  /** 作者头像 URL，直接给 `<img src>` 用（同封面，必须带 ?token=）。 */
  authorPhotoUrl: (name: string) => {
    const t = _authToken()
    return `/api/authors/${encodeURIComponent(name)}/photo${t ? `?token=${encodeURIComponent(t)}` : ''}`
  },

  /** 设置作者传记的本地覆盖（空串 = 撤销覆盖，回退到在线传记）。 */
  setAuthorBio: (name: string, bio: string) =>
    request<AuthorMeta>(`/api/authors/${encodeURIComponent(name)}/bio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bio }),
    }),

  /** 设置作者排序名的本地覆盖（空串 = 撤销覆盖，排序回退到在线排序名 / 显示名）。 */
  setAuthorSortName: (name: string, sortName: string) =>
    request<AuthorMeta>(`/api/authors/${encodeURIComponent(name)}/sort-name`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sort_name: sortName }),
    }),

  /**
   * 批量回填作者派生排序键（第 43 期）。只写派生态列 `sort_name`，**不动**用户覆盖列。
   * 返回 `{total, filled, skipped, details}` —— details 只列真正补上的。
   */
  backfillAuthorSortNames: () =>
    request<{
      ok: boolean
      total: number
      filled: number
      skipped: number
      details: { name: string; sort_name: string }[]
    }>('/api/authors/sort-name/backfill', { method: 'POST' }),

  /** 上传作者头像作为本地覆盖。 */
  uploadAuthorPhoto: (name: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<AuthorMeta>(`/api/authors/${encodeURIComponent(name)}/photo`, {
      method: 'POST',
      body: form,
    })
  },

  /** 撤销本地头像覆盖，回退到在线照片。 */
  clearAuthorPhoto: (name: string) =>
    request<AuthorMeta>(`/api/authors/${encodeURIComponent(name)}/photo`, { method: 'DELETE' }),

  /** 抓取单个作者的在线传记 / 头像。 */
  fetchAuthor: (name: string) =>
    request<AuthorMeta>(`/api/authors/${encodeURIComponent(name)}/fetch`, { method: 'POST' }),

  /** 抓取全部作者的在线元数据。 */
  fetchAllAuthors: () =>
    request<{ total: number; ok: number; failed: number }>('/api/authors/fetch-all', {
      method: 'POST',
    }),

  // ---------- 批注总览 ----------
  /** 跨书批注。默认只给活跃批注（既有契约）；`includeTrashed` 时把垃圾桶一并带回。 */
  allAnnotations: (includeTrashed = false) =>
    request<{ items: AllAnnotation[]; total: number }>(
      `/api/annotations${includeTrashed ? '?include_trashed=1' : ''}`,
    ),

  annotationOverview: () => request<AnnotationOverview>('/api/annotations/overview'),

  /**
   * 从各书库里找 **KOReader 的批注导出文件**并导入（第 63 期 6/6）。
   *
   * ⚠️ 这不是 kosync。官方 kosync **只同步进度、没有批注端点** —— KOReader 的批注
   * 跨设备同步走的是**文件**（关书时导出 `<书名>.annotations.lua`）。
   *
   * `apply = false`（默认）**只看不写**：先让用户看到「会导多少条」再落库。
   * 导入是幂等的，但**永不删除** —— 格式里没有墓碑。
   */
  importKoreaderAnnotations: (apply = false) =>
    request<KoreaderImportResult>(
      `/api/annotations/import-koreader${apply ? '?apply=1' : ''}`,
      { method: 'POST' },
    ),

  /**
   * 侧栏「浏览」组的三计数。不传库 = 全部书库（侧栏用这个：三个目标页都是跨库的，
   * 计数跨库才对得上）；浏览页传当前库，取该库自己的数字。服务端 60 秒节流。
   */
  browseCounts: (libraryId = '') =>
    request<BrowseCounts>(
      `/api/browse-counts${libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : ''}`,
    ),

  // ---------- 书库（第 10 期：库实体 / 分面 / 能力 / 迁移） ----------

  /** 书库实体列表（含书数 / 是否存在 / 可写）。 */
  libraries: () => request<LibrariesResult>('/api/libraries'),

  /**
   * 每库的**扫描状态**（第 88 期）。
   *
   * 书架在「有库正在建索引」时**每 2 秒**拉一次它，扫完即停（`stores/library.ts` 管轮询）。
   * ⚠️ `items` 可选：后端接口并行开发中，未落地时返回 `{}` 也不该让界面报错。
   */
  librariesScanState: () => request<{ items?: LibraryScanState[] }>('/api/libraries/scan-state'),

  /** 格式分面（原 `/api/libraries` 语义，第 10 期改址到 `/api/library-facets`）。 */
  libraryFacets: () => request<{ items: LibraryFacet[] }>('/api/library-facets'),

  /**
   * 阅读阈值（第 40 期）：`{started, finished}`，0–100。
   *
   * 不给库 id = **全局值**（书架 / 仪表盘这类跨库视图用）；给了 = 该库的**生效值**
   * （每库覆写 ?? 全局）。⚠️ 别在界面里再写 `99.5` —— 见 `lib/readingThresholds.ts`。
   */
  readingThresholds: (libraryId = '') =>
    request<{ library_id: string; started: number; finished: number }>(
      `/api/reading-thresholds${libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : ''}`,
    ),

  /**
   * 来源根目录树（第 41 期，支持不定数量来源根）。
   * - 不传参：返回所有已配置来源根 `roots`（每张含 index / name / path / exists / entries）。
   * - 传 `root` + `path`：返回该根下某目录的子项 `entries`（下钻）。
   */
  librarySourceDirs: (params?: { root?: number; path?: string }) =>
    request<{
      roots?: { index: number; name: string; path: string; exists: boolean; entries: number }[]
      root_index?: number
      root_name?: string
      base?: string
      path?: string
      entries?: { name: string; path: string; type: 'dir' | 'file' }[]
    }>(
      '/api/libraries/source-dirs' +
        (params?.root != null
          ? `?root=${params.root}&path=${encodeURIComponent(params.path ?? '')}`
          : ''),
    ),

  /** 新建书库（**只登记，不搬文件**）。第 41 期：内容来源为多个文件夹（source_dirs）。 */
  createLibrary: (payload: {
    name: string
    type: LibraryType
    /** 第 41 期：内容来源 = 多个文件夹的绝对路径（就地引用，跨根合法） */
    source_dirs: string[]
    rules?: unknown
    sort_order?: number
    /** 刮削出版成品目录（可选；空 = 该库不产出硬链接副本） */
    publish_path?: string
    /** 逐库扫描调度 */
    watch?: number
    scan_interval?: number
    scan_cron?: string
    /** 图标 key（取自 `lib/icons.ts` 的 `ICONS`；空 = 不显示图标） */
    icon?: string
    /** 允许的格式（空数组 = 继承库类型默认白名单） */
    allowed_exts?: string[]
    /** 排除图案（glob；含 `/` 匹相对库根的路径，否则只匹文件名） */
    exclude?: string[]
  }) =>
    request<{ ok: boolean; library: LibraryEntity }>('/api/libraries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 改库属性（改 `source_dirs` 只改登记，不搬文件）。 */
  updateLibrary: (
    id: string,
    payload: Partial<{
      name: string
      type: LibraryType
      /** 第 41 期：改内容来源 = 多个文件夹的绝对路径 */
      source_dirs: string[]
      rules: unknown
      sort_order: number
      /** 传空串 = 关闭该库的副本产出（不动已有副本） */
      publish_path: string
      watch: number
      scan_interval: number
      scan_cron: string
      /** 图标 key；空串 = 不显示图标 */
      icon: string
      /** 空数组 = 恢复「继承库类型默认白名单」（**不是**「一个格式都不收」） */
      allowed_exts: string[]
      /** 空数组 = 不过滤 */
      exclude: string[]
    }>,
  ) =>
    request<{ ok: boolean; library: LibraryEntity }>(`/api/libraries/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /**
   * 移除书库（**第 81 期语义变更**）：**默认只删项目内登记，不动任何磁盘文件** ——
   * 同步、立即返回。旧口径（第 75 期「非空库需 force、force 回收 ②③」）已作废：
   * 库就地引用用户目录时，被当作「② 书库内成品」回收掉的就是**用户的本地原件**。
   *
   * 传 `purgeFiles=true` 才连文件一起清（书库内文件 + 出版副本移入回收站），
   * 且它在**后台任务**里跑（长操作绝不挂在 HTTP 请求上，见第 81 期线上故障）——
   * 返回 `task_id`，进度到任务中心看。① 收书目录里的本地原件**永不**回收。
   */
  deleteLibrary: (id: string, purgeFiles = false) =>
    request<{
      ok: boolean
      removed: string
      /** 移除时该库的书目数 */
      books: number
      /** 是否受理了「连文件一起清理」 */
      purge_files: boolean
      /** 受理的待回收份数（0 = 没有可清理的东西 / 未要求清理） */
      targets: number
      /** 后台清理任务 id；没有可清理的东西时为 null */
      task_id: string | null
    }>(
      `/api/libraries/${encodeURIComponent(id)}${purgeFiles ? '?purge_files=true' : ''}`,
      { method: 'DELETE' },
    ),

  /**
   * 回收站现状（第 81 期）：**台账条目**（可按原路径还原）+ **无台账孤儿**
   * （第 81 期之前的历史回收，还原时要显式指定目录）。
   *
   * `limit` 只截返回条数（2400 份不该一次拉满），计数始终是全量。
   */
  recycleList: (limit = 0) =>
    request<RecycleListPayload>(`/api/recycle${limit ? `?limit=${limit}` : ''}`),

  /**
   * 回收站还原（**把文件搬回原处**）：立即返回 `task_id`，后台逐项搬。
   *
   * 三种入参可组合：`ids`（台账行，按各自原路径）/ `names`（孤儿，必须带 `target_dir`）/
   * `all: true`（还原全部台账条目）。目标是**幂等可续跑**的：还原成功即删台账行。
   * 解析不出的条目在 `errors` 里如实回报（不静默丢）。
   */
  recycleRestore: (payload: {
    ids?: number[]
    names?: string[]
    target_dir?: string
    all?: boolean
  }) =>
    request<{
      ok: boolean
      task_id: string | null
      total: number
      errors: Array<{ id?: number; name?: string; error: string }>
      note?: string
    }>('/api/recycle/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 重新扫描单个库。 */
  scanLibrary: (id: string) =>
    request<{ ok: boolean; id: string; count: number }>(
      `/api/libraries/${encodeURIComponent(id)}/scan`,
      { method: 'POST' },
    ),

  // ---------- 每库覆盖 + 同名冲突（第 13 期）----------
  /**
   * 该库的**生效设置**：`每库覆写 ?? 全局`。返回里同时带全局值与 `overridden`，
   * 界面才能说清「这一项是跟着全局走、还是这个库单独设过」。
   * `schema` 已按库类型能力收窄 —— 漫画库不会返回元数据策略这类它用不上的项。
   */
  librarySettings: (id: string) =>
    request<LibrarySettingsResult>(`/api/libraries/${encodeURIComponent(id)}/settings`),

  /**
   * 写入覆盖项：`{键: 值}`。**值传 `null` = 该项恢复继承全局**。
   * `metadata_fetch.fields` 支持字段级恢复（`{"fields": {"tags": null}}`）。
   * 键名用全局配置的点分路径（`output.layout` / `naming.pattern` …）。
   */
  librarySettingsUpdate: (id: string, values: Record<string, unknown>) =>
    request<LibrarySettingsResult>(`/api/libraries/${encodeURIComponent(id)}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    }),

  /** 恢复继承：给 keys 只清这几项，不给 = 全部回到全局值。 */
  librarySettingsReset: (id: string, keys?: string[]) =>
    request<LibrarySettingsResult>(
      `/api/libraries/${encodeURIComponent(id)}/settings${
        keys && keys.length ? `?keys=${encodeURIComponent(keys.join(','))}` : ''
      }`,
      { method: 'DELETE' },
    ),

  /** 同名冲突清单（book_id 撞车：跨库同名 / 库内同名）。 */
  libraryConflicts: () => request<ConflictsResult>('/api/library-conflicts'),

  /**
   * 应用冲突修复。只回传清单里确认过的条目，后端会**再校验一遍**；
   * 改名会换 book_id，关联数据由后端一并搬迁（`remapped` 即搬迁条数）。
   */
  libraryConflictsApply: (
    items: Array<{ old: string; new: string; library_id?: string | null }>,
  ) =>
    request<ConflictApplyResult>('/api/library-conflicts/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    }),

  /** 同一本书的**副本**清单（第 87 期）：名字只差副本后缀 / 破折号 / 全角半角。 */
  libraryCopies: () => request<CopiesResult>('/api/library-copies'),

  /** 待展开的容器（`format === 'ZIP'`，第 87 期）：展开是它们唯一的出路。 */
  libraryContainers: () => request<ContainersResult>('/api/library-containers'),

  /**
   * 展开容器成真正可读的书（第 87 期）。
   * ⚠️ `removeSource` 默认 false —— 删源不可逆，必须由用户在界面上显式选。
   */
  unpackBook: (bid: string, removeSource = false) =>
    request<UnpackResult>(`/api/books/${encodeURIComponent(bid)}/unpack`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remove_source: removeSource }),
    }),

  // ---------- 书源：导入 / 台账 / 登录 / 验证（第 86 期）----------

  /**
   * 导入书源（Legado 原文或本项目导出文件）。
   * ⚠️ `dry_run` 默认 true —— 一个字节都不写，先出差异表；确认后才带 `resolutions` 落盘。
   * `resolutions` 里**非法取值一律当没给**（后端退回判定的默认动作），不会静默覆盖。
   */
  sourcesImport: (body: {
    payload: unknown
    origin?: string
    dry_run?: boolean
    resolutions?: Record<string, string>
  }) =>
    request<SourceImportResult>('/api/sources/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  /** 导入历史（新的在前）。 */
  sourcesImports: (limit = 20) =>
    request<{ items: Record<string, unknown>[] }>(`/api/sources/imports?limit=${limit}`),

  /** 导出全部用户源（导出 → 导入是幂等的）。 */
  sourcesExport: () => request<unknown>('/api/sources/export'),

  /** 台账全量：启停 / 档位 / 分组 / 最近验证 / 最近追更。 */
  sourcesLedger: () => request<{ items: SourceLedgerRow[] }>('/api/sources/ledger'),

  /** 启停一个书源（文件不动，只不注册；内置源会被后端如实拒绝）。 */
  sourceEnabled: (name: string, enabled: boolean) =>
    request<{ ok: boolean; enabled: boolean }>(
      `/api/sources/${encodeURIComponent(name)}/enabled`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      },
    ),

  /** 覆盖历史（只有元数据，不含旧规则原文）。 */
  sourceHistory: (name: string, limit = 20) =>
    request<{ items: SourceHistoryItem[] }>(
      `/api/sources/${encodeURIComponent(name)}/history?limit=${limit}`,
    ),

  /** 回滚到某条历史里的旧规则（覆盖前已备份，这就是兑现处）。 */
  sourceRollback: (name: string, historyId: string) =>
    request<Record<string, unknown>>(
      `/api/sources/${encodeURIComponent(name)}/rollback`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history_id: historyId }),
      },
    ),

  /** 按台账里的**原始原文**重新判定能力档位（引擎升级后老源的重新体检）。 */
  sourceReanalyze: (name: string) =>
    request<{ name: string; supported: string; usable: boolean }>(
      `/api/sources/${encodeURIComponent(name)}/reanalyze`,
      { method: 'POST' },
    ),

  /** 登录态元数据（**没有任何 cookie 值**）。 */
  sourceCookie: (name: string) =>
    request<SourceCookieStatus>(`/api/sources/${encodeURIComponent(name)}/cookie`),

  /** 保存粘贴的 Cookie（`domains` 可选，用来覆盖书源声明的补域）。 */
  sourceCookieSave: (name: string, text: string, domains: string[] = []) =>
    request<SourceCookieStatus>(`/api/sources/${encodeURIComponent(name)}/cookie`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, domains }),
    }),

  /** 清除登录态；`cleared=false` = 本来就没有（界面据此如实说）。 */
  sourceCookieClear: (name: string) =>
    request<{ ok: boolean; cleared: boolean }>(
      `/api/sources/${encodeURIComponent(name)}/cookie`,
      { method: 'DELETE' },
    ),

  /** 变量：只回「每个键有没有设置」+ 规则里引用到的键（提示还差哪几个）。 */
  sourceVars: (name: string) =>
    request<SourceVarsResult>(`/api/sources/${encodeURIComponent(name)}/vars`),

  /** 写变量；值传空串 = **清除该键**。 */
  sourceVarsSave: (name: string, values: Record<string, string>) =>
    request<SourceVarsResult>(`/api/sources/${encodeURIComponent(name)}/vars`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    }),

  /** 登录面板的全部输入（Cookie 表单 / 变量表单 / 登录页地址 / 作者说明）。 */
  sourceLoginSpec: (name: string) =>
    request<SourceLoginSpec>(`/api/sources/${encodeURIComponent(name)}/login-spec`),

  /** 单源连通性探测（结果形状宽松，界面按需渲染）。 */
  sourceProbe: (name: string) =>
    request<Record<string, unknown>>(`/api/sources/${encodeURIComponent(name)}/probe`, {
      method: 'POST',
    }),

  /** 全部源探测（逐条回报）。 */
  sourcesProbeAll: () =>
    request<Record<string, unknown>>('/api/sources/probe-all', { method: 'POST' }),

  /**
   * 批量操作（启用 / 停用 / 删除 / 重分析）。
   * ⚠️ 后端**逐条回报**（`items`），混选里必然有内置源与未知源 —— 不做「成功 200 / 失败 500」
   * 那种整批语义（整批失败会让用户不知道哪几条真的动了）。
   */
  sourcesBulk: (action: 'enable' | 'disable' | 'delete' | 'reanalyze', names: string[]) =>
    request<{ action: string; items: Array<{ name: string; ok: boolean; note: string }>; ok_count: number }>(
      '/api/sources/bulk',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, names }),
      },
    ),

  /** 追更调度状态（第 86 期）：是否在跑 / 开关 / 间隔。 */
  autoupdateState: () =>
    request<{ running: boolean; enabled: boolean; interval_hours: number }>('/api/autoupdate'),

  /**
   * 立即跑一轮追更。
   * ⚠️ 会**出网**且可能跑一阵（单轮 ≤ max_books 本 × 每本节流）——界面要显示进行态；
   * 开关与数值本身走 `saveConfig({auto_update: …})`，**不另开写接口**（同一份配置两种写法必然分叉）。
   */
  autoupdateRun: () =>
    request<{ total: number; ok: number; skipped: number; errors: number; added: number }>(
      '/api/autoupdate/run',
      { method: 'POST' },
    ),

  // ---------- 刮削出版（第 18 期）----------
  /** 刮削台账：概览计数 + 条目 + worker 运行态（页面轮询此端点）。 */
  scrapeState: (query: { library_id?: string; status?: string; q?: string } = {}) => {
    const p = new URLSearchParams()
    if (query.library_id) p.set('library_id', query.library_id)
    if (query.status) p.set('status', query.status)
    if (query.q) p.set('q', query.q)
    const qs = p.toString()
    return request<ScrapeState>(`/api/scrape/state${qs ? `?${qs}` : ''}`)
  },

  /**
   * 开始 / 重新刮削（**异步**：入队后由后端单线程 worker 串行跑，进度看 /state）。
   * `force` = 忽略「已是最新」强制重抓；`only_failed` = 只重排当前失败的条目。
   */
  scrapeRun: (payload: { library_id?: string; force?: boolean; only_failed?: boolean } = {}) =>
    request<{ ok: boolean; queued: number; total: number; started: boolean }>(
      '/api/scrape/run',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),

  /**
   * 校验副本是否还在。缺失 → 标「待确认」，源不在 → 标「孤本」。
   * ⚠️ 只标记不处置：不删源文件、不自动重建。
   */
  scrapeVerify: (libraryId = '') =>
    request<{
      ok: boolean
      checked: number
      removed: Array<{ book_id: string; name: string; source: string; removed_path: string }>
      orphan: Array<{ book_id: string; name: string; copy: string }>
    }>(`/api/scrape/verify${libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : ''}`, {
      method: 'POST',
    }),

  /**
   * 对某本书执行**显式**处置。这是唯一能把「待确认 / 孤本」带回已出版的入口。
   * - `delete_source` 原文件移入回收站（绝不真删）
   * - `keep_source`   保留原文件，不再提醒
   * - `rebuild`       重新生成副本（按当前元数据重写）
   * - `keep_copy`     保留副本（原文件已不在，以副本为准）
   * - `recycle_copy`  副本移入回收站并清台账
   */
  scrapeResolve: (bid: string, action: ScrapeAction) =>
    request<{ ok: boolean; action: string; recycled?: string; note?: string }>(
      `/api/scrape/${encodeURIComponent(bid)}/resolve`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      },
    ),

  /** 当前库（或「全部书库」）的能力清单。 */
  features: (libraryId = '') =>
    request<FeaturesResult>(
      `/api/features${libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : ''}`,
    ),

  // ---------- 跨库移动（用户点选） ----------
  // 一律 POST：选择集可能几十本、book_id 里带 `$`，塞进 query string 迟早撞长度上限。

  /** 可选的目标库（含逐库相容判定与理由 —— 前端照原样显示，别自己编一套说法）。 */
  bookMoveTargets: (bookIds: string[]) =>
    request<BookMoveTargets>('/api/book-move/targets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ book_ids: bookIds }),
    }),

  /** 逐本预检：能不能搬 / 为什么不能 / 副本会去哪。**只读**。 */
  bookMovePreflight: (bookIds: string[], dstLibraryId: string, decisions?: BookMoveDecision[]) =>
    request<BookMovePreview>('/api/book-move/preflight', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ book_ids: bookIds, dst_library_id: dstLibraryId, decisions }),
    }),

  /** 落成批次（只写台账，不搬文件）。有书进不去目标库时后端翻 400。 */
  bookMovePlan: (bookIds: string[], dstLibraryId: string, decisions?: BookMoveDecision[]) =>
    request<BookMovePlanResult>('/api/book-move/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ book_ids: bookIds, dst_library_id: dstLibraryId, decisions }),
    }),

  /** 执行（**真移文件**）：立刻返回 task_id，进度去任务中心看。 */
  bookMoveApply: (batchId: string) =>
    request<{ task_id: string; batch_id: string }>('/api/book-move/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_id: batchId }),
    }),

  /** 撤回本次移动（不传 = 最近一次跨库移动批次）。同步返回真实结果。 */
  bookMoveRollback: (batchId = '') =>
    request<BookMoveRollbackResult>('/api/book-move/rollback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_id: batchId }),
    }),

  /** 最近的跨库移动批次（书架的「撤销本次移动」条用它）。 */
  bookMoveBatches: (limit = 10) =>
    request<{ items: BookMoveBatch[] }>(`/api/book-move/batches?limit=${limit}`),

  // ---------- 阅读时长（会话上报） ----------
  /**
   * 上报一段阅读时长（秒）。
   *
   * `extra` 全部可选（第 63 期）：**没给的字段不写进 body**，服务端据此记「未知」——
   * 别在这里补 0 兜底，那会把「没记录」变成「读到 0%」（见 `SessionExtra` 的说明）。
   */
  recordSession: (bookId: string, seconds: number, extra: SessionExtra = {}) =>
    request<{ ok: boolean; session_uid: string }>(
      `/api/books/${encodeURIComponent(bookId)}/session`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seconds, ...extra }),
      },
    ),

  /** 单书阅读记录（详情页「阅读日志」标签整页的数据源）。 */
  bookReadingStats: (bookId: string) =>
    request<BookReadingStats>(`/api/books/${encodeURIComponent(bookId)}/stats`),

  // ---------- 应用设置（服务端持久化） ----------
  getConfig: () => request<ConfigPayload>('/api/config'),

  saveConfig: (patch: Record<string, unknown>) =>
    request<{ ok: boolean; overrides: Record<string, unknown> }>('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),

  clearCache: () =>
    request<{ ok: boolean; removed: number; preserved?: string }>('/api/cache/clear', { method: 'POST' }),

  // ---------- 维护 ----------
  maintenance: () => request<MaintenanceInfo>('/api/maintenance'),

  /** 重建书库索引（清缓存 + 强制重扫 OUTPUT_DIR；只读操作，不动任何文件） */
  rebuildLibrary: () =>
    request<{ ok: boolean; books: number }>('/api/maintenance/library/rebuild', { method: 'POST' }),

  /** 清空回收站 —— **真删，不可恢复**（第 81 期：同批清掉回收台账，`ledger_cleared` 是条数） */
  clearRecycle: () =>
    request<{ ok: boolean; removed: number; freed: number; ledger_cleared: number }>(
      '/api/maintenance/recycle/clear',
      { method: 'POST' },
    ),

  // ---------- 高级：config.yaml 原文 ----------
  getRawConfig: () => request<RawConfig>('/api/config/raw'),

  saveRawConfig: (text: string) =>
    request<{ ok: boolean; backup: string }>('/api/config/raw', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }),

  listBackups: () => request<{ items: BackupItem[] }>('/api/config/backups'),

  restoreBackup: (name: string) =>
    request<{ ok: boolean; restored: string; backup: string }>('/api/config/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  resetConfig: () =>
    request<{ ok: boolean; backup: string }>('/api/config/reset', { method: 'POST' }),

  clearOverrides: () =>
    request<{ ok: boolean }>('/api/config/overrides', { method: 'DELETE' }),

  // ---------- 数据统计 ----------
  // top=50：让「展开全部」真的能展开到 50（服务端已收敛 1–50）；体积榜固定 50 条、与之无关
  // libraryId 为空 = 全部书库：**此时 URL 与加参数之前逐字节相同**（不带空参数），
  // 既有缓存与断言不受影响；给了才附加 library_id。
  stats: (days = 28, libraryId = '') =>
    request<StatsOverview>(
      `/api/stats?days=${days}&top=50${libraryId ? `&library_id=${encodeURIComponent(libraryId)}` : ''}`,
    ),

  readingActivity: (libraryId = '', year?: number, limit = 120) =>
    request<ReadingActivity>(
      `/api/reading-activity?limit=${limit}${libraryId ? `&library_id=${encodeURIComponent(libraryId)}` : ''}${year ? `&year=${year}` : ''}`,
    ),
}
