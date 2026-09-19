/**
 * 后端 API 封装（迁移自 v1 app.js 的 api()）。
 *
 * 约定：
 *   · 同源请求，dev 期由 vite.config.ts 的 server.proxy 转发到 localhost:8993
 *   · 统一的错误处理：非 2xx 打 console.error 并抛 Error（消息取自后端 detail）
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
  /** 活动日志目录（后端 /health 会返回） */
  logs?: string
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
   * 操作者（登录账号名）。由后端鉴权中间件写入（见 `core/activity_log.py` 的 actor）。
   * 历史条目没有该字段（字段是后加的），读取端必须按「未记录」渲染而非报错。
   */
  actor?: string
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

// ---------- 工具页（实体管理 / 批量重命名 / 重复书籍 / 缺失资源） ----------

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

/** 一条「旧名 → 新名」。conflict 为真时前端必须置灰、禁止提交。 */
export interface RenameItem {
  old: string
  new: string
  conflict: boolean
  reason: string
  /**
   * 条目所属书库（第 13 期）。**多库下必须有**：同名书在不同库都有时，
   * 只拿名字没法判断该改哪个库的文件（后端会按它取正确的库根）。
   */
  library_id?: string | null
}

export interface RenamePlan {
  items: RenameItem[]
  type?: EntityKind
  from?: string
  to?: string
  scope?: string
  pattern?: string
  /** 批量重命名规则里可用的占位符，由后端给出，避免前后端各写一份 */
  fields?: string[]
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
  /** 最佳候选是否达到置信度阈值 */
  auto_ok: boolean
  /** 字段级改动：{字段: {from, to, source, score}}（字段名是 OPF 口径，年份叫 date） */
  changes: Record<string, { from: unknown; to: unknown; source: string; score: number }>
  cover: { url: string; action: string; source: string; score: number } | null
  /** 跳过原因（例如该库关闭了在线元数据抓取、或没有够格的候选） */
  skipped: string
  error: string
}

export interface MetadataPlan {
  enabled: boolean
  items: MetadataPlanItem[]
  sources?: string[]
  threshold?: number
  /** 达到阈值可自动应用的本数 */
  auto?: number
  total?: number
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
  /** 能否自动验证凭据（StoryGraph 无公开 API → false，前端不显示验证按钮） */
  verify: boolean
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
  /** StoryGraph 这类无法验证的服务会带这个标记 */
  unsupported?: boolean
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

export interface ApplyResult {
  renamed: Array<{ old: string; new: string; library_id?: string | null }>
  errors: Array<{ old?: string; error: string }>
  count?: number
  /** 连带搬迁过关联数据（进度 / 批注 / 评分 / 收藏）的条目数 */
  remapped?: number
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
  /** 建议名（后端给的口径：`X (2).ext`），保留项为空串 */
  suggest: string
}

export interface ConflictGroup {
  id: string
  name: string
  title: string
  /** **跨库**冲突：分属不同库，最该先处理（阅读数据会张冠李戴） */
  cross_library: boolean
  library_count: number
  keep: string
  suggest: string
  items: ConflictItem[]
}

export interface ConflictsResult {
  groups: ConflictGroup[]
  total: number
  /** 其中跨库冲突组数 */
  cross_library: number
  libraries: Array<{ id: string; name: string }>
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
  num: number
  title: string
  /** 在 EPUB spine 中的顺序索引，阅读器据此加载正文 */
  index?: number
}

export interface BookVolume {
  volume: string
  chapters: BookChapter[]
}

export interface BookFile {
  name: string
  format: string
  size: number
  mtime: number
}

/** 书架网格与详情页共用的书籍卡片（对齐 docs/bookorbit-library-contract.md）。 */
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
  year: string
  publisher: string
  isbn: string
  language: string
  description: string
  issues: string[]
  /** 阅读进度 0-100（由 /api/books 附加，来自 SQLite） */
  percent?: number
  /** 最近阅读时间戳（秒） */
  updated_at?: number
  /** 批注数量 */
  annotation_count?: number
  /** 评分 1–5；**0 = 未评分**（未评分不用 0 星表示，见 core/db.py 的说明） */
  stars?: number
  /** 页数——**估算值**：EPUB 没有固定页数概念，见 core/library._pages_in */
  pages?: number
  /** 页数来源：'estimate'（EPUB 估算）/ 'archive'（漫画归档真实页数）/ 空串 */
  pages_source?: string
  /** 有声书轨数（单文件 1、目录 n）；非音频为 0 或未定义 */
  tracks?: number
  /** 所属书库 id（第 10 期多书库；`name` 仍是**相对该库根**的路径） */
  library_id?: string
  /** 所属书库类型（ebook / comic / audiobook / mixed） */
  library_type?: LibraryType
}

