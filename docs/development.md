# 开发方式、命令与回归清单（development）

> 开工前先读 `AGENTS.md`（硬约束 / 三处同步点 / 陷阱）。本文件是**操作手册**：环境、命令、回归清单、调试、发布。

## 1. 环境准备

```bash
# 后端（Python 3.10+）
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt   # dev 含 pytest，不进生产镜像
mkdir -p novelforge/static          # 缺这个目录会在 **import 期**就抛；但别建 static/v2/index.html

# 前端（Node 走 nvm，24.x）
cd frontend && npm install          # registry 走 .npmrc 配置；本仓**只用 npm**（只有 package-lock.json，别跑 pnpm / yarn）
```

- ⚠️ **本机（Windows）专属**：`.venv\Scripts\python.exe`、命令前 `$env:NODE_OPTIONS=''`（IDE 的 safe-delete shim 会拦 Vite 清目录与删除）等
  —— 一律见 `docs/development-windows.md`（Linux / 容器忽略该文件）。
- 不要提交机器相关路径：`.vscode/settings.json` 是**本机配置**（第 117 期已从仓库移除、并在 `.gitignore` 里钉住），
  要指向 `.venv` 的配置放本机 **User 设置**里。

## 2. 常用命令

| 目的 | 命令 |
|---|---|
| **后端全量测试**（首选） | `bash scripts/test.sh`（自动探测解释器、清 proxy / `NODE_OPTIONS`、跑完打印 junit 摘要与路径） |
| 单模块 / 传参 | `bash scripts/test.sh tests/test_catalog.py -k 关键字`（参数原样透传给 pytest） |
| 后端（等价手写） | `.venv/bin/python -m pytest`（离线；Windows 用 `Scripts\python.exe`） |
| 单模块 | `.venv/bin/python -m pytest tests/test_catalog.py -k 关键字` |
| **前端四连**（首选） | `bash scripts/frontend-verify.sh`（= `type-check && test:unit && build && deploy`，缺一即退非 0） |
| 前端类型检查 | `cd frontend && npm run type-check` |
| 前端单测 | `npm run test:unit`（= `vitest run`；脚本名**刻意不叫 `test`**） |
| 前端构建 | `npm run build`（只落 `frontend/dist`） |
| **同步产物** | `npm run deploy`（`dist` → `novelforge/static/v2`） |
| **本地起服务**（首选） | `bash scripts/dev-instance.sh [端口]`（默认 8412；见下面「隔离实例」） |
| CLI | `.venv/bin/python -m novelforge convert|search|download|update|watch|scan|logs` |
| 浏览器冒烟 | `playwright-cli open --browser=msedge <url>` —— **本机专属用法**见 `docs/development-windows.md` §4 |

### 隔离实例（本地调试/冒烟，别干扰别人）

一键：`bash scripts/dev-instance.sh 8412`（每次建全新目录、`AUTO_WATCH=false`）。等价手写版：

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
- **shell 变量**：`$VAR` 后面紧跟**中文标点 / 全角字符**时必须写 `${VAR}` —— macOS 自带的 bash **3.2** 在默认 locale 下
  会把那个多字节字符吞进**变量名**（`"$PY）"` 找的是名为 `PY）` 的变量，`set -u` 直接 `unbound variable`，
  脚本一行不跑还退出 1）。`tests/test_scripts_contract.py` 钉着这一类（含 `bash -n` 语法与 LF 行尾）。
- **脚本输出别接管道**：`bash scripts/test.sh | tail` 的退出码是 `tail` 的 —— 全红也能看到 `exit 0`。要截取输出用
  `> out.log 2>&1; echo $?`。
- **导入**：`core/` 内一律 `from .. import config`；`db` 只经 `db._connect()`。
- **提交**：中文 commit、**按能力拆多笔**、**提交即推送**；临时文件写 `$TMP`，不要落仓库根。
- **期号**：动手前 `git log` 确认——可能有并行会话把期号用掉（历史先例：计划写「第 62 期」但已被占用，实际落成第 66 期）。
- 写计划只写四块：需求来源 / 功能范围 / 防回归要点 / 任务清单。

