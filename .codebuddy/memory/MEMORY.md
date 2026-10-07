# 长期记忆（novel_dl_convert / NovelForge）

> 只放**每次都要遵守的铁律 + 一期一行的逐期索引**（体积受限、每次会话自动注入）。运行手册 / 域细节 / 跨会话待办见 `MEMORY-REF.md`（**按主题**）；第 53–105 期逐期铁律全文见 `MEMORY-PERIODS.md`（存档）；能力与缺口清单见 `docs/bookorbit/bookorbit-*.md`。
> **收尾只写两处**（第 106 期起）：`docs/roadmap-gaps-remaining.md` 本期段 + 本文件索引一行；**不再**写 `memory/YYYY-MM-DD.md`（当日日志已取消），**不再**按期号追加 `MEMORY-REF.md`。
> 📚 文档：`AGENTS.md`（AI 入口 / 硬约束 / 三处同步点）、`docs/TODO.md`、`docs/DESIGN.md`（视觉）、`docs/architecture.md` / `user-guide.md` / `development.md` / `component-api.md`；上游基线 `docs/bookorbit/`；逐期记录 `docs/roadmap-gaps-remaining.md`（最新期在末尾）。

## 硬约定
1. TXT→EPUB，NAS/容器；input/output 物理分离；FastAPI+CLI；可插拔书源。
2. **加/删功能都彻底**：路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口 404」断言。
   ⚠️ **新增白名单配置键 = 界面控件 + 代码读点，缺一即缺陷**（第 80 期立；契约 `tests/test_update_config_contract.py` 钉 `EDITABLE ⇄ 设置页 FIELDS ⇄ 读点` 一致）。
3. 写计划只四块：需求来源/功能范围/防回归要点/任务清单。
4. 提交即推送（中文 commit、按能力拆多笔）；收尾不留未提交改动；临时文件放 `/tmp`。
5. 视觉照搬 BookOrbit；局部更新不重建 DOM；**不做假交互**。⚠️「零外部请求/零依赖」第 80 期起只是**默认取向**：默认自托管不拉 CDN，允许**显式、可关、失败降级**地引入（新依赖须在 `requirements*.txt`/`package.json` 声明理由；出网由后端发起）。
6. 可能另有 AI 会话：改前 `git status`；他人改动不回退、不顺手提交；记忆只追加。⚠️ **期号会被别人用掉** —— 动手前先 `git log --oneline` 确认。
7. 书库用户手建；每库来源=多个绝对路径 `source_dirs`（JSON 数组）；`type` 只决定功能显隐。
8. **书源合规**：只接公版/授权源（盗版平台专用下载不做）；闸门判定**只有** `DownloadManager.gate_reason()`；来源名**只有** `sources.source_of()`。
   ⚠️ **第 93 期口径修订（用户 2026-10-03 拍板）**：删掉「仅放行公版源」（`download.public_only`）—— 闸门**只剩** `download.enabled`（+ `toc` 用途维度）；适配器的 `public` 字段降级为**纯标注**（书源列表徽章「公版 / 非公版」），不再参与任何过滤。上面那条「只接公版/授权源」是**使用者自己的选源准则**，不再是程序闸门；后果自负已写进 `CHANGELOG` / `docs/user-guide.md`。历史期段不改写。
9. **允许出网，且「能出网验证的就必须真的出网验证」**（第 86 期）：不许拿「网络受限」跳过真机验证、也不许把只跑过桩的结论写成「可用」；离线单测是**回归**主力，「是否真能用」要真网核一次。

