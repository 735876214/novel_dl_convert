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
| 14 | `book-metadata-lock` | 8 | §3 | **✗** | **漏项候选** | **字段级锁定**：13 个 provider id + 11 个漫画字段可锁，防自动抓取覆盖 |
| 15 | `book-move` | 12 | §2 书架 | ✓ | 已覆盖 | **第 36 期已落地**（原为漏项候选）：跨库移动（预检 + 逐本进度 + 目标库相容闸门）；「目标库权限」在单用户下的等价物 = **库类型相容闸门**，原判与落地见 §4.2 该行 |
| 16 | `book-request` | 131 | §9 求书 | ✓ | 已拍板不做 | 第 32 期已决策不做（含 indexers / download-clients / plugins 三大子树） |
| 17 | `book` | 56 | §3 | ✓ | 已覆盖 | 含 `reading-attempt`（重读尝试）⇒ 见第 64 行 `user-book-status` |
| 18 | `bookmark` | 14 | §4 | ✓ | **漏项候选** | **书签**（CFI 定位 / 软删 / tombstone 复活 / 冲突合并），本项目**零出现** |
| 19 | `browse-counts` | 6 | §1 | ✓ | **漏项候选** | 侧栏 Browse 徽标三计数（作者 / 系列 / 批注），60 s 缓存 |
| 20 | `catalog` | 9 | §10 | ✓ | **漏项候选** | **跨实体搜索**（作者 / 题材 / 标签 / 演播者 / 出版社 / 系列 / 语言 / 收藏） |
| 21 | `collection` | 13 | §1 | ✓ | 已覆盖 | 收藏夹（含拖拽排序） |
| 22 | `cover` | 22 | §3 | ✓ | 已覆盖 | 4 个封面 provider（audiobookcovers / duckduckgo / itunes）—— 本项目封面抓取已落地 |
| 23 | `custom-icon` | 11 | §1 | ✓ | 已拍板不做 | 图标风格 + 上传 + 排序：`roadmap-gaps-remaining.md:785-787` 已判「成本远超收益」 |
| 24 | `custom-metadata` | 9 | §3 | ✓ | **漏项候选** | **自定义字段的「定义」**（建字段 / 排序 / 改标签 / 切适用书库 / 归档 / 软删恢复永久删） |
| 25 | `dashboard` | 22 | §6 | ✓ | 已覆盖 | 第 32 期已对齐 12 件部件 |
| 26 | `email` | 79 | §7 通知与更新 | ✓ | **漏项候选** | **邮件分发整块**（书籍附件 / 模板 / 收件人组 / 发送日志 / 加密凭据 / SMTP） |
| 27 | `embedding` | 9 | §6 | **✗** | **漏项候选** | **元数据特征向量**（作者 / 题材 / 评分构成，非语义 embedding），服务第 52 行推荐 |
| 28 | `entity-manager` | 30 | §5 | ✓ | 已覆盖 | 9 个实体策略（作者 / 题材 / 语言 / 演播者 / 出版社 / 系列 / 标签 / 内联 / 联结） |
| 29 | `file-write` | 94 | §5 | **✗** | **不与本项目定位相容** | **把元数据写回文件本身**（EPUB/FB2/MOBI/PDF/CBZ/音频 6 类 writer）—— 与发布三原则冲突 |
| 30 | `font` | 18 | §1 | ✓ | 已覆盖 | 阅读器自定义字体上传 / 校验 / 元数据解析 |
| 31 | `hardcover` | 32 | 三方同步 | ✓ | 已拍板不做 | 用户 2026-09-20 拍板本轮不做（§13） |
| 32 | `health` | 9 | §1 | ✓ | 已覆盖 | 健康检查（本项目有 `/api/health`） |
| 33 | `kobo` | 67 | §10 | ✓ | 已覆盖 | 本项目已实现 Kobo 同步的可用子集（第 7 / 31 期） |
| 34 | `koreader` | 62 | §10 | ✓ | 已覆盖 | 本项目已实现 kosync 协议服务端（`settingsNav.ts:397` 有完整口径记录） |
| 35 | `library` | 26 | §2 | ✓ | 已覆盖 | 多库实体 + 定时扫描（第 10 期） |
| 36 | `maintenance` | 11 | §5 | ✓ | 已覆盖 | 缺失资源巡检（含孤儿封面目录） |
| 37 | `metadata-fetch` | 121 | §3 | ✓ | 已覆盖 | 13 个 provider（aladin / amazon / audible / audnexus / comicvine / goodreads / google / hardcover / itunes / kobo / librofm / lubimyczytac / open-library / ranobedb） |
| 38 | `metadata-preferences` | 20 | §3 | ✓ | 已覆盖 | 字段级写入策略 + provider 开关 + provider 链接设置（第 30 期） |
| 39 | `metadata-score` | 9 | §3 | ✓ | 已覆盖 | 第 29 期（`core/metascore.py` 12 字段加权） |
| 40 | `metadata` | 70 | §3 | **✗** | 已覆盖 | 提取器 + 解析器（epub / fb2 / mobi / pdf / cbz / 音频 6 类）—— 本项目 `core/metadata.py` 对等 |
| 41 | `migration` | 89 | — | ✓ | **漏项候选** | **从其他系统迁移整块**（Audiobookshelf / Booklore / Calibre-Web-Automated / Grimmory） |
| 42 | `narrator` | 5 | §11 | **✗** | **漏项候选** | **演播者实体**（规范化 / sort name / 按书替换）—— 本项目仅命名模板有 `{narrators}` 且**已记缺失** |
| 43 | `notification` | 11 | §7 | ✓ | 已覆盖 | 通知浮层 + 已读 + 清理 job |
| 44 | `opds` | 23 | §10 | ✓ | 已覆盖 | 第 7 期（OPDS 1.2 + 独立凭据） |
| 45 | `path` | 9 | §5 | ✓ | 已拍板不做 | 路径策略（`GET config` / `GET` / `POST`）—— 服务于第 16 行求书的远程路径映射 |
| 46 | `position-converter` | 17 | §4 / §10 | **✗** | **漏项候选** | **跨阅读器位置换算**（CFI / kobo span / XPointer / kepub DOM），服务 Kobo 与 KOReader 的进度互通 |
| 47 | `reader` | 12 | §4 | ✓ | 已覆盖 | 阅读器服务端（epub + cbz 两子树） |
| 48 | `reader-preferences` | 7 | §4 | ✓ | 已覆盖 | 第 32 期已落地 |
| 49 | `reading-session` | 17 | §4 / §6 | ✓ | 已覆盖 | 阅读会话（本项目 `reading_sessions` 表对等） |
| 50 | `reading-state` | 7 | §4 | ✓ | **漏项候选** | **重置一本书的阅读状态**（删会话 + 删进度 + 重置状态），本项目零出现 |
| 51 | `readwise` | 20 | 三方同步 | ✓ | 已拍板不做 | 同上（§13） |
| 52 | `recommendation` | 8 | §3 / §6 | ✓ | **漏项候选** | **打分排序的推荐**（元数据向量余弦 0.5 + 作者 0.1 + 题材 0.25 + 系列 0.1 + 评分距 0.05，上限 25） |
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

