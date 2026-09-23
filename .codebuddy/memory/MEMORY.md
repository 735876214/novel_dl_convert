# 长期记忆（novel_dl_convert / NovelForge）

> 只放**每次都要遵守的铁律**（每会话自动注入、体积受限）；逐期事实写 `YYYY-MM-DD.md`；运行手册/域细节/跨会话待办见 **`MEMORY-REF.md`**；能力/模块/缺口清单见 `docs/bookorbit-*.md`（capability-gap / module-inventory / roadmap-gaps-remaining）。

## 硬约定
1. TXT→EPUB，NAS/容器；input/output 物理分离；FastAPI+CLI；可插拔书源。
2. **加/删功能都彻底**：路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口 404」断言。
3. 写计划只写四块：需求来源/功能范围/防回归要点/任务清单。
4. 提交即推送（中文 commit、按能力拆多笔）；收尾不留未提交改动；临时文件放 `/tmp`。
5. 视觉照搬 BookOrbit；零外部请求；局部更新不重建 DOM；**不做假交互**。
6. 可能另有 AI 会话：改前 `git status`；他人改动不回退、不顺手提交；记忆只追加。
7. 书库用户手建；每库来源=**多个绝对路径 `source_dirs`（JSON 数组）**，来源根 `LIBRARY_SOURCE_DIRS1..N`（未配回退 `LIBRARY_SOURCE_DIR`）；`type` 只决定功能显隐。

## 元数据与出版
- **只落服务端 DB、绝不写回文件**（override/online/cover/locks/custom_values）；`core/publish.py` 是唯一仍写文件的模块。
- **源不可变**：源只读；副本禁原地写（临时文件+`Path.replace`）；副本被删只标记待确认+日志、**绝不删源**；成品目录禁与库根/扫描源重叠（建库即拦）；⚠️ 硬链接副本内嵌元数据成独立 inode ⇒ 不宣称省空间。
- 源文件名无写入口：改名只剩「按命名规则重出版副本」；实体改名/合并=纯元数据写入。
- 命名规则**唯一实现**=`fileops.fill_pattern`（先长后短），`publish.relpath_for` 调它；`PATTERN_FIELDS` 唯一真值源、前端 `RENAME_TOKENS` 逐字一致（契约）；**禁第二处展开**。
- 「预览==落盘」不变量：`publish.relpath_for`+`rel_verdict`（REUSE/REBUILD/DECLINE）；有未保存草稿时 UI 拒重出版；`apply_*` 目标服务端自算、客户端 `book_ids` 只收窄。
- 抓取/手工编辑**不按格式分流**；非 EPUB 无 OPF 兜底，「恢复」=撤销覆盖回落在线值。
- **目录型条目（有声书一章一文件）同样出版**（形态判据/细节见 REF）。
- 无值哨兵 `db.META_CLEAR="-"`：空串=撤销覆盖、接口 `null`=显式清空；三处翻译须一致（见 REF）。
- **三层** `override>online>opf`；抓取受**三道正交闸**（字段策略 `overwrite(默认)/fill_only/skip` ⊗ `meta_locks` 显式锁（只挡抓取）⊗「改过就不动」）⇒ 细节见 REF。
- `metadata_fetch.custom_fields` 已下线（移 `custom_field_defs`）；`custom_fields` 仍在 `metascore.NOT_SCORED`、权重表未动。
- 相似书五路加权与降级口径**见 REF**；`limit`≤25、详情页默认 6 可展开；0 分不返回；`score`=0–1（前端不显示）。
- **软删除**：`DELETE`=移垃圾桶（`deleted_at`），`purge` 才真删；**一切读点须 `WHERE deleted_at=0`**（含 `annotation_counts`/`trashed_*`/remap 探测）。
- **作者排序名两列**：`sort_name`（派生/在线）、`sort_name_local`（用户覆盖）；展示取 覆盖>派生。⚠️ 派生/回填**只写 `sort_name`、绝不动 `sort_name_local`**（写后者=冒充用户改过，误显「已覆盖」并挡住抓取）；派生规则见 REF（CJK 原样返回⇒跳过）。
- **系列缺册**：唯一实现 `library.series_gaps`（按 `series_index` 数字集合求 `[1..max]` 补集）；**无序号/非数字序号各自单列、不并入缺册**。
- **阅读尝试（轮次）**：`reading_attempts` 表（进 `ORPHAN_TABLES`/`REMAP_TABLES`）；一轮=「开始读→读完」；⚠️ 自动维护挂 `db.set_status`、`reset_reading_state` **四清**（含 attempts）⇒ 细节见 REF。

