# 项目长期记忆（novel_dl_convert / NovelForge）

## 项目定位
TXT 小说转 EPUB 工具，面向 NAS / 容器部署；输入（input）与导出（output）目录物理分离。
FastAPI 服务 + CLI；可插拔书源（内置 Gutenberg 公版源 + 数据驱动 JSON 规则源）。
镜像由 GitHub Actions 构建发布到 `ghcr.io/735876214/novel_dl_convert:latest`，NAS 端 `docker compose up -d` 即可。

## 关键约定

- **提交即推送**：任务完成后自动 `git add → commit → push`（中文提交信息，按功能/修复拆分多个 commit）。
- **git 协议常被代理拦截**（`CONNECT tunnel failed 502`），但 `api.github.com` 可达 →
  用 `github-push-via-api` skill（Git Data REST API：blob → tree → commit → PATCH refs）推送。
  注意：远端 tip 要现取；blob 内容必须 LF 归一化（工作区可能是 CRLF）；token 从 `GH_TOKEN` 传入，不写进 remote。
- **本地 git 对象库曾整体丢失**（`.git/objects` 下文件被清空，仅剩空目录），表现为
  `fatal: bad object HEAD` / `unknown revision origin/main`。修复方式：
  `git update-ref -d refs/heads/main` → 删 `.git/index` → `git add -A` → 重新提交；
  网络恢复后 `git fetch origin && git reset --hard origin/main` 与远端对齐。
  `git stash push` 在该状态下会触发 `BUG: diff-lib.c:632` 崩溃，别用。
- **无 Docker CLI**：Dockerfile / 构建脚本的验证手段是查 GitHub Actions
  （`GET /repos/735876214/novel_dl_convert/actions/runs?per_page=1`）。
- **沙箱环境**：Python 进程写系统临时目录（`%TEMP%`）会被杀（退出码 1、无任何输出），
  测试脚本的临时目录必须放在工作区内（如 `_test/_tmp`）；PowerShell 的 `Remove-Item` 也常失败，
  删文件用 Python；**PowerShell 工具不回显 stdout**，命令输出要重定向到文件再读。
- `_test/` 已被 .gitignore 忽略（本地冒烟脚手架，不入库）；`.workbuddy/memory/` 需 `git add -f` 才会入库。

## 功能模块（截至 2026-09-14）

- `core/pipeline.py`：文件分发（txt 转换 / 电子书复制 / 其它跳过）。
- `core/watcher.py` + `core/activity_log.py`：输入目录自动监听（txt→EPUB，非 txt 导出）
  与活动日志（时间 / 文件名 / 操作 / 成败）。轮询制（NAS 网络挂载 inotify 不可靠），
  状态存 `CACHE_DIR/watcher_state.json`，日志落 `LOG_DIR`（默认 `CONFIG_DIR/logs`）。
- `sources/`：书源适配（gutenberg / generic 模板 / rules 数据驱动 / store 用户源 / manager）。
- `static/`：卡片式单页 Web（书源管理 / 搜索下载 / 导出目录 / 本地转换 / 转换日志）。
