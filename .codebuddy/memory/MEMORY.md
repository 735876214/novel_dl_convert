# 长期记忆（novel_dl_convert / NovelForge）

> **唯一真值源**：`.codebuddy/memory/`。`.workbuddy/memory/` 已并入，只剩指针文件，**不要再往那里写**。
> 本文 2026-09-15、**2026-09-18** 各做过一次压缩整理（去重、合并过期结论、剔除已失效的环境细节）；过程细节看同日期的日记。
> **提到「bookorbit」默认指本项目**（基于 bookorbit 二次开发的 novel_dl_convert），只有对比上游时才需区分。

## 项目
- 定位：**TXT 小说 → EPUB 转换工具**，面向 NAS / 容器部署；`input`（输入）与 `output`（导出）**物理分离**。
  FastAPI 服务 + CLI；可插拔书源（内置 Gutenberg 公版源 + 数据驱动 JSON 规则源）。
- 镜像：GitHub Actions 构建发布 **`ghcr.io/735876214/novel_dl_convert:latest`**，NAS 端 `docker compose up -d`。
- remote：`origin` = `https://github.com/735876214/novel_dl_convert.git`（HTTPS）。分支 `main`。

## 工作约定（用户偏好）
- **提交即推送**：任务完成后主动 `git add → commit → push`；提交信息用中文，**按功能拆成多个 commit**。
- **视觉层严格照搬 BookOrbit，不允许自行发挥**（自创方向已被否决）。
- **零外部请求**（NAS 内网）：字体本地自托管、图标全内联 SVG、作者头像本地缓存，**不引 CDN / 外链**。
- **延续局部更新**：交互（折叠 / 筛选 / 计数）只改必要 class 与节点，**不整体重建 DOM**。
- **⚠️ 本工作区可能同时有另一个 AI 会话在跑**（曾误删临时目录并改写同一份 `MEMORY.md`）。
  故：改文件前先 `git status`，不属于自己的改动不要回退；临时文件别放仓库（用 `/tmp`）；写记忆一律**追加**。
- `_test/` 已不存在（被并行会话误删，不可恢复）。

## 记忆目录 / 不该入库
- `.codebuddy/memory/` = 唯一真值源；`MEMORY.md`（长期）+ `YYYY-MM-DD.md`（日记，追加）。
- `.gitignore`：`.codebuddy/*` + `!.codebuddy/memory/`（否定规则必须配 `/*`，**不带尾斜杠**才能重新包含子目录）。
- **`data/`（= `DATA_DIR`）**：运行时 SQLite（阅读进度/批注/评分/收藏/偏好 + 外部服务 Token + KOReader 密钥哈希）
  → 已 gitignore（连同 `*.db`）；查过 `git log --all -- data/novelforge.db` 为空，从未入库。**`.playwright-cli/`** 同样已忽略。
- 忽略自检：`git check-ignore -v <path>`。

## Git 认证 / 提交分组
- 认证走 **GCM**；URL 内嵌 token 与 `insteadof` 明文重写已清除，**勿再引入**。历史 PAT 视为已泄露。
- `github.com` 作用域代理是 **Windows 环境**的配置；**macOS 工作区实测无代理、`GIT_TERMINAL_PROMPT=0 git push origin main` 直连可推**。
  推送失败先查认证/网络，别先改 git config。
- **提交分组**：按「能力」而非「文件类型」拆，一条线从底层到上层：
  `feat(core)` → 各独立能力（`feat(opds)` / `feat(komga)` / `feat(koreader)` / `feat(integrations)` …）
  → `feat(server)` 路由与配置接线 → `feat(frontend)` → `chore(build)` → `docs`（含工作记忆）。
  `server.py` / `config.py` 被多期共同改动，只能合成一个「接线」commit。
- 提交信息用 `-m 标题 -m 正文`；超长用 `git commit -F <文件>`（放 `.git/` 下）。

