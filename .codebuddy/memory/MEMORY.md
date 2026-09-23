# 长期记忆（novel_dl_convert / NovelForge）

> 只留仍成立的不变式/约定/踩坑，写成规则、不带故事；某期做了什么写当天 `YYYY-MM-DD.md`；域细节/逐项清单见 `docs/bookorbit-capability-gap.md`、`module-inventory.md`、`roadmap-gaps-remaining.md`。
> 立规 09-19；09-21、09-22 三轮压缩（删叙事、合并同类、指针化）。
> **`MEMORY-REF.md`**＝运行/UI 验证手册 + 域细节 + 跨会话待办 ⇒ 动到那些领域前先读它。

## 项目与硬约定
1. TXT→EPUB 工具，NAS/容器部署；input/output 物理分离；FastAPI+CLI；可插拔书源。
2. **删功能要删干净**：路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口 404」防回归断言。
3. 写计划只写四块：需求来源/功能范围/防回归要点/任务清单（不写架构/目录/代码结构）。
4. 提交即推送：中文 commit、按能力拆多笔；收尾不留未提交改动；临时文件放 `/tmp`。
5. 视觉照搬 BookOrbit；零外部请求；局部更新不重建 DOM；**不做假交互**（宁可空态也别放假数字）。
6. 可能同时有另一 AI 会话：改前 `git status`；别人改动不回退、不顺手提交；记忆只追加。
7. 新增书库由用户手动操作；每库来源=**多个绝对路径 `source_dirs`（JSON 数组，第 41 期起）**，来源根用 `LIBRARY_SOURCE_DIRS1..N` 声明（未配则回退单根 `LIBRARY_SOURCE_DIR`）；库 `type` 只决定功能显隐矩阵。

## 元数据与出版
- **只落服务端 DB，绝不写回文件**：`meta_override`/`meta_online`/`meta_cover`/`meta_locks`/`book_custom_values`；`core/publish.py` 是**唯一**仍写文件的模块。
- **源不可变**：源只读；副本禁原地写（临时文件+`Path.replace`）；副本被删只标记待确认+记日志、**绝不自删源**；成品目录不得与库根/扫描源重叠（建库即拦）；硬链接副本内嵌元数据变独立 inode ⇒ 如实标注、不得宣称省空间。
- 源文件名无写入口：改名只剩「按命名规则重出版副本」；实体改名/合并退化为纯元数据写入。
- 命名规则**唯一实现**=`fileops.fill_pattern`（先长后短），`publish.relpath_for` 调它；`PATTERN_FIELDS` 唯一真值源、前端 `RENAME_TOKENS` 须逐字一致（契约）；**不许第二处展开规则**。
- 「预览==落盘」硬不变量：`publish.relpath_for`+`rel_verdict`（REL_REUSE/REBUILD/DECLINE）；UI 拒「有未保存草稿时重出版」；`apply_*` 目标服务端自算，客户端 `book_ids` 只当收窄条件。
- 抓取与手工编辑**不按格式分流**；非 EPUB 无 OPF 兜底，「恢复」=撤销覆盖回落在线值。
- **目录型条目（有声书一章一文件）同样出版**：副本真目录+内部逐文件硬链接；形态判据=**名字带不带 `library.BOOK_EXTS` 扩展名**（不看 format、不 stat 磁盘）；副本名不带扩展名。
- 无值哨兵 `db.META_CLEAR="-"`（`_CLEARABLE` 全字段、有测试）：空串=撤销覆盖、接口 `null`=显式清空；三处翻译须一致：`db.get_effective_meta`/`metastore.effective`/`metastore.state`。
- **三层** `override > online > opf`；抓取受**三道正交闸**：①字段策略 `metadata_fetch.fields[key]∈{overwrite(默认)/fill_only/skip}`（全局+每库）②**`meta_locks` 显式字段锁**（只挡抓取、不挡手工编辑；解锁后抓取重新接管）③「改过就不动」（`field in overrides` 隐式）；**自定义字段默认值同受这三道闸**。
- `metadata_fetch.custom_fields` 已下线（移 `custom_field_defs`，`key`/`label` 分离）；`custom_fields` 仍在 `metascore.NOT_SCORED`、权重表未动。
- 相似书权重 `0.5·词袋余弦 + 0.1·同作者 + 0.25·题材 Jaccard + 0.1·同系列 + 0.05·评分接近度`；`limit`≤25、详情页默认 6 可展开；任一方未评分不进分母；词袋**简介不进**；0 分不返回；`SimilarBook.score`=0–1（前端不显示）。
- **软删除**：`DELETE`=移垃圾桶（`deleted_at`），`purge` 才真删且只对垃圾桶开放；**一切读点须 `WHERE deleted_at=0`**（含 `annotation_counts`/`trashed_*`/remap 探测）。
- **作者排序名两列**：`sort_name`（**派生 / 在线**）与 `sort_name_local`（**用户覆盖**）；展示取 覆盖 > 派生（`authors.sort_name_of`）。⚠️ **派生 / 回填只写 `sort_name`，绝不动 `sort_name_local`**（写后者＝冒充用户改过，界面误显示「已覆盖」并挡住抓取）。派生规则 `authors.derive_sort_name`：拉丁两名 →「姓, 名」、多名带小词表（`Le Guin`），**CJK 原样返回 ⇒ 跳过**（填了等于没填）。
- **系列缺册**：唯一实现 `library.series_gaps` —— 按 `series_index` 数字集合求 `[1..max]` 补集；**无序号 / 非数字序号各自单列、不并入缺册**（前端不再自己算）。
- **阅读尝试（轮次）**：`reading_attempts` 表；一轮 =「开始读 → 读完」，读完再开始＝新一轮（`round` 递增）。⚠️ 自动维护挂 `db.set_status`（进 reading 开轮 / finished 收尾；**搁置·弃读不动轮次**）；`reset_reading_state` **四清**（含 attempts）；表已进 `ORPHAN_TABLES`/`REMAP_TABLES`。

