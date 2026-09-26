# BookOrbit 上游模块级能力对照清单（第 33 期取证）

> **来源**：只读镜像 `%TEMP%\bookorbit-ref`，`main` @ `c292d6cc`（v2.10.0，与上游 `origin/main` 一致）。
> **方法（零网络为主）**：`git ls-tree` 从 tree 对象直接列清单（不下载 blob），按 `*.controller.ts` /
> `*.service.ts` / `*.repository.ts` 的命名推断职责；**只对「归不进既有十二域」的候选按需拉 1–3 个关键文件**
> （走一次性代理 `git -c http.proxy=… cat-file -p`）确认职责。**全程只读，不复制上游代码**。
> **为什么要做这件事**：`docs/bookorbit-capability-gap.md` 是按**协议面**（`packages/types`）与**页面**
> 做出来的对照，**从未按上游代码模块系统对照过**。一旦缺口是「整块模块从未进过视野」，
> 按页面对照永远发现不了 —— 本文件就是为堵这个口子。
> **本期只产出清单，不实现清单里的任何项**（供第 34 期排期）。
> **第 34 期更新（2026-09-21）**：§4.1「值得做」的 4 项**已全部落地**（逐项锚点见 §4.1 表）；
> §4.2「有价值但不做」8 项本轮**未改判**（仍不做）。
> **第 35 期更新（2026-09-21）**：§4.2 里有 **3 项由用户改判为做并已落地** —— `book-metadata-lock`（字段级
> 元数据锁）、`custom-metadata`（自定义字段 schema）、`recommendation`（相似书加权打分）；
> 三行**保留原位**以留档原始判断，行内以 ⚠️ 标注改判与落地锚点 ⇒ §4.2 剩余真·不做 **5 项**。
> 其中 `custom-metadata` 原判理由里「要动 12 字段的 metascore 权重表」一句**经核为误**，已就地订正。
> **第 36 期更新（2026-09-21）**：§4.2 里的 `book-move`（跨库移动）**由用户改判为做并已落地** ——
> 该行**保留原位**以留档原始判断（原判「做全了是独立一期」正是本期的立项理由），行内以 ⚠️ 标注落地锚点
> ⇒ §4.2 剩余真·不做 **4 项**。另有一条**刻意差异**如实记在该行内：不引入 SSE，逐本进度走既有的
> 「SQLite 任务行 + 前端轮询」范式。
> **第 42 期更新（2026-09-23）**：⚠️ **上游复核：`refs/heads/main` 仍为 `c292d6cc`**（与第 33 期取证时同一
> commit，无新提交、无新 tag）⇒ 「上游出了新版本、有新模块」的前提**不成立**。本期转为**同一版本上的深挖**：
> ① **刷新 §2 逐行判定**（多条「漏项候选」其实已在第 34–36 期落地，表未同步）；② **订正 3 处文档错误**
> （`health` 路由 / `kobo`「可用子集」/ `metadata`「对等 6 类」）；③ 新增 **第六节**「已覆盖模块的部分缺口」。
> **本期零运行时改动**（纯取证/文档）。

---

## 0. 三个坐标系（读这张表前必须分清）

| 轴 | 数量 | 真相源 | 说明 |
| --- | --- | --- | --- |
| **模块轴** | **67** | `server/src/modules/` 的直接子目录 | 后端能力块。**其中 1 个不是能力**（见下） |
| **页面轴** | **33** | `client/src/features/` 的直接子目录 | 前端页面块 |
| **能力轴** | 12 域 | `docs/bookorbit-capability-gap.md` §1–§12 | 既有对照表用的轴 |

三条轴**不是一一对应**：一个能力可能横跨多个模块（如「书籍详情」= `book` + `metadata` + `metadata-score`
+ `cover` + `user-book-status`），一个模块也可能横跨多个域。本文件做的是**把模块轴映射到能力轴**，
因此「一个模块归一个主域」是**为了可读性的近似**，不是上游的真实结构。

**两处必须先说的口径（否则数字对不上）**：

1. **67 里有一个不是能力模块**：`server/src/modules/architecture/` 只有
   `architecture-boundaries.test.ts` 一个文件 —— 它是**架构边界约束测试**，不是能力。
   所以**能力模块实为 66 个**。本文件保留 67 行以对齐目录事实，但该行判定为「非能力」。
2. **不是所有模块都有对外路由**：66 个能力模块里**只有 57 个带 controller**（共 84 个 `*.controller.ts`），
   **9 个模块是纯内部服务、零 HTTP 面**：`book-metadata-lock` / `embedding` / `file-write` / `metadata` /
   `narrator` / `position-converter` / `seed` / `user-book-note` / `user-book-status`。
   ——**这 9 个正是按页面对照最容易整块漏掉的那一类**（页面上看不见它们，它们只出现在别的模块的依赖里）。

---

## 一、结论摘要

计数全部来自第二节的逐行判定（**不是**名称匹配，理由见下面的「一条方法学警告」）：

1. **既有文档已覆盖 51 个**：**已覆盖 40** ＋ **已拍板不做 11**（§0.2 多用户原则 / §13 不建议做 /
   用户 2026-09-20 拍板的三方同步）。
2. **16 个从未进过对照视野**（既没有条目、也没有档位判定）：**漏项候选 13** ＋ `file-write` /
   `migration` / `seed` —— 其中 `migration` 同时也是 13 个漏项候选之一，故 13 ＋ 2 ＝ 15，
   再加 `architecture` 这个非能力项，才凑齐 67 的补集。**计数以第二节的逐行判定为准**。
3. 13 个漏项候选按价值三分类：**值得做 4 / 有价值但不做 8 / 与定位不相容 1（`migration`）**；
   另有首次记录但不属漏项候选的两项 —— `file-write`（与发布三原则不相容）与 `seed`（与定位无关）。
   详见第四节。
4. **一条最重的结论**：`file-write`（94 个文件，上游第二大模块）是**把元数据写回文件本身**
   （EPUB / FB2 / MOBI / PDF / CBZ / 音频六类 writer）。这**与本项目「元数据仅存于服务器数据库、
   绝不写入 OPF」的发布三原则直接冲突** ⇒ 永久不做。此前它从未进过任何对照视野 ——
   这正是「按页面对照」会漏掉的东西。

### ⚠️ 一条方法学警告（本文件实测得出，下次取证必须遵守）

**按模块名 grep 文档，得出的覆盖结论是错的。** 实测：67 个模块名在 `capability-gap.md` 里
**34 个零命中、2 个仅 1 次命中** —— 但其中绝大多数能力**文档里明明写了**，只是写的是中文名或
另一种叫法（`audiobook`→「有声书播放器」、`scanner`→「文件监听 / 扫描」、`app-info`→「版本标识」、
`metadata-score`→「Metadata Score Distribution」…）。

零命中的 34 个里，**真正未被判定的只有 16 个**；也就是说**名称 grep 的假阴性率过半**。

这与 `capability-gap.md:94`（`Show library controls` 原判「无此能力」，实际有库级控制条，
当时也是靠 grep 词表判的）是**同一类错误**。**结论：判一个能力有没有，只能按语义找 + 落到
`文件:行号`，grep 词表只能用来「找到起点」，不能用来「判定不存在」。**

---

## 二、后端模块 67 项逐条对照

**判定列的口径**：

- **已覆盖** —— `capability-gap.md` 的对应域里已有该能力的条目与档位判定（锚点见该文件）。
- **已拍板不做** —— 文档已明确不做（§0.2 多用户原则 / §13 不建议做 / 用户 2026-09-20 拍板的三方同步）。
- **漏项候选** —— 从未进过对照视野，本文件首次记录；按价值见第四节。
- **非能力** —— 目录上有，但不是能力模块。

