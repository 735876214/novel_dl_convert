# 长期记忆（novel_dl_convert / NovelForge）

> 真值源 = `.codebuddy/memory/`；结构性决策留本文件，逐期细节看同名日记 `YYYY-MM-DD.md`。

## 项目 / 约定
- **TXT 小说 → EPUB 工具**，NAS/容器部署；`input`/`output` 物理分离；FastAPI + CLI；可插拔书源（Gutenberg + JSON 规则）。镜像 `ghcr.io/735876214/novel_dl_convert:latest`。
- **写计划只写四块**：需求来源 / 功能范围 / 防回归要点 / 任务清单；**不要**输出架构设计、目录结构、关键代码结构（2026-09-18 用户明确要求）。
- **提交即推送**：做完 `git add → commit → push`，中文信息，**按能力拆多个 commit**（`feat(core)` → 各能力 → `feat(server)` 接线 → `feat(frontend)` → `chore(build)` → `docs`）。
- 视觉**严格照搬 BookOrbit**（自创已否决）；**零外部请求**；**局部更新**，不重建 DOM。
- ⚠️ 本工作区**可能同时有另一个 AI 会话**：改文件前先 `git status`；别人的改动不回退；临时文件放 `/tmp`；写记忆一律**追加**。

## 记忆 / Git / 环境
- `.gitignore`：`.codebuddy/*` + `!.codebuddy/memory/`（否定规则须配 `/*` 且**不带尾斜杠**）；忽略 `data/`、`*.db`、`/data-test/`、`.playwright-cli/`、`novelforge/static/v2/`。
- 认证走 **GCM**；URL 内嵌 token 与 `insteadof` 明文重写已清除，**勿再引入**。推送失败先查认证/网络，别改 git config。
- Python 需 **3.10+**（放 `.venv`）；Node v20/22 皆可。**Docker daemon 可用**（Linux 容器环境），本机网络对外有限制。
- 行尾必须 **LF**（`.gitattributes` 已锁）；CRLF 会让容器 `sh /app/start.sh` 报 `set: Illegal option -` 并反复重启。

## 前端栈 / 规范
- `frontend/` = **Vue 3 SFC + TS + Vite 8 + Tailwind v4 + Pinia 4 + vue-router 5**（勿再往 `novelforge/static/` 加手写页面）；产物落 `novelforge/static/v2/`（gitignore），FastAPI 挂 `/static`，`/` 服务其 `index.html`（缺失 503）；路由 **hash 模式**。
- 样式**全用** Tailwind v4 工具类 + BookOrbit 语义 token；重复类串封装进 `components/ui/*`。**`bridge.css` 是前提**（`@theme inline` 桥接层）；**`main.css` 必须有 `@custom-variant dark (&:is(.dark *));`**。
- 主题：`<html>` 挂 `dark`/`accent-*`/`radius-*`；localStorage `theme`/`accent`/`radius`（JSON）+ `nav-collapsed`/`dashboard-widgets`/`dashboard-shelves`；`index.html` 防 FOUC。BookOrbit **默认暖中性**，蓝只是 accent 之一。
- 仪表盘 = 部件行（`widgets/registry.ts` 12 登记 / 3 实现，未实现置灰）+ 书架行；**演示数据必须确定性常量，禁止 `Math.random()`**。
- `settingsNav.ts`/`router` 里「标 ready 但未注册组件」会 `console.error` → **注册表与组件必须同批改**（`libraries` 页已是 `placeholder`，只跳 `/tools/libraries`）。
- ⚠️ **Vue 模板不渲染 markdown**：模板里写 `**强调**` 会原样显示星号 → 静态文本用 `<strong>`，JS 字符串别加星号。
- **侧栏**：品牌区 → 主导航（仪表盘/探索发现/任务中心/工具）→ 四个可折叠组（浏览/库/智能书架/收藏夹），无 footer。**顶栏顺序固定**：侧栏开关 → 全局搜索（⌘K）→ 通知 → 数据统计 → 任务面板（抽屉）→ 主题 → 设置 → 头像。`/settings` 用 `SettingsSidebar`（含「返回主界面」+ `SETTINGS_GROUPS`）替换 `AppSidebar`。