## 元数据与出版
- **只落服务端 DB、绝不写回文件**；`core/publish.py` 是唯一仍写文件的模块（写副本，源只读）。
- **源不可变**：副本禁原地写（临时文件+`Path.replace`）；删除一律移回收站（`CACHE_DIR/recycle`），**从不 `unlink`**（例外：仅用户显式动作才移动磁盘文件。「删书」回收三份；「移除书库」**默认只删登记、零文件触碰**，仅 `purge_files=1` 才后台清②③）。
- 命名规则**唯一实现**=`fileops.fill_pattern`；`PATTERN_FIELDS` 唯一真值源、前端 `RENAME_TOKENS` 逐字一致；**禁第二处展开**。
- 三层 `override>online>opf`；抓取受三道正交闸（字段策略 ⊗ `meta_locks` ⊗「改过就不动」）；无值哨兵 `db.META_CLEAR="-"`。
- **软删除**：`DELETE`=置 `deleted_at`，`purge` 才真删；**一切读点须 `WHERE deleted_at=0`**。
- 作者排序名 `sort_name`（派生）/`sort_name_local`（用户覆盖），展示取 覆盖>派生；派生/回填**只写 `sort_name`**。
- 系列缺册唯一实现 `library.series_gaps`；`reading_attempts` 进 `ORPHAN_TABLES`/`REMAP_TABLES`。
- **「一棵树=一本书」唯一真值源=`core/units.py`**。

## Git / 环境 / 构建
- 行尾必须 **LF**（CRLF⇒容器 `sh /app/start.sh` 报 `set: Illegal option -`）。
- Python 3.10+（PEP 604）；Node 走 **nvm**（24.x）；本机仓库根**已有 `.venv`**（3.14）⇒ Windows 用 `.venv\Scripts\python.exe -m pytest`。
- 认证走 GCM；推送失败先查认证/网络，**别改 git config**。**切勿恢复 `docker-compose.override.yml` 名**（会静默合并成 8993+禁拉取）；NAS 部署=`docker-compose.yml` 单文件、不读 `.env`。
- ⚠️ 出网走本机代理 `127.0.0.1:7897`；根证书含自建 CA ⇒ 已设 User 级 `NODE_OPTIONS=--use-system-ca`（须完全重启 IDE 生效）。
- 🚀 **改 `VERSION` ⇒ 同批补 `CHANGELOG.md` 段**：推 `main` 后 CI 读 `VERSION`，`v<版本>` tag 不存在就**自动打 tag + 建 Release**（缺段则发布失败）；版本唯一真值源=`VERSION`（`/health` 下发），别写第二份；**首段必须是 `VERSION` 指的版本**。

## 自动化测试
- 完全离线 `pytest`（Windows `.venv\Scripts\python.exe -m pytest`，先 `$env:NODE_OPTIONS=''`）；**前端另计**（`npm run test:unit`），不并入后端计数。
- ⚠️ `pytest.ini` 已含 `addopts=-q`，**别再加 `-q`**；长跑必须**后台 `Start-Process` + 轮询 junit**（前台会被 harness 静默上限取消）。
- **新增旁路线程必须进收尾清单**；`_quiesce_background()` 须在夹具 `db.close()` **前**收尾；仓库根有**防删除守卫**（`tests/conftest.py`）。

## 后端踩坑 / 配置分层
- core 内一律 `from .. import config`（裸 `import config` 被同名命名空间包劫持，启动才炸）。
- **httpx 0.28 无 `CookieJar`**：`core/network.py` 用标准库 `http.cookiejar`。
- 版本唯一真值源=`server.APP_VERSION`（读 `VERSION`），只由 `GET /health` 下发；**无 `/api/health`**。`db` 只走 `db._connect()`。
- **新增库表列须同进 `db._LIBRARY_COLS`**，否则 `update_library` 静默写不进。
- 批量端点注册在 `/api/books/{bid}` **之前**；字面量路径在 `{param}` 之前。
- 配置四层 `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值=每库覆写 ?? 全局`。
- ⚠️ **新增「可保存的配置分区」= 三处同步点**：`server.EDITABLE` ↔ `GET /api/config` 键列表 ↔ 前端 `settingsFields.ts` 的 `SECTION_KEYS`。
- ⚠️ **偏好块 = 前后端两处真值源**：`server.PREFS_BLOCKS` ↔ 前端 `lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS`。