## Git / 环境 / 构建
- 行尾必须 **LF**（CRLF⇒容器 `sh /app/start.sh` 报 `set: Illegal option -` 重启）。
- Python 3.10+（PEP 604）；本机对外网络有限；Node 走 **nvm**（已激活 24.19.0）⇒ 见 REF「环境与构建」。
- 认证走 GCM；**勿再引入** token 内嵌/insteadof 明文；推送失败先查认证/网络，**别改 git config**。
- 入库配置禁含机器相关绝对路径（前例 `.vscode/settings.json` 的 `python.pythonPath`）：指向 `.venv` 的各人配在本机用户设置。
- `.gitignore`/建环境/首跑/lock 噪声/Windows 删除 shim ⇒ **见 REF**。

## 自动化测试
- 完全离线 `.venv/bin/python -m pytest`；**后端基线（win32）721**、0 failed/0 err；**前端另计**（`npm run test:unit`=**62**）、不并入。
- ⚠️ `pytest.ini` 已含 `addopts=-q`，**别再加 `-q`**（变 `-qq` 吞汇总行）；计数一律 `--junitxml=…`+脚本解析；跑全量前确认 `novelforge/static` 存在；**落全量日志到文件再读**，别 `grep` 猜。
- **「长期稳定失败」是产品 bug 症状**：逐层打印中间返回值找根因；e2e 做改前 FAIL/改后 PASS 对照。
- 环境变量须在 import 业务模块**前**设（`config` 固化目录、`server` 导入即 `ensure_dirs()`）；`db._conn`/`_db_path` 模块级缓存⇒隔离靠 `db.close()`。
- 碰库/DB 用例必须 `isolated`、接口 `client`+`auth_headers`；假 EPUB(`b"EPUB"`)够扫描类，元数据写回/系列解析要真 EPUB(`epub_builder.build_epub`)；测试库根须在 `LIBRARY_SOURCE_DIR` 下；断言留余地。
- 全量后半程曾 segfault ⇒ `_quiesce_background()` 须在夹具 `db.close()` **之前**收尾；`watcher.wait_pending(5.0)` 非 0 即 `pytest.fail`（干净运行恒 0）。
- **仓库根防删除守卫（第 45 期，`tests/conftest.py`）**：会话级 autouse 夹具补丁删除/移走入口，目标解析到仓库根内即 `pytest.fail`；`pytest_sessionfinish` 对根文件完整性告警 ⇒ **不依赖目录重定向的最后防线**（曾出现全量 pytest 后 14 个根文件被误删）。