**计数核对**：已覆盖 40 ＋ 已拍板不做 11（含 `custom-icon` / `path`）＋ 漏项候选 13 ＋ 非能力 1 ＋ 与定位无关 1
（`seed`）＋ 与定位不容 1（`file-write`）＝ **67** ✓

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
| `kobo` | §10 | 已覆盖 | `whats-new` | §7 | 已覆盖 |
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
| `bookmark` | `bookmark.service.ts`：按 CFI / 位置创建、软删、tombstone 复活、并发冲突合并 | **已落地**（原为「零」）：`bookmarks` 表 + 六条路由 + 阅读器工具条开关与书签档（活跃 / 垃圾桶）；对齐上游三形态：**位置去重 / 墓碑复活 / 并发合并** | `novelforge/core/db.py:894` `save_bookmark`、`novelforge/server.py:1957-2033`、`frontend/src/views/ReaderView.vue:1053`/`:1150`（工具条开关 / 书签档面板）；能力键 `bookmarks`（仅 ebook / mixed） |
| `reading-state` | `reading-state.service.ts`：`POST /books/:bookId/reset-reading-state`，删会话 + 删进度 + 重置状态 | **已落地**（原为「零」）：详情页「我的记录 → 从头开始」；**只删读出来的痕迹**，批注 / 书签 / 评分 / 收藏与磁盘文件一律不碰 | `novelforge/core/db.py:3472` `reset_reading_state`、`novelforge/server.py:1727`、`frontend/src/components/book/ReadingRecord.vue:137` |
| `catalog` | `catalog.service.ts`：7 个实体维度的搜索（作者/题材/标签/演播者/出版社/系列/语言）+ 收藏；按可见库收窄 | **已落地**（原为「全局搜索只跨书」）：新页 `/browse`「实体总览」按**六个**维度浏览本地书目、按当前书库收窄；**不新增聚合接口**（这些维度本就是同一份书目的投影） | `frontend/src/views/BrowseView.vue:51`（维度表）、`frontend/src/router/index.ts:174`、`frontend/src/data/nav.ts:72`；「收藏」维度靠 `/api/books` 附带的 `collection_ids`（`novelforge/core/db.py:1063` `collection_map()`） |
| `browse-counts` | `browse-counts.service.ts`：侧栏 Browse 三计数，60 s 缓存 | **已落地**（原为「无计数」）：三计数与目标页**同源**、60 秒节流、按库可选收窄；读失败不显示胶囊 | `novelforge/core/browse_counts.py:25`/`:65`、`novelforge/server.py:3572`、`frontend/src/data/nav.ts` 的 `countSource: 'browse'` + `frontend/src/components/AppSidebar.vue` 的 `navCount()` |