## 工具页（单页 9 标签，硬约定）
- `ToolsLayout.vue` = `/tools` 外壳，只有「标签栏 + 嵌套 `<RouterView>` + `KeepAlive :max="8"`」，**无卡片外框与内边距**。顺序：书库管理/实体管理/批量重命名/重复书籍/缺失资源 → 书源管理/导出目录/本地转换/转换日志；后段三个**按当前库能力裁剪**；**不做权限门控**。
- **状态保持硬要求**：子页用 `onActivated`（**别挂 `onMounted`**），**不要在 `onActivated` 里重置用户输入/勾选/预览**。
- **改磁盘的工具一律「先预览、再应用」**；`apply` 只认前端回传的**具体条目**；**删除即移入回收目录**（`CACHE_DIR/recycle`，**永不 `unlink`**）；每次改动写活动日志。
- 四个工具页（实体管理/批量重命名/重复书籍/缺失资源）有「范围：当前库 / 全部书库」（`LibraryScopeSwitch.vue`）；全部时按库分组并标「跨库重复」。

## 后端模块
- `core/library.py`（只读）：按 `libraries` 表**逐库扫描并合并**，EPUB 真解 zip 读 OPF；**缓存按库分桶**（TTL 5s + 目录指纹），写后 `invalidate(library_id)`。`BookCard.id` = `_book_id`（**basename 派生**）；**`name` = 相对所属库根的路径**；`by_id` 命中多库**显式报错**（`BookIdConflict`）。
- `core/fileops.py`（写）：`safe_path(name, library_id)`（拒分隔符/`..`/绝对路径；父目录**恰好**是所属库根）、`plan_*` 预览、`apply_rename`、`apply_conflict_rename`、`recycle_items`、`apply_komga_layout`、`patch_epub_meta`/`patch_opf_meta`/`rewrite_epub`。**只用 `rename`/`move`，从不 `unlink`。** ⚠️ **禁止 `config.OUTPUT_DIR / b["name"]`** —— 一律 `library.root_of(b) / b["name"]`。
- `core/pipeline.py` 分发（`.txt` 转换 / 电子书复制 / 其它跳过），`EBOOK_EXT` 含 `.cbz/.cbr` 与音频。`core/comics.py` CBZ/CBR **zip/rar 双后端 + 魔数嗅探**，缺解压器 503。`core/audio.py` 音频目录 = 一本书。`core/komga.py` 系列推断**保守**。
- `sources/`（gutenberg/generic/rules/store/manager）；`server.py` 只做校验与胶水；`cli.py` convert/search/download/update/watch/scan/logs。
- `activity_log.py`：**双写** `activity.log` + `activity.jsonl`，失败降级临时目录；**内存与文件都存旧→新，`reversed()` 后给 API**。
- `watcher.py`：**轮询**；写入稳定判定（连续 `stable_rounds` 次同 size）；状态存 `CACHE_DIR/watcher_state.json`；失败 3 次跳过；`_target()` → `(库实体|None, 库根)`。
- ⚠️ core 内引用配置一律 `from .. import config`；`import config` 会被同名命名空间包劫持（**py_compile 抓不到，启动才炸**）。

## 配置分层（第 13 期：四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时叠加 `生效值 = 每库覆写 ?? 全局值`。落点 `libraries.settings`（**稀疏 JSON**，键 = 全局点分路径如 `output.layout`；**只存被覆写的键**），老库靠幂等 `ALTER TABLE libraries ADD COLUMN settings`。
- `core/lib_settings.py`：`effective()`（生效值 + `overridden` + `overrides`）/ `config_for()`（**深拷贝**）/ `apply_to()`（只并入**真正覆写过**的键 → 「库没覆写 = 行为不变」）/ `set_overrides`（`None` = 恢复继承，全清则整体摘掉）/ `clear_overrides(keys?)` / `schema(type)`。**不改 `config.load_config()` 语义。**
- 与 `features.allows_setting` 联动：库类型没这能力 → 覆盖项**不返回、不生效**（历史残留也不会「活过来」）；`features.SETTING_CAPS` 是唯一真值源。接口：`GET/PUT/DELETE /api/libraries/{lid}/settings`（`?keys=` 按项恢复）。
- `db.py` 新增列**必须**同进 `_LIBRARY_COLS`，否则 `update_library` **静默写不进**。
- 覆盖项：`output.format`、`output.layout`、`watcher.recursive`、`watcher.copy_non_txt`、`metadata_fetch.enabled/.threshold/.fields`、`naming.pattern/.scope`。

