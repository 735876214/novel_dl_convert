# 长期记忆（novel_dl_convert / NovelForge）

> **唯一真值源**。2026-09-15 起由 `.codebuddy/memory/` 统一承载：
> 原 `.workbuddy/memory/` 的内容已全部并入本文与同名日记，那个目录只留一个指针文件。
> **不要再往 `.workbuddy/memory/` 写内容**，否则又会分叉。

## 项目
- 定位：**TXT 小说 → EPUB 转换工具**，面向 NAS / 容器部署；`input`（输入）与 `output`（导出）目录**物理分离**。
  FastAPI 服务 + CLI；可插拔书源（内置 Gutenberg 公版源 + 数据驱动 JSON 规则源）。
- 镜像：GitHub Actions 构建发布到 **`ghcr.io/735876214/novel_dl_convert:latest`**，
  NAS 端 `docker compose up -d` 即可；`docker-compose.yml` 拉该镜像，源码烤在镜像里。
- 远程仓库：**实际 remote 是 HTTPS** —— `origin` = `https://github.com/735876214/novel_dl_convert.git`
  （`git@github.com:` 的 SSH 形式并未配置为 remote）。当前分支 `main`。

## 工作约定（用户偏好，务必遵守）
- **提交即推送**：任务完成后主动 `git add → commit → push`；提交信息用**中文**，
  并**按功能/修复拆分成多个 commit**（不要一个巨型 commit 裹一堆无关改动）。
- **视觉层严格照搬 BookOrbit，不允许自行发挥**。用户曾明确**推翻**过「铅字车间 / 油墨套色」等自创方向，不要再提。
- **零外部请求**（NAS 内网部署）：字体走本地自托管文件，图标全用内联 SVG，不引字体/图标 CDN。
- 「延续局部更新」：交互（折叠、筛选、计数变化）优先只改必要的 class / 节点，**不整体重建 DOM**，
  否则会丢输入焦点与展开态。这条是用户逐轮盯出来的。

## 记忆目录（2026-09-15 已统一）
- **`.codebuddy/memory/` 是唯一真值源**（CodeBuddy IDE 使用）。
- `.workbuddy/memory/` 已并入，**只剩一个指针文件**，不再承载内容。
- 忽略规则：`.codebuddy/*` + `!.codebuddy/memory/`
  —— 即 `settings.local.json`、`plans/` 等本机状态不入库，只有 `memory/` 入库。
  （写法要点：否定规则必须配 `/*` 不带尾斜杠，否则无法重新包含子目录。）

## Git 认证（重要）
- 认证方式：**Git Credential Manager（GCM）**，已配置为 global `credential.helper`。
- 已删除 remote URL 内嵌的明文 token，以及 global 的 `url.<token>@github.com/.insteadof` 重写规则。
- **勿再引入** URL 内嵌 token 或 `insteadOf` 明文重写；认证交给 GCM（凭据存系统凭据管理器）。
- 若 GCM 未缓存凭据，首次 push 会触发浏览器/OAuth 或 PAT 登录。

## Git 代理
- 已为 git 配置 `github.com` 作用域代理：`http.https://github.com/.proxy`（内网代理含 Basic 认证），
  用于解决直连 github:443 超时。**仅作用域**（非全局），避免误代理内网/其它 git 主机。
- 代理凭据明文存于 global git config，**勿将全局配置提交/外泄**。
- 2026-09-15 实测：经该代理 `git push origin main` 成功（`e0c4d7d..901e06b`），
  说明链路可用；宿主机对 `github.com` 的 HTTPS 探测也曾返回 200。

## 安全提醒
- 曾存在于 git config 的 GitHub PAT 应视为**已泄露**，建议去 GitHub 撤销并用 GCM 托管新凭据。

## 前端技术栈与视觉规范（2026-09-15 全面重写，**作废 2026-09-14 的旧版**）
- 前端是**顶层 `frontend/` 的 Vue 3 SFC + TypeScript + Vite 8 + Tailwind v4 + Pinia 4 + vue-router 5 工程**。
  **旧的零构建原生三件套已退役删除**（`novelforge/static/{index.html,style.css,app.js}` 已删，
  备份在 `%TEMP%\nf-v1-backup-20260915-002245`，git 亦可恢复）。**不要**再往 `static/` 里加手写页面。
