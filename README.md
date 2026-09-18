# NovelForge（novel_dl_convert）

TXT 小说转 EPUB 工具，融合 Fanqie-novel-Downloader / kaf-cli / txt2epub / denovel 的思路。
面向 NAS / 服务器部署，输入与导出目录**物理分离**，避免源文件与成品混在一起。

除此之外，Web 端本身是一个可用的**书库 + 阅读器**：管理成品（书架 / 元数据 / 统计 / 工具），
直接在浏览器里读 ePub、PDF 与漫画，并把书库喂给第三方阅读器（OPDS / Komga / KOReader）。

## 功能

- 多正则 + 缩进降级 + **AI 兜底**的章节识别（`-t` 可调试正则；配置 `llm.api_key` 后疑难章节自动调 LLM）
- 编码多层 fallback（utf-8-sig / utf-8 / gb18030 / gbk / big5）
- 文本精排、繁体转简体（opencc）
- 三级元数据（文件名 / 正文头部 / 在线补全）
- 基于 ebooklib 的 EPUB 组装（HTML 净化 + 封面）
- **可插拔书源适配器**：已含 Gutenberg 公版源，并附 `generic.py` 扩展模板
- **下载加固**：类浏览器标头伪造、Cookie 持久化（LWPCookieJar 落盘）、429 退避重试、域名替换、**原生 JS eval**（Node 执行站点解密脚本）
- **增量更新**：为下载得到的 txt 写 sidecar，日后只爬取新增章节再重转
- **内容预览 API**：`/content?url=...` 即时抓取清洗（不落盘即可完美预览），`/supported` 判断 URL 归属
- **输入目录自动监听**：扔进 `input` 的文件自动处理——`txt` 转 EPUB，非 `txt` 原样导出到 `output`
- **活动日志**：每一次「转换 / 添加」都记录时间、文件名、操作、成功或失败（Web 可查、可下载、CLI 可看）
- FastAPI 服务：上传即转、按路径转换、列出文件、下载成品、搜索、下载
- **书库与阅读**：书架三视图 / 真实封面、ePub+PDF+漫画阅读器、进度与状态追踪、批注与收藏夹、数据统计、智能书架、九个工具 —— 见下两节

## 书库与阅读

转换与下载之外，Web 端就是一个书库与阅读器。数据**全部来自 `output/`**（没有额外的库实体），
所以「把文件放进导出目录」就等于入库。

- **书架**：三视图（网格 / 列表 / 表格）、真实内嵌封面（显示模式 / 书脊 / 阴影 / 卡片叠加层）、搜索、
  排序、按系列折叠、多选批量（标记状态 / 评分 / 加入收藏夹）
- **元数据**：单本「编辑元数据」直接改写 EPUB 内的 OPF（书名 / 作者 / 系列 / 系列序号 / 语言 / 出版社 /
  标签 / ISBN），改完立即生效；系列与作者可成批改名、合并
- **阅读器**：ePub（排版增强：翻页 / 纵向 / 横向、分栏、字距词距、两端对齐、多档阅读主题）、
  PDF（pdf.js 懒加载）、漫画（CBZ）。**刻意不支持 CBR**：RAR 需要额外的系统级解压依赖，
  与其放一本永远打不开的书进书架，不如让它不出现在书目里
- **阅读追踪**：进度与位置（位置精确到章节 / 页码）、阅读状态（未读 / 在读 / 读完 / 搁置 / 弃读）、
  起止日期、1–5 星评分与书评、Reading Log（按书的时间流水）、手工补录、阅读时长统计
- **批注 / 收藏夹 / 成就 / 通知**：批注按书聚合与检索；收藏夹跨书归类
- **数据统计**：规模卡片、入库节奏与阅读节奏（窗口 7 / 28 / 90 天可切换）、Top 作者 / 系列 / 出版社 / 题材、
  出版年代分布、平均阅读进度、**书库体检**（缺作者 / 缺语言 / 无封面 / 零字节 / 解析失败）