## 前端技术栈 / 视觉规范
- `frontend/` = **Vue 3 SFC + TS + Vite 8 + Tailwind v4 + Pinia 4 + vue-router 5**。旧的零构建三件套已退役，
  **不要**再往 `novelforge/static/` 加手写页面。
- 构建产物落 `novelforge/static/v2/`（gitignore），FastAPI `StaticFiles` 挂 `/static`；`/` 服务 `static/v2/index.html`，缺失 503。
- 路由用 **hash 模式**（`createWebHashHistory`，后端无 SPA 兜底）。
- 样式**全部** Tailwind v4 工具类 + BookOrbit 语义 token，无手写消费层；重复类串封装为 `components/ui/*`
  （Card / Button / Badge / PageHead / EmptyState / BookCover / Segment / SwatchGrid / Icon / ProgressRing）。
- **`bridge.css` 是前提**（`@theme inline` 桥接层，缺它 `bg-card` / `text-muted-foreground` / `rounded-lg` 生成不出来）。
  主题五件在 `frontend/src/assets/theme/`（tokens / accents / radius / bridge / cover-effects）。
- **`main.css` 必须有 `@custom-variant dark (&:is(.dark *));`** —— 否则 `dark:` 全部静默失效。
- 主题：`<html>` 挂 `dark` / `accent-<name>` / `radius-<name>`；localStorage 键 `theme` / `accent` / `radius`（JSON 序列化），
  另有 `nav-collapsed` / `dashboard-widgets` / `dashboard-shelves`；`index.html` 有防 FOUC 内联脚本。
- BookOrbit **默认不是蓝色**：`--tint-h:80 / --tint-c:0.006` 暖白暖黑中性系，`--primary` 亮色近黑；蓝只是 65 档 accent 之一。
- 仪表盘 = 顶部部件行（`widgets/registry.ts` 12 个全登记 / 3 个已实现，`component: null` 置灰「待实现」）+ 书架行 + 自定义面板。
  **演示数据全为确定性常量，禁止 `Math.random()`**；环形进度单一真值源（JS 写 `--deg`，CSS 只消费）。

## 前端信息架构（用户逐轮拍板）
- **侧栏**：品牌区（「书」字方块 +「书籍轨道」）→ 主导航 → 四个可折叠组，无 footer。
  主导航＝仪表盘 / 探索发现 / 任务中心 / **工具**，四者**同级并列**（「工具」不自成一块，无组标题/分隔线）。
  四组：浏览 / 库 / 智能书架 / 收藏夹。「书架」项已删，`shelf` 视图保留作共同落地页。
- **顶栏**（顺序固定）：侧栏开关 → 全局搜索（带 ⌘K）→ 通知中心 → 数据统计 → 任务面板 → 主题 → 设置 → 头像。
- **任务面板**是右侧滑出抽屉（`fixed` + `translateX` + `.drawer-scrim`，点遮罩/Esc 关闭），非常驻第三列。
- **设置页左列替换（2026-09-18）**：进 `/settings` 任意子路径时，`App.vue` 左列由 `AppSidebar` 整体替换为
  `SettingsSidebar`（复用卡片样式 + 顶部「返回主界面」`router.push('/')` + `SETTINGS_GROUPS` 分组导航）；
  `SettingsLayout.vue` 只留页头 + 面包屑 + `RouterView`。
- 计数胶囊**有值才渲染**（`count == null` 不输出）。

## 工具页（单页 9 标签）
- 形态：`views/tools/ToolsLayout.vue` = `/tools` 外壳，只有「标签栏 + 嵌套 `<RouterView>` + `KeepAlive :max="8"`」，
  **无卡片外框与内边距**（`App.vue` 主区已是卡片）。标签栏 `h-11` 横向下划线，`sticky top-0` + 负 `m` 抵消 main 内边距。