## 4. 回归清单（每期收尾照着过）

- [ ] **后端全量**：`bash scripts/test.sh`（自动落 junit 并打印摘要，失败退非 0）
      （CI 的 `Tests` workflow 在 push 到 `main` / PR 时跑**同一条命令**，见 `.github/workflows/tests.yml` ——
      「代码假设了 Windows」这类缺陷只有换平台跑才会露头）
      （⚠️ Windows 下 safe-delete shim 会让会话末退出码非 0，而 junit 全绿 —— **只认 junit**；`pytest.ini` 已含 `-q`，**别再 `-q`**）。
- [ ] **前端四连**：`bash scripts/frontend-verify.sh`
      （缺 `build` 会漏掉模块断链；缺 `deploy` 则服务端仍发旧 bundle）。
- [ ] **接口边界**：新增/删除功能要有「接口 404」与参数边界断言（加删功能都要彻底，见 `AGENTS.md` §1）。
- [ ] **三处同步点**：涉及配置分区 / 偏好块 / 设置页 / 库列 / 含 `book_id` 的表 / 书源注册表 → 逐项对照 `AGENTS.md` §2。
- [ ] **契约测试**：`tests/test_remap_tables.py`、`tests/test_prefs_shelf_block.py`、`tests/test_metadata_providers.py`、
      `tests/test_settings_nav_contract.py`、`tests/test_nav_contract.py`、`tests/test_db_concurrency_contract.py` 是否受影响。
      书源相关的另有：`tests/test_sources_intake.py`（静默 200 回归钉）、`tests/test_format_adapters.py`、
      `tests/test_convert_honesty.py`（假可用钉）、`tests/test_legado_field_report.py`、
      `tests/test_source_url_import.py`（SSRF 全拒）、`tests/test_js_sandbox.py`、`tests/test_saferegex.py`、
      `tests/test_pipeline_decode_bytes.py`、`tests/test_sources_capabilities_ext.py`、`tests/test_source_import_config_contract.py`。
- [ ] **真机（能出网就必须真测）**：⚠️ **凡「重建 / 包装 HTTP 响应或流」的改动，必须拿真实地址核一次** ——
      第 94 期的 gzip 解两遍（`Content-Encoding` 未摘）就是这样漏过单测、只被真网抓到的（桩站正文从不压缩）。
      出网走本机代理（**仅当前开发机**，见 `docs/development-windows.md` §3）。
- [ ] **后台线程**：新增旁路线程必须进 `tests/conftest.py` 的 `_quiesce_background()` 收尾清单，否则全量后半程可能 segfault。
- [ ] **数据隔离**：碰库用例用 `isolated` 夹具 + `client`/`auth_headers`；环境变量必须在 **import 业务模块之前** 设。
- [ ] **文档**：`docs/roadmap-gaps-remaining.md` 写本期实施记录（最新期在文件末尾）；
      大文件改动后跑 `python tests/check_doc_anchors.py --drift` 并在文档里做「锚点披露」（硬错 0 / 疑似漂移保留，**历史行号不改写**）。
- [ ] **记忆（第 106 期起只有两处）**：`MEMORY.md` 的「逐期铁律索引」加**一行**（期号 + 一句话）；跨会话 / 领域知识进 `MEMORY-REF.md` 的**对应主题小节**（它不再按期号追加）。
      **不写**当日日志（`memory/YYYY-MM-DD.md` 已取消）、**不写**第二份实施记录；逐期全文存档 = `MEMORY-PERIODS.md`（只读）。
- [ ] **收尾落位与对账（第 107 期起，用户 m08782）**：机械的几处**别手改**，用
      `python tests/period_close.py new --period N --title "期标题" --numbers "总 passed skipped" --seconds S`
      （一次改完 roadmap 期段标题 / TODO 头部占位与 §2 一行索引 / §0 的 HEAD 链与基线句 / `AGENTS.md` §4 基线 /
      `MEMORY.md` 索引行；缺锚点或期号已被占用就**整体拒绝**，绝不改一半）。
      随后手写 roadmap 正文、TODO 头部那句话、索引行里的一句话，最后 `python tests/period_close.py check`（**只读**，R1–R8）**0 问题**才算收尾完。