## Git / 环境 / 构建
- 行尾必须 **LF**（`.gitattributes` 锁；CRLF ⇒ 容器 `sh /app/start.sh` 报 `set: Illegal option -` 反复重启）。
- Python 3.10+（PEP 604，系统 python3.9 不可用）；Node v20/22、Docker daemon 可用；本机对外网络有限。⚠️ **本机 `nvm` 是空的另一套**，可用的 Node 是 IDE 管理的 `.workbuddy/binaries/node/versions/<ver>`——跑 npm 前把它加进 PATH，见 REF「运行 / UI 验证」。
- 认证走 GCM；**勿再引入** token 内嵌/insteadof 明文重写；推送失败先查认证/网络，**别改 git config**。
- **入库配置不得含机器相关绝对路径**（`.vscode/settings.json` 的 `python.pythonPath` 是前例）：指向 `.venv` 的各人配在本机用户设置。
- `.gitignore`/macOS 建环境/首跑/`npm install` 的 lock 噪声/Windows 删除 shim ⇒ **见 REF「环境与构建」**。

## 自动化测试
- 完全离线 `.venv/bin/python -m pytest`；dev 依赖在 `requirements-dev.txt`；**基线** win32 **651** / POSIX **632**，0 failed/0 err；**前端另计**（`npm run test:unit`），两套跑法两套前提、不并入此基线。
- ⚠️ `pytest.ini` 已有 `addopts=-q`，命令行**别再加 `-q`**（变 `-qq` 吞掉汇总行）；计数量一律 `--junitxml=…` + Python 解析（根 `<testsuites>`，非 `<testsuite>`）；跑全量前确认 `novelforge/static` 存在。
- ⚠️ 看真相**落全量日志到文件再读**，别用 `grep` 猜（`-qq` 下无汇总行、grep 大小写敏感会误读）。
- **「长期稳定失败」是产品 bug 症状**：逐层打印中间返回值找根因；e2e 做改前 FAIL/改后 PASS 对照。
- 环境变量须在 import 业务模块**前**设（`config` 固化目录、`server` 导入即 `ensure_dirs()`）；`db._conn`/`_db_path` 模块级缓存 ⇒ 隔离靠 `db.close()`。
- 碰库/DB 用例必须 `isolated`、接口 `client`+`auth_headers`；假 EPUB(`b"EPUB"`)够扫描类，元数据写回/系列解析要真 EPUB(`epub_builder.build_epub`)；测试库根须在 `LIBRARY_SOURCE_DIR` 下；断言留余地。⚠️ `isolated` 换库=改 `DATA_DIR`+`db.close()`（只 `close()+init()` 重开同一文件）。
- 全量后半程曾 segfault ⇒ `tests/conftest.py` 的 `_quiesce_background()` 须在夹具 `db.close()` **之前**收尾；`watcher.wait_pending(5.0)` 非 0 就 `pytest.fail`（干净运行恒为 0，不误伤）。