- 9 标签（顺序固定）：**书库管理** / 实体管理 / 批量重命名 / 重复书籍 / 缺失资源 → 书源管理 / 导出目录 / 本地转换 / 转换日志。
  其中「书源管理 / 本地转换 / OPDS 订阅」**按当前库能力裁剪**（第 10 期）。
  子路由 `name` 沿用 BookOrbit（`tools-entity-manager` 等），`/tools` 重定向到第一个。**不做权限门控**。
- **状态保持是硬要求**（切标签不重置）：子页用 `onActivated`（KeepAlive 下也覆盖首次挂载，**别再挂 `onMounted`**）；
  **不要在 `onActivated` 里重置用户输入/勾选/预览**；需重拉的页面保留已选项。
- **会改磁盘的工具一律「先预览、再应用」**；`apply` 只接受前端回传的**具体条目**；**删除即移入回收目录**
  （`CACHE_DIR/recycle`，时间戳前缀、重名加序号，**永不 `unlink`**）；目标名冲突前端置灰禁提交；每次改动写活动日志。

## 后端模块
- `core/pipeline.py`：文件分发（`.txt` 转换 / 电子书复制 / 其它跳过）。
- **`core/library.py`**（只读数据源）：**多书库**（第 10 期）——按 `libraries` 表逐库扫描并合并，
  解析元数据（EPUB 真解 zip 读 OPF）→ 聚合书目 / 作者 / 系列 / 重复 / 缺失。
  **进程内短期缓存按库分桶**（TTL 5s + 目录指纹），写操作后 `invalidate(library_id)`。
  `probe_epub()` 全程容错（失败折算 `unparsable` 不抛）。
  `books()` 的 `BookCard` 含 `id`(= `_book_id(name)`，**basename 派生**)、`library_id`/`library_type`、`mtime`、`c1,c2` 等。
  **`name` 始终是「相对所属库根」的路径** —— 这是协议层不用改的关键。
- **`core/fileops.py`**（写操作）：`safe_path(name, library_id)`（拒绝分隔符 / `..` / 绝对路径；父目录必须**恰好**是**该书所属库根**）、
  `output_dir(library_id)`、`_lib_of(name, item)`（前端回传 `library_id` 优先，否则按名字反查）、
  `plan_*` 预览、`apply_rename()`、`recycle_items()`；`METADATA_FIELDS` 白名单、`patch_epub_meta()`、`rewrite_epub()`、
  `patch_opf_meta()`、`cover_paths()`、`set_epub_cover()`。**只用 `Path.rename` / `shutil.move`，从不 `unlink`。**
  ⚠️ **不要再写 `config.OUTPUT_DIR / b["name"]`**（它只是默认库的根）——按书取路径一律 `library.root_of(b) / b["name"]`。
- `sources/`：gutenberg / generic / rules 数据驱动 / store / manager。
- `server.py`：FastAPI，业务逻辑都在 `core/`，server 只做校验与胶水。`cli.py`：convert / search / download / update / watch / scan / logs。
- `activity_log.py` 操作类型含 `重命名`（`ACTION_RENAME`）/ `清理`（`ACTION_RECYCLE`）/ `ACTION_FONT` / `ACTION_METADATA` 等，与既有同构。

## 目录监听 + 活动日志
- `activity_log.py`：**双写** `activity.log`（文本）+ `activity.jsonl`（结构化供 API）；目录默认 `LOG_DIR`，写不进降级临时目录。
  **顺序约定：内存与文件都存旧→新，`reversed()` 后给 API。**
- `watcher.py`（`FolderWatcher`）：**轮询**而非 inotify（NAS 的 SMB/NFS 事件不可靠）。写入稳定判定（连续 `stable_rounds` 次同 size）；
  状态持久化 `CACHE_DIR/watcher_state.json`；失败累计 `max_retries`(3) 后跳过；`mark_processed/mark_recent` 供上传/下载登记。
  配置：`config.py` 的 `LOG_DIR` / `watcher` / `logging`；`AUTO_WATCH` / `WATCH_INTERVAL` 可覆盖。

