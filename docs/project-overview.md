# 项目整体说明（project-overview）

> 本文回答「这是个什么东西、能做什么、怎么部署、和别的工具什么关系」。
> 安装/配置的**完整**细节见 `README.md`；架构见 `docs/architecture.md`；用哪个功能怎么点见 `docs/user-guide.md`。

## 1. 一句话

**NovelForge**（仓库名 `novel_dl_convert`）是一个自托管的 **TXT/电子书 → 书库 + 在线阅读器**：
把散落在 NAS 上的 txt / epub / pdf / cbz / 音频收进书库，在浏览器里整洁地读，并把书库喂给第三方阅读器。

- **形态**：FastAPI 后端（单进程、单用户）+ Vue 3 SPA 前端；Docker / 裸机都能跑。
- **取向**：NAS 优先、**零外部请求**（字体/图标/依赖全自托管）、**源文件绝对只读**
  （后台流程不写不改；用户显式「删书 / 移除书库」时只把文件**移入回收站**，从不 unlink）。
- **不做的**：多用户与权限、国际化、邮件投递、Kobo 同步、在线元数据的插件市场。

## 2. 它解决的三件事

| # | 场景 | 能力 |
|---|---|---|
| 1 | **收书与整理** | 输入目录监听 → 原样入库；分章（正则 + 缩进降级 + AI 兜底，置信判据 = 边界密度**或**条数≥3，长章书不误判为无章节）；编码探测（按字符分布择优，utf-8 自证按**前缀**判 —— 采样按字节截断，尾部被切断不算失败）；繁体转简；元数据三级（文件名 / 正文头 / 在线）；刮削出版（在**副本**上写元数据，源文件不动） |
| 2 | **读与管理** | 书架三视图 + 真实封面；ePub / PDF / 漫画 / 有声书 / **合集（逐话）** 阅读器；进度、状态、评分、书评、阅读时长；批注、书签、收藏夹、成就、通知；统计与图表；智能书架 |
| 3 | **多端互通** | OPDS 目录（对外只读）；Komga 兼容服务端（**本应用可冒充 Komga**）；KOReader kosync 进度互通；外部账号凭据与连通性验证 |

## 3. 支持的内容形态

| 形态 | 说明 |
|---|---|
| 电子书 | EPUB（全解析）、PDF、TXT（**只入库不转换**，阅读时按需生成派生 EPUB）、FB2 / MOBI / AZW3 等（入库即可，元数据不支持解析） |
| 漫画 | CBZ / CBR（CBR 需容器内 `libarchive-tools` 提供 `bsdtar`）；**漫画库里的 PDF 也可按漫画形态读**（pdf.js 逐页渲染成图） |
| 有声书 | 单文件 或 **一个目录=一本书（一章一文件）**；播放器含倍速/跳转/睡眠定时/轨列表；跨轨与跨册续接 |
| 合集（序号单元） | 漫画库 / 有声书库里的 `《书名（1-43话）》/第1卷/第1话.pdf` 这类目录树：**一棵树 = 一本书**，逐话连续读（话目录 / 上下一话 / 读完自动续）；序号写法不限（`第1话` / `第二话` / `第03话` / `4 第4话` / `01`），书名自动剥掉「（1-43话）」这类范围备注 |

> 「一本书」的判据是**条目**：普通文件、平铺音频目录、**序号单元树**、或目录型条目。目录型条目同样参与出版（副本是真目录 + 内部逐文件硬链接）。
> **序号单元合并只在漫画库与有声书库生效**（电子书库 / 混合库与以前逐字相同）；看着不像连载的目录（一个文件夹里几本独立漫画）**不合并**。

## 4. 与同类工具的关系（设计取舍）

- 融合了 `Fanqie-novel-Downloader` / `kaf-cli` / `txt2epub` / `denovel` 的思路：**下载 → 分章 → 精排 → EPUB**。
- 与 Calibre 的差异：**绝不改写源文件**；所有元数据只落应用数据库。代价是用 SMB 直读目录时看不到这些元数据，而经 Komga/OPDS/本应用访问则全部可见。
- 与 Komga 的差异：本应用**同时**是 Komga 客户端可用的服务端（兼容接口），也可把库整理成 Komga 的目录布局。
- 与「在线书库」的差异：一切离线优先；在线能力（元数据抓取、书源）都是**可选增强**，失败/关闭不影响主流程。