- **智能书架**：自定义规则书架（字段 + 操作 + 值，全部满足 / 任一满足），规则存服务端、命中数实时预览
- **元数据抓取**：内置 OpenLibrary 与 Google Books（**均无需 API Key**），按书名 + 作者匹配补全封面 / 出版社 /
  语言 / 简介 / 题材；字段级写入策略（默认**只补空**）、置信度阈值、题材黑名单、自定义元数据；
  新书入库可选自动抓取。一律**先预览、再应用**，写入前不会动任何文件
- **工具**（9 个标签）：实体管理、批量重命名、重复书籍（同作者 + 书名相似度阈值可调）、缺失资源、
  书源管理、导出目录、本地转换、转换日志、OPDS 订阅。
  会改磁盘的三个工具一律**先预览、再应用**，且「删除」是移入回收站（`CONFIG_DIR/cache/recycle`），
  **从不直接删文件**

## 多端互通

让别的阅读器用上这个书库，或与外部的阅读服务对接 —— 都在「设置 → 设备」里，**默认关闭**。

| 方向 | 能力 | 要点 |
|---|---|---|
| 对外 | **OPDS 目录** | 只读 Atom feed：全部 / 最近 / 按作者 / 按系列 / 按标签 / 搜索 / 单书 / 封面 / 下载。用 HTTP Basic + 应用账号；`/opds` 是独立前缀，不走 `/api` 的 Bearer 中间件（客户端只会发 Basic） |
| 对外 | **Komga 库布局** | 有系列的书按 `系列名/系列名 #N.ext` 落盘（Komga 只认一层系列目录、不递归），并可从文件名或 OPF 推断系列；「整理既有库」把已平铺的书收进系列目录，**会改名时自动迁移阅读进度 / 批注 / 评分 / 收藏** |
| 对接 | **KOReader 进度互通** | 实现 kosync 协议（`users/auth`、`users/create`、`syncs/progress` 的 GET/PUT）：按 partialMD5 索引文档，并在 XPointer / 页码与本项目的位置之间换算 |
| 对接 | **OPDS 订阅** | 工具页里可订阅外部 OPDS 源（Komga / Calibre-Web 等），浏览后直接下载入库 |
| 对接 | **Hardcover / Readwise / StoryGraph** | 凭据存储 + **真实连通性验证**（能验证的才放验证按钮；StoryGraph 无公开 API，如实标注不可验证） |
| 双向 | **Komga 兼容服务端** | 本应用可直接**冒充 Komga 服务端**：第三方 Komga 客户端（Mihon / Panels / 官方 App）把地址填成 NovelForge 即可浏览书库、读漫画与 PDF（服务端逐页渲染）、下载 EPUB、双向同步阅读进度。支持 Basic / `X-API-Key` / 会话三种认证与 Komga 的分页壳 |

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
| `*.txt` | 走转换管线生成 EPUB，落到 output | `转换` |
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
  copy_non_txt: true      # 非 txt 原样导出到 output
  process_existing: true  # 启动时处理 input 里已有的存量文件
  max_retries: 3          # 单文件失败重试上限
  ignore: [".*", "*.tmp", "*.part", "*.crdownload", "*.meta.json", "*.log"]
logging:
  dir: ""                 # 留空则用 LOG_DIR
  max_entries: 2000       # 接口读取的内存缓冲条数
```

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

# 监听 input 目录：txt 自动转 EPUB，非 txt 自动导出（前台常驻，Ctrl+C 停止）
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
因此在 NAS 上**只需要一个 `docker-compose.yml` 文件**，一条命令即可运行：

```bash
# 在 NAS 上建个目录，只放 docker-compose.yml（整份文件已含镜像地址与挂载配置）
mkdir -p novel_dl_convert && cd novel_dl_convert
# 把本仓库的 docker-compose.yml 下载/拷到这个目录