## 前端
- Vue3 SFC+TS+Vite+Tailwind v4+Pinia+vue-router(hash)；产物 `novelforge/static/v2/`（`/` 服务其 index.html；**勿往里加手写页**）。
- ⚠️ **视觉层=逐字照搬 BookOrbit 的 oklch token**（`assets/theme/*.css`；默认 `--tint-h: 80`）；组件**禁写死颜色/圆角/阴影**。
- ⚠️ **收尾四连**：`type-check` + `test:unit` + `build` + `deploy`（跑前 `$env:NODE_OPTIONS=''`）。`build` 只落 `frontend/dist`，**`deploy` 才同步到 `static/v2`**。
- ⚠️ **新增/删设置页三处同批改**：`settingsNav.ts` ↔ `router/index.ts` 的 `SETTINGS_PAGE_COMPONENTS` ↔ 组件（须与 `status==='ready'` 一一对应）；**设置页真实路由=`#/settings/<page.path>`**（不带分组段）。
- **全站开关唯一实现=`ui/Switch.vue`**；改偏好必须走 UI 点击；`v-model` 与同事件副作用监听器顺序不保证 ⇒ 写 `@update:model-value="x = $event; persist()"`。
- 演示数据禁 `Math.random()`；路由 path 全局唯一。冒烟用机器级 **`ui-smoke`**（`.codebuddy/tools/ui-smoke.ps1`；`-CleanOnly` 清残留）。`agent-browser` 视口是 **`set viewport W H`（子命令）**。
- ⚠️ **窄屏（≤640px）判据只有 `lib/viewport.ts`**；侧栏折叠/宽度只经 `useSidebar()`（别在页面里另建一份状态）。
  ⚠️ `ui-smoke` 一次只传**一条**路由（数组经 `.cmd` 转发逗号会被吃）；git-bash 下还得防 MSYS 改写 `#/…`。
- ⚠️ 只跑 HTTP 端到端/`ui-smoke` 仍可能漏界面缺陷（第 83 期）；**共享数组加分页会静默影响所有消费方**（第 88 期）⇒ 分页/切片数据必须有**自己的状态**。

## 逐期铁律索引（一期一行）

> 详情只在 `docs/roadmap-gaps-remaining.md`（**最新期在文件末尾**）；第 53–105 期的逐期铁律全文存档在 `.codebuddy/memory/MEMORY-PERIODS.md`；第 74 期及更早的期号↔主题对照见 `docs/TODO.md` §2 交付索引。
> **第 106 期起收尾只写两处**：① `docs/roadmap-gaps-remaining.md` 本期段（唯一叙事：根因 / 证据 / 修法 / 核验）② 本表加一行（期号 + 一句话铁律）。**不再**新建 `memory/YYYY-MM-DD.md`（当日日志 2026-10-06 起取消），**不再**往 `MEMORY-REF.md` 按期号追加。

