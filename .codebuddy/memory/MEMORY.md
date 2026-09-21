# 长期记忆（novel_dl_convert / NovelForge）

> 只留**仍然成立的不变式/约定/踩坑**，写成规则、不带故事；某期做了什么写当天 `YYYY-MM-DD.md`；口径依据与逐项清单在 `docs/bookorbit-capability-gap.md`、`module-inventory.md`、`roadmap-gaps-remaining.md`。
> 立规 09-19；09-21 两轮压缩（删叙事、合并同类、指针化、域细节外移）。
> **`MEMORY-REF.md`**＝运行/UI 验证手册 + 域细节 + 跨会话待办 ⇒ **动到那些领域前先读它**。

## 项目与硬约定
1. TXT→EPUB 工具，NAS/容器部署；input/output 物理分离；FastAPI+CLI；可插拔书源。
2. **删功能要删干净**：路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口 404」防回归断言。
3. 写计划只写四块：需求来源/功能范围/防回归要点/任务清单（不写架构/目录/代码结构）。
4. 提交即推送：中文 commit、按能力拆多笔；收尾不留未提交改动；临时文件放 `/tmp`。
5. 视觉照搬 BookOrbit；零外部请求；局部更新不重建 DOM；**不做假交互**（宁可空态也别放假数字）。
6. 可能同时有另一 AI 会话：改前 `git status`；别人改动不回退、不顺手提交；记忆只追加。
7. 新增书库由用户手动操作；每库来源=`LIBRARY_SOURCE_DIR/<source_subdir>`；库 `type` 只决定功能显隐矩阵。

## 元数据与出版
- **只落服务端 DB，绝不写回文件**：`meta_override`/`meta_online`/`meta_cover`/`meta_locks`/`book_custom_values`。编辑、revert、抓取、重排册号、改名、合并一视同仁；`core/publish.py` 是**唯一**仍写文件的模块。
- **源不可变**：源只读；副本禁原地写（共享 inode ⇒ 临时文件+`Path.replace`）；副本被删只标记待确认+记日志、**绝不自删源**；成品目录不得与库根/扫描源重叠（建库即拦）。硬链接副本内嵌元数据会变独立 inode ⇒ 如实标注、**不得宣称省空间**。
- **源文件名无写入口**：改名只剩「按命名规则重出版副本」；实体改名/合并退化为纯元数据写入。
- 命名规则**唯一实现**=`fileops.fill_pattern`（**先长后短**），`publish.relpath_for` 调它；`PATTERN_FIELDS` 为唯一真值源、前端 `RENAME_TOKENS` 须逐字一致（契约测试）。**不许第二处展开规则**。
- 「预览==落盘」硬不变量：共用 `publish.relpath_for`+`rel_verdict`（REL_REUSE/REBUILD/DECLINE）；UI 拒「有未保存草稿时重出版」；`apply_*` 目标**一律服务端自己算**，客户端 `book_ids` 只当收窄条件。
- 抓取与手工编辑**不按格式分流**；非 EPUB 无 OPF 兜底，「恢复」=撤销覆盖回落在线值。
- **目录型条目（有声书一章一文件）同样出版**：副本真目录+内部逐文件硬链接；形态判据=**名字带不带 `library.BOOK_EXTS` 扩展名**（不看 format、不 stat 磁盘）；副本名不带扩展名。
- 无值哨兵 `db.META_CLEAR="-"`（`_CLEARABLE` 全字段、有测试）：空串=撤销覆盖、接口 `null`=显式清空；三处翻译须一致：`db.get_effective_meta`/`metastore.effective`/`metastore.state`。
- **三层** `override > online > opf`。抓取写入受**三道正交闸**：①字段策略 `metadata_fetch.fields[key]∈{overwrite(默认)/fill_only/skip}`（全局+每库）②**`meta_locks` 显式字段锁**（**只挡抓取、不挡手工编辑**；能锁「没改过」的字段，解锁后抓取重新接管）③「改过就不动」（`field in overrides` 隐式）。**自定义字段默认值同受这三道闸**。
- `metadata_fetch.custom_fields` 配置项**已下线**（定义移 `custom_field_defs`，一处权威；`key`(slug) 与 `label` 分离 ⇒ 改标签不动值；`library_ids` 空=全部书库）；`custom_fields` 仍在 `metascore.NOT_SCORED`、**权重表未动**。
- 相似书权重 `0.5·词袋余弦 + 0.1·同作者 + 0.25·题材 Jaccard + 0.1·同系列 + 0.05·评分接近度`；`limit`≤**25**、详情页默认 6 可展开；任一方未评分 ⇒ 该路**不进分母**；词袋**简介刻意不进**；0 分不返回；`SimilarBook.score`=**0–1**（前端不显示）。
- **软删除语义**：`DELETE`=移垃圾桶（`deleted_at`），`purge` 才真删且只对垃圾桶内开放；**一切读点必须 `WHERE deleted_at=0`**（含 `annotation_counts`/`trashed_*`/remap 探测）。