export interface BookDetail extends BookCard {
  chapters: BookVolume[]
  files: BookFile[]
  /** 有声书专有：轨清单（随详情一起下发，播放器首屏无需再请求一次） */
  audio_tracks?: AudioTrack[]
}

/** 单条音轨（目录型有声书里一章一文件） */
export interface AudioTrack {
  index: number
  name: string
  size: number
}

// ---------- 账户（单用户轻登录） ----------

export interface AuthResult {
  token: string
  user: string
}

export interface MeInfo {
  user: string
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
}

export interface Annotation {
  id: number
  chapter: number
  quote: string
  color: string
  note: string
  created_at: number
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
}

// ---------- 作者 ----------

export interface AuthorItem {
  name: string
  count: number
  series: string[]
  covers: SeriesCover[]
  /** 是否有本地缓存的头像（有则去 `/api/authors/{name}/photo` 取图） */
  has_photo: boolean
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

/** 作者元数据写操作的返回（btw BIO / 头像 / 抓取接口，只回生效信息不含书目） */
export interface AuthorMeta {
  ok?: boolean
  name: string
  bio: string
  bio_overridden: boolean
  has_photo: boolean
  photo_overridden: boolean
  photo_source: string
  fetched_at: number
  /** 仅抓取接口返回：本次抓取结果 */
  result?: { ok: boolean; bio?: string; has_photo?: boolean; error?: string }
}

// ---------- 批注总览 ----------

export interface AllAnnotation {
  id: number
  book_id: string
  book_title: string
  book_author: string
  chapter: number
  quote: string
  color: string
  note: string
  created_at: number
}

// ---------- 收藏夹 ----------

export interface CollectionItem {
  id: number
  name: string
  count: number
  created_at: number
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

export interface RecentRead {
  id: string
  title: string
  author: string
  percent: number
  updated_at: number
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
  /** 书库体检：缺元数据 / 无封面 / 异常文件的计数 */
  integrity: {
    missing_author: number
    missing_language: number
    no_cover: number
    zero_size: number
    unparsable: number
  }
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
  recent: RecentRead[]
}

// ---------- 应用设置（服务端持久化） ----------

export interface AppConfig {
  chapter_detection: { mode?: string; context_lines?: number; fallback?: string }
  traditionalize: boolean
  output: { format?: string; [k: string]: unknown }
  /** 成品命名规则（批量重命名的默认值，服务端持久化） */
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
   * 多书库跨库策略（第 10 期）。库实体本身存 SQLite（见 `/api/libraries`），
   * 这里只有「跨库行为」类开关。
   */
  libraries: { auto_migrate?: boolean }
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
  capabilities: { ebook_convert: EbookConvertCap }
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
  /** 逐字段明细（在线建议 / 是否已本地覆盖） */
  meta: MetaStateMap
}

/** `GET /api/books/{bid}/metadata/online` */
export interface MetadataOnlineResult {
  ok: boolean
  /** 在线候选字段值 */
  values: Partial<BookMetadataFields>
  source: string
  score: number
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
}

export interface ConfigPayload {
  config: AppConfig
  overrides: Record<string, unknown>
  /** 被 settings.json 覆盖的点号键（提示「改了 config.yaml 但不生效」的原因） */
  overridden: string[]
  config_file: string
  settings_file: string
  backup_dir: string
  capabilities: { ebook_convert: EbookConvertCap }
}

/** Calibre ebook-convert 能力探测 */
export interface EbookConvertCap {
  available: boolean
  path: string
  version: string
  env_var: string
  supported: string[]
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

/** 归属模式：就地引用来源子目录（不搬文件）/ 独立存储 */
export type LibraryMode = 'inplace' | 'import'
/** 库类型：决定功能显隐矩阵（见后端 core/features.py） */
export type LibraryType = 'ebook' | 'comic' | 'audiobook' | 'mixed'

/** 书库实体（`/api/libraries`，第 10 期起） */
export interface LibraryEntity {
  id: string
  name: string
  type: LibraryType
  type_label: string
  mode: LibraryMode
  mode_label: string
  /** **实际库根**（扫描 / 落盘 / 路径解析的唯一根） */
  root_path: string
  /** 来源子目录名（相对 `LIBRARY_SOURCE_DIR`；只存相对名，挂载点换了也不失效） */
  source_subdir: string
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
  book_count: number
  exists: boolean
  writable: boolean
  /** 默认书库（承接未归类的书）不可删除 */
  is_default: boolean
  last_scan_at: number
  last_scan_note: string
}

export interface LibrariesResult {
  items: LibraryEntity[]
  total: number
  /** `LIBRARY_SOURCE_DIR` —— 新建「就地引用」库时的父目录 */
  source_dir: string
  types: { value: LibraryType; label: string }[]
  modes: { value: LibraryMode; label: string }[]
}

/** 每库可覆写项中的一项（`/api/libraries/{id}/settings` 的 `schema`）。 */
export interface LibrarySettingItem {
  /** 全局配置的点分路径（如 `output.layout`）—— 覆写就以它为键 */
  key: string
  label: string
  /** `str` 是自由文本（命名规则 / 适用格式） */
  kind: 'bool' | 'enum' | 'number' | 'str' | 'policy_map'
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
 * - `skipped` 跳过（库未配成品目录、目录型有声书等「不是错误但没出版」）
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

/** 迁移预览里的一条（`/api/library-migrations/preview`） */
export interface MigrationItem {
  name: string
  book_id: string
  title: string
  format: string
  target_type: LibraryType
  target_label: string
  /** 当前所在库 */
  library_id: string
  library_name: string
  src: string
  dst_library_id: string
  dst_library_name: string
  dst: string
  /** ready=可迁移 / conflict=目标同名 / no_library=目标库未建 / ambiguous=需指定目标 */
  status: 'ready' | 'conflict' | 'no_library' | 'ambiguous'
  reason: string
  /** 冲突时的建议名（**只建议不自动改**：改名会换 book_id，进度会断链） */
  suggest: string
}

export interface MigrationGate {
  /** 用户已答过「暂不迁移」 */
  dismissed: boolean
  dismissed_at: number
  note: string
  /** 设置里勾了「以后自动执行」 */
  auto_migrate: boolean
}

/** 向导建议：为缺失的类型库给出的两套位置方案（逐库选：就地引用 / 独立存储） */
export interface LibrarySpecSuggestion {
  id: string
  type: LibraryType
  name: string
  source_subdir: string
  inplace: { mode: LibraryMode; root_path: string }
  import: { mode: LibraryMode; root_path: string }
}

export interface MigrationPreview {
  items: MigrationItem[]
  total: number
  ready: number
  conflict: number
  no_library: number
  ambiguous: number
  movable: number
  blocked: number
  missing_types: LibraryType[]
  missing_labels: string[]
  suggest_specs: LibrarySpecSuggestion[]
  gate: MigrationGate
  /** 有可迁移项、且未答过、且未开自动 → 前端应**阻塞式**确认一次 */
  needs_confirm: boolean
}

export interface MigrationPlanResult {
  batch_id: string
  created: number
  /** 同一批文件重复 plan 会复用同一批次（幂等） */
  reused: boolean
  items: MigrationItem[]
  message: string
}

export interface MigrationRow {
  id: number
  batch_id: string
  direction: string
  library_id: string
  src: string
  dst: string
  status: 'pending' | 'done' | 'failed' | 'rolled_back' | 'rollback_failed' | string
  error: string
  created_at: number
}

export interface MigrationRunResult {
  ok: boolean
  batch_id: string
  /** 执行时 */
  moved?: number
  /** 回滚时 */
  restored?: number
  failed: number
  skipped?: number
  errors: { src: string; dst: string; error: string }[]
  items: MigrationRow[]
}

export interface MigrationBatch {
  batch_id: string
  direction: string
  n: number
  at: number
  pending: number
  done: number
  failed: number
  rolled_back: number
}

function _authToken(): string {
  try {
    return localStorage.getItem('nf_token') || ''
  } catch {
    return ''
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const token = _authToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(path, { ...init, headers })
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
  bookDockRescan: (id: string) =>
    request<{ ok: boolean; item: BookDockItem }>(
      `/api/book-dock/${encodeURIComponent(id)}/rescan`,
      { method: 'POST' },
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
   */
  setBookMetadata: (bid: string, fields: BookMetadataWriteFields) =>
    request<MetadataWriteResult>(`/api/books/${encodeURIComponent(bid)}/metadata`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fields }),
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

  bookReview: (bid: string) =>
    request<BookReview>(`/api/books/${encodeURIComponent(bid)}/review`),

  /** stars 0 = 清除评分；review 空串 = 清除书评。两者一起保存但可独立留空 */
  setReview: (bid: string, payload: { stars: number; review: string }) =>
    request<BookReview>(`/api/books/${encodeURIComponent(bid)}/review`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 相似书：内容重合度派生（同作者 / 题材 / 同系列），得分为 0 的不返回 */
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

  /** 本设备记录。未登记时后端 404 → 这里抛错，调用方据此判断「新设备」 */
  prefDevice: (id: string) => request<PrefDevice>(`/api/prefs/devices/${encodeURIComponent(id)}`),

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

  downloadUrl: (name: string) => `/download/${encodeURIComponent(name)}`,

  // ---------- 工具页：实体管理 / 批量重命名 / 重复书籍 / 缺失资源 ----------
  // 改文件一律「先 preview、再 apply」；apply 只回传预览过的条目，不传规则。
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

  entityRenameApply: (type: EntityKind, to: string, items: RenameItem[]) =>
    request<ApplyResult>('/api/entities/rename/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, to, items }),
    }),

  entityMerge: (type: EntityKind, source: string, target: string, libraryId = '') =>
    request<RenamePlan>('/api/entities/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, source, target, library_id: libraryId }),
    }),

  /**
   * 按规则预览改名。scope / pattern 留空时用**该库的生效命名规则**
   * （每库覆写 ?? 全局，见 `/api/libraries/{id}/settings`）。
   */
  renamePreview: (scope: string, pattern: string, libraryId = '') =>
    request<RenamePlan>('/api/rename/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope, pattern, library_id: libraryId }),
    }),

