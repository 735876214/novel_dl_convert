# 开发方式、命令与回归清单（development）

> 开工前先读 `AGENTS.md`（硬约束 / 三处同步点 / 陷阱）。本文件是**操作手册**：环境、命令、回归清单、调试、发布。

## 1. 环境准备

```bash
# 后端（Python 3.10+）
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt   # dev 含 pytest，不进生产镜像
mkdir -p novelforge/static          # 缺这个目录会在 **import 期**就抛；但别建 static/v2/index.html

# 前端（Node 走 nvm；本机已 nvm use 24.19.0）
cd frontend && npm install          # registry 走 .npmrc 配置
```

- Windows 用 `.venv\Scripts\python.exe`；命令前先 **`$env:NODE_OPTIONS=''`**（IDE 的 safe-delete shim 会拦 Vite 清目录与删除）。
- 不要提交机器相关路径（`.vscode/settings.json` 里指向 `.venv` 的配置属各人本机设置）。

## 2. 常用命令

| 目的 | 命令 |
|---|---|
| 后端全量测试 | `.venv/bin/python -m pytest`（离线；Windows 同左，用 `Scripts\python.exe`） |
| 单模块 | `.venv/bin/python -m pytest tests/test_catalog.py -k 关键字` |
| 前端类型检查 | `cd frontend && npm run type-check` |
| 前端单测 | `npm run test:unit`（= `vitest run`；脚本名**刻意不叫 `test`**） |
| 前端构建 | `npm run build`（只落 `frontend/dist`） |
| **同步产物** | `npm run deploy`（`dist` → `novelforge/static/v2`） |
| 本地起服务 | 见下面「隔离实例」 |
| CLI | `.venv/bin/python -m novelforge convert|search|download|update|watch|scan|logs` |
| 浏览器冒烟 | `playwright-cli open --browser=msedge <url>`（本机无 Chrome，必须 `--browser=msedge`） |

### 隔离实例（本地调试/冒烟，别干扰别人）

```bash
T=$TMP/nf-dev   # 或 /tmp/nf-dev
mkdir -p $T/{input,output,config,cache,data,libraries}
INPUT_DIR=$T/input OUTPUT_DIR=$T/output CONFIG_DIR=$T/config CACHE_DIR=$T/cache \
DATA_DIR=$T/data LIBRARY_SOURCE_DIR=$T/libraries AUTO_WATCH=false \
.venv/bin/python -m uvicorn novelforge.server:app --port 8412
# 健康检查：GET /health（唯一给版本号的端点，白名单仅 /health + /api/auth/login + /api/logout）
# 登录体：{"user":"admin","pin":"changeme"}（**不是** username/password）
```

- ⚠️ 端口别抢：`8993` 常被测试用 compose 占、`8992` 是生产；**别 kill 别人的实例**。
- ⚠️ 多实例共用同一 `CONFIG_DIR` 会共享日志目录 ⇒ 验证日志/合并类行为要换全新目录。
- ⚠️ **改了后端必须重启进程**才生效。

## 3. 代码规范（本项目特有）

- **行尾**：`*.sh` / `Dockerfile` / `.dockerignore` 必须 LF（`.gitattributes` 已钉）；CRLF 会让容器 `sh /app/start.sh` 报 `set: Illegal option -`。
- **导入**：`core/` 内一律 `from .. import config`；`db` 只经 `db._connect()`。
- **提交**：中文 commit、**按能力拆多笔**、**提交即推送**；临时文件写 `$TMP`，不要落仓库根。
- **期号**：动手前 `git log` 确认——可能有并行会话把期号用掉（历史先例：计划写「第 62 期」但已被占用，实际落成第 66 期）。
- 写计划只写四块：需求来源 / 功能范围 / 防回归要点 / 任务清单。

## 4. 回归清单（每期收尾照着过）

- [ ] **后端全量**：`.venv/bin/python -m pytest --junitxml=<tmp>.xml`，解析 junit 得 `tests/failures/errors`
      （⚠️ Windows 下 safe-delete shim 会让会话末退出码非 0，而 junit 全绿 —— **只认 junit**；`pytest.ini` 已含 `-q`，**别再 `-q`**）。
- [ ] **前端四连**：`npm run type-check && npm run test:unit && npm run build && npm run deploy`
      （缺 `build` 会漏掉模块断链；缺 `deploy` 则服务端仍发旧 bundle）。
- [ ] **接口边界**：新增/删除功能要有「接口 404」与参数边界断言（加删功能都要彻底，见 `AGENTS.md` §1）。
- [ ] **三处同步点**：涉及配置分区 / 偏好块 / 设置页 / 库列 / 含 `book_id` 的表 / 书源注册表 → 逐项对照 `AGENTS.md` §2。
- [ ] **契约测试**：`tests/test_remap_tables.py`、`tests/test_prefs_shelf_block.py`、`tests/test_metadata_providers.py`、
      `tests/test_settings_nav_contract.py`、`tests/test_nav_contract.py`、`tests/test_db_concurrency_contract.py` 是否受影响。