| # | 模块 | 文件数 | 主域 | 有路由 | 判定 | 依据 / 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `account-activity` | 9 | §1 应用外壳 | ✓ | 已拍板不做 | 超管列出全部账号（活跃/最后登录/供给方式）⇒ 属多用户（§0.2 原则 1） |
| 2 | `achievement` | 27 | §6 统计与成就 | ✓ | 已覆盖 | 第 22 期已实现（单用户口径）；上游 5 分类（`packages/types/src/achievement.ts`） |
| 3 | `annotation` | 31 | §12 批注 | ✓ | 已覆盖 | 含 `device-position-rebuilder`（按设备重建位置）—— 属 §10 设备同步，见第 45 行 |
| 4 | `app-info` | 6 | §1 | ✓ | 已覆盖 | 版本 / 关于；本项目收敛为单一 `APP_VERSION`（第 30 期） |
| 5 | `app-settings` | 23 | §1 | ✓ | 已覆盖 | 含 OIDC provider 管理与 group mapping ⇒ 多用户部分不做 |
| 6 | `architecture` | 1 | — | ✗ | **非能力** | 仅 `architecture-boundaries.test.ts`（架构约束测试） |
| 7 | `audiobook` | 9 | §4 阅读器 | ✓ | 已覆盖 | 第 9 期已落地（`core/audio.py` + `/listen/:id`） |
| 8 | `audit` | 13 | §1 | ✓ | 已拍板不做 | 审计日志（actor / resource / retention）⇒ 多用户（§0.2） |
| 9 | `auth` | 45 | §1 | ✓ | 已拍板不做 | JWT + magic-link + OIDC 全栈 ⇒ 多用户（§0.2 明确点名免密登录与 OIDC） |
| 10 | `authors` | 61 | §11 作者与系列 | ✓ | 已覆盖 | 第 8 / 32 期；含上游 4 个 metadata provider（audnexus / goodreads）——书源侧见 metadata-fetch |
| 11 | `book-dock` | 33 | §10 收书目录 | ✓ | 已覆盖 | 第 30 期（含整页拖拽投递） |
| 12 | `book-duplicates` | 10 | §5 工具 | ✓ | 已覆盖 | 第 28 期（相似度阈值 85%） |
| 13 | `book-metadata-fetch` | 18 | §3 书籍详情 | ✓ | 已覆盖 | 第 30 期「先预览再应用」的手动抓取面板 |
| 14 | `book-metadata-lock` | 8 | §3 | **✗** | **已覆盖**（第 35 期） | **字段级锁定**：⚠️ **第 42 期复核已落地** —— `meta_locks` 表（`novelforge/core/db.py:396`）+ 接口 `POST /api/books/{bid}/metadata/lock`（`novelforge/server.py:1358`）+ 抓取双重挡锁（`novelforge/core/metafetch.py:140/206/334`）；范围 = `fileops.METADATA_FIELDS` 10 字段 + `cover`，**只挡抓取、不挡手工编辑** |
| 15 | `book-move` | 12 | §2 书架 | ✓ | 已覆盖 | **第 36 期已落地**（原为漏项候选）：跨库移动（预检 + 逐本进度 + 目标库相容闸门）；「目标库权限」在单用户下的等价物 = **库类型相容闸门**，原判与落地见 §4.2 该行 |
| 16 | `book-request` | 131 | §9 求书 | ✓ | 已拍板不做 | 第 32 期已决策不做（含 indexers / download-clients / plugins 三大子树） |
| 17 | `book` | 56 | §3 | ✓ | 已覆盖 | 含 `reading-attempt`（重读尝试）⇒ 见第 64 行 `user-book-status` |
| 18 | `bookmark` | 14 | §4 | ✓ | **已覆盖** | **书签**：⚠️ **第 42 期复核已落地** —— `bookmarks` 表（`novelforge/core/db.py:207-219`，`UNIQUE(book_id, anchor)` + 软删/墓碑）+ 全套 CRUD（`:899-1049`）+ 路由（`novelforge/server.py:1963-2037`）+ 前端（`frontend/src/views/ReaderView.vue:516-667`）。**刻意差异**：定位用**章节坐标**（`章序号:章内比例`）**非 CFI** |
| 19 | `browse-counts` | 6 | §1 | ✓ | **已覆盖**（第 34 期） | 侧栏 Browse 徽标三计数（作者 / 系列 / 批注），60 s 缓存：⚠️ **第 42 期复核已落地** —— `novelforge/core/browse_counts.py:25/65`、`GET /api/browse-counts`（`novelforge/server.py:3957`） |
| 20 | `catalog` | 9 | §10 | ✓ | **已覆盖**（第 34 期） | **跨实体搜索**：⚠️ **第 42 期复核已落地为 `/browse` 实体总览，六维度**（作者 / 系列 / 题材 / 出版社 / 语言 / 收藏；`frontend/src/views/BrowseView.vue:51-64`）。**刻意差异**：上游 8 维里的「演播者」本项目无实体故不做、「题材/标签」合并为同一字段只做一维 |
| 21 | `collection` | 13 | §1 | ✓ | 已覆盖 | 收藏夹（含拖拽排序） |
| 22 | `cover` | 22 | §3 | ✓ | 已覆盖 | 4 个封面 provider（audiobookcovers / duckduckgo / itunes）—— 本项目封面抓取已落地 |
| 23 | `custom-icon` | 11 | §1 | ✓ | 已拍板不做 | 图标风格 + 上传 + 排序：`roadmap-gaps-remaining.md:785-787` 已判「成本远超收益」 |
| 24 | `custom-metadata` | 9 | §3 | ✓ | **已覆盖**（第 35 期） | **自定义字段的「定义」**（建字段 / 排序 / 改标签 / 切适用书库 / 归档 / 软删恢复永久删）：⚠️ **第 42 期复核已落地** —— `novelforge/core/customfields.py` + 七条路由（`novelforge/server.py:1410-1522`）+ 两张新表 `custom_field_defs`（`novelforge/core/db.py:462`）/ `book_custom_values`（`novelforge/core/db.py:485`）；同名配置项 `metadata_fetch.custom_fields` 已下线 |
| 25 | `dashboard` | 22 | §6 | ✓ | 已覆盖 | 第 32 期已对齐 12 件部件 |
| 26 | `email` | 79 | §7 通知与更新 | ✓ | **漏项候选** | **邮件分发整块**（书籍附件 / 模板 / 收件人组 / 发送日志 / 加密凭据 / SMTP） |
| 27 | `embedding` | 9 | §6 | ✓ | **已覆盖**（第 54 期） | **语义向量**：⚠️ **第 54 期由用户改判为做并已落地**（原判「向量是元数据特征、非语义 embedding」就此翻转）—— `core/embed.py`（默认 LSA：TF-IDF + 截断 SVD，纯 numpy、离线零下载；可选本地 transformer 模型，用户自备文件于 `CACHE_DIR/embedding-model`、运行时不联网）+ `book_embeddings` 表（float32 BLOB + `model_tag`，进 `REMAP_TABLES`/`ORPHAN_TABLES`）+ `POST /api/embeddings/recompute` + `/similar` 余弦一路优先取向量（缺向量逐对回落词袋）、/similar 出参结构不变 |
| 28 | `entity-manager` | 30 | §5 | ✓ | 已覆盖 | 9 个实体策略（作者 / 题材 / 语言 / 演播者 / 出版社 / 系列 / 标签 / 内联 / 联结） |
| 29 | `file-write` | 94 | §5 | **✗** | **不与本项目定位相容** | **把元数据写回文件本身**（EPUB/FB2/MOBI/PDF/CBZ/音频 6 类 writer）—— 与发布三原则冲突 |
| 30 | `font` | 18 | §1 | ✓ | 已覆盖 | 阅读器自定义字体上传 / 校验 / 元数据解析 |
| 31 | `hardcover` | 32 | 三方同步 | ✓ | 已拍板不做 | 用户 2026-09-20 拍板本轮不做（§13） |
| 32 | `health` | 9 | §1 | ✓ | 已覆盖 | 健康检查：⚠️ **第 42 期订正** —— 本项目路由是 **`GET /health`**（`novelforge/server.py:262`），**没有 `/api/health`**（打它会经鉴权中间件被拦成 401；白名单 `novelforge/server.py` 的 `_auth_middleware` 只含 `/health` + `/api/auth/login` + `/api/logout`）。原记「本项目有 `/api/health`」为笔误 |
| 33 | `kobo` | 67 | §10 | ✓ | **未实现** | ⚠️ **第 42 期订正**（原记「已实现可用子集」**与代码、`capability-gap.md`、`README.md` 三处矛盾**）：Kobo 同步 **2026-09-17 已决策不做**（`README.md:113`、`docs/bookorbit-capability-gap.md:435`、设置页占位 `frontend/src/data/settingsNav.ts:344-363`）。全仓无 `kobo*.py`；`kobo` 只作批注来源枚举（`novelforge/server.py:1959`，实际只写 `web`）与 Komga 占位字段（`novelforge/core/komga_api.py:458` 的 `koboSpan` 恒空） |
| 34 | `koreader` | 62 | §10 | ✓ | 已覆盖 | 本项目已实现 kosync 协议服务端（`settingsNav.ts:397` 有完整口径记录） |
| 35 | `library` | 26 | §2 | ✓ | 已覆盖 | 多库实体 + 定时扫描（第 10 期） |
| 36 | `maintenance` | 11 | §5 | ✓ | 已覆盖 | 缺失资源巡检（含孤儿封面目录） |
| 37 | `metadata-fetch` | 121 | §3 | ✓ | 已覆盖 | 13 个 provider（aladin / amazon / audible / audnexus / comicvine / goodreads / google / hardcover / itunes / kobo / librofm / lubimyczytac / open-library / ranobedb） |
| 38 | `metadata-preferences` | 20 | §3 | ✓ | 已覆盖 | 字段级写入策略 + provider 开关 + provider 链接设置（第 30 期） |
| 39 | `metadata-score` | 9 | §3 | ✓ | 已覆盖 | 第 29 期（`core/metascore.py` 12 字段加权） |
| 40 | `metadata` | 70 | §3 | **✗** | **部分实现** | 提取器 + 解析器（上游 epub / fb2 / mobi / pdf / cbz / 音频 6 类）。⚠️ **第 42 期订正**（原记「本项目 `core/metadata.py` 对等」为**高估**）：`novelforge/core/metadata.py` 实际只做 **ISBN 形状判定**（`:23`）+ **文件名解析**（`:45`）；真解析仅 **EPUB**（`novelforge/core/library.py:879` `probe_epub`，完整 OPF）+ **漫画/音频结构**（`comics.py:156` `probe` 页数封面 / `audio.py:68` `tracks` 轨数）；**MOBI/AZW3/PDF 仅按文件名兜底、FB2 完全不支持**（`library.py:37` 的 `BOOK_EXTS` 不含 `.fb2`） |
| 41 | `migration` | 89 | — | ✓ | **漏项候选** | **从其他系统迁移整块**（Audiobookshelf / Booklore / Calibre-Web-Automated / Grimmory） |
| 42 | `narrator` | 5 | §11 | ✓ | **已覆盖**（第 53 期） | **演播者实体**（规范化 / sort name / 按书替换）—— 零依赖音频标签解析（m4b/mp3/m4a/opus/ogg/flac，提取 ©nrt / NARRATOR / TXXX·演播 / 旁白）落 `books.narrators`；`narrators` 实体表（排序名 `sort_name` / `sort_name_local` 两列分列，镜像 `authors`，无头像 `hasPhoto=—`、软删同作者现状）；`/api/narrators*` 端点 + 命名 token `{narrators}` 打通。⚠️ 刻意差异：不新增独立浏览维度（BrowseView 第 34 期已定不做）、无头像 |
| 43 | `notification` | 11 | §7 | ✓ | 已覆盖 | 通知浮层 + 已读 + 清理 job |
| 44 | `opds` | 23 | §10 | ✓ | 已覆盖 | 第 7 期（OPDS 1.2 + 独立凭据） |
| 45 | `path` | 9 | §5 | ✓ | 已拍板不做 | 路径策略（`GET config` / `GET` / `POST`）—— 服务于第 16 行求书的远程路径映射 |
| 46 | `position-converter` | 17 | §4 / §10 | ✓ | **已覆盖**（第 54 期·子集） | **阅读位置换算**：⚠️ **第 54 期改判为做并已落地（CFI ↔ XPointer ↔ NF 章内偏移）** —— `core/epub_cfi.py`（生成/解析/兼容层，位置换算唯一真值源）+ `progress.cfi` 列 + `/api/books/{bid}/progress` 的 `offset` 进 `cfi`/`offset` 出 + `to_nf` 兼容识别 `epubcfi`。**刻意差异**：kobo span / kepub DOM 两向仍不做（沿用原判「单用户单设备收益低」，Kobo 同步 2026-09-17 决策不做）；KOReader **下发仍用章首 XPointer**（kosync 只认 XPointer，真 CFI 会破坏其解析），精确坐标的收益落在本项目自己的阅读器 |
| 47 | `reader` | 12 | §4 | ✓ | 已覆盖 | 阅读器服务端（epub + cbz 两子树） |
| 48 | `reader-preferences` | 7 | §4 | ✓ | 已覆盖 | 第 32 期已落地 |
| 49 | `reading-session` | 17 | §4 / §6 | ✓ | 已覆盖 | 阅读会话（本项目 `reading_sessions` 表对等） |
| 50 | `reading-state` | 7 | §4 | ✓ | **已覆盖** | **重置一本书的阅读状态**（删会话 + 删进度 + 重置状态）：⚠️ **第 42 期复核已落地** —— `POST /api/books/{bid}/reset-reading-state`（`novelforge/server.py:1733`）+ `reset_reading_state`（`novelforge/core/db.py:3767`，删 `reading_sessions` + `progress` + `reading_status` **+ `reading_attempts`（第 43 期起）四处**，**不动批注/书签/评分/文件**） |
| 51 | `readwise` | 20 | 三方同步 | ✓ | 已拍板不做 | 同上（§13） |
| 52 | `recommendation` | 8 | §3 / §6 | ✓ | **已覆盖**（第 35 期） | **打分排序的推荐**（五路权重：元数据词袋余弦 0.5 + 同作者 0.1 + 题材 0.25 + 同系列 0.1 + 评分距 0.05，上限 25）：⚠️ **第 42 期复核已落地** —— `novelforge/core/recommend.py:28-33`（权重）/`:123-197`（打分排序）、`GET /api/books/{bid}/similar`（`novelforge/server.py:1777`）；`embedding`（语义向量）仍不做 |
| 53 | `release-notes` | 11 | §7 | ✓ | 已覆盖 | What's New（本项目第 30 期已收敛为单一版本常量） |
| 54 | `scanner` | 28 | §2 | ✓ | 已覆盖 | 文件监听 + 稳定性判定 + 扫描任务（本项目第 30 期已落地） |
| 55 | `seed` | 6 | §1 | ✗ | 与定位无关 | 演示数据播种 + 清理 —— 本项目已删除演示种子（见 §8 域「任务真实性」条目） |
| 56 | `series` | 14 | §11 | ✓ | 已覆盖 | 含系列缺册（`series-gaps`）与阶梯（`series-ladder`）工具 ⇒ 见第 60 行 |
| 57 | `server-font` | 8 | §1 | ✓ | 已覆盖 | 服务端字体库 |
| 58 | `shared-reading-insights` | 10 | §6 | ✓ | 已拍板不做 | 用户间共享阅读洞察（分享级别 + 查看会话 + 审计）⇒ 多用户（§0.2 原则 1） |
| 59 | `smart-scope` | 12 | §2 | ✓ | 已覆盖 | 智能书架（第 10 期） |
| 60 | `statistics` | 13 | §6 | ✓ | 已覆盖 | 第 32 / 33 期（本书图表两批共 30 张） |
| 61 | `storygraph` | 24 | 三方同步 | ✓ | 已拍板不做 | 同上（§13） |
| 62 | `upload` | 16 | §5 | ✓ | 已覆盖 | 上传（第 30 期已对齐允许集） |
| 63 | `user-book-note` | 5 | §12 | ✗ | 已覆盖 | 单书笔记（本项目书评 / 批注覆盖） |
| 64 | `user-book-status` | 15 | §3 | ✗ | 已覆盖 | 阅读状态 + **阅读尝试**（`reading-attempt` 重读）—— 本项目有 `reading_status` 表 |
| 65 | `user-preferences` | 7 | §1 | ✓ | 已覆盖 | 单用户偏好（本项目各 store 对等） |
| 66 | `user-statistics` | 18 | §6 | ✓ | 已覆盖 | 阅读统计聚合 job + 时区回填 |
| 67 | `user` | 33 | §1 | ✓ | 已拍板不做 | 多用户实体 + 头像 + 内容过滤 ⇒ 多用户（§0.2） |

