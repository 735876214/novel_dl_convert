import type { IconName } from '@/lib/icons'

/**
 * 设置页分区注册表 —— 上游（BookOrbit）设置页信息架构的单一数据源。
 *
 * 对齐依据：`docs/bookorbit-settings-inventory.md`（线上实例逐页采集）。
 * 结构整体与上游一致：6 个分组 / 36 个叶子页，路由为 `/settings/<path>`。
 * 上游 41 页里 **30 页有落点**，另 11 页经**第 49 期裁决已移除**（Icons / Language /
 * Privacy & Sharing / Restrictions / Kobo / Email / Users / Account Activity /
 * Magic Links / OIDC·SSO / Requests）—— 均为单用户本地库下**永无对象**或**已决策不做**
 * 的页；逐页理由与上游结构对照保留在 `docs/bookorbit-settings-inventory.md`。
 * 本项目补充 6 页（`ext` 组 5 页 + `komga`，标 `own`）。
 *
 * 命名约定（迁移要点 2：不自创中文名）：
 *   - `label` = 上游英文原名，**作为对齐基准，不翻译**
 *   - `zh`    = 中文侧栏显示名（界面语言为中文，仅供展示）
 *
 * 状态约定（迁移要点 3：占位项统一呈现）：
 *   - `ready`       已有真实实现
 *   - `placeholder` 本项目无该后端能力，页面只读展示上游结构并标注「未支持」
 *     （第 49 期后占位页**清零**，机制保留，供将来新增未支持页时复用）
 */

export interface UpstreamPage {
  /** 上游页面的 <h2> */
  title: string
  /** 上游页头说明原文（保留英文，不翻译） */
  desc?: string
  /** 页内分组标题（大写） */
  groups?: string[]
  /** 主要设置项（中文转述，便于中文界面下阅读） */
  items?: string[]
  /** 采集缺口说明 */
  uncaptured?: string
}

export interface SettingsPageDef {
  /** 相对 /settings 的子路径 */
  path: string
  /** 路由 name */
  name: string
  /** 上游英文原名（对齐基准） */
  label: string
  /** 中文侧栏显示名 */
  zh: string
  icon?: IconName
  status: 'ready' | 'placeholder'
  /** 占位页展示的上游结构 */
  upstream?: UpstreamPage
  /** 本项目已有等价能力时的跳转入口 */
  link?: { to: string; label: string }
  /** 本项目落地说明（占位页顶部展示） */
  note?: string
  /**
   * 本项目补充项：**上游没有这一页**（如 komga / koreader-upstream）。
   * 界面需明确标注，避免后续与上游逐页对读时误以为「上游也有」。
   */
  own?: boolean
}

export interface SettingsGroupDef {
  id: string
  /** 上游分组名（大写） */
  label: string
  zh: string
  icon: IconName
  /** 本项目扩展组：上游没有对应分区，需与上游分区明确隔离 */
  own?: boolean
  pages: SettingsPageDef[]
}