## Git / 环境 / 构建
- 行尾必须 **LF**（`.gitattributes` 锁；CRLF ⇒ 容器 `sh /app/start.sh` 报 `set: Illegal option -` 反复重启）。
- Python 3.10+（**PEP 604，系统 python3.9 不可用**）；Node v20/22、Docker daemon 可用；本机对外网络有限。
- 认证走 GCM；**勿再引入** token 内嵌/insteadof 明文重写；推送失败先查认证/网络，**别改 git config**。
- **入库的配置不得含机器相关绝对路径**（`.vscode/settings.json` 的 `python.pythonPath` 是前例）：要指向 `.venv` 的各人配在本机用户设置里。
- `.gitignore` 清单、macOS 建环境与首跑、`npm install` 的 lock 噪声、Windows 删除 shim ⇒ **见 REF「环境与构建」**。

## 自动化测试（硬前提）
- 完全离线 `.venv/bin/python -m pytest`；dev 依赖在 `requirements-dev.txt`。**基线按环境取**：POSIX 36 期 595 例 / 0 failed（34 期记 475 → 36 期开工时实测基线 548 → 595）；win32 33 期 404 例 / 0 failed（**未随 POSIX 重取**）。
- ⚠️ **`pytest -q` 汇总行抓不到**（重定向后只剩 warnings）⇒ 一律 `--junitxml=/tmp/nf.xml` + Python 解析 `//testcase[failure|error]`（**别用 `[xml]`**）；跑全量前确认 `novelforge/static` 存在。
- **「长期稳定失败」不是 flaky，是产品 bug 的症状**：报错不指向根因就逐层打印中间返回值；修完临时回退那一处确认「恰好相关用例失败」；e2e 做改前 FAIL / 改后 PASS 对照。
- 硬前提：①环境变量须在 import 业务模块**前**设（`config` 导入即固化目录、`server` 导入即 `ensure_dirs()`）；②`db._conn`/`_db_path` 是模块级缓存 ⇒ 隔离靠 `db.close()`。
- 碰库/DB 用例必须 `isolated`、接口一律 `client`+`auth_headers`；假 EPUB（`b"EPUB"`）够扫描类，元数据写回/系列解析要真 EPUB（`epub_builder.build_epub`）；测试库根须在 `LIBRARY_SOURCE_DIR` 下；断言留余地。⚠️ `isolated` 换库=改 `DATA_DIR`+`db.close()`（只 `close()+init()` 会重开**同一个文件**）。
- 全量后半程曾 segfault ⇒ `tests/conftest.py` 的 `_quiesce_background()` 在夹具 `db.close()` **之前**收尾。