- **≤74** 见 `docs/TODO.md` §2 交付索引 + `MEMORY-PERIODS.md`（老期号铁律全文）。
- **75–79** 删书回收三份 / `Switch` 圆点白（75）；EPUB 插图 URL 只在 `library._rewrite_assets` + `_rewrite_css_urls` 拼、书内样式独立端点**不进正文容器**（76）；跨库移动与按格式归库链（77–78）；序号单元第四形态「前缀 + 尾部编号」+ 存量自愈 + 冒烟纪律（79）。
- **80–83** `update` 四键全有读点、**假开关即缺陷**（80）；「移除书库」只删登记 + `recycle_items`（不含 `book_id`）+ 回收站还原 + `recycled_name` ≤255B（81）；首页对齐上游：两步走 / 壳上移 / 行内拖拽 / 真实数据态（82）；仪表盘余留：库范围 / 第 13 件部件 / 快速预览 / 封面上场（83）。
- **84**（**期号曾被并行会话占用**）自动更新：退避状态机（1h→6h→24h）+ 启动即检 + 更新前备份（失败即中止）。
- **85** 目录体系：`core/reading_list.py`（卷/段唯一真值源）+ `core/toc_sources.py`（**只取目录**）+ `download.toc_enabled`（默认关）；番茄/起点内置规则第 91 期真机核过（番茄书页可用 / 搜索 404）。
- **86** 书源体系 + 追更：16 接口全有界面入口；`autoupdate` 默认开启、**只调 `update_report`**；`manager.update_lock` 防并发丢章。
- **87** `.zip` 按内容分派（`zipkind.py`，`format` 归一 `CBZ`）；三处静默失败修复；重名判据收敛（**不改 `book_id` 规则**）；`format-capability-matrix.md` 契约。
- **88** 脏库读**不扫盘**（派后台 + `SETTLE_WAIT=0.25`；显式扫描仍同步）；`/api/books` 加 `limit`/`offset`（不传=全量）；书架用**独立分页源**。
- **89** `requestAck()` 修上传假报错（不解析响应体）；`ENCODING_RULE_VERSION=2`，BOM 优先 + 坏字节**不静默丢**、计数上报。
- **90** 外壳侧栏照搬上游 `ui/sidebar`（基座 `reka-ui`）：折叠态/宽度的唯一真值源 = `SidebarProvider`；窄屏断点唯一真值源 = `lib/viewport.ts`。
- **91** 未登录 401 探测归零 = `showLogin` **初值** + 抽 `bootstrapShell()`（`@authed` 必须复跑，漏了不报错）；**数 401 只能读访问日志**。
- **92** 工具页窄屏：`ui-smoke` 的 `off` 是**原始** `getBoundingClientRect()`（不过滤横滚容器内元素）；`ovf=false` **不是**没问题（溢出被横滚容器吸收、缺陷不报错）。
- **93** 在线阅读（接用户自己的书源）+ 章节缓存 + 跨客户端进度 + 读满 5 章自动落地；按用户要求删掉「仅放行公版源」；**正文净化唯一实现 = `sources/rules.html_to_text`**。
- **94** 书源导入**三条入口收敛成一条**（`sources/intake.py`；拒绝**不再回 200 装成功**）；格式轴（5 adapter）与执行轴 `base.REGISTRY` **正交**。
- **95** `AGENTS.md` 新增 **§7「工程原则」**（8 条 + 两条边界：数据安全语义与 DB 迁移**不是**兼容层）；并按 `AGENTS.md` 做了一轮合规审计。
- **96** 数据安全：⚠️ **「删除」与「覆盖」是同一条纪律** —— 任何会动用户文件的路径都必须**先 `publish.recycle`**（回收站 + 台账 ⇒ 可还原）。
- **97** 第 95 期审计四条 `[low]` 全清（用户拍板候选 C）：`gate_reason` 的 `source` 形参删除 / 死参数 / 测试专用别名 / 零消费者端点。
- **98** 仪表盘余留三条 + 一条**上游事实更正**：**页级三态**判据 = **聚合首屏真请求**（`stores/stats` + `stores/library`）。
- **99** 元数据抓取**真机核验** + 三处**线上真 bug**：① Audible 整家永远 0 结果（`response_groups` 带**非法组名** `publisher` ⇒ 接口回 400）。
- **100** EPUB 解析换成熟解析器这条待办**实测后删除**（37 本真实 EPUB 逐字段对比 ⇒ 零收益）；`dc:description` 与 `dc:title` 的需求**刚好相反**。
- **101** 书源网页抓取收口：**Goodreads 整家失效**（真结果页结构各 0 次，旧正则恒 0 条）⇒ 改用 **RSC flight payload** 解析；AWS WAF 三家分开归因。
- **102** 元数据抓取**地基**（来源声明收口 `core/sources/` + 缓存 + 限流 + 按 ID 详情 + 两个配置键）。⚠️ **不新建 `providers/`** —— `metasources.py` 就是现有可插拔系统（§7.1 第二份实现 = 缺陷）。
- **103** 把 `series` / `series_index` / `narrators` 接进抓取线（用户选 A）。⚠️ **性质是「接线」不是「加能力」**（字段早就建模）；RanobeDB 详情补全**从未生效**（0.7 < 0.75 阈值）。
- **104** 出网失败归因（用户选 A）：`core/netdiag.py` 把「DNS 解析失败 / 解析被污染 / 连接被阻断 / TLS / 代理 / 超时」分开 + 收口前端类型红。⚠️ **本机 DNS 被上游污染**（`openlibrary.org` → `31.13.x`，而 8.8.8.8 给 `199.59.149.201`）—— 看到 `dns_polluted` **先查本机 DNS，别改代码**。
- **105** ⚠️ **CI 镜像构建失败的真因：源码被 `.gitignore` 静默忽略** —— `input/` 少前导斜杠吞掉 `frontend/src/components/ui/input/`（第 90 期新增）⇒ CI 从 clone 构建报 `[UNLOADABLE_DEPENDENCY]`；**本机文件一直在 ⇒ 本地永远绿**（「本地复现」不算证明，要用干净 clone 验）。防回归 `tests/test_source_tracking_contract.py`。
- **106** 记忆体系精简（用户 m08584）：**收尾只写两处** = roadmap 本期段（唯一叙事）+ 本表一行；`MEMORY-REF.md` 改为**按主题**的域手册（不再按期号追加）；**当日日志取消**；第 53–105 期逐期全文存档 = `MEMORY-PERIODS.md`（只读）；三个文件名一律不动。
- **107** 自动化收尾（用户 m08782「再谈自动化」）：机械的几处交给 `tests/period_close.py` —— `new` 一次落位 / `check` 只读对账 R1–R8；⚠️ **工具只摆位置、不写叙事也不提炼**，缺锚点或期号已占用**整体拒绝**（绝不改一半）、**不猜数字**（没给 `--numbers` 就让人手改）、逐文件保住**行尾与 BOM**（否则假 diff）。⚠️ **对账不能追溯历史**：§2 是第 62 期才开始记的（53–61 无行）、74/78 反过来 ⇒ `STRICT_FROM=107`，历史错位只 warning（补一条从来没存在过的记录 = 编造）。
- **108** 阅读动线四改（用户 m09151；五处歧义经 m09230 全部选推荐项）：仪表盘封面**直接开书**（`frontend/src/lib/bookOpen.ts` 的 `openTargetOf` 是唯一真值源，端点读不动的格式去详情页）／侧栏抽屉判据从「纯宽度」改成 `DRAWER_QUERY = 窄屏 or (pointer: coarse and ≤1023.98px)`（手机横屏与平板收起，桌面窗口拖窄仍两栏）／阅读路由**整屏沉浸 = 外壳根本不渲染**（`/listen` 刻意不在内：它是播放器不是阅读界面）／设置面板补 document 级 `click` + `contains` 收面板（用 click 冒泡而非 pointerdown ⇒ 翻页模式下只收面板、不翻页）。⚠️ 三条教训：**本仓 SPA 是 hash 路由**（探测要用 `#/read/<id>`；`location.pathname` 恒为 `/`，按路径导航拿到的是服务端 404）／**VTU 默认挂游离树**，测 document 级监听的用例必须 `attachTo: document.body`，否则会以「看着像产品 bug」的形式假红／新增前端 spec 必须登记进 `tests/test_frontend_unit_contract.py` 的 `EXPECTED_SPECS`，否则全量 pytest 红。
  第 108 期补记（用户 m09721 追问「确保满足响应式了吗？」）：真机横扫（CDP，17 视口 × 5 路由 = 12 触屏 + 5 鼠标）
  **FAILS=0**，但查出一个**既有**缺陷并已修 —— 阅读设置面板 `absolute right-0 w-72` 的定位父节点是那颗 38px 宽的按钮
  （它右侧还有「切换模式 / 书签 / 笔记」≈138px），320px 视口面板 x=-118、左半边被祖先 `overflow-hidden` **裁掉**（看不见也滚不回来）；
  修法 = `relative` 挂到工具栏**整行**（`frontend/src/views/ReaderView.vue:2378`）+ 面板 `max-w-full`（该缺陷 `ac1906d` 起就有）。
  ⚠️ 横扫探针的两条假警报：元素右边缘越界**不能**直接算页面溢出（横向滚动容器、`transform` 停在屏外的抽屉、`inert`/`aria-hidden` 都要排除）、
  CDP 非触屏档不能传 `maxTouchPoints: 0`（回 `Touch points must be between 1 and 16`）。