- 构建产物落 **`novelforge/static/v2/`**（**已 gitignore，不入库**），由 FastAPI `StaticFiles` 挂在 `/static`；
  `server.py` 的 `/` 直接服务 `static/v2/index.html`（缺失时返回 503 并提示构建命令）。
- 路由用 **hash 模式**（`createWebHashHistory`）—— FastAPI 没开 SPA 兜底，history 模式刷新会 404。
- **样式一律用 Tailwind v4 工具类 + BookOrbit 语义 token，没有手写消费层**（原 `app.css` 已删）。
  重复类串封装成 `src/components/ui/*` 组件（Card / Button / Badge / PageHead / EmptyState / BookCover /
  Segment / SwatchGrid / Icon / ProgressRing）。圆角用 Tailwind 档位 `rounded-sm/md/lg/xl`
  （已被 bridge.css 桥接到 `--radius-*`）；未桥接 token 用任意值（`bg-[var(--shell-surface)]`、
  `border-[var(--shell-border)]`、`rounded-[var(--shell-radius)]`、`gap-[var(--shell-gap)]` 等）。
- 视觉语言**严格照搬 BookOrbit**（`github.com/bookorbit/bookorbit`，AGPL-3.0 + ADDITIONAL_TERMS + NOTICE 归属）。
  theme 五件在 `frontend/src/assets/theme/`（tokens / accents / radius / **bridge** / cover-effects）。
  **`bridge.css` 是前提**：Tailwind v4 的 `@theme inline` 桥接层，
  **没有它 `bg-card` / `text-muted-foreground` / `rounded-lg` / `shadow-sm` 根本生成不出来**。
- 主题机制：`<html>` 挂 class **`dark` / `accent-<name>` / `radius-<name>`**；
  localStorage 键 **`theme`(默认 system) / `accent`(默认 neutral) / `radius`(默认 default)**，值 JSON 序列化。
  `frontend/index.html` 有内联预置脚本防 FOUC。
  **`main.css` 里必须有 `@custom-variant dark (&:is(.dark *));`** —— Tailwind v4 的 `dark:` 默认跟随
  `prefers-color-scheme`，漏掉这行**所有 `dark:` 工具类都静默失效**。
- 其它 localStorage 键：`nav-collapsed`、`dashboard-widgets`、`dashboard-shelves`。
- 字体本地自托管（10 个 woff2：Inter Variable ×7 + Fraunces Variable ×3），零外部请求；图标全内联 SVG。
  **BookOrbit 默认不是蓝色**：`--tint-h:80 / --tint-c:0.006` 是暖白暖黑中性系，
  `--primary` 亮色 `oklch(0.21 …)`（近黑，主按钮黑底白字）、深色 `oklch(0.91 …)`。蓝只是 65 档 accent 之一。
- 仪表盘照搬 BookOrbit 真实结构：顶部部件行（`widgets/registry.ts` **12 个全登记、3 个已实现**，
  `component: null` 即在自定义面板中置灰标注「待实现」）+ 下方横向书架行 + 右下角自定义面板。
  **部件与书架的演示数据全部是确定性常量，禁止 `Math.random()`**（参考页的热力图就是因此每次重渲染都变）。

## 前端信息架构（用户逐轮拍板，以此为准）
- **侧栏**：品牌区（「书」字方块 + 单行标题「书籍轨道」，无副标题）→ 主导航（无组标题）→ 四个可折叠组。
  主导航＝**仪表盘** / **探索发现** / **任务中心** / **工具**
  （`工具` 原为空占位项，2026-09-15 四个功能页迁移完成后**升级为可折叠组**）。
  「书架」项已删除，但 `shelf` 视图保留，作书库/智能书架/收藏夹条目与「查看全部书库」的共同落地页。
  四组：**浏览**（作者/系列/批注，不显示计数）、**库**（组头 `+`/`⋮` + 筛选框 + 9 个演示书库 + 组尾）、
  **智能书架**、**收藏夹**。整个底部 footer 已删除。
