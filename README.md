# NovelForge（novel_dl_convert）

TXT 小说入库 + 阅读工具，融合 Fanqie-novel-Downloader / kaf-cli / txt2epub / denovel 的思路。
面向 NAS / 服务器部署，输入与书库目录**物理分离**，避免源文件与读到的书混在一起。

> 第 62 期起 **TXT 只入库不转换**：投进 `input/` 的 `.txt` 与 EPUB / PDF 一样原样进书库，
> 在线阅读时才按需生成派生 EPUB（带目录、可批注、有进度）；不再落一份转换产物到 `output/`。
> 转换链路本身仍在 —— **书源下载**拿到的正文没有磁盘文件，仍由它组装成 EPUB。

除此之外，Web 端本身是一个可用的**书库 + 阅读器**：管理成品（书架 / 元数据 / 统计 / 工具），
直接在浏览器里读 ePub、PDF 与漫画，并把书库喂给第三方阅读器（OPDS / Komga / KOReader）。

## 功能

- 多正则 + 缩进降级 + **AI 兜底**的章节识别（`-t` 可调试正则；配置 `llm.api_key` 后**判据不自信**的文本才调 LLM）；
  第 62 期起**行首锚定**（正文中间提到「第 3 章」不再误切）+ 卷 / `【第1章】` / `（一）` 等新形态，规则版本写进派生缓存指纹；
  第 72 期起**长章书不再被误判成「没有章节」**（置信判据 = 边界密度**或**条数），缩进降级认全角空格
- 编码探测按**字符分布判据**择优（utf-8-sig / utf-8 / gb18030 / big5hkscs / big5）——
  「能解码」不等于「解对了」：繁体 Big5 书以前会被 GB18030 解成满屏乱码却「成功」；
  utf-8 自证按**前缀**判：采样窗口按字节截断，尾部被切断**不算**失败
  （大于 256 KB 的中文 TXT 曾因此整本被判成 GB18030）
- 文本精排、繁体转简体（opencc）
- 三级元数据（文件名 / 正文头部 / 在线补全）
- 基于 ebooklib 的 EPUB 组装（HTML 净化 + 封面）
- **可插拔书源适配器**：已含 Gutenberg 公版源 + JSON 规则源（`CONFIG_DIR/sources/*.json`），另附 `generic.py` 扩展模板（供必须写 Python 时复制）
- **下载加固**：类浏览器标头伪造、Cookie 持久化（LWPCookieJar 落盘）、429 退避重试、域名替换、**原生 JS eval**（Node 执行站点解密脚本）
- **增量更新**：为下载得到的 txt 写 sidecar，日后只爬取新增章节再重转
- **内容预览 API**：`/content?url=...` 即时抓取清洗（不落盘即可完美预览），`/supported` 判断 URL 归属
- **输入目录自动监听**：扔进 `input` 的文件自动收进书库（原样入库，`.txt` 也不再转换）
- **活动日志**：每一次「转换 / 添加 / 刮削」都记录时间、文件名、操作、成功或失败（Web 可查、可下载、CLI 可看）
- **刮削出版**：扫描入库后自动刮元数据，并在**每库独立的成品目录**里硬链接出一份副本、
  把元数据写进**副本**——原书文件逐字节不变，外部阅读器（Komga 等）挂载成品目录即可读到整理完成的书
- FastAPI 服务：上传即入库、按路径入库、列出文件、下载成品、搜索、下载
- **书库与阅读**：书架三视图 / 真实封面、ePub+PDF+漫画阅读器、进度与状态追踪、批注与收藏夹、数据统计、智能书架、九个工具 —— 见下两节
- **序号单元合并**（第 73 期）：漫画库 / 有声书库里 `《书名（1-43话）》/第1卷/第1话.pdf` 这类目录树按**一本书**入库
  （序号写法不限：`第1话` / `第二话` / `第03话` / `4 第4话` / `01.pdf`），书名自动剥掉「（1-43话）」这类范围备注，
  阅读器里逐话连读（话目录 / 上下一话 / 读完自动续）；看着不像连载的目录不合并，电子书库与混合库与以前逐字相同

## 书库与阅读

转换与下载之外，Web 端就是一个书库与阅读器。书目来自**各书库的根目录**（第 10 期起书库是
一条数据记录：默认库 = `output/`，另可在「设置 → 书库管理」新建电子书 / 漫画 / 有声书 / 混合库），
所以「把文件放进库根目录」就等于入库。

书库管理页按上游 BookOrbit 的范式组织：顶部一条工具条（**全部扫描** / 过滤 / 排序：默认顺序 · 名称 ·
书籍数 · 上次扫描），每个库一张卡分**四栏**（书库 · 内容 · 自动化 · 上次扫描）；
新建与编辑书库走**三页签** —— **内容**（名称 / 类型 / 存放方式 / 库根 / 来源子目录 / 归类关键词 /
**刮削成品目录**）、**自动化**（监听开关 / 扫描间隔 / 定时 cron / 刮削出版开关）、
**上次扫描**（上次扫描时间、备注、书目数与「立即扫描」）。分页签是因为这三块回答的是三个不同时刻的问题：
建库时该定什么、日常怎么跑、现在健康吗。

- **书架**：三视图（网格 / 列表 / 表格）、真实内嵌封面（显示模式 / 书脊 / 阴影 / 卡片叠加层）、搜索、
  排序、按系列折叠、多选批量（标记状态 / 评分 / 加入收藏夹）
- **元数据**：单本「编辑元数据」把改动存到应用数据库（书名 / 作者 / 系列 / 系列序号 / 语言 / 出版社 /
  标签 / ISBN），**所有格式都能改**（EPUB / PDF / 漫画 / 有声书），改完立即生效；
  **不改写书文件**（数据只存服务端，详情 / 列表 / 搜索 / OPDS / Komga 一致）；
  每个字段还能**「清空」**（显式无值，盖住在线的抓取值，之后抓取也不会把它填回来）或
  **「恢复在线」**（撤销改动，回落抓取值 / 文件原值）；系列与作者可成批改名、合并
- **阅读器**：ePub（排版增强：翻页 / 纵向 / 横向、分栏、字距词距、两端对齐、多档阅读主题）、
  PDF（pdf.js 懒加载）、漫画（CBZ）、有声书（倍速 / 睡眠定时 / 轨列表）、
  **合集**（序号单元树逐话连读：话目录 + 上/下一话 + 读完自动续，跨话进度连续）。
  ⚠️ **CBR 需要容器内有 `bsdtar`**（官方镜像已含）：RAR 是系统级解压依赖，缺它时相关入口会明确提示