- **109** 发版 V1.0.0（用户 m09886）：把第 95–108 期连续十四轮「只提交不发版」的积累一次性发布；镜像起多推一个 `:1.0.0` 版本 tag（NAS 端可固定版本 / 需要时回滚）。
  ⚠️ 发版段正文**第一行必须是 `### ` 分组标题**（`tests/test_changelog_render.py` 断言 `startswith("### ")`，且 `changelog.main()` 输出里必须含写死的 `### 新功能`）—— `>` 领起的一段话不算段首；而 `note` 收的是本节内**任意** `>` 行，所以「`### 新功能` + 一段话 + `### 口径变化（如实记录）`」既满足契约、也满足用户「只写一段话、不逐项罗列」。
  ⚠️ `VERSION` 一改就必须**同批**改 `CHANGELOG.md`（取段失败 ⇒ `release.yml` 退 1、发布失败）；反过来 `tests/period_close.py` 的 R7 原本按整篇文本扫 `` `VERSION` 仍 0.94.0 ``，而 `docs/TODO.md` §2 是**逐期历史**（第 95–106 期都写着旧版本）⇒ `--fix` 会一次改掉 **12 行历史**（第 109 期第一次真发版才暴露）；现在 R7 与 `--fix` 都跳过 `| …` 表格行（新契约 `test_S2_历史行里的旧版本字面量不算漂移`）。
  ⚠️ `new` 的索引行改插在**整段索引末尾**：上一条的缩进续行不再被切到新条目底下（同一个坑第二次暴露）。
  ✅ 核过（推送后按 REST）：`origin/main == 5727744`，head 上 `Release`（run `37408546297`）与 `Build and Push Image`（run `37408546232`）都 success；
  tag `v1.0.0` → `5727744`、Release 建出（notes 1639 B、首行 `### 新功能`）；镜像 `:1.0.0` / `:latest` / `:<sha>` 三个 tag 取 manifest 均 **200**（编造的 tag 回 404 做对照）。
  ⚠️ **GHCR 的 `tags/list` 有缓存** —— 构建 success 十几分钟后它仍只列 `latest` + 旧 sha，`1.0.0` 与新 sha 都不在（差点据此误判「版本 tag 没生效」）⇒ 判 tag 要**按 tag 取 manifest**。没核：镜像内 `APP_VERSION` 标签（本机到 ghcr.io 反复 `SSL: UNEXPECTED_EOF_WHILE_READING`）、NAS 端实拉。
  ⚠️ 本机新的编码坑：`write` 工具落的 `.ps1` 是**无 BOM UTF-8**，Windows PowerShell 按 GBK 解 ⇒ 全角字符把字符串打断（`字符串缺少终止符: "`，脚本一行没跑）；`.ps1` 只用 ASCII 或写成带 BOM。