**计数核对（第 42 期刷新口径，第 53 期 `narrator` 由「已拍板不做」移入「已覆盖」）**：已覆盖 **47**（原 40 − `kobo` 1 − `metadata` 1 + 第 34–36 期落地 8 + `narrator` 第 53 期 1）＋ **部分实现 1**（`metadata`）＋ 已拍板不做 **15**（原 11 + `email` / `embedding` / `position-converter` / `kobo`）＋ 非能力 **1** ＋ 与定位无关/不容 **3**（`seed` / `file-write` / `migration`）＝ **67** ✓

---

## 三、前端 feature 33 项对照

页面轴**覆盖度明显好于模块轴** —— 因为既有对照表本来就是按页面采的。列出是为了完整性，
**只有 1 项是新信息**：

| feature | 主域 | 判定 | feature | 主域 | 判定 |
| --- | --- | --- | --- | --- | --- |
| `achievements` | §6 | 已覆盖 | `library` | §2 | 已覆盖 |
| `admin` | §1 | 已拍板不做（多用户） | `metadata-score` | §3 | 已覆盖 |
| `annotations` | §12 | 已覆盖 | `migration` | — | **漏项候选**（同第 41 行模块） |
| `audit` | §1 | 已拍板不做（多用户） | `notifications` | §7 | 已覆盖 |
| `auth` | §1 | 已拍板不做（多用户） | `onboarding` | §1 | 已拍板不做（多用户首启流程） |
| `author` | §11 | 已覆盖 | `pwa` | §1 | 已覆盖（本项目有 PWA 支持） |
| `book-dock` | §10 | 已覆盖 | `reader` | §4 | 已覆盖 |
| `book-metadata-fetch` | §3 | 已覆盖 | `readwise` | 三方 | 已拍板不做 |
| `book-requests` | §9 | 已拍板不做 | `scanner` | §2 | 已覆盖 |
| `book` | §3 | 已覆盖 | `series` | §11 | 已覆盖 |
| `collection` | §1 | 已覆盖 | `settings` | §1 | 已覆盖 |
| `custom-icons` | §1 | 已拍板不做 | `smart-scope` | §2 | 已覆盖 |
| `dashboard` | §6 | 已覆盖 | `statistics` | §6 | 已覆盖 |
| `email` | §7 | **漏项候选**（同第 26 行模块） | `storygraph` | 三方 | 已拍板不做 |
| `hardcover` | 三方 | 已拍板不做 | `tools` | §5 | 已覆盖 |
| `kobo` | §10 | **未实现**（同 §2；仅设置页占位） | `whats-new` | §7 | 已覆盖 |
| `koreader` | §10 | 已覆盖 | | | |

---

## 四、首次记录的模块深挖（13 个漏项候选 + 3 个其他）

**分母就是第二节里判定为「漏项候选 / 与定位不相容 / 与定位无关」的那 15 行**
（`architecture` 是第 16 行，但它不是能力，无需深挖）：

- **4.1 值得做 4 项** ＋ **4.2 有价值但不做 8 项** ＝ 13 个漏项候选（**第 35 期**：4.2 里的 3 项改判为做
  并落地；**第 36 期**：再 1 项 —— `book-move` ⇒ 真·不做 **4 项**、真·值得做 **8 项**）；
- **4.3 与定位不容 / 无关 3 项** ＝ 其中 `migration` 属那 13 个，**另外 2 项（`file-write` / `seed`）
  是首次记录但不属漏项候选**。

### 4.1 值得做（4 项）—— **第 34 期已全部落地**

> 落地账目（第 34 期，2026-09-21）：四项全部实现并各有测试钉住。
> 与本节原判的两处偏差**如实记录**：① `catalog` 的七维里「题材 / 标签」在本项目是**同一个字段**
> （`tags` = OPF `dc:subject`，上游分 genre / tag 两个）⇒ 只做一个题材维度、六个维度上线，
> **不把同一份数据换个名字列两遍**；② 侧栏计数**刻意不带 `library_id`** —— 三个目标页都是跨库的，
> 计数跨库才对得上（否则会出现「侧栏 3、页面 12」）。

| 模块 | 上游形态（证据） | 本项目现状（第 34 期后） | 落地锚点 |
| --- | --- | --- | --- |
| `bookmark` | `bookmark.service.ts`：按 CFI / 位置创建、软删、tombstone 复活、并发冲突合并 | **已落地**（原为「零」）：`bookmarks` 表 + 六条路由 + 阅读器工具条开关与书签档（活跃 / 垃圾桶）；对齐上游三形态：**位置去重 / 墓碑复活 / 并发合并** | `novelforge/core/db.py:970` `save_bookmark`、`novelforge/server.py:1963-2037`、`frontend/src/views/ReaderView.vue:1053`/`:1150`（工具条开关 / 书签档面板）；能力键 `bookmarks`（仅 ebook / mixed） |
| `reading-state` | `reading-state.service.ts`：`POST /books/:bookId/reset-reading-state`，删会话 + 删进度 + 重置状态 | **已落地**（原为「零」）：详情页「我的记录 → 从头开始」；**只删读出来的痕迹**，批注 / 书签 / 评分 / 收藏与磁盘文件一律不碰 | `novelforge/core/db.py:3767` `reset_reading_state`、`novelforge/server.py:1733`、`frontend/src/components/book/ReadingRecord.vue:137` |
| `catalog` | `catalog.service.ts`：7 个实体维度的搜索（作者/题材/标签/演播者/出版社/系列/语言）+ 收藏；按可见库收窄 | **已落地**（原为「全局搜索只跨书」）：新页 `/browse`「实体总览」按**六个**维度浏览本地书目、按当前书库收窄；**不新增聚合接口**（这些维度本就是同一份书目的投影） | `frontend/src/views/BrowseView.vue:51`（维度表）、`frontend/src/router/index.ts:174`、`frontend/src/data/nav.ts:72`；「收藏」维度靠 `/api/books` 附带的 `collection_ids`（`novelforge/server.py:998`）+ `collection_map()`（`novelforge/core/db.py:1154`） |
| `browse-counts` | `browse-counts.service.ts`：侧栏 Browse 三计数，60 s 缓存 | **已落地**（原为「无计数」）：三计数与目标页**同源**、60 秒节流、按库可选收窄；读失败不显示胶囊 | `novelforge/core/browse_counts.py:25`/`:65`、`novelforge/server.py:3572`、`frontend/src/data/nav.ts` 的 `countSource: 'browse'` + `frontend/src/components/AppSidebar.vue` 的 `navCount()` |

### 4.2 有价值但不做（8 项；其中 3 项第 35 期、1 项第 36 期、1 项第 53 期（narrator）改判为做并落地，行内 ⚠️ 标注）

