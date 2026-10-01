# 长期记忆（novel_dl_convert / NovelForge）

> **体积受限，只放每次都要遵守的铁律**。逐期事实写 `YYYY-MM-DD.md`；**逐期铁律原文 + 运行手册 / 域细节 / 跨会话待办**见 **`MEMORY-REF.md`**；能力/模块/缺口清单见 `docs/bookorbit/bookorbit-*.md`。
> 📚 **文档体系**：`AGENTS.md`（AI 入口 / 硬约束 / 三处同步点）、`docs/TODO.md`、`docs/DESIGN.md`（视觉）、`docs/` 下 project-overview / architecture / user-guide / development / component-api；**上游对照基线在 `docs/bookorbit/`**；逐期记录 `docs/roadmap-gaps-remaining.md`（最新期在**末尾**）。

## 硬约定
1. TXT→EPUB，NAS/容器；input/output 物理分离；FastAPI+CLI；可插拔书源。
2. **加/删功能都彻底**：路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口 404」断言。
   ⚠️ **新增白名单配置键 = 界面控件 + 代码读点，二者缺一即缺陷**（第 80 期立；契约 `tests/test_update_config_contract.py` 钉死
   `EDITABLE ⇄ 设置页 FIELDS ⇄ 读点` 三者一致）。「写得进但没人读」的假配置是静默危害 —— 用户只会在下次发版时觉得「这开关时灵时不灵」。
3. 写计划只写四块：需求来源/功能范围/防回归要点/任务清单。
4. 提交即推送（中文 commit、按能力拆多笔）；收尾不留未提交改动；临时文件放 `/tmp`。
5. 视觉照搬 BookOrbit；局部更新不重建 DOM；**不做假交互**（未支持就如实标注）。⚠️ **「零外部请求 / 零依赖」已于第 80 期解除为「默认取向」**：默认仍自托管、不拉 CDN，但允许**显式、可关、失败降级**地引入外部依赖与出网（新依赖须在 `requirements*.txt`/`package.json` 声明理由；出网由后端发起）。
6. 可能另有 AI 会话：改前 `git status`；他人改动不回退、不顺手提交；记忆只追加。⚠️ **期号会被别人用掉** —— 动手前先 `git log --oneline` 确认本期号。
7. 书库用户手建；每库来源=多个绝对路径 `source_dirs`（JSON 数组）。`type` 只决定功能显隐。
8. **书源合规**：只接公版/授权源；盗版分发平台（zlibrary 等）专用下载不做。闸门判定**只有** `DownloadManager.gate_reason()`；来源名**只有** `sources.source_of()` 一种读法。

## 元数据与出版
- **只落服务端 DB、绝不写回文件**；`core/publish.py` 是唯一仍写文件的模块（写副本，源只读）。
- **源不可变**：副本禁原地写（临时文件+`Path.replace`）；删除一律移回收站（`CACHE_DIR/recycle`），**从不 `unlink`**（⚠️ 例外：仅用户显式动作才移动磁盘文件 ——「删书」回收三份；「移除书库」**第 81 期起默认只删登记、零文件触碰**，仅显式 `purge_files=1` 才在后台任务里回收②③保留①，可用「维护 → 回收站还原」搬回）。
- 命名规则**唯一实现**=`fileops.fill_pattern`；`PATTERN_FIELDS` 唯一真值源、前端 `RENAME_TOKENS` 逐字一致（契约）；**禁第二处展开**。
- 三层 `override>online>opf`；抓取受三道正交闸（字段策略 ⊗ `meta_locks` ⊗「改过就不动」）。无值哨兵 `db.META_CLEAR="-"`。
- **软删除**：`DELETE`=置 `deleted_at`，`purge` 才真删；**一切读点须 `WHERE deleted_at=0`**。
- 作者排序名两列：`sort_name`（派生）/ `sort_name_local`（用户覆盖），展示取 覆盖>派生；派生/回填**只写 `sort_name`**。
- 系列缺册唯一实现 `library.series_gaps`；阅读尝试 `reading_attempts` 表进 `ORPHAN_TABLES`/`REMAP_TABLES`。
- **「一棵树=一本书」唯一真值源=`core/units.py`**（`library`/`catalog`/`migrate`/`server` 全读它）。