- **顶栏**（顺序固定）：侧栏开关 → 全局搜索框（唯一非图标项，带 ⌘K）→ 通知中心 → 数据统计 →
  任务面板 → 主题 → 设置 → 头像。
- **任务面板**：不是常驻第三列，而是**右侧滑出抽屉**（`position: fixed` + `translateX` + `.drawer-scrim` 遮罩，
  点遮罩或 Esc 关闭，顶栏按钮高亮）。
- **设置入口在顶栏**（侧栏没有设置项）；设置页含「外观」（主题段控 + 65 档点缀色 swatch 网格 8 列 + 圆角段控）
  与「书源」两块。
- 计数胶囊**有值才渲染**：数据里 `count == null` 时不输出胶囊，将来接真实数据会自动出现，不用改代码。

## 后端模块清单
- `novelforge/core/pipeline.py`：文件分发（`.txt` 转换 / 电子书复制 / 其它跳过）。
- `novelforge/core/watcher.py` + `core/activity_log.py`：输入目录自动监听 + 活动日志。
- `novelforge/core/`：预处理 / 分章 / AI 分章 / 网络加固 / 元数据 / EPUB 组装。
- `novelforge/sources/`：gutenberg 公版 / generic 模板 / rules 数据驱动 / store 用户源管理 / manager。
- `novelforge/server.py`：FastAPI，**22 条路由**（`/api/sources*`、`/api/search`、`/api/preview`、
  `/api/download`、`/api/tasks/{tid}`、`/api/files`、`/download/{name}`、`/api/watcher*`、`/api/scan`、
  `/api/logs*`、`/convert`、`/convert-path`、`/content`、`/health`）。
- `novelforge/cli.py`：convert / search / download / update / **watch / scan / logs**。

## 后端设计要点：目录监听 + 活动日志
- `activity_log.py`：字段 = 时间 / 文件名 / 操作（转换·添加·跳过）/ 成功或失败 + 输出名、体积、耗时、
  来源（watcher / upload / api / download）。**双写** `activity.log`（可读文本）与 `activity.jsonl`（结构化供 API）。
  目录默认 `LOG_DIR`（= `CONFIG_DIR/logs`），写不进时降级临时目录。
- `watcher.py`（`FolderWatcher`）：**轮询**而非 inotify —— NAS 的 SMB/NFS 挂载事件不可靠。
  `.txt` → `pipeline.convert_txt` 转 EPUB 落 output（记「转换」）；其它文件 `shutil.copy2` 原样导出（记「添加」）。
- **写入稳定判定**：连续 `stable_rounds` 次（间隔 `settle_seconds`）读到相同 size 才处理，避免拷贝一半就转。
- **状态持久化**：`CACHE_DIR/watcher_state.json` 存 `relpath -> {size, mtime, failed}`；
  指纹一致即跳过（重启不重复转换），文件被覆盖更新才重转。
- **失败重试**：同一文件失败累加，达 `max_retries`(3) 后记一次失败并跳过，避免坏文件反复刷日志。
- `mark_processed()` / `mark_recent()`：供上传 / 下载等内部流程登记，避免监听线程对已生成成品重复转换。
- 配置入口：`config.py` 的 `LOG_DIR`、`watcher` / `logging` 默认项；`AUTO_WATCH` / `WATCH_INTERVAL`
  环境变量可覆盖。`server.py` 用 FastAPI `lifespan` 启停监听线程。

## 后端踩坑（真实教训，值得记住）
- **`threading.Lock` 自锁死锁**：`activity_log.log()` 持 `_lock` 后调 `log_dir()`（内部再取同一把锁）→ 死锁。
  现象极坑：进程**静默挂死**，既无异常也无 traceback，表现为「卡住、超时被杀、退出码 1、无任何输出」。
  已改 `threading.RLock`。**教训：模块内多处共用一个锁且有嵌套调用时，一律用 RLock。**