- **序号单元合并**：漫画库 / 有声书库里一棵子树有 ≥2 个能解析出序号的媒体文件 ⇒ 整棵树 = **一本书**
  （`format = UNITS`，话数就是清单条数）；`.pdf` / `.cbz` / `.cbr` / 音频话混在一棵树里也认，
  各话按种类自动选阅读器。⚠️ 合并后是一本**新书**：旧的每文件一本的那些行的
  进度 / 评分 / 收藏**不会**并过来（旧行不删不搬，如实保留）；走**收书目录**（`input/`）丢进来的目录
  **不做**这种合并
- **阅读追踪**：进度与位置（位置精确到章节 / 页码）、阅读状态（未读 / 在读 / 读完 / 搁置 / 弃读）、
  起止日期、1–5 星评分与书评、Reading Log（按书的时间流水）、手工补录、阅读时长统计
- **批注 / 收藏夹 / 成就 / 通知**：批注按书聚合与检索；收藏夹跨书归类
- **数据统计**：规模卡片、入库节奏与阅读节奏（窗口 7 / 28 / 90 天可切换）、Top 作者 / 系列 / 出版社 / 题材、
  出版年代分布、平均阅读进度、**书库体检**（缺作者 / 缺语言 / 无封面 / 零字节 / 解析失败）
- **智能书架**：自定义规则书架（字段 + 操作 + 值，全部满足 / 任一满足），规则存服务端、命中数实时预览
- **元数据抓取**：内置 OpenLibrary 与 Google Books（**均无需 API Key**），按书名 + 作者匹配补全封面 / 出版社 /
  语言 / 简介 / 题材；字段级写入策略（默认**只补空**）、置信度阈值、题材黑名单、自定义元数据；
  一律**先预览、再应用**，结果**只存应用数据库**（含封面缓存，按书主键），**绝不改写任何文件** ——
  因此**不区分格式**（EPUB / PDF / 漫画 / 有声书一视同仁，有声书是目录型条目同样适用）；
  **新书入库自动抓取可按库分别开关**（全局默认关）。
  ⚠️ 手动编辑元数据同样**不限格式**：非 EPUB 没有 OPF 兜底原值层，所以「恢复」是撤销覆盖后回落在线的
  抓取值、没有在线值即为空（是清晰语义，不是缺口）
- **系列级元数据**：系列页展示**系列简介 / 出版社 / 首发年 / 题材 / 册数**，可直接编辑（改过即本地覆盖，
  再抓取不冲掉）并可「恢复在线」；「抓取全部系列」逐个抓、单个失败不中断。
  ⚠️ 取字段的顺序是**「本地覆盖 > 成员书聚合 > 在线补空」** —— 册数 / 首发年 / 出版社 / 题材优先取成员书
  OPF 里的**事实**，在线值只在算不出时补位。**这些数据只存在应用自己的数据库里，不写入书本文件**
  （EPUB 的 OPF 没有「系列简介」这个字段，写 `dc:description` 等于覆盖掉某一册自己的简介）；
  因此用 SMB 把书库直接挂给别的软件（如 Calibre）时看不到它们，而通过 Komga 兼容接口 / OPDS / 应用界面
  访问则全部可见。另外外部元数据源**没有「系列」实体**，只能拿系列名去检索、再用该系列的成员书做一致性
  校验 —— 分数不够时如实显示「未找到」，不会编造简介（界面会展示来源与置信度）
- **重排册号**：把某个系列的册号按当前顺序重写成 1..N（可逐册微调、可清空某册的序号），
  **序号只存服务端、不改文件名、也不改写 EPUB 文件** —— 因此阅读进度 / 批注 / 评分 / 收藏都不会断链，
  可随时再排或还原（代价：用别的软件直读文件看到的是文件里的原始序号）
- **工具**（9 个标签）：实体管理、批量重命名、重复书籍（同作者 + 书名相似度阈值可调）、缺失资源、
  书源管理、导出目录、本地导入、转换日志（内含「日志 / 刮削」两个子标签）。
  会改磁盘的三个工具一律**先预览、再应用**，且「删除」是移入回收站（`CONFIG_DIR/cache/recycle`），
  **从不直接删文件**（删书会把收书目录里的本地原件、书库里的文件、出版副本**三份**都移入回收站；
  第 81 期起「移除书库」**默认只删登记、一个文件都不动**，要清文件须在确认框里勾选「连文件一起清理」，
  那时才回收项目内的两份、**本地原件保留**）

### 刮削出版：给外部阅读器的第二份真相

想让 Komga 这类外部阅读器读到「整理好元数据的书」，又不想动自己收藏的原文件 —— 这一条就是为它准备的。
在**新建 / 编辑书库**时选一个**成品目录**（`libraries.publish_path`，仅对该库生效），之后：

- **扫描入库后自动刮削**（`scrape.enabled`，全局开、可按库关）：单线程串行抓在线元数据
  （沿用既有 `metadata_fetch`，落 `meta_online` / `meta_cover`），再把生效值里**与 OPF 原值不同**的字段
  写进副本；与 OPF 一致的不写，副本因此能保持纯硬链接、不额外占盘。
- **副本 = 硬链接**（跨文件系统时自动回退复制，页面标注「硬链接 / 复制」）：文件名套用该库的
  **命名规则 + 系列布局**（`系列名/系列名 #N.epub`，与 Komga 的约定一致）。
- **原文件绝对只读**：写元数据必须「临时文件 + 原子替换」（替换的是副本的目录项）——
  硬链接副本与源共享 inode，原地写会连源一起改坏，这条有测试兜底。
  因此**内嵌过元数据的副本会变成独立文件**（页面标「独立占用」），没内容可写的则保持共享。
- **没有元数据抓取也能用**：只把本地已有元数据出版成副本，外呼开关与抓取开关是两件事。
- **副本被删只提示不处置**：校验发现副本没了 → 标成「待确认」并写一条「硬链接副本已删除，
  原文件待确认」日志，等你空闲时选**保留原文件 / 删除原文件（移入回收站）/ 重新生成副本**；
  源文件不见了而副本还在 → 标「孤本」。**绝不自动删源、绝不自动重建**（状态机只许降级）。