# 启动：自动从 ghcr.io 拉取「已含源码+依赖」的镜像并运行（无需 git / 无需 build / 无运行时 clone）
docker compose up -d
```

> 首次会下载镜像（含 Python 依赖，约几百 MB，视网速 1~3 分钟，仅此一次，之后本地有缓存）；
> 镜像下载完成即**秒级启动**，彻底告别之前「启动时 git clone 源码」的 2~4 分钟等待。
> 之后日常重启 / NAS 重启恢复都是秒级。

> 数据目录（`input/` `output/` `config/` `cookies/` `cache/`）首次启动由 Docker 自动创建，无需手动 `mkdir`；
> 配置放 `./config/config.yaml`（留空则应用回退到内置默认值）。

- 访问 http://<NAS-IP>:8000 上传 txt 转 EPUB
- **文件直接丢进 `./input` 即可**：txt 自动转 EPUB，其它文件自动导出到 `./output`，全程记日志（网页「转换日志」页可看）
- **输入放 `./input`，成品落 `./output`**，互不影响
- 在线书源：`POST /search`、`POST /download`；内容预览：`GET /content?url=`、`GET /supported?url=`
- Synology Container Manager / QNAP Container Station：直接导入本目录的 `docker-compose.yml` 即可

### 更新代码

仓库推新后，GitHub Actions 会自动重建并发布新镜像。NAS 上拉取最新镜像即可：

```bash
docker compose pull && docker compose up -d
```

### 为什么既没有本地 build、也没有运行时 clone

之前两种方案都有等待：免 build 方案在**容器启动时** `git clone` 源码（2~4 分钟）；
本地 build 方案则要求 NAS 能 build 镜像（部署平台常拿不到 Dockerfile）。
现改为 **CI 构建并把「源码 + 依赖」烤进 `ghcr.io` 公开镜像**：NAS 只是下载一个现成镜像，
既不 build 也不 clone，部署后等待时间降到最低、更新也只需 `docker compose pull`。

### 目录结构

```
novel_dl_convert/
  docker-compose.yml   真实版：拉 ghcr 预构建镜像，input / output / config / cookies / cache / data 六处挂载
  docker-compose.test.yml  测试版：本地 build + 挂源码、端口 8993、数据隔离到 ./data-test
  start.sh             启动脚本（依赖已内置，自检后 exec uvicorn，秒级拉起）
  Dockerfile           多阶段构建：builder(venv 依赖) + node(仅取二进制) + frontend(Vue 构建) + runtime(python-slim)
  config.yaml          转换行为配置
  .env.example         环境变量示例
  novelforge/          Python 包
    cli.py             命令行入口（convert / search / download / update / watch / scan / logs）
    server.py          FastAPI 服务（NAS 部署 + 内容预览 API）
    config.py          目录与配置解析
    core/              预处理 / 分章 / AI 分章 / 网络加固 / 元数据 / EPUB 组装 / 管线
                       + activity_log.py（活动日志）· watcher.py（输入目录监听）
                       + library.py（扫描导出目录，聚合书目 / 作者 / 系列 / 重复 / 缺失）
                       + fileops.py（安全改名与移动、冲突检测、回收目录；不做 unlink）
                       + db.py（SQLite：进度 / 批注 / 评分 / 收藏 / 状态 / 偏好 / 凭据）
                       + stats.py（统计聚合）· achievements.py · recommend.py（相似书）
                       + auth.py（单用户轻登录）· comics.py（CBZ 解包）· fonts.py（字体管理）
                       + ebook_convert.py（Calibre 派生兜底，缺失时降级 EPUB）
                       + opds.py（对外 OPDS 目录）· opds_client.py（订阅外部 OPDS 源）
                       + komga.py（Komga 库布局与系列推断）· koreader.py（kosync 进度互通）
                       + integrations.py（Hardcover / Readwise / StoryGraph 凭据与验证）
    sources/           书源适配器（gutenberg 公版 / generic 模板 / rules 数据驱动 / store 用户源管理 / manager）
    static/v2/          前端构建产物（Vue + Tailwind，由 frontend/ 构建，不入库）
  frontend/           前端工程（Vue 3 SFC + TypeScript + Vite 8 + Tailwind v4 + Pinia）
    src/views/          仪表盘 / 探索发现 / 任务中心 / 数据统计 / 阅读记录 / 通知 / 成就 /
                        书架 / 单书详情 / 作者 / 系列 / 批注 / 收藏夹 / 智能书架
                        reader/    阅读器（ePub / PDF / 漫画）
                        settings/  设置页（注册表生成；48 页分 6 组）
                        tools/     工具页外壳（ToolsLayout，顶部标签栏）+ 9 个工具子页
    src/components/     外壳（侧栏 / 顶栏 / 任务抽屉）+ UI 组件 + 仪表盘部件 + 阅读器组件
    src/stores/         Pinia：theme / nav / library / tasks / dashboard / ui / auth /
                        collections / fonts / stats / shelfPrefs / coverPrefs / prefSync
    src/lib/            阅读与外貌偏好（readerPrefs / pdfPrefs / comicPrefs）、
                        智能书架求值（smartScope）、偏好同步桥（prefsBridge / prefsPayload）
    src/assets/theme/   照搬 BookOrbit 的 tokens / accents / radius / bridge / cover-effects