- **`asyncio` 事件循环线程长持同步锁 → Web 服务假死**：watcher 后台线程持 `state` 锁转换时，
  事件循环线程在 `mark_processed` 处被阻塞，整个服务无响应。修法：
  `mark_processed/mark_recent` 走 `await asyncio.to_thread(...)`；`_log_dispatch` / `convert_path` 改 async；
  watcher 新增独立 `_scan_lock`（串行化扫描轮次），原 `_lock` 只保护短临界区，**转换 I/O 移出锁**。
- **AI 分章在 async 路径静默失效**：`asyncio.run()` 在已有事件循环的线程里会抛 RuntimeError 被 except 吞掉。
  改为调用独立的 `_run_in_thread()`。
- `recent()` 曾有**双重 reverse** bug（从 jsonl 回填时多 reverse 一次，返回顺序变成旧→新）。
  现统一约定：内存与文件都是旧→新，`reversed()` 后给 API。

## 开发环境（2026-09-15 更新：**Node 已装**，作废旧版「本机无 Node」结论）
- **宿主机已装 Node v22.23.2**（ZIP 免安装到 `C:\Users\qingr\nodejs`，已加入用户 PATH），npm 10.9.8。
  容器内 `novelforge-dev` 的 node 也是 **v22.23.2**，两端同版本，本地与生产构建不会漂。
- **必记的坑**：npm 的 `postinstall` 经 `cmd.exe` 调用，要求 PATH 里已有 node —— 每条命令需前置
  `$env:PATH="C:\Users\qingr\nodejs;"+$env:PATH`（新开终端自动生效）；不前置会报
  `'node' is not recognized`（首次装 agent-browser 就是因此失败）。
- **`novelforge-dev` 容器只有裸 node，没有 npm/npx**（Dockerfile 仅 `COPY` 了 node 二进制），
  不要对它执行 npm 命令；要容器化构建请用本地已有的 `node:20-slim`（node v20.20.2 + npm 10.8.2，满足 Vite 8）。