## 元数据：在线优先分层（第 8 期，2026-09-18）
- **原则**：元数据**优先在线**；在线不对则用**本地（用户编辑）**；**可编辑**。
- **分层优先级**：`meta_override`（用户编辑，受保护） > `meta_online`（在线抓取值） > `opf`（EPUB 文件原值）。
- **表（`core/db.py`）**：
  - `meta_override(book_id, field, value, orig, updated_at)`：`orig` = **首次覆盖前的 OPF 原值**（老库有 `ALTER TABLE … ADD COLUMN orig` 迁移）。
  - `meta_online(book_id, field, value, source, fetched_at)`：仅供「恢复在线」回退。
  - `authors(name PK, bio, bio_local, photo_path, photo_source, photo_local_path, fetched_at)`：在线 / 本地覆盖**分列**。
    写覆盖用 **upsert**（作者从没抓取过也要能落库 —— 踩过 `UPDATE` 静默失败）。
- **`core/metastore.py`**：`effective(book)` / `state(book)` 做分层解析。**只服务详情/编辑接口，`library.books()` 热路径不动**（控制爆炸半径）。
- **`core/metafetch.py`**：`DEFAULT_POLICY` = **`overwrite`**（`config.py` 默认字段策略同步翻转，仍可逐字段 `fill_only`/`skip`）；
  `plan()` 一次性 `db.all_overrides()` 并**跳过用户改过的字段**；`apply()` 把写回的在线值记入 `meta_online`；
  `online_candidate()` 纯查询（编辑器在线建议用）；`auto_fetch()` 语义同步。
- **`core/authors.py`（D1/D2）**：OpenLibrary 作者检索（`/search/authors.json` → `/authors/{key}.json`）取传记 + 头像 `photos[0]`；
  头像下载到 **`CACHE_DIR/authors/`**（零外链）；归一化名相似度 **<0.5 视为不同人**（宁可放弃不给错配）；全程容错不抛。
- **`core/metasources.py`（D4）**：抽出 `_ol_entry/_gb_entry`；新增 **ISBN 精确匹配** `search_by_isbn()`（命中即 `score=1.0`、`exact_isbn=True`）；
  `metafetch.plan` 与 `online_candidate` **优先 ISBN 命中**，否则回退书名 + 作者检索。
- **`server.py` 接口**：`GET/POST /api/books/{bid}/metadata`（`fields` 生效值 + `meta` 明细；POST 只对**与 OPF 不同**的字段记 override 带 `orig`）；
  `GET …/metadata/online`（实时在线建议）、`POST …/metadata/revert`（撤覆盖；有在线值写回在线值，无则还原 `orig`）；
  `GET /api/authors`（含 `has_photo` / `added_ts` = 名下最早一本书 mtime）、`GET /api/authors/{name}`（含 bio/覆盖标记/photo_source/fetched_at/added_ts）、
  `GET /{name}/photo`（分发，无图 404）、`POST /{name}/bio`、`POST|DELETE /{name}/photo`、`POST /{name}/fetch`、`POST /api/authors/fetch-all`。
  **头像端点已加入 `_MEDIA_TOKEN_PATHS`**（`<img src>` 只能靠 `?token=`）。
- 前端：`MetadataEditor.vue`（已本地修改徽标 + 逐字段/整体「恢复在线」+ 在线值提示）；`AuthorsView`（有头像显示头像，否则书封占位 +「本周新增」+「新」徽标）；
  `AuthorDetailView`（资料卡：抓取在线资料 / 编辑传记 / 上传头像 / 恢复在线）；`MetadataPage` 作者区块做实（启用 / 抓传记 / 抓头像 / 立即抓取全部作者）。

## 多书库（第 10 期 D8，2026-09-18）
- **四项已确认的结构决策**（改前需重新确认）：① `/api/libraries` = **库实体**，格式分面改址 `/api/library-facets`，
  侧栏「库」组只列真实书库（分面不再占侧栏）；② **库根不设默认、逐库选**（就地引用 / 独立存储），
  库里只存**相对的** `source_subdir`（挂载点换了绝对路径会失效）；③ **迁移首次需一次确认**（启动出预览 + 落 manifest，
  阻塞等确认；「暂不迁移」记 `app_state`，设置可勾自动执行）；④ 保留**「全部书库」为默认不裁剪**。