## Git / 环境 / 构建
- 行尾必须 **LF**（CRLF⇒容器 `sh /app/start.sh` 报 `set: Illegal option -`）。
- Python 3.10+（PEP 604）；本机对外网络有限；Node 走 **nvm**（已激活 24.19.0）。
- 认证走 GCM；推送失败先查认证/网络，**别改 git config**。**切勿恢复 `docker-compose.override.yml` 名**（会静默合并成 8993+禁拉取）；NAS 部署=`docker-compose.yml` 单文件、不读 `.env`。
- ⚠️ **出网走本机代理**：系统代理 `127.0.0.1:7897` = `verge-mihomo`（Clash Verge）；根证书里有本机自建 CA **`CN=Yaya的小电脑`**（带私钥，已信任）⇒ Node 默认不信它，会出现 `Error 10006 / self signed certificate`。已设 User 级 **`NODE_OPTIONS=--use-system-ca`**（Node 信任集 121→210，含该 CA），**改后须完全重启 IDE** 才生效；回滚 = 把它设回 `$null`。
- 🚀 **版本号改动 ⇒ 必须同批补 `CHANGELOG.md` 段**：推 `main` 后 CI（`release.yml`）读仓库根 `VERSION`，`v<版本>` tag 不存在就**自动打 tag + 建 Release**（notes 由 `python -m novelforge.core.changelog <版本>` 产出，与应用内「新功能」页同源）；缺段则发布失败。版本唯一真值源=`VERSION`（`/health` 下发），**别再写第二份版本字面量**。

## 自动化测试
- 完全离线 `pytest`（⚠️ **Windows 用 `.venv\Scripts\python.exe -m pytest`**；2026-10-01 起仓库根**已有 `.venv`**（此前一度没有，须在 `%TEMP%` 建临时 venv）—— 开工前仍先 `Test-Path .venv` 确认）；
  **前端另计**（`npm run test:unit`），**不并入**后端计数。
- ⚠️ `pytest.ini` 已含 `addopts=-q`，**别再加 `-q`**；计数用 `--junitxml`+脚本解析。
- **新增旁路线程必须进收尾清单**；`_quiesce_background()` 须在夹具 `db.close()` **前**收尾。
- **仓库根防删除守卫**（`tests/conftest.py`）：目标解析到仓库根内即 `pytest.fail`。