- [ ] **后台线程**：新增旁路线程必须进 `tests/conftest.py` 的 `_quiesce_background()` 收尾清单，否则全量后半程可能 segfault。
- [ ] **数据隔离**：碰库用例用 `isolated` 夹具 + `client`/`auth_headers`；环境变量必须在 **import 业务模块之前** 设。
- [ ] **文档**：`docs/roadmap-gaps-remaining.md` 写本期实施记录（最新期在文件末尾）；
      大文件改动后跑 `python tests/check_doc_anchors.py --drift` 并在文档里做「锚点披露」（硬错 0 / 疑似漂移保留，**历史行号不改写**）。
- [ ] **记忆**：`.codebuddy/memory/YYYY-MM-DD.md` 追加当日结论；跨会话的事实进 `MEMORY.md`（铁律）/ `MEMORY-REF.md`（细节）。
- [ ] **工作区**：`git status` 无自有未提交改动；不顺手提交别人的改动。

## 5. 调试技巧（都踩过坑）

- **测量**：计时用 `curl`（`-w "%{time_total} %{size_download}"`）；**别用 PowerShell `Invoke-RestMethod`**（解析大 JSON 会严重虚高，曾把 65 ms 测成 613 ms）。
- **日志**：pytest 全量落文件再读，别用 `grep` 猜；uvicorn 访问日志写 `RedirectStandardError` 指向的文件。
- **测试计数**：一律 `--junitxml` + 脚本解析；**前端用例数不与后端合并**（两套跑法两套前提）。
- **「长期稳定失败」= 产品 bug 症状**：逐层打印中间返回值找根因；e2e 做「改前 FAIL / 改后 PASS」对照。
- **浏览器冒烟**：
  - `playwright-cli open --browser=msedge "<url>?nc=<随机>"`（带 cache-bust，否则看到旧 bundle 误判「改动没生效」）；
  - ⚠️ **注入 `nf_token` 不稳**（首屏会 401 并清掉 token）⇒ **直接走登录表单**：填 `admin/changeme` 点「进入」；
  - 该外壳下 `getByRole` 常匹配不到 ⇒ 用 DOM 文本/DOM 遍历点按钮；`run-code` 传 JS 时**别用 `\"` 转义**（用 JS 单引号）；
  - 该沙箱里 `setTimeout` 可能缺失 ⇒ 竞态类验证改由 Vitest 钉。
- **Redis / PG 相关**：不配即关闭（行为与旧版一致）；测缓存那几条用 `NOVELFORGE_TEST_REDIS_URL`（独立 db）；测 PG 用 `NOVELFORGE_DB=pg NOVELFORGE_PG_DSN=... NOVELFORGE_PG_RESET=1`（**只对测试库**）。

## 6. 发布

- 镜像：`Dockerfile` 多阶段（`builder` 装 venv → `nodejs` 只借 node 二进制 → `frontend` 构建 Vue → `runtime` python-slim）；
  生产镜像**不含** `requirements-dev.txt`。
- 版本号：唯一真值源 `novelforge/server.py` 的 `APP_VERSION`，只由 `GET /health` 下发（**无 `/api/health`**）。
- 镜像发布（CI）与 NAS 部署 / 更新命令见 `README.md` §Web 服务；⚠️ **切勿**新建 `docker-compose.override.yml`
  （Compose 会自动合并并静默改端口 / 禁拉取）。

## 7. 文档维护

| 文档 | 什么时候改 |
|---|---|
| `AGENTS.md` | 硬约束、同步点、常用命令、陷阱发生变化时 |
| `docs/TODO.md` | 开工/收尾（移走已完成、补新发现，**每条带证据**） |
| `docs/DESIGN.md` | 视觉 token / 圆角档 / 字体 / 动效 / 组件范式变化时 |
| `docs/project-overview.md` | 定位、能力面、技术栈、部署形态、规模数字变化时 |
| `docs/architecture.md` | 新增 core 模块、数据流变化、不变量增减时 |
| `docs/user-guide.md` | 用户可见功能/入口/设置页变化时 |
| `docs/development.md`（本文） | 命令、回归清单、调试手法变化时 |
| `docs/component-api.md` | 组件 props/emit、store/lib 公共 API 变化时 |
| `docs/roadmap-gaps-remaining.md` | **每期**追加实施记录（活文档，最新在末尾） |

## 8. 锚点核验工具

`tests/check_doc_anchors.py`（**非 `test_` 前缀，pytest 不收集**）：

```bash
python tests/check_doc_anchors.py --drift      # 找疑似漂移
python tests/check_doc_anchors.py --suggest    # 给建议行号
python tests/check_doc_anchors.py --todo       # 列出待人工确认
python tests/check_doc_anchors.py --file docs/xxx.md
```
方法与四条局限见 `docs/bookorbit/bookorbit-capability-gap.md` §0.4/§0.5。判据是「0 硬错 **且** 人工过完 `--todo`」，
**历史实施记录里的旧行号一律不改写**（改它=篡改历史）。