- [ ] **工作区**：`git status` 无自有未提交改动；不顺手提交别人的改动。

## 5. 调试技巧（都踩过坑）

- **测量**：计时用 `curl`（`-w "%{time_total} %{size_download}"`）；**别用 PowerShell `Invoke-RestMethod`**（本机专属，见 `docs/development-windows.md` §3）。
- **日志**：pytest 全量落文件再读，别用 `grep` 猜；uvicorn 访问日志写 `RedirectStandardError` 指向的文件。
- **测试计数**：一律 `--junitxml` + 脚本解析；**前端用例数不与后端合并**（两套跑法两套前提）。
- **「长期稳定失败」= 产品 bug 症状**：逐层打印中间返回值找根因；e2e 做「改前 FAIL / 改后 PASS」对照。
- **浏览器冒烟**（**本机（Windows）专属**；环境与 `ui-smoke.ps1` 见 `docs/development-windows.md` §4）：
  - `playwright-cli open --browser=msedge "<url>?nc=<随机>"`（带 cache-bust，否则看到旧 bundle 误判「改动没生效」）；
  - ⚠️ **注入 `nf_token` 不稳**（首屏会 401 并清掉 token）⇒ **直接走登录表单**：填 `admin/changeme` 点「进入」；
  - 该外壳下 `getByRole` 常匹配不到 ⇒ 用 DOM 文本/DOM 遍历点按钮；`run-code` 传 JS 时**别用 `\"` 转义**（用 JS 单引号）；
  - 该沙箱里 `setTimeout` 可能缺失 ⇒ 竞态类验证改由 Vitest 钉。
- **Redis / PG 相关**：不配即关闭（行为与旧版一致）；测缓存那几条用 `NOVELFORGE_TEST_REDIS_URL`（独立 db）；测 PG 用 `NOVELFORGE_DB=pg NOVELFORGE_PG_DSN=... NOVELFORGE_PG_RESET=1`（**只对测试库**）。

## 6. 发布

- 镜像：`Dockerfile` 多阶段（`builder` 装 venv → `nodejs` 只借 node 二进制 → `frontend` 构建 Vue → `runtime` python-slim）；
  生产镜像**不含** `requirements-dev.txt`。
- **版本号**：唯一真值源 = **仓库根 `VERSION`**（约定「第 N 期 = V0.N.0」）。
  `server._read_version()` 读它 → `APP_VERSION` → 只由 `GET /health` 下发（**无 `/api/health`**）；
  `novelforge/__init__.py` 里的第二份 `__version__` 已在第 79 期删除 —— 别再引入版本字面量。
- 🚀 **发布自动化**（`.github/workflows/release.yml`，第 79 期起）：

  | 事件 | 行为 |
  |---|---|
  | 推送到 `main` | 读 `VERSION`：`v<版本>` tag **不存在** ⇒ 自动打 tag + 建 Release；已存在 ⇒ 跳过（版本没变） |
  | 推送 `v*` tag（人工补发） | 为那个 tag 建 Release（已存在则跳过） |

  notes 取 `CHANGELOG.md` 对应版本段，且**只经一个实现**：`python3 -X utf8 -m novelforge.core.changelog <版本>`
  （应用内「新功能」页读的是同一份数据 ⇒ 两处永远同源）。
  ⇒ **改了 `VERSION` 必须同批补 `CHANGELOG.md` 段**：缺段时该命令以 1 退出、发布在 CI 里失败
  （宁可失败，也不建一个空 notes 的 Release）；本地可用它自检：`python -m novelforge.core.changelog 0.79.0`。
  ⚠️ 打 tag 与建 Release 必须在**同一个 job** 里：用 `GITHUB_TOKEN` 推的 tag **不会**再触发别的 workflow。
- 镜像发布（CI）与 NAS 部署 / 更新命令见 `README.md` §Web 服务；⚠️ **切勿**新建 `docker-compose.override.yml`
  （Compose 会自动合并并静默改端口 / 禁拉取）。

## 7. 文档维护

