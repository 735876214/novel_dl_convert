# 长期记忆（novel_dl_convert / NovelForge）

> 只放**每次都要遵守的铁律**（每会话自动注入、**体积受限**）；逐期事实写 `YYYY-MM-DD.md`；**逐期铁律原文 + 运行手册 / 域细节 / 跨会话待办**见 **`MEMORY-REF.md`**；能力/模块/缺口清单见 `docs/bookorbit-*.md`。
> 📚 **文档体系**：`AGENTS.md`（AI 入口 / 硬约束 / 三处同步点）、`TODO.md`、`DESIGN.md`（视觉）、`docs/` 下 project-overview / architecture / user-guide / development / component-api；逐期记录 `docs/roadmap-gaps-remaining.md`（最新期在**末尾**）。**改动要同步对应那份**。

## 硬约定
1. TXT→EPUB，NAS/容器；input/output 物理分离；FastAPI+CLI；可插拔书源。
2. **加/删功能都彻底**：路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口 404」断言。
3. 写计划只写四块：需求来源/功能范围/防回归要点/任务清单。
4. 提交即推送（中文 commit、按能力拆多笔）；收尾不留未提交改动；临时文件放 `/tmp`。
5. 视觉照搬 BookOrbit；零外部请求；局部更新不重建 DOM；**不做假交互**。
6. 可能另有 AI 会话：改前 `git status`；他人改动不回退、不顺手提交；记忆只追加。⚠️ **期号会被别人用掉** —— 动手前先 `git log --oneline` 确认本期号（第 66 期先例：计划原写第 62 期，落地时 62–65 已被其它会话占用）。
7. 书库用户手建；每库来源=**多个绝对路径 `source_dirs`（JSON 数组）**，来源根 `LIBRARY_SOURCE_DIRS1..N`（未配回退 `LIBRARY_SOURCE_DIR`）；`type` 只决定功能显隐。
8. **书源合规**：只接公版/授权源；**盗版分发平台（zlibrary 等）专用下载不做**（第 57 期决定、第 71 期复核维持），以「通用规则书源 + 投递」替代。书源闸门判定**只有** `DownloadManager.gate_reason()` 一处；命中来源名**只有** `sources.source_of()` 一种读法（`source` / `_source` 都认、新键优先）。

## 元数据与出版
- **只落服务端 DB、绝不写回文件**（override/online/cover/locks/custom_values）；`core/publish.py` 是唯一仍写文件的模块。
- **源不可变**：源只读；副本禁原地写（临时文件+`Path.replace`）；副本被删只标记待确认+日志、**绝不删源**；成品目录禁与库根/扫描源重叠（建库即拦）；硬链接副本内嵌元数据成独立 inode ⇒ 不宣称省空间。
- 源文件名无写入口：改名只剩「按命名规则重出版副本」；实体改名/合并=纯元数据写入。
- 命名规则**唯一实现**=`fileops.fill_pattern`（先长后短）；`PATTERN_FIELDS` 唯一真值源、前端 `RENAME_TOKENS` 逐字一致（契约）；**禁第二处展开**。
- 「预览==落盘」不变量：`publish.relpath_for`+`rel_verdict`（REUSE/REBUILD/DECLINE）；有未保存草稿时 UI 拒重出版；`apply_*` 目标服务端自算。
- 抓取/手工编辑**不按格式分流**；非 EPUB 无 OPF 兜底，「恢复」=撤销覆盖回落在线值。**目录型条目（有声书一章一文件）同样出版**。
- 无值哨兵 `db.META_CLEAR="-"`：空串=撤销覆盖、接口 `null`=显式清空；三处翻译须一致。
- **三层** `override>online>opf`；抓取受**三道正交闸**（字段策略 ⊗ `meta_locks` 显式锁（只挡抓取）⊗「改过就不动」）。`metadata_fetch.custom_fields` 已下线（移 `custom_field_defs`）。
- 相似书五路加权与降级口径、`limit`≤25、`score`=0–1（前端不显示）⇒ 细节见 REF。
- **软删除**：`DELETE`=移垃圾桶（`deleted_at`），`purge` 才真删；**一切读点须 `WHERE deleted_at=0`**（含 `annotation_counts`/`trashed_*`/remap 探测）。
- **作者排序名两列**：`sort_name`（派生/在线）、`sort_name_local`（用户覆盖），展示取 覆盖>派生。⚠️ 派生/回填**只写 `sort_name`、绝不动 `sort_name_local`**（写后者=冒充用户改过，误显「已覆盖」并挡住抓取）。
- **系列缺册**唯一实现 `library.series_gaps`；**无序号/非数字序号各自单列、不并入缺册**。**阅读尝试** `reading_attempts` 表（进 `ORPHAN_TABLES`/`REMAP_TABLES`），自动维护挂 `db.set_status`、`reset_reading_state` **四清**。
- **系列级元数据** `series_meta.FIELDS`（description/publisher/first_year/tags 可本地覆盖）；⚠️ `set_local` 空串=**清除该字段覆盖** ⇒ 「恢复在线」必须**只提交那一个字段**；`owned_count` 与 `declared_count` 不可合并。