## 后端约束与踩坑
- core 内一律 `from .. import config`（`import config` 被同名命名空间包劫持，启动才炸）。
- **`scrape._epoch` 世代号**：`stop(timeout)` 等不到 worker 退出⇒推进世代；`process`/`_failed`/`_lost`/`verify` 每个落库点都校验世代，作废即停手（返回 `aborted`）；`gen=None`=同步调用；**新增 worker 落库点必须加守卫**。
- **ISBN 形状唯一真值源=`metadata.isbn_digits`**（10 位末位可 X / 13 位纯数字，允许分隔符与 `urn:isbn:`；UUID 不认）；`library._isbn_of`/`fileops._set_isbn` 都调它（契约钉「全仓一处判据」）。
- 写磁盘只用 rename/move，删除移 `CACHE_DIR/recycle`；路径用 `library.root_of(b)/b["name"]`，**禁** `config.OUTPUT_DIR/b["name"]`；`write_epub` 前先 `mkdir`。
- 库根限 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR`（`safe_path`，之外 400）；`book_id`=basename 派生+库维度化。⚠️ 库存储根在 `OUTPUT_DIR` 下时 `default` 库把副本再收一次（断言按 `library_id` 过滤）。
- ⚠️ **新增库表列须同进 `db._LIBRARY_COLS`**，否则 `update_library` **静默写不进**（过滤后为空就原样返回，界面还显「已保存」）；第 40 期 `icon`/`allowed_exts`/`exclude` 三列均在其内。
- ⚠️ **列里的 `''`=「没设过」**：`allowed_exts=''`⇒回落库类型默认白名单；`exclude=''`⇒不过滤；**坏 JSON 当没设过**（不抛、不留死库）；sqlite `ALTER TABLE ADD COLUMN` 只吃常量默认值 ⇒ 回落**只能放读时**。
- ⚠️ **加唯一约束/PK 看 `db.remap_book_id`**：整体 `UPDATE` 撞约束被 `except` 吞成「搬 0 行」⇒静默丢数据 ⇒ 必须**逐行搬+冲突取舍**。**含 book_id 的表必过四处**：`ORPHAN_TABLES`/`REMAP_TABLES`/有软删进 `REMAP_PROBE_FILTER`/含库相关列进 `REMAP_EXPLICIT_TABLES`（唯一成员 `scrape_items`）。契约 `tests/test_remap_tables.py` 钉「含 book_id 列的表必在某一清单」。
- ⚠️ **`migrate.execute`/`rollback` 不再按 `direction` 分支**：自动归库(`move`)与用户移动(`bookmove`)共用 `_after_bookmove`/`_after_bookmove_back`，回程对称。`DIR_AUTO="move"` 字面量**不能改**；`server.py` 拒用 bookmove 执行自动归库批次那两处**保留**；反查所属库用 `_lib_id_of_path`（取**最长**匹配）。
- ⚠️ **win32 目录 `st_size` 恒 0**：「空文件」判据须 `if not p.is_dir() and p.stat().st_size==0`；目录体积用 `watcher._sig()`。
- 批量端点注册在 `/api/books/{bid}` 之前、字面量路径在 `{param}` 之前；目录型条目用 `path.exists()` 不用 `is_file()`。
- **版本唯一真值源=`server.APP_VERSION`，只由 `GET /health` 下发**；**无 `/api/health`**（白名单仅 `/health`+`/api/auth/login`+`/api/logout`）；前端 `api.ts` 的 `health()` 走 `/health`。
- 共用锁嵌套用 `RLock`；`mark_processed`/`mark_recent` 走 `asyncio.to_thread`；watcher 独立 `_scan_lock`。
- ⚠️ **`db` 访问只走 `db._connect()`**（持 `_lock` 的代理 `db._Conn`，非裸 `sqlite3.Connection`）；`_lock` 是 **RLock**（非重入锁会自锁死）；`with _lock:` 块内还会再 `c.execute`。**别抓裸连接、别绕开 `_lock`**（「锁内写+裸读」实测全 `InterfaceError`、裸读+`close()` 全段错误）；`db._Result` 接口面收窄（execute/executemany/executescript/commit/rollback + 标量/fetchone/fetchall/迭代），新增游标属性要补。契约 `tests/test_db_concurrency_contract.py`。
- ⚠️ **`db.close()` 生产无人调**，但「锁内写+裸读」生产可达（watcher/scrape/asyncio.to_thread 并发）；旧代理线程拿 `ProgrammingError` 是**真错误、别吞**。
- `core/stats.py`：`overview` 键**只增不删**、**须跟随 `library_id`**、**不新增扫描路径**；真名照代码（`weekdays`/`pages_by_format`）。
- ⚠️ **阅读状态阈值只有两入口**：后端 `lib_settings.reading_thresholds(library_id)`、前端 `lib/readingThresholds.ts`（`statusFromPercent`/`statusBucket`/`statusLabelOf`）；**别再第三处判**。默认值刻意不动既有行为（finished **99.5**、started **0.0**≡`pct>0`）。第 41 期把 `ShelfView` 筛选与 `BookCover` 角标收口到 `statusBucket`/`statusLabelOf`（与书卡 `bookInfo.statusLabel` 同源）；`stores/library.ts` 的 `derivedStatus` 分面计数保持进度口径、不在其列。
- ⚠️ **路径判据只有 `frontend/src/lib/paths.ts`**（`isAbsolutePath`/`pathsOverlap`）；原来两处各写 `startsWith('/')` 抄 POSIX 口径 ⇒ Windows `C:\…` 被判非绝对。
- **「文件:行号」收尾必须实测复核**：`tests/check_doc_anchors.py`（非 `test_` 前缀⇒pytest 不收集）。①别记偏移量、只记真实行号；②脚本只生成待核清单、不能判定「行号合法但内容换了」⇒ 判据「0 硬错+0 漂移」**且**人工过完 `--todo`。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值=每库覆写 ?? 全局`，落 `libraries.settings`（稀疏 JSON，键=全局点分路径）。
- `core/lib_settings.py` 与 `features.SETTING_CAPS` 唯一真值源；接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（`?keys=` 按项恢复）；可覆盖项清单见 REF。
- 可见性=能力矩阵（库类型有没有）∩ 每库开关，判定**只留一处**；「不可见」=「不存在」→404。
- ⚠️ **能力键判隐显轴**：`library.hasFeature(k)` 判「侧栏当前选着哪个库」，只适合全局导航/设置页；读者侧要判「**这本书**属于哪个库」。
- ⚠️ **新增「可保存的配置分区」=三处同步点**：① `server.EDITABLE` 白名单 ② `GET /api/config` 里硬编码键列表 ③ 前端 `settingsFields.ts` 的 `SECTION_KEYS`。漏任一处都**不报错**（①漏⇒400「无可保存项」；②漏⇒写进读不回；③漏⇒开关正常但 patch 空），表现都只一条 toast。判「某能力有没有页面入口」也照这三处查。
- ⚠️ **偏好块的块名清单是前后端两处真值源**：`server.PREFS_BLOCKS` ↔ 前端 `lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS`（连带 `PrefsPayload` / `normalizePayload` / `prefSync` 的 `collect`·`applyPayload`）。**新增块必须两端同批改**；漂移表现很隐蔽（推上去 400 / 拉回来静默丢字段）。契约测试 `tests/test_prefs_shelf_block.py`（第 43 期加的第 7 块 `shelf`：只承载 `collapseSeries`）。

## 前端
- Vue3 SFC+TS+Vite8+Tailwind v4+Pinia4+vue-router5(hash)；产物 `novelforge/static/v2/`（`/` 服务其 index.html，缺失 503）；**勿往 `novelforge/static/` 加手写页**。
- 演示数据确定性常量禁 `Math.random()`；**路由 path 全局唯一**（同 path 两条被静默覆盖+侧栏重复 key）；`settingsNav`/router 注册表/侧栏**三处与组件同批改**；**零外部请求零 CDN**。
- ⚠️ 设置页 `note` 纯文本插值 ⇒ `**`/反引号/`<strong>` 原样显示（契约钉住）。
- 图表唯一入口 `lib/charts.ts`、偏好归属、侧栏导航契约、命名避让（`/explore` vs `/browse`）、实体总览六维、窄屏双写法、`ToolsLayout` 用 `onActivated` ⇒ **域细节见 REF**，动前先读。
