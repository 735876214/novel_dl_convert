/**
 * 服务端配置字段定义（config.yaml → settings.json 覆盖层）。
 *
 * 从原 SettingsView.vue 原样抽出，仅做位置搬迁，字段与文案未改动。
 * `path` 是 config.yaml 里的点号路径；分区保存时按 SECTION_KEYS 收集顶层键成 patch。
 */

export type FieldType = 'bool' | 'number' | 'text' | 'password' | 'select'

export interface FieldDef {
  path: string
  label: string
  type: FieldType
  hint?: string
  placeholder?: string
  options?: { value: string; label: string }[]
}

/** 转换（本项目扩展） */
export const CONVERSION_FIELDS: FieldDef[] = [
  {
    path: 'chapter_detection.mode',
    label: '分章模式',
    type: 'select',
    hint: 'hybrid = 正则优先、疑难再调 AI；regex 纯正则；ai 纯 AI',
    options: [
      { value: 'hybrid', label: 'hybrid（推荐）' },
      { value: 'regex', label: 'regex' },
      { value: 'ai', label: 'ai' },
    ],
  },
  {
    path: 'chapter_detection.context_lines',
    label: 'AI 上下文行数',
    type: 'number',
    hint: 'AI 核验候选时前后取的上下文行数',
  },
  {
    path: 'chapter_detection.fallback',
    label: 'AI 失败降级',
    type: 'select',
    hint: 'AI 调用失败时回退到正则',
    options: [{ value: 'regex', label: 'regex' }],
  },
  { path: 'traditionalize', label: '繁体转简体', type: 'bool', hint: '转换时用 opencc 繁转简' },
  { path: 'llm.api_key', label: 'LLM API Key', type: 'password', hint: '已配置时留空即可，不会覆盖原值' },
  { path: 'llm.base_url', label: 'LLM 接口地址', type: 'text', placeholder: 'https://api.openai.com/v1' },
  { path: 'llm.model', label: 'LLM 模型', type: 'text', placeholder: 'gpt-4o-mini' },
]

/** 监听（本项目扩展） */
export const WATCHER_FIELDS: FieldDef[] = [
  { path: 'watcher.enabled', label: '目录监听', type: 'bool', hint: '服务启动时自动监听输入目录' },
  { path: 'watcher.interval', label: '轮询间隔（秒）', type: 'number', hint: 'NAS 网络挂载建议 ≥3' },
  { path: 'watcher.recursive', label: '递归子目录', type: 'bool' },
  { path: 'watcher.settle_seconds', label: '写入稳定等待（秒）', type: 'number' },
  { path: 'watcher.stable_rounds', label: '稳定判定轮数', type: 'number', hint: '连续 N 次大小不变才认为写入完成' },
  { path: 'watcher.copy_non_txt', label: '非 txt 原样导出', type: 'bool' },
  { path: 'watcher.process_existing', label: '启动时处理存量文件', type: 'bool' },
  { path: 'watcher.max_retries', label: '单文件失败重试上限', type: 'number' },
]

/** 网络与下载（本项目扩展） */
export const NETWORK_FIELDS: FieldDef[] = [
  { path: 'network.max_retries', label: '传输重试次数', type: 'number', hint: '下载时超时 / 传输错误的重试上限' },
  { path: 'download.enabled', label: '开放搜索 / 下载', type: 'bool', hint: '关闭时书源仅做规则管理，不可搜索下载' },
  { path: 'download.public_only', label: '仅放行公版源', type: 'bool' },
  { path: 'logging.max_entries', label: '日志内存缓冲条数', type: 'number' },
  { path: 'logging.dir', label: '日志目录', type: 'text', placeholder: '留空则用 LOG_DIR' },
]

/** 维护 → 上传上限（对应上游 Maintenance 页的 UPLOADS 分组） */
export const UPLOAD_FIELDS: FieldDef[] = [
  {
    path: 'upload.max_bytes',
    label: '单本书上传上限（字节）',
    type: 'number',
    hint: 'POST /convert 的请求体上限。此前后端完全没有限制，超大文件可直接打满容器内存',
  },
  {
    path: 'upload.max_source_rules_bytes',
    label: '书源文件上传上限（字节）',
    type: 'number',
    hint: 'POST /api/sources/upload 的上限，通常远小于整本书',
  },
]