## 后端踩坑
- core 内一律 `from .. import config`（裸 `import config` 被同名命名空间包劫持，启动才炸）。
- **httpx 0.28 无 `CookieJar`**：`core/network.py` 用标准库 `http.cookiejar`。
- **版本唯一真值源=`server.APP_VERSION`，只由 `GET /health` 下发**；**无 `/api/health`**。`db` 只走 `db._connect()`。
- **新增库表列须同进 `db._LIBRARY_COLS`**，否则 `update_library` 静默写不进。
- 批量端点注册在 `/api/books/{bid}` **之前**；字面量路径在 `{param}` 之前。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值=每库覆写 ?? 全局`。
- ⚠️ **新增「可保存的配置分区」=三处同步点**：① `server.EDITABLE` ② `GET /api/config` 硬编码键列表 ③ 前端 `settingsFields.ts` 的 `SECTION_KEYS`。
- ⚠️ **偏好块=前后端两处真值源**：`server.PREFS_BLOCKS` ↔ 前端 `lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS`（契约 `tests/test_prefs_shelf_block.py`）。

## 前端
- Vue3 SFC+TS+Vite+Tailwind v4+Pinia+vue-router(hash)；产物 `novelforge/static/v2/`（`/` 服务其 index.html，缺失 503）；**勿往 `novelforge/static/` 加手写页**。
- ⚠️ **视觉层=逐字照搬 BookOrbit 的 oklch token**（`frontend/src/assets/theme/*.css`；默认 `--tint-h: 80`）。组件**禁写死颜色/圆角/阴影**（规则见 `docs/DESIGN.md`）。
- ⚠️ **收尾四连**：`type-check` + `test:unit` + `build` + `deploy`。`build` 只落 `frontend/dist`，**`deploy` 才同步到 `novelforge/static/v2`**（漏 deploy⇒服务端发旧 bundle）。
- ⚠️ **新增/删设置页三处同批改**：`settingsNav.ts` ↔ `router/index.ts` 的 `SETTINGS_PAGE_COMPONENTS` ↔ 组件（且 `SETTINGS_PAGE_COMPONENTS` 与 `status==='ready'` 必须一一对应，否则运行期 `console.error`）。**设置页真实路由=`#/settings/<page.path>`**，**不带分组段**。
- 演示数据禁 `Math.random()`；**路由 path 全局唯一**。
- **全站开关唯一实现=`ui/Switch.vue`**；改偏好必须走 UI 点击（`localstorage-set` 会被同步层拉回）。
- 浏览器冒烟（2026-10-01 起）：**`agent-browser`**（全局 CLI + Chrome，本轮实测可用；`open → wait → snapshot → screenshot → close`，收尾必 `close`）；⚠️ `snapshot` 后元素 ref 会重排，别缓存上一次的 ref；`type` 会触发 Vue `v-model`。隔离实例 + `admin/changeme`；⚠️ 注入 `nf_token` 不稳，走登录表单（端点 `/api/auth/login`，字段 `{user,pin}`）。
  ⇒ 界面层缺陷**必须靠冒烟兜**：第 83 期抓到的「受控 checkbox 原生态与 store 不一致」HTTP 端到端与 43 个旧 spec 全都测不到（详见 `.codebuddy/memory/2026-10-01.md`）。

## 逐期铁律索引（**全文见 `MEMORY-REF.md`「逐期铁律原文」**）
近期关键期锚点：**75** 删除语义（删书回收三份；「移除书库回收②③保留①」**已于第 81 期作废**，改成默认只删登记；Switch 圆点固定白色）；**76** EPUB 插图资源 URL 形状只在 `library._rewrite_assets`/`_rewrite_css_urls` 拼、令牌响应期注入、书内样式走独立端点且**绝不进正文容器**；**77** 移除「按格式归库」整条链（migrate 的 preview/plan/门禁、端点 `/api/library-migrations/*`、`libraries.auto_migrate`、前端 MigrationGateDialog+卡片台账）—— 它与「移除书库」错误耦合；跨库移动 `/api/book-move/*` 与 `execute`/`rollback`/`library_migrations` **全部保留**；**78** 版本号唯一真值源 = 仓库根 `VERSION`（第 N 期 = V0.N.0）经 `GET /health` 下发，`CHANGELOG.md` 每版一段驱动「新功能」页；**79** 序号单元**第四形态**「前缀 + 尾部编号」（编号必须**紧贴**标题文字，否则 `vol.1` 会被误认成「第 1 话」）+ `is_unit_dir` 加「同前缀」闸（≥2 种前缀即不合并）+ `SCAN_RULE_VERSION` 2；**80** `update` 段四个键全部真有读点（消灭假开关）+「零外部请求 / 零依赖」解除为**默认取向**；**81** 「移除书库」默认只删登记、`purge_files=1` 才清文件且改**后台任务**（`librarypurge`）+ 回收台账 `recycle_items`（**刻意不含 `book_id`**）与「回收站还原」（`core/recycle.py`、`recycle` 任务、幂等可续跑、退让不覆盖）+ 回收落点名 ≤255 字节（唯一实现 `fileops.recycled_name`）；**82** 首页对齐上游（部件行横向卡片带 + 壳上移消灭双层壳 + 12 件补真实数据态 `useWidgetState` + 书架多行分带/两列 + 首启卡片上游化；**显式依赖 `vue-draggable-plus`**、`@vueuse/core` 与 `lucide-vue-next` 刻意不引；行内拖拽经 `applyVisibleOrder` 做「可见子集 → 全量索引」映射；`WidgetId` localStorage 键一字不改）；**83** 仪表盘余留（`ShelfDef.library_ids` **空 = 全部书库** + `lib/shelfScope.ts`；第 13 件自开部件 `reading-time` —— **前 12 个 id 仍与上游逐一对应**，契约测试 `test_dashboard_widget_contract.py` 钉住；书架行点封面开 `BookPreviewDialog`（加 `actions`，**Teleport to body** 因外壳 `backdrop-blur` 会让 `fixed` 后代被裁）；删书流程收敛到 `lib/bookDelete.ts` 唯一真值源；⚠️ **83 验证与提交已补完**：前端 `type-check` ✅ / `test:unit` **44 spec 全过** / `build` ✅ / `deploy` ✅（已同步 `static/v2`，产物含「阅读时长 / 库范围 / 全部书库 / 已移入回收站」标记）；后端全量 **1340 例 / 0 failed / 0 errors / 12 skipped**（比 82 期 1335 例 +5，新增 `test_dashboard_widget_contract.py`）；四笔提交 `3c81112`→`152c407`→`8316107`→`3944880` 已推 main，CI 自动打 tag **`v0.83.0`** 并建 Release；文档锚点：先证零新增（`git diff c06bb03..HEAD -- docs/` 无新增 `文件:行号`、且无锚点指向本期改过的文件），**随后另起一轮全仓复核**把存量 **51 处疑似漂移 + 4 处硬错**逐条改成实测行号 ⇒ `check_doc_anchors.py` **漂移 0 / 硬错 0**（符号命中 27→74；仍剩「目标不在此仓」12 条 = 上游外部引用 + 裸文件名，未动））；**84** 自动更新加固 —— ① 第 80 期「先记已尝试、再执行」使 pull 失败也被当「已试过」⇒ **失败一次即永久卡死**；改建 `auto_failures` / `auto_retry_at` / `last_auto_result` / `auto_message` **退避状态机**（**1h→6h→24h 封顶**，新 stage **`defer`** 不复用语义为「永久放弃」的 `already_tried`；未挂 socket 记 `unavailable` **不记失败**）；② 抽出 `_tick()` 让**启动首轮与定时轮共用同一份逻辑**（启动即检，不等一个间隔）；③ 新增 `core/backup.py` 更新前快照（PG `pg_dump -Fc` / SQLite `copy2`，落 `BACKUP_DIR` 保留 5 份，**失败即 `backup_failed` 中止、不进入 pull**）；④ 维护页 UPDATES 从「未实现」改为「已实现 + 跳转 `ext/update`」—— ⚠️ `IMPLEMENTED` 必须与 `settingsNav` 的 `upstream.items` **逐字一致**（裸 `Check for updates` 匹配不上带中文括注的那条，是新 spec 抓出的真缺陷）；**84** 自动更新加固（并行会话交付：退避重试 / 启动即检 / 更新前自动备份 / 引导式开启，V0.84.0）——
⚠️ **期号 84 已被并行会话占用，别再回用**；**85** 目录体系（本地卷/楔子解析 + 官方书城目录映射覆盖，V0.85.0；
批次 A **已交付**（4 笔 `d9b3b72`→`11a9825`：前端 48 spec / 后端 1359 例全绿）；批次 B **底座已落**（`store_toc` + `toc_map` 两表与搬迁登记，`3d5877e`），余「来源注册表与只取目录 + 覆盖层 + 配置三同步点 + 路由 + UI + 发版」待做）。更早各期（53–74）细节见 REF。