  renameApply: (items: RenameItem[]) =>
    request<ApplyResult>('/api/rename/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
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

  /** 源连通性自检（真的外呼；被点的源才测） */
  metadataProbe: (sources?: string[]) =>
    request<{ items: Record<string, { ok: boolean; message: string; ms: number }> }>(
      '/api/metadata/probe',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources }),
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

  /** 提交掩码 = 不修改（与其它凭据同一约定） */
  saveIntegration: (service: string, payload: Record<string, string>) =>
    request<{ ok: boolean }>(`/api/integrations/${service}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 真实连通性验证。StoryGraph 无公开 API，会返回 `unsupported: true` */
  testIntegration: (service: string) =>
    request<IntegrationTestResult>(`/api/integrations/${service}/test`, { method: 'POST' }),

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
  books: () => request<{ items: BookCard[]; total: number }>('/api/books'),

  bookDetail: (id: string) =>
    request<BookDetail>(`/api/books/${encodeURIComponent(id)}`),

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

  // ---------- 阅读器：章节内容 / 进度 / 批注 ----------
  chapter: (id: string, index: number) =>
    request<ChapterContent>(
      `/api/books/${encodeURIComponent(id)}/chapter/${index}`,
    ),

  getProgress: (id: string) =>
    request<ProgressState>(`/api/books/${encodeURIComponent(id)}/progress`),

  setProgress: (id: string, locator: number, percent: number) =>
    request<{ ok: boolean }>(`/api/books/${encodeURIComponent(id)}/progress`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ locator, percent }),
    }),

  listAnnotations: (id: string) =>
    request<{ items: Annotation[] }>(
      `/api/books/${encodeURIComponent(id)}/annotations`,
    ),

  addAnnotation: (id: string, a: Omit<Annotation, 'id' | 'created_at'>) =>
    request<{ id: number; ok: boolean }>(
      `/api/books/${encodeURIComponent(id)}/annotations`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(a),
      },
    ),

  deleteAnnotation: (id: string, aid: number) =>
    request<{ ok: boolean }>(
      `/api/books/${encodeURIComponent(id)}/annotations/${aid}`,
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
  allAnnotations: () =>
    request<{ items: AllAnnotation[]; total: number }>('/api/annotations'),

  // ---------- 书库（第 10 期：库实体 / 分面 / 能力 / 迁移） ----------

  /** 书库实体列表（含书数 / 是否存在 / 可写）。 */
  libraries: () => request<LibrariesResult>('/api/libraries'),

  /** 格式分面（原 `/api/libraries` 语义，第 10 期改址到 `/api/library-facets`）。 */
  libraryFacets: () => request<{ items: LibraryFacet[] }>('/api/library-facets'),

  /** `LIBRARY_SOURCE_DIR` 下的候选来源子目录（新建向导给默认值用）。 */
  librarySourceDirs: () =>
    request<{ root: string; exists: boolean; dirs: { name: string; path: string; entries: number }[] }>(
      '/api/libraries/source-dirs',
    ),

  /** 新建书库（**只登记，不搬文件**）。 */
  createLibrary: (payload: {
    name: string
    type: LibraryType
    mode: LibraryMode
    root_path: string
    source_subdir?: string
    rules?: unknown
    sort_order?: number
    /** 刮削出版成品目录（可选；空 = 该库不产出硬链接副本） */
    publish_path?: string
    /** 逐库扫描调度 */
    watch?: number
    scan_interval?: number
    scan_cron?: string
  }) =>
    request<{ ok: boolean; library: LibraryEntity }>('/api/libraries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 改库属性（改 `root_path` 只改登记，不搬文件）。 */
  updateLibrary: (
    id: string,
    payload: Partial<{
      name: string
      type: LibraryType
      mode: LibraryMode
      root_path: string
      source_subdir: string
      rules: unknown
      sort_order: number
      /** 传空串 = 关闭该库的副本产出（不动已有副本） */
      publish_path: string
      watch: number
      scan_interval: number
      scan_cron: string
    }>,
  ) =>
    request<{ ok: boolean; library: LibraryEntity }>(`/api/libraries/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 移除库**登记**（绝不删文件）。库非空时默认拒绝，`force` 才会只移除登记。 */
  deleteLibrary: (id: string, force = false) =>
    request<{ ok: boolean; removed: string; books_left_on_disk: number }>(
      `/api/libraries/${encodeURIComponent(id)}${force ? '?force=true' : ''}`,
      { method: 'DELETE' },
    ),

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

  /** 待迁移概览。`targets` 用于「同类库有多个」时指定目标。 */
  migrationPreview: (targets?: Record<string, string>) => {
    const q =
      targets && Object.keys(targets).length
        ? `?targets=${encodeURIComponent(JSON.stringify(targets))}`
        : ''
    return request<MigrationPreview>(`/api/library-migrations/preview${q}`)
  },

  /** 生成/复用迁移批次（只写台账，不搬文件）。 */
  migrationPlan: (targets?: Record<string, string>) =>
    request<MigrationPlanResult>('/api/library-migrations/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ targets }),
    }),