- **agent-browser 已就绪**：v0.27.0 + Chrome 153.0.8010.36（`C:\Users\qingr\.agent-browser\browsers\`），
  已验证可截 `localhost:8993` 与 `localhost:5173`。用法：`open <url>` → `wait --load networkidle` →
  `screenshot [selector] [path]` → `close`，调用前前置 PATH。
  **路径是位置参数，不是 `--path`**（用错报 "Element not found"）；`--full` 截全页；`--annotate` 叠加编号标签；
  同一任务复用同一 daemon，最后再 `close`。
- 网络实测：宿主机对 `nodejs.org` / `github.com` / `registry.npmjs.org` / `registry.npmmirror.com`
  **全部 200、无代理**（旧记录「连不上 github.com:443」已过期；git push 仍可能需代理，见上文）。
  npm 源用 npmmirror（350ms vs npmjs 5117ms）。
- 宿主机**仍无 Python**（`python` 是 WindowsApps 占位符，exit 9009），后端验证仍需 Docker。
- 本机 Docker 可用（Docker Desktop 29.8.0 / Compose v5.5.1）。已在
  `C:\Users\qingr\.docker\daemon.json` 配 `registry-mirrors`
  （`docker.m.daocloud.io` / `docker.1ms.run` / `hub.rat.dev`）——原因：Docker 走 IPv6 访问
  `auth.docker.io` 超时（IPv4 正常）。改 daemon.json 后需 `docker desktop restart`。
- **Dockerfile 有两个可覆盖构建参数**（默认值与 CI 行为保持一致）：
  `INSTALL_BUILD_TOOLS`（0 = 跳过 build-essential，amd64 用）、`PIP_INDEX`（换 PyPI 源）。

## 前端开发与构建命令（重要）
```bash
cd frontend
npm install      # 源见 frontend/.npmrc（registry.npmmirror.com）
npm run dev      # Vite dev server（HMR），/api /health /download 代理到 localhost:8993
npm run build    # 产出 frontend/dist
npm run deploy   # dist → novelforge/static/v2（脚本先删目录再拷）
```
- **dev server 看到的是最新源码，不等于 `dist` 最新** —— 验证生产服务（`localhost:8993`）前
  必须重新 `npm run build && npm run deploy`，否则看到的是上一次构建的旧产物（已踩过一次）。
- 生产镜像由 `Dockerfile` 的 **`frontend` 阶段**自动构建
  （`npm ci` + `npm run build`，产物 `COPY --from=frontend /web/dist/ → /app/novelforge/static/v2/`，
  该 COPY **必须在 `COPY novelforge/` 之后**），无需本地 deploy。
- `.dockerignore` 排除 `frontend/node_modules`、`frontend/dist`、`novelforge/static/v2`。

## 本地开发与 Docker 约定（重要）
- 本地开发用 **`docker-compose.dev.yml`**（不是 `docker-compose.yml`）：本地 build `novelforge:dev`
  + 挂载 `./novelforge:/app/novelforge`，端口 **8993**（8992 留给 `docker-compose.yml`）。
  改 Python → restart 容器；改 requirements/Dockerfile → 重新 `--build`。
  **改前端不再需要 rebuild**：dev 走宿主机 `npm run dev`（HMR，5173）。
- `docker-compose.yml` 拉 ghcr 预构建镜像、源码烤在镜像里，**本地改代码用它不会生效**。
- **行尾必须 LF**：本机 `core.autocrlf=true`，仓库已加 `.gitattributes`
  （`*.sh text eol=lf`、`Dockerfile text eol=lf`、`.dockerignore text eol=lf`）。
  改这几类文件时**不要写成 CRLF**，否则容器内 `sh /app/start.sh` 会报 `set: Illegal option -` 并反复重启。
  （受限于此，`write_to_file` 在 Windows 会写 CRLF，修改这类文件请用
  `[IO.File]::WriteAllText` + `UTF8Encoding $false`。）
- **`python:3.12-slim` 上游基线已从 bookworm 变为 trixie**（Debian 13），与 `node:22-bookworm-slim`
  glibc 前向兼容，COPY node 二进制仍可用。

## 历史坑与旧环境限定（**多数已过期，勿据此判断当前状态**）
以下几条来自早前的 WorkBuddy 沙箱 / 早期环境，**在 2026-09-15 的 CodeBuddy 环境下已不成立**，
保留仅为解释历史提交与旧笔记：
- 「本机无 Docker CLI，验证只能靠 GitHub Actions」—— 现在本地 Docker 可用，已用 dev 容器验证。
- 「本机 Node / Python / 浏览器自动化全无」—— Node 与 agent-browser 现已装好（见上）。
- 「git 推送被代理拦截（`CONNECT tunnel failed 502`），需用 `github-push-via-api` skill」——
  2026-09-15 经作用域代理推送成功；该 skill 仍可作为代理不通时的备用手段。
- 「PowerShell 工具不回显 stdout」—— 那是该沙箱的限制；本地正常，但**多行输出仍可能被截断**，
  稳妥做法是把结果拼成**单行**再 `Write-Output`。
- 「Python 写系统 `%TEMP%` 会被杀、`Remove-Item` 常失败」—— 沙箱限定，勿套用到当前环境。
- 「本地 git 对象库曾整体丢失（`fatal: bad object HEAD`）」—— 修复方式：
  `git update-ref -d refs/heads/main` → 删 `.git/index` → `git add -A` → 重新提交；
  或网络恢复后 `git fetch origin && git reset --hard origin/main`。
  **该状态下 `git stash` 会触发 `BUG: diff-lib.c:632` 崩溃，别用。**
- 「`.gitignore` 里 `.workbuddy/` 写成带尾斜杠会无法重新包含子目录」—— 通用 git 规则：
  否定规则必须配 `/*` 形式。
- 该仓库曾出现「工作区文件已是远端最新内容、但未提交」的情况，提交前先
  `git diff FETCH_HEAD --stat` 判断真实差异，别只看 `git status`。
- 曾有 `docker ps -a` 里的容器被用户自行清理，导致本地 build **必须联网拉基础镜像**。