## 元数据：在线优先分层（第 8 期）
- 分层 `meta_override`（用户编辑，受保护）> `meta_online`（在线值）> `opf`（原值）。`meta_override.orig` = **首次覆盖前的 OPF 原值**；`authors` 在线/本地覆盖**分列**，写覆盖必须 **upsert**。
- `core/metastore.py` 分层解析，**只服务详情/编辑接口，`library.books()` 热路径不动**。`core/metafetch.py` 的 `DEFAULT_POLICY` = **`overwrite`**（可逐字段 `fill_only`/`skip`），`plan()` **跳过用户改过的字段**；策略**按书所属库**取。
- `core/metasources.py`：OpenLibrary / Google Books（**无需 Key**）；**ISBN 精确匹配**优先，否则书名 0.7 + 作者 0.3。`core/authors.py` 头像 → **`CACHE_DIR/authors/`**（零外链）；相似度 **<0.5 视为不同人**。头像端点已进 `_MEDIA_TOKEN_PATHS`（`<img src>` 只能靠 `?token=`）。

## 多书库（第 10 期）
- **四项结构决策**（改前须重新确认）：① `/api/libraries` = **库实体**，格式分面改址 `/api/library-facets`；② **库根不设默认、逐库选**（`inplace` / `import`），库里只存**相对的** `source_subdir`；③ **迁移首次需一次确认**（预览 + manifest，阻塞等确认）；④ 保留**「全部书库」为默认不裁剪**。
- **库是数据**（`libraries` 表）；表为空时 `ensure_default_library()` 落「默认库 = `OUTPUT_DIR`」（**启动必须调用**，漏掉会让书目为空 → 孤儿判定**真删**进度/批注）。类型 `ebook`/`comic`/`audiobook`/`mixed`。
- `core/migrate.py`：**只挪库不改名**（`book_id` 不变）；manifest 先行 → 幂等 + 可回滚；同名**拒绝覆盖**并建议 `X (2).ext`。
- `core/library_rules.py`：归库优先级 **来源子目录名 > 格式 > 关键词**；`resolve_target()` 返回决策结构（含跨库同名闸门），`target_root()` 是薄壳；**摄入侧取目标目录的唯一入口**（watcher/上传/convert-path/书源/OPDS 共用）。
- **跨库同名防护（第 13 期）**：`guard_conflict` —— **同库同名 = 重新投递，放行**；跨库才抛 `IngestConflict`（带建议名）。`library.id_conflicts()`/`id_conflict_with()`/`suggest_name()`；`fileops.apply_conflict_rename()` 改名必换 `book_id` → 必须 `db.remap_book_id` 搬 `REMAP_TABLES`（否则进度/批注清零），**basename 未变必须跳过**。接口 `GET /api/library-conflicts` + `POST /api/library-conflicts/apply`。
- **范围参数语义**：工具端点可选 `library_id`，**空串 = 全部书库 = 零行为变化**，不存在 → 404（`_opt_library()`）。
- `core/features.py`：库类型 → 能力矩阵（真值源）；前端需求表 `AppSidebar.ITEM_FEATURE`、`ToolsLayout` 的 `feature`、`settingsNav.PAGE_FEATURE`、`dashboard.WIDGET_FEATURE`；「全部书库」= 不裁剪。
- **安全边界**：库根**只允许**落在 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR` 之内 —— 库根就是 `safe_path` 的边界。**`book_id` 仍由 basename 派生、不做数据迁移**，跨库同名由入库冲突检测拦住。
- 前端 `stores/library.ts`：`currentLibraryId`（localStorage `nf_current_library`，空 = 全部）、`scopedBooks`、`hasFeature`；启动阻塞确认 `MigrationGateDialog.vue`。

## 系列级元数据（第 12 期）
- **存储决策（勿擅改）**：系列级字段**只存本项目 SQLite（`series_meta`）**，绝不写回 EPUB。已知代价（用户接受）：SMB 直读看不到，连服务读全可见。
- **分层**：**本地覆盖 > 本地聚合 > 在线补空**；册数/首发年/出版社/题材优先取**成员书 OPF 聚合**，**系列简介只能来自在线**。`owned_count` 与 `declared_count` 分开显示。
- **在线可靠性低**：只能「系列名检索 + 成员书书名/作者打分（0.7/0.3）」，`MIN_MATCH=0.6` 以下**如实回「未找到」且不写库**；**不为好看放宽阈值或编造简介。**
- **性能红线**：`komga_api.series_dto` 在列表端点被**逐系列**调用 → 里面**不许**调 `series_meta.effective()`；列表走 `effective_light()` + `db.all_series_meta()`。`genres` **保序去重**。
- **`renumber_apply` 不变量**：只改 OPF `calibre:series_index`、**不动文件名**（→ `book_id` 不变）；幂等、可回滚；**必须 `safe_path(name, library_id)`**；写后 `invalidate(lid)` 并**回读 OPF 校验**。

## Komga 兼容服务端（第 15 期）
- **对外是两条通道，别混**：`/opds` = OPDS 目录；`/api/v1/*` = **冒充 Komga 服务端**（客户端把地址填成 NovelForge）。用户说「给别的设备提供 Komga 订阅源」指的是后者；真 Komga **服务端**不支持订阅外部源，那种场景只能 SMB/NFS 挂目录或让客户端直连。
- **可见性只有一处判定**：`_ko_visible_libraries()`（库类型具备 `features` 的 `komga` 能力）。**有声书库天然没有该能力** → 不进 Komga（Komga 无音频模型，硬塞就是打不开的坏条目）。不新增配置项，库类型改了自动跟着变。
- **按库过滤**：`komga_api.grouped(library_id=None)` / `find_series(name, library_id=None)` 默认 `None` = 全库（三个单系列端点零变化）；server 侧 `_ko_books` / `_ko_grouped` / `_ko_library_id_of`。不传库 = 全部**可见**库 = 与之前一致。
- **系列 id 由名字派生，不能改**（客户端已用它存进度 / 收藏）→ 同名系列跨库时只出现在第一本所在库，这是已知取舍，别为此改派生方式。
- **系列级进度**：官方 `POST /api/v1/series/{id}/read-progress` = 已读、`DELETE` = 未读，均 204 无 body；书级官方新口径是 `PATCH`（老客户端 `PUT`，两个都留）。**标已读保留原 locator、只顶 percent**（`mark_series_read`）。

## OPDS 按库暴露（第 14 期）
- **库维度只落在路径上**：`/opds/lib/{lid}/…` 一整套（14 条路由）。OPDS 客户端只会发 URL、订阅的是固定地址，**不能用 `?library=`**；`/opds` 前缀不走 Bearer 中间件（Basic）这条不变。
- **`opds.py` 新增参数一律 keyword-only**：`prefix="/opds"`（还有 `title` / `feed_id` / `libraries`），默认值 = 原行为 → 既有 `/opds*` 输出逐字节不变；⚠️ `acquisition_feed` 的 self/next/prev/up **四组** href 都要跟 prefix 走。
- **可见性两层，真值源一处**：`features` 能力键 `opds`（在 `_COMMON` 里）+ `SETTING_CAPS["opds.expose"]="opds"` + `lib_settings.ITEMS` 的「对 OPDS 暴露」bool；`config.DEFAULTS["opds"]["expose"]=True`。**不可见与不存在一律 404**。
- **单库取书用 `_opds_book_in`（库内查找）**，不用 `library.by_id()`（跨库同名抛 `BookIdConflict`）。
- 根导航**只在可见库 > 1** 时插「按书库」入口（沿用 C2 取法）；`/opds/libraries` 始终可达。
- 前端：`OpdsPage` 拉 `/api/libraries` 列各库地址（>1 才显示）；复制状态存**被复制的地址**而非布尔值（多行列不会一起变「已复制」）。
- 设置页注册表：`p()` 的第一个参数就是 path，**全局必须唯一** —— 同 path 两条会静默覆盖（vue-router 同名路由后者胜 + 侧栏重复 key）。上游对照页用不同 path（如 `koreader-upstream`）且它**不应**在 `SETTINGS_PAGE_COMPONENTS` 里注册组件（否则拿到真组件而非 placeholder）。

## 自动化测试
- `.venv/bin/python -m pytest`（**完全离线**）；dev 依赖在 `requirements-dev.txt`，**不进生产镜像**。当前 **171 passed**（约 2.4s）。
- **两条硬前提**：① **环境变量必须在 import 业务模块之前设置**（`config` 导入即固化目录、`server.py` 导入即 `ensure_dirs()`）；② `db` 的 `_conn`/`_db_path` 是**模块级缓存** → 隔离靠 `db.close()`。
- 碰书库/DB 的用例**必须声明 `isolated`**；接口用 `client` + `auth_headers`。假 EPUB（`b"EPUB"`）只够扫描类用例；**元数据写回 / 系列解析必须用真 EPUB**（`epub_builder.build_epub`）。**不测会外呼的接口**；**`GET /` 会 503**。
- 库 id 由名称派生（中文名 slug 为空 → 回退 `lib-<sha1[:8]>`）；测试库根必须在 `LIBRARY_SOURCE_DIR` 之下。冲突用例注意：`id_conflict_with` 只算**别的**库。
- **C1（求书 / Requests）已决策不做**；上游采集记录（`docs/review/*`）**保留为对照，不要删**。

## 后端踩坑（真实教训）
- **`threading.Lock` 自锁死锁**：持锁后再取同锁 → 进程**静默挂死**。**模块内共用一个锁且有嵌套调用 → 一律 `RLock`。**
- **事件循环线程长持同步锁 → Web 假死**：`mark_processed/mark_recent` 走 `asyncio.to_thread`；watcher 独立 `_scan_lock`。**AI 分章在 async 路径静默失效** → 用 `_run_in_thread()`。
- **`ebooklib.write_epub` 父目录不存在时只 warn 不抛** → 造真 EPUB 前必须先 `mkdir`。
- **HMR 源码 ≠ 服务端产物**：验证前必须 `npm run build && npm run deploy`。
- 其它已修：批量端点必须注册在 `/api/books/{bid}` **之前**；查重长度预筛 `max/min > (2-thr)/thr`；OPDS 走 `trust_env=False`，integrations 公网目标**保留** `trust_env=True`。

## 运行 / 构建 / UI 验证
- **本地测试实例**（已授权直接 py_compile + 重启）：各 `*_DIR` → `/tmp/nf-test/…`，`AUTO_WATCH=false`，auth `admin`/`test1234`，`.venv/bin/python -m uvicorn novelforge.server:app --port 8791`。
- **Docker**：`docker-compose.yml` 真实版拉 ghcr 镜像，端口 **8992**，挂 `./data`；`docker-compose.test.yml` 测试版本地 build + 挂 `./novelforge:/app/novelforge`，端口 **8993**，数据隔离 `./data-test`。**断网无法 `--build`**。
- **UI 验证（playwright）**：装在项目 `.venv`（不进生产依赖），缓存内核传 `executable_path`；直连本机实例时 **`nf_token` 必须用 `context.add_init_script` 注入**（否则首屏 401）；迁移确认弹窗（`div.fixed.inset-0`）会挡点击 → 先 `force=True` 点「暂不迁移」。
- 构建：`cd frontend && npm run type-check && npm run build && npm run deploy`（生产镜像由 Dockerfile 的 `frontend` 阶段自动构建）。

## 各期状态
- 6–7 期前端快赢 + B 类轻后端；8 期元数据在线优先 + 作者页 + ISBN；9 期 CBR + 有声书；10 期多书库；11 期工程护栏（`tests/`，删 C1）；12 期系列级元数据（路线图最后一项已关）；**13 期（已完结）** 每库覆盖 + 跨库同名防护 + 工具页库维度，收尾 commit `f07012e`；**14 期** OPDS 按库暴露（`/opds/lib/{lid}/*` + 每库开关）+ 四处小尾巴；**15 期** Komga 兼容服务端补齐（系列 / 书籍按库过滤、有声书库不进 Komga、CBR 类型、系列级已读 + 书级 PATCH）。
