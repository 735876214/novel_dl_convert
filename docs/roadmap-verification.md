# 路线图完成度核查（2026-09-17）

> **⏳ 时效标注（第 29 期，2026-09-20）**：本文件正文是**第 0–4 期核查的当时快照**（2026-09-17）。
> 之后只在个别行就地追加了后来各期的更正（下方可见第 11/14/15/16/20 期字样），
> 但**主体结论与数字都停在第 4 期末**，没有随第 5–29 期重取。
> 因此 —— **第 5 期起的完成度不要引用本文件**：以 `docs/bookorbit-capability-gap.md`（逐域现状 +
> 复核头，第 29 期已逐行核验到底）与 `docs/roadmap-gaps-remaining.md`（活文档，逐项勾选）为准。
> 本文仍有效的部分：第 0–4 期那 27 项的**核查方法与实证要点** —— 它记的是「当时怎么证的」，
> 这部分不随代码演进而过期。

## 核查方法

**不采信文档里的状态标记**（那些也是本项目自己写的），每一项都要求两类实证：

1. **源码特征**：模块/表/路由/页面文件确实存在，且含关键实现特征（不是空壳）
2. **运行实例响应**：对隔离测试实例（`127.0.0.1:8791`，目录 `/tmp/nf-test`）发真实 HTTP 请求，
   参数化接口还要验证**参数真的生效**（如 `?days=7` 回传 `window=7`）

共 27 个核查项，覆盖第 0–4 期全部条目。

## 结果：27/27 通过

| 期 | 条目 | 实证要点 |
|---|---|---|
| 0 | 审计日志 | `activity_log` 写 actor；审计页存在；`/api/logs` 支持 actor 过滤 |
| 0 | 收书目录 | BookDock 页；`/api/watcher`；与 `INPUT_DIR` 关联 |
| 1 | 通知已读态 | `notifications_read` 表；`POST /api/notifications/read`；通知页 + 顶栏浮层 |
| 1 | 任务持久化 | `tasks` 表；`server.py` 已无进程内 `TASKS` dict；前端无种子数据 |
| 1 | 维护与清理 | `/api/maintenance`（含 orphans）；维护页 |
| 1 | 上传大小上限 | `upload.max_bytes` 配置 + 接口回传 + 页面可改 |
| 1 | ~~Requests 骨架~~ | **已于 2026-09-18 撤销**：该能力决策不做，`/api/requests/config` 与骨架页均已从代码删除 —— 本行不再可复现 |
| 1 | 成就体系 | `core/achievements.py`；`user_achievements` 表；接口 + 页面 |
| 2 | 真实封面 | `/api/books/{bid}/cover`；BookCover 组件；封面设置（模式/书脊/阴影/叠加层） |
| 2 | 书架三视图等 | 三视图 + 多选批量 + `POST /api/books/batch` + `/api/libraries` 筛选 |
| 2 | 书卡信息 + 系列序号 | `lib/bookInfo.ts`；`library.py` 解析 `series_index` |
| 2 | Edit Metadata | `POST /api/books/{bid}/metadata` + 详情页标签 |
| 2 | 阅读状态/书评/相似书/Reading Log | 状态、评分书评、相似书、全局 Reading Log、`reading_sessions`（时长/补录） |
| 2 | 统计增强 | `days`/`top` 参数**实测生效**；publishers/genres/years/avg_progress/integrity 齐全 |
| 2 | 导出元数据 | `/api/books/export` + 书架入口 |
| 2 | 自定义智能书架 | `/api/smart-scopes`；`lib/smartScope.ts` 求值器；管理页 |
| 2 | 查重阈值 | `?threshold=70` **实测回传 70**；返回 `similarity`；页面有阈值控件 |
| 3 | 排版增强 | `readerPrefs` 含分栏/页展/字距/两端对齐等；阅读器页 |
| 3 | PDF 阅读器 | PdfReader 组件 + `pdfPrefs` + pdf.js 依赖 + 设置页 |
| 3 | 漫画阅读器 | ComicReader + `comicPrefs` + 页清单/取图接口 + 设置页（**另造 CBZ 实测**，见下） |
| 3 | 字体管理 | `core/fonts.py`；`/api/fonts`；阅读器字体页 + 服务端字体页 |
| 3 | 偏好同步 | `/api/prefs/profiles` + `/api/prefs/devices`；`prefSync` store；`prefsBridge` 防回环 |
| 4 | OPDS 订阅源 | `core/opds.py`；`/opds`（关闭态 404）；设置页 |
| 4 | KOReader 互通 | `core/koreader.py`；healthcheck 实测返回 `{"state":"OK"}`；syncs 路由；设置页 |
| 4 | Komga 集成 | `core/komga.py` + `core/opds_client.py`（⚠️ **订阅外部 OPDS 源于第 16 期删除**）；布局预览接口；~~订阅页~~ + 设置页 |
| 4 | 外部服务集成 | `core/integrations.py`；三家服务齐全；三页共用组件（props 传 service） |
| 4 | Kobo / 邮件投递 | 文档已划掉并写明理由；设置页保持 `placeholder`（不假装可用） |

### 两处首轮 FAIL 的甄别（均为**检查方式**问题，非实现缺失）