  /** 执行迁移批次（**真移文件**）。 */
  migrationApply: (batchId: string) =>
    request<MigrationRunResult>('/api/library-migrations/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_id: batchId }),
    }),

  /** 一键回滚（`batchId` 留空 = 最近一次迁移批次）。 */
  migrationRollback: (batchId = '') =>
    request<MigrationRunResult>('/api/library-migrations/rollback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_id: batchId }),
    }),

  migrationBatches: () =>
    request<{ items: MigrationBatch[]; gate: MigrationGate }>('/api/library-migrations/batches'),

  /** 「暂不迁移」：之后不再每次启动阻塞提示。 */
  migrationDismiss: (note = '') =>
    request<{ ok: boolean; gate: MigrationGate }>('/api/library-migrations/dismiss', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note }),
    }),

  /** 让启动提示重新出现。 */
  migrationResetGate: () =>
    request<{ ok: boolean; gate: MigrationGate }>('/api/library-migrations/reset-gate', {
      method: 'POST',
    }),

  // ---------- 阅读时长（会话上报） ----------
  recordSession: (bookId: string, seconds: number) =>
    request<{ ok: boolean }>(
      `/api/books/${encodeURIComponent(bookId)}/session`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seconds }),
      },
    ),

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

  /** 清空回收站 —— **真删，不可恢复** */
  clearRecycle: () =>
    request<{ ok: boolean; removed: number; freed: number }>('/api/maintenance/recycle/clear', {
      method: 'POST',
    }),

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
  stats: (days = 28) => request<StatsOverview>(`/api/stats?days=${days}`),
}