```

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
    写在文件名里，因此「改名」实质是改文件名。
  - **批量重命名**：按规则（`{title}` / `{author}` / `{series}` / `{index}` / `{ext}`）生成
    「旧名 → 新名」对照表，冲突行置灰且不可提交，确认后才落盘。
  - **重复书籍**：同作者 + **书名相似度阈值可调**（默认 85%，与 Calibre 的 similar-title 口径一致），
    相似的书聚成一组，每组选一项保留、其余移入回收目录。
  - **缺失资源**：列出零字节 / 无法解析 / 缺封面的成品文件，并逐条说明原因。
  - **书源管理**：查看已注册书源，粘贴 JSON 或上传文件批量添加，可删除用户源。
  - **导出目录**：列出 EPUB 成品与下载留档的 txt，提供下载。
  - **本地转换**：拖拽上传本地 txt 直接转 EPUB、按路径转换、监听目录启停与立即扫描。
  - **转换日志**：全部活动日志（时间 / 文件名 / 操作 / 成败，支持过滤、下载、清空）。
  - **OPDS 订阅**：添加外部 OPDS 目录（Komga / Calibre-Web 等），逐级浏览并直接下载入库。
- **书架**：三视图（网格 / 列表 / 表格）+ 搜索 / 排序 / 系列折叠 / 多选批量；书卡用真实内嵌封面。
- **单书详情**：概览 / 目录 / 文件 / 批注 / 阅读状态（评分与书评、相似书推荐）等标签，
  并可「编辑元数据」直接改写 EPUB 内的 OPF。
- **阅读器**：ePub（排版增强）/ PDF / 漫画三种；阅读进度、状态与时长自动回写。
- **设置**：47 个页面分 6 组 —— 你 / 书库 / **设备**（OPDS、Komga、KOReader、字体、偏好与同步）/
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

- 覆盖两层：**核心纯逻辑**（按格式迁移与回滚、入库归库判决、库类型能力矩阵、元数据分层、路径安全边界）
  + **接口冒烟**（鉴权、书库 CRUD 边界、迁移全链路、元数据覆盖与恢复、能力清单、系列按媒体分组）。
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

## 扩展一个新书源（代码方式）

复制 `novelforge/sources/generic.py` 为 `my_site.py`，改 `name` / `domains`，实现 `search()` 与
`fetch_book()`；若有字体加密 / 内容混淆，在 `decryption_js()` 返回解密片段，`render()` 会自动调用
Node 执行。加 `@register` 即可被 `/search`、`/download`、`/supported` 自动识别，零改核心。

## 合规说明

下载功能默认关闭，仅对接公版书源（Project Gutenberg）。使用其他书源请遵守目标站点
robots.txt 与服务条款，仅限合法用途。