1. **「前端无演示种子数据」**：首轮正则命中了 `data/tasks.ts` 里**说明「旧版曾有」的注释**。
   逐行剥离注释后复核：代码里已无 `TASKS` 常量、无演示书名；`stores/tasks.ts` 也无假推进 ticker。
2. **「漫画页清单接口」**：测试库里**没有 CBZ 样本**，不是接口缺失。
   补造一个含 3 张 PNG + macOS 垃圾条目（`__MACOSX/`、`.DS_Store`）的 CBZ 后实测：
   页数 = **3**（垃圾条目被正确过滤）、页序自然序、单页取图 `image/png` 且**字节与源一致**、越界返回 404。

## 文档数字核对（连自己写进文档的数字也一并核实）

| 说法 | 实测 | 结论 |
|---|---|---|
| 设置页 48 个 | `settingsNav.ts` 中 `p('` 计数 = 48 | ✓（**现值 38**：第 11 期删求书页、第 20 期删 9 个已决策不做的对照页） |
| 点缀色 65 档 | `data/accents.ts` 的 `ACCENTS` = 65（页面按 `ACCENTS.length` 显示） | ✓ |
| 工具 9 标签 | `ToolsLayout` 的 `routeName: 'tools-*'` = 9 | ✓ |
| 主导航 8 项 | `NAV_GROUPS` 首组条目 = 8 | ✓ |
| 后端 146 条路由 | `^@app\.(get\|post\|put\|delete)` = 146 | ✓ |

> ⚠️ 上表是**当时（第 4 期末）的快照**：后续各期新增了路由与设置页，因此「设置页 48 个 / 后端 146 条路由」
> **不再等于现值**。其中「Requests 骨架」已随 C1 决策不做而删除，该行不可复现。
>
> **第 29 期重取（2026-09-20，附命令以便复现）**：
>
> | 量 | 命令 | 实测 |
> | --- | --- | --- |
> | 设置页 | `grep -cE "p\('" frontend/src/data/settingsNav.ts` | **48** |
> | 后端路由 | `grep -cE '^@app\.(get\|post\|put\|delete\|patch)\(' novelforge/server.py` | **260** |
> | 工具页签 | `grep -roE "routeName: 'tools-[a-z-]+'" frontend/src \| wc -l` | **8**（第 28 期删「批量重命名」后） |
>
> ⚠️ 注意本文件自身遗留的一处**内部矛盾**（本轮发现，一并说明以免被继续引用）：
> 上表「设置页 48 个」那行的括注写「**现值 38**」，而紧随其后的这段原文写「**现值 47**」——
> 同一文件给出两个互相打架的「现值」，且**两个都不是今天的值**（今天按上表命令是 48）。
> 这不是笔误可解释的：它们各自记的是**写下它那一刻**的值。这类数字一旦脱离日期就没有意义，
> 故本轮起**一律写成「日期 + 命令 + 实测」三元组**，不再写光秃秃的「现值」。

## 明确**不属于**完成项的

- ~~**后期（未定期）**：Requests 的完整功能（插件式索引器 / 插件市场 / Torznab-Newznab / 下载客户端与凭据加密 / 下载后自动化）~~
  **已于 2026-09-18 决策不做**：本轮未启动；第 1 期曾交付的骨架（`/api/requests/config` + 骨架页）也已从代码中删除。
- **明确不做**：Kobo 同步、邮件投递（2026-09-17 用户决定，文档已划掉）。

## 各功能页里如实标注的「未支持」（后续可选方向，非缺陷）

| 功能 | 未支持项 |
|---|---|
| Komga | 接入侧：从 Komga 拉书目 / 下载入库、双向进度同步（**服务端侧已于第 15 期补齐**：按库浏览、系列级已读、CBR 类型、有声书库不进 Komga） |
| KOReader | 多设备管理、注解与书签同步（kosync 协议本身只同步进度） |
| 外部服务 | 同步任务（推送状态/书评/书摘，需先做书籍匹配 ISBN/标题） |
| OPDS 服务 | 独立账号体系（现用应用账号）—— ~~按书库分别暴露~~ **已于第 14 期实现** |
| 阅读器 | eBook 排版已实现 13 项（阅读模式 / 13 档主题 / 字体 / 字号 / 行高 / 内容宽度 / 段落间距 / 首行缩进 / 字距 / 词距 / 分栏 / 两端对齐 / 断词）；未支持：新书套用设置、固定版式页宽、字重样式、文本区左右内边距；有声书播放器（§11 不建议做）、CBR（需 RAR 系统依赖） |
| 维护页 | IMPORT（从其它书库工具一次性导入）/ RECOMMENDATIONS（刷新推荐索引）/ UPDATES（查 GitHub 新版本）在容器部署口径下未支持；ACHIEVEMENTS 的 Backfill 已接入维护页 |
| 外观（Icons / Layout / Behavior） | 未实现，仅作上游结构对照（图标风格 / 布局密度 / 浏览行为不暴露为设置） |

## 结论

**第 0–4 期路线图 27 项全部完成，且每一项都有代码与运行实例层面的实证。**
没有发现「文档说完成但实际缺失」的情况；两处首轮 FAIL 经复核均为核查脚本的判据问题。