- **失败与未刮的书可人工整理**：在「工具 → 转换日志 → 刮削」里看进展与结果，点「整理」改元数据
  （或采用在线候选）后**应用并重建副本**，外部阅读器立刻可见；失败可重试，超限后等人工介入。
- 成品目录**不得与库根 / 扫描源目录重叠**（否则副本会被扫回来变成重复书），后端在建库时就拦。
  推荐放在与它们平级的位置，例如 `<挂载根>/../output/ebook-sorted`。

## 多端互通

让别的阅读器用上这个书库，或与外部的阅读服务对接 —— 都在「设置 → 设备」里，**默认关闭**。

| 方向 | 能力 | 要点 |
|---|---|---|
| 对外 | **OPDS 目录** | 只读 Atom feed：全部 / 最近 / 按作者 / 按系列 / 按标签 / 搜索 / 单书 / 封面 / 下载。用 HTTP Basic + 应用账号；`/opds` 是独立前缀，不走 `/api` 的 Bearer 中间件（客户端只会发 Basic）。**按书库暴露**：可见库多于一个时根 feed 多一个「按书库」入口，每个书库有独立地址 `/opds/lib/<库 id>`，可在「设置 → 书库管理 → 每库设置」逐库关掉（默认全部暴露，关掉后直连返回 404） |
| 对外 | **Komga 库布局** | 有系列的书按 `系列名/系列名 #N.ext` 落盘（Komga 只认一层系列目录、不递归），并可从文件名或 OPF 推断系列；「整理既有库」把已平铺的书收进系列目录，**会改名时自动迁移阅读进度 / 批注 / 评分 / 收藏** |
| 对接 | **KOReader 进度互通** | 实现 kosync 协议（`users/auth`、`users/create`、`syncs/progress` 的 GET/PUT）：按 partialMD5 索引文档，并在 XPointer / 页码与本项目的位置之间换算 |
| 对接 | **Hardcover / Readwise / StoryGraph** | 凭据存储 + **真实连通性验证**（能验证的才放验证按钮；StoryGraph 无公开 API，如实标注不可验证） |
| 双向 | **Komga 兼容服务端** | 本应用可直接**冒充 Komga 服务端**：第三方 Komga 客户端（Mihon / Panels / 官方 App）把地址填成 NovelForge 即可浏览书库、读漫画与 PDF（服务端逐页渲染）、下载 EPUB、双向同步阅读进度。支持 Basic / `X-API-Key` / 会话三种认证与 Komga 的分页壳。**可按书库浏览**（系列与书籍都按库过滤，老客户端的 GET 端点同样生效）、**系列级「全部已读 / 全部未读」**（只把百分比顶到 100，不清除读者位置）、CBR 有正确的媒体类型；**有声书库不进 Komga**（Komga 没有音频模型，硬塞进去只会得到打不开的坏条目）。**每个书库可单独决定是否对 Komga 暴露**（「设置 → 书库管理 → 每库设置」，默认全部暴露；关掉后它不进客户端书库列表，直连它的系列 / 书籍地址也一并 404）。**Collections = 应用内收藏夹**（可新建 / 加系列 / 移出 / 重命名，改动真的落到收藏夹），**Readlists 为空**（本项目没有阅读清单这个概念，不编造），另有单库详情与系列内「上一本 / 下一本」 |

未做：Kobo 同步、邮件投递（成本与收益不匹配，已明确不做）；
外部服务的「同步任务」（把状态 / 书评 / 书摘推给对方）需要先做书籍匹配，尚未实现。

## 目录约定（输入 / 导出 / 配置 / 缓存 各自独立）

| 宿主机 | 容器内 | 作用 |
|--------|--------|------|
| `./input`  | `/app/input`  | 待转换的 txt / 电子书源文件 |
| `./output` | `/app/output` | 生成的 epub 等成品（**也是书库的唯一来源**：文件放进去就等于入库） |
| `config.yaml` | `/app/config/config.yaml` | 转换行为配置（只读挂载） |
| `./cookies` | `/app/config/cookies` | 各书源 Cookie 持久化（下载功能，跨重启保留登录态） |
| `./cache`   | `/app/config/cache`   | AI 分章结果缓存（按文本哈希）+ 监听状态（已处理文件指纹）+ **回收站** `recycle/` |
| `./config/logs` | `/app/config/logs` | 活动日志 `activity.log` / `activity.jsonl` |
| `./data` | `/app/data` | **运行时数据库** `novelforge.db`：阅读进度 / 批注 / 评分 / 收藏 / 阅读状态 / 偏好 / 外部服务凭据。**备份它等于备份全部阅读数据**（容器里由 `DATA_DIR=/app/data` 指定，裸跑时默认落 `CONFIG_DIR/data`） |
| `./config/fonts` | `/app/config/fonts` | 「设置 → 阅读字体」上传的自定义字体（TTF / OTF / WOFF / WOFF2） |
| `./config/sources` | `/app/config/sources` | 数据驱动书源规则 |
| `./config/backups` | `/app/config/backups` | 直接编辑 `config.yaml` 前的自动备份 |

目录路径由环境变量 `INPUT_DIR` / `OUTPUT_DIR` / `CONFIG_DIR` / `COOKIE_DIR` / `CACHE_DIR` / `LOG_DIR` /
`DATA_DIR` / `SOURCES_DIR` / `FONTS_DIR` / `BACKUP_DIR` 控制。

## 自动监听与活动日志

服务启动后自动监听输入目录（也可 `AUTO_WATCH=false` 关闭）：

| 放到 input 的文件 | 处理动作 | 日志 |
|------------------|---------|------|
| `*.txt` | **原样收进书库**（第 62 期起不再转 EPUB） | `添加` |
| 其它文件（pdf / epub / zip / 图片…） | 原样复制到 output | `添加` |
| 隐藏文件、临时文件（`.*`、`*.tmp`、`*.crdownload`、`*.meta.json`…） | 忽略 | — |

每条日志含：**时间、文件名、操作（转换 / 添加）、成功或失败**，失败附带原因；成功还记录输出文件名、体积、耗时。
日志同时写 `activity.log`（人类可读）与 `activity.jsonl`（结构化，供接口读取），目录为 `LOG_DIR`（默认 `/app/config/logs`）。