## Git / 环境 / 构建
- 行尾必须 **LF**（CRLF⇒容器 `sh /app/start.sh` 报 `set: Illegal option -` 重启）。
- Python 3.10+（PEP 604）；本机对外网络有限；Node 走 **nvm**（已激活 24.19.0）⇒ 见 REF「环境与构建」。
- 认证走 GCM；**勿再引入** token 内嵌/insteadof 明文；推送失败先查认证/网络，**别改 git config**。
- 入库配置禁含机器相关绝对路径（前例 `.vscode/settings.json` 的 `python.pythonPath`）：指向 `.venv` 的各人配在本机用户设置。
- `.gitignore`/建环境/首跑/lock 噪声/Windows 删除 shim ⇒ **见 REF**。
- ⚠️ **切勿恢复 `docker-compose.override.yml` 这个名字**（Compose 会自动合并 ⇒ NAS 上 `docker compose up -d` 静默变成 8993 + 禁拉取 + 挂不存在的 `./novelforge`），该用途已改名 `docker-compose.offline.yml` 且须显式 `-f`。NAS 部署 = **`docker-compose.yml` 单文件**（配置全写字面量、**不读 `.env`**），细节见 REF。

## 自动化测试
- 完全离线 `.venv/bin/python -m pytest`；**后端基线逐期增长**（第 71 期 **1207 passed / 12 skipped**，0 failed/0 err；最新以 junit 为准）；**前端另计**（`npm run test:unit`，第 71 期 **424 例 / 36 文件**）、**不并入**。
- ⚠️ `pytest.ini` 已含 `addopts=-q`，**别再加 `-q`**；计数一律 `--junitxml=…`+脚本解析；**落全量日志到文件再读**。⚠️ 本机 safe-delete shim 拦 pytest 会话末清理 ⇒ `$LASTEXITCODE=1` 而 junit 全绿，**别据此判失败**（跑前 `$env:PYTHONPATH=''` 整段绕开）；**Remove-Item 多文件时一个不存在会整批中止**。
- **「长期稳定失败」是产品 bug 症状**：逐层打印中间返回值找根因；e2e 做改前 FAIL/改后 PASS 对照。
- 环境变量须在 import 业务模块**前**设；`db._conn`/`_db_path` 模块级缓存⇒隔离靠 `db.close()`。
- 碰库/DB 用例必须 `isolated`、接口 `client`+`auth_headers`；假 EPUB(`b"EPUB"`)够扫描类，元数据写回/系列解析要真 EPUB(`epub_builder.build_epub`)；⚠️ 隔离夹具**不预建库根目录**，写真 EPUB 前先 `mkdir(parents=True)`（ebooklib 写失败只发 UserWarning、文件静默缺失）；测试库根须在 `LIBRARY_SOURCE_DIR` 下；断言留余地。
- 全量后半程曾 segfault ⇒ `_quiesce_background()` 须在夹具 `db.close()` **之前**收尾；`watcher.wait_pending(5.0)` 非 0 即 `pytest.fail`；**新增旁路线程必须进收尾清单**。
- **仓库根防删除守卫（第 45 期，`tests/conftest.py`）**：会话级 autouse 夹具补丁删除/移走入口，目标解析到仓库根内即 `pytest.fail` ⇒ **不依赖目录重定向的最后防线**。