| 文档 | 什么时候改 |
|---|---|
| `AGENTS.md` | 硬约束、同步点、常用命令、陷阱发生变化时 |
| `docs/TODO.md` | 开工/收尾（**只放「还没做的」**；完成的只留第 2 节一行索引，细节进 roadmap；补新发现，**每条带证据**） |
| `docs/DESIGN.md` | 视觉 token / 圆角档 / 字体 / 动效 / 组件范式变化时 |
| `docs/project-overview.md` | 定位、能力面、技术栈、部署形态、规模数字变化时 |
| `docs/architecture.md` | 新增 core 模块、数据流变化、不变量增减时 |
| `docs/user-guide.md` | 用户可见功能/入口/设置页变化时 |
| `docs/development.md`（本文） | 命令、回归清单、调试手法变化时 |
| `docs/component-api.md` | 组件 props/emit、store/lib 公共 API 变化时 |
| `docs/roadmap-gaps-remaining.md` | **每期**追加实施记录（活文档，最新在末尾） |
| `docs/development-windows.md` | **仅当前 Windows 开发机**的运行坑（nvm / 编码 / DNS / 代理 / 冒烟 / 端口）变化时；Linux / 容器读者**忽略该文件** |
| `scripts/`（`test.sh` / `frontend-verify.sh` / `dev-instance.sh` + 共用 `_lib.sh`） | 常用命令口径变化时 —— **先改脚本**（脚本是首选入口），本文表格与 `AGENTS.md` §4 跟着改；解释器探测 / 要清哪些变量只许有 `_lib.sh` 一份 |

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

## 9. 收尾落位与对账工具（第 107 期）

`tests/period_close.py`（**非 `test_` 前缀，pytest 不收集**；stdlib，无新依赖）：

```bash
python tests/period_close.py new --period 108 --title "期标题" --numbers "2340 2315 25" --seconds 329.85
python tests/period_close.py new --period 108 --title "期标题" --junit junit.xml   # 或用 junit 取数字
python tests/period_close.py new --period 108 --title "期标题" --dry-run          # 只看改哪几处
python tests/period_close.py check            # 只读对账 R1–R8（0 问题退 0）
python tests/period_close.py check --history  # 顺带列出历史豁免项（第 53–61 期）
python tests/period_close.py check --fix      # 只修版本字面量（= 仓库根 VERSION）
```

- **它做什么**：把「期段标题 / TODO 头部占位 / §2 一行索引 / §0 HEAD 链与基线 / `AGENTS.md` §4 基线 /
  `MEMORY.md` 索引行 / 去掉手记的『连续 N 轮未升版』」一次改完；`check` 负责三方对账（roadmap 期段 ↔
  `TODO` §2 ↔ `MEMORY.md` 索引）与口径检查，**唯一叙事仍在 roadmap**。
- **它不做什么**：不写叙事、不做「一句话提炼」、不碰 `MEMORY-PERIODS.md`（只读存档）、**不新建当日日志**。
- **为什么对账从第 107 期起才严判**：`TODO` §2 是第 62 期才开始记的 —— roadmap 的第 53–61 期**有期段却从没有过索引行**；
  而第 74 / 78 期反过来（§2 有行、roadmap 没有对应期段）。这两类历史差异若按今天的规则判，都得「补一条从没存在过的记录」= **编造**。
  ⇒ `STRICT_FROM = 107`，历史差异只出 warning（`check --history` 会列出来）。
- 契约见 `tests/test_period_records_contract.py`（32 例：每条规则都有「故意破坏 ⇒ 报错」用例，
  外加 `new` 幂等、整体拒绝、行尾 / BOM 保住、`check` 只读）。
- `R6` 管的是「`TODO` §2 必须是一行一期的表」：期号不重复、不许夹不以 `|` 开头的裸行（表尾脚注不算）、
  第 ≥107 期的行 ≤300 字符。它**第一次真跑就抓到一处既有缺陷**：第 105 期那行被吃掉 `| 105 | ` 前缀后
  整段掉进表格中间（1465 字符，把表格从那里截断）—— 这类事故**肉眼很难注意到**，是这条判据的主要价值。
