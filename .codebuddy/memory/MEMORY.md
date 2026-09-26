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
- ⚠️ **切勿恢复 `docker-compose.override.yml` 这个名字**（Compose 会自动合并 ⇒ NAS 上 `docker compose up -d` 静默变成 8993 + 禁拉取 + 挂不存在的 `./novelforge`），该用途已改名 `docker-compose.offline.yml` 且须显式 `-f`。NAS 部署 = **`docker-compose.yml` 单文件**（配置全写字面量、**不读 `.env`**；`.env.example` 已删），细节见 REF。

## 自动化测试
- 完全离线 `.venv/bin/python -m pytest`；**后端基线（win32）820**（第 54 期）、0 failed/0 err；**前端另计**（`npm run test:unit`=**62**）、不并入。
- ⚠️ `pytest.ini` 已含 `addopts=-q`，**别再加 `-q`**（变 `-qq` 吞汇总行）；计数一律 `--junitxml=…`+脚本解析；跑全量前确认 `novelforge/static` 存在；**落全量日志到文件再读**，别 `grep` 猜。⚠️ 本机 safe-delete shim 会拦 pytest 会话末对 `%TEMP%\pytest-of-*` 的清理 ⇒ `$LASTEXITCODE=1` 而 junit 全绿，**别据此判失败**（清 `NODE_OPTIONS` 也拦不住，只有 junit 权威）；**Remove-Item 传多个文件时一个不存在会整批中止**（先确认存在再删）。
- **「长期稳定失败」是产品 bug 症状**：逐层打印中间返回值找根因；e2e 做改前 FAIL/改后 PASS 对照。
- 环境变量须在 import 业务模块**前**设（`config` 固化目录、`server` 导入即 `ensure_dirs()`）；`db._conn`/`_db_path` 模块级缓存⇒隔离靠 `db.close()`。
- 碰库/DB 用例必须 `isolated`、接口 `client`+`auth_headers`；假 EPUB(`b"EPUB"`)够扫描类，元数据写回/系列解析要真 EPUB(`epub_builder.build_epub`)；⚠️ 隔离夹具**不预建库根目录**，写真 EPUB 前先 `mkdir(parents=True)`（ebooklib 写失败只发 UserWarning、文件静默缺失）；测试库根须在 `LIBRARY_SOURCE_DIR` 下；断言留余地。
- 全量后半程曾 segfault ⇒ `_quiesce_background()` 须在夹具 `db.close()` **之前**收尾；`watcher.wait_pending(5.0)` 非 0 即 `pytest.fail`（干净运行恒 0）；**新增旁路线程必须进收尾清单**（第 54 期先例：`server.wait_embed_refresh`）。
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
- **「文件:行号」收尾必须实测复核**（工具/局限见 REF）：只记真实行号、不记偏移量；判据「0 硬错」**且**人工过完 `--todo`；⚠️ **历史实施记录里的旧行号不改写**（改它=篡改历史）；改了大文件后跑 `tests/check_doc_anchors.py` 并按先例在文档里做「锚点披露」（硬错 0 / 疑似漂移保留）。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值=每库覆写 ?? 全局`，落 `libraries.settings`；真值源 `core/lib_settings.py`+`features.SETTING_CAPS`；接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（细节见 REF）。
- 可见性=能力矩阵（库类型）∩每库开关，判定**只留一处**；「不可见」=「不存在」→404。
- ⚠️ **能力键判隐显轴**：`library.hasFeature(k)` 判「侧栏当前选着的库」，只适合全局导航/设置页；读者侧要判「**这本书**属于哪个库」。
- ⚠️ **新增「可保存的配置分区」=三处同步点**：① `server.EDITABLE` ② `GET /api/config` 硬编码键列表 ③ 前端 `settingsFields.ts` 的 `SECTION_KEYS`；漏任一处都不报错。判「某能力有无页面入口」也照这三处查。
- ⚠️ **偏好块块名清单是前后端两处真值源**：`server.PREFS_BLOCKS` ↔ 前端 `lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS`（连带相关函数）；**新增块必须两端同批改**；契约 `tests/test_prefs_shelf_block.py`。

## 前端
- Vue3 SFC+TS+Vite8+Tailwind v4+Pinia4+vue-router5(hash)；产物 `novelforge/static/v2/`（`/` 服务其 index.html，缺失 503）；**勿往 `novelforge/static/` 加手写页**。
- 演示数据禁 `Math.random()`；**路由 path 全局唯一**；`settingsNav`/router 注册表/侧栏**三处与组件同批改**（设置页由注册表生成路由 ⇒ **删条目即删路由**）；**零外部请求零 CDN**。⚠️ 第 49 期后**设置页共 36 页**（占位页清零）；**「书库管理」在 `/settings/libraries`**。
- ⚠️ **前端收尾必须 `npm run type-check` + `npm run build` + `npm run deploy`**：`vitest` 不校验模块导出完整性（第 44 期曾把两个文件误提交成 0 B，62 个单测全过、只有构建才报断链）；且 `build` 只落 `frontend/dist`，**`deploy` 才同步到 `novelforge/static/v2`**（漏 deploy ⇒ 服务端仍服务旧 bundle，改动看似「没生效」）。
- ⚠️ 设置页 `note` 纯文本插值 ⇒ `**`/反引号/`<strong>` 原样显示（契约钉住）；且**只有 `placeholder` 页会渲染 `note`**，`ready` 页的 note **用户看不到** —— 但它仍是「本项目落地口径」的来源，改能力时应同步（第 50 期实测）。
- 冒烟改偏好**必须走 UI 点击**：直接 `localstorage-set comic-prefs '{…}'` 会被**偏好同步层**拉回默认值（第 51 期实测）。另：阅读器偏好只在组件 setup 读一次，改完需重开阅读器。
- 阅读器翻页路径：`ComicReader` 的 `go()` 是**唯一汇聚点**（键盘 / 点击 / 工具栏都走它）⇒ 挂钩子（如「自动翻下一本」）必须放 `go()`，放 `next()` 会让键盘前进静默失效（第 51 期真缺陷）。
- 图表入口 `lib/charts.ts`、偏好归属、侧栏导航契约、命名避让（`/explore` vs `/browse`）、实体总览六维、窄屏双写法、`ToolsLayout` 用 `onActivated` ⇒ **域细节见 REF**。

## 演播者实体（第 53 期，2026-09-24）
- `books.narrators`（列表列，与 `tags` 同构）+ `narrators` 实体表（`sort_name`/`sort_name_local` 两列分列，镜像 `authors`；**派生/回填只写 `sort_name`**）；扫描期 `core/audio_meta.py` **零依赖**解析音频标签落盘（m4b/mp3/m4a/opus/ogg/flac），解析失败降级空、绝不挡入库；接口 `/api/narrators*` 形态对齐 authors；命名 token `{narrators}` 与 `RENAME_TOKENS` 契约钉死；**刻意差异**：不新增浏览维度、无头像。

## 语义向量与精确位置（第 54 期，2026-09-26）
- **`core/embed.py`**：相似书余弦一路优先语义向量 —— 默认 **LSA**（TF-IDF+SVD，纯 numpy **离线零下载**；词表按 df 封顶并**显式定序**，否则两次重算余弦漂移 ⇒ 推荐列表跳）；可选本地 transformer（`CACHE_DIR/embedding-model` + 自备依赖）；**绝不引远程 embedding API**。`book_embeddings` 表（float32 BLOB + `model_tag`）进 REMAP/ORPHAN；读端 `load_vectors` **只认当前 tag**（旧 tag 不混排）；重算=全量批式（`POST /api/embeddings/recompute` + `/similar` 缺向量·扫描完成两条自愈钩子，单飞闸 `threading.Event`+600s 节流，线程收尾走 `server.wait_embed_refresh` 进 conftest）。
- **`recommend.similar_books(…, vectors=)`**：两书都有向量走语义余弦、缺向量**逐对回落**词袋；「实质重合」门不动 —— 向量管排得好不好、门管该不该出现；出参结构不变。
- **`core/epub_cfi.py` = 位置换算唯一真值源**：CFI 生成/解析 + CFI→XPointer 兼容层；`xml.etree` 解析（坏书一律安全回落空 CFI）；⚠️ **字符偏移 = 渲染正文 textContent 坐标系**（后端 ET text/tail 模拟 DOM childNodes 数步序，前端 `contentRef.textContent.length`，两侧同尺度才能往返）；`progress.cfi` **只由 NF 阅读器写入，其它来源写进度一律清空 cfi**（防「章已变、CFI 挂旧章」）；进度端点 `offset` 进 / `cfi`+`offset` 出（前端不在 JS 里解析 CFI）；恢复换算不了必须回落「章+全书百分比」。
- **KOReader 刻意保守**：`from_nf` 下发仍为**章首 XPointer**（kosync 只认 XPointer，真 CFI 会破坏解析，章内精度由 percentage 兜底）；`to_nf` 仅兼容识别 `epubcfi` 取章序号（crengine 字符坐标不同尺度，不换算不落库）；kobo span / kepub DOM 仍不做；Kobo 同步仍不做（2026-09-17 决策）。
- 依赖：`requirements.txt` 新增 `numpy>=1.26`。文档：module-inventory §2/§4.2/§9 两行改判（embedding 已覆盖；position-converter 已覆盖·子集）+ 第 54 期记录；roadmap 同步。

## 第 55 期铁律（就地建库 / TXT 阅读 / 分章真值源）
- **「新增书库」= 就地弹窗**：全局单实例 `frontend/src/stores/libraryWizard.ts` + App.vue 挂**一份** `<LibraryWizard>`；各入口调 `wizard.show()`（`created()` 负责刷新全局书库实体 + 宿主回调）。⚠️ **禁再在别处挂 LibraryWizard 或另建第二份数据拉取**（z-50 浮层叠两层关不掉；`?new=1` 经 store 仍可用）。「管理」语义入口（书架顶栏 / 侧栏「更多」）仍跳 `/settings/libraries`。
- **分章唯一真值源 = `core/detect.py`**（出版管线 / 书源 / TXT 阅读共用；契约 `tests/test_detect_chapters.py`）。⚠️ 两条现状口径别当 bug 顺手改（会同时改出版成品目录）：① 首个边界前的内容（书名/作者）**被丢弃**；② 正则是**非锚定**的 —— 正文里出现「第 N 章」字样也会被当边界。
- **TXT 阅读 = 派生 EPUB 优先、原生分章兜底**（`core/txtcache.py`）：派生件落 `CACHE_DIR/txt-epub/<book_id>/`（**派生缓存**：不进书库、不落成品目录）；形态由**源文件指纹**锁定（源没变不换路线，防章节号漂移让批注跳错章）；失败写 state.json 标记。⚠️ 派生 EPUB 必须 `epub_builder.build_epub(..., nav=False)`（spine 不含 nav 页 ⇒ 章节 index 0 基，与原生兜底索引空间对齐）；`build_epub` 的 `nav` 参数默认 `True`，改动它前先看全部既有调用方。
- 新增端点/接口形状不变原则：TXT 阅读**前端零改动**（后端把两条路线归一成 `chapters` + `/chapter/{index}` 同一形状）；`BookDetailView.canRead` 放行 TXT（需有章节）。
- 设置页三处同步点、契约测试的「源码字符串断言」：改行为时**同步改断言**并在测试里写清新口径（第 55 期改了 `manageLibs`→`createLib`、`cta.to` 可选两处）。

## 第 56 期铁律（多设备进度提示 / 偏好同步感知）
- **进度同步 = 轮询 + 提示，绝不上 SSE、绝不静默挪阅读位置**：`ReaderView` 用服务端 `updated_at` 当基准（载入读到的 + PUT 回带的 `ownWriteAt`），8s 轮询且「时间戳更新 >1s **且位置确实不同**」才渲染提示条；**只有用户点「跳过去」才 `loadChapter`**（随即写回本机位置避免重复提示）。`hidden` 不轮询；卸载停轮询；提示条不碰 `html`/`contentRef`（不重排正文）。
- **`updated_at` 是公开契约**：`GET/PUT /api/books/{bid}/progress` 都带；⚠️ **没有进度行时不得给**（造 0 当基准会让首次进阅读器就弹提示）。任何写进度的来源（KOReader/Komga/完成标记）都经 `db.set_progress` ⇒ 自动刷新时间戳（语义：也算「别处读过」）。
- **偏好同步感知**：设备行 `last_seen` 就是变更信号（勿另建表/列）；判定**必须走纯函数** `prefsSyncDecision`（noop / apply-remote / conflict，1s 容差）；`conflict`（本机有未推送改动）**只提示不覆盖**（顶栏胶囊 → 设置页显式选）。`boot()` 的启动裁决语义不变（启动那刻 pending⇒本机为准并推）。
- 前端 spec 假时钟约定：伪造计时器时**保留真 `setTimeout`**（只 fake `setInterval`/`clearInterval`/`Date`），否则 `flushPromises()` 自挂。

## 第 57 期铁律（元数据提供商 / 插件市场 / 书源）
- **提供商注册表 = 上游 14 家目录，`implemented` 是诚实标记**：`core/metasources.SOURCES` 列全 14 家（四组），真正能抓的只有 `openlibrary`/`googlebooks`；⚠️ **契约 `IMPLEMENTED == _FETCHERS.keys()`**（`tests/test_metadata_providers.py`）—— 加一家实现必须同时改注册表 `implemented=True`、`IMPLEMENTED`、`_FETCHERS` 三处。**未实现的家绝不给开关**（能点但没用 = 假交互），前端渲染 `—` + 「未实现 · 可经插件市场安装」。
- **未实现的源不发外呼**：`/api/metadata/probe` 如实回报「未实现」（spy 测试断言零外呼）；`metafetch.plan`/`online_candidate` 只选 `is_implemented()` 的源（配置里混入未实现 id 不白跑、不炸）。
- **启用状态的真值源仍是 `metadata_fetch.sources`**（在列表里 = 启用，顺序 = 优先级）；`GET /api/metadata/providers` 只做聚合，**不新开一份状态**；设置页 `已启用 N/总数` 读配置草稿（未保存即时可见）。
- 出网口径（本期修订）：**默认零外部请求；仅插件市场与已启用的元数据源按用户显式配置出网**，其余（前端 CDN/字体/更新检查）仍严格零外部。插件包必须是**声明式规则**（复用 `sources/rules.py` schema），**不执行远端任意代码**。
- zlibrary 专用下载**不做**（盗版分发平台）；书源获取走通用声明式规则 + 投递目录。