实现要点：
- **轮询而非 inotify**：NAS 上 input 多是 SMB / NFS 挂载，inotify 事件不可靠，轮询 +「文件大小连续 N 次不变才认为写完」最稳。
- **状态持久化**：已处理文件的 `(size, mtime)` 存进 `CACHE_DIR/watcher_state.json`，重启不会重复转换；文件被覆盖更新（指纹变化）才重新处理。
- **失败重试**：同一文件失败最多重试 `watcher.max_retries` 次，之后记为失败并跳过，避免坏文件反复刷日志。

相关接口：

| 接口 | 说明 |
|------|------|
| `GET /api/watcher` | 监听状态（是否运行、输入输出目录、间隔、累计统计） |
| `POST /api/watcher/start`、`/stop` | 启停监听 |
| `POST /api/scan` | 立即扫描一轮（不等下个周期） |
| `GET /api/logs?limit=&action=&status=&q=` | 活动日志（新→旧，可按操作 / 结果 / 关键字过滤） |
| `GET /api/logs/download` | 下载 `activity.log` |
| `DELETE /api/logs` | 清空日志 |

配置（`config.yaml`）：

```yaml
watcher:
  enabled: true           # 服务启动时自动监听（环境变量 AUTO_WATCH 可覆盖）
  interval: 5             # 轮询间隔（秒），NAS 网络挂载建议 >=3
  recursive: false        # 是否递归子目录
  settle_seconds: 1       # 文件写入稳定判定的单次等待
  stable_rounds: 2        # 连续 N 次大小不变才认为上传完成
  copy_non_txt: true      # 除 txt 外的格式是否也收（关掉 = 只收 txt）
  process_existing: true  # 启动时处理 input 里已有的存量文件
  max_retries: 3          # 单文件失败重试上限
  ignore: [".*", "*.tmp", "*.part", "*.crdownload", "*.meta.json", "*.log"]
logging:
  dir: ""                 # 留空则用 LOG_DIR
  max_entries: 2000       # 接口读取的内存缓冲条数
update:                   # 第 78 期：版本检查与一键更新（第 80 期起四个键保存即生效；第 84 期加固）
  check_enabled: true     # 容器启动即查一次 + 每 interval_hours 小时检查 GitHub 最新版本（出网失败静默忽略；关掉即停后台线程）
  interval_hours: 6       # 定时检查间隔（小时）；启动即首检（不等一个间隔），保存后立即按新间隔重启
  image: "ghcr.io/735876214/novel_dl_convert:latest"  # 一键更新拉取的镜像；可改私有仓库 / 加速镜像，留空=环境变量 NOVELFORGE_UPDATE_IMAGE 或内置默认
  auto_apply: false       # 发现新版是否自动应用（默认关：只提示，手动点「立即更新」）
```

> **一键更新**：默认**不挂载** `docker.sock`，「新功能」页只展示复制升级命令
> （`docker compose pull && docker compose up -d`）。要在应用内点「立即更新」真实重建容器，
> 在 `docker-compose.yml` 的 `volumes` 下取消注释 `/var/run/docker.sock` 那一行
> （这会把宿主机 docker 控制权交给容器，仅在信任环境启用）。
>
> **自动更新（第 84 期加固）**：把 `update.auto_apply` 设为 `true` 后，后台检查发现新版本会**自动**
> 先**备份业务数据**、再拉取镜像并重建容器。要点：
> - **每次容器启动即校验一次版本**（不等一个检查间隔）—— 自动更新重建容器后的那次启动会立刻确认已是最新；
> - **更新前自动备份**（PostgreSQL 走 `pg_dump -Fc`，SQLite 整文件拷贝），落在 `config/backups`（持久卷，
>   容器重建后仍在），保留最近 5 份；**备份失败即中止本次更新**，绝不带着数据风险继续；
> - **失败退避重试**：同一版本失败后按 1 小时 → 6 小时 → 24 小时退避重试（不再「失败一次就永久放弃」），
>   失败原因与下次重试时间显示在「扩展 → 更新」页与「新功能」页；
> - 未挂载 `docker.sock` 时如实降级为「只提示升级命令」，**不会**在退避计数里记一次「失败」。
> 内网 / 私有仓库请用 `update.image` 或环境变量 `NOVELFORGE_UPDATE_IMAGE` 指定镜像地址。

## 命令行

```bash
pip install -r requirements.txt

# 转换单个文件
python -m novelforge convert 小说.txt -o ./output --traditionalize

# 批量转换目录（省略路径时默认用 INPUT_DIR / OUTPUT_DIR 环境变量）
python -m novelforge convert ./input -o ./output

# 测试某标题是否能被正则识别
python -m novelforge convert -t "第一章 开端"

# 跨书源搜索（需先在 config.yaml 开启 download.enabled=true）
python -m novelforge search "三体"

# 下载书籍条目并转 EPUB（item 为 search 返回的某条 JSON；或给 --source/--url/--title）
python -m novelforge download --item '{"_source":"gutenberg","url":"...","title":"...","author":"..."}'

# 增量更新本地 txt（需先经 download 生成 .meta.json sidecar）
python -m novelforge update ./input/某书.txt

# 监听 input 目录：文件自动收进书库（前台常驻，Ctrl+C 停止）
python -m novelforge watch --interval 5 --recursive

# 只扫描一轮就退出（适合放进 cron / 任务计划）
python -m novelforge scan

# 查看活动日志（可过滤）
python -m novelforge logs -n 50 --action 转换 --status 失败
```

## Web 服务（NAS 部署）

### 部署方式：直接拉预构建镜像（源码 + 依赖已烤进镜像）

镜像 `ghcr.io/735876214/novel_dl_convert:latest` 由 GitHub Actions 在每次推送到 `main` 时自动构建并发布，
**源码与全部 Python 依赖已在「构建镜像时」烤进镜像**——不需要 NAS 本地 build，也不需要容器启动时 clone 源码。
版本号一变（仓库根 `VERSION`），CI 还会自动打 `v<版本>` tag 并创建 GitHub Release（说明取 `CHANGELOG.md` 对应段）。
因此在 NAS 上**只需要 `docker-compose.yml` 一个文件**（配置全部写在文件里，不依赖任何 `.env`），一条命令即可运行：