### 4.2 有价值但不做（8 项；其中 3 项第 35 期、1 项第 36 期改判为做并落地，行内 ⚠️ 标注）

| 模块 | 上游形态 | 不做的理由 |
| --- | --- | --- |
| `book-move` | 跨库移动（preview + SSE 逐本进度 + 目标库权限） | 本项目多库是**独立目录**（`LIBRARY_SOURCE_DIR`），移动 = 真搬文件 + 处理同书冲突 + 回滚。上游那种「先预览再流式搬」的完整度不做会留半成品，做全了是独立一期。⚠️ **第 36 期由用户改判为做并已落地**（原判末句「做全了是独立一期」正是本期立项理由）：**两条入口共用一个执行层** —— 自动归库 `migrate.preview:172` / `plan:258`（行为逐字未动）与用户发起的移动 `migrate.move_preview:571` / `move_plan:594`，共用 `execute:947` / `rollback:1041`（批次用既有 `library_migrations.direction` 列区分）—— 接口 `POST /api/book-move/{targets,preflight,plan,apply,rollback}` + `GET /api/book-move/batches`（`novelforge/server.py:3226`/`:3236`/`:3251`/`:3277`/`:3344`/`:3367`），前端书架批量条「移动到书库」+ 三段式弹窗（`frontend/src/views/ShelfView.vue:678`、`frontend/src/components/book/BookMoveDialog.vue`）+ 「撤销本次移动」（`ShelfView.vue:692`）。**三处刻意差异**：① **不引入 SSE**（全仓零先例），逐本进度走既有「SQLite 任务行 + 前端轮询」；② 「目标库权限」在单用户下的等价物 = **库类型相容闸门**（判据只许来自 `library._exts_for_type`，前端禁选是体验、后端 400 才是契约）；③ 同名冲突按用户口径「拒绝覆盖 + 一键用建议名移入」。**开工前先修掉一条既有缺陷**：`meta_override` / `meta_online` / `meta_cover` / `scrape_items` 四张按 `book_id` 存的表原先**不在搬迁清单**里 ⇒ 移动或改名一次就断链（修法见 `core/db.py:1633` 的 `REMAP_TABLES` / `:1643` 的 `REMAP_EXPLICIT_TABLES` / `:1655` 的 `REMAP_MERGE_TABLES`） |
| `book-metadata-lock` | 13 个 provider id + 11 个漫画字段的**字段级**锁定 | 本项目已有**单书级**「覆盖 / 保留」三态语义（`server.py:1183-1350` 的元数据 GET / POST / online / revert 四个端点）。字段级锁定是把它拆细，收益主要是自动化抓取场景 —— 而本项目的自动抓取默认关，收益面窄。⚠️ **第 35 期由用户改判为做并已落地**：新表 `meta_locks`（`core/db.py:379`，`PRIMARY KEY(book_id, field)`；「刻意与 `meta_override` 分表」的理由在 `:374-378` 的建表注释里 —— override 行只在**有值**时存在，表达不了「我没改过、但也不想让抓取动它」）。抓取闸门落在 `core/metafetch.py:207`（10 个字段）与 `:222`（封面，独立键 `cover`），在线确认写入另在 `:335-349` 再挡一道；接口 `POST /api/books/{bid}/metadata/lock`（`server.py:1352`）。**可锁对象 = `fileops.METADATA_FIELDS` 的 10 个 + 封面**（上游是「13 provider id + 11 漫画字段」，本项目无多 provider / 漫画字段之分，换算后即这 11 项）。**与三态互不干涉**：三态管「取谁的值」，锁管「让不让抓取写」 |
| `custom-metadata` | 自定义字段的**定义**（建字段 / 排序 / 改标签 / 切适用书库 / 归档 / 软删恢复） | 本项目 `custom_fields` 是**抓取时的固定键值对**，不是用户可定义的字段 schema；原判另称「做成 schema 要动元数据模型 + 12 字段的 metascore 权重表」。⚠️ **第 35 期由用户改判为做并已落地，且原判理由有一处经核为误**：① 实测那次再核时 `custom_fields` 的编辑入口**已经不存在**（`frontend/src/views/settings/pages/MetadataPage.vue` 里零命中），原锚点已失效；② 「要动 12 字段的 metascore 权重表」**不成立** —— `custom_fields` 本就在 `NOT_SCORED`（`novelforge/core/metascore.py:80-84`，why =「用户自定义键值，不参与完整度」），**权重表一行没动**。落地 = 定义表 `custom_field_defs`（`core/db.py:343`，`key` 与 `label` 分离、`type` / `position` / `library_ids` / `archived` / `deleted_at` 垃圾桶）+ 值表 `book_custom_values`（`:366`）+ 七条路由 `server.py:1404-1516`；同名配置项 `metadata_fetch.custom_fields` **已整体下线**（默认值 / 顶层白名单 / 编辑器 / note 文案 / 文档引用一并清理）。**级联**：`book_custom_values` 与 `meta_locks` 均已进 `ORPHAN_TABLES`（`core/db.py:1568-1569`）与 `REMAP_TABLES`（`:1619-1622`），改名时**逐行搬迁、撞主键保留目标行** —— 照第 34 期书签的范式（整体 `UPDATE` 撞唯一约束会被外层 `except` 吞成「搬 0 行」而静默丢数据） |
| `recommendation` + `embedding` | 元数据特征向量 + 加权打分（余弦 0.5 / 作者 0.1 / 题材 0.25 / 系列 0.1 / 评分距 0.05），上限 25 | 本项目 `core/recommend.py` 已有**规则式**相似书（同作者 / 题材 / 系列）。上游那套的价值全在**排序质量**，而它的向量是元数据特征（不是语义 embedding）。⚠️ **第 35 期改判「`recommendation` 做、`embedding` 仍不做」并已落地**：权重与形态对齐上游（`core/recommend.py:29-33` 的五个权重、`:36-37` 上限 25 / 默认 6）；原判顾虑「没有评分数据的库里会退化到接近规则式」**用降级口径化解** —— 任一方未评分时**那一路不进分母**（`:116-120`、`:163-166`），而不是当 0 分。**刻意差异两处已写进模块 docstring（`:10-22`）**：向量用元数据词袋（作者 / 题材 / 系列 / 出版社 / 语言 / 十年段 / 书名词元，**简介刻意不进**），且保留一道「实质重合」门（至少同作者 / 同题材 / 同系列之一才算候选）—— 上游权重决定**排得好不好**，这道门决定**该不该出现**。`embedding`（语义向量）**仍然不做** |
| `position-converter` | CFI / kobo span / XPointer / kepub DOM 四向换算 | 只服务多设备进度互通。本项目的 Kobo / KOReader 支持**已按可用子集落地**（`settingsNav.ts:397` 记了完整口径与「反向只定位到章首、准确位置由 percentage 兜底」的取舍）—— 补全的收益在单用户单设备下很低 |
| `email` | 邮件分发整块（附件 / 模板 / 收件人组 / 发送日志 / 凭据加密 / SMTP） | 79 个文件。价值是「把书发到 Kindle 邮箱」这类，但需要 SMTP 凭据管理 + 失败重试 + 附件大小限制一整摊。**与「本地单用户书库」的定位偏离**，且本项目离线优先 |
| `narrator` | 演播者实体（规范化 / sort name / 按书整体替换），5 个文件、**无对外路由** | 实测本项目后端**一个 `narrator` 字样都没有**（`novelforge/**.py` 零命中），前端只在命名模板里记着 `{narrators}` 属缺失 token（`FileNamingPage.vue:185`）。要立实体得**先有音频标签的演播者解析**这一环，前置缺失；而演播者不像作者需要独立浏览页 ⇒ 收益面窄 |

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