| 模块 | 上游形态 | 不做的理由 |
| --- | --- | --- |
| `book-move` | 跨库移动（preview + SSE 逐本进度 + 目标库权限） | 本项目多库是**独立目录**（`LIBRARY_SOURCE_DIR`），移动 = 真搬文件 + 处理同书冲突 + 回滚。上游那种「先预览再流式搬」的完整度不做会留半成品，做全了是独立一期。⚠️ **第 36 期由用户改判为做并已落地**（原判末句「做全了是独立一期」正是本期立项理由）：**两条入口共用一个执行层** —— 自动归库 `migrate.preview:172` / `plan:258`（行为逐字未动）与用户发起的移动 `migrate.move_preview:571` / `move_plan:594`，共用 `execute:947` / `rollback:1041`（批次用既有 `library_migrations.direction` 列区分）—— 接口 `POST /api/book-move/{targets,preflight,plan,apply,rollback}` + `GET /api/book-move/batches`（`novelforge/server.py:3226`/`:3236`/`:3251`/`:3277`/`:3344`/`:3367`），前端书架批量条「移动到书库」+ 三段式弹窗（`frontend/src/views/ShelfView.vue:678`、`frontend/src/components/book/BookMoveDialog.vue`）+ 「撤销本次移动」（`ShelfView.vue:692`）。**三处刻意差异**：① **不引入 SSE**（全仓零先例），逐本进度走既有「SQLite 任务行 + 前端轮询」；② 「目标库权限」在单用户下的等价物 = **库类型相容闸门**（判据只许来自 `library._exts_for_type`，前端禁选是体验、后端 400 才是契约）；③ 同名冲突按用户口径「拒绝覆盖 + 一键用建议名移入」。**开工前先修掉一条既有缺陷**：`meta_override` / `meta_online` / `meta_cover` / `scrape_items` 四张按 `book_id` 存的表原先**不在搬迁清单**里 ⇒ 移动或改名一次就断链（修法见 `core/db.py:1633` 的 `REMAP_TABLES` / `:1643` 的 `REMAP_EXPLICIT_TABLES` / `:1655` 的 `REMAP_MERGE_TABLES`） |
| `book-metadata-lock` | 13 个 provider id + 11 个漫画字段的**字段级**锁定 | 本项目已有**单书级**「覆盖 / 保留」三态语义（`server.py:1183-1350` 的元数据 GET / POST / online / revert 四个端点）。字段级锁定是把它拆细，收益主要是自动化抓取场景 —— 而本项目的自动抓取默认关，收益面窄。⚠️ **第 35 期由用户改判为做并已落地**：新表 `meta_locks`（`core/db.py:396`，`PRIMARY KEY(book_id, field)`；「刻意与 `meta_override` 分表」的理由在 `:374-378` 的建表注释里 —— override 行只在**有值**时存在，表达不了「我没改过、但也不想让抓取动它」）。抓取闸门落在 `core/metafetch.py:207`（10 个字段）与 `:222`（封面，独立键 `cover`），在线确认写入另在 `:335-349` 再挡一道；接口 `POST /api/books/{bid}/metadata/lock`（`server.py:1352`）。**可锁对象 = `fileops.METADATA_FIELDS` 的 10 个 + 封面**（上游是「13 provider id + 11 漫画字段」，本项目无多 provider / 漫画字段之分，换算后即这 11 项）。**与三态互不干涉**：三态管「取谁的值」，锁管「让不让抓取写」 |
| `custom-metadata` | 自定义字段的**定义**（建字段 / 排序 / 改标签 / 切适用书库 / 归档 / 软删恢复） | 本项目 `custom_fields` 是**抓取时的固定键值对**，不是用户可定义的字段 schema；原判另称「做成 schema 要动元数据模型 + 12 字段的 metascore 权重表」。⚠️ **第 35 期由用户改判为做并已落地，且原判理由有一处经核为误**：① 实测那次再核时 `custom_fields` 的编辑入口**已经不存在**（`frontend/src/views/settings/pages/MetadataPage.vue` 里零命中），原锚点已失效；② 「要动 12 字段的 metascore 权重表」**不成立** —— `custom_fields` 本就在 `NOT_SCORED`（`novelforge/core/metascore.py:80-84`，why =「用户自定义键值，不参与完整度」），**权重表一行没动**。落地 = 定义表 `custom_field_defs`（`core/db.py:343`，`key` 与 `label` 分离、`type` / `position` / `library_ids` / `archived` / `deleted_at` 垃圾桶）+ 值表 `book_custom_values`（`:366`）+ 七条路由 `server.py:1404-1516`；同名配置项 `metadata_fetch.custom_fields` **已整体下线**（默认值 / 顶层白名单 / 编辑器 / note 文案 / 文档引用一并清理）。**级联**：`book_custom_values` 与 `meta_locks` 均已进 `ORPHAN_TABLES`（`core/db.py:1568-1569`）与 `REMAP_TABLES`（`:1619-1622`），改名时**逐行搬迁、撞主键保留目标行** —— 照第 34 期书签的范式（整体 `UPDATE` 撞唯一约束会被外层 `except` 吞成「搬 0 行」而静默丢数据） |
| `recommendation` + `embedding` | 元数据特征向量 + 加权打分（余弦 0.5 / 作者 0.1 / 题材 0.25 / 系列 0.1 / 评分距 0.05），上限 25 | 本项目 `core/recommend.py` 已有**规则式**相似书（同作者 / 题材 / 系列）。上游那套的价值全在**排序质量**，而它的向量是元数据特征（不是语义 embedding）。⚠️ **第 35 期改判「`recommendation` 做、`embedding` 仍不做」并已落地**：权重与形态对齐上游（`core/recommend.py:29-33` 的五个权重、`:36-37` 上限 25 / 默认 6）；原判顾虑「没有评分数据的库里会退化到接近规则式」**用降级口径化解** —— 任一方未评分时**那一路不进分母**（`:116-120`、`:163-166`），而不是当 0 分。**刻意差异两处已写进模块 docstring（`:10-22`）**：向量用元数据词袋（作者 / 题材 / 系列 / 出版社 / 语言 / 十年段 / 书名词元，**简介刻意不进**），且保留一道「实质重合」门（至少同作者 / 同题材 / 同系列之一才算候选）—— 上游权重决定**排得好不好**，这道门决定**该不该出现**。⚠️ **第 54 期 `embedding` 由用户改判为做并已落地**：`core/embed.py`（LSA 默认 / 本地 transformer 可选，离线零下载）+ `book_embeddings` 表 + `POST /api/embeddings/recompute`；`similar_books` 余弦一路**优先取向量、缺向量逐对回落词袋**，词元集合降为回落路径 —— 「实质重合」门原样保留，上游那句「权重决定排得好不好、门决定该不该出现」继续成立。**简介进向量语料**（TF-IDF + L2 归一下「谁的字数多」的偏差不存在了，取舍记在 embed.py） |
| `position-converter` | CFI / kobo span / XPointer / kepub DOM 四向换算 | 只服务多设备进度互通。本项目的 Kobo / KOReader 支持**已按可用子集落地**（`settingsNav.ts:397` 记了完整口径与「反向只定位到章首、准确位置由 percentage 兜底」的取舍）—— 补全的收益在单用户单设备下很低。⚠️ **第 54 期由用户改判为做并已落地（子集）**：`core/epub_cfi.py`（CFI 生成 / 解析 / CFI→XPointer 兼容层）+ `progress.cfi` 列（非 NF 来源写入一律清空，防「章已变、CFI 挂旧章」矛盾行）+ 阅读器保存 / 恢复精确到章内字符偏移（textContent 坐标系，前后端同尺度）；KOReader 下发**仍为章首 XPointer**（kosync 只认 XPointer），`to_nf` 仅兼容识别 `epubcfi` 取章序号；kobo span / kepub DOM 仍不做 |
| `email` | 邮件分发整块（附件 / 模板 / 收件人组 / 发送日志 / 凭据加密 / SMTP） | 79 个文件。价值是「把书发到 Kindle 邮箱」这类，但需要 SMTP 凭据管理 + 失败重试 + 附件大小限制一整摊。**与「本地单用户书库」的定位偏离**，且本项目离线优先 |
| `narrator` | 演播者实体（规范化 / sort name / 按书整体替换），5 个文件 | ⚠️ **第 53 期改判「做」并已落地**：零依赖音频标签解析（m4b/mp3/m4a/opus/ogg/flac）落 `books.narrators` + `narrators` 实体表（排序名两列分列，对齐 `authors`）+ `/api/narrators*` 端点 + 命名 token `{narrators}` 打通；前置「音频标签演播者解析」已同步补齐。⚠️ 刻意差异：不新增独立浏览维度、无头像（`hasPhoto=—`） |

### 4.3 与本项目定位不相容 / 无关（3 项）

| 模块 | 判定 | 理由 |
| --- | --- | --- |
| `file-write` | **不与发布三原则相容 ⇒ 永久不做** | 上游第二大模块（94 文件），做的是**把元数据写回文件本身**（6 类 writer：EPUB / FB2 / MOBI / PDF / CBZ / 音频）。本项目发布三原则明确「**元数据仅存于服务器数据库，绝不写入 OPF**」⇒ 方向相反。**这是本次取证最重要的一条发现**：一个 94 文件的模块此前从未进过任何对照视野 |
| `migration` | 不做（但值得记一笔） | 89 文件，从 Audiobookshelf / Booklore / Calibre-Web-Automated / Grimmory 四源迁移。本项目是**单一成品目录**结构，迁移进来要先把四家的库表模型映射到本项目 —— 前置依赖（多库 + 用户体系）本就不同。**若将来要做，第一条应是「只迁书目元数据、不迁用户状态」** |
| `seed` | 与定位无关 | 演示数据播种。本项目**已主动删除**演示种子（`data/tasks.ts` 头注释记了移除始末），再引回来是倒退 |

---

## 五、与既有文档的关系与本次订正

1. **本文件是新增的第三条轴，不替代 `capability-gap.md`**：那份文档回答「线上看到的能力本项目做了没有」，
   本文件回答「上游代码里的能力块本项目做了没有」。**两份都要看**。
2. **订正 `docs/roadmap-gaps-remaining.md:790`**：原文写「69 个后端模块逐模块对照：用户未选」，
   实测是 **67 个**（`ls-tree -d` 计数），其中 1 个非能力 ⇒ 能力模块 **66 个**。该行同时从「未选」
   改为「第 33 期已产出清单，见 `docs/bookorbit-module-inventory.md`」。
3. **`capability-gap.md` 顶部加一行指引**指向本文件（避免下次又只按页面找缺口）。
4. **本期不实现清单里的任何项**。第四节「值得做」的 4 项是第 34 期的候选输入，
   **排期与否由用户决定**，本文件只提供事实与成本判断。

---