```bash
# 1) 在 NAS 上建个部署目录，把本仓库的 docker-compose.yml 拷进去（只要这一个文件）
mkdir -p /volume1/docker/novelforge && cd /volume1/docker/novelforge

# 2) 按需修改文件里标了「可改」的几处：端口 / 数据路径 / 登录密码（不改也能直接跑）

# 3) 启动：自动从 ghcr.io 拉取「已含源码+依赖」的镜像并运行（无需 git / 无需 build / 无运行时 clone）
docker compose up -d
```

> 首次会下载镜像（含 Python 依赖，约几百 MB，视网速 1~3 分钟，仅此一次，之后本地有缓存）；
> 镜像下载完成即**秒级启动**，彻底告别之前「启动时 git clone 源码」的 2~4 分钟等待。
> 之后日常重启 / NAS 重启恢复都是秒级。

> 数据目录（`input/` `output/` `config/` `cookies/` `cache/` `data/` `libraries/`）首次启动由 Docker 自动创建，
> 无需手动 `mkdir`；配置放 `./config/config.yaml`（留空则应用回退到内置默认值）。

**NAS 上常改的几项**（都在 `docker-compose.yml` 里，改完 `docker compose up -d` 生效）：

| 改哪里 | 默认 | 说明 |
|--------|------|------|
| `ports` | `8992:8000` | 冒号左边是 NAS 对外端口，与系统占用端口冲突时改它（右边是容器内端口，别动） |
| `./libraries:/app/libraries` | `./libraries` | 书库**来源根**：填 NAS 上已有的书库共享目录绝对路径（如 `/volume1/books`），其下文件夹可被「新建书库」就地引用 |
| `./input` / `./output` | 部署目录下同名子目录 | 输入与成品目录，**必须分开** |
| `./data` | `./data` | SQLite（阅读进度 / 批注 / 账号 / 书库登记），务必落在持久盘 |
| `AUTH_USER` / `AUTH_PIN` / `AUTH_SECRET` | `admin` / `changeme` / 占位串 | **仅首次启动初始化**，之后在界面「设置 → 账户」里改 |
| `pull_policy` | `missing` | 本地已有镜像就不联网检查，断网也能启动；想让每次启动都追最新镜像改成 `always` |
| `# user: "1026:100"` | 注释掉（=root） | 想让挂载目录里的文件归某个 NAS 用户所有时取消注释（群晖常见 `1026:100`） |
| `# - HTTP_PROXY=…` | 注释掉（直连） | 容器要走代理才能访问书源 / 在线元数据时取消注释（Clash 跑在 NAS 主机上则填 `http://host.docker.internal:7890`） |

- 访问 `http://<NAS-IP>:8992` 上传文件入库
- **文件直接丢进 `./input` 即可**：自动收进书库并记日志（网页「转换日志」页可看），在线阅读 TXT 时按需生成目录
- **输入放 `./input`，成品落 `./output`**，互不影响
- 在线书源：`POST /search`、`POST /download`；内容预览：`GET /content?url=`、`GET /supported?url=`
- Synology Container Manager / QNAP Container Station：新建「项目 / 应用」，目录选上面那个部署目录即可
- ⚠️ 部署目录里**不要**放 `docker-compose.override.yml`：Compose 会自动合并它并静默改掉端口与拉取策略（本仓库不提供此类叠加件）

### 更新代码

仓库推新后，GitHub Actions 会自动重建并发布新镜像。NAS 上拉取最新镜像即可：

```bash
docker compose pull && docker compose up -d
```

> 只执行 `docker compose up -d` 不会拉新镜像（`docker-compose.yml` 里默认 `pull_policy: missing`，这是刻意的：
> 断网或 ghcr.io 访问受限时容器照样能启动）。想恢复「每次启动都自动追新」，把该值改成 `always`。

### 为什么既没有本地 build、也没有运行时 clone

之前两种方案都有等待：免 build 方案在**容器启动时** `git clone` 源码（2~4 分钟）；
本地 build 方案则要求 NAS 能 build 镜像（部署平台常拿不到 Dockerfile）。
现改为 **CI 构建并把「源码 + 依赖」烤进 `ghcr.io` 公开镜像**：NAS 只是下载一个现成镜像，
既不 build 也不 clone，部署后等待时间降到最低、更新也只需 `docker compose pull`。

### 目录结构

```
novel_dl_convert/
  docker-compose.yml        部署版（NAS 只需这一个文件）：拉 ghcr 预构建镜像；端口 / 挂载 / 账号都写在本文件里
  docker-compose.test.yml   本地测试版：本地 build + 挂源码、端口 8993、数据隔离到 ./data-test
  start.sh                  启动脚本（依赖已内置，自检后 exec uvicorn，秒级拉起）
  Dockerfile                多阶段构建：builder(venv 依赖) + node(仅取二进制) + frontend(Vue 构建) + runtime(python-slim)
  config.yaml               转换行为配置（目录路径由 compose 的环境变量控制）
  novelforge/          Python 包
    cli.py             命令行入口（convert / search / download / update / watch / scan / logs）
    server.py          FastAPI 服务（NAS 部署 + 内容预览 API）
    config.py          目录与配置解析
    core/              预处理 / 分章 / AI 分章 / 网络加固 / 元数据 / EPUB 组装 / 管线
                       + activity_log.py（活动日志）· watcher.py（输入目录监听）
                       + library.py（扫描导出目录，聚合书目 / 作者 / 系列 / 重复 / 缺失）
                       + fileops.py（安全改名与移动、冲突检测、回收目录；不做 unlink）
                       + db.py（持久层：进度 / 批注 / 评分 / 收藏 / 状态 / 偏好 / 凭据）
                       + catalog.py（书目索引：增量扫盘 + 落库，请求路径不再扫盘）
                       + sqlcompat.py（SQL 方言适配）· pg.py（PostgreSQL 后端）
                       + pgmigrate.py（SQLite → PostgreSQL 一次性数据搬迁）
                       + publish.py（刮削出版：硬链接副本 / 原子写副本 / 回收）
                       + scrape.py（刮削台账状态机与单线程 worker，含「待确认」处置）
                       + stats.py（统计聚合）· achievements.py · recommend.py（相似书）
                       + auth.py（单用户轻登录）· comics.py（CBZ 解包）· fonts.py（字体管理）

                       + opds.py（对外 OPDS 目录）
                       + komga.py（Komga 库布局与系列推断）· koreader.py（kosync 进度互通）
                       + integrations.py（Hardcover / Readwise / StoryGraph 凭据与验证）
    sources/           书源适配器（gutenberg 公版 / generic 模板·不注册 / rules 数据驱动 / store 用户源管理 / manager）
    static/v2/          前端构建产物（Vue + Tailwind，由 frontend/ 构建，不入库）
  frontend/           前端工程（Vue 3 SFC + TypeScript + Vite 8 + Tailwind v4 + Pinia）
    src/views/          仪表盘 / 探索发现 / 任务中心 / 数据统计 / 阅读记录 / 通知 / 成就 /
                        书架 / 单书详情 / 作者 / 系列 / 批注 / 收藏夹 / 智能书架
                        reader/    阅读器（ePub / PDF / 漫画）
                        settings/  设置页（注册表生成；48 页分 6 组，上游 41 页逐页有落点）
                        tools/     工具页外壳（ToolsLayout，顶部标签栏）+ 9 个工具子页
    src/components/     外壳（侧栏 / 顶栏 / 任务抽屉）+ UI 组件 + 仪表盘部件 + 阅读器组件
    src/stores/         Pinia：theme / nav / library / tasks / dashboard / ui / auth /
                        collections / fonts / stats / shelfPrefs / coverPrefs / prefSync
    src/lib/            阅读与外貌偏好（readerPrefs / pdfPrefs / comicPrefs）、
                        智能书架求值（smartScope）、偏好同步桥（prefsBridge / prefsPayload）
    src/assets/theme/   照搬 BookOrbit 的 tokens / accents / radius / bridge / cover-effects
```