const p = (
  path: string,
  label: string,
  zh: string,
  status: SettingsPageDef['status'],
  extra: Partial<SettingsPageDef> = {},
): SettingsPageDef => ({
  path,
  name: 'settings-' + path.replace(/\//g, '-'),
  label,
  zh,
  status,
  ...extra,
})

export const SETTINGS_GROUPS: SettingsGroupDef[] = [
  {
    id: 'you',
    label: 'YOU',
    zh: '你',
    icon: 'user',
    pages: [
      p('account/profile', 'Profile', '个人资料', 'ready', {
        upstream: {
          title: 'Profile',
          desc: 'Your name, email, password, and active sessions.',
          groups: ['PREFERENCES', 'SECURITY & ACCESS', 'Connected Accounts'],
          items: ['头像上传 / 移除', 'Full name', 'Username（不可改）', 'Email（只读）', 'Timezone', 'Enable achievements', 'Guided Tour 重放', 'Change password', 'Connected Accounts（OIDC）'],
        },
        note: '本项目为单用户轻登录：已实现账号展示、修改密码、头像上传/移除、显示名、时区（接通时间类成就）、成就开关与新手引导重放；OIDC / Email 在单用户场景无意义，故不提供。',
      }),
      p('appearance/theme', 'Theme', '主题', 'ready', {
        upstream: {
          title: 'Theme',
          desc: 'Theme, accent colour, background, and corner radius.',
          groups: ['WHERE TO SAVE APPEARANCE PREFERENCES', 'THEME', 'LIBRARY BACKGROUND'],
          items: ['保存位置（本机 / 账号）', 'Color scheme（Light / Dark / System）', 'Accent color（64 档）', 'Corner radius（Sharp / Default / Rounded / Pill）', 'Background pattern（20 个图案）'],
          uncaptured: '点缀色与背景图案的「当前值」在上游存在信号分歧，未能确证。',
        },
        note: '本项目实现主题 / 点缀色（65 档）/ 圆角；「保存位置」已由「偏好与同步」页统管（外观与阅读偏好整套同步，也可按设备各用各的）；「背景图案」为未支持。',
      }),
      p('appearance/book-covers', 'Book Covers', '封面样式', 'ready', {
        note: '已实现：真实内嵌封面 + 填充方式（填满 / 自然贴底 / 模糊底图）+ 书脊（含第 20 期的「漫画是否显示书脊」开关）+ 阴影强度 + 5 种卡片叠加层 + 详情页封面取色（第 20 期），存本机、改完立即生效。未支持：封面搜索提供者（依赖在线封面抓取）。',
        upstream: {
          title: 'Book Covers',
          desc: 'Cover shadows, spine effects, and placeholder art.',
          groups: ['BOOK COVERS'],
          items: ['Default cover search provider（DuckDuckGo / iTunes / All Sources）', 'Cover display mode（Blurred fit / Fill card / Natural bottom）', 'Book spine overlay（Off / Subtle / Strong）', 'Show spine on comics', 'Book details cover tint（Off / One / Two colours）', 'Cover shadow strength', 'Card overlays（进度条 / 格式 / 评分 / 阅读状态 / 系列号 / 锁定）'],
        },
      }),
      p('appearance/layout', 'Layout', '布局', 'ready', {
        upstream: {
          title: 'Layout',
          desc: 'Default library view, density, and spacing.',
          groups: ['LIBRARY GRID LAYOUT', 'SERIES DISPLAY', 'AUTHOR GRID', 'LIST AND TABLE VIEWS'],
          items: ['Cover size behavior（全部同步 / 各视图独立）', 'Portrait cover size（130px）', 'Square cover size（150px）', 'Portrait grid spacing（28px）', 'Square grid spacing（28px）', 'Card info mode（On hover / Below cover / Off）', 'Collapsed series cover（Stack / Mosaic / First / Latest / First Unread）', 'Author cover size（120px）/ shape（Circle / Square）', 'Zebra striping'],
        },
        note: '已实现封面尺寸 / 网格间距 / 卡片信息位置 / 作者封面尺寸与形状 / 表格隔行底色五项，均真作用于书架与作者页。上游的「尺寸同步方式」「方形封面尺寸」「方形网格间距」在本项目没有对应实体（只有一套网格、只有竖版封面），卡片主次标签与折叠系列封面形态暂缓 —— 四条均在页尾对照卡列明，不造假控件。这几项属外观，随账号同步（并入 appearance 块，未新增第七块）。',
      }),
      p('appearance/behavior', 'Behavior', '浏览行为', 'ready', {
        upstream: {
          title: 'Behavior',
          desc: 'How the library reacts as you browse and sort.',
          groups: ['LIBRARY BEHAVIOR'],
          items: ['Thumbnail clicks（Read first / Open details）', 'Show filter preview by default', 'Collapse series by default'],
        },
        note: '已实现上游该页全部三项（缩略图点击 / 筛选预览默认展开 / 系列默认折叠）—— 故无「未支持」对照卡。三项存本机，与书架视图偏好同一份，不随账号同步。',
      }),
      p('reader/ebook', 'eBook', '电子书', 'ready', {
        upstream: {
          title: 'eBook',
          desc: 'Fonts, spacing, and page behaviour for eBooks.',
          groups: ['NEW BOOKS', 'LAYOUT', 'THEME', 'TYPOGRAPHY', 'ADVANCED'],
          items: ['Apply my settings to new books', 'Reading flow（Paginated / Scrolled）', 'Fixed-layout page spreads', 'Columns', 'Dark mode（13 档变体）', 'Font', 'Font style', 'Font size', 'Line height', 'Paragraph spacing', 'Justify text', 'Hyphenation', 'Letter / Word spacing', 'First-line indent', 'Max content width', 'Column gap'],
        },
        note: '本项目实现「阅读模式 / 13 档主题 / 字体 / 字重样式 / 字号 / 行高 / 内容宽度 / 文本区左右内边距 / 段落间距 / 首行缩进 / 字距 / 词距 / 分栏 / 两端对齐 / 断词」共 15 项；未支持：新书套用设置（Apply my settings to new books，本项目排版是全局单一来源、新书一律套用，该开关要解决的问题天然不存在）、固定版式页宽三档（Fixed-layout page spreads：固定版式已能识别并对这类书停用重排设置，但不提供页宽档位）。',
      }),
      p('reader/pdf', 'PDF', 'PDF', 'ready', {
        upstream: {
          title: 'PDF',
          desc: 'Rendering, zoom, and page fit for PDFs.',
          groups: ['LAYOUT', 'ZOOM'],
          items: ['Scroll mode（Page / Scrolled / Horizontal）', 'Page spread（None / Odd / Even / Auto）', 'Default fit（Fit Page / Fit Width / Automatic / Custom）'],
        },
        note: '已实现：滚动模式（翻页 / 纵向 / 横向）、页展（单页 / 双页奇右 / 偶右 / 自动）、适配方式、自定义缩放、阅读进度。渲染用 pdf.js，懒加载（打开 PDF 才下载）。',
      }),
      p('reader/comics', 'Comics', '漫画', 'ready', {
        upstream: {
          title: 'Comics',
          desc: 'Reading direction and page spreads for comics.',
          groups: ['VIEW', 'DISPLAY'],
          items: ['Reading mode（Paginated / Infinite spaced / Infinite no gaps）', 'Page view（Single / Two-page）', 'Fit mode（Page / Width / Height / Actual）', 'Reading direction（L to R / R to L）', 'Spread alignment', 'Spread gap', 'Wide-page handling', 'Force two-page on small screens', 'Auto-advance to next book', 'Background color'],
        },
        note: '已实现：阅读模式（翻页 / 纵向连续）、页视图（单页 / 双页）、适配方式、阅读方向（含日漫右→左）、页间距、背景色、阅读进度。支持 CBZ 与 CBR：CBR 由服务端的 zip/rar 双后端解压（bsdtar，容器内由 libarchive-tools 提供），两种格式在阅读器里体验完全一致。',
      }),
      p('reader/audio', 'Audiobook', '有声书', 'ready', {
        upstream: {
          title: 'Audiobook',
          desc: 'Playback speed, skip intervals, and sleep timer.',
          groups: ['PLAYBACK', 'SKIP CONTROLS'],
          items: ['Default playback speed（0.75x–2x）', 'Default volume', 'Skip back duration（5/10/15/30s）', 'Skip forward duration（10/15/30/60s）'],
        },
        note: '已实现：默认倍速（0.75x–2x）、默认音量、快退间隔（5/10/15/30 秒）、快进间隔（10/15/30/60 秒）、睡眠定时默认时长。播放器另提供轨道列表与按秒进度保存（跨设备同步）；有声书支持「一个目录 = 一本书」（一章一文件）与单个音频文件两种形态。',
      }),
      p('reader/fonts', 'Fonts', '阅读字体', 'ready', {
        upstream: {
          title: 'Fonts',
          desc: 'Fonts available while reading.',
          groups: ['UPLOAD FONTS', 'YOUR FONTS'],
          items: ['上传字体（TTF / OTF / WOFF / WOFF2，单个 ≤50MB）', '字体列表（上限 50）'],
        },
        note: '已实现：字体上传 / 列表 / 删除 / 在阅读器中选用。族名从字体 name 表解析（TTF/OTF），解析不出时回落文件名并以文件名显示。本项目单用户，上限取服务端口径（200）。',
      }),
      p('reader/general', 'General', '偏好与同步', 'ready', {
        upstream: {
          title: 'General',
          desc: 'Defaults shared by every reading mode.',
          groups: ['WHERE TO SAVE READER PREFERENCES'],
          items: ['阅读偏好保存位置（This device only / My account）'],
        },
        note: '本项目把它扩展为「偏好与同步」：偏好可存成具名模式（整套快照，含外观），供不同设备套用；每台设备也可各用各的。应用模式 = 拷贝内容，因此别人改模式本体不会让你被动变化。已知限制：无实时推送 —— 其它设备的改动需本机下次打开或点「立即同步」才可见。',
      }),
      p('account/notifications', 'Notifications', '通知', 'ready', {
        note: '已实现：按活动类别设「关闭 / 仅失败 / 全部」。差异——上游是服务端投递（可走邮件），本项目无投递渠道，开关为客户端过滤，生效范围是通知中心与日志。',
        upstream: {
          title: 'Notifications',
          desc: 'What BookOrbit tells you about, and where.',
          groups: ['LIBRARY', 'FILES', 'INTEGRATIONS', 'PERSONAL', 'APP UPDATES'],
          items: ['Library scanning', 'Metadata fetching', 'Author enrichment', 'File write-back', 'File rename', 'Bulk rename', 'Data migration', 'Book Dock', 'Book requests', 'Email delivery', '（以上每条为 Off / Problems / All 三档）', 'Achievements（Off / All）', "Show \"What's New\" after updates"],
        },
      }),
    ],
  },
  {
    id: 'library',
    label: 'LIBRARY',
    zh: '书库',
    icon: 'library',
    pages: [
      p('libraries', 'Libraries', '书库管理', 'ready', {
        upstream: {
          title: 'Libraries',
          desc: 'Scan paths, watched folders, and ingest rules.',
          groups: ['LIBRARY', 'CONTENTS', 'AUTOMATION', 'LAST SCAN'],
          items: ['书库列表（组织模式 / 文件夹 / 书数 / 占用 / 格式分布）', 'Watch folders', 'Scheduled scan', 'Write to file', 'Rename files', '最后扫描状态与原因', 'Scan All', 'Add Library', '排序（默认 / 名称 / 书数 / 占用 / 最后扫描）'],
        },
        note: '本页即操作页（第 49 期起，原「工具 → 书库管理」入口已并入此处，工具页不再单列）。已实现（第 10 期）：多书库实体（类型：电子书 / 漫画 / 有声书 / 混合；存放方式：就地引用，一个库可引用多个来源文件夹）、来源文件夹投递、按格式迁移（逐条预览 + 台账幂等 + 一键回滚 + 同名冲突拒绝并建议改名）、按子目录名 / 格式 / 关键词自动归库、以及「库类型 → 功能显隐」。已实现（第 13 期）：每库独立覆盖投递布局 / 产物格式、递归与复制非 txt、元数据抓取策略与字段、命名规则（未覆写则继承全局）；以及入库时的跨库同名拦截与一键改名。',
      }),
      p('metadata/providers', 'Providers', '元数据来源', 'ready', {
        upstream: {
          title: 'Providers',
          desc: 'Enable external metadata sources and configure their credentials.',
          groups: ['GENERAL BOOK CATALOGUES', 'AUDIOBOOKS', 'COMICS & LIGHT NOVELS', 'REGIONAL CATALOGUES', 'ADVANCED FETCH BEHAVIOR'],
          items: ['14 个元数据源（当前 10 个启用）', '逐字段的提供者优先级链（书名 / 评分 / 系列名 / 系列序号 / 题材 / 旁白 / 时长 / 是否删节）', '每字段合并策略（Fill gaps / Merge / If provided / Always）', 'Combine genres from all selected providers', 'Maximum genres per book', 'Store provider IDs on books', 'Use existing provider IDs only'],
        },
      }),
      p('metadata/field-rules', 'Field Rules', '字段规则', 'ready', {
        upstream: {
          title: 'Field-Level Rules',
          desc: '逐字段的元数据写入规则矩阵。',
          items: ['每字段覆写策略（Overwrite if provided / Merge with existing 等）', '共 204 个控件，是设置页中体量最大的一页'],
        },
      }),
      p('metadata/custom-fields', 'Custom Fields', '自定义字段', 'ready', {
        upstream: {
          title: 'Custom Fields',
          desc: 'Define custom metadata fields and choose which libraries use them.',
          groups: ['NEW FIELD', 'FIELDS'],
          items: ['自定义字段定义表单', '字段列表（拖拽排序 / 改标签 / 切换适用书库 / 归档）'],
        },
      }),
      p('metadata/score', 'Confidence Score', '元数据完整度', 'ready', {
        upstream: {
          title: 'Confidence Score',
          desc: 'How each metadata field counts towards the completeness score shown on every book.',
          groups: ['WHERE A SCORE COMES FROM', 'COUNT TOWARDS THE SCORE', 'NOT SCORED', 'WHERE YOUR BOOKS LAND'],
          items: ['24 个计分字段与权重份额（Title / Authors / Cover 各 12.8% 等）', '5 个权重分组（Core / Publishing / Classification / Provider IDs / Enrichment）', '不参与计分的 3 个字段（Subtitle / Series name / Series index）', '书库分布直方图（<50 / 50-69 / 70-89 / 90+）', 'Recalculate all', 'Reset to defaults'],
        },
      }),
      p('metadata/auto-fetch', 'Books', '书籍自动抓取', 'ready', {
        upstream: {
          title: 'Books',
          desc: 'Automatically fetch covers, descriptions, and other details when new books are added to your library.',
          groups: ['GLOBAL SETTINGS', 'AUTOMATION'],
          items: ['Enable auto-fetch', 'Trigger on import', 'Eligibility conditions（任一命中即合格）'],
        },
      }),
      p('metadata/authors', 'Authors', '作者自动抓取', 'ready', {
        upstream: {
          title: 'Author Auto-Fetch',
          desc: '作者传记与照片的自动抓取配置。',
          items: ['作者元数据抓取开关与策略'],
          uncaptured: '该页正文已完整采集，但未渲染出可判定的分段控件选中态，条目未能逐项结构化。',
        },
      }),
      p('metadata/genre-blocklist', 'Genre Blocklist', '题材黑名单', 'ready', {
        upstream: {
          title: 'Genre Blocklist',
          desc: '题材黑名单的维护。',
          items: ['新增黑名单值', '按关键词过滤黑名单'],
        },
      }),
      p('library/file-naming', 'File Naming', '文件命名', 'ready', {
        upstream: {
          title: 'File Naming',
          desc: '按书库或全局模式生成文件路径与文件名。',
          items: ['每书库命名模式（Folder as Book / File as Book）', 'File as Book 默认模式', '13 个 TOKENS', '7 个 MODIFIERS', '4 类 STRUCTURE（optional / fallback / folder / or）', '4 个配方', '元数据缺失时的降级预览', 'Cross-platform path sanitization'],
        },
        link: { to: '/tools/logs?tab=scrape', label: '刮削面板 → 命名规则' },
        note: '已实现：命名规则存服务端（config.naming，每库可覆写）+ 4 个配方 + 生效预览，支持 9 个占位符（书名 / 作者 / 系列 / 系列序号 / 卷号 / 出版年 / 出版社 / 语言 / 扩展名）。第 28 期起规则只作用于「副本名」（改名不再动源文件，批量重命名工具已并入刮削面板的「命名规则」区块，可预览并一键重出版）。上游的 13 token / 7 修饰符 / 结构语法未支持。',
      }),
      p('library/maintenance', 'Maintenance', '维护', 'ready', {
        upstream: {
          title: 'Maintenance',
          desc: 'Rescans, duplicates, orphans, and cache rebuilds.',
          groups: ['UPLOADS', 'IMPORT', 'RECOMMENDATIONS', 'ACHIEVEMENTS', 'UPDATES'],
          items: ['Maximum upload file size limit', 'Import library data（从其它书库工具一次性导入）', 'Refresh recommendation index', 'Backfill achievements', 'Check for updates（查 GitHub 新版本）'],
        },
        link: { to: '/tools/duplicates', label: '重复书籍清理' },
        note: '已实现：UPLOADS 上传上限（可配置且生效）、ACHIEVEMENTS 的成就重算（Backfill）、书库索引重建、缓存清理、回收站清空与各目录占用统计。IMPORT（从其它书库工具一次性导入）/ RECOMMENDATIONS（刷新推荐索引）/ UPDATES（查 GitHub 新版本）在容器部署口径下未实现，页内以只读条目列出。',
      }),
    ],
  },
  {
    id: 'devices',
    label: 'DEVICES',
    zh: '设备',
    icon: 'layers',
    pages: [
      p('opds', 'OPDS', 'OPDS', 'ready', {
        upstream: {
          title: 'OPDS',
          desc: 'Catalog feeds for third-party reading apps.',
          groups: ['SERVER', 'ENDPOINT', 'OPDS ACCOUNTS', 'OPDS NOTES'],
          items: ['OPDS Catalog Server 开关', '端点地址（可复制）', 'OPDS 账号管理', '排序（Recently Added / Title / Author / Series 各升降序）'],
        },
        note: '已实现：目录开关、端点地址（可复制）、全部/最近/按作者/按系列/按标签/搜索/单书详情/封面/下载、分页（?page=）与排序（?sort=recent|title|author|series&order=）。第 14 期起支持按书库分别暴露：可见库多于一个时根 feed 多一个「按书库」入口，每个书库有独立地址 /opds/lib/<库 id>，可在「工具 → 书库管理 → 每库设置」逐库关掉（默认全部暴露，关掉后直连返回 404）。鉴权用 HTTP Basic + 应用账号（OPDS 客户端只会发 Basic，所以 /opds 不走 /api 的 Bearer 中间件）。未支持：独立 OPDS 账号体系。',
      }),
      p('koreader', 'KOReader', 'KOReader 进度互通', 'ready', {
        upstream: {
          title: 'KOReader',
          desc: 'Progress sync and document matching.',
          groups: ['KOREADER STATUS', 'SETUP', 'DEVICES', 'PLUGIN ACTIVITY', 'UNMATCHED KOREADER BOOKS', 'MANUAL KOREADER LINKS', 'SETUP GUIDE', 'DANGER ZONE'],
          items: ['Progress sync 开关', '同步账号与凭据', 'KOReader sync URL', '预置 BookOrbit 插件下载', '设备管理（退役 / 删除数据）', '未匹配书目与手动链接', '删除同步凭据'],
        },
        note: '本项目实现 kosync 协议的服务端：healthcheck / users/auth / users/create / syncs/progress（GET+PUT）。三个必须精确的协议细节：①鉴权头是 x-auth-user / x-auth-key，key = 密码的 MD5（不是 Basic，服务端也只存这个哈希）；②文档标识是 partialMD5（只采样 12 个点，偏移 1024×4^i，i=-1..10，不读第 0 字节、读不满即停），另有 checksum_method=FILENAME 的 md5(basename) 变体，两种都索引；③percentage 是 0–1，progress 对 EPUB 是 XPointer、PDF/漫画是页码。进度映射：DocFragment[N] ↔ 本项目章节序号（N-1），PDF/漫画用页码；反向的 XPointer 只定位到章首，准确位置由 percentage 兜底。未支持：多设备管理、注解/书签同步。',
      }),
      p('komga', 'Komga', 'Komga 库布局', 'ready', {
        own: true,
        note: '本项目实现「输出侧」：输出布局开关（output.layout —— 有系列的书落 系列名/系列名 #N.ext，无系列保持平铺）+ 既有库整理（先预览、再应用）。会改 basename 的条目在应用时自动迁移阅读进度 / 批注 / 评分 / 收藏（按 book_id 搬迁），整理库不会把进度清零。系列来源：EPUB 的 calibre:series 优先，判不出则从文件名推断（系列 第01卷 / 系列 #1 / 系列 (01) / 系列 - 01），都判不出就原地不动。第 15 期起兼容服务端补齐：客户端可按书库浏览（系列与书籍都按库过滤，老客户端的 GET 端点同样生效）、系列级「全部已读 / 全部未读」（只把百分比顶到 100，不清除读者位置）、CBR 拿到正确的媒体类型；有声书库不进 Komga（Komga 没有音频模型，硬塞进去只会得到打不开的坏条目）。第 22 期起还能逐库决定是否暴露：在「工具 → 书库管理 → 每库设置」关掉某库的「对 Komga 暴露」，它就不进客户端书库列表，直连它的系列 / 书籍地址也一并 404（默认全部暴露，与加这个开关之前一致）。未支持「接入侧」：从 Komga 拉书目 / 下载入库、双向同步进度。',
      }),
    ],
  },
  {
    id: 'accounts',
    label: 'ACCOUNTS',
    zh: '外部账号',
    icon: 'star',
    pages: [
      p('hardcover', 'Hardcover', 'Hardcover', 'ready', {
        upstream: {
          title: 'Hardcover',
          desc: 'Sync reading status and reviews with Hardcover.',
          items: ['API Token（已设置 / 未设置）', 'Validate token', 'Save'],
        },
        note: '已实现：API Token 存储（掩码回显，提交掩码 = 不修改）+ 真实连通性验证（向 Hardcover GraphQL 发 { me { id username } } 探针）。⚠️ 其鉴权失败也可能返回 200 + errors 字段，所以不能只看状态码。未支持：状态 / 书评同步（需先做书籍匹配）。',
      }),
      p('readwise', 'Readwise', 'Readwise', 'ready', {
        upstream: {
          title: 'Readwise',
          desc: 'Send your highlights to Readwise automatically.',
          items: ['Access Token（已设置 / 未设置）', 'Test', 'Enable sync（自动推送高亮）', 'Save'],
        },
        note: '已实现：Access Token 存储 + 真实验证（向 GET /api/v2/auth/ 发探针）。⚠️ Readwise 用 204 表示验证通过（不是 200）——按 200 判定会把有效凭据误判为失败。未支持：自动推送高亮与「Enable sync」开关。',
      }),
      p('storygraph', 'StoryGraph', 'StoryGraph', 'ready', {
        upstream: {
          title: 'StoryGraph',
          desc: 'Sync your reading progress and status to The StoryGraph.',
          items: ['_storygraph_session（Cookie，已设置 / 未设置）', 'remember_user_token（Cookie，已设置 / 未设置）', 'Validate cookies', 'Save'],
          uncaptured: '上游说明：StoryGraph 无公开 API，此集成复用登录态 Cookie，可能因对方改版失效。',
        },
        note: '已实现：两个 Cookie 的存储（掩码回显）。不做自动验证与同步 —— StoryGraph 没有公开 API，上游自己也只能用登录态 Cookie 并注明可能失效；本项目如实标注，而不是放一个点了没用的「Validate cookies」。',
      }),
    ],
  },
  {
    id: 'server',
    label: 'SERVER',
    zh: '服务端',
    icon: 'settings',
    pages: [
      p('admin/book-dock', 'Book Dock', '收书目录', 'ready', {
        note: '已实现：投递目录（= 输入目录）+ 监听状态与启停 + 自动处理开关 + 处理计数 + 入库后自动抓元数据（watcher 旁路调用 auto_fetch，按所属库的策略执行；达到置信度阈值的字段自动定稿，低于阈值的只列在预览页等人工确认）。',
        upstream: {
          title: 'Book Dock',
          desc: 'Quick actions shown on book pages.',
          groups: ['DROP FOLDER', 'METADATA', 'AUTO-FINALIZE'],
          items: ['Container path（/data/book-dock，由 BOOK_DOCK_PATH 环境变量配置）', 'Auto-fetch metadata from providers', 'Enable auto-finalize（元数据置信度达阈值自动定稿）'],
        },
        link: { to: '/settings/ext/watcher', label: '本项目扩展 → 监听' },
      }),
      p('admin/server-fonts', 'Server Fonts', '服务端字体', 'ready', {
        upstream: {
          title: 'Server Fonts',
          desc: 'Fonts installed for every reader on this server.',
          groups: ['UPLOAD FONTS', 'SERVER FONTS'],
          items: ['上传字体（TTF / OTF / WOFF / WOFF2，单个 ≤50MB）', '字体列表（上限 200，对所有用户生效）'],
        },
        note: '已实现：与「阅读字体」共用同一份字体库（本项目单用户部署，无「每用户 / 服务端」两级），上限 200。',
      }),
      p('admin/audit-log', 'Audit Log', '审计日志', 'ready', {
        note: '已实现：直接读活动日志并显示操作者（actor 为本次新增，历史条目按「未记录」渲染）+ 类别归并 + 按动作/结果/关键字筛选。上游是独立审计子系统，本项目复用活动日志。',
        upstream: {
          title: 'Audit Log',
          desc: '带操作者与类别的审计流水。',
          items: ['流水列（时间 / 操作者 / 类别 / 动作 / Details）', '操作类别：Authentication、Books、Libraries、Settings、Integrations'],
        },
        link: { to: '/tools/logs', label: '工具 → 日志' },
      }),
    ],
  },
  {
    id: 'ext',
    label: 'EXTENSIONS',
    zh: '本项目扩展',
    icon: 'wrench',
    own: true,
    pages: [
      p('ext/conversion', 'Conversion', '转换', 'ready', {
        upstream: {
          title: '（本项目独有）',
          desc: '上游 BookOrbit 无对应设置页 —— 它不做 TXT → EPUB 转换，因此没有分章、LLM 兜底、繁转简等概念。',
          items: ['分章模式（hybrid / regex / ai）', 'AI 上下文行数', 'AI 失败降级', '繁体转简体', 'LLM API Key / 接口地址 / 模型', '输出格式（EPUB / MOBI / AZW3）'],
        },
      }),
      p('ext/watcher', 'Watcher', '监听', 'ready', {
        upstream: {
          title: '（本项目独有）',
          desc: '上游的监听是「每书库一个 Watch folders 开关」，没有本项目这 9 项轮询/稳定判定参数。',
          items: ['目录监听开关与运行状态', '轮询间隔 / 递归子目录', '写入稳定等待 / 稳定判定轮数', '非 txt 原样导出', '启动时处理存量文件', '失败重试上限', '忽略规则（fnmatch）', '清空缓存 / 清空日志'],
        },
      }),
      p('ext/network', 'Network', '网络与下载', 'ready', {
        upstream: {
          title: '（本项目独有）',
          desc: '上游没有书源下载体系，因此没有下载开关、公版源限制、域名替换等设置。',
          items: ['传输重试次数', '开放搜索 / 下载', '仅放行公版源', '日志内存缓冲条数 / 日志目录', '域名替换'],
        },
      }),
      p('ext/advanced', 'Advanced', '高级', 'ready', {
        upstream: {
          title: '（本项目独有）',
          desc: '上游不提供「直接编辑配置文件」的入口；本项目保留它作为设置失效时的安全网。',
          items: ['settings.json 覆盖层提示与一键清除', '直接编辑 config.yaml 原文（保存前自动备份）', '重置为内置默认配置', '备份列表与还原'],
        },
      }),
      p('ext/about', 'About', '关于', 'ready', {
        upstream: {
          title: '（对应上游 Help → About BookOrbit）',
          desc: '上游把「关于」放在 Help 菜单里，本项目保留为设置页的一页。',
          items: ['应用定位', '前端 / 后端技术栈', '鉴权方式', '设置存储位置'],
        },
      }),
    ],
  },
]

/** 扁平化的页面列表（供路由生成与查找） */
export const SETTINGS_PAGES: SettingsPageDef[] = SETTINGS_GROUPS.flatMap((g) => g.pages)

/**
 * 设置页 → 所需能力（第 10 期「库类型 → 全量显隐」）。
 *
 * 单独一张表而不是写进每个 `p(...)`：
 *   · 显隐是**一处**策略，集中在这里一眼能看全，也便于对照后端 `core/features.py`；
 *   · 不声明的页面 = 通用页（账号 / 外观 / 服务端…），任何库类型都显示。
 */
export const PAGE_FEATURE: Record<string, string> = {
  'reader/ebook': 'ebook',
  'reader/pdf': 'pdf',
  'reader/comics': 'comic',
  'reader/audio': 'audio',
  // 这 6 页绑 `metadata` 能力：抓取结果只存服务端 DB、与文件格式无关
  // → 电子书 / 漫画 / 有声书库都可见（`metadata/authors` 绑的是 `authors`，仍只有电子书库）
  'metadata/providers': 'metadata',
  'metadata/field-rules': 'metadata',
  'metadata/custom-fields': 'metadata',
  'metadata/score': 'metadata',
  'metadata/auto-fetch': 'metadata',
  'metadata/genre-blocklist': 'metadata',
  'metadata/authors': 'authors',
}

/** 设置页默认落点 */
export const SETTINGS_HOME = '/settings/appearance/theme'

const PAGE_BY_PATH = new Map(SETTINGS_PAGES.map((pg) => [pg.path, pg]))

export function findSettingsPage(path: string): SettingsPageDef | undefined {
  return PAGE_BY_PATH.get(path)
}

/** 由路由 path 反查所属分组（面包屑用） */
export function findSettingsGroup(path: string): SettingsGroupDef | undefined {
  return SETTINGS_GROUPS.find((g) => g.pages.some((pg) => pg.path === path))
}