## 后端踩坑
- core 内一律 `from .. import config`（`import config` 被同名命名空间包劫持，启动才炸）。
- **`scrape._epoch` 世代号**：`stop(timeout)` 等不到 worker 退出⇒推进世代；各落库点校验世代、作废即停手（`aborted`）；**新增 worker 落库点必须加守卫**。
- **ISBN 形状唯一真值源=`metadata.isbn_digits`**（10 位末位可 X / 13 位纯数字；允许分隔符与 `urn:isbn:`；UUID 不认）；`library._isbn_of`/`fileops._set_isbn` 都调它（契约「一处判据」）。
- 写磁盘只用 rename/move，删除移 `CACHE_DIR/recycle`；路径用 `library.root_of(b)/b["name"]`、**禁** `config.OUTPUT_DIR/b["name"]`；`write_epub` 前先 `mkdir`。
- 库根限 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR`（`safe_path`，之外 400）；`book_id`=basename 派生+库维度化。
- ⚠️ **新增库表列须同进 `db._LIBRARY_COLS`**，否则 `update_library` **静默写不进**（界面仍显「已保存」）。
- ⚠️ **列里的 `''`=「没设过」**：`allowed_exts=''`⇒回落库类型默认；`exclude=''`⇒不过滤；**坏 JSON 当没设过**；sqlite `ADD COLUMN` 只吃常量默认 ⇒ 回落**只能放读时**。
- ⚠️ **加唯一约束/PK 看 `db.remap_book_id`**（整体 `UPDATE` 撞约束会被吞成「搬 0 行」⇒静默丢数据）；**含 book_id 的表必过四处**（清单见 REF）；契约 `tests/test_remap_tables.py`。
- ⚠️ **`migrate.execute`/`rollback` 不按 `direction` 分支**、`DIR_AUTO="move"` 字面量**不能改**（细节见 REF）。
- ⚠️ **win32 目录 `st_size` 恒 0**：「空文件」判据见 REF；目录体积用 `watcher._sig()`。
- 批量端点注册在 `/api/books/{bid}` 之前、字面量路径在 `{param}` 之前；目录型条目用 `path.exists()` 不用 `is_file()`。
- **版本唯一真值源=`server.APP_VERSION`，只由 `GET /health` 下发**；**无 `/api/health`**（白名单仅 `/health`+`/api/auth/login`+`/api/logout`）。
- 共用锁嵌套用 `RLock`；`mark_processed`/`mark_recent` 走 `asyncio.to_thread`；watcher 独立 `_scan_lock`。
- ⚠️ **`db` 只走 `db._connect()`**（持 `_lock` 的代理 `db._Conn`，`_lock` 是 RLock）；**别抓裸连接、别绕开 `_lock`**（细节/契约见 REF）。
- `core/stats.py`：`overview` 键**只增不删**、**跟随 `library_id`**、**不新增扫描路径**（细节见 REF）。
- ⚠️ **阅读状态阈值只有两入口**：后端 `lib_settings.reading_thresholds(library_id)`、前端 `lib/readingThresholds.ts`；**别第三处判**。默认值不动既有行为（finished 99.5、started 0.0≡`pct>0`）。
- ⚠️ **路径判据只有 `frontend/src/lib/paths.ts`**（`isAbsolutePath`/`pathsOverlap`）；别处抄 `startsWith('/')` ⇒ Windows `C:\…` 被判非绝对。
- **「文件:行号」收尾必须实测复核**（工具/局限见 REF）：只记真实行号、不记偏移量；判据「0 硬错+0 漂移」**且**人工过完 `--todo`。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值=每库覆写 ?? 全局`，落 `libraries.settings`；真值源 `core/lib_settings.py`+`features.SETTING_CAPS`；接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（细节见 REF）。
- 可见性=能力矩阵（库类型）∩每库开关，判定**只留一处**；「不可见」=「不存在」→404。
- ⚠️ **能力键判隐显轴**：`library.hasFeature(k)` 判「侧栏当前选着的库」，只适合全局导航/设置页；读者侧要判「**这本书**属于哪个库」。
- ⚠️ **新增「可保存的配置分区」=三处同步点**：① `server.EDITABLE` ② `GET /api/config` 硬编码键列表 ③ 前端 `settingsFields.ts` 的 `SECTION_KEYS`；漏任一处都不报错。判「某能力有无页面入口」也照这三处查。
- ⚠️ **偏好块块名清单是前后端两处真值源**：`server.PREFS_BLOCKS` ↔ 前端 `lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS`（连带相关函数）；**新增块必须两端同批改**；契约 `tests/test_prefs_shelf_block.py`。

## 前端
- Vue3 SFC+TS+Vite8+Tailwind v4+Pinia4+vue-router5(hash)；产物 `novelforge/static/v2/`（`/` 服务其 index.html，缺失 503）；**勿往 `novelforge/static/` 加手写页**。
- 演示数据禁 `Math.random()`；**路由 path 全局唯一**；`settingsNav`/router 注册表/侧栏**三处与组件同批改**；**零外部请求零 CDN**。
- ⚠️ **前端收尾必须 `npm run type-check` + `npm run build`**：`vitest` 不校验模块导出完整性（第 44 期曾把两个文件误提交成 0 B，62 个单测全过、只有构建才报断链）。
- ⚠️ 设置页 `note` 纯文本插值 ⇒ `**`/反引号/`<strong>` 原样显示（契约钉住）。
- 图表入口 `lib/charts.ts`、偏好归属、侧栏导航契约、命名避让（`/explore` vs `/browse`）、实体总览六维、窄屏双写法、`ToolsLayout` 用 `onActivated` ⇒ **域细节见 REF**。