## 六、第 42 期更新（2026-09-23）：上游无新增 → 判定刷新 + 部分缺口

**背景**：本期按「重新取证上游找新缺口」立项，先代理优先复核上游
`https://github.com/735876214/bookorbit` 的 `refs/heads/main` —— **仍为 `c292d6cc`**
（与第 33 期取证时**同一个 commit**，无新提交、无新 tag）⇒ 「上游出了新版本、有新模块/新页面」
的前提**不成立**。于是本期做两件**在同一版本上就能完成、且此前未系统做过**的事：
① **刷新 §2 逐行判定**（多条「漏项候选」其实已在第 34–36 期落地，表未同步；另订正 3 处文档错误）；
② **补一类此前未单独成表的「部分缺口」** —— 上游模块有、本项目**只做了子集**的子能力。
**本期零运行时改动**（不实现清单里的任何项）。

### 6.1 §2 判定刷新（10 处，已就地改在第二节表内）

| # | 模块 | 原判定 | 第 42 期判定 | 一句话依据 |
| --- | --- | --- | --- | --- |
| 14 | `book-metadata-lock` | 漏项候选 | 已覆盖（第 35 期） | `meta_locks` 表 + `/metadata/lock` 路由 + 抓取双重挡锁 |
| 18 | `bookmark` | 漏项候选 | 已覆盖 | `bookmarks` 表 + 全套 CRUD（定位=章节坐标，非 CFI） |
| 19 | `browse-counts` | 漏项候选 | 已覆盖（第 34 期） | `core/browse_counts.py` + `GET /api/browse-counts` |
| 20 | `catalog` | 漏项候选 | 已覆盖（第 34 期） | `/browse` 实体总览，**六**维度（上游 8） |
| 24 | `custom-metadata` | 漏项候选 | 已覆盖（第 35 期） | `custom_field_defs` + `book_custom_values` + 七路由 |
| 50 | `reading-state` | 漏项候选 | 已覆盖 | `reset-reading-state` 路由 + `reset_reading_state` |
| 52 | `recommendation` | 漏项候选 | 已覆盖（第 35 期） | `core/recommend.py` 五路权重 + `/similar` |
| 32 | `health` | 已覆盖（**备注错**） | 已覆盖（**订正**） | 路由是 `GET /health`，**无 `/api/health`** |
| 33 | `kobo` | 已覆盖 | **未实现** | Kobo 同步 2026-09-17 决策不做，全仓无 `kobo*.py` |
| 40 | `metadata` | 已覆盖 | **部分实现** | 仅 EPUB 全解析；FB2 不支持、MOBI/AZW3/PDF 无内容解析 |

**为何原表会陈旧**：§2 的「判定」列是第 33 期一次性写就的，第 34–36 期的落地只写在**各行的 ⚠️ 备注**
与 §4.2 里，**没有回填判定列** ⇒ 直接读表会得出「这么多还没做」的错误印象。**这一条是本期最重要的方法学收获**：
**判定列必须与落地记录同批回写**，否则表越大越不可信。

### 6.2 已覆盖模块的部分缺口（新候选，三类）

对「上游有、本项目只做了子集」的子能力逐条核实（锚点为实测）。**排期与否由用户决定**，本节只给事实与成本。

**A. 值得做（6 项）—— ⚠️ 第 43 期已全部落地，逐项落地锚点见第七节**

| 子能力 | 上游模块 | 本项目现状（锚点） | 成本 |
| --- | --- | --- | --- |
| 系列缺册工具（series-gaps） | `series` | **未实现**；仅有「缺序号」提示（`frontend/src/views/SeriesDetailView.vue:55`），不是「找出缺的册号」 | 低：按系列序号找空洞，纯读 |
| 作者排序键回填（author sort-key backfill） | `book` | **部分**：字段 + 手改有（`novelforge/core/db.py:405`、`POST /api/authors/{name}/sort-name` `novelforge/server.py:2289`），**无批量回填** | 低 |
| 书架首字母/分桶跳转（jump buckets） | `book` | **未实现** | 中：需排序键 + 前端跳转条 |
| 阅读尝试/重读（reading-attempt） | `book` / `user-book-status` | **未实现**：`reading_sessions` 无重读语义 | 中：新表/列 + 状态机（上游另有 backfill） |
| 批注导出增强（格式 / 范围） | `annotation` | **部分**：前端仅 Markdown 导出（`frontend/src/views/AnnotationsView.vue:179`），无后端接口、无其它格式 | 低 |
| 系列折叠偏好上云（series-collapse-prefs） | `book` | **部分**：仅存 `localStorage`（键 `nf-shelf-prefs`，`frontend/src/stores/shelfPrefs.ts:40`），不随账号偏好同步 | 低 |

**B. 有价值但不做（收益面窄 / 上游语义与本项目不匹配）**

| 子能力 | 上游模块 | 本项目现状 | 不做的理由 |
| --- | --- | --- | --- |
| ⚠️ 批注颜色 ↔ 样式映射 + 跨端降色 | `annotation` | **部分→第 44 期改判为做（样式类型部分）**：10 色调色板（`frontend/src/data/annotationColors.ts:27` 的 `HIGHLIGHT_COLORS`）新增并列「样式类型」维度（高亮/下划线/删除线/纯笔记，`HIGHLIGHT_STYLES`），阅读器/批注总览/书详情/每日划线四处统一引用；「跨端降色」仍不做 | 单端阅读器，无跨端降色需求（该部分仍不做） |
| 批注级位置换算（CFI / kobo span / kepub DOM） | `annotation` / `position-converter` | **部分**：仅进度级 XPointer↔章（`novelforge/core/koreader.py:63`） | 与 §4.2 `position-converter` 同判：单用户单设备收益低 |
| 实体**删除**策略 | `entity-manager` | **部分**：仅作者/系列的改名 + 合并（`novelforge/core/fileops.py:218/254`） | 源文件名无写入口 ⇒ 删除退化为纯元数据操作，收益窄 |
| 元数据提取器扩到 6 类 | `metadata` | **部分**：仅 EPUB 全解析（见 §2 第 40 行） | 非 EPUB 本项目**刻意不解析**（`novelforge/core/library.py:1234`） |
| 在线 provider 扩到 13 个 | `metadata-fetch` | **2 源**（OpenLibrary / Google Books，`novelforge/core/metasources.py:36-48`） | 刻意维持内置 2 源（`docs/roadmap-gaps-remaining.md:72`） |

**C. 与定位或既有决策不容（不做）**

| 子能力 | 上游模块 | 本项目现状 | 判定依据 |
| --- | --- | --- | --- |
| 批注跨端同步 / 导入 | `annotation` | **未实现** | kosync 只同步进度、**无批注端点**（`novelforge/server.py:2443`）；无数据源 |
| 按设备重建批注位置（device-position-rebuilder） | `annotation` | **未实现**：批注表无设备维度（`novelforge/core/db.py:191-199`） | 无设备来源 |
| Kobo 阅读状态投影 | `user-book-status` | **未实现** | Kobo 同步已决策不做（见 §2 第 33 行） |
| 通知清理 job | `notification` | **未实现**（刻意不做） | 本项目**无通知产生端**（`novelforge/server.py:4666-4672` 明写不做自动清理） |
| 通知推送网关（SSE） | `notification` | **未实现**（走轮询，`novelforge/server.py:4638`） | 全仓**刻意不上 SSE**（与 §4.2 `book-move` 同一口径） |
| 孤儿封面清扫（cover-sweep） | `maintenance` | **未实现**：仅有孤儿**记录**清理（`novelforge/server.py:4410`） | 已决策不做（`docs/bookorbit-capability-gap.md:283`） |

### 6.3 联动文档时效

- `docs/bookorbit-settings-inventory.md` / `docs/bookorbit-feature-flows.md` /
  `docs/bookorbit-library-contract.md`：按第 41 期库模型关键字（`root_path` / `source_subdir` /
  `inplace`）**复核后零命中** ⇒ 无需改动。
- `docs/roadmap-gaps-remaining.md`：逐期历史记录里的旧 `root_path` / `source_subdir` / `mode` 表述
  **属历史事实，一律不动**（按锚点核验约定，改它等于篡改历史）。
- `docs/bookorbit-capability-gap.md` §0.3 基线已随本期重取（路由 284 → **285**）。

---

## 七、第 43 期更新（2026-09-23）：§6.2-A「值得做」6 项全部落地

第 42 期第六节 §6.2-A 列出的 6 项「值得做」部分缺口，**第 43 期一次性全部实现**。
下行只给**落地实现位置**（文件名 + 函数/接口名，不写行号以避免锚点漂移 —— 需要行号时按
`tests/check_doc_anchors.py` 现测）：

| 子能力 | 第 43 期落地实现（本项目） |
| --- | --- |
| 系列缺册（series-gaps） | `novelforge/core/library.py` 的 `series_gaps()`（**唯一真值源**）注入 `GET /api/series/{name}` 的 `gaps`；前端 `frontend/src/views/SeriesDetailView.vue` 徽章 + 可展开清单。**无序号 / 非数字序号单独计数、不并入缺册** |
| 作者排序键回填（author sort-key backfill） | `novelforge/core/authors.py` 的 `derive_sort_name()` + `backfill_sort_names()`；接口 `POST /api/authors/sort-name/backfill`。⚠️ **只写派生态列 `sort_name`，绝不动用户覆盖列 `sort_name_local`** |
| 书架首字母跳转（jump buckets） | 判据唯一源 `frontend/src/lib/shelfBuckets.ts`（拉丁按首字、其余归 `#`，桶序 A–Z 升序且 `#` 垫底）；`frontend/src/views/ShelfView.vue` 顶部跳转条（三视图共用 `data-bucket`，滚动高亮取**真实**位置） |
| 阅读尝试 / 重读（reading-attempt） | 新表 `reading_attempts`（`novelforge/core/db.py`，已进 `ORPHAN_TABLES` / `REMAP_TABLES`）；`db.set_status` 自动开轮 / 收尾，另有 `db.start_attempt` / `finish_attempt` / `backfill_attempts`；接口 `/api/books/{bid}/reading-attempts`(`/finish`)、`POST /api/reading-attempts/backfill`；前端 `frontend/src/components/book/ReadingRecord.vue` 轮次块。`reset_reading_state` 同步扩为**四清**（+`attempts`） |
| 批注导出增强（格式 / 范围） | `GET /api/annotations/export?format=markdown\|json\|csv`（可按 `book_id` / `library_id` 收窄，**只导活跃**）；前端 `api.exportAnnotations` + `frontend/src/views/AnnotationsView.vue` 下拉（格式 + 仅当前书库） |
| 系列折叠偏好上云（series-collapse-prefs） | 新增第 7 个偏好块 `shelf`（`novelforge/server.py` 的 `PREFS_BLOCKS` + `frontend/src/lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS`，**两端有一致性契约测试** `tests/test_prefs_shelf_block.py`）；`frontend/src/stores/shelfPrefs.ts` 增 `applyRemote`（逐键挑 + 抑制回推）；其余书架字段（视图 / 排序 / 缩略图点击 / 筛选默认展开）**仍只存本机** |