## 后端约束与踩坑
- core 内一律 `from .. import config`（`import config` 被同名命名空间包劫持，启动才炸）。
- **`scrape._epoch` 世代号**：`stop(timeout)` 等不到 worker 真退出 ⇒ 它**必定推进世代**；`process`/`_failed`/`_lost`/`verify` 每个落库点都校验世代，作废即停手不落库（返回 `aborted`，留待下轮 `reset_running`）；`gen=None`=同步调用。**新增 worker 落库点必须一并加守卫**。
- **ISBN 形状唯一真值源=`metadata.isbn_digits`**：10 位末位可 X / 13 位纯数字，允许分隔符与 `urn:isbn:`；**UUID 不认**。`library._isbn_of` 与 `fileops._set_isbn` 都调它（契约测试钉「全仓只剩一处判据」）。
- 写磁盘只用 rename/move，删除移 `CACHE_DIR/recycle`；路径用 `library.root_of(b)/b["name"]`，**禁** `config.OUTPUT_DIR/b["name"]`；`write_epub` 前先 `mkdir`。
- 库根限 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR`（`safe_path`，建库强校验，之外 400）；`book_id`=basename 派生+库维度化。⚠️ 库存储根在 `OUTPUT_DIR` 之下时 `default` 库会把副本**再收一次** ⇒ 同一本书两条（预期行为，断言按 `library_id` 过滤）。
- 新增库表列须同进 `db._LIBRARY_COLS`，否则 `update_library` 静默写不进。
- **给既有表加唯一约束/PK 要回头看 `db.remap_book_id`**：整体 `UPDATE` 撞约束会抛异常并被外层 `except` 吞成「搬 0 行」⇒ **静默丢数据** ⇒ 必须**逐行搬 + 冲突时取舍**。**新增含 book_id 的表必须过三处**：`ORPHAN_TABLES`、`REMAP_TABLES`、有软删的再进 `REMAP_PROBE_FILTER`。
- ⚠️ **win32 上目录 `st_size` 恒为 0**：「空文件」判据都要**排除目录**（`if not p.is_dir() and p.stat().st_size == 0`），否则 win32 有声书永不入库；目录体积用 `watcher._sig()`。
- 批量端点注册在 `/api/books/{bid}` 之前、字面量路径在 `{param}` 之前；目录型条目用 `path.exists()` 不用 `is_file()`。
- **版本唯一真值源=`server.APP_VERSION`，只由 `GET /health` 下发**：**没有 `/api/health`**（白名单只含 `/health`+`/api/auth/login`+`/api/logout`）；前端 `api.ts` 的 `health()` 也走 `/health`。
- 共用锁嵌套用 `RLock`；`mark_processed`/`mark_recent` 走 `asyncio.to_thread`；watcher 独立 `_scan_lock`。
- `core/stats.py`：`overview` 既有键**只增不删**、**必须跟随 `library_id`**、**不新增扫描路径**；真名照代码（`weekdays`/`pages_by_format`）。
- **「文件:行号」收尾必须实测复核**：工具=`tests/check_doc_anchors.py`（**非 `test_` 前缀 ⇒ pytest 不收集**），用法与局限见 capability-gap §0.5。①**别记偏移量，只记当前真实行号**；②脚本**只生成待核清单、不能判定**（「行号合法但内容换了」天生测不出）⇒ 判据是「0 硬错 + 0 漂移」**且**人工过完 `--todo` 清单。先例：32 期核 71 修 10、33 期核 312 修 28、35 期核 706 修 37、36 期核 719 修 7（**7 处全部落在本期自己动过的 `core/db.py` / `server.py` 上** ⇒ 动了锚点密集的文件就顺手重核那一份）。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值=每库覆写 ?? 全局`，落 `libraries.settings`（稀疏 JSON，键=全局点分路径）。
- `core/lib_settings.py` 与 `features.SETTING_CAPS` 是唯一真值源；接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（`?keys=` 按项恢复）；**可覆盖项清单见 REF**。
- 可见性=能力矩阵（库类型有没有）∩ 每库开关，判定**只留一处**；「不可见」=「不存在」→ 404。
- ⚠️ **能力键的判隐显轴要挑对**：`library.hasFeature(k)` 判的是「侧栏**当前选着**哪个库」，只适合**全局导航项/设置页**；读者侧要判「**这本书**属于哪个库」。
- ⚠️ **判断「某能力有没有页面入口」两头查**：先查 `server.py` 的 `EDITABLE` 白名单，再查前端 `settingsFields.ts`（只看配置文件会误判）。

## 前端
- Vue3 SFC+TS+Vite8+Tailwind v4+Pinia4+vue-router5(hash)；产物 `novelforge/static/v2/`（`/` 服务其 index.html，缺失 503）；**勿往 `novelforge/static/` 加手写页**。
- 演示数据确定性常量禁 `Math.random()`；**路由 path 全局唯一**（同 path 两条被静默覆盖+侧栏重复 key）；`settingsNav`/router 注册表/侧栏**三处与组件同批改**；**零外部请求零 CDN**。
- ⚠️ **设置页 `note` 是纯文本插值** ⇒ 写 `**`/反引号/`<strong>` 会**原样显示**（有契约测试钉住）。
- 图表（唯一入口 `lib/charts.ts`）、偏好归属、侧栏导航契约、命名避让（`/explore` vs `/browse`）、实体总览六维、窄屏双写法、`ToolsLayout` 用 `onActivated` —— **域细节见 REF**，动前先读。