## 后端踩坑
- ⚠️ **httpx 0.28 没有 `CookieJar`**：`core/network.py` 必须用**标准库** `http.cookiejar.CookieJar`（写 `httpx.CookieJar()` ⇒ 构造客户端即 AttributeError、搜索恒 0 条；**单测全用桩 client 照不到**）。
- **规则源搜索命中地址必须补绝对**：`_parse_search` 里 `_absolutize` 按搜索页 url 做 urljoin（与 `_extract_links` 同口径）。
- **`search_page(client,title,page=1)` 契约**：**`page>1` 且源不支持分页必须回空**；`RuleBasedSource` 仅当 `search.url` 含 `{page}` 时替换。搜索**必须真并发**（`gather` + 每源 `wait_for(SEARCH_TIMEOUT=20)`），逐源状态如实回（含 `skipped`/`reason`）。
- core 内一律 `from .. import config`（裸 `import config` 被同名命名空间包劫持，启动才炸）。
- **`scrape._epoch` 世代号**：`stop` 等不到 worker ⇒ 推进世代；各落库点校验世代、作废即停手；**新增 worker 落库点必须加守卫**。
- **ISBN 形状唯一真值源=`metadata.isbn_digits`**；`library._isbn_of`/`fileops._set_isbn` 都调它。写磁盘只用 rename/move，删除移 `CACHE_DIR/recycle`；路径用 `library.root_of(b)/b["name"]`（**禁** `config.OUTPUT_DIR/b["name"]`）；`write_epub` 前先 `mkdir`。库根限 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR`（`safe_path`，之外 400）。
- ⚠️ **新增库表列须同进 `db._LIBRARY_COLS`**，否则 `update_library` **静默写不进**。⚠️ **列里的 `''`=「没设过」**（坏 JSON 同）；sqlite `ADD COLUMN` 只吃常量默认 ⇒ 回落**只能放读时**。
- ⚠️ **加唯一约束/PK 看 `db.remap_book_id`**（整体 `UPDATE` 撞约束被吞成「搬 0 行」⇒静默丢数据）；**含 `book_id` 的表必过四处**（清单见 REF）。⚠️ **`migrate.execute`/`rollback` 不按 `direction` 分支**、`DIR_AUTO="move"` 不能改。
- ⚠️ **win32 目录 `st_size` 恒 0**（「空文件」判据见 REF）；批量端点注册在 `/api/books/{bid}` 之前、字面量路径在 `{param}` 之前；目录型条目用 `path.exists()`。
- **版本唯一真值源=`server.APP_VERSION`，只由 `GET /health` 下发**；**无 `/api/health`**。共用锁嵌套用 `RLock`；⚠️ **`db` 只走 `db._connect()`**，别抓裸连接、别绕开 `_lock`。
- `core/stats.py` `overview` 键**只增不删**、跟随 `library_id`、**不新增扫描路径**。⚠️ **阅读状态阈值只有两入口**（后端 `lib_settings.reading_thresholds` / 前端 `lib/readingThresholds.ts`）。⚠️ **路径判据只有 `frontend/src/lib/paths.ts`**（别处抄 `startsWith('/')` ⇒ Windows `C:\…` 判错）。
- **「文件:行号」收尾必须实测复核**：只记真实行号；判据「0 硬错」**且**人工过完 `--todo`；⚠️ **历史实施记录里的旧行号不改写**；改大文件后跑 `tests/check_doc_anchors.py`。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值=每库覆写 ?? 全局`，落 `libraries.settings`；真值源 `core/lib_settings.py`+`features.SETTING_CAPS`；接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（细节见 REF）。
- 可见性=能力矩阵（库类型）∩每库开关，判定**只留一处**；「不可见」=「不存在」→404。⚠️ **能力键判隐显轴**：`library.hasFeature(k)` 判「侧栏当前选着的库」（只适合全局导航/设置页）；读者侧要判「**这本书**属于哪个库」。
- ⚠️ **新增「可保存的配置分区」=三处同步点**：① `server.EDITABLE` ② `GET /api/config` 硬编码键列表 ③ 前端 `settingsFields.ts` 的 `SECTION_KEYS`；漏任一处不报错。
- ⚠️ **偏好块清单是前后端两处真值源**：`server.PREFS_BLOCKS` ↔ 前端 `lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS`；**新增块必须两端同批改**；契约 `tests/test_prefs_shelf_block.py`。