### 数据库后端：SQLite（默认）与 PostgreSQL

第 62 期起，业务数据可以由 **PostgreSQL** 承载。**不配置时行为与之前完全一致**（内置
SQLite），所以老部署升级上来不会被动改后端。

```yaml
      # docker-compose.yml 的 novel_dl_convert.environment 里：
      - NOVELFORGE_DB=pg
      - NOVELFORGE_PG_DSN=postgresql://novelforge:novelforge@postgres:5432/novelforge
```

仓库自带的 `docker-compose.yml` 里已经有一个 `postgres` 服务（数据落在 `./pgdata`），
上面两行也**已经默认打开**。想把数据库换回 SQLite，把这两行注释掉再 `docker compose up -d`
即可 —— 老的 `./data/novelforge.db` 一直在，随时能回去（切过去之后在 PG 里产生的增量会丢）。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `NOVELFORGE_DB` | `sqlite` | 后端选择。取 `pg` / `postgres` / `postgresql` 走 PostgreSQL |
| `NOVELFORGE_PG_DSN` | 空 | 选了 `pg` 就必须给。**留空会带着明确报错启动失败**，不会静默回落 SQLite |
| `NOVELFORGE_PG_SCHEMA` | `public` | 表建在哪个 schema 里 |
| `NOVELFORGE_PG_RESET` | 关 | **只给测试用**：打开后允许「整个 schema 删掉重建」。别在生产打开 |

**老数据怎么办：自动搬迁。** 首次用 PG 启动时，服务端会把 `DATA_DIR/novelforge.db`
**整库搬进 PG**（逐行、幂等、只搬一次），搬完在「活动日志」里留一条 `migrate` 记录。

- 原 SQLite 文件**一个字节都不改** —— 它是回滚唯一的路，别删；
- 搬迁的幂等标记写在 **PG 那边**的 `app_state` 表里，所以重装 PG 会重新触发一次搬迁；
- 重跑不会覆盖 PG 上已有的行（`ON CONFLICT DO NOTHING`）—— 切过去之后读的进度、
  改的批注不会被旧库盖回去；
- **搬迁失败会直接启动失败**，不会出现「界面空的但其实没连上」；
- 想手动搬 / 换个源库：`python -m novelforge.core.pgmigrate [--force] [源库路径]`。

书目索引（`book_index`）**不搬**：它是磁盘的投影，行里存的是绝对路径，换机器就不成立；
它对增量扫描是自愈的，第一次刷新会自己重建（所以搬迁后第一次进书架可能稍慢一拍）。

**注意：把接口从 42 秒降到亚秒的是「书目索引落库」（见「书库与阅读」一节），
与选哪个数据库无关** —— 索引在 SQLite 上一样快。PG 解决的是容量与并发余量。

跑测试时想验 PG 那条路：

```bash
NOVELFORGE_DB=pg NOVELFORGE_PG_DSN=postgresql://novelforge:novelforge@127.0.0.1:5433/novelforge \
  NOVELFORGE_PG_RESET=1 python -m pytest
```

⚠️ `NOVELFORGE_PG_RESET=1` 下**每个用例都会把整个 schema 删掉重建** —— 只对测试库这么跑；
不设这个开关就直接跑，conftest 会拒绝启动（而不是悄悄用一个没有隔离的库）。

### 缓存层：Redis（可选）

第 62 期起可以再叠一层 Redis 读缓存。**它是可选的，而且是可缺席的**：不配就整层关闭，
Redis 中途挂掉会自动降级为直读数据库 —— 两种情况下业务都照常。

```yaml
      # docker-compose.yml 的 novel_dl_convert.environment 里：
      - NOVELFORGE_REDIS_URL=redis://redis:6379/0
```

仓库自带的 `docker-compose.yml` 里有一个 `redis` 服务（**不落盘**：纯缓存，丢了重建就是），
上面这行**已经默认打开**；注释掉它就等于关掉缓存。

**先说清楚它解决什么、不解决什么**（与数据库那节一样的口径）：本项目是单进程、单用户，
Redis 的跨进程优势在这里用不上 —— **它同样不是「书架 42 秒」的解药**（那是书目索引）。
三处缓存里只有一处收益明显：

| 缓存 | 内容 | 收益 |
|---|---|---|
| `nf:chapter:*` | 章节正文 HTML | **明显**：省掉开 zip / 解压 / 解码 / 正文资源 URL 改写，书库挂在 NAS 上时这些每一步都在付网络往返 |
| `nf:book:list:*` | 书目列表（含元数据覆盖层） | 有限：省一次查询 + 一次覆盖层 + 序列化，与直读同一量级 |
| `nf:cover:*` | 封面字节 | 有限：HTTP 层本就有 `max-age=86400`，收益只在「换设备 / 清缓存」那几次 |