**契约测试**：`tests/test_series_gaps.py`、`tests/test_reading_attempts.py`、
`tests/test_annotation_export.py`、`tests/test_author_sort_backfill.py`、
`tests/test_prefs_shelf_block.py`、`frontend/src/lib/shelfBuckets.spec.ts`。
后端全量 **720 例 / 0 failed**（含本期 +30）；前端 `npm run test:unit` **62 例**（含 +4）。

## 八、第 44 期更新（2026-09-23）：重审 §6.2-B「有价值但不做」5 项

第 44 期对 §6.2-B 五项逐条重审（依据当前代码现状与当初「不做」理由），结论如下：

| 子能力 | 第 44 期结论 | 依据 |
| --- | --- | --- |
| 批注颜色 ↔ 样式映射 + 跨端降色 | **改判为做（仅「样式类型」部分）** | 当前批注模型只有 `color`（`annotationColors.ts` 的 `HIGHLIGHT_COLORS`），无「样式」维度；单端阅读器里增加**样式类型**（高亮/下划线/删除线/纯笔记）是真实可用功能。理由里的「跨端降色」因无 Kobo 设备**仍不做** |
| 批注级位置换算（CFI / kobo span / kepub DOM） | 仍不做 | 需完整 EPUB DOM/CFI 解析器，单用户单设备收益低，理由仍成立（`core/koreader.py` 仅进度级 XPointer↔章） |
| 实体删除策略 | 仍不做 | 源文件名无写入口，删除退化为纯元数据操作且书仍引用作者/系列（`core/fileops.py` 仅改名+合并），收益窄 |
| 元数据提取器扩到 6 类 | 仍不做 | 非 EPUB 刻意不解析（`core/library.py`） |
| 在线 provider 扩到 13 个 | 仍不做 | 刻意维持内置 2 源（`core/metasources.py` + `roadmap-gaps-remaining.md`） |

**批注样式类型落地实现**（第 44 期）：
- 数据层：`annotations` 表加列 `style TEXT NOT NULL DEFAULT 'highlight'`（`db.py` 建表 + 轻量迁移）；加列不加 `book_id`，不影响 remap 契约。
- 后端：`db.add_annotation` 透传 `style`；`list_annotations` / `all_annotations` / `trashed_annotations` 一并返回；`POST /api/books/{bid}/annotations` 接收 `style`；`GET /api/annotations/export` 的 csv/json/markdown 一并输出。
- 前端单一来源：在 `annotationColors.ts` 同文件新增 `HIGHLIGHT_STYLES`（高亮/下划线/删除线/纯笔记 + 中文 `label`）与 `highlightStyleLabel()`；四处 UI（阅读器选区浮层、批注总览、书详情批注 tab、每日划线）统一引用。
- 阅读器 `wrapQuote` 按 `style` 分流渲染（下划线 `text-decoration: underline`、删除线 `line-through`、纯笔记虚线下沿、高亮铺底色）；选区浮层在色板旁加样式类型切换。

**契约测试**：`tests/test_annotations.py` 增 `test_annotation_style_roundtrips`（创建带 style → 列表/导出含 style → 老库迁移补 style 列，后者并入既有 `test_legacy_db_gets_new_columns_without_losing_rows` 断言集）。

后端全量 **721 例 / 0 failed**（含本期 +1）；前端 `npm run test:unit` **62 例**（无新增）。

## 九、第 46 期更新（2026-09-23）：16 漏项模块裁决复核（无新增可做项）

对第 33 期遗留的「16 个从未进过对照视野」模块做**逐模块复核**（语义 + 文本检索核实到当前代码），
结论：**值得做的都已在往期落地，无新增可做项，无新增表 / 路由 / 含 `book_id` 的表**。

| 模块 | 现判定 | 代码现状（证据） |
| --- | --- | --- |
| `book-metadata-lock` / `bookmark` / `browse-counts` / `catalog` / `custom-metadata` / `reading-state` / `recommendation` / `book-move` | 已覆盖（第 34–36 期） | 8 项均有表 / 路由 / 前端锚点（详见 §4.1、§7、§8） |
| `email` | 不做 | 全仓无 SMTP / 邮件链路；设置页为占位 |
| `embedding` | 已覆盖（第 54 期） | `core/embed.py`（LSA 默认 / 本地 transformer 可选，离线零下载）+ `book_embeddings` 表 + `POST /api/embeddings/recompute`；`/similar` 余弦一路优先取向量、缺向量逐对回落词袋 |
| `migration` | 不做 | `core/migrate.py` 只做**本地库间搬迁**；无四家外部系统迁移 |
| `narrator` | 已覆盖（第 53 期） | 零依赖音频标签解析 + `narrators` 实体表（排序名两列分列，对齐 `authors`）+ `/api/narrators*` 端点 + 命名 token `{narrators}` 打通；不新增独立浏览维度、无头像（`hasPhoto=—`） |
| `position-converter` | 已覆盖（第 54 期·子集） | `core/epub_cfi.py`（CFI↔XPointer↔NF 章内偏移，唯一真值源）+ `progress.cfi` 列 + 进度端点 `offset` 进 `cfi`/`offset` 出；kobo span / kepub DOM 仍不做，KOReader 下发仍为章首 XPointer |
| `file-write` | 永久不做 | `core/fileops.py` 的写回函数已**退出生产路径**；元数据只落 DB 是硬约束 |
| `seed` | 不做 | 演示种子已主动移除 |
| `architecture` | 非能力 | 无等价物 |

**本期文档订正 2 处**：

- §3 前端 feature 表的 `kobo` 行原标「已覆盖」，与 §2 第 33 行（第 42 期订正为**未实现**）及代码矛盾
  ⇒ 已就地改为「未实现」（本项目仅设置页占位，Kobo 同步 2026-09-17 决策不做）。
- §1 的「13 个漏项候选 / 值得做 4 / 有价值但不做 8」是**第 33 期一次性口径**；§2 判定列已在第 42 期回填
  （8 项转为「已覆盖」）⇒ 引用 §1 计数时**以 §2 逐行判定为准**（§1 已自带该提示，此处再点明）。

**本期零运行时改动**。

## 十、第 47 期更新（2026-09-23）：闭环遗留 + 深化占位视图

- **热力图时区口径统一**：`core/activity.py` 的 `timeline` 为三类事件（session/annotation/achievement）补
  server-local `date`（`YYYY-MM-DD`，与 `db.reading_day_minutes` 的 heatmap 同 `time.localtime` 口径）；
  前端 `ReadingActivityView` 的日分组改读 `e.date`，删除 `new Date(ts*1000)` 的浏览器时区换算
  ⇒ 消除 server/browser 跨时区 ±1 天错位。契约 `tests/test_reading_activity.py::test_timeline_events_carry_server_local_date`。
- **Dashboard 确定性**：`DashboardShelfRow` 的 `discover` 行去掉 `Math.random()` 洗牌，改按 book id 稳定升序
  （刷新顺序固定、无运行时随机）。
- **收藏夹做深**（对应上游 collections 总览）：`db.collections` 补 `updated_at` 列（老库迁移回填 `created_at`，
  成员增删 / 重命名均刷新）；`list_collections` 返 `first_book_id`（由 API 层补 `first_book_has_cover`）；
  新增 `PATCH /api/collections/{cid}` 重命名端点；前端 `CollectionsView` 加首书封面预览 / 最后修改 / 行内重命名。
  契约 `tests/test_collections.py`。
- **更新日志做深**：`data/whatsNew.ts` 条目补 `tag` 分类；`WhatsNewView` 渲染版本徽章（`/health` 真实版本）+
  分类 chip + 空态 + 「自上次访问以来」高亮（localStorage，确定性）。
- **通知中心错误态**：`NotificationsView` 加载失败不再退化成「暂无通知」，给错误文案 + 重试
  （与第 46 期 ReadingLog / HighlightOfTheDay 同修法）。
- **浏览器冒烟**：无头浏览器认证后加载 `/annotations`、`/reading-activity`、`/collections`、`/whats-new`，
  控制台 0 错误（第 44 期误清空回归在**运行时**确认已修复，此前只跑了 type-check + build）。

## 十一、第 48 期更新（2026-09-23）：三页质量一过（成就 / 探索发现 / 智能书架）

第 47 期滚动项的落地。三页此前均已「已覆盖」，本期只做**质量 / 深化一过**，零后端改动、无新路由 / 表：

- **智能书架**（`SmartScopesView`）：`load()` 原用 `catch { /* ignore */ }` 吞错 ⇒ 失败被当成「还没有自定义书架」。
  改为**错误态 + 重试**；规则编辑器各控件补 `aria-label`（名称 / 匹配方式 / 字段 / 操作符 / 值）。
- **成就**（`AchievementsView`）：加载失败原只 `ui.toast`、底部兜底成「成就加载失败」空态 ⇒ 改为**可重试的错误态**
  （与空态分离）；新增**解锁状态筛选**（全部 / 已解锁 / 未解锁）+ **分组进度条**；「重算成就」按钮改为仅在
  数据已加载且开启时显示（原先 `data?.enabled !== false` 在加载失败时也会显示）。
- **探索发现**（`ExploreView`）：预览弹窗补 `role="dialog"` / `aria-modal` / `aria-labelledby` 与 **Esc 关闭**
  （`onMounted` / `onUnmounted` 挂卸监听）；结果区新增「共 N 条结果」计数。
- **验证**：前端 `type-check` 0 错 + `test:unit` 62 + `build` + `deploy` 全绿；playwright 冒烟三页认证后
  **控制台 0 错误**；后端全量 **725 passed / 0 failed**（本期无新增后端用例）。

## 十二、第 49 期更新（2026-09-23）：设置页信息架构 + 错误态收敛 + 偏简视图做深

