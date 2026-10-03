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
- ⚠️ 只跑 HTTP 端到端/`ui-smoke` 仍可能漏界面缺陷（第 83 期）；**共享数组加分页会静默影响所有消费方**（第 88 期）⇒ 分页/切片数据必须有**自己的状态**。

## 逐期铁律索引（**全文见 `MEMORY-REF.md`「逐期铁律原文」+ `docs/roadmap-gaps-remaining.md`**）
- **75–79** 删书回收三份 / Switch 圆点白（75）；EPUB 插图 URL 只在 `library._rewrite_assets`+`_rewrite_css_urls` 拼、书内样式独立端点**不进正文容器**（76）；移除「按格式归库」链、**跨库移动 `/api/book-move/*` 保留**（77）；版本真值源=`VERSION`（78）；序号单元**第四形态**（编号须**紧贴**标题）+ `SCAN_RULE_VERSION` 自愈（79）。
- **80–83** `update` 四键全有读点、假开关即缺陷（80）；「移除书库」只删登记 + `recycle_items`（**不含 `book_id`**）+ 回收站还原 + `recycled_name` ≤255B（81）；首页对齐上游、显式依赖 `vue-draggable-plus`、`WidgetId` 键不改（82）；`ShelfDef.library_ids` **空=全部书库**、第 13 件 `reading-time`、`BookPreviewDialog` **Teleport to body**（83）。
- **84**（**期号已被并行会话占用**）自动更新：退避状态机（1h→6h→24h）+ 启动即检 + 更新前备份（失败即中止）。
- **85** 目录体系：`core/reading_list.py`（卷/段唯一真值源）+ `toc_sources.py`（**只取目录**）+ `download.toc_enabled`（默认关）；⚠️ 番茄/起点内置规则**未在本机验证**。
- **86** 书源体系 + 追更：16 接口全有界面入口；`autoupdate` 默认开启、**只调 `update_report`**；`manager.update_lock` 防并发丢章。
- **87** `.zip` 按内容分派（`zipkind.py`，`format` 归一 `CBZ`）；三处静默失败修复；重名判据收敛（**不改 `book_id` 规则**）；`format-capability-matrix.md` 契约。
- **88** 脏库读**不扫盘**（派后台 + `SETTLE_WAIT=0.25`；**显式扫描仍同步**）；`/api/books` 加 `limit`/`offset`（不传=全量）；书架用**独立分页源**。
- **89** `requestAck()` 修上传假报错（不解析响应体）；`ENCODING_RULE_VERSION=2`，BOM 优先 + 坏字节**不静默丢**、计数上报。