**失效只有一处入口**：所有写操作（改名 / 上传封面 / 元数据编辑 / 刮削落库 / 搬迁 / 建库…）
本来就会调 `library.invalidate()`，缓存层挂在那条路上；另外「用户绕过 App 直接往 NAS
目录里丢文件」这类**没有写操作**的变更，由增量扫描报告 `added / removed` 来失效
（`unchanged` 的一轮**不清缓存** —— 否则每轮刷新都把缓存清一次，等于没有）。章节与封面
的键里带着**源文件指纹**，文件一变键就变，不需要手动失效。

Redis 挂掉时：连着失败几次就**熔断 30 秒**，期间一次网络都不发、所有读当未命中，
到点自动重连 —— 不会出现「Redis 没了，每个请求都去等一次超时」。缓存层也**不会**
让服务起不来：驱动缺失只提示不拦（`NOVELFORGE_REDIS_URL` 配了却没装 `redis` 包时，
`start.sh` 会打一条 `[WARN]` 然后照常启动）。

看命中率与内存占用：

```bash
docker compose exec redis redis-cli INFO memory | grep used_memory_human
docker compose exec redis redis-cli --scan --pattern 'nf:*' | wc -l
```

跑测试时想验缓存那几条（**没有 Redis 会自动跳过**，离线全量不受影响）：

```bash
NOVELFORGE_TEST_REDIS_URL=redis://127.0.0.1:6380/15 python -m pytest tests/test_cache.py -v
```

⚠️ 测试用**独立的 db 15**（`NOVELFORGE_TEST_REDIS_URL` 可改），不会碰生产用的 db 0。

## 数据驱动书源（可视化批量添加，无需写代码）

除了写 Python 适配器，还可以用一段 **JSON 规则** 描述站点，在 Web 界面「书源管理」里**批量粘贴 / 上传**即可生效，无需改代码、无需重启。规则存到 `config/sources/<name>.json`（挂载目录，重建镜像不丢）。

### Web 界面
界面是 Vue 单页应用（hash 路由）。侧栏为：主导航（仪表盘 / 探索发现 / 任务中心 / 工具 /
数据统计 / 阅读记录 / 通知中心 / 成就）+ 四个可折叠组（浏览 / 库 / 智能书架 / 收藏夹）。

> 「工具」**与任务中心并列**（同属主导航这一层），但**不自成一块** —— 它不再是一个带组标题的
> 独立分组，而是工具页的**唯一入口**：点进去是单页 9 标签。

- **仪表盘**：顶部统计部件（书库概览 / 年度目标环形 / 入库节奏柱状图）+ 下方横向滚动书架行；
  右下角「调节」按钮可开关与拖拽排序部件、增删书架行（偏好存浏览器本地）。
- **探索发现**：输入书名跨全部书源并发检索 → 结果可「预览」→ 点「下载」后台抓取，进度实时回写任务中心。
- **任务中心**：下载 / 转换任务的统一列表，按状态筛选；右侧抽屉形态（点遮罩或 Esc 关闭）。
- **数据统计**：规模卡片 + 入库与阅读节奏（窗口 7 / 28 / 90 天可切换）+ Top 作者 / 系列 / 出版社 / 题材 +
  出版年代分布 + 平均阅读进度 + **书库体检**（缺作者 / 缺语言 / 无封面 / 零字节 / 解析失败）。
- **阅读记录**：按时间的阅读流水（Reading Log），支持手工补录。
- **通知中心 / 成就**：任务与系统通知（只读标记，不做推送）；基于阅读数据的单用户成就墙。
- **工具**：**单页 + 顶部下划线标签栏**（结构照搬 BookOrbit 的 tools），9 个标签在页内切换；
  切换时各标签的列表 / 筛选 / 输入与滚动位置都保留（子页走 `KeepAlive`）。
  - **实体管理**：按作者（或系列）聚合成品书目，可批量改名、可合并。作者名按本项目命名约定
    写在文件名里，因此「改名」实质是**移动文件**；新名字同时写进服务端元数据
    （`meta_override`）让列表与聚合立刻识别，**不改写 EPUB 内容**。
  - **批量重命名**：按规则（`{title}` / `{author}` / `{series}` / `{index}` / `{ext}`）生成
    「旧名 → 新名」对照表，冲突行置灰且不可提交，确认后才落盘。
  - **重复书籍**：同作者 + **书名相似度阈值可调**（默认 85%，与 Calibre 的 similar-title 口径一致），
    相似的书聚成一组，每组选一项保留、其余移入回收目录。
  - **缺失资源**：列出零字节 / 无法解析 / 缺封面的成品文件，并逐条说明原因。
  - **书源管理**：查看已注册书源，粘贴 JSON 或上传文件批量添加，可删除用户源。
  - **导出目录**：列出成品与下载留档的 txt，提供下载。
  - **本地导入**：拖拽上传本地文件直接入库、按路径入库、监听目录启停与立即扫描。
  - **转换日志**：全部活动日志（时间 / 文件名 / 操作 / 成败，支持过滤、下载、清空）。
- **书架**：三视图（网格 / 列表 / 表格）+ 搜索 / 排序 / 系列折叠 / 多选批量；书卡用真实内嵌封面。
- **单书详情**：概览 / 目录 / 文件 / 批注 / 阅读状态（评分与书评、相似书推荐）等标签，
  并可「编辑元数据」——改动存服务端，**不改写 EPUB 文件**。
- **阅读器**：ePub（排版增强）/ PDF / 漫画三种；阅读进度、状态与时长自动回写。
- **设置**：48 个页面分 6 组（上游 BookOrbit 41 页逐页有落点，含只读占位对照页）—— 你 / 书库 / **设备**（OPDS、Komga、KOReader、字体、偏好与同步）/
  外部账号 / 服务端 / 本项目扩展。含主题（浅色 / 深色 / 跟随系统）、65 档点缀色、四档圆角、
  转换与监听配置、回收站与维护等。
- **接口文档**：FastAPI 自带的交互式 API 文档在 **`/docs`**（OpenAPI，实时反映全部路由）——
  下面几张 API 表只是常用项的摘录，不作为完整清单。

> **工具页的安全约定**：会改磁盘的三个工具（实体管理 / 批量重命名 / 重复书籍）一律
> **「先预览、再应用」**，`apply` 只接受预览过的具体条目、不接受自由规则；
> **删除即移入回收目录**（`cache/recycle`，带时间戳前缀，永不 `unlink`，可人工取回），
> 每次实际改动都写进「转换日志」（动作为「重命名」/「清理」）。