- **书库管理并入设置页**：`settingsNav` 的 `libraries` 由 placeholder 转 `ready`（组件 = `views/tools/LibrariesView.vue`），
  删工具页「书库管理」标签与 `tools/libraries` 路由；8 处入口改指 `/settings/libraries`（侧栏 / 书架 / 首屏提示条 /
  引导弹窗 / 迁移门禁 / 本地转换 / 收书目录 / `nav.ts`）；用户可见文案「工具 → 书库管理」→「设置 → 书库管理」
  （含后端 `core/library_rules.py`、`core/library.py`）。契约 `tests/test_first_run_contract.py` 的 `LIBRARIES_ROUTE` 已同步。
- **删除 12 个上游对照只读占位页**（图标 / 界面语言 / 隐私与共享 / 内容限制 / Kobo / KOReader 上游对照 / 邮件投递 /
  用户 / 账号活动 / 免密链接 / OIDC·SSO / 求书）：设置页 48 → **36 页**，占位页清零；
  `tests/test_settings_nav_contract.py` 重构（页数 36、`EXPECTED_PLACEHOLDERS` 空集、新增 `REMOVED_UPSTREAM` /
  `REMOVED_PAGE_PATHS` 显式「已移除」清单、`EXPECTED_OWN` 收缩为 `{komga}`）。逐页理由见
  `docs/bookorbit-settings-inventory.md` §8。
- **全站错误态收敛（19 处）**：把「主数据加载失败被静默当成空态」的页面改为**可重试错误态** ——
  `AuthorsView` / `SeriesView` / `SeriesDetailView` / `AuthorDetailView` / `AnnotationsView` / `StatsView` /
  `CollectionDetailView` / `BookDetailView`（区分「拉取失败」与「找不到」）/ `tools/{SourcesView, OutputView,
  MissingResourcesView, DuplicateBooksView, EntityManagerView, LogsView, LibrariesView}` /
  `settings/pages/{IntegrationPage, KoreaderPage}` / `stores/{collections, stats, library}`（后者供仪表盘页级提示）。
  有意静默降级（离线进度 / 可选增强 / 非阻塞状态预取）**保留**不动。
- **偏简视图做深**：`SeriesView` 加排序（册数 / 名称）；`tools/OutputView` 加格式筛选 + 排序（时间 / 名称 / 体积）；
  `DocumentationView` 接 `/health` 真实版本号并补「更新日志 / 关于 / 高级」入口。
- **文档锚点**：本期改 `router/index.ts`、`data/settingsNav.ts` 等被引用文件 ⇒ 重跑 `tests/check_doc_anchors.py`，
  修正 `capability-gap.md`（8 处）与 `module-inventory.md`（4 处）的**实测行号**，**硬错 0**；余 14 条「疑似漂移」
  全在 `docs/roadmap-gaps-remaining.md` 的**历史实施记录**内，按约定（历史行号不改写）保留。

## 第 50 期更新（2026-09-23）：服务端组三页做深 + Komga 页深化 + 遗留文案订正

- **订正第 49 期漏改的指引文案**：`frontend/src/` 内共 14 处「工具 → 书库管理」→「设置 → 书库管理」
  （`TaskCenterView` / `ExploreView` ×2 / `ProfilePage` / `OpdsPage` ×2 / `KomgaPage` / `BookDockPage` /
  `settingsNav.ts` ×2 / `settingsFields.ts` / `MigrationGateDialog` / `GuidedTourModal` / `ScrapePanel`）。
  **刻意不改**：`settingsNav.ts` 与 `router/index.ts` 里的「**原**「工具 → 书库管理」入口已并入 / 已移除」
  （正确历史陈述）、`docs/roadmap-gaps-remaining.md` 的历史实施记录、各 inventory 的记录性表述。
- **收书目录（Book Dock）做深**：`loadDock()` 由静默 `catch` 改为**可重试错误态**（此前失败会渲染成空态
  「投递目录里还没有文件」，属「失败冒充空态」）+ 首屏加载态（消除空态闪烁）；投递目录路径一键复制；
  条目补「入库 / 更新」时间（`created_at`，`updated_at` 晚于其 60s 以上才另标）；全选 / 清空 +
  批量「重扫 / 忽略」（无批量端点，逐条调用既有单条接口，失败逐条汇总后统一刷新）。
- **服务端字体（Server Fonts）做深**：新增**行内字体预览** —— 列表行可点选，用 store 已注入的 `@font-face`
  以 `customFontFamily(id)` 渲染样例文本（中文 / 拉丁 / 数字 / 标点）并可调字号，**零额外请求**；
  未支持清单相应下调为仅剩「按字重 / 斜体派生变体」。
- **审计日志（Audit Log）做深**：类别筛选 chips（**客户端**派生，由动作归并反向得出并带计数）、
  「仅看未记录操作者」筛选（客户端）、「加载更多」（后端只有 `limit` 无 `offset` ⇒ 200/500/1000/2000
  四档抬高重取）、「导出当前筛选结果为 CSV」（客户端 Blob + BOM 保中文）。客户端两维的作用范围在页面上
  如实标注为「当前已加载的 N 条」，与服务端四维（动作 / 结果 / 操作者 / 关键字）区分。既有 `err` 兜底保留。
- **Komga 库布局页深化**（不新增子系统）：整理预览加搜索 / 只看冲突 / 全选可见项 / 排序（系列 · 路径），
  全部 `computed` 派生、**不改 `plan.items` 原数组**，并注明「筛选与排序只影响展示，提交范围 = 已勾选」；
  `preview()` 失败由「只 toast」改为**页面级错误态 + 重试**；兼容服务端区加开启状态徽章，
  未开启时地址与凭据区弱化并说明「先填好备用，开启后生效」。
- **验证**：前端 `type-check` 0 错 + `test:unit` 62 + `build` + `deploy`；后端全量 pytest（基线 725）；
  `tests/check_doc_anchors.py` 判硬错 0；无头浏览器冒烟四页控制台 0 错误。
- 提交：`80c56b4`（文案）+ `9e8b989`（收书目录）+ `7fe4657`（服务端字体）+ `b38306d`（审计日志）+
  `d85a007`（Komga）。

## 第 51 期更新（2026-09-24）：外观与阅读器五页照上游补齐并深化

对 7 个与外观 / 阅读器相关的设置页逐条对照上游，**只有 4 页存在真实差额**（浏览行为 / 电子书 / PDF 已达覆盖，其中 PDF 的未支持卡还串了漫画页的条目）。**所有新增档位默认值一律等于改造前行为**，观感 1:1 不变。

- **封面样式**：详情页取色加「关闭 / 单色 / 双色」三档 —— 单色档刻意**不写第二套 CSS 变量**，靠 `cover-effects.css` 既有的 `--cover-tint-hue-2: var(--cover-tint-hue)` 收成一片单色（该兜底本就是为这种情形写的）；`off` 档连取色都跳过。卡片叠加层补「系列号」（`BookCover` 右下角，避开格式 / 状态角标），共 6 项。
- **布局**：卡片主 / 次标签可选（取不到值回退书名 / 作者，**不留空行**）；折叠系列封面五形态 —— 代表本按偏好取（`first` 首本 = 改造前 / `latest` 末册 / `first_unread` 首本未读，都读完回退首本），`stack` / `mosaic` 是**纯 CSS 多封面组合**（复用 `BookCover`，不额外请求、不做真图叠加计算）。
- **漫画**：补齐 5 项 —— 纵向连续「无间隙」档（`gapPx` 恒 0）、跨页对齐（起点奇数 / 偶数）、宽页处理（按图片**自然**宽高比 > 1.15 判定，**取不到尺寸就不判定**、回退现状）、小屏强制双页（`ResizeObserver` 量容器宽；`forceTwoPage` **默认 true** 以保持「双页与屏宽无关」的原有行为）、自动翻到下一本（末页 / 连续模式触底触发；先 `await save()` 再跳，避免卸载时的 save 来不及）。数据用既有 `api.seriesDetail` + `sortBySeriesIndex`，**零新增后端**。另订正「只支持 CBZ；CBR 后端会直接拒绝」的陈旧注释（后端早已 CBZ + CBR 双后端，缺解压器时返 503）。
- **电子书**：固定版式页宽三档（`book` 跟随书籍 = 改造前 / `single` 收成一页宽居中 / `columns` 按 50% 列宽并排），**只在 `fixedLayout` 分支生效，仍不注入任何重排设置**（守住既有原则）；设置页控件旁注明「只对固定版式的书生效」。
- **有声书**：`AUDIO_SPEEDS` 补回 1.75x（上游 0.75x–2x 六档齐，默认仍 1x）。
- **PDF**：不新增功能，仅移除错挂的「页与页之间的自定义间距（Spread gap）」（实为**漫画页**的上游条目），页尾改为一句口径说明；对照卡 + 其 import 一并删除。
- **浏览行为**：未改动（上游 3 项早已全覆盖、无对照卡）。
- 契约变化：`reader/comics` 与 `reader/audio` 的未支持清单**清零**（漫画页对照卡删除）；`appearance/layout` 4 条 → 2 条；`reader/ebook` 2 条 → 1 条；`appearance/book-covers` 仍 1 条、措辞更新为「搜索提供者 + 锁定状态」；`settingsNav` 六条 note 同步。
- 验证：前端 `type-check` 0 错 + `test:unit` 62 + `build` + `deploy`；后端全量 pytest（基线 725）；`check_doc_anchors.py` 硬错 0；无头浏览器冒烟 6 页控制台 0 错误。
- 提交：`cd9e63f`（封面样式）+ `3ebb529`（布局）+ `b88d271`（漫画）+ `7a7d133`（电子书）+ `d2ca0f4`（有声书 / PDF）+ 文档与记忆（见后续提交）。
- ⚠️ **锚点披露**：本期在 `views/ShelfView.vue`（+约 120 行）、`components/reader/ComicReader.vue`、`views/ReaderView.vue` 上加了较多行 ⇒ `docs/bookorbit-capability-gap.md` §2「书架与浏览」里指向 `ShelfView.vue` 的若干「实测行号」**整体后移**。本期未逐条重取 —— 那些锚点本就落在工具的「需人工看（该句没点名符号）」桶内（该桶 265 条、历史引用 465 条，与前两期**逐条一致**），`check_doc_anchors.py` 判「**硬错 0 / 疑似漂移 14**」与前一期**完全相同**。**下次触碰书架域时应整域重测**（对齐第 33 期的做法）。

## 第 52 期更新（2026-09-24）：外部账号同步闭环 + 服务端三项补齐

把「外部账号」与「服务端」两组设置页的剩余能力补齐为「真的能用」。全部新增能力**默认关闭**；失败不阻塞主流程；前端零外部请求（出网一律后端发起）；无真实凭据不做真实外呼验证（推送逻辑以「打桩 httpx + 断言请求形状与映射」的契约测试钉住）。

