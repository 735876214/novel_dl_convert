# 长期记忆（novel_dl_convert / NovelForge）

> 只放**每次都要遵守的铁律**（体积受限）。逐期事实写 `YYYY-MM-DD.md`；**逐期铁律原文 / 运行手册 / 域细节 / 跨会话待办**见 `MEMORY-REF.md`；能力与缺口清单见 `docs/bookorbit/bookorbit-*.md`。
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

## 逐期铁律索引（**全文见 `MEMORY-REF.md`「逐期铁律原文」+ `docs/roadmap-gaps-remaining.md`**）
- **75–79** 删书回收三份 / Switch 圆点白（75）；EPUB 插图 URL 只在 `library._rewrite_assets`+`_rewrite_css_urls` 拼、书内样式独立端点**不进正文容器**（76）；移除「按格式归库」链、**跨库移动 `/api/book-move/*` 保留**（77）；版本真值源=`VERSION`（78）；序号单元**第四形态**（编号须**紧贴**标题）+ `SCAN_RULE_VERSION` 自愈（79）。
- **80–83** `update` 四键全有读点、假开关即缺陷（80）；「移除书库」只删登记 + `recycle_items`（**不含 `book_id`**）+ 回收站还原 + `recycled_name` ≤255B（81）；首页对齐上游、显式依赖 `vue-draggable-plus`、`WidgetId` 键不改（82）；`ShelfDef.library_ids` **空=全部书库**、第 13 件 `reading-time`、`BookPreviewDialog` **Teleport to body**（83）。
- **84**（**期号已被并行会话占用**）自动更新：退避状态机（1h→6h→24h）+ 启动即检 + 更新前备份（失败即中止）。
- **85** 目录体系：`core/reading_list.py`（卷/段唯一真值源）+ `toc_sources.py`（**只取目录**）+ `download.toc_enabled`（默认关）；⚠️ 番茄/起点内置规则**第 91 期真机核过**（番茄书页可用 / 搜索 404、起点两条都不可用 ⇒ **仍留 `verified=false`**，结论见第 91 期）。
- **86** 书源体系 + 追更：16 接口全有界面入口；`autoupdate` 默认开启、**只调 `update_report`**；`manager.update_lock` 防并发丢章。
- **87** `.zip` 按内容分派（`zipkind.py`，`format` 归一 `CBZ`）；三处静默失败修复；重名判据收敛（**不改 `book_id` 规则**）；`format-capability-matrix.md` 契约。
- **88** 脏库读**不扫盘**（派后台 + `SETTLE_WAIT=0.25`；**显式扫描仍同步**）；`/api/books` 加 `limit`/`offset`（不传=全量）；书架用**独立分页源**。
- **89** `requestAck()` 修上传假报错（不解析响应体）；`ENCODING_RULE_VERSION=2`，BOM 优先 + 坏字节**不静默丢**、计数上报。
- **90** 外壳侧栏照搬上游 `ui/sidebar`（基座 `reka-ui`）：折叠态/宽度的**唯一真值源=`SidebarProvider`**（`stores/ui.ts` 的 `sidebarCollapsed`/`toggleSidebar` 已删）；窄屏断点唯一真值源=`lib/viewport.ts`（**639.98px，不跟上游 768**）；侧栏偏好**只落本机**（`nf_sidebar_*`，**不进** `PREFS_BLOCKS`）；默认宽度 **240**（非上游 256）；取菜单行认 `data-sidebar="menu-button"`（`data-slot` 会被 tooltip 触发器顶掉）。
- **91** 未登录 401 探测归零 = `showLogin` **初值**（`auth.authenticated` 同步可读）+ 抽 `bootstrapShell()`，**`@authed` 必须复跑**（漏了不报错、只是登录后永不加载）；**数 401 只能读访问日志**（`performance.getEntriesByType('resource')` 拿不到状态码）。窄屏顶栏 7 个入口**只有**「更多」一条路 ⇒ 判据走 `useNarrowScreen()`、`v-if` 而非 CSS 隐藏。**浮层菜单（`DropdownMenu`）键盘**：`Teleport` 到 body ⇒ Tab 序跑到页面末尾、`Esc` 无人监听 ⇒ 补「入焦首项 / ↑↓ 循环 / `Esc`·`Tab` 关闭并把焦点还给触发器」。`metadata_fetch.source_weights` 排序键 `(-weight, language_tier)`，归一**只有** `metasources.weight_of()`（**全 0 必须与现状逐字一致**——靠 `sorted` 稳定性）。番茄「书页可用 / 搜索 404」、起点两条都不可用 ⇒ **两条都保守留 `verified=false`**。`note` 是纯文本插值 ⇒ **不许写 markdown**。`docs/TODO.md` 只放「还没做的」。
- **92** 工具页窄屏：`ui-smoke` 的 `off` 是**原始** `getBoundingClientRect()`、**不过滤横滚容器内元素** ⇒「反正能横滑到」不算达标；`ovf=false` **不是**没问题（横滚容器把溢出吸收了，缺陷**不报错**）。工具页外壳**两处**都拆了横滚（内容区 `min-w-[32rem]` + 标签条）；标签条改 `flex-wrap`（**不做固定断点**——侧栏可拖 224–480，断点算不准）⇒ 窄屏（<640，与 `NARROW_QUERY` 同档的 `sm:`）另配原生 `<select>`，**换控件不是隐藏**（两条路必须同一份 `visibleSections`）。`<input>/<textarea>` 进栅格/flex 轨道**必须带 `min-w-0`**（`w-full` 不够，固有 min-content 会撑破）。契约 `tests/test_tools_layout_contract.py`。
- **93** 在线阅读（接用户自己的书源）+ 章节缓存 + 跨客户端进度 + 读满 5 章自动落地 + 单本「检查更新」；按用户要求**删掉「仅放行公版源」**（见硬约定 8）。**正文净化唯一实现 = `sources/rules.html_to_text`**（从三份收敛；`get_text("\n", strip=True)` 会把内联标签切成独立行，须 `get_text("")` + 逐行 strip + 只给块级标签补分段）；**两份位置故意不合并**（`online_bind.pos` = 在线位置 = 跨客户端续读唯一依据；`progress` = 本地位置；`align_online` 5 章窗口 ≥3 同名时**同时**写，`local_index === null` **不是异常**、前端**只读**服务端算好的值）；在线读**写盘点限死 `CACHE_DIR/online/`**（200 MB / 单本 500 章，真 LRU）、第三方标记**永不进 `v-html`**；自动落地走 `core/landing.py`、**写进这本书自己的位置**（同 `book_id`、**绝不新建第二条书目**）、`len(seen) > 5` 且 `auto_task` 空才触发**一次**，且**追更只写「收书目录原件」+「本项目成品」两份** ⇒ 用户自己导入的书**换不到**（如实拒绝、零写入）；首次落地按**书自身后缀**挑产物（否则 EPUB 字节写成 `.txt`）；`Esc` 收面板要**一次一层 + 焦点还给触发按钮 + 没面板时不吞键**（放在 `if (!paged.value) return` 之前）。
- **94** 书源导入**三条入口收敛成一条**（`sources/intake.py`；拒绝**不再回 200 装成功**）；格式轴（5 adapter）与**执行轴 `base.REGISTRY` 正交**，adapter 只 sniff/parse/map/serialize、**不产出第二套可执行结构**；**「引擎能执行什么」唯一真值源 = `rules.MODES` + `audit_native_rule`**（转换器不许自评可用 ⇒ 22 条真样本上 `yes` 9→2、假可用 6 条改判 `partial`）；**全字段报告 `field_report` 与 `unsupported_fields` 分工不同、不许合并**（合并会把 1321 条带发现页的源全判死）；`_IMPORT_ROW_KEYS` 白名单漏键 ⇒ 接口上拿不到（native 行也要有这个键，空列表）；⚠️ **重建响应体必须摘掉 `Content-Encoding`/`Content-Length`**（否则 httpx 解两遍，**所有开 gzip 的真实站点全挂**，而单测 100% 绿）；⚠️ quickjs 只有 cp38–cp312 包（`python_version < "3.13"` 标记不能少）；⚠️ `POST /api/sources/import` 的键是 `payload` 不是 `content`、`import-url` 的 `dry_run` 默认 true；调 `ledger.plan` 的用例必须带 `isolated` fixture。
- **95** `AGENTS.md` 新增 **§7「工程原则」**（8 条：不为向后兼容留路 / 最简实现 / 分层生长 / 模块化 / 优先成熟库 / 先查已有依赖 / 长期决策 / 先研究成熟产品；边界：**数据安全语义与 DB 迁移不是兼容层**）。按 `AGENTS.md` 做了一轮合规审计（`docs/agents-audit-95.md`，四轴 + 逐条复核）并整改。⚠️ **本机跑 pytest 前必须清空全部代理变量**（`NO_PROXY` 里的 `[::1]` 让 httpx 生成畸变 mount ⇒ **45 个用例假失败**，已写进 §5）。⚠️ **「删功能要删干净」= 路由 + 模块 + 前端 api/store/类型 + 文档 + 「接口 404」断言**（本轮删的两个端点各补了一条 404 用例）。⚠️ **「格式中文名」唯一产出点 = `sources/formats/base.py:format_label`，由后端下发 `format_label`**（前端 `FORMAT_LABELS` 那份第二份表已删）。⚠️ **文件名安全判据唯一实现 = `core/filename.py`**（叶子模块；`komga.clean_segment` 与 `fileops.sanitize_stem` 共用，**两者「折不折叠内部空白」的差异是刻意的**）。⚠️ **版本兜底不许是像样的版本号**（原 `"0.80.0"` 会掩盖「部署缺 VERSION」）⇒ 改哨兵 `0.0.0-unknown`。⚠️ **组件里不许自创颜色**已有守卫 `tests/test_visual_tokens_contract.py`（禁止 `bg-[#…]` 任意值与已作废的 `#2563eb`/`#6366f1`；`charts.cssVarHex()` 是「CSS 变量→色串」唯一实现）。⚠️ **不要用 PowerShell `Get-Content -Raw`/`Set-Content` 改这些 UTF-8 文件**（中文会被写坏）。
- **96** 数据安全两处口径落地（第 95 期审计批次 8）：⚠️ **「删除」与「覆盖」是同一条纪律** —— 任何会动用户文件的路径都必须**先 `publish.recycle`**（回收站 + 台账 ⇒ 可还原）。① `core/zipkind.py` 的 `remove_source` 此前是全仓**唯一**一次真 `unlink` ⇒ 改成 `recycle`（回收失败进 `source_note` 且原文件保留；**函数内局部 import `publish`** —— 顶层会与 `library` 成 import 环）；② `core/landing.py` 的整本覆盖（自动落地 + 显式的「用源站整本覆盖本地」）**写盘之前**先把 `dest` 与 `txt_dest` 移入回收站（用 `_same_path` 去重：单目录部署下两者**是同一个文件**），**回收失败即中止、盘上零改动**；留档 txt 的复制改 `.part` + `replace`（半份留档会被监听器收成新书）。⚠️ **「自动落地无二次确认」不是缺口**（用户 2026-10-03 口径明确要自动覆盖），真缺的是「覆盖不可撤销」。⚠️ **报告要写实**：显式覆盖那条路不许再说「本地读不了」（`_first_landing(..., replacing_readable=)`）。守卫例：`tests/test_zip_unpack.py`（16）/ `tests/test_online_landing.py`（24）。
- **97** 第 95 期审计四条 `[low]` 全清（用户拍板「候选 C」）：① **`gate_reason` 的 `source` 形参删除** —— 闸门判定只剩 `download.enabled` / `download.toc_enabled` 两条（`novelforge/sources/manager.py`；17 处调用点里 11 处传参同批改，测试桩 `tests/test_autoupdate.py:47`、`tests/test_online_read.py:575` 同步）。② `manager._mark` **只写 `source` + `source_name`**，不再写历史键 `_source`；⚠️ **读侧 `source_of` 必须留** —— 认 `_source` 是**外部回传 item**（`cli.py --item` / sidecar）的输入契约，删的是「我们自己不再写」。③ `config.LIBRARY_SOURCE_DIR` **Python 别名删除**（⚠️ `LIBRARY_SOURCE_DIRS1..N` 与**单根环境变量回退照旧**；18 个测试文件改读 `LIBRARY_SOURCE_ROOTS[0]["path"]`；`isolated` 夹具删掉别名 patch、只留 `LIBRARY_SOURCE_ROOTS` 那份）。④ **`GET /content` 端点删除**（旧式非 `/api` 路径：按 `supports_url` 选源 + 把 `render()` 结果原样 HTML 回吐，每次出网抓第三方页面；经用户确认无外部脚本在用）+ 404 断言 + 顺手删 `HTMLResponse` import。⚠️ **删调用点会留下过期的注释举例**（`novelforge/core/network.py` 的 `verify_tls_enabled` docstring 曾拿 `/content` 举例）。⚠️ **批处理替换后必须跑聚焦用例 + 核对 `git diff`** —— 第 97 期的替换脚本对 `tests/test_sources_search.py` 报告命中却**实际没改**（`KeyError` 才暴露），别只信计数。
- **98** 仪表盘余留三条（用户点名「做一下仪表盘余留的功能」）＋一条**上游事实的更正**：① **页级三态**判据 = **聚合首屏真请求**（`stores/stats` 的 `loaded`/`error` + `stores/library` 的 `loading`/`booksError`），唯一实现 `frontend/src/lib/dashboardPageState.ts`（`loading` = 统计**既没成功也没失败**且书目在路上；`error` = 两条**都**失败且统计从未到手；`empty` 让位 0 库引导 / 全关空态；其余 `ready`）；`frontend/src/views/DashboardView.vue` 按它渲染**页级骨架**（`[data-page-skeleton]`，复用 `ui/Skeleton.vue`）与**页级错误**（「重试」把 stats 与 books 一起重拉），**任一条 settle 即不再遮**、有真数据绝不盖住；⚠️ `DashboardView.vue` 的 `onMounted` **必须自己打一发 `stats.load()`** —— 骨架期部件行不渲染，没人替它发请求。② **快速预览补两个动作**：`edit-metadata` **深链** `?tab=metadata`（唯一路径实现 `frontend/src/lib/bookOpen.ts` 的 `metadataEditPath()`，**不挂第二个 `MetadataEditor` 实例**）+ `move-to-library` 复用 `BookMoveDialog`（`DashboardShelfRow` 的同一层 Teleport，因本行外壳带 `backdrop-blur`）。③ ⚠️ **上游其实有页级信号**：`client/src/views/DashboardView.vue` 第 42-44 行 `libraryState` 拿 `useLibraries()` 的 `loaded`/`error`/`length===0` ⇒ `dashboard-styles.md` §7.4 那句「没有单一的整页加载信号」**只对本项目成立**；但我们**刻意不照搬**（`frontend/src/stores/library.ts` 的 `loadLibraries` 失败时 `librariesLoaded` 保持 false 且**不加 error 标志** ⇒ 拿它当页级信号会得到**永远解不开的骨架**，正是 §7.4 说的「假」）。④ ~~⚠️ **本机模型不支持图片输入**（`read_image` 直接拒绝；转交视觉模型子代理也返回 null）⇒ 与上游首页截图的**像素级比对没做成**~~ ⇒ **收尾已补做**（用户「换能读图的模型了，再跑一次」）：PNG（5.68 MB，上游 commit `c292d6c`）只落在 `%TEMP%`、**不入库**；本项目截图改走 **Edge CDP 无头**（⚠️ `agent-browser` 在本机**已不可用**，会连 CEF 调试实例然后挂住；服务端口也**不是** §7.7 的 8412 而是 8413）。**看图结论：外壳与书架行 class 逐字一致、结构同序，差异只在语言 / 默认启用集合 / 分区粒度三处 ⇒ 没有发现需要修的视觉偏差**（写进 `docs/bookorbit/bookorbit-dashboard-styles.md` §7.8 ④，§7.4 的「界面肉眼冒烟」一行至此**全部收口**）。守卫：`src/lib/dashboardPageState.spec.ts`(8) / `src/views/DashboardView.spec.ts`(4) / `BookPreviewDialog.spec.ts`(+1)，三者都登记进 `EXPECTED_SPECS`；前端 **67 spec / 686 例**。