#### 前端开发与构建
```bash
cd frontend
npm install          # 依赖走 registry.npmmirror.com（见 frontend/.npmrc）
npm run dev          # 开发：Vite dev server（HMR），/api /health /download 代理到 localhost:8993
npm run build        # 产出到 frontend/dist
npm run deploy       # 同步 dist → novelforge/static/v2（先删后拷）
```

> 生产镜像由 `Dockerfile` 的 `frontend` 阶段自动构建，无需本地执行 `deploy`。
>
> **注意**：dev server 看到的是最新源码，不等于 `dist` 最新 —— 验证生产服务前必须重新
> `npm run build && npm run deploy`。

#### 自动化测试（第 11 期「工程护栏」）

```bash
.venv/bin/pip install -r requirements-dev.txt     # 含 pytest（**不进生产镜像**）
.venv/bin/python -m pytest                        # 全部用例，约 2 秒
.venv/bin/python -m pytest tests/test_migrate.py   # 只跑某个模块
```

- 覆盖两层：**核心纯逻辑**（跨库移动与回滚、入库归库判决、库类型能力矩阵、元数据分层、路径安全边界）
  + **接口冒烟**（鉴权、书库 CRUD 边界、元数据覆盖与恢复、能力清单、系列按媒体分组）。
  （⚠️ 第 77 期移除了「按格式归库」及其端点，原先那两处措辞随之改掉；跨库移动的用例在 `tests/test_book_move.py` 与 `tests/test_migrate.py`。）
- 全程**离线**（不触任何外部网络）；每个用例自带临时目录与独立 SQLite，**不依赖执行顺序**、可反复连跑。
- 只新增 `tests/` 与 dev 依赖：`Dockerfile` 只装 `requirements.txt`，生产镜像不受影响。

### 规则字段（JSON Schema 要点）
```jsonc
{
  "name": "my_site",                  // 唯一标识（必填）
  "display_name": "我的站",            // 展示名（可选）
  "domains": ["example.com"],          // 域名白名单（必填，用于自动选源）
  "public": false,                    // 是否公版/合规（默认 false）
  "headers": {"User-Agent": "..."},   // 可选覆盖请求头
  "concurrency": 8,                   // 并发抓取章节上限
  "search": {                         // 搜索
    "url": "https://x.com/s?q={title}",// {title} 会被 URL 编码替换
    "mode": "css",                    // css | regex
    "container": ".item",             // css：每条结果容器选择器
    "fields": {"title": ".t", "author": ".a", "url": "a::attr(href)"}
    // regex："pattern": "<a href=\"(?P<url>[^\"]+)\">(?P<title>[^<]+)</a>"
  },
  "book": {                           // 取书
    "mode": "toc",                    // toc（目录式）| single（整页即全文）
    "toc": {"mode": "css", "container": "#list a", "url_attr": "href"}
    // regex："pattern": "<a href=\"(?P<href>[^\"]+)\"[^>]*>(?P<title>[^<]+)</a>"
    "content": {"mode": "css", "container": "#content", "text": true}
    // regex："pattern": "<div id=\"content\">([\\s\\S]*?)</div>"
  },
  "chapter": {                        // 分章（single 模式或全文后切分生效）
    "mode": "toc",                    // toc（结构化，直接用目录）| regex | auto
    "regex": "第\\s*\\d+\\s*章"        // mode=regex 时必填
  }
}
```
- 搜索 / 取书的解析均支持 **css 选择器**（需 `beautifulsoup4`，已加入依赖）与 **regex** 双通道，`::attr(name)` 取属性，空选择器 `""` 取元素自身文本。
- **分章策略**：`book.mode=toc` 时直接用书目目录结构化分章（最干净，推荐）；`book.mode=single` + `chapter.mode=regex` 用该书源正则切全文；`chapter.mode=auto` 走全局正则/缩进/AI 检测。
- 可一次粘贴 **JSON 数组** 或 **每行一条 JSON（JSONL）** 实现批量添加；示例见 `examples/sources/`（`example_regex.json` / `example_css.json`）。

### 自建镜像（可选）

默认直接用 ghcr.io 预构建镜像即可。需要自己 build 时，Dockerfile 是多阶段构建：

```bash
docker build -t novelforge .                 # 默认 amd64
docker build --build-arg NODE_VERSION=22 -t novelforge .
```

| 阶段 | 作用 | 是否进最终镜像 |
|------|------|----------------|
| `builder` | 装 `build-essential`，把依赖装进 `/opt/venv` | 否 |
| `nodejs` | 官方 Node 镜像，只借 `node` 二进制（书源 JS 解密用） | 仅二进制 |
| `runtime` | `python:3.12-slim` + venv + 源码 | 是 |

瘦身要点：编译工具链不进最终镜像；venv 剔除 pip/wheel、`.so` 去符号；只取 Node 二进制而
不带 npm/文档；按路径精确 COPY 配合 `.dockerignore`。若不需要 JS 解密能力，删掉 runtime
阶段 `COPY --from=nodejs` 那一行可再省约 90~110MB（镜像里最大的单个文件）。

## 扩展一个新书源

**首选：JSON 规则（不写代码）** —— 在设置页「书源」粘贴规则，或往 `CONFIG_DIR/sources/<name>.json`
放一个文件，启动时自动加载。字段约定见 `novelforge/sources/rules.py` 的模块 docstring（搜索 / 取书 /
正文提取各支持 css 与 regex 两种模式，可离线用正则）。

**进阶：Python 适配器** —— 复制 `novelforge/sources/generic.py` 为 `my_site.py`，改 `name` / `domains`，
实现 `search()` 与 `fetch_book()`；若有字体加密 / 内容混淆，在 `decryption_js()` 返回解密片段，
`render()` 会自动调用 Node 执行。**给自己的类加 `@register`** 即可被 `/search`、`/download`、`/supported`
自动识别，零改核心。

> 模板本身带 `@register` 会让每次 `/api/search` 都命中一个未实现的 `search()`，被吞成一条
> 「书源 generic 搜索失败」的假失败日志，并让它那个占位域名混进书源清单 —— 所以模板**不注册**。

## 合规说明

下载功能默认关闭，仅对接公版书源（Project Gutenberg）。使用其他书源请遵守目标站点
robots.txt 与服务条款，仅限合法用途。