- **集成同步层（新增 `core/sync.py`）**：与 `core/integrations.py`（凭据 + 探针）分工 —— 前者管匹配 + 推送编排，后者只管凭据与探针。`SERVICES` 元数据补 `sync` / `auto_push` 默认字段，前端据此渲染。
  - 书籍匹配（三方共用）：`match()` 两段式 —— ISBN 精确 → 规范化书名+作者 → 跳过并记原因，绝不模糊强推；匹配结果仅过程内使用，不新增持久化字段。
  - Hardcover 推送：GraphQL 按 ISBN / 书名+作者 search 取对方 `book_id`（取不到跳过），写阅读状态 + 评分 + 书评；状态映射（unread/reading/finished/paused/abandoned → want_to_read/currently_reading/read/paused）；**每次响应都查 `errors`**（鉴权失败也可能是 200）。
  - Readwise 推送：`POST /api/v2/highlights/`，每批 ≤100，`external_id` 用批注稳定 id 作去重键；带笔记无划线的批注 `text` 回落章节名、`note` 放正文；限流退避，**204 才是成功**。
  - StoryGraph Cookie 校验：`verify_storygraph()` 用两个 Cookie 请求对方站点，跳登录页 / 命中登录表单即失效，200 无障碍即有效，连接异常单独归类；纯启发式，页面如实写明可能失效。
  - 统一结果 `{ok,service,matched,pushed,skipped:[{id,reason}],failed:[{id,error}],at}` + 写 1 条 `tasks` 表记录（`type='sync'`，不新增表）；自动推送（默认关）在批注 / 状态写入口旁路触发，捕获全部异常绝不阻塞。
  - 接口：`POST /api/integrations/{svc}/preview`、`POST /api/integrations/{svc}/sync`、`POST /api/integrations/storygraph/verify`；前端 `IntegrationPage.vue` 补预览 / 立即同步 / 自动推送开关 / StoryGraph 校验，未支持卡收敛（移除「同步任务」「同步历史与失败重试」，保留「反向同步」）。
- **审计日志留存（`core/activity_log.py`）**：新增 `logs.retention.{enabled,max_bytes,keep,compress}`（沿用 config 默认段 + 设置覆盖层）。`log()` 追加后按**大小**阈值（非时间）滚动归档（`activity-YYYYMMDD-HHMMSS.log[.gz]`），超 `keep` 份删最旧；用既有 `_lock` 包住。`_read_tail` 改为「当前 + 最新归档」合并再取尾 N，保证 `recent/actors` 滚动后仍连续；`clear()` 连归档一起删；`GET /api/logs/download` 仍下当前文件。降级一律吞掉不阻塞。后端随 `GET /api/logs` 返回 `storage`（bytes/archives/retention），审计页新增留存策略卡；保存配置后清 5 秒缓存。测试 `tests/test_activity_log_retention.py`（22 项）。
- **服务端字体变体（`core/fonts.py` + `stores/fonts.ts`）**：`_style_to_weight_italic` 解析子样式串 → 字重(100–900)+斜体，`_metrics` 交叉校验 OS/2 `usWeightClass` + head `macStyle`；`list_fonts`/`save_font` 项补 `weight/italic/family_key`（族名归一，解析不出留空 = 不猜）。`injectFontFaces` 为每个变体输出带 `font-weight`/`font-style` 的 `@font-face`，同族归到同一 family；阅读器选加粗/斜体命中真实变体而非合成。前端字体选择器按族分组。测试 `tests/test_font_variants.py`（7 项）。
- **收书目录 AUTO-FINALIZE（`core/metafetch.py`）**：新增 `preset_to_fields(preset)` 把合并模式预设映射到既有 `fields` 逐字段策略（overwrite/fill_only/safe_merge→fill_only/embedded_only→skip，未知回落 overwrite）。Book Dock 页新增自动定稿卡：开关→`metadata_fetch.auto_on_import`（开时一并开 `enabled`）、阈值界面 0–100↔内部 0–1、合并预设→`fields`；入库目标沿用各库自己的来源目录（不做单点设置）。测试 `tests/test_metafetch_presets.py`（5 项）。
- **配置层**：`integrations.<svc>.auto_push`、`logs.retention.*` 入 `config.py` 默认段；`EDITABLE` / `GET /api/config` / `settingsFields.SECTION_KEYS` 三处同步点已含相关键（`logs` 单开分区只提交 `logging`，避免连带提交 network/download 草稿）。
- **验证**：前端 `type-check` 0 错 + `build` + `deploy`；后端全量 pytest（**762 通过 / 0 失败**，基线 725 + 本期 34 项新测试）；`check_doc_anchors.py` 硬错 0。提交：审计留存 `ad51dee`、字体变体 `5ed287b`、自动定稿 `f99cc70`；settingsNav 六条 note 与三份文档同步。
- ⚠️ **锚点披露**：本期在 `core/fonts.py` / `core/metafetch.py` / `core/activity_log.py` / `core/sync.py` / `server.py` / `lib/api.ts` 上加了较多行 ⇒ `capability-gap.md` 指向这些文件的「实测行号」**整体后移**；本期未逐条重取，沿用「硬错 0 / 疑似漂移保留」口径，历史实施记录不改写。

## 十三、第 54 期更新（2026-09-26）：重开两项「不做」—— 语义向量 + 精确阅读位置

用户拍板把 §4.2 里仅剩的两项「有价值但不做」重开落地（`embedding` 与 `position-converter`），
module-inventory 三处判定同步改写（§2 第 27 / 46 行、§4.2 两行、§9 两行）。

**① `embedding` 语义向量（改判 已覆盖）**：

- 新增 `core/embed.py`：默认 **LSA 后端**（TF-IDF + 截断 SVD，纯 numpy、离线零下载；
  语料 = 题名 / 作者 / 系列 / 出版社 / 语言 / 年份 + **简介**（TF-IDF + L2 下「谁的字数多」
  的偏差不存在了，简介词元按 0.25 降权）；词表按文档频率封顶 4096、显式定序保证确定性；
  Gram 口径下同批书两次重算的两两余弦一致）。可选 **本地 transformer 后端**（用户自备模型
  于 `CACHE_DIR/embedding-model` 且装了 `sentence-transformers` 才启用，运行时不联网），
  缺一即回落 LSA —— **绝不引远程 embedding API**。
- 新表 `book_embeddings(book_id PK, vec BLOB, model_tag, updated_at)`：float32 小端 BLOB +
  模型标识，读端（`embed.load_vectors`）**只认当前后端 tag**，换模型后旧行自然失效不混排；
  已进 `REMAP_TABLES` / `ORPHAN_TABLES`（契约 `tests/test_remap_tables.py` 自动钉住）。
- 新端点 `POST /api/embeddings/recompute`（全量重算落库）+ 两条自愈钩子（`/similar` 缺向量
  后台补算、单库扫描完成后补算；单飞闸 `threading.Event` + 600s 节流，收尾经
  `server.wait_embed_refresh` 进 conftest `_quiesce_background` 清单）。
- `recommend.similar_books` 新增可选 `vectors` 参：两书**都有**向量 ⇒ 余弦路取语义向量
  （理由「语义相似 N%」），任一侧缺 ⇒ **逐对回落**原词袋集合余弦（理由「元数据重合 N%」）；
  「实质重合」门原样保留 —— 向量只影响排序，不改变「该不该出现」。接口出参结构不变。

**② `position-converter` 阅读位置换算（改判 已覆盖·子集）**：

- 新增 `core/epub_cfi.py`（位置换算**唯一真值源**）：`cfi_for_position` /
  `position_from_cfi`（spine 步 + 元素步 + 文本步 + 字符偏移，标准 `epubcfi(…)`）、
  `cfi_to_xpointer` / `locator_from_cfi`（兼容层）。解析用标准库 `xml.etree`
  （EPUB 内容文档本就要求良构 XML，不引新依赖；HTML 实体预处理，坏书解析失败一律
  安全回落）。**字符偏移 = 渲染正文 textContent 坐标系**（前后端同尺度：
  后端 ET text/tail 还原 DOM childNodes 数步序，前端 `contentRef.textContent.length`）。
- `progress` 表加 `cfi` 列（老库补列迁移，存量行回落 `''`）；**来源纪律**：CFI 只由
  NF 阅读器进度写入，**其它来源（KOReader / Komga / 完成标记）写入一律清空** ——
  防「章序号已变、CFI 挂旧章」的矛盾行让恢复跳错位置。
- 进度端点：PUT 可带 `offset`（章内字符偏移）⇒ 服务端生成 CFI 落库（生成失败存空串，
  **保存进度绝不因 CFI 失败**）；GET 返回 `cfi` + 服务端反解的 `offset`（前端无需在
  JS 里再实现 CFI 解析）。`ReaderView` 保存附带 offset、恢复优先用 offset 换滚动位置
  （换算不了回落「全书百分比反推」，与改造前行为逐字一致）。
- **KOReader 兼容（相对原计划的刻意保守）**：`from_nf` 下发**仍为章首 XPointer** ——
  kosync 只按 XPointer 定位 EPUB，真 CFI 它解析不了，反而不如「章首 + 精确 percentage」
  可靠；`to_nf` 仅兼容识别客户端回传的 `epubcfi(...)` 取 spine 步当章序号（crengine 的
  章内字符坐标与源 DOM 不同尺度，**不换算不落库**，那是假精度）。kobo span / kepub DOM
  仍不做（沿用原判）。

**契约测试**：`tests/test_embeddings.py`（14 项：LSA 方向性 / 确定性 / 小语料回落 /
DB 三件套 / tag 过滤 / 逐对回落 / 端点非 404）+ `tests/test_epub_cfi.py`（12 项：CFI 往返
不变量 / 坏输入 / koreader 兼容 / progress.cfi 来源纪律 / 端点往返）。另更新
`test_reading_state.py` 的进度归零断言（响应加法演进，恒带 `cfi` 字段）。
依赖：`requirements.txt` 新增 `numpy>=1.26`。
验证：后端全量 **820 passed / 0 failed**（基线 794 + 本期 26）；前端 `type-check` /
`build` / `deploy` 全绿。
- ⚠️ **锚点披露**：本期在 `core/db.py` / `server.py` / `core/koreader.py` 上加行 ⇒
  指向这些文件的既有「实测行号」整体后移（`check_doc_anchors.py` 硬错 0 / 疑似漂移 37，
  与前两期口径一致）；历史实施记录不改写。