## 前端
- Vue3 SFC+TS+Vite+Tailwind v4+Pinia+vue-router(hash)；产物 `novelforge/static/v2/`（`/` 服务其 index.html，缺失 503）；**勿往 `novelforge/static/` 加手写页**。
- ⚠️ **视觉层 = 逐字照搬 BookOrbit 的 oklch token**（`frontend/src/assets/theme/*.css`；默认 `--tint-h: 80` 暖中性 + 65 档 accent + 4 档圆角）。**不是** hex 的 `#2563eb`/`#6366f1`（那是**已作废旧原型**）。组件**禁写死颜色/圆角/阴影**，规则见 `DESIGN.md`。
- 演示数据禁 `Math.random()`；**路由 path 全局唯一**；`settingsNav`/router 注册表/侧栏**三处与组件同批改**（**删条目即删路由**与侧栏项）；**零外部请求零 CDN**。**设置页真实路由 = `#/settings/<page.path>`**，**不带分组段**。
- ⚠️ **收尾四连**：`type-check` + `test:unit` + `build` + `deploy`。`vitest` 不校验模块导出完整性（曾误提交 0 B 文件）；`build` 只落 `frontend/dist`，**`deploy` 才同步到 `novelforge/static/v2`**（漏 deploy ⇒ 服务端仍发旧 bundle）；跑前 `$env:NODE_OPTIONS=''`。
- ⚠️ **形态与语义**：设置页 `note` 是**纯文本插值**且**只有 `placeholder` 页会渲染**。**全站开关唯一实现 = `ui/Switch.vue`**（滑块用 `bg-card`，别写死白色）。**冒烟改偏好必须走 UI 点击**（`localstorage-set` 会被同步层拉回）。
- ⚠️ **目录/列表类数据拉取失败必须显式**：不许静默 `catch` 让块变空；尽量回落旧接口 + 原因上屏 + 「重试」；计数别出 `N/0`。
- 阅读器翻页 `ComicReader`/`PdfReader` 的 `go()` 是**唯一汇聚点**⇒挂钩子必须放 `go()`。⚠️ **列表载荷不给「重字段」**：书目列表统一经 `server._card()`，不发长文本（加字段前先问「列表真的需要吗」）。
- ✅ **改契约时先让类型变严格**（字段改可选 ⇒ `vue-tsc` 一次报出全部消费方，比人肉 grep 可靠）。
- 浏览器冒烟：`playwright-cli open --browser=msedge <url>`（本机无 Chrome）；隔离目录 + `admin/changeme`；⚠️ **注入 `nf_token` 不稳，走登录表单**；`goto` 只改 hash ⇒ 验新构建要 cache-busting/`reload`；⚠️ **隔离目录复用前先清残留 `settings.json`**。
- 图表入口 `lib/charts.ts`、偏好归属、命名避让（`/explore` vs `/browse`）、实体总览六维、窄屏双写法、`ToolsLayout` 用 `onActivated`、滚动连续流补偿三条、`:key` 并发重复、`v-model` 落盘顺序 ⇒ **域细节见 REF**。

## 逐期铁律索引（**全文见 `MEMORY-REF.md`「逐期铁律原文」**，此处仅关键锚）
- **53** 演播者实体（`books.narrators`+`narrators` 表）；**54** `core/embed.py` 离线 LSA + `core/epub_cfi.py` 位置唯一真值源（`progress.cfi` 只由 NF 阅读器写）；**55** `LibraryWizard` 全局单实例就地弹窗 + 分章唯一 `core/detect.py`；**56** 进度同步=轮询+提示（不上 SSE，`updated_at` 是公开契约）。
- **57** 14 家提供商（`SOURCES`↔`_FETCHERS` 逐字一致）；出网收口 `metasources._get_*`；**插件市场已取消**；试搜 `POST /api/sources/test` 不落盘。**58** 跨源合并门槛 `score>=max(0.7,0.9×最佳)`；`FIELD_TRUST` 键是**字段名**（年份=`date`）。**59** 体检只读+分类+首条、进程内缓存。
- **60** 语种重排「专精本语种→多语种→专精别语种」，只排不筛；占位语种须再拦 `LANG_UNKNOWN`。**61** 翻页 `width` 是 border-box⇒设整屏宽；目录按 `flat` 位置跳+请求序号守卫；**没有指标不许凭感觉优化**。
- **66** 跨册续接唯一真值源 `lib/seriesNext.ts`；**67** gzip（**206 永不压缩**）+ 并发**单飞**（在飞 Promise）+ 计时用 `curl`；**68** `server._card()` 不发简介正文 + 门控用 `authChecked`（**`auth.ready` 不行**）。
- **69** 滚动跨章：锚取正文 article、补偿写绝对值、锚须已存在；`:key` 重复⇒**重读集合+按 id 去重+写入串行**。**70** 开关只 `ui/Switch.vue`；`v-model` 与监听器顺序不定⇒写 `:model-value` + `@update:model-value`；投递唯一链路 `api.convertDrop`。
- **71** 探索发现：闸门**唯一判定** `gate_reason()`（三端点 400 + 原因；**试搜不拦**；前端提前置灰+出口）；来源名**唯一读法** `source_of()`；搜索真并发+逐源状态；`search_page`（**不支持分页的第 2 页必须回空**）；合并保守（缺作者/卷次差异**不并**）；**不做一键重试**。