/** 个人资料 → 成就开关（对应上游 Profile 页的 Enable achievements） */
export const ACHIEVEMENTS_FIELDS: FieldDef[] = [
  {
    path: 'achievements.enabled',
    label: '启用成就',
    type: 'bool',
    hint: '关闭后不判定、不解锁，侧栏也不再显示成就入口',
  },
]

/**
 * 偏好与同步 → 阅读进度口径（第 40 期，对应上游的 Progress Thresholds）。
 *
 * 这是全站「在读 / 已读完」判定的**全局默认值** —— 统计、书架、成就、Komga 客户端
 * 四处同源（都读 `core/lib_settings.reading_thresholds`），所以改这里会**同时**改变
 * 四处的结果，不是只影响某一页。每个书库还能单独覆写（书库管理 → 每库设置 → 阅读）。
 *
 * ⚠️ 值域是 **0–100**（百分比），不是 `confidence` 那类 0–1 的小数。
 */
export const READING_FIELDS: FieldDef[] = [
  {
    path: 'reading.started_threshold',
    label: '在读下界（%）',
    type: 'number',
    hint: '进度高于该值即算「在读」。默认 0 = 有一点进度就算在读',
  },
  {
    path: 'reading.finished_threshold',
    label: '已读完阈值（%）',
    type: 'number',
    hint: '进度达到该值即算「已读完」。默认 99.5（本项目既有口径，不是上游的 99）',
  },
]

/** 保存某个分区时提交的顶层配置键 */
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
  network: ['network', 'download', 'logging'],
  naming: ['naming'],
  upload: ['upload'],
  achievements: ['achievements'],
  opds: ['opds'],
  // Komga 页有两块：输出布局（output.layout）+ 兼容服务端（komga.*）
  komga: ['output', 'komga'],
  // 元数据抓取的 7 个页面共用同一配置段（同一份 cfg 草稿，各页只改自己的子键）
  metadata: ['metadata_fetch'],
  // 多书库：跨库策略开关（库实体存 SQLite，见「工具 → 书库管理」）
  libraries: ['libraries'],
  // 阅读进度口径的全局默认值（页面在「偏好与同步」；每库覆写在书库管理里）
  reading: ['reading'],
}

/** 命名规则的格式筛选取值（与后端 naming.scope 的取值一致：all 或某个扩展名） */
export const RENAME_SCOPES: { value: string; label: string }[] = [
  { value: 'all', label: '全部格式' },
  { value: 'epub', label: '仅 EPUB' },
  { value: 'mobi', label: '仅 MOBI' },
  { value: 'azw3', label: '仅 AZW3' },
  { value: 'pdf', label: '仅 PDF' },
  { value: 'txt', label: '仅 TXT' },
]

/**
 * 后端 `core/fileops.py` 实际支持的 9 个占位符（`PATTERN_FIELDS`，顺序与之一致）。
 * 这是**本项目实现**，不是上游的 token 表 —— 上游有 13 个 token + 7 个修饰符。
 * 只登记书目里**真实存在**的字段：加不出真实值的一律不加。
 */
export const RENAME_TOKENS: { token: string; desc: string }[] = [
  { token: '{title}', desc: '书名；为空时回退原始文件名' },
  { token: '{author}', desc: '作者；为空时回退「未知」' },
  { token: '{series}', desc: '系列名；为空时回退「无系列」' },
  { token: '{series_index}', desc: '系列内序号（书目原值；读不到为空串）' },
  { token: '{index}', desc: '系列卷号（两位补零；无系列卷号时回落 01）' },
  { token: '{year}', desc: '出版年（读不到为空串）' },
  { token: '{publisher}', desc: '出版社（读不到为空串）' },
  { token: '{language}', desc: '语言（读不到为空串）' },
  { token: '{ext}', desc: '扩展名（去点）' },
]

/** 命名配方：一键填入常用模式（对齐上游的 recipes，但只使用本项目支持的占位符） */
export const RENAME_RECIPES: { name: string; pattern: string; desc: string }[] = [
  { name: '作者 - 书名', pattern: '{author} - {title}', desc: '默认；扁平结构，便于按作者浏览' },
  { name: '卷号. 书名', pattern: '{index}. {title}', desc: '按系列卷号编号，适合成系列的成品' },
  { name: '系列 - 卷号 - 书名', pattern: '{series} - {index} - {title}', desc: '系列优先，同类聚在一起' },
  { name: '书名（作者）', pattern: '{title}（{author}）', desc: '书名在前，适合书名优先的检索习惯' },
]