- **模型**：库是**数据**（`libraries` 表），不是配置常量；库表为空时 `library.ensure_default_library()` 落一条
  「默认库 = `OUTPUT_DIR`」（**启动必须调用** —— 漏掉会让书目为空 → 孤儿判定真删进度/批注）。
  列语义：`root_path` = **实际库根**（扫描/落盘唯一根，两模式一致）；`storage_path` 预留；`source_subdir` = 相对来源子目录名。
  关键类型：`ebook` / `comic` / `audiobook` / `mixed`；模式：`inplace` / `import`。
- **`core/migrate.py`**：按格式迁移；**只挪库不改名**（`name` 是库内相对路径 → `book_id` 不变 → 进度/批注不断链）；
  manifest 先行（pending→done/failed）→ 幂等 + 可回滚；同名**拒绝覆盖**给建议名；`batch_id` 由条目集合确定性派生（重复 plan 复用）。
- **`core/library_rules.py`**：入库归库优先级 **来源子目录名 > 格式 > 关键词**；都不可靠 → `None` → 回退默认库；
  `target_root()` 是摄入侧取目标目录的唯一入口（watcher / 上传 / convert-path / 书源下载 / OPDS 下载五处共用）。
- **`core/features.py`**：库类型 → 能力矩阵（真值源，只登记**有区分度**的能力）。前端自己声明「哪项菜单需要哪个能力」：
  `AppSidebar` 的 `ITEM_FEATURE`、`ToolsLayout` 的 section `feature`、`settingsNav` 的 `PAGE_FEATURE`、`dashboard.ts` 的 `WIDGET_FEATURE`。
  未选库（全部书库）= 全部能力 = **不裁剪**。
- **安全边界**：库根**只允许**落在 `LIBRARY_SOURCE_DIR` / `OUTPUT_DIR` / `DATA_DIR` 之内 —— 库根就是 `safe_path` 的边界。
- **`book_id` 仍由 basename 派生、不做数据迁移**：跨库同名由迁移与入库的冲突检测拦住（`library.by_id` 命中多库时显式报错）。
- 前端：`stores/library.ts` 的 `currentLibraryId`（localStorage `nf_current_library`，空 = 全部书库）、`scopedBooks`、`hasFeature`；
  书库页相关筛选（smart/facet/tag/continueReading/scopeCounts/allTags）都按**当前库**走。工具页新增「书库管理」
  （`views/tools/LibrariesView.vue`），启动阻塞确认在 `components/MigrationGateDialog.vue`（挂在 `App.vue`）。

## 后端踩坑（真实教训）
- **`threading.Lock` 自锁死锁**：`log()` 持锁后调 `log_dir()`（再取同锁）→ 进程**静默挂死**（无异常无 traceback）。
  **规律：模块内共用一个锁且有嵌套调用时，一律用 RLock。**
- **事件循环线程长持同步锁 → Web 服务假死**：watcher 后台线程持锁转换时阻塞事件循环。修法：`mark_processed/mark_recent` 走
  `asyncio.to_thread`；`_log_dispatch`/`convert_path` 改 async；watcher 独立 `_scan_lock` 串行化扫描，**转换 I/O 移出锁**。
- **AI 分章在 async 路径静默失效**：`asyncio.run()` 在已有事件循环的线程里抛 RuntimeError 被 except 吞掉 → 改 `_run_in_thread()`。
- `activity_log.recent()` 曾有**双重 reverse** bug，已修。

## 运行环境（本机 macOS 工作区）
- **Python 需 3.10+**（代码用 PEP 604，如 `dict | None`）；系统 `python3` 3.9.6 **不可用**。
  可用：`/Users/stromboid/.local/bin/python3.12`（uv 托管）；项目内 **`.venv`**（gitignore）已建，依赖 `.venv/bin/pip install -r requirements.txt`。
