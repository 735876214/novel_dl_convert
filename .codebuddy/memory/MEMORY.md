# 长期记忆（novel_dl_convert / NovelForge）

## 项目
- 这是一个 TXT→EPUB 转换工具（NovelForge），FastAPI Web 服务 + 目录监听自动转换。
- 远程仓库：`git@github.com:735876214/novel_dl_convert.git`（HTTPS 形式 `https://github.com/735876214/novel_dl_convert.git`）。

## Git 认证（重要）
- 认证方式：**Git Credential Manager（GCM）**，已配置为 global `credential.helper`。
- 已删除 remote URL 内嵌的明文 token，以及 global 的 `url.<token>@github.com/.insteadof` 重写规则。
- **勿再引入** URL 内嵌 token 或 `insteadOf` 明文重写；认证交给 GCM（凭据存系统凭据管理器）。
- 若 GCM 未缓存凭据，首次 push 会触发浏览器/OAuth 或 PAT 登录。

## Git 代理
- 已为 git 配置 `github.com` 作用域代理：`http.https://github.com/.proxy`（内网代理 192.168.0.120:10086，带 Basic 认证），用于解决本机直连 github:443 超时。
- 仅作用域（非全局），避免误代理内网/其它 git 主机。
- 代理凭据明文存于 global git config，勿将全局配置提交/外泄。

## 安全提醒
- 曾存在于 config 的 GitHub PAT 应视为已泄露，建议去 GitHub 撤销并重新生成（由 GCM 托管新凭据）。
- 本机直连 `github.com:443` 超时，推送经上述代理即可连通（已 `ls-remote` 验证通过）。

## 前端技术栈与视觉规范（2026-09-15 全面重写，**作废 2026-09-14 的旧版**）
- 前端是**顶层 `frontend/` 的 Vue 3 SFC + TypeScript + Vite 8 + Tailwind v4 + Pinia 4 + vue-router 5 工程**。
  **旧的零构建原生三件套已退役删除**（`novelforge/static/{index.html,style.css,app.js}` 已删，
  备份在 `%TEMP%\nf-v1-backup-20260915-002245`，git 亦可恢复）。**不要**再往 `static/` 里加手写页面。
- 构建产物落 **`novelforge/static/v2/`**（**已 gitignore，不入库**），由 FastAPI `StaticFiles` 挂在 `/static`；
  `server.py` 的 `/` 直接服务 `static/v2/index.html`（缺失时 503 并提示构建命令）。
- 路由用 **hash 模式**（`createWebHashHistory`）—— FastAPI 没有 SPA 兜底，history 模式刷新会 404。
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
- 字体本地自托管（10 个 woff2：Inter Variable ×7 + Fraunces Variable ×3），**零外部请求**；图标全内联 SVG。
- 仪表盘照搬 BookOrbit 真实结构：顶部部件行（`widgets/registry.ts` **12 个全登记、3 个已实现**，
  `component: null` 即在自定义面板中置灰标注「待实现」）+ 下方横向书架行 + 右下角自定义面板。
  **部件与书架的演示数据全部是确定性常量，禁止 `Math.random()`**（参考页的热力图就是因此每次重渲染都变）。

## 开发环境（2026-09-15 更新：**Node 已装**，作废旧版「本机无 Node」结论）
- **宿主机已装 Node v22.23.2**（ZIP 免安装到 `C:\Users\qingr\nodejs`，已加入用户 PATH），npm 10.9.8。
  容器内 `novelforge-dev` 的 node 也是 **v22.23.2**，两端同版本，本地与生产构建不会漂。
- **必记的坑**：npm 的 `postinstall` 经 `cmd.exe` 调用，要求 PATH 里已有 node —— 每条命令需前置
  `$env:PATH="C:\Users\qingr\nodejs;"+$env:PATH`（新开终端自动生效）；不前置会报
  `'node' is not recognized`（首次装 agent-browser 就是因此失败）。
- **`novelforge-dev` 容器只有裸 node，没有 npm/npx**（Dockerfile 仅 `COPY` 了 node 二进制），
  不要对它执行 npm 命令；要容器化构建请用本地已有的 `node:20-slim`。
- **agent-browser 已就绪**：v0.27.0 + Chrome 153.0.8010.36（`C:\Users\qingr\.agent-browser\browsers\`），
  已验证可截 `localhost:8993` 与 `localhost:5173`。用法：`open <url>` → `wait --load networkidle` →
  `screenshot [selector] [path]` → `close`，调用前前置 PATH。
  **路径是位置参数，不是 `--path`**（用错报 "Element not found"）；`--full` 截全页；`--annotate` 叠加编号标签；
  同一任务复用同一 daemon，最后再 `close`。
- 网络实测：宿主机对 `nodejs.org` / `github.com` / `registry.npmjs.org` / `registry.npmmirror.com`
  **全部 200、无代理**（旧记录「连不上 github.com:443」已过期；git push 仍可能需代理，见上文）。
- 宿主机**仍无 Python**（`python` 是 WindowsApps 占位符，exit 9009），后端验证仍需 Docker。
- 本机 Docker 可用（Docker Desktop 29.8.0 / Compose v5.5.1）。已在
  `C:\Users\qingr\.docker\daemon.json` 配 `registry-mirrors`
  （`docker.m.daocloud.io` / `docker.1ms.run` / `hub.rat.dev`）——原因：Docker 走 IPv6 访问
  `auth.docker.io` 超时（IPv4 正常）。改 daemon.json 后需 `docker desktop restart`。

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
  改前端 → 刷新浏览器即生效；改 Python → restart 容器；改 requirements/Dockerfile → 重新 `--build`。
- `docker-compose.yml` 拉 ghcr 预构建镜像、源码烤在镜像里，**本地改代码用它不会生效**。
- **行尾必须 LF**：本机 `core.autocrlf=true`，仓库已加 `.gitattributes`（`*.sh text eol=lf`、`Dockerfile text eol=lf`）。
  改这两个文件时**不要写成 CRLF**，否则容器内 `sh /app/start.sh` 会报 `set: Illegal option -` 并反复重启。
  （受限于此，`write_to_file` 在 Windows 会写 CRLF，修改这两类文件请用 `[IO.File]::WriteAllText` + `UTF8Encoding $false`。）
- Dockerfile 有两个可覆盖构建参数（默认值与 CI 行为保持一致）：
  `INSTALL_BUILD_TOOLS`（0 = 跳过 build-essential，amd64 用）、`PIP_INDEX`（换 PyPI 源）。