- **110** MOBI/AZW3/AZW **直读 = 解包，不是转换**（用户 m00255「mobi直接阅读，不进行转化」+ m00226「有成熟功能和模块的，不要自研」）：`core/mobicache.py` 把书自身 KF8 内容解包到 `CACHE_DIR/mobi-unpack/<book_id>/`（**不进书库、不写回源文件**）；KF8 出真 EPUB ⇒ 目录/正文/插图/书内样式/**CFI 与批注**全复用，纯 MOBI6 出 HTML ⇒ 如实降级（无插图/样式、`cfi` 留空）。⚠️ **四个读点（目录表 / 单章 / 资源与样式 / 进度 CFI）必须收敛到一个「读目标」判据**（`mobicache.read_target`）—— 第 87 期那四条不一致就是同一判据写四遍的产物。⚠️ 教训：`elif suffix in mobicache.EXTS:` 里再 `from . import mobicache` 会让它成**局部名**而条件先求值 ⇒ `UnboundLocalError`、**详情接口全线 500**（延迟导入必须放分支第一行）；`.azw` 进白名单要 `SCAN_RULE_VERSION` 2→3。⚠️ 本机跑 pytest 除清空 6 个 proxy 变量外还有两道沙箱坎：`0o700` 目录**不可枚举**（垫片把 `os.mkdir` 的 0o700 改 0o777）、`--basetemp` **不能放仓库根**（conftest 有仓库根防删除守卫）；前端命令（vite 起子进程）在受限沙箱下必然 `spawn EPERM` ⇒ 需提权一次。⚠️ 许可证：`mobi` GPL-3.0-only + 既有 `EbookLib` AGPL-3.0 ⇒ 本项目整体 **AGPL-3.0**（首次补 `LICENSE` + `THIRD-PARTY-NOTICES.md`；`quickjs` 上游未标注许可证）。