- **Node**：`/Users/stromboid/.workbuddy/binaries/node/versions/20.18.0/bin`（node v20.18，构建用）。
- **本地测试实例**：`OUTPUT_DIR/INPUT_DIR/CONFIG_DIR/CACHE_DIR/LOG_DIR/DATA_DIR` 指向 `/tmp/nf-test/…`，
  `AUTO_WATCH=false`，`AUTH_USER=admin` / `AUTH_PIN=test1234` / `AUTH_SECRET=testsecret`，
  `.venv/bin/python -m uvicorn novelforge.server:app --port 8791`。**已获授权直接 py_compile + 重启（无需每次确认）。**
  ⚠️ **8993 是用户的 Docker 容器**（`docker-compose.test.yml`），**不要去动**。重启前记得 `mkdir -p /tmp/nf-test/{input,output,config,cache,logs,data}`。
- `core/db.py` / `core/auth.py` 必须用 `from .. import config`；直接 `import config` 会被同名命名空间包劫持。
- `AUTH_SECRET` 生产必须改。`DATA_DIR` 默认 `CONFIG_DIR/data`。

## 前端构建命令
```bash
# macOS：先加 node 到 PATH
export PATH="/Users/stromboid/.workbuddy/binaries/node/versions/20.18.0/bin:$PATH"
cd frontend
npm install        # 源见 frontend/.npmrc
npm run dev        # Vite dev server（HMR），/api 等代理到 localhost:8993
npm run type-check # vue-tsc --build
npm run build      # 产出 frontend/dist
npm run deploy     # dist → novelforge/static/v2（先删目录再拷）
```
- **HMR 看到的最新源码 ≠ 服务端产物**：验证前必须 `build && deploy` 两步都做，否则界面是旧的（踩过）。
- 生产镜像由 `Dockerfile` 的 `frontend` 阶段自动构建（`npm ci` + `npm run build` → `static/v2`），无需本地 deploy。
- `.dockerignore` 排除 `frontend/node_modules`、`frontend/dist`、`novelforge/static/v2`。

## Docker / 本地开发约定
- 两个 compose（2026-09-18 收敛，删了 dev/local）：
  - **真实版 `docker-compose.yml`**：拉 ghcr 预构建镜像、源码烤在镜像里（**改代码不生效**）；端口 **8992**，挂 `./data`。
  - **测试版 `docker-compose.test.yml`**：本地 build `novelforge:test` + 挂 `./novelforge:/app/novelforge`；端口 **8993**；
    数据隔离到 `./data-test`（`DATA_DIR=/app/data`，gitignore 已加 `/data-test/`）。`docker compose -f docker-compose.test.yml up -d --build`。
- 改 Python → restart 测试容器；改 requirements/Dockerfile → 重新 `--build`；前端走宿主机 `npm run dev`。
- **行尾必须 LF**：`core.autocrlf=true`，`.gitattributes` 已把 `*.sh`/`Dockerfile`/`.dockerignore` 锁 `eol=lf`；
  CRLF 会让容器 `sh /app/start.sh` 报 `set: Illegal option -` 并反复重启。
- `docker-compose.yml` 自带 `pull_policy: always`；离线时用 `docker-compose.override.yml`（已存在）关掉。

## 通用 git 教训（跨环境有效）
- 提交信息过长时，`git commit -m` 的超长单行命令可能**整体失败（exit 255、无输出）** → 改用 `git commit -F <文件>`（放 `.git/` 下）。
- `.gitignore` 里目录写成带尾斜杠会无法重新包含子目录 —— 通用 git 规则（否定规则用 `/*` 不带走尾斜杠）。
- 工作区「文件已是远端最新却显示未提交」时，先 `git diff FETCH_HEAD --stat` 判断真实差异，别只看 `git status`。