## 5. 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.10+ / FastAPI / uvicorn；标准库为主，`ebooklib` / `rarfile` / `numpy` / `beautifulsoup4` 等按需；**无 ORM**（`sqlcompat` 手写 SQL 适配 SQLite / PostgreSQL） |
| 数据 | SQLite（默认）或 PostgreSQL；Redis 可选读缓存（可缺席、挂掉自动降级） |
| 前端 | Vue 3 SFC + TypeScript + Vite + Tailwind CSS v4 + Pinia + vue-router（**hash**） |
| 图表 | ECharts（`vue-echarts`），经 `lib/charts.ts` 单一入口按需注册 |
| 测试 | pytest（后端，**离线**）+ Vitest（前端；脚本名刻意叫 `test:unit`） |
| 部署 | Docker 多阶段构建；镜像由 GitHub Actions 发布到 `ghcr.io`；NAS 只需一个 `docker-compose.yml` |

## 6. 部署形态

| 方式 | 说明 | 端口 |
|---|---|---|
| **NAS 生产** | 只用 `docker-compose.yml`（配置全写在文件里，**不读 `.env`**）；拉 ghcr 预构建镜像（源码+依赖已烤进镜像，无需 build/clone） | `8992:8000` |
| 本地测试 compose | `docker-compose.test.yml`：本地 build + 挂源码 + 数据隔离到 `./data-test` | `8993` |
| 离线叠加件 | `docker-compose.offline.yml`：**必须 `-f` 显式叠加**（⚠️ 千万别改名成 `docker-compose.override.yml` —— Compose 会自动合并并静默改端口/拉取策略） | 同生产 |
| 裸机 / 开发 | `.venv` + `uvicorn novelforge.server:app --port <自定义>`；`frontend && npm run dev` 走 Vite HMR | 自定 |

目录约定（输入 / 成品 / 配置 / 缓存 / 数据库 / 字体 / 书源 / 备份）见 `README.md` 的「目录约定」表；
环境变量：`INPUT_DIR` `OUTPUT_DIR` `CONFIG_DIR` `COOKIE_DIR` `CACHE_DIR` `LOG_DIR` `DATA_DIR` `SOURCES_DIR` `FONTS_DIR` `BACKUP_DIR`
`LIBRARY_SOURCE_DIR`（或多数根 `LIBRARY_SOURCE_DIRS1..N`）`AUTO_WATCH` `AUTH_USER` `AUTH_PIN` `AUTH_SECRET`
`NOVELFORGE_DB` `NOVELFORGE_PG_DSN` `NOVELFORGE_REDIS_URL`。

## 7. 规模与现状（便于判断「这项目多大」）

| 维度 | 当前值 |
|---|---|
| 后端测试 | **1263 例（1251 passed / 12 skipped / 0 failed）**（离线全量，约 2–3 分钟） |
| 前端测试 | **441 例 / 38 文件**（Vitest） |
| 后端模块 | `novelforge/core/` **54 个模块** |
| 前端 | 约 **172 个 .vue**（`components/` 109 + `views/` 63）+ **46 个 `lib`** + **21 个 `store` 文件**；**36 个设置页**（6 组）、**30 张统计图表**、**9 个工具标签** |
| 元数据提供商 | **14 家**（5 家免密钥即用 / 3 家填密钥即用 / 6 家页面抓取型并标注「易失效」） |
| 版本 | `0.6.0`（唯一真值源 `server.APP_VERSION`，只由 `GET /health` 下发） |
| 期号 | 第 73 期（2026-09-29）；逐期记录见 `docs/roadmap-gaps-remaining.md` |

## 8. 文档地图

| 想了解 | 看 |
|---|---|
| 怎么装、怎么配、CLI 怎么用 | `README.md` |
| AI 接手要注意什么 | `AGENTS.md` |
| 现在做什么、优先级 | `TODO.md` |
| 视觉规则 | `DESIGN.md` |
| 架构与数据流 | `docs/architecture.md` |
| 功能怎么用（使用者视角） | `docs/user-guide.md` |
| 怎么开发、怎么回归 | `docs/development.md` |
| 组件/工具模块 API | `docs/component-api.md` |
| 与上游 BookOrbit 的差距 | `docs/bookorbit-capability-gap.md`、`docs/bookorbit-module-inventory.md` |
